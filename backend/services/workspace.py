"""ResQWork orchestration: the one place the full flow is wired together.

    disruption (NL or structured or demo button)
      → AI interpretation (LLM or rules) → validated disruption + instructions
      → policy bundle (RAG → constraints → conflicts)          [per organization]
      → standing manager feedback
      → repair engine (CP-SAT / exact search): options A–D, evidence, why-not
      → candidate comparison + grounded explanations
      → proposal (pending manager decision)
      → approve → new schedule version, history updated (historical fairness),
                  employee notices, voice scripts, audit, analytics
      → reject  → audit (+ optional feedback)

API routes are thin wrappers around this class, so the whole flow is
testable without a web server.
"""

from __future__ import annotations

import uuid
from datetime import date as Date, datetime, timezone
from typing import Any, Optional

from ai.schemas import ParseResult
from ai.service import AIService
from core.models import Assignment, Availability, Dataset, Disruption
from core.validation import ValidationReport, validate_dataset
from engine.repair import RepairResult, generate_repair
from rag.service import PolicyService

from . import bridge, kpis, notify, recognition, rewards
from .domains import demo_dataset, domain_config, policy_dir
from .operations import OperationsMixin


class ResQWorkError(Exception):
    def __init__(self, message: str, status: int = 400, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class ResQWork(OperationsMixin):
    def __init__(self, store, ai: Optional[AIService] = None) -> None:
        self.store = store
        self.ai = ai or AIService(None)
        self._policies: dict[str, PolicyService] = {}

    # ------------------------------------------------------------ helpers

    def audit(self, org: str, event: str, actor: str, description: str, **details: Any) -> dict:
        """Who · what · when, with previous/new values and a reason where the caller has them."""
        doc = {"id": _id("aud"), "event_type": event, "actor": actor, "description": description,
               "previous": details.pop("previous", None), "new": details.pop("new", None),
               "reason": details.pop("reason", None), "details": details, "timestamp": _now()}
        self.store.put("audit", doc["id"], org, doc)
        return doc

    def _ws(self, org: str) -> dict:
        ws = self.store.get("workspace", "current", org)
        if not ws:
            raise ResQWorkError("No dataset loaded for this organization. Load a demo or upload data first.", 404)
        return ws

    def dataset(self, org: str) -> Dataset:
        return Dataset.model_validate(self._ws(org)["dataset"])

    def _save_dataset(self, org: str, ds: Dataset, **extra: Any) -> None:
        ws = self._ws(org)
        ws.update(extra)
        ws["dataset"] = ds.model_dump(mode="json")
        ws["updated_at"] = _now()
        self.store.put("workspace", "current", org, ws)

    def policies(self, org: str) -> PolicyService:
        if org not in self._policies:
            svc = PolicyService(self.ai.provider)
            ws = self.store.get("workspace", "current", org)
            if ws and policy_dir(ws["domain"]).exists():
                svc.ingest_directory(policy_dir(ws["domain"]))
            for doc in self.store.list("policy_doc", org):
                from rag.documents import parse_document
                svc.ingest(parse_document(doc["text"], doc["policy_id"], doc.get("filename")))
            self._policies[org] = svc
        return self._policies[org]

    # ------------------------------------------------------------ datasets

    def load_dataset(self, raw: dict, source: str, actor: str = "admin") -> tuple[ValidationReport, Optional[dict]]:
        report = validate_dataset(raw)
        if not report.ok:
            return report, None
        ds = report.dataset
        org = ds.organization.id
        # A (re)loaded dataset is a fresh baseline: drop operational state that referenced the previous schedule.
        # Audit history, manager feedback and uploaded policy documents are kept.
        for kind in ("disruption", "proposal", "version", "notification", "availability_request", "recognition",
                     "reward_eligibility", "workforce_request", "admin_request", "outbox", "constraint_config",
                     "import_job"):
            for doc in self.store.list(kind, org, limit=100000):
                if doc.get("id"):
                    self.store.delete(kind, doc["id"], org)
        ws = {"org": org, "domain": ds.organization.domain, "organization": ds.organization.model_dump(),
              "source": source, "version": "v1.0", "loaded_at": _now(), "updated_at": _now(),
              "dataset": ds.model_dump(mode="json"), "original_schedule": [a.model_dump() for a in ds.existing_schedule]}
        self.store.put("workspace", "current", org, ws)
        self.store.put("version", "v1.0", org, {
            "id": "v1.0", "tag": "v1.0", "parent": None, "created_at": _now(), "created_by": actor,
            "title": f"Initial schedule ({source})", "assignments": ws["original_schedule"], "changes": [],
            "status": "active"})
        self._policies.pop(org, None)
        recognition.seed_from_history(self.store, org, ds.organization.domain, ds.employees)
        self.audit(org, "DATASET_LOADED", actor, f"{source} dataset loaded: {report.summary}",
                   stats=report.stats, warnings=len(report.warnings))
        return report, ws

    def load_demo(self, domain: str, actor: str = "admin") -> tuple[ValidationReport, Optional[dict]]:
        try:
            raw = demo_dataset(domain)
        except KeyError as exc:
            raise ResQWorkError(str(exc), 404) from exc
        return self.load_dataset(raw, f"{domain} demo", actor)

    def workspace_summary(self, org: str) -> dict:
        ws = self._ws(org)
        ds = Dataset.model_validate(ws["dataset"])
        return {"org": org, "organization": ws["organization"], "domain": ws["domain"], "source": ws["source"],
                "version": ws["version"], "loaded_at": ws["loaded_at"],
                "reference_date": ds.reference_date, "reference_time": ds.reference_time,
                "counts": {"employees": len(ds.employees), "shifts": len(ds.shifts),
                           "assignments": len(ds.existing_schedule), "departments": len(ds.departments)},
                "presets": [d.model_dump() for d in ds.disruptions], "config": domain_config(ws["domain"])}

    # ------------------------------------------------------------ schedule views

    def employees(self, org: str) -> list[dict]:
        return [e.model_dump() for e in self.dataset(org).employees]

    def schedule(self, org: str, employee_id: Optional[str] = None) -> list[dict]:
        ds = self.dataset(org)
        amap = ds.assignment_map()
        emps = {e.id: e for e in ds.employees}
        original = {a["shift_id"]: a["employee_id"] for a in self._ws(org)["original_schedule"]}
        open_d = self.open_disruptions(org)
        rows = []
        for s in sorted(ds.shifts, key=lambda s: (s.window[0], s.assignment)):
            eid = amap.get(s.id)
            if employee_id and eid != employee_id and original.get(s.id) != employee_id:
                continue
            status = "scheduled"
            if eid is None:
                status = "open"
            elif any(d.employee_id == eid and _overlaps(s, d) for d in open_d):
                status = "disrupted"
            elif original.get(s.id) and original.get(s.id) != eid:
                status = "changed"
            rows.append({"shift_id": s.id, "date": s.date, "start": s.start, "end": s.end, "hours": s.hours,
                         "assignment": s.assignment, "department": s.department, "shift_type": s.shift_type,
                         "priority": s.priority, "required_skills": s.required_skills + s.required_certifications,
                         "employee_id": eid, "employee_name": emps[eid].name if eid in emps else None,
                         "original_employee_id": original.get(s.id),
                         "original_employee_name": emps[original[s.id]].name if original.get(s.id) in emps else None,
                         "status": status, "attributes": s.attributes})
        return rows

    # ------------------------------------------------------------ disruptions

    def open_disruptions(self, org: str) -> list[Disruption]:
        return [Disruption.model_validate(d["disruption"]) for d in self.store.list("disruption", org)
                if d["status"] == "open" and _is_absence(d)]

    # ------------------------------------------------------------ schedule conflicts (problems already in the data)

    def schedule_conflicts(self, org: str) -> list[dict]:
        """Hard-rule conflicts in the current schedule (double bookings, unqualified assignees, open shifts…)."""
        from engine.conflicts import detect_conflicts
        in_progress = {c["id"] for r in self.store.list("disruption", org)
                       if r.get("kind") == "conflict" and r["status"] == "open" for c in r["conflicts"]}
        return [{**c.model_dump(), "in_repair": c.id in in_progress} for c in detect_conflicts(self.dataset(org))]

    def resolve_conflicts(self, org: str, conflict_ids: Optional[list[str]] = None, actor: str = "manager") -> dict:
        """Turn detected conflicts into one repair run. Nothing is changed until a manager approves."""
        found = [c for c in self.schedule_conflicts(org) if c["repairable"]]
        chosen = [c for c in found if not conflict_ids or c["id"] in conflict_ids]
        if not chosen:
            raise ResQWorkError("No repairable schedule conflict found.", 409)
        for r in self.store.list("disruption", org):     # supersede earlier conflict runs
            if r.get("kind") == "conflict" and r["status"] == "open":
                r["status"] = "dismissed"
                self.store.put("disruption", r["id"], org, r)
        rec = {"id": _id("cfl"), "kind": "conflict", "status": "open", "created_at": _now(), "actor": actor,
               "source": "schedule check", "conflicts": [{k: v for k, v in c.items() if k != "in_repair"} for c in chosen],
               "affected_shifts": sorted({s for c in chosen for s in list(c["release"]) + c["cover"]}),
               "employee_name": ", ".join(sorted({c["employee_name"] for c in chosen if c["employee_name"]}))
               or "Open shifts"}
        self.store.put("disruption", rec["id"], org, rec)
        self.audit(org, "CONFLICTS_DETECTED", actor,
                   f"{len(chosen)} schedule conflict(s) sent to repair: " + "; ".join(c["label"] for c in chosen),
                   disruption_id=rec["id"])
        return self.generate_repair(org, [rec["id"]], actor=actor)

    def report_disruption(self, org: str, text: Optional[str] = None, structured: Optional[dict] = None,
                          preset_id: Optional[str] = None, actor: str = "manager") -> dict:
        ds = self.dataset(org)
        parsed: Optional[ParseResult] = None
        if preset_id:
            preset = next((d for d in ds.disruptions if d.id == preset_id), None)
            if preset is None:
                raise ResQWorkError(f"Unknown demo disruption '{preset_id}'", 404)
            disruptions = [preset.model_copy(update={"id": _id("dis")})]
            source = f"demo: {preset.label}"
        elif structured:
            try:
                disruptions = [Disruption.model_validate({"id": _id("dis"), **structured})]
            except Exception as exc:  # noqa: BLE001
                raise ResQWorkError(f"Invalid disruption: {exc}") from exc
            if ds.employee(disruptions[0].employee_id) is None:
                raise ResQWorkError(f"Unknown employee '{disruptions[0].employee_id}'", 404)
            source = "form"
        elif text:
            parsed = self.ai.parse_request(text, bridge.parse_context(ds))
            if not parsed.ready:
                return {"status": parsed.status, "interpretation": parsed.model_dump(mode="json"), "disruptions": []}
            disruptions = bridge.core_disruptions(parsed, _id("dis"))
            source = f"natural language ({parsed.meta.provider or 'llm'})"
        else:
            raise ResQWorkError("Provide text, a structured disruption or a demo preset.")

        records = []
        for d in disruptions:
            affected = [s.id for s in ds.shifts if ds.assignment_map().get(s.id) == d.employee_id and _overlaps(s, d)]
            rec = {"id": d.id, "status": "open", "created_at": _now(), "source": source, "actor": actor,
                   "disruption": d.model_dump(), "affected_shifts": affected,
                   "employee_name": ds.employee(d.employee_id).name,
                   "instructions": parsed.model_dump(mode="json") if parsed else None}
            self.store.put("disruption", d.id, org, rec)
            records.append(rec)
            self.audit(org, "DISRUPTION_REPORTED", actor,
                       f"{rec['employee_name']} unavailable {d.date} {d.start or ''}–{d.end or ''} ({source}); "
                       f"{len(affected)} shift(s) affected.", disruption_id=d.id)
        return {"status": "READY", "interpretation": parsed.model_dump(mode="json") if parsed else None,
                "disruptions": records}

    def dismiss_disruption(self, org: str, disruption_id: str, actor: str = "manager") -> dict:
        rec = self.store.get("disruption", disruption_id, org)
        if not rec:
            raise ResQWorkError("Unknown disruption", 404)
        rec["status"] = "dismissed"
        self.store.put("disruption", disruption_id, org, rec)
        self.audit(org, "DISRUPTION_DISMISSED", actor, f"Disruption {disruption_id} dismissed.")
        return rec

    # ------------------------------------------------------------ repair

    def generate_repair(self, org: str, disruption_ids: Optional[list[str]] = None, actor: str = "manager",
                        scenario=None, parent_id: Optional[str] = None, extra_disruptions: Optional[list] = None) -> dict:
        ds = self.dataset(org)
        ws = self._ws(org)
        records = [self.store.get("disruption", i, org) for i in disruption_ids] if disruption_ids else \
            [r for r in self.store.list("disruption", org) if r["status"] == "open"]
        records = [r for r in records if r]
        if not records:
            raise ResQWorkError("No open disruption to repair.", 409)
        disruptions = [Disruption.model_validate(r["disruption"]) for r in records if _is_absence(r)] \
            + list(extra_disruptions or [])
        release = {sid: why for r in records if r.get("kind") == "conflict" for c in r["conflicts"]
                   for sid, why in c["release"].items()}
        cover = sorted({sid for r in records if r.get("kind") == "conflict" for c in r["conflicts"] for sid in c["cover"]})
        parsed = next((ParseResult.model_validate(r["instructions"]) for r in records if r.get("instructions")), None)

        cfg = domain_config(ws["domain"])
        roles = sorted({e.role for e in ds.employees if any(d.employee_id == e.id for d in disruptions)})
        affected_assignments = sorted({ds.shift(s).assignment for r in records for s in r["affected_shifts"]})
        bundle = self.policies(org).build_bundle(" ".join(r.get("source", "") for r in records), roles,
                                                 affected_assignments)
        feedback = [f for f in self.store.list("feedback", org) if f.get("active", True)]
        settings, priority, notes = bridge.settings_from(ds, parsed, feedback, bundle.optimizer_config, disruptions)
        if release or cover:
            settings = settings.model_copy(update={"release_shift_ids": release, "cover_shift_ids": cover})
        if scenario is not None:
            settings, priority, scen_notes = _apply_scenario(settings, priority, scenario)
            notes += scen_notes

        result: RepairResult = generate_repair(ds, disruptions, settings, strategies=bridge.strategy_order(priority))
        relaxation = None
        if result.status in ("PARTIAL", "INFEASIBLE") and settings.allow_overtime is False:
            relaxed = generate_repair(ds, disruptions, settings.model_copy(update={"allow_overtime": None}),
                                      strategies=["recommended"], with_baseline=False)
            if relaxed.options and not relaxed.options[0].impact.unfilled_shifts:
                o = relaxed.options[0]
                relaxation = {"change": "allow overtime",
                              "message": f"Without the no-overtime instruction, {o.label} would cover everything: "
                                         + ", ".join(f"{c.to_employee_name} → {c.assignment}" for c in o.changes)
                                         + f" ({o.impact.overtime_hours_added:g}h overtime).",
                              "option": o.model_dump(mode="json")}
        names = [e.name for e in ds.employees]
        comparison = self.ai.compare_candidates(bridge.candidate_facts(ds, result), priority, names) \
            if len(result.options) > 1 else None
        enforced = {"minimum_rest", "max_daily_hours", "max_weekly_hours", "max_overtime_weekly", "overtime_allowed",
                    "required_skill"}
        citations = [c for c in bundle.citations() if c.constraint_type in enforced]
        explanations = {}
        for o in result.options:
            facts = bridge.explanation_facts(ds, result, o, citations, cfg.get("constraintLabels"))
            explanations[o.option_id] = self.ai.explain(facts, roster_names=names).model_dump(mode="json")

        proposal = {
            "id": _id("prop"), "status": "pending", "created_at": _now(), "created_by": actor,
            "parent_id": parent_id, "disruption_ids": [r["id"] for r in records],
            "scenario": scenario.summary if scenario is not None else None,
            "relaxation": relaxation,
            "run_notes": notes, "priority": priority.value if priority else None,
            "problem": _problem(ds, records),
            "result": result.model_dump(mode="json"),
            "comparison": comparison.model_dump(mode="json") if comparison else None,
            "explanations": explanations,
            "policy": {"mode": bundle.mode,
                       "constraints": [{"type": c.constraint_type, "value": c.value, "unit": c.unit,
                                        "severity": c.severity, "scope": c.scope.label(),
                                        "source": f"{c.source.document} §{c.source.section}",
                                        "policy_id": c.source.policy_id, "quote": c.source.quote,
                                        "enforced": c.constraint_type in enforced and c.severity == "hard",
                                        "confidence": c.interpretation_confidence} for c in bundle.constraints],
                       "conflicts": [c.message for c in bundle.conflicts], "warnings": bundle.warnings(),
                       "topics_without_policy": [t.topic for t in bundle.topics if t.status != "found"]},
        }
        self.store.put("proposal", proposal["id"], org, proposal)
        best = next((o for o in result.options if o.option_id == result.recommended_option_id), None)
        self.audit(org, "REPAIR_GENERATED", actor,
                   f"{len(result.options)} repair option(s) generated with {result.solver} in {result.solve_ms} ms"
                   + (f"; recommended {best.label}: {best.impact.assignments_changed} change(s), "
                      f"{best.impact.overtime_hours_added:g}h overtime." if best else f"; status {result.status}."),
                   proposal_id=proposal["id"], status=result.status, policies=[c["policy_id"] for c in
                                                                                 proposal["policy"]["constraints"]])
        return proposal

    def proposal(self, org: str, proposal_id: str) -> dict:
        p = self.store.get("proposal", proposal_id, org)
        if not p:
            raise ResQWorkError("Unknown proposal", 404)
        return p

    def latest_proposal(self, org: str) -> Optional[dict]:
        props = self.store.list("proposal", org, limit=1)
        return props[0] if props else None

    def what_if(self, org: str, proposal_id: str, text: Optional[str] = None, spec: Optional[dict] = None,
                actor: str = "manager") -> dict:
        base = self.proposal(org, proposal_id)
        ds = self.dataset(org)
        from ai.what_if import ScenarioSpec, WhatIfParser, _RawScenario
        if spec is not None:
            raw = _RawScenario.model_validate({"is_what_if": True, "changes": spec.get("changes", [])})
            scenario = WhatIfParser(None).resolve(raw, bridge.parse_context(ds))
        else:
            scenario = self.ai.parse_what_if(text or "", bridge.parse_context(ds)) if self.ai.what_if else \
                _rule_what_if(text or "", ds)
        if scenario.status != "READY":
            return {"status": scenario.status, "scenario": scenario.model_dump(mode="json")}
        extra = [Disruption(id=_id("whatif"), employee_id=d.employee_id, date=d.date, start=d.start_time,
                            end=d.end_time, reason="what-if") for d in scenario.added_disruptions()]
        new = self.generate_repair(org, base["disruption_ids"], actor, scenario=scenario, parent_id=proposal_id,
                                   extra_disruptions=extra)
        self.audit(org, "WHAT_IF_RUN", actor, scenario.summary, proposal_id=new["id"], parent_id=proposal_id)
        return {"status": "READY", "scenario": scenario.model_dump(mode="json"), "proposal": new,
                "delta": _delta(base, new)}

    # ------------------------------------------------------------ decision

    def approve(self, org: str, proposal_id: str, option_id: Optional[str] = None, actor: str = "manager",
                notes: str = "", allow_partial: bool = False) -> dict:
        prop = self.proposal(org, proposal_id)
        if prop["status"] != "pending":
            raise ResQWorkError(f"Proposal is already {prop['status']}.", 409)
        result = RepairResult.model_validate(prop["result"])
        option_id = option_id or result.recommended_option_id
        option = next((o for o in result.options if o.option_id == option_id), None)
        if option is None:
            raise ResQWorkError("Unknown option", 404)
        if option.impact.unfilled_shifts and not allow_partial:
            gaps = ", ".join(c.assignment for c in option.changes if c.kind == "uncovered")
            raise ResQWorkError(f"{option.label} leaves {gaps} uncovered. Confirm explicitly (allow_partial) "
                                f"or try a what-if first.", 409)

        ds = self.dataset(org)
        amap = ds.assignment_map()
        for sid, eid in option.assignment.items():
            if eid:
                amap[sid] = eid
            else:
                amap.pop(sid, None)
        new_assignments = [Assignment(shift_id=s, employee_id=e) for s, e in amap.items()]
        absences = [Availability(employee_id=d.employee_id, date=d.date, start=d.start, end=d.end,
                                 kind="unavailable", reason=d.reason) for d in result.disruptions
                    if d.reason != "what-if"]
        shifts_by_id = {s.id: s for s in ds.shifts}
        employees = self._with_contributions(ds, [(s.employee_id, shifts_by_id[s.shift_id], "additional",
                                                   f"{proposal_id}:{s.shift_id}") for s in option.selected])
        new_ds = ds.model_copy(update={"existing_schedule": new_assignments, "employees": employees,
                                       "availability": ds.availability + absences})

        versions = self.store.list("version", org)
        parent = next((v for v in versions if v["status"] == "active"), None)
        tag = f"v1.{len(versions)}"
        for v in versions:
            if v["status"] == "active":
                v["status"] = "superseded"
                self.store.put("version", v["id"], org, v)
        changes = bridge.change_facts(ds, option)
        names = {e.id: e.name for e in ds.employees}
        version = {"id": tag, "tag": tag, "parent": parent["id"] if parent else None, "created_at": _now(),
                   "created_by": actor, "status": "active", "proposal_id": proposal_id, "option_id": option_id,
                   "title": "Repair: " + "; ".join(p["title"] for p in prop.get("problem", {}).get("items", []))[:160]
                            + f" ({option.label} · {option.title})",
                   "notes": notes, "assignments": [a.model_dump() for a in new_assignments],
                   "changes": [c.model_dump() for c in option.changes], "impact": option.impact.model_dump(),
                   "fairness": option.fairness.model_dump(),
                   "policies": [c["policy_id"] for c in prop["policy"]["constraints"]]}
        self.store.put("version", tag, org, version)
        self._save_dataset(org, new_ds, version=tag)

        prop["status"], prop["approved_option"], prop["decided_at"], prop["decided_by"] = "approved", option_id, _now(), actor
        self.store.put("proposal", proposal_id, org, prop)
        for did in prop["disruption_ids"]:
            rec = self.store.get("disruption", did, org)
            if rec:
                rec["status"] = "repaired"
                rec["repaired_by"] = tag
                self.store.put("disruption", did, org, rec)
                req = rec.get("request_id") and self.store.get("availability_request", rec["request_id"], org)
                if req and req["status"] == "approved":
                    self._set_request_status(org, req, "completed", f"Covered in schedule {tag}.", "system")

        # used-up "next time" feedback
        for fb in self.store.list("feedback", org):
            if fb.get("scope") == "next_reschedule" and fb.get("active", True):
                fb["active"] = False
                self.store.put("feedback", fb["preference_id"], org, fb)

        citations = [c for c in bridge.explanation_facts(ds, result, option).policies_applied]
        policy_cites = [_citation(c) for c in prop["policy"]["constraints"]
                        if c["enforced"] and c["type"] in ("minimum_rest", "max_weekly_hours", "max_daily_hours")]
        released = {c["employee_id"] for did in prop["disruption_ids"]
                    for c in (self.store.get("disruption", did, org) or {}).get("conflicts", []) if c.get("release")}
        notices = self.ai.employee_notices(changes, names, policy_cites or citations, schedule_version=tag,
                                           notify_unassigned=released)
        from .voice import employee_voice_line
        sent = []
        for n in notices:
            sev = self._change_severity(ds, [c.shift_id for c in option.changes
                                             if n.employee_id in (c.to_employee_id, c.from_employee_id)])
            doc = self.notify_employee(org, n.employee_id, sev, "schedule_change", n.title, n.body,
                                       extra={"changes": [c.model_dump() for c in n.changes], "version": tag,
                                              "voice_text": employee_voice_line(n, names)})
            sent.append(doc)
        awarded = [rewards.register(self.store, org, employee_id=c.to_employee_id, employee_name=c.to_employee_name,
                                    trigger=rewards.trigger_for(shifts_by_id[c.shift_id].priority),
                                    ref=f"{proposal_id}:{c.shift_id}", shift_id=c.shift_id, date=c.date, end=c.end,
                                    task=c.assignment, source="repair", source_id=proposal_id,
                                    critical=shifts_by_id[c.shift_id].priority == "critical")
                   for c in option.changes if c.to_employee_id]
        self.audit(org, "SCHEDULE_APPROVED", actor,
                   f"{option.label} approved; schedule {tag} published; {len(sent)} employee(s) notified.",
                   proposal_id=proposal_id, version=tag, option=option_id, impact=option.impact.impact_score,
                   fairness=option.fairness.fairness_score, notes=notes,
                   previous=[{"shift_id": c.shift_id, "employee": c.from_employee_name} for c in option.changes],
                   new=[{"shift_id": c.shift_id, "employee": c.to_employee_name} for c in option.changes])
        return {"version": version, "notifications": sent, "proposal": prop, "recognition": awarded}

    def reject(self, org: str, proposal_id: str, actor: str = "manager", reason: str = "") -> dict:
        prop = self.proposal(org, proposal_id)
        if prop["status"] != "pending":
            raise ResQWorkError(f"Proposal is already {prop['status']}.", 409)
        prop["status"], prop["decided_at"], prop["decided_by"], prop["reject_reason"] = "rejected", _now(), actor, reason
        self.store.put("proposal", proposal_id, org, prop)
        self.audit(org, "REPAIR_REJECTED", actor, f"Proposal rejected. {reason}".strip(), proposal_id=proposal_id)
        return prop

    # ------------------------------------------------------------ feedback

    def add_feedback(self, org: str, text: str, actor: str = "manager") -> dict:
        ds = self.dataset(org)
        if self.ai.feedback is None:
            res = _rule_feedback(text, ds)
        else:
            res = self.ai.parse_feedback(text, bridge.parse_context(ds))
        if res.status == "READY":
            for p in res.preferences:
                self.store.put("feedback", p.preference_id, org, {**p.model_dump(mode="json"), "active": True})
            self.audit(org, "FEEDBACK_RECORDED", actor, res.summary)
        return res.model_dump(mode="json")

    def feedback(self, org: str) -> list[dict]:
        return self.store.list("feedback", org)

    # ------------------------------------------------------------ employees

    def employee_view(self, org: str, employee_id: str) -> dict:
        ds = self.dataset(org)
        e = ds.employee(employee_id)
        if e is None:
            raise ResQWorkError("Unknown employee", 404)
        notes = [n for n in self.store.list("notification", org) if n["employee_id"] == employee_id]
        requests = [r for r in self.store.list("availability_request", org) if r["employee_id"] == employee_id]
        return {"employee": e.model_dump(), "schedule": self.schedule(org, employee_id), "notifications": notes,
                "requests": requests}

    def acknowledge(self, org: str, notification_id: str, employee_id: str) -> dict:
        n = self.store.get("notification", notification_id, org)
        if not n or n["employee_id"] != employee_id:
            raise ResQWorkError("Unknown notification", 404)
        if n.get("acknowledged_at"):
            return n
        n = notify.acknowledge(self.store, org, n)
        recognition.on_acknowledge(self.store, org, self._ws(org)["domain"], n)
        self.audit(org, "CHANGE_ACKNOWLEDGED", employee_id, f"{n['employee_name']} acknowledged {n['title']}.")
        return n

    # ------------------------------------------------------------ employee requests (single source of truth)
    #
    # One document per request in the store; every dashboard reads that same document.
    #   pending ──► approved ──► completed   (approved absence → disruption → repair approved)
    #      │  └──► rejected
    #      └─────► needs_review ──► approved | rejected

    REQUEST_KINDS = ("unavailable", "time_off", "shift_swap", "preference")
    ABSENCE_KINDS = ("unavailable", "time_off")

    def submit_availability(self, org: str, employee_id: str, date: str, start: Optional[str], end: Optional[str],
                            reason: str = "", kind: str = "unavailable") -> dict:
        ds = self.dataset(org)
        e = ds.employee(employee_id)
        if e is None:
            raise ResQWorkError("Unknown employee", 404)
        if kind not in self.REQUEST_KINDS:
            raise ResQWorkError(f"kind must be one of {', '.join(self.REQUEST_KINDS)}")
        try:
            Date.fromisoformat(date)
        except ValueError as exc:
            raise ResQWorkError("date must be YYYY-MM-DD") from exc
        if (start and not end) or (end and not start):
            raise ResQWorkError("Give both a start and an end time, or neither (whole day).")
        now = _now()
        affected = [s.id for s in ds.shifts if ds.assignment_map().get(s.id) == employee_id and s.date == date
                    and (not start or _overlaps(s, Disruption(id="x", employee_id=employee_id, date=date,
                                                              start=start, end=end)))]
        req = {"id": _id("req"), "employee_id": employee_id, "employee_name": e.name, "date": date, "start": start,
               "end": end, "reason": reason, "kind": kind, "status": "pending", "created_at": now, "updated_at": now,
               "affected_shifts": affected, "manager_note": None, "decided_by": None, "disruption_id": None,
               "history": [{"status": "pending", "at": now, "by": e.name, "note": reason or None}]}
        self.store.put("availability_request", req["id"], org, req)
        recognition.on_request(self.store, org, self._ws(org)["domain"], req)
        self.audit(org, "REQUEST_SUBMITTED", e.name,
                   f"{e.name} submitted a {kind.replace('_', ' ')} request for {date} {start or ''}–{end or ''}.",
                   request_id=req["id"])
        return req

    def availability_requests(self, org: str) -> list[dict]:
        return self.store.list("availability_request", org)

    def decide_request(self, org: str, request_id: str, status: str, note: str = "", actor: str = "manager") -> dict:
        req = self.store.get("availability_request", request_id, org)
        if not req:
            raise ResQWorkError("Unknown request", 404)
        if status not in ("approved", "rejected", "needs_review"):
            raise ResQWorkError("status must be approved, rejected or needs_review")
        if req["status"] in ("approved", "rejected", "completed"):
            raise ResQWorkError(f"This request is already {req['status']}.", 409)
        out: dict = {}
        if status == "approved" and req.get("kind", "unavailable") in self.ABSENCE_KINDS:
            out = self.report_disruption(org, structured={
                "employee_id": req["employee_id"], "date": req["date"], "start": req["start"], "end": req["end"],
                "reason": "personal", "severity": "medium",
                "label": f"Request from {req['employee_name']}"}, actor=actor)
            rec = out["disruptions"][0]
            rec["request_id"] = req["id"]
            self.store.put("disruption", rec["id"], org, rec)
            req["disruption_id"] = rec["id"]
            if not rec["affected_shifts"]:     # nothing to repair: the request is done as soon as it's approved
                status = "completed"
        elif status == "approved":
            status = "completed"               # swaps/preferences: noted, nothing to repair
        req = self._set_request_status(org, req, status, note, actor)
        return {"request": req, **out}

    def accept_availability(self, org: str, request_id: str, actor: str = "manager") -> dict:
        """Backward-compatible alias for approving a request."""
        return self.decide_request(org, request_id, "approved", actor=actor)

    def _set_request_status(self, org: str, req: dict, status: str, note: str, actor: str) -> dict:
        now = _now()
        req["status"], req["updated_at"] = status, now
        if status in ("approved", "rejected", "needs_review", "completed") and actor != "system":
            req["decided_by"], req["decided_at"] = actor, now
        if note:
            req["manager_note"] = note
        req.setdefault("history", []).append({"status": status, "at": now, "by": actor, "note": note or None})
        self.store.put("availability_request", req["id"], org, req)
        label = {"approved": "approved", "rejected": "declined", "needs_review": "marked for review",
                 "completed": "completed"}[status]
        body = {"approved": "Your manager approved it. ResQWork is arranging cover; you'll see any change here.",
                "rejected": "Your manager declined it." + (f" Note: {note}" if note else ""),
                "needs_review": "Your manager needs to look into it further." + (f" Note: {note}" if note else ""),
                "completed": "Your schedule has been updated accordingly."}[status]
        self.notify_employee(org, req["employee_id"], 1, "request", f"Request {label}: {req['date']}", body,
                             requires_acknowledgement=False,
                             extra={"request_id": req["id"], "version": self._ws(org)["version"]})
        self.audit(org, "REQUEST_" + status.upper(), actor,
                   f"{req['employee_name']}'s request for {req['date']} {label}" + (f": {note}" if note else "."),
                   request_id=req["id"], previous=req["history"][-2]["status"] if len(req["history"]) > 1 else None,
                   new=status, reason=note or None)
        return req

    # ------------------------------------------------------------ recognition

    def recognition_overview(self, org: str) -> dict:
        domain = self._ws(org)["domain"]
        people = [recognition.summary(self.store, org, domain, e.id, e.name) for e in self.dataset(org).employees]
        people.sort(key=lambda s: (-s["points_90d"], s["employee_name"]))
        return {"config": recognition.config(domain), "employees": people,
                "recent": self.store.list("recognition", org, limit=20)}

    def employee_recognition(self, org: str, employee_id: str) -> dict:
        e = self.dataset(org).employee(employee_id)
        if e is None:
            raise ResQWorkError("Unknown employee", 404)
        domain = self._ws(org)["domain"]
        return {"config": recognition.config(domain),
                **recognition.summary(self.store, org, domain, e.id, e.name)}

    def recognize(self, org: str, employee_id: str, category: str, note: str, actor: str = "manager") -> dict:
        e = self.dataset(org).employee(employee_id)
        if e is None:
            raise ResQWorkError("Unknown employee", 404)
        try:
            award = recognition.manager_award(self.store, org, self._ws(org)["domain"], e.id, e.name, category, note, actor)
        except ValueError as exc:
            raise ResQWorkError(str(exc)) from exc
        self.notify_employee(org, e.id, 1, "recognition", f"Recognition: {award['category_label']}",
                             f"{actor}: {award['reason']}", requires_acknowledgement=False)
        self.audit(org, "RECOGNITION_GIVEN", actor, f"{e.name} recognized for {award['category_label']}: {award['reason']}")
        return award

    # ------------------------------------------------------------ policies

    def policy_overview(self, org: str) -> dict:
        svc = self.policies(org)
        bundle = svc.build_bundle(exhaustive=True)
        docs = [{"policy_id": d.policy_id, "title": d.title, "version": d.version, "effective_date": d.effective_date,
                 "chunks": sum(1 for c in svc.store.chunks if c.policy_id == d.policy_id)}
                for d in svc.store.documents.values()]
        return {"documents": docs, "mode": bundle.mode,
                "constraints": [{"type": c.constraint_type, "value": c.value, "unit": c.unit, "severity": c.severity,
                                 "scope": c.scope.label(), "source": f"{c.source.document} §{c.source.section}",
                                 "policy_id": c.source.policy_id, "quote": c.source.quote,
                                 "confidence": c.interpretation_confidence} for c in bundle.constraints],
                "conflicts": [c.message for c in bundle.conflicts],
                "unsupported": [u.text for u in bundle.unsupported], "optimizer_config": bundle.optimizer_config}

    def policy_search(self, org: str, query: str) -> dict:
        r = self.policies(org).lookup(query)
        return {"query": query, "status": r.status, "message": r.message,
                "hits": [{"citation": h.citation(), "policy_id": h.policy_id, "section": h.chunk.section,
                          "text": h.chunk.text, "confidence": h.confidence} for h in r.hits]}

    def upload_policy(self, org: str, filename: str, text: str, actor: str = "admin") -> dict:
        from rag.documents import parse_document
        default_id = filename.rsplit(".", 1)[0].upper().replace(" ", "-")[:40] or "POLICY"
        doc = parse_document(text, default_id, filename)
        self.store.put("policy_doc", doc.policy_id, org, {"policy_id": doc.policy_id, "filename": filename,
                                                           "text": text, "uploaded_at": _now()})
        n = self.policies(org).ingest(doc)
        self.audit(org, "POLICY_UPLOADED", actor, f"Policy '{doc.title}' indexed ({n} sections).")
        return {"policy_id": doc.policy_id, "title": doc.title, "sections": n}

    # ------------------------------------------------------------ dashboards, versions, audit, analytics

    def dashboard(self, org: str) -> dict:
        ds = self.dataset(org)
        ws = self._ws(org)
        cfg = domain_config(ws["domain"])
        open_d = self.open_disruptions(org)
        metrics = kpis.compute(ds, open_d)
        history = [{"date": r["created_at"][:10], "employee": r["employee_name"], "status": r["status"],
                    "reason": r["disruption"].get("reason") if _is_absence(r) else "schedule conflict",
                    "source": r["source"]}
                   for r in self.store.list("disruption", org, limit=50)]
        disruptions = [r for r in self.store.list("disruption", org) if r["status"] == "open"]
        return {"domain": ws["domain"], "dashboardName": cfg["dashboardName"], "organization": ws["organization"],
                "version": ws["version"], "metrics": metrics,
                "kpis": [{**k, "value": metrics.get(k["metric"], {})} for k in cfg["kpis"]],
                "commonKpis": [{**k, "value": metrics.get(k["metric"], {})} for k in cfg["commonKpis"]],
                "widgets": kpis.widgets(ds, open_d, history), "open_disruptions": disruptions,
                "latest_proposal": _proposal_card(self.latest_proposal(org)),
                "pending_requests": [r for r in self.availability_requests(org)
                                     if r["status"] in ("pending", "needs_review")],
                "conflicts": [c for c in self.schedule_conflicts(org) if c["repairable"]],
                "overview": self.admin_overview(org)}

    def versions(self, org: str) -> list[dict]:
        return [{k: v for k, v in d.items() if k != "assignments"} for d in self.store.list("version", org)]

    def version(self, org: str, version_id: str) -> dict:
        v = self.store.get("version", version_id, org)
        if not v:
            raise ResQWorkError("Unknown version", 404)
        return v

    def audit_trail(self, org: str, limit: int = 200) -> list[dict]:
        return self.store.list("audit", org, limit)

    def notifications(self, org: str) -> list[dict]:
        self.run_escalations(org)
        return self.store.list("notification", org)

    def analytics(self, org: str) -> dict:
        from .analytics import operations_analytics, org_analytics
        base = org_analytics(self.store.list("disruption", org), self.store.list("proposal", org),
                             self.store.list("version", org), self.dataset(org))
        return {**base, **operations_analytics(self, org)}


# ---------------------------------------------------------------- helpers

def _is_absence(record: dict) -> bool:
    return record.get("kind", "absence") == "absence"


def _problem(ds: Dataset, records: list[dict]) -> dict:
    """What went wrong, in plain words, for the Repair Centre's "Problem" section."""
    items = []
    for r in records:
        if _is_absence(r):
            d = r["disruption"]
            when = f"{d['date']} {d.get('start') or ''}{'–' + d['end'] if d.get('end') else ' (all day)'}".strip()
            items.append({"kind": "absence", "title": f"{r['employee_name']} unavailable",
                          "detail": f"{when}" + (f" · {d['reason']}" if d.get("reason") else ""),
                          "hard_constraint": "Availability", "shift_ids": r["affected_shifts"]})
        else:
            for c in r["conflicts"]:
                items.append({"kind": c["type"], "title": c["label"] + (f": {c['employee_name']}" if c["employee_name"] else ""),
                              "detail": c["message"], "hard_constraint": c["hard_constraint"],
                              "shift_ids": list(c["release"]) + c["cover"]})
    shifts = {s.id: s for s in ds.shifts}
    affected = sorted({sid for i in items for sid in i["shift_ids"]})
    return {"items": items,
            "affected_shifts": [{"shift_id": sid, "assignment": shifts[sid].assignment, "date": shifts[sid].date,
                                 "start": shifts[sid].start, "end": shifts[sid].end,
                                 "priority": shifts[sid].priority} for sid in affected if sid in shifts]}


def _overlaps(shift, d: Disruption) -> bool:
    from core.rules import overlaps
    return overlaps(shift.window, d.as_availability().window)


def _citation(c: dict):
    from ai.schemas import PolicyCitation
    doc, _, section = c["source"].rpartition(" §")
    return PolicyCitation(policy_id=c["policy_id"], document=doc, section=section, constraint_type=c["type"],
                          value=c["value"], unit=c.get("unit"))


def _proposal_card(p: Optional[dict]) -> Optional[dict]:
    if not p:
        return None
    r = p["result"]
    best = next((o for o in r["options"] if o["option_id"] == r.get("recommended_option_id")), None)
    return {"id": p["id"], "status": p["status"], "created_at": p["created_at"], "solver": r["solver"],
            "result_status": r["status"], "feasible": r["status"] in ("OPTIMAL", "FEASIBLE"),
            "unresolved": [{"assignment": u["assignment"], "date": u["date"], "summary": u["summary"]}
                           for u in r.get("unresolved", [])],
            "problem": [i["title"] for i in p.get("problem", {}).get("items", [])],
            "options": len(r["options"]), "recommended": best and {"label": best["label"], "title": best["title"],
                                                                    "impact": best["impact"], "fairness": best["fairness"]}}


def _apply_scenario(settings, priority, scenario):
    from ai.schemas import ManagerPreferences
    notes = [scenario.summary]
    prefs = scenario.apply_to(ManagerPreferences(locked_employee_ids=settings.locked_employee_ids,
                                                 excluded_employee_ids=settings.excluded_employee_ids,
                                                 allow_overtime=settings.allow_overtime, priority=priority))
    s = settings.model_copy(update={"locked_employee_ids": prefs.locked_employee_ids,
                                    "excluded_employee_ids": prefs.excluded_employee_ids,
                                    "allow_overtime": prefs.allow_overtime,
                                    "removed_unavailability": scenario.removed_unavailability()})
    mapping = {"minimum_rest": "min_rest_hours", "max_daily_hours": "max_daily_hours",
               "max_weekly_hours": "max_weekly_hours", "max_overtime_weekly": "max_overtime_hours_per_week",
               "overtime_allowed": "allow_overtime"}
    overrides = dict(s.constraint_overrides)
    for k, v in scenario.policy_overrides().items():
        if k in mapping:
            overrides[mapping[k]] = v
    s.constraint_overrides = overrides
    return s, prefs.priority, notes


def _delta(base: dict, new: dict) -> dict:
    def best(p):
        r = p["result"]
        return next((o for o in r["options"] if o["option_id"] == r.get("recommended_option_id")), None)
    b, n = best(base), best(new)
    if not b or not n:
        return {"comparable": False, "message": "One of the runs has no feasible repair."}
    keys = ("assignments_changed", "employees_affected", "overtime_hours_added", "impact_score", "unfilled_shifts")
    d = {k: round(n["impact"][k] - b["impact"][k], 2) for k in keys}
    d["fairness_score"] = round(n["fairness"]["fairness_score"] - b["fairness"]["fairness_score"], 1)
    return {"comparable": True, "before": {"label": b["label"], "impact": b["impact"], "fairness": b["fairness"]},
            "after": {"label": n["label"], "impact": n["impact"], "fairness": n["fairness"]}, "delta": d}


def _rule_what_if(text: str, ds: Dataset):
    """Minimal deterministic what-if parsing when no LLM is configured."""
    import re
    from ai.what_if import WhatIfParser, _RawScenario
    changes = []
    t = text.lower()
    if re.search(r"(minimi[sz]e|least|less|lower|reduce|fewest|lowest) overtime", t):
        changes.append({"op": "set_priority", "priority": "minimize_overtime", "text": "minimize overtime"})
    elif re.search(r"overtime (is )?(forbidden|not allowed|prohibited|banned)|no overtime", t):
        changes.append({"op": "set_overtime", "value": False, "text": "overtime forbidden"})
    elif re.search(r"overtime (is |were |was )?(allowed|permitted|ok|okay|fine|acceptable)|allow overtime", t):
        changes.append({"op": "set_overtime", "value": True, "text": "overtime allowed"})
    if "fair" in t:
        changes.append({"op": "set_priority", "priority": "fairness", "text": "fairness first"})
    if re.search(r"(fewest|minimum|least) (number of )?(people|employees)", t):
        changes.append({"op": "set_priority", "priority": "minimize_affected_employees", "text": "fewest affected"})
    for m in re.finditer(r"\b([A-Z][a-z]+)\b (?:is |was )?also (?:out|unavailable|sick|off)", text):
        changes.append({"op": "add_unavailability", "employee_mention": m.group(1), "date": ds.reference_date and
                        _next_day(ds.reference_date), "date_expression": "tomorrow", "text": m.group(0)})
    for m in re.finditer(r"(?i:(?:don'?t|do not) (?:want to )?(?:use|assign|ask|call in)|exclude|without|avoid|not) "
                         r"([A-Z][a-z]+(?: [A-Z][a-z]+)?)", text):
        changes.append({"op": "exclude_employee", "employee_mention": m.group(1), "text": m.group(0)})
    for m in re.finditer(r"(?i:don'?t|do not) (?:want to )?(?i:move|change|touch) ([A-Z][a-z]+)", text):
        changes.append({"op": "lock_employee", "employee_mention": m.group(1), "text": m.group(0)})
    m = re.search(r"(?:max(?:imum)? )?weekly hours (?:were|was|is|of|at) (\d+)", t)
    if m:
        changes.append({"op": "override_policy", "policy_type": "max_weekly_hours", "value": int(m.group(1)),
                        "text": m.group(0)})
    if re.search(r"\btwo employees\b|\b2 employees\b", t) and not any(c["op"] == "add_unavailability" for c in changes):
        changes.append({"op": "add_unavailability", "employee_mention": None, "count": 2, "text": "two employees"})
    raw = _RawScenario.model_validate({"is_what_if": bool(changes), "changes": changes})
    spec = WhatIfParser(None).resolve(raw, bridge.parse_context(ds))
    spec.raw_request = text
    return spec


def _next_day(d: str) -> str:
    from datetime import date as Date, timedelta
    return (Date.fromisoformat(d) + timedelta(days=1)).isoformat()


def _rule_feedback(text: str, ds: Dataset):
    import re
    from ai.feedback import FeedbackParser, _RawFeedback
    items = []
    scope = "next_reschedule" if re.search(r"next time|this time", text, re.I) else "until_revoked"
    for m in re.finditer(r"(?i:don'?t|do not|never) (?i:assign|use|schedule) ([A-Z][a-z]+)", text):
        items.append({"kind": "avoid_employee", "employee_mention": m.group(1), "scope": scope, "strength": "hard",
                      "text": m.group(0)})
    for m in re.finditer(r"(?i:prefer) (?:using )?([A-Z][a-z]+)", text):
        items.append({"kind": "prefer_employee", "employee_mention": m.group(1), "scope": scope, "strength": "soft",
                      "text": m.group(0)})
    if re.search(r"unless (it'?s )?unavoidable", text, re.I) and "overtime" in text.lower():
        items.append({"kind": "overtime_rule", "overtime_mode": "only_if_unavoidable", "scope": scope,
                      "strength": "soft", "text": "overtime only if unavoidable"})
    elif re.search(r"never (use )?overtime|no overtime", text, re.I):
        items.append({"kind": "overtime_rule", "overtime_mode": "never", "scope": scope, "strength": "hard",
                      "text": "never overtime"})
    for pat, pr in ((r"minim\w* disruption|minimum change", "minimize_changes"), (r"fairness", "fairness"),
                    (r"fewest (people|employees)", "minimize_affected_employees")):
        if re.search(pat, text, re.I):
            items.append({"kind": "objective_priority", "priority": pr, "scope": scope, "strength": "soft",
                          "text": pat})
            break
    return FeedbackParser(None).resolve(_RawFeedback.model_validate({"items": items}), bridge.parse_context(ds))
