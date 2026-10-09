"""Voice assistant brain: intent → answer from ResQWork's live data → optional UI action.

Understanding comes from rules (always available) or Gemini (``gemini_voice``, when configured).
Answers are computed here from the same stored proposals, versions, schedule and requests the
dashboards show, and each reply says which screen to open (``navigate``), so a voice command does what
the matching UI action does. Approve and reject go through ``ResQWork.approve`` / ``reject``.
"""

from __future__ import annotations

import re
from typing import Optional

from ai.resolution import resolve_employee
from ai.schemas import EmployeeRef

from . import voice

RULES: list[tuple[str, re.Pattern]] = [
    ("approve", re.compile(r"\b(approve|accept|go ahead|confirm)\b", re.I)),
    ("reject", re.compile(r"\b(reject|decline|cancel)\b", re.I)),
    ("why_reassigned", re.compile(r"\bwhy (?:was|is|did|were)\s+(.+?)\s+(?:get\s+)?(?:re-?assigned|chosen|selected|"
                                  r"picked|moved|assigned|given)", re.I)),
    ("why_not", re.compile(r"\bwhy (?:not|wasn'?t|isn'?t)\s+([A-Z]?[a-z]+(?:\s+[A-Z][a-z]+)?)", re.I)),
    ("unresolved", re.compile(r"\b(unresolved|can'?t be covered|cannot be covered|impossible|infeasible|"
                              r"conflicts?|constraints?|violations?)\b", re.I)),
    ("affected_employees", re.compile(r"\b(affected|impacted)\b", re.I)),
    ("latest_changes", re.compile(r"\b(what changed|latest (repair|change|schedule)|changes)\b", re.I)),
    ("today_schedule", re.compile(r"\b(today'?s schedule|schedule (for )?today|who(?:'s| is) working|"
                                  r"show (me )?(the )?schedule|roster)\b", re.I)),
    ("requests", re.compile(r"\brequests?\b", re.I)),
    ("disruptions", re.compile(r"\b(disruptions?|absen\w*|who(?:'s| is) (out|off|sick)|what happened)\b", re.I)),
    ("alternatives", re.compile(r"\b(alternatives?|options?|other choices)\b", re.I)),
    ("recommend", re.compile(r"\b(recommend\w*|suggest\w*|repair|what should)\b", re.I)),
    ("status", re.compile(r"\b(status|at risk|coverage|summary|what'?s happening)\b", re.I)),
]

HELP = ("You can ask: show today's schedule, what disruptions are open, what is unresolved, "
        "what is the recommended repair, why was a person reassigned, what changed in the latest repair, "
        "which employees are affected, show pending requests, approve, or reject.")


def detect(utterance: str) -> tuple[str, Optional[str]]:
    for name, pat in RULES:
        m = pat.search(utterance or "")
        if m:
            arg = m.group(1).strip(" ?.!") if name in ("why_reassigned", "why_not") else None
            return name, arg
    return "unknown", None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _match(name: str, employees: list[dict]):
    return resolve_employee(name, [EmployeeRef(id=e["id"], name=e["name"]) for e in employees])


def _best(p: dict) -> Optional[dict]:
    r = p["result"]
    oid = p.get("approved_option") or r.get("recommended_option_id")
    return next((o for o in r["options"] if o["option_id"] == oid), None)


def handle(svc, org: str, actor: str, utterance: str, intent: Optional[str] = None,
           employee: Optional[str] = None) -> dict:
    if intent is None:
        intent, employee = detect(utterance)
    ws = svc.workspace_summary(org)
    domain = ws["domain"]
    p = svc.latest_proposal(org)
    shift_word = voice.term(domain, "shift", "shift").lower()
    action, navigate = None, None

    if intent == "today_schedule":
        rows = svc.schedule(org)
        today = ws.get("reference_date") or (rows[0]["date"] if rows else None)
        todays = [r for r in rows if r["date"] == today]
        risk = [r for r in todays if r["status"] in ("disrupted", "open")]
        changed = [r for r in todays if r["status"] == "changed"]
        listing = "; ".join(f"{r['start']} {r['assignment']}: {r['employee_name'] or 'open'}" for r in todays[:4])
        text = (f"Today, {voice._day(today) if today else 'today'}, there {'is' if len(todays) == 1 else 'are'} "
                f"{_plural(len(todays), shift_word)}. " + (f"{listing}. " if listing else "")
                + (f"{len(todays) - 4} more on screen. " if len(todays) > 4 else "")
                + (f"{_plural(len(risk), shift_word)} at risk. " if risk else "Nothing is at risk. ")
                + (f"{len(changed)} changed by a repair." if changed else ""))
        navigate = {"screen": "schedule"}
    elif intent == "disruptions":
        open_recs = [r for r in svc.store.list("disruption", org) if r["status"] == "open"]
        if not open_recs:
            text = "There are no open disruptions right now. " + voice.ops_summary(domain, svc.dashboard(org)["metrics"])
        else:
            text = f"There {'is' if len(open_recs) == 1 else 'are'} {_plural(len(open_recs), 'open disruption')}. " + \
                   " ".join(voice.manager_alert(domain, r) for r in open_recs[:2])
        navigate = {"screen": "dashboard"}
    elif intent == "unresolved":
        unresolved = p["result"].get("unresolved", []) if p and p["status"] == "pending" else []
        conflicts = [c for c in svc.schedule_conflicts(org) if c["repairable"]]
        parts = [u["summary"] for u in unresolved[:2]]
        if conflicts:
            parts.append(f"{_plural(len(conflicts), 'schedule conflict')} in the current schedule: "
                         + "; ".join(c["message"] for c in conflicts[:2]))
        text = " ".join(parts) if parts else \
            "Nothing is unresolved: every affected shift is covered and no hard rule is broken."
        navigate = {"screen": "repair", "proposal_id": p["id"]} if unresolved else {"screen": "dashboard"}
    elif intent == "why_reassigned":
        text, navigate = _why_reassigned(svc, org, p, employee)
    elif intent == "latest_changes":
        versions = [v for v in svc.versions(org) if v.get("changes")]
        if versions:
            v = versions[0]
            ch = "; ".join(f"{c['assignment']} on {voice._day(c['date'])}: {c.get('from_employee_name') or 'open'} "
                           f"to {c.get('to_employee_name') or 'uncovered'}" for c in v["changes"][:4])
            text = f"Schedule {v['tag']} was published by {v['created_by']}. It changed {_plural(len(v['changes']), 'assignment')}: {ch}."
            if p and p["status"] == "pending":
                text += " A newer repair is waiting for your approval."
            navigate = {"screen": "versions"}
        elif p and p["status"] == "pending" and _best(p):
            b = _best(p)
            text = ("Nothing has been published yet. The pending recommendation would change "
                    + "; ".join(f"{c['assignment']}: {c.get('from_employee_name') or 'open'} to "
                                f"{c.get('to_employee_name') or 'uncovered'}" for c in b["changes"][:4]) + ".")
            navigate = {"screen": "repair", "proposal_id": p["id"]}
        else:
            text = "No repair has been published yet; the schedule is the original one."
    elif intent == "affected_employees":
        if p and _best(p):
            b = _best(p)
            absent = sorted({d["employee_id"] for d in p["result"].get("disruptions", [])})
            names = {e["id"]: e["name"] for e in svc.employees(org)}
            moved = sorted({c["to_employee_name"] for c in b["changes"] if c.get("to_employee_name")})
            out = sorted({c["from_employee_name"] for c in b["changes"] if c.get("from_employee_name")
                          and c.get("from_employee_id") not in absent})
            text = (("Out: " + ", ".join(names.get(a, a) for a in absent) + ". ") if absent else "") + \
                (f"Taking on work: {', '.join(moved)}. " if moved else "") + \
                (f"Coming off a {shift_word}: {', '.join(out)}. " if out else "") + \
                f"{_plural(b['impact']['employees_affected'], 'person')} affected in total" + \
                (" (pending your approval)." if p["status"] == "pending" else f" ({p['status']}).")
            navigate = {"screen": "repair", "proposal_id": p["id"]}
        else:
            text = "No repair has been generated yet, so nobody is affected."
    elif intent == "requests":
        reqs = [r for r in svc.availability_requests(org) if r["status"] in ("pending", "needs_review")]
        text = (f"{_plural(len(reqs), 'request')} waiting: " + "; ".join(
            f"{r['employee_name']}, {r.get('kind', 'unavailable').replace('_', ' ')} on {voice._day(r['date'])}"
            for r in reqs[:3]) + ".") if reqs else "There are no pending employee requests."
        navigate = {"screen": "requests"}
    elif intent in ("recommend", "alternatives", "why_not", "approve", "reject") and p is None:
        text = "There is no repair yet. Report or simulate a disruption first."
    elif intent == "recommend":
        text = voice.recommendation(p)
        navigate = {"screen": "repair", "proposal_id": p["id"]}
    elif intent == "alternatives":
        text = voice.alternatives(p)
        navigate = {"screen": "repair", "proposal_id": p["id"]}
    elif intent == "why_not":
        text = voice.why_not(p, employee or "", svc.employees(org))
        navigate = {"screen": "repair", "proposal_id": p["id"]}
    elif intent == "approve":
        rec = _best(p)
        if p["status"] != "pending":
            text = f"The latest repair is already {p['status']}."
        elif not rec or rec["impact"]["unfilled_shifts"]:
            text = ("I can't approve this by voice: no feasible repair covers every shift. "
                    "Please review the constraint analysis on screen.")
            navigate = {"screen": "repair", "proposal_id": p["id"]}
        else:
            action = svc.approve(org, p["id"], None, actor=f"{actor} (voice)")
            n = len(action["notifications"])
            text = (f"Approved. Schedule {action['version']['tag']} is published and "
                    f"{_plural(n, 'affected employee')} {'have' if n != 1 else 'has'} been notified.")
            navigate = {"screen": "versions"}
    elif intent == "reject":
        if p["status"] != "pending":
            text = f"The latest repair is already {p['status']}."
        else:
            action = svc.reject(org, p["id"], actor=f"{actor} (voice)", reason="Rejected by voice")
            text = "Rejected. The current schedule stays as it is."
    elif intent == "status":
        open_d = [r for r in svc.store.list("disruption", org) if r["status"] == "open"]
        text = voice.manager_alert(domain, open_d[0]) if open_d else voice.ops_summary(domain, svc.dashboard(org)["metrics"])
    else:
        text = HELP
    return {"intent": intent, "employee": employee, "text": text, "action": action, "navigate": navigate}


def _why_reassigned(svc, org: str, p: Optional[dict], name: Optional[str]):
    props = [x for x in svc.store.list("proposal", org, limit=20) if _best(x)]
    if not props:
        return "No repair has assigned anyone yet.", None
    employees = svc.employees(org)
    target_id = None
    if name and name.lower() not in ("this employee", "this person", "they", "he", "she", "them"):
        m = _match(name, employees)
        if m.status != "MATCH":
            return f"I couldn't tell who {name} is. Please say their full name.", None
        target_id = m.employee.id
    for prop in props:                                        # newest first
        b = _best(prop)
        sel = [s for s in b["selected"] if target_id is None or s["employee_id"] == target_id]
        if not sel:
            continue
        s = sel[0]
        skills = ", ".join(s["matched_skills"]) or "the required skills"
        ot = "no overtime" if not s["overtime_hours_added"] else f"{s['overtime_hours_added']:g} hours of overtime"
        rest = f", has {s['rest_hours_before_shift']:g} hours of rest before it" if s.get("rest_hours_before_shift") else ""
        state = {"approved": "was assigned", "pending": "is recommended", "rejected": "was proposed"}[prop["status"]]
        text = (f"{s['employee_name']} {state} to cover {s['covers']} because they hold {skills}, are available "
                f"then{rest}, and their week goes from {s['weekly_hours_before']:g} to {s['weekly_hours_after']:g} "
                f"hours against a {s['max_weekly_hours']:g} hour limit, with {ot}. "
                f"The repair changes {_plural(b['impact']['assignments_changed'], 'assignment')} in total.")
        return text, {"screen": "repair", "proposal_id": prop["id"]}
    who = next((e["name"] for e in employees if e["id"] == target_id), name)
    return f"{who} wasn't reassigned in any recent repair.", None
