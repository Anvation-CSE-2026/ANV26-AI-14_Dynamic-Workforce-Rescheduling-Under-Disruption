"""Admin and employee operations on top of the repair core (mixed into ``ResQWork``).

    Repair Center         list / view / hide / show hidden / complete
    What-if simulation    assign X · move a shift · add one employee · accept a volunteer · second-best option
    Conflict assistant    type, severity, why, constraints, recommendation, alternatives, confidence, policy
    Workforce             staffing gaps · eligible-employee search · workforce requests · volunteers
    Admin requests        to an employee / department / role / several people / eligible people
    Notifications         3 levels + escalation (services.notify)
    Employees             add · edit · deactivate/reactivate · bulk import with one-time temporary passwords
    Schedule import       CSV/XLSX with validation and hard-constraint warnings
    Constraint Center     data-driven hard/soft rules (services.constraint_center)
    Rewards               completion-based rewards (services.rewards)

Nothing here changes the schedule without an explicit admin action, and every change goes through the
same hard-rule checks as the solver.
"""

from __future__ import annotations

import secrets
import string
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from analytics import fairness_engine
from core.models import Assignment, Contribution, Dataset, Department, Disruption, Employee, interval
from core.rules import schedule_violations

from . import constraint_center as cc
from . import importers, notify, rewards, workforce

VAULT_TTL_S = 15 * 60
ADMIN_REQUEST_TYPES = {
    "task": ("accept", "decline"), "shift_coverage": ("accept", "decline"),
    "availability_confirmation": ("accept", "decline"), "training": ("accept", "decline"),
    "schedule_confirmation": ("accept", "decline"), "general": ("acknowledge",),
    "emergency_coverage": ("accept", "decline"), "volunteer_opportunity": ("accept", "decline"),
}
ADMIN_REQUEST_SEVERITY = {"emergency_coverage": 3, "volunteer_opportunity": 2, "shift_coverage": 2, "task": 2,
                          "availability_confirmation": 2, "schedule_confirmation": 2, "training": 1, "general": 1}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _err(message: str, status: int = 400):
    from .workspace import ResQWorkError
    return ResQWorkError(message, status)


def temp_password(n: int = 12) -> str:
    """Readable but strong: letters + digits + one symbol, no look-alike characters."""
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "Il1O0o")
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n - 1)) + secrets.choice("!@#$%*?")
        if any(c.isdigit() for c in pw) and any(c.isupper() for c in pw) and any(c.islower() for c in pw):
            return pw


class OperationsMixin:
    store: Any

    # ------------------------------------------------------------ shared helpers

    def _vault(self) -> dict:
        v = self.__dict__.setdefault("_credential_vault", {})
        now = time.time()
        for k in [k for k, (exp, _) in v.items() if exp < now]:
            v.pop(k, None)
        return v

    def _contact(self, org: str, employee_id: str) -> tuple[dict, dict]:
        e = self.dataset(org).employee(employee_id)
        contact = {"email": e.email if e else None, "phone": e.phone if e else None}
        prof = self.store.get("profile", employee_id, org) or {}       # employee-editable contact + preferences
        contact["phone"] = prof.get("phone") or contact["phone"]
        prefs = prof.get("notification_preferences") or {}
        return contact, prefs

    def notify_employee(self, org: str, employee_id: str, severity: int, type: str, title: str, message: str,
                        requires_acknowledgement: Optional[bool] = None, extra: Optional[dict] = None) -> dict:
        e = self.dataset(org).employee(employee_id)
        contact, prefs = self._contact(org, employee_id)
        n = notify.create(self.store, org, employee_id=employee_id, employee_name=e.name if e else employee_id,
                          severity=severity, type=type, title=title, message=message, contact=contact, prefs=prefs,
                          requires_acknowledgement=requires_acknowledgement, extra=extra)
        self.audit(org, "NOTIFICATION_SENT", "ResQWork",
                   f"Level {severity} {type.replace('_', ' ')} to {n['employee_name']}: {title}",
                   notification_id=n["id"], channels=[c["channel"] for c in n["channels"]])
        return n

    def run_escalations(self, org: str, force: bool = False) -> list[dict]:
        ds = self.dataset(org)
        contacts = {e.id: self._contact(org, e.id)[0] for e in ds.employees}
        out = notify.escalate_due(self.store, org, contacts, force=force)
        for n in out:
            self.audit(org, "NOTIFICATION_ESCALATED", "ResQWork",
                       f"{n['employee_name']} hasn't acknowledged '{n['title']}': escalated to WhatsApp + SMS.",
                       notification_id=n["id"], previous=0, new=1)
        return out

    def _now_dt(self, ds: Dataset) -> datetime:
        return interval(ds.reference_date, ds.reference_time or "00:00", "23:59")[0] if ds.reference_date \
            else datetime.now()

    def _change_severity(self, ds: Dataset, shift_ids: list[str]) -> int:
        now = self._now_dt(ds)
        for sid in shift_ids:
            s = ds.shift(sid)
            if s and s.priority == "critical" and s.window[0] - now <= timedelta(hours=24):
                return 3
        return 2

    def _with_contributions(self, ds: Dataset, items: list[tuple[str, Any, str, str]]) -> list[Employee]:
        """Append dated contributions (employee, shift, kind, ref) to the fairness ledger."""
        add: dict[str, list[Contribution]] = {}
        for eid, shift, kind, ref in items:
            add.setdefault(eid, []).append(Contribution(date=shift.date, kind=kind, hours=shift.hours,
                                                        completed=False, ref=ref))
        out = []
        for e in ds.employees:
            if e.id in add:
                h = e.history.model_copy(update={"contributions": e.history.contributions + add[e.id]})
                e = e.model_copy(update={"history": h})
            out.append(e)
        return out

    def _publish(self, org: str, new_ds: Dataset, title: str, actor: str, changes: list[dict],
                 **extra: Any) -> dict:
        versions = self.store.list("version", org)
        parent = next((v for v in versions if v["status"] == "active"), None)
        tag = f"v1.{len(versions)}"
        for v in versions:
            if v["status"] == "active":
                v["status"] = "superseded"
                self.store.put("version", v["id"], org, v)
        version = {"id": tag, "tag": tag, "parent": parent["id"] if parent else None, "created_at": _now(),
                   "created_by": actor, "status": "active", "title": title[:200],
                   "assignments": [a.model_dump() for a in new_ds.existing_schedule], "changes": changes, **extra}
        self.store.put("version", tag, org, version)
        self._save_dataset(org, new_ds, version=tag)
        return version

    # ------------------------------------------------------------ Repair Center

    def repair_center(self, org: str, include_hidden: bool = False) -> dict:
        ds = self.dataset(org)
        shifts = {s.id: s for s in ds.shifts}
        elig = rewards.eligibilities(self.store, org)
        rows = []
        for p in self.store.list("proposal", org, limit=1000):
            r = p["result"]
            best = next((o for o in r["options"] if o["option_id"] == (p.get("approved_option")
                                                                       or r.get("recommended_option_id"))), None)
            mine = [x for x in elig if x.get("source_id") == p["id"]]
            completed = p["status"] == "approved" and (p.get("completed_at") is not None or
                                                       (bool(mine) and all(x["status"] != "pending_completion"
                                                                           for x in mine)))
            state = "completed" if completed else p["status"]
            affected = p.get("problem", {}).get("affected_shifts", [])
            critical = any(shifts.get(a["shift_id"]) is not None and shifts[a["shift_id"]].priority == "critical"
                           for a in affected)
            row = {"id": p["id"], "status": p["status"], "state": state, "hidden": bool(p.get("hidden")),
                   "created_at": p["created_at"], "decided_at": p.get("decided_at"), "decided_by": p.get("decided_by"),
                   "what_if": bool(p.get("parent_id")), "parent_id": p.get("parent_id"),
                   "problem": [i["title"] for i in p.get("problem", {}).get("items", [])],
                   "affected_shifts": len(affected), "critical": critical, "solver": r["solver"],
                   "result_status": r["status"], "options": len(r["options"]),
                   "recommended": best and {"label": best["label"], "title": best["title"],
                                            "changes": best["impact"]["assignments_changed"],
                                            "employees_affected": best["impact"]["employees_affected"],
                                            "overtime": best["impact"]["overtime_hours_added"],
                                            "impact": best["impact"]["impact_score"],
                                            "impact_level": best["impact"]["impact_level"],
                                            "fairness": best["fairness"]["fairness_score"]},
                   "unresolved": len(r.get("unresolved", [])), "completed_at": p.get("completed_at"),
                   "pending_completion": sum(1 for x in mine if x["status"] == "pending_completion")}
            rows.append(row)
        visible = [x for x in rows if include_hidden or not x["hidden"]]
        disruptions = [d for d in self.store.list("disruption", org) if d["status"] == "open"]
        crit_d = [d for d in disruptions if (d.get("disruption") or {}).get("severity") == "critical"
                  or any(shifts.get(s) is not None and shifts[s].priority == "critical" for s in d["affected_shifts"])]
        counts = {k: sum(1 for x in rows if x["state"] == k and not x["hidden"])
                  for k in ("pending", "approved", "completed", "rejected")}
        counts["hidden"] = sum(1 for x in rows if x["hidden"])
        counts["active_disruptions"] = len(disruptions)
        counts["critical_disruptions"] = len(crit_d)
        return {"repairs": visible, "counts": counts, "active_disruptions": disruptions,
                "critical_disruption_ids": [d["id"] for d in crit_d]}

    def set_repair_hidden(self, org: str, proposal_id: str, hidden: bool, actor: str) -> dict:
        p = self.proposal(org, proposal_id)
        before = bool(p.get("hidden"))
        p["hidden"] = hidden
        self.store.put("proposal", proposal_id, org, p)
        self.audit(org, "REPAIR_HIDDEN" if hidden else "REPAIR_RESTORED", actor,
                   f"Repair {proposal_id} {'hidden' if hidden else 'restored to the list'} (nothing deleted).",
                   proposal_id=proposal_id, previous=before, new=hidden)
        return {"id": proposal_id, "hidden": hidden}

    def complete_eligibility(self, org: str, eligibility_id: str, actor: str) -> dict:
        domain = self._ws(org)["domain"]
        try:
            e = rewards.complete(self.store, org, domain, eligibility_id, actor)
        except KeyError as exc:
            raise _err(str(exc).strip("'"), 404) from exc
        ds = self.dataset(org)
        emps = []
        for emp in ds.employees:                         # mark the ledger entry completed
            if emp.id == e["employee_id"]:
                contribs = [c.model_copy(update={"completed": True}) if c.ref == e["ref"] else c
                            for c in emp.history.contributions]
                emp = emp.model_copy(update={"history": emp.history.model_copy(update={"contributions": contribs})})
            emps.append(emp)
        self._save_dataset(org, ds.model_copy(update={"employees": emps}))
        if e["status"] == "rewarded":
            self.notify_employee(org, e["employee_id"], 1, "reward", f"+{e['points']} points: {e['task']}",
                                 "Thank you for completing this coverage. Your reward has been added to "
                                 "Rewards & Recognition.", requires_acknowledgement=False)
        self.audit(org, "ASSIGNMENT_COMPLETED", actor,
                   f"{e['employee_name']} completed {e['task']} on {e['date']}: reward {e['status'].replace('_', ' ')}.",
                   eligibility_id=e["id"], previous="pending_completion", new=e["status"])
        return e

    def complete_repair(self, org: str, proposal_id: str, actor: str) -> dict:
        p = self.proposal(org, proposal_id)
        if p["status"] != "approved":
            raise _err("Only an approved repair can be marked completed.", 409)
        done = [self.complete_eligibility(org, x["id"], actor) for x in rewards.eligibilities(self.store, org)
                if x.get("source_id") == proposal_id and x["status"] == "pending_completion"]
        p["completed_at"], p["completed_by"] = _now(), actor
        self.store.put("proposal", proposal_id, org, p)
        return {"proposal_id": proposal_id, "completed": done}

    # ------------------------------------------------------------ what-if simulation (never saved)

    def simulate(self, org: str, proposal_id: str, action: dict) -> dict:
        from engine.evaluate import evaluate, measure
        from engine.problem import build_problem
        from engine.repair import RepairResult, generate_repair
        prop = self.proposal(org, proposal_id)
        ds = self.dataset(org)
        result = RepairResult.model_validate(prop["result"])
        kind = action.get("type")
        best = next((o for o in result.options if o.option_id == result.recommended_option_id), None)
        names = {e.id: e.name for e in ds.employees}

        def workload(assign: dict[str, Optional[str]]) -> list[dict]:
            full = ds.assignment_map()
            for sid, eid in assign.items():
                if eid:
                    full[sid] = eid
                else:
                    full.pop(sid, None)
            before, after = {}, {}
            for sid, eid in ds.assignment_map().items():
                before[eid] = before.get(eid, 0) + ds.shift(sid).hours
            for sid, eid in full.items():
                after[eid] = after.get(eid, 0) + ds.shift(sid).hours
            return [{"employee_id": k, "employee_name": names.get(k, k), "before": round(before.get(k, 0), 2),
                     "after": round(after.get(k, 0), 2)}
                    for k in sorted(set(before) | set(after)) if round(before.get(k, 0), 2) != round(after.get(k, 0), 2)]

        base_fair = best.fairness.fairness_score if best else None
        if kind in ("assign", "accept_volunteer") and action.get("shift_id"):
            if best is None:
                raise _err("This repair has no option to start from.", 409)
            sid, eid = action["shift_id"], action.get("employee_id")
            if ds.employee(eid or "") is None:
                raise _err("Unknown employee", 404)
            p = build_problem(ds, result.disruptions)
            if sid not in p.slots:
                raise _err("That shift can't be changed (it has started or isn't part of this repair).", 409)
            assign = dict(best.assignment)
            for s in p.slots:
                assign.setdefault(s, p.original.get(s))
            assign[sid] = eid
            ev = evaluate(p, assign, full_check=True)
            imp, fair = measure(p, assign, ev)
            conflicts = [self._violation_text(v, names) for v in ev.violations]
            changes = [{"shift_id": x, "assignment": ds.shift(x).assignment, "date": ds.shift(x).date,
                        "start": ds.shift(x).start, "end": ds.shift(x).end,
                        "from": names.get(p.original.get(x) or "", None), "to": names.get(e or "", None)}
                       for x, e in assign.items() if p.original.get(x) != e]
            return {"type": kind, "feasible": not ev.violations, "conflicts_introduced": conflicts,
                    "constraints_affected": sorted({v["rule"] for v in ev.violations}),
                    "changes": changes, "changes_count": len(ev.changed_slots), "workload": workload(assign),
                    "fairness_before": base_fair, "fairness_after": fair.fairness_score,
                    "overtime_added": imp.overtime_hours_added, "impact": imp.impact_score,
                    "optimization_score": ev.cost, "baseline_score": best.cost,
                    "summary": (f"Assigning {names.get(eid)} is valid: {len(ev.changed_slots)} change(s), "
                                f"score {ev.cost:g} vs {best.cost:g} for the recommendation."
                                if not ev.violations else
                                f"Assigning {names.get(eid)} breaks {len(conflicts)} hard rule(s): " + "; ".join(conflicts[:2])),
                    "saved": False}
        if kind == "option":
            opt = next((o for o in result.options if o.option_id == action.get("option_id")), None)
            if opt is None or best is None:
                raise _err("Unknown option", 404)
            return {"type": kind, "feasible": opt.impact.unfilled_shifts == 0, "conflicts_introduced": [],
                    "constraints_affected": [], "changes": [c.model_dump() for c in opt.changes],
                    "changes_count": opt.impact.assignments_changed, "workload": workload(opt.assignment),
                    "fairness_before": base_fair, "fairness_after": opt.fairness.fairness_score,
                    "overtime_added": opt.impact.overtime_hours_added, "impact": opt.impact.impact_score,
                    "optimization_score": opt.cost, "baseline_score": best.cost,
                    "summary": f"{opt.label} ({opt.title}) vs {best.label}: {opt.impact.assignments_changed} vs "
                               f"{best.impact.assignments_changed} change(s), {opt.impact.overtime_hours_added:g}h vs "
                               f"{best.impact.overtime_hours_added:g}h overtime, fairness {opt.fairness.fairness_score:g} "
                               f"vs {best.fairness.fairness_score:g}.", "saved": False}
        if kind in ("move_shift", "add_employee"):
            trial = ds
            note = ""
            if kind == "move_shift":
                sid = action.get("shift_id")
                s = ds.shift(sid or "")
                if s is None:
                    raise _err("Unknown shift", 404)
                try:
                    moved = s.model_copy(update={"start": action["start"], "end": action["end"]})
                    moved = type(s).model_validate(moved.model_dump())
                except Exception as exc:  # noqa: BLE001
                    raise _err("start and end must be 24-hour HH:MM") from exc
                trial = ds.model_copy(update={"shifts": [moved if x.id == sid else x for x in ds.shifts]})
                note = f"{s.assignment} moved to {moved.start}–{moved.end}"
            else:
                need = sorted({q for sid in result.disrupted_shifts for q in (ds.shift(sid).required_skills
                                                                              + ds.shift(sid).required_certifications)})
                extra = Employee(id="__extra__", name="Additional employee", role="Additional staff",
                                 skills=list(action.get("skills") or need), department=None)
                trial = ds.model_copy(update={"employees": ds.employees + [extra]})
                names["__extra__"] = "Additional employee"
                note = "one additional qualified employee (" + (", ".join(extra.skills) or "no specific skill") + ")"
            res = generate_repair(trial, result.disruptions, strategies=["recommended"], with_baseline=False)
            o = res.options[0] if res.options else None
            return {"type": kind, "feasible": bool(o) and o.impact.unfilled_shifts == 0,
                    "conflicts_introduced": [] if o else res.infeasibility_reasons,
                    "constraints_affected": [], "changes": [c.model_dump() for c in o.changes] if o else [],
                    "changes_count": o.impact.assignments_changed if o else 0,
                    "workload": workload(o.assignment) if o else [],
                    "fairness_before": base_fair, "fairness_after": o.fairness.fairness_score if o else None,
                    "overtime_added": o.impact.overtime_hours_added if o else 0,
                    "impact": o.impact.impact_score if o else None, "optimization_score": o.cost if o else None,
                    "baseline_score": best.cost if best else None,
                    "summary": (f"With {note}: " + (f"{o.impact.assignments_changed} change(s), "
                                                    f"{o.impact.unfilled_shifts} uncovered, "
                                                    f"{o.impact.overtime_hours_added:g}h overtime."
                                                    if o else "still no valid repair.")),
                    "saved": False}
        raise _err("Unknown what-if action. Use assign, accept_volunteer, option, move_shift or add_employee.")

    @staticmethod
    def _violation_text(v: dict, names: dict) -> str:
        who = names.get(v.get("employee_id") or "", v.get("employee_id"))
        return {"ineligible": f"{who} isn't eligible ({str(v.get('reason', '')).replace('_', ' ').lower()})",
                "overlap": f"{who} would be double-booked", "rest": f"{who} would get too little rest",
                "daily_hours": f"{who} would exceed the daily hours limit",
                "weekly_hours": f"{who} would exceed the weekly hours limit",
                "unavailable": f"{who} is unavailable", "qualification": f"{who} lacks a required qualification",
                }.get(v["rule"], f"{who}: {v['rule']}")

    # ------------------------------------------------------------ AI conflict resolution assistant

    def conflict_assistant(self, org: str, use_ai: bool = True) -> dict:
        from engine.conflicts import detect_conflicts
        ds = self.dataset(org)
        open_d = self.open_disruptions(org)
        amap = ds.assignment_map()
        now = self._now_dt(ds)
        items: list[dict] = []
        for d in open_d:
            for s in ds.shifts:
                if amap.get(s.id) == d.employee_id and s.window[0] >= now \
                        and _overlaps(s.window, d.as_availability().window):
                    leave = (d.reason or "").lower() in ("leave", "vacation", "time off", "personal")
                    items.append({"type": "approved_leave" if leave else "unavailable", "employee_id": d.employee_id,
                                  "shift": s, "disruption_id": d.id,
                                  "why": f"{ds.employee(d.employee_id).name} "
                                         f"{'has approved leave' if leave else 'is unavailable'} on {d.date} "
                                         f"{(d.start or '00:00')}–{(d.end or '23:59')}"
                                         + (f" ({d.reason})" if d.reason else "") + f", which overlaps {s.assignment} "
                                         f"{s.start}–{s.end}.",
                                  "constraints": ["C001 Availability"]})
        for c in detect_conflicts(ds):
            if not c.repairable:
                continue
            sid = (list(c.release) or c.cover or [None])[0]
            s = ds.shift(sid) if sid else None
            if s is None:
                continue
            items.append({"type": c.type, "employee_id": c.employee_id, "shift": s, "conflict_id": c.id,
                          "why": c.message, "constraints": [_constraint_label(c.type)]})
        for g in workforce.staffing_gaps(ds, open_d):
            if any(i["shift"].id in g["shift_ids"] for i in items):
                continue
            items.append({"type": "staffing_gap", "employee_id": None, "gap": g,
                          "shift": ds.shift(g["shift_ids"][0]),
                          "why": f"{g['task']} on {g['date']} {g['start']}–{g['end']} needs {g['required']} people; "
                                 f"{g['assigned']} assigned. {g['gap']} more required.",
                          "constraints": ["C010 Minimum staffing"]})
        out = []
        cache = self.store.get("ai_cache", "conflicts", org) or {}
        policies_used = 0
        for i, it in enumerate(items):
            s = it["shift"]
            spec = {"date": s.date, "start": s.start, "end": s.end, "task": s.assignment,
                    "skills": s.required_skills, "certifications": s.required_certifications,
                    "location": s.location, "priority": s.priority, "needed": (it.get("gap") or {}).get("gap", 1)}
            exclude = tuple(x for x in [it.get("employee_id")] if x)
            assignments = {k: v for k, v in amap.items() if k != s.id} if it["type"] != "staffing_gap" else None
            found = workforce.find_candidates(ds, spec, open_d, exclude=exclude, assignments=assignments,
                                              ignore_shift=s.id)
            elig, inel = found["eligible"], found["ineligible"]
            hours_to_start = (s.window[0] - now).total_seconds() / 3600
            severity = ("critical" if s.priority == "critical" and (hours_to_start <= 24 or not elig) else
                        "high" if s.priority in ("critical", "high") or not elig or hours_to_start <= 24 else "medium")
            rec = elig[0] if elig else None
            checks = []
            if rec:
                checks = [{"label": c["name"], "status": "PASS"} for c in rec["checks"] if c["name"] != "Active account"]
                checks.append({"label": "Workload fairness",
                               "status": "GOOD" if all(n["status"] == "good" for n in rec["soft"][:1]) else "FAIR"})
                checks.append({"label": "Minimal schedule changes", "status": "PASS"})
            alternatives = [{"kind": "employee", "employee_id": c["employee_id"], "employee_name": c["employee_name"],
                             "rank": c["rank"], "tradeoffs": [n["detail"] for n in c["soft"] if n["status"] == "warn"]
                             or ["comparable"]} for c in elig[1:3]]
            alternatives += [{"kind": "split_shift", "label": "Split the shift between two eligible people"},
                             {"kind": "workforce_request", "label": "Request additional workforce"},
                             {"kind": "volunteers", "label": "Request volunteers from eligible employees"}]
            confidence = ("high" if len(elig) >= 2 and elig[1]["score"] - elig[0]["score"] >= 2 else
                          "medium" if elig else "low")
            label = _TYPE_LABEL.get(it["type"], it["type"].replace("_", " ").title())
            key = f"{it['type']}:{s.id}:{it.get('employee_id')}:{[c['employee_id'] for c in elig[:3]]}"
            policy = None
            if i < 6:
                try:
                    hits = self.policy_search(org, f"{label} {s.assignment} {' '.join(s.required_skills)}")
                    if hits["hits"]:
                        h = hits["hits"][0]
                        policy = {"citation": h["citation"], "text": h["text"][:400], "confidence": h["confidence"]}
                        policies_used += 1
                except Exception:  # noqa: BLE001 - policy context is optional
                    policy = None
            absent = ds.employee(it["employee_id"]).name if it.get("employee_id") and ds.employee(it["employee_id"]) else None
            facts = {"conflict": label, "employee_name": absent, "why": it["why"], "task": s.assignment, "date": s.date,
                     "start": s.start, "end": s.end,
                     "eligible": [{"id": c["employee_id"], "name": c["employee_name"], "rank": c["rank"],
                                   "overtime_hours": c["overtime_added"],
                                   "recent_load": c["fairness"]["contribution_load"]} for c in elig[:4]],
                     "ineligible": [{"id": c["employee_id"], "name": c["employee_name"],
                                     "failed": c["failed"]["name"] if c["failed"] else None} for c in inel[:6]],
                     "policy": policy["text"] if policy else None}
            advice = cache.get(key)
            if advice is None and use_ai and i < 5 and self.ai.provider is not None:
                advice = self.ai.conflict_advice(facts, [e.name for e in ds.employees])
                if advice is not None:
                    cache[key] = advice
            discarded = []
            if advice:
                eligible_ids = {c["employee_id"] for c in elig}
                discarded = [x for x in advice.get("suggested_employee_ids", []) if x not in eligible_ids]
                advice = {**advice, "suggested_employee_ids": [x for x in advice.get("suggested_employee_ids", [])
                                                               if x in eligible_ids]}
            who = ds.employee(it["employee_id"]).name if it.get("employee_id") and ds.employee(it["employee_id"]) else None
            recommendation = (f"Replace {who} with {rec['employee_name']}." if rec and who else
                              f"Assign {rec['employee_name']}." if rec else workforce.INSUFFICIENT)
            out.append({
                "id": f"cfx-{i + 1}", "type": it["type"], "type_label": label, "severity": severity,
                "employee_id": it.get("employee_id"), "employee_name": who, "task": s.assignment,
                "shift_id": s.id, "date": s.date, "start": s.start, "end": s.end, "priority": s.priority,
                "impact": {"shifts": 1 if it["type"] != "staffing_gap" else it["gap"]["gap"], "hours": s.hours,
                           "starts_in_hours": round(hours_to_start, 1), "critical": s.priority == "critical"},
                "why": it["why"], "constraints": it["constraints"],
                "recommendation": recommendation, "recommended": rec and {
                    "employee_id": rec["employee_id"], "employee_name": rec["employee_name"], "checks": checks,
                    "soft": rec["soft"], "fairness": rec["fairness"]},
                "alternatives": alternatives, "confidence": confidence,
                "eligible_count": len(elig), "funnel": found["funnel"],
                "rejected": [{"employee_name": c["employee_name"], "reason": c["failed"]["name"],
                              "detail": c["failed"]["detail"]} for c in inel if c["failed"]
                             and c["failed"]["name"] not in ("Required skill", "Certification", "Active account")][:5],
                "explanation": (advice or {}).get("summary") or _template_explanation(label, it["why"], rec, elig),
                "strategies": (advice or {}).get("strategies") or _template_strategies(elig, it["type"]),
                "explained_by": (f"{advice['provider']} ({advice['prompt']})" if advice else "template (facts only)"),
                "ai_discarded": discarded, "policy": policy,
                "disruption_id": it.get("disruption_id"), "conflict_id": it.get("conflict_id"),
                "gap": it.get("gap")})
        self.store.put("ai_cache", "conflicts", org, cache)
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        out.sort(key=lambda x: (order[x["severity"]], x["date"], x["start"]))
        return {"conflicts": out, "count": len(out),
                "critical": sum(1 for x in out if x["severity"] == "critical"),
                "llm": self.ai.provider.name if self.ai.provider else None, "policies_used": policies_used,
                "note": "Suggestions are pre-checked against every hard constraint. The optimizer (CP-SAT) "
                        "confirms the final repair when you generate it."}

    # ------------------------------------------------------------ workforce

    def staffing_gaps(self, org: str) -> list[dict]:
        return workforce.staffing_gaps(self.dataset(org), self.open_disruptions(org))

    def find_employees(self, org: str, spec: dict) -> dict:
        try:
            clean = workforce.validate_request({**spec, "task": spec.get("task") or "Coverage",
                                                "additional_needed": spec.get("needed") or spec.get("additional_needed") or 1})
        except ValueError as exc:
            raise _err(str(exc)) from exc
        return workforce.find_candidates(self.dataset(org), workforce.as_spec(clean), self.open_disruptions(org))

    def create_workforce_request(self, org: str, body: dict, actor: str) -> dict:
        try:
            req = workforce.validate_request(dict(body))
        except ValueError as exc:
            raise _err(str(exc)) from exc
        found = workforce.find_candidates(self.dataset(org), workforce.as_spec(req), self.open_disruptions(org))
        doc = {"id": _id("wfr"), **req, "status": "open", "created_by": actor, "created_at": _now(),
               "updated_at": _now(), "invited": [], "volunteers": [], "assignments": [],
               "eligible_count": len(found["eligible"]), "sufficient": found["sufficient"],
               "message": found["message"], "history": [{"at": _now(), "by": actor, "event": "created"}]}
        self.store.put("workforce_request", doc["id"], org, doc)
        self.audit(org, "WORKFORCE_REQUESTED", actor,
                   f"Additional workforce requested: {req['additional_needed']} for {req['task']} on {req['date']} "
                   f"{req['start']}–{req['end']} ({len(found['eligible'])} eligible).", workforce_request_id=doc["id"],
                   new={"needed": req["additional_needed"], "skills": req["skills"]}, reason=req["reason"] or None)
        return {**doc, "candidates": found}

    def workforce_requests(self, org: str) -> list[dict]:
        return self.store.list("workforce_request", org)

    def workforce_request(self, org: str, wid: str, with_candidates: bool = True) -> dict:
        doc = self.store.get("workforce_request", wid, org)
        if not doc:
            raise _err("Unknown workforce request", 404)
        if with_candidates:
            assigned = tuple(a["employee_id"] for a in doc["assignments"])
            doc = {**doc, "candidates": workforce.find_candidates(self.dataset(org), workforce.as_spec(doc),
                                                                  self.open_disruptions(org), exclude=assigned)}
        return doc

    def _save_wfr(self, org: str, doc: dict, event: str, actor: str) -> dict:
        doc = {k: v for k, v in doc.items() if k != "candidates"}
        filled = len([a for a in doc["assignments"]])
        if doc["status"] not in ("cancelled",):
            doc["status"] = "filled" if filled >= doc["additional_needed"] else (
                "partially_filled" if filled else "open")
        doc["updated_at"] = _now()
        doc["history"].append({"at": _now(), "by": actor, "event": event})
        self.store.put("workforce_request", doc["id"], org, doc)
        return doc

    def request_volunteers(self, org: str, wid: str, mode: str, actor: str) -> dict:
        """mode: volunteers (top eligible) · broadcast (every eligible person) · escalate (critical, all channels)."""
        if mode not in ("volunteers", "broadcast", "escalate"):
            raise _err("mode must be volunteers, broadcast or escalate")
        doc = self.workforce_request(org, wid)
        elig = doc["candidates"]["eligible"]
        if not elig:
            raise _err(workforce.INSUFFICIENT + " Nobody passes every hard constraint for this request.", 409)
        n = max(3, 2 * doc["additional_needed"]) if mode == "volunteers" else len(elig)
        targets = [c for c in elig if c["employee_id"] not in doc["invited"]][:n]
        if not targets:
            raise _err("Every eligible employee has already been invited.", 409)
        sev = 3 if mode == "escalate" or doc.get("emergency") or doc["priority"] == "critical" else 2
        rq = self.create_admin_request(org, {
            "type": "emergency_coverage" if sev == 3 else "volunteer_opportunity",
            "title": f"Coverage opportunity: {doc['task']}",
            "message": f"{doc['task']} · {doc['date']} {doc['start']}–{doc['end']}"
                       + (f" · {doc['location']}" if doc.get("location") else "")
                       + (f" · needs {', '.join(doc['skills'])}" if doc["skills"] else "")
                       + ". Volunteering doesn't assign you: an admin confirms first.",
            "target": {"kind": "employees", "value": [c["employee_id"] for c in targets]}, "severity": sev,
            "workforce_request_id": wid}, actor)
        doc["invited"] = sorted(set(doc["invited"]) | {c["employee_id"] for c in targets})
        doc.setdefault("admin_request_ids", []).append(rq["id"])
        if mode == "escalate":
            doc["priority"] = "critical"
        doc = self._save_wfr(org, doc, f"{mode}: {len(targets)} eligible employee(s) notified", actor)
        self.audit(org, "VOLUNTEERS_REQUESTED", actor,
                   f"{len(targets)} eligible employee(s) invited to volunteer for {doc['task']} ({mode}); "
                   "ineligible employees were not contacted.", workforce_request_id=wid)
        return {"request": doc, "invited": [c["employee_name"] for c in targets], "admin_request": rq}

    def volunteer(self, org: str, wid: str, employee_id: str, accept: bool) -> dict:
        doc = self.workforce_request(org, wid)
        if employee_id not in doc["invited"]:
            raise _err("This opportunity wasn't offered to you.", 403)
        if doc["status"] in ("filled", "cancelled"):
            raise _err(f"This request is already {doc['status']}.", 409)
        me = next((c for c in doc["candidates"]["eligible"] + doc["candidates"]["ineligible"]
                   if c["employee_id"] == employee_id), None)
        vols = [v for v in doc["volunteers"] if v["employee_id"] != employee_id]
        name = self.dataset(org).employee(employee_id).name
        entry = {"employee_id": employee_id, "employee_name": name, "at": _now(),
                 "status": "volunteered" if accept else "declined",
                 "eligible": bool(me and me["eligible"]),
                 "validation": me["failed"]["detail"] if me and me["failed"] else "passes every hard constraint",
                 "rank": me.get("rank") if me else None}
        doc["volunteers"] = vols + [entry]
        doc = self._save_wfr(org, doc, f"{name} {'volunteered' if accept else 'declined'}", name)
        self.audit(org, "VOLUNTEERED" if accept else "VOLUNTEER_DECLINED", name,
                   f"{name} {'volunteered for' if accept else 'declined'} {doc['task']} on {doc['date']} "
                   "(no assignment and no reward until an admin approves and the work is completed).",
                   workforce_request_id=wid)
        return doc

    def decide_volunteer(self, org: str, wid: str, employee_id: str, approve: bool, actor: str) -> dict:
        doc = self.workforce_request(org, wid)
        v = next((x for x in doc["volunteers"] if x["employee_id"] == employee_id and x["status"] == "volunteered"), None)
        if v is None:
            raise _err("This person hasn't volunteered for this request.", 404)
        if not approve:
            v["status"] = "not_selected"
            self.notify_employee(org, employee_id, 1, "volunteer", f"Thanks for volunteering: {doc['task']}",
                                 "The admin has filled this one another way. Thank you for offering.",
                                 requires_acknowledgement=False)
            return self._save_wfr(org, doc, f"{v['employee_name']} not selected", actor)
        return self.assign_from_request(org, wid, employee_id, actor, volunteer=True)

    def assign_from_request(self, org: str, wid: str, employee_id: str, actor: str, volunteer: bool = False) -> dict:
        doc = self.workforce_request(org, wid)
        if doc["status"] in ("filled", "cancelled"):
            raise _err(f"This request is already {doc['status']}.", 409)
        cand = next((c for c in doc["candidates"]["eligible"] if c["employee_id"] == employee_id), None)
        if cand is None:
            bad = next((c for c in doc["candidates"]["ineligible"] if c["employee_id"] == employee_id), None)
            raise _err(f"Can't assign: {bad['failed']['name'].lower()}: {bad['failed']['detail']}." if bad and bad["failed"]
                       else "Can't assign this person.", 409)
        ds = self.dataset(org)
        e = ds.employee(employee_id)
        n = len(doc["assignments"]) + 1
        shift = workforce.spec_shift(workforce.as_spec(doc), f"{workforce.slug(doc['task'])}-{doc['id'][-4:]}-{n}")
        shift = shift.model_copy(update={"department": doc.get("department") or e.department,
                                         "attributes": {"workforce_request": wid, "additional": True}})
        kind = "emergency" if doc.get("emergency") else ("volunteer" if volunteer else "additional")
        ref = f"{wid}:{employee_id}"
        employees = self._with_contributions(ds, [(employee_id, shift, kind, ref)])
        new_ds = ds.model_copy(update={"shifts": ds.shifts + [shift], "employees": employees,
                                       "existing_schedule": ds.existing_schedule + [Assignment(shift_id=shift.id,
                                                                                                employee_id=employee_id)]})
        bad = [v for v in schedule_violations(new_ds, new_ds.assignment_map()) if
               v.get("shift_id") == shift.id or shift.id in v.get("shift_ids", []) or
               (v["rule"] in ("daily_hours", "weekly_hours") and v["employee_id"] == employee_id)]
        if bad:
            raise _err("Hard-constraint check failed at assignment time: " + bad[0]["rule"].replace("_", " "), 409)
        version = self._publish(org, new_ds, f"Additional workforce: {e.name} → {doc['task']} {doc['date']} "
                                             f"{doc['start']}–{doc['end']}", actor,
                                [{"shift_id": shift.id, "date": shift.date, "start": shift.start, "end": shift.end,
                                  "assignment": shift.assignment, "from_employee_id": None, "from_employee_name": None,
                                  "to_employee_id": employee_id, "to_employee_name": e.name, "kind": "filled"}],
                                workforce_request_id=wid)
        for v in doc["volunteers"]:
            if v["employee_id"] == employee_id:
                v["status"] = "approved"
        doc["assignments"].append({"employee_id": employee_id, "employee_name": e.name, "shift_id": shift.id,
                                   "status": "assigned", "assigned_at": _now(), "completed_at": None,
                                   "volunteer": volunteer, "rank": cand.get("rank")})
        elig = rewards.register(self.store, org, employee_id=employee_id, employee_name=e.name,
                                trigger=rewards.trigger_for(doc["priority"], doc.get("emergency"), volunteer),
                                ref=ref, shift_id=shift.id, date=shift.date, end=shift.end, task=doc["task"],
                                source="workforce", source_id=wid, critical=doc["priority"] == "critical")
        doc["assignments"][-1]["eligibility_id"] = elig["id"]
        doc = self._save_wfr(org, doc, f"{e.name} assigned ({'volunteer' if volunteer else 'direct'})", actor)
        sev = 3 if doc.get("emergency") or doc["priority"] == "critical" else 2
        self.notify_employee(org, employee_id, sev, "assignment", f"New assignment: {doc['task']} {doc['date']}",
                             f"You're assigned to {doc['task']} on {doc['date']} {doc['start']}–{doc['end']}"
                             + (f" at {doc['location']}" if doc.get("location") else "") + ". Please acknowledge.",
                             extra={"version": version["tag"], "workforce_request_id": wid,
                                    "changes": [{"shift_id": shift.id, "date": shift.date, "start": shift.start,
                                                 "end": shift.end, "assignment": shift.assignment,
                                                 "change_type": "assigned"}]})
        self.audit(org, "WORKFORCE_ASSIGNED", actor,
                   f"{e.name} assigned to {doc['task']} on {doc['date']} {doc['start']}–{doc['end']} "
                   f"({'approved volunteer' if volunteer else 'direct assignment'}); schedule {version['tag']}.",
                   workforce_request_id=wid, previous=None, new={"employee": e.name, "shift_id": shift.id})
        return doc

    def complete_workforce_assignment(self, org: str, wid: str, employee_id: str, actor: str) -> dict:
        doc = self.workforce_request(org, wid, with_candidates=False)
        a = next((x for x in doc["assignments"] if x["employee_id"] == employee_id), None)
        if a is None:
            raise _err("No assignment for this person on this request.", 404)
        if a["status"] == "completed":
            return doc
        a["status"], a["completed_at"] = "completed", _now()
        if a.get("eligibility_id"):
            self.complete_eligibility(org, a["eligibility_id"], actor)
        return self._save_wfr(org, doc, f"{a['employee_name']} completed the assignment", actor)

    def cancel_workforce_request(self, org: str, wid: str, actor: str) -> dict:
        doc = self.workforce_request(org, wid, with_candidates=False)
        doc["status"] = "cancelled"
        self.audit(org, "WORKFORCE_CANCELLED", actor, f"Workforce request for {doc['task']} cancelled.",
                   workforce_request_id=wid, previous="open", new="cancelled")
        return self._save_wfr(org, doc, "cancelled", actor)

    # ------------------------------------------------------------ admin requests

    def create_admin_request(self, org: str, body: dict, actor: str) -> dict:
        rtype = body.get("type", "general")
        if rtype not in ADMIN_REQUEST_TYPES:
            raise _err(f"type must be one of {', '.join(ADMIN_REQUEST_TYPES)}")
        title = str(body.get("title") or "").strip()[:140]
        message = str(body.get("message") or "").strip()[:2000]
        if not title:
            raise _err("title is required")
        ds = self.dataset(org)
        active = [e for e in ds.employees if e.status == "active"]
        target = body.get("target") or {}
        kind, value = target.get("kind"), target.get("value")
        if kind == "employee":
            ids = [value] if isinstance(value, str) else []
        elif kind == "employees":
            ids = [v for v in (value or []) if isinstance(v, str)]
        elif kind == "department":
            ids = [e.id for e in active if (e.department or "").lower() == str(value or "").lower()]
        elif kind == "role":
            ids = [e.id for e in active if e.role.lower() == str(value or "").lower()]
        elif kind == "eligible":
            spec = value if isinstance(value, dict) else {}
            try:
                clean = workforce.validate_request({**spec, "task": spec.get("task") or title, "additional_needed": 1})
            except ValueError as exc:
                raise _err(f"eligible target needs date, start and end: {exc}") from exc
            found = workforce.find_candidates(ds, workforce.as_spec(clean), self.open_disruptions(org))
            ids = [c["employee_id"] for c in found["eligible"]]
        else:
            raise _err("target.kind must be employee, employees, department, role or eligible")
        known = {e.id: e for e in active}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise _err(f"Unknown or inactive employee(s): {', '.join(unknown)}", 404)
        if not ids:
            raise _err("Nobody matches that target.", 404)
        sev = int(body.get("severity") or ADMIN_REQUEST_SEVERITY[rtype])
        if sev not in (1, 2, 3):
            raise _err("severity must be 1, 2 or 3")
        doc = {"id": _id("arq"), "type": rtype, "title": title, "message": message, "severity": sev,
               "target": {"kind": kind, "value": value}, "actions": list(ADMIN_REQUEST_TYPES[rtype]),
               "workforce_request_id": body.get("workforce_request_id"), "due": body.get("due"),
               "status": "open", "created_by": actor, "created_at": _now(), "updated_at": _now(),
               "recipients": [{"employee_id": i, "employee_name": known[i].name, "status": "pending",
                               "responded_at": None, "note": None, "notification_id": None} for i in dict.fromkeys(ids)]}
        for r in doc["recipients"]:
            n = self.notify_employee(org, r["employee_id"], sev, rtype, title, message or title,
                                     requires_acknowledgement=sev >= 2, extra={"admin_request_id": doc["id"]})
            r["notification_id"] = n["id"]
        self.store.put("admin_request", doc["id"], org, doc)
        self.audit(org, "ADMIN_REQUEST_CREATED", actor,
                   f"{rtype.replace('_', ' ').title()} request '{title}' sent to {len(doc['recipients'])} employee(s).",
                   admin_request_id=doc["id"], new={"target": doc["target"], "severity": sev})
        return doc

    def admin_requests(self, org: str, employee_id: Optional[str] = None) -> list[dict]:
        rows = self.store.list("admin_request", org)
        if employee_id is None:
            return rows
        out = []
        for r in rows:
            mine = next((x for x in r["recipients"] if x["employee_id"] == employee_id), None)
            if mine:
                out.append({**{k: v for k, v in r.items() if k != "recipients"}, "my_status": mine["status"],
                            "responded_at": mine["responded_at"], "recipient_count": len(r["recipients"])})
        return out

    def respond_admin_request(self, org: str, rid: str, employee_id: str, action: str, note: str = "") -> dict:
        r = self.store.get("admin_request", rid, org)
        if not r:
            raise _err("Unknown request", 404)
        me = next((x for x in r["recipients"] if x["employee_id"] == employee_id), None)
        if me is None:
            raise _err("This request wasn't sent to you.", 403)
        if action not in r["actions"]:
            raise _err(f"This request can be: {', '.join(r['actions'])}")
        if r["status"] == "closed":
            raise _err("This request is closed.", 409)
        before = me["status"]
        me["status"] = {"accept": "accepted", "decline": "declined", "acknowledge": "acknowledged"}[action]
        me["responded_at"], me["note"] = _now(), note.strip()[:500] or None
        if all(x["status"] != "pending" for x in r["recipients"]):
            r["status"] = "completed"
        r["updated_at"] = _now()
        self.store.put("admin_request", rid, org, r)
        if me.get("notification_id"):
            n = self.store.get("notification", me["notification_id"], org)
            if n:
                notify.acknowledge(self.store, org, n)
        if r.get("workforce_request_id"):
            self.volunteer(org, r["workforce_request_id"], employee_id, accept=action == "accept")
        self.audit(org, "ADMIN_REQUEST_" + me["status"].upper(), me["employee_name"],
                   f"{me['employee_name']} {me['status']} '{r['title']}'.", admin_request_id=rid,
                   previous=before, new=me["status"], reason=me["note"])
        return r

    def close_admin_request(self, org: str, rid: str, actor: str) -> dict:
        r = self.store.get("admin_request", rid, org)
        if not r:
            raise _err("Unknown request", 404)
        r["status"], r["updated_at"] = "closed", _now()
        self.store.put("admin_request", rid, org, r)
        self.audit(org, "ADMIN_REQUEST_CLOSED", actor, f"Request '{r['title']}' closed.", admin_request_id=rid)
        return r

    # ------------------------------------------------------------ employees

    def employee_directory(self, org: str) -> list[dict]:
        ds = self.dataset(org)
        amap = ds.assignment_map()
        count: dict[str, int] = {}
        for eid in amap.values():
            count[eid] = count.get(eid, 0) + 1
        return [{**e.model_dump(exclude={"history"}), "shifts": count.get(e.id, 0),
                 "fairness": fairness_engine.profile(ds, e)} for e in ds.employees]

    def update_employee(self, org: str, employee_id: str, patch: dict, actor: str) -> dict:
        ds = self.dataset(org)
        e = ds.employee(employee_id)
        if e is None:
            raise _err("Unknown employee", 404)
        allowed = {"name", "email", "phone", "department", "role", "skills", "certifications", "location",
                   "max_daily_hours", "contracted_weekly_hours", "max_weekly_hours"}
        bad = set(patch) - allowed
        if bad:
            raise _err(f"Can't change: {', '.join(sorted(bad))}")
        data = e.model_dump()
        before = {k: data[k] for k in patch}
        for k, v in patch.items():
            data[k] = [x.strip() for x in v.split(",") if x.strip()] if k in ("skills", "certifications") \
                and isinstance(v, str) else v
        if data.get("email") and not importers._EMAIL.match(str(data["email"])):
            raise _err("email is not valid")
        try:
            new_e = Employee.model_validate(data)
        except Exception as exc:  # noqa: BLE001 - surface pydantic's message
            raise _err(f"Invalid employee data: {exc.errors()[0]['msg'] if hasattr(exc, 'errors') else exc}") from exc
        self._save_dataset(org, ds.model_copy(update={"employees": [new_e if x.id == employee_id else x
                                                                     for x in ds.employees]}))
        self.audit(org, "EMPLOYEE_UPDATED", actor, f"{e.name}'s profile updated: {', '.join(sorted(patch))}.",
                   employee_id=employee_id, previous=before, new={k: new_e.model_dump()[k] for k in patch})
        return new_e.model_dump()

    def set_employee_status(self, org: str, employee_id: str, status: str, actor: str, reason: str = "") -> dict:
        if status not in ("active", "inactive"):
            raise _err("status must be active or inactive")
        ds = self.dataset(org)
        e = ds.employee(employee_id)
        if e is None:
            raise _err("Unknown employee", 404)
        if e.status == status:
            return {"employee": e.model_dump(), "disruptions": []}
        new_e = e.model_copy(update={"status": status})
        self._save_dataset(org, ds.model_copy(update={"employees": [new_e if x.id == employee_id else x
                                                                     for x in ds.employees]}))
        created = []
        if status == "inactive":                        # their future shifts need cover: open a disruption per day
            now = self._now_dt(ds)
            days = sorted({s.date for s in ds.shifts if ds.assignment_map().get(s.id) == employee_id
                           and s.window[0] >= now})
            for d in days:
                out = self.report_disruption(org, structured={"employee_id": employee_id, "date": d,
                                                              "reason": "deactivated", "severity": "high",
                                                              "label": f"{e.name} deactivated"}, actor=actor)
                created += [r["id"] for r in out["disruptions"]]
        self.audit(org, "EMPLOYEE_" + ("DEACTIVATED" if status == "inactive" else "REACTIVATED"), actor,
                   f"{e.name} {'deactivated' if status == 'inactive' else 'reactivated'}"
                   + (f"; {len(created)} day(s) of shifts need cover" if created else "") + ".",
                   employee_id=employee_id, previous=e.status, new=status, reason=reason or None)
        return {"employee": new_e.model_dump(), "disruptions": created}

    def preview_employee_import(self, org: str, filename: str, data: bytes, emails: set[str], actor: str) -> dict:
        try:
            rows = importers.read_table(filename, data)
        except importers.ImportError_ as exc:
            raise _err(str(exc)) from exc
        if not rows:
            raise _err("The file has no rows.")
        report = importers.validate_employees(self.dataset(org), rows, emails)
        job = {"id": _id("imp"), "kind": "employees", "filename": filename, "status": "preview", "created_at": _now(),
               "created_by": actor, "report": report}
        self.store.put("import_job", job["id"], org, job)
        return job

    def confirm_employee_import(self, org: str, job_id: str, auth, emails: set[str], actor: str) -> dict:
        job = self.store.get("import_job", job_id, org)
        if not job or job["kind"] != "employees":
            raise _err("Unknown import", 404)
        if job["status"] != "preview":
            raise _err("This import was already confirmed.", 409)
        ds = self.dataset(org)
        rows = [r for r in job["report"]["rows"] if r["status"] == "valid"]
        recheck = importers.validate_employees(ds, [_row_back(r["data"]) for r in rows], emails)
        rows = [r for r, chk in zip(rows, recheck["rows"]) if chk["status"] == "valid"]
        if not rows:
            raise _err("No new valid employees to create.", 409)
        new_emps = [importers.build_employee(r["data"]) for r in rows]
        depts = list(ds.departments)
        known = {d.id.lower() for d in depts} | {d.name.lower() for d in depts}
        for e in new_emps:
            if e.department and e.department.lower() not in known:
                depts.append(Department(id=e.department, name=e.department))
                known.add(e.department.lower())
        avail = list(ds.availability)
        dates = importers.horizon_dates(ds)
        for r, e in zip(rows, new_emps):
            if r["data"].get("availability_start"):
                avail += importers.availability_window(e.id, r["data"]["availability_start"],
                                                       r["data"]["availability_end"], dates)
        self._save_dataset(org, ds.model_copy(update={"employees": ds.employees + new_emps, "departments": depts,
                                                      "availability": avail}))
        creds, skipped = [], []
        for e in new_emps:
            if not e.email:
                continue
            pw = temp_password()
            try:
                auth.create_employee_account(e.email, pw, e.name, org, e.id)
                creds.append([e.id, e.name, e.email, pw, "created - change password at first login"])
            except Exception as exc:  # noqa: BLE001 - e.g. the email already has an account elsewhere
                skipped.append({"employee_id": e.id, "reason": str(exc)})
                creds.append([e.id, e.name, e.email, "", f"no login created: {exc}"])
        token = secrets.token_urlsafe(24)
        self._vault()[token] = (time.time() + VAULT_TTL_S, creds)
        job.update(status="confirmed", confirmed_at=_now(), created=[e.id for e in new_emps],
                   accounts=len(creds) - len(skipped))
        self.store.put("import_job", job_id, org, job)
        self.audit(org, "EMPLOYEES_IMPORTED", actor,
                   f"{len(new_emps)} employee(s) imported from {job['filename']} "
                   f"({job['report']['invalid']} invalid, {job['report']['duplicates']} duplicate, "
                   f"{job['report']['existing']} existing rows not imported). Temporary passwords issued once.",
                   import_id=job_id, new=[e.id for e in new_emps])
        return {"created": [e.model_dump(exclude={"history"}) for e in new_emps], "accounts": job["accounts"],
                "skipped_accounts": skipped, "credentials_token": token, "expires_in_s": VAULT_TTL_S,
                "report": job["report"]}

    def take_credentials(self, token: str) -> bytes:
        """One-time download of the temporary-password workbook; the plaintext is then gone."""
        from core import xlsx
        item = self._vault().pop(token, None)
        if item is None:
            raise _err("This download has expired or was already used. Reset passwords individually instead.", 410)
        return xlsx.write([["employee_id", "name", "email", "temporary_password", "status"], *item[1]],
                          "Temporary passwords")

    @staticmethod
    def login_email(org: str, e: Employee) -> str:
        """The employee's sign-in: their email, or a generated login ID when the data has no email."""
        import re as _re
        return (e.email or f"{_re.sub(r'[^a-z0-9]+', '', e.id.lower())}@{_re.sub(r'[^a-z0-9-]+', '', org.lower())}.resqwork").lower()

    def create_employee_logins(self, org: str, auth, actor: str) -> dict:
        """Give every active employee without an account a login with a one-time temporary password."""
        rows, created = [], 0
        for e in self.dataset(org).employees:
            if e.status != "active":
                continue
            email = self.login_email(org, e)
            if auth.get(email):
                continue
            pw = temp_password()
            auth.create_employee_account(email, pw, e.name, org, e.id)
            rows.append([e.id, e.name, email, pw, "created - change password at first login"])
            created += 1
        if not created:
            raise _err("Every active employee already has a login. Use Reset to issue a new temporary password.", 409)
        token = secrets.token_urlsafe(24)
        self._vault()[token] = (time.time() + VAULT_TTL_S, rows)
        self.audit(org, "EMPLOYEE_LOGINS_CREATED", actor, f"Logins created for {created} employee(s); temporary passwords issued once.")
        return {"created": created, "credentials_token": token, "expires_in_s": VAULT_TTL_S}

    def reset_employee_password(self, org: str, employee_id: str, auth, actor: str) -> dict:
        e = self.dataset(org).employee(employee_id)
        if e is None:
            raise _err("Unknown employee", 404)
        email = self.login_email(org, e)
        pw = temp_password()
        auth.create_employee_account(email, pw, e.name, org, e.id, reset=bool(auth.get(email)))
        token = secrets.token_urlsafe(24)
        self._vault()[token] = (time.time() + VAULT_TTL_S, [[e.id, e.name, email, pw, "temporary - change at login"]])
        self.audit(org, "PASSWORD_RESET", actor, f"Temporary password issued for {e.name}.", employee_id=employee_id)
        return {"credentials_token": token, "expires_in_s": VAULT_TTL_S}

    def add_employee(self, org: str, data: dict, auth, emails: set[str], actor: str) -> dict:
        report = importers.validate_employees(self.dataset(org), [data], emails)
        row = report["rows"][0]
        if row["status"] != "valid":
            raise _err("; ".join(row["errors"] or row["warnings"]) or f"Row is {row['status']}", 409
                       if row["status"] in ("existing", "duplicate") else 400)
        job = {"id": _id("imp"), "kind": "employees", "filename": "manual entry", "status": "preview",
               "created_at": _now(), "created_by": actor, "report": report}
        self.store.put("import_job", job["id"], org, job)
        return self.confirm_employee_import(org, job["id"], auth, emails, actor)

    def preview_schedule_import(self, org: str, filename: str, data: bytes, actor: str) -> dict:
        try:
            rows = importers.read_table(filename, data)
        except importers.ImportError_ as exc:
            raise _err(str(exc)) from exc
        if not rows:
            raise _err("The file has no rows.")
        report = importers.validate_schedule(self.dataset(org), rows)
        job = {"id": _id("imp"), "kind": "schedule", "filename": filename, "status": "preview", "created_at": _now(),
               "created_by": actor, "report": report}
        self.store.put("import_job", job["id"], org, job)
        return job

    def confirm_schedule_import(self, org: str, job_id: str, include_warnings: bool, actor: str) -> dict:
        job = self.store.get("import_job", job_id, org)
        if not job or job["kind"] != "schedule":
            raise _err("Unknown import", 404)
        if job["status"] != "preview":
            raise _err("This import was already confirmed.", 409)
        ds = self.dataset(org)
        rows = [r for r in job["report"]["rows"] if r["status"] == "valid"
                and (include_warnings or not r.get("hard_warning"))]
        recheck = importers.validate_schedule(ds, [_sched_back(r["data"]) for r in rows])
        rows = [r for r, chk in zip(rows, recheck["rows"]) if chk["status"] == "valid"]
        if not rows:
            raise _err("No rows to import (rows with hard-constraint warnings need 'import rows with warnings').", 409)
        shifts, assigns = importers.schedule_rows_to_dataset(ds, rows)
        new_ds = ds.model_copy(update={"shifts": ds.shifts + shifts, "existing_schedule": ds.existing_schedule + assigns})
        version = self._publish(org, new_ds, f"Schedule import: {len(shifts)} shift(s) from {job['filename']}", actor,
                                [{"shift_id": s.id, "date": s.date, "start": s.start, "end": s.end,
                                  "assignment": s.assignment, "to_employee_id": a.employee_id, "kind": "filled",
                                  "from_employee_id": None} for s, a in zip(shifts, assigns)])
        job.update(status="confirmed", confirmed_at=_now(), imported=len(shifts), version=version["tag"])
        self.store.put("import_job", job_id, org, job)
        self.audit(org, "SCHEDULE_IMPORTED", actor,
                   f"{len(shifts)} shift(s) imported from {job['filename']} into schedule {version['tag']}.",
                   import_id=job_id, new=[s.id for s in shifts])
        return {"imported": len(shifts), "version": version["tag"], "skipped": job["report"]["total"] - len(shifts)}

    # ------------------------------------------------------------ constraint center

    def constraints(self, org: str) -> dict:
        ds = self.dataset(org)
        return {"constraints": cc.catalog(self.store, org, ds), "hard_categories": list(cc.HARD_CATEGORIES),
                "soft_categories": list(cc.SOFT_CATEGORIES), "solver": _solver_status()}

    def import_constraints(self, org: str, filename: str, data: bytes, apply: bool, actor: str) -> dict:
        try:
            raw = cc.parse_file(filename, data)
        except cc.ConstraintError as exc:
            raise _err(str(exc)) from exc
        rules, errors = [], []
        for i, row in enumerate(raw):
            r, errs = cc.normalize(row, i + (2 if not filename.lower().endswith(".json") else 1))
            if r:
                rules.append(r)
            errors += errs
        result = {"valid": rules, "errors": errors, "applied": False,
                  "unenforced": [r["constraint_id"] for r in rules if not r["enforced"]]}
        if apply:
            if errors:
                raise _err("Fix the invalid rows first: " + "; ".join(errors[:5]))
            result["changes"] = self._apply_constraints(org, rules, actor, f"imported from {filename}")
            result["applied"] = True
        return result

    def update_constraint(self, org: str, constraint_id: str, patch: dict, actor: str) -> dict:
        ds = self.dataset(org)
        row = next((r for r in cc.catalog(self.store, org, ds) if r["constraint_id"] == constraint_id), None)
        if row is None:
            raise _err("Unknown constraint", 404)
        merged = {**row, **{k: v for k, v in patch.items() if k in ("value", "weight", "enabled", "rule", "priority")}}
        r, errs = cc.normalize(merged)
        if errs:
            raise _err("; ".join(errs))
        r["constraint_id"] = constraint_id
        self._apply_constraints(org, [r], actor, "edited")
        return next(x for x in cc.catalog(self.store, org, self.dataset(org)) if x["constraint_id"] == constraint_id)

    def _apply_constraints(self, org: str, rules: list[dict], actor: str, how: str) -> list[dict]:
        try:
            new_ds, info = cc.apply(self.store, org, self.dataset(org), rules)
        except cc.ConstraintError as exc:
            raise _err(str(exc)) from exc
        self._save_dataset(org, new_ds)
        for ch in info["changes"]:
            self.audit(org, "CONSTRAINT_CHANGED", actor, f"{ch['constraint_id']} {ch['field']} {how}.",
                       constraint_id=ch["constraint_id"], previous=ch["previous"], new=ch["new"])
        return info["changes"]

    def remove_constraint(self, org: str, constraint_id: str, actor: str) -> dict:
        try:
            cc.remove(self.store, org, constraint_id)
        except cc.ConstraintError as exc:
            raise _err(str(exc)) from exc
        self.audit(org, "CONSTRAINT_REMOVED", actor, f"Imported rule {constraint_id} removed.",
                   constraint_id=constraint_id)
        return {"removed": constraint_id}

    def test_constraints(self, org: str) -> dict:
        return cc.test(self.store, org, self.dataset(org))

    # ------------------------------------------------------------ rewards

    def rewards_overview(self, org: str) -> dict:
        ds = self.dataset(org)
        return rewards.overview(self.store, org, self._ws(org)["domain"], [(e.id, e.name) for e in ds.employees])

    def employee_rewards(self, org: str, employee_id: str) -> dict:
        e = self.dataset(org).employee(employee_id)
        if e is None:
            raise _err("Unknown employee", 404)
        domain = self._ws(org)["domain"]
        return {"config": rewards.config(self.store, org, domain),
                **rewards.employee_summary(self.store, org, domain, e.id, e.name)}

    def save_reward_config(self, org: str, rules: list[dict], actor: str) -> dict:
        domain = self._ws(org)["domain"]
        before = rewards.config(self.store, org, domain)["rules"]
        try:
            out = rewards.save_config(self.store, org, domain, rules)
        except (ValueError, TypeError) as exc:
            raise _err(str(exc)) from exc
        self.audit(org, "REWARD_RULES_CHANGED", actor, "Reward rules updated.", previous=before, new=out["rules"])
        return out

    def approve_reward(self, org: str, eligibility_id: str, actor: str) -> dict:
        try:
            e = rewards.approve(self.store, org, self._ws(org)["domain"], eligibility_id, actor)
        except KeyError as exc:
            raise _err(str(exc).strip("'"), 404) from exc
        self.notify_employee(org, e["employee_id"], 1, "reward", f"+{e['points']} points: {e['task']}",
                             "Your reward was approved. See Rewards & Recognition.", requires_acknowledgement=False)
        self.audit(org, "REWARD_APPROVED", actor, f"{e['employee_name']}: +{e['points']} points approved.",
                   eligibility_id=eligibility_id, previous="pending_approval", new="rewarded")
        return e

    def give_reward(self, org: str, employee_id: str, trigger: str, note: str, actor: str) -> dict:
        e = self.dataset(org).employee(employee_id)
        if e is None:
            raise _err("Unknown employee", 404)
        try:
            out = rewards.manager_award(self.store, org, self._ws(org)["domain"], e.id, e.name, trigger, note, actor)
        except ValueError as exc:
            raise _err(str(exc)) from exc
        self.notify_employee(org, e.id, 1, "reward", f"Recognized: {rewards.TRIGGERS[trigger]}", f"{actor}: {note}",
                             requires_acknowledgement=False)
        self.audit(org, "REWARD_GIVEN", actor, f"{e.name} recognized ({trigger.replace('_', ' ')}): {note}",
                   new={"points": out.get("points"), "trigger": trigger})
        return out

    # ------------------------------------------------------------ employee home

    def employee_home(self, org: str, employee_id: str) -> dict:
        ds = self.dataset(org)
        e = ds.employee(employee_id)
        if e is None:
            raise _err("Unknown employee", 404)
        view = self.employee_view(org, employee_id)
        for n in view["notifications"]:
            if not n.get("opened_at") and n.get("channels") is not None:
                notify.mark_opened(self.store, org, n)
        now = self._now_dt(ds)
        today = ds.reference_date or now.date().isoformat()
        sched = view["schedule"]
        upcoming = [r for r in sched if r["employee_id"] == employee_id and r["date"] >= today]
        affected = [r for r in sched if r["status"] in ("disrupted",) and r["original_employee_id"] == employee_id]
        opps = []
        for w in self.store.list("workforce_request", org):
            if employee_id in w.get("invited", []) and w["status"] in ("open", "partially_filled"):
                mine = next((v for v in w["volunteers"] if v["employee_id"] == employee_id), None)
                opps.append({"id": w["id"], "task": w["task"], "date": w["date"], "start": w["start"], "end": w["end"],
                             "location": w.get("location"), "skills": w["skills"], "priority": w["priority"],
                             "emergency": w.get("emergency", False), "my_status": mine["status"] if mine else None})
        return {**view, "today": today, "now": ds.reference_time,
                "today_shifts": [r for r in upcoming if r["date"] == today],
                "next_shift": upcoming[0] if upcoming else None, "upcoming": upcoming[:14],
                "conflict_alerts": affected, "opportunities": opps,
                "admin_requests": self.admin_requests(org, employee_id),
                "rewards": self.employee_rewards(org, employee_id),
                "workload": fairness_engine.profile(ds, e)}

    # ------------------------------------------------------------ admin overview

    def admin_overview(self, org: str) -> dict:
        ds = self.dataset(org)
        notes = self.store.list("notification", org, limit=2000)
        wfr = self.store.list("workforce_request", org)
        rc = self.repair_center(org)
        return {"staffing_gaps": self.staffing_gaps(org)[:8], "workforce": workforce.summary_counts(wfr),
                "notifications": notify.summary(notes), "repairs": rc["counts"],
                "fairness": fairness_engine.team_distribution(ds)[:12],
                "rewards": rewards.overview(self.store, org, self._ws(org)["domain"], [])["stats"],
                "employees": {"active": sum(1 for e in ds.employees if e.status == "active"),
                              "inactive": sum(1 for e in ds.employees if e.status == "inactive")},
                "solver": _solver_status()}


# ---------------------------------------------------------------- module helpers

_TYPE_LABEL = {"approved_leave": "Approved leave", "unavailable": "Employee unavailable",
               "double_booking": "Double booking", "rest_violation": "Minimum rest violation",
               "missing_skill": "Skill mismatch", "missing_certification": "Certification mismatch",
               "unavailable_assignee": "Assigned while unavailable", "daily_hours": "Maximum daily hours",
               "weekly_hours": "Maximum weekly hours", "open_shift": "Uncovered shift",
               "staffing_gap": "Staffing gap"}


def _constraint_label(conflict_type: str) -> str:
    return {"double_booking": "C002 No double booking", "rest_violation": "C006 Minimum rest",
            "missing_skill": "C003 Required skill", "missing_certification": "C004 Required certification",
            "unavailable_assignee": "C001 Availability", "daily_hours": "C007 Maximum daily hours",
            "weekly_hours": "C008 Maximum weekly hours", "open_shift": "C010 Minimum staffing"}.get(
        conflict_type, "Hard constraint")


def _template_explanation(label: str, why: str, rec: Optional[dict], elig: list[dict]) -> str:
    if not rec:
        return f"{label}: {why} Nobody passes every hard constraint for this slot, so it needs additional " \
               "workforce, volunteers or a manual override."
    more = f" {len(elig) - 1} other eligible option(s) exist." if len(elig) > 1 else " No other eligible option exists."
    return f"{label}: {why} {rec['employee_name']} passes every hard constraint and has the lowest recent " \
           f"workload among eligible staff.{more}"


def _template_strategies(elig: list[dict], kind: str) -> list[str]:
    out = []
    if elig:
        out.append(f"Reassign to {elig[0]['employee_name']} (passes all hard constraints, fairest choice).")
    if len(elig) >= 2:
        out.append(f"Split the shift between {elig[0]['employee_name']} and {elig[1]['employee_name']}.")
    out.append("Request additional workforce for this slot.")
    out.append("Ask eligible employees to volunteer (volunteering doesn't assign anyone until you approve).")
    return out[:4]


def _overlaps(a, b) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _row_back(d: dict) -> dict:
    return {**d, "skills": ";".join(d["skills"]), "certifications": ";".join(d.get("certifications", [])),
            "max_hours": d.get("max_hours") or "", "availability_start": d.get("availability_start") or "",
            "availability_end": d.get("availability_end") or ""}


def _sched_back(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "employee_name"}


def _solver_status() -> dict:
    from engine import solver_cpsat
    return solver_cpsat.status()
