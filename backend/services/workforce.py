"""Workforce augmentation: staffing gaps, eligible-employee search, workforce requests, volunteers.

Selection pipeline (spec §21), every step reported per person:

    required skill → certification → availability → existing schedule (double booking, rest)
    → hours limits → ELIGIBLE → soft score (overtime, location, preference) → fairness → ranking

Hard checks reuse ``core.rules`` (the same functions CP-SAT and the validator use). Soft ranking reuses the
fairness engine. Volunteering never assigns anyone and never earns a reward: an admin approves a volunteer,
the assignment is created, and only a completed assignment becomes eligible for Rewards & Recognition.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date as Date
from typing import Any, Optional

from analytics import fairness_engine
from core.models import Availability, Dataset, Disruption, Employee, Shift, normalize_hhmm
from core.rules import blocked_by, conflicts, day_key, effective_limits, gap_hours, week_key

INSUFFICIENT = "No sufficient eligible workforce available."


def spec_shift(spec: dict, sid: str = "__probe__") -> Shift:
    return Shift(id=sid, date=spec["date"], start=normalize_hhmm(spec["start"]), end=normalize_hhmm(spec["end"]),
                 assignment=spec.get("task") or "Additional coverage", department=spec.get("department") or None,
                 required_skills=list(spec.get("skills") or []),
                 required_certifications=list(spec.get("certifications") or []),
                 location=spec.get("location") or None,
                 priority=spec.get("priority") if spec.get("priority") in ("critical", "high", "normal") else "normal")


def _check(name: str, ok: bool, detail: str, kind: str = "hard") -> dict:
    return {"name": name, "status": "pass" if ok else "fail", "detail": detail, "kind": kind}


def evaluate_person(ds: Dataset, e: Employee, shift: Shift, unavailable: list[Availability],
                    assignments: Optional[dict[str, str]] = None, ignore_shift: Optional[str] = None) -> dict:
    """All hard checks for giving ``shift`` to ``e`` on top of the current schedule, plus soft facts."""
    amap = assignments if assignments is not None else ds.assignment_map()
    shifts = {s.id: s for s in ds.shifts}
    mine = [shifts[sid] for sid, eid in amap.items() if eid == e.id and sid in shifts and sid != ignore_shift]
    checks = []
    have = e.qualifications
    miss_skill = [q for q in shift.required_skills if q.lower() not in have]
    miss_cert = [q for q in shift.required_certifications if q.lower() not in have]
    checks.append(_check("Active account", e.status == "active", "active" if e.status == "active" else "deactivated"))
    checks.append(_check("Required skill", not miss_skill,
                         "has " + (", ".join(shift.required_skills) or "no specific skill needed") if not miss_skill
                         else "missing " + ", ".join(miss_skill)))
    checks.append(_check("Certification", not miss_cert,
                         ("holds " + ", ".join(shift.required_certifications)) if shift.required_certifications
                         and not miss_cert else ("none required" if not miss_cert else "missing " + ", ".join(miss_cert))))
    av = blocked_by(shift, [u for u in unavailable if u.employee_id == e.id])
    checks.append(_check("Availability", av is None, "available" if av is None else
                         f"unavailable ({av.reason or av.kind})"))
    overlap = next((s for s in mine if conflicts(shift, s, 0) == "overlap"), None)
    checks.append(_check("No double booking", overlap is None, "no overlap" if overlap is None else
                         f"already on {overlap.assignment} {overlap.start}–{overlap.end}"))
    rest_hours = ds.constraints.min_rest_hours
    rest_clash = next((s for s in mine if conflicts(shift, s, rest_hours) == "rest"), None)
    checks.append(_check("Rest requirement", rest_clash is None,
                         f"at least {rest_hours:g}h rest kept" if rest_clash is None else
                         f"only {gap_hours(shift, rest_clash):g}h rest next to {rest_clash.assignment} "
                         f"(minimum {rest_hours:g}h)"))
    daily, contracted, cap = effective_limits(e, ds.constraints)
    day_h = sum(s.hours for s in mine if day_key(s) == day_key(shift)) + shift.hours
    week_h_before = sum(s.hours for s in mine if week_key(s) == week_key(shift))
    week_h = week_h_before + shift.hours
    checks.append(_check("Daily hours", day_h <= daily + 1e-6, f"{day_h:g}h of max {daily:g}h that day"))
    checks.append(_check("Weekly hours", week_h <= cap + 1e-6, f"{week_h:g}h of max {cap:g}h that week"))
    eligible = all(c["status"] == "pass" for c in checks)
    overtime = max(0.0, week_h - max(contracted, week_h_before))
    loc_match = not (e.location and shift.location and e.location.lower() != shift.location.lower())
    prefs = e.preferences
    pref_ok = not ((shift.shift_type and shift.shift_type in prefs.avoid_shift_types)
                   or (prefs.avoid_weekends and Date.fromisoformat(shift.date).weekday() >= 5))
    prof = fairness_engine.profile(ds, e)
    return {"employee_id": e.id, "employee_name": e.name, "role": e.role, "department": e.department,
            "eligible": eligible, "checks": checks,
            "failed": next((c for c in checks if c["status"] == "fail"), None),
            "weekly_hours_before": round(week_h_before, 2), "weekly_hours_after": round(week_h, 2),
            "overtime_added": round(overtime, 2), "location_match": loc_match, "preference_ok": pref_ok,
            "fairness": {k: prof[k] for k in ("contribution_load", "volunteer_assignments", "additional_assignments",
                                              "emergency_coverage", "weekly_hours", "monthly_hours",
                                              "last_additional_assignment", "window_days")}}


def soft_score(c: dict) -> float:
    """Lower is better. Fairness load dominates, then overtime, then current hours, location, preference."""
    return round(10 * c["fairness"]["contribution_load"] + 6 * c["overtime_added"] + c["weekly_hours_before"] / 4
                 + (0 if c["location_match"] else 4) + (0 if c["preference_ok"] else 3), 2)


def unavailable_records(ds: Dataset, open_disruptions: list[Disruption]) -> list[Availability]:
    return [a for a in ds.availability if a.kind != "preferred_off"] + [d.as_availability() for d in open_disruptions]


def find_candidates(ds: Dataset, spec: dict, open_disruptions: list[Disruption] = (),
                    exclude: tuple[str, ...] = (), assignments: Optional[dict[str, str]] = None,
                    ignore_shift: Optional[str] = None) -> dict:
    shift = spec_shift(spec)
    unav = unavailable_records(ds, list(open_disruptions))
    rows = [evaluate_person(ds, e, shift, unav, assignments, ignore_shift) for e in ds.employees if e.id not in exclude]
    eligible = sorted((r for r in rows if r["eligible"]), key=lambda r: (soft_score(r), r["employee_name"]))
    for i, r in enumerate(eligible):
        r["score"] = soft_score(r)
        r["rank"] = i + 1
        r["soft"] = _soft_notes(r, eligible[0])
    ineligible = [r for r in rows if not r["eligible"]]
    funnel = []
    remaining = list(rows)
    for name in ("Active account", "Required skill", "Certification", "Availability", "No double booking",
                 "Rest requirement", "Daily hours", "Weekly hours"):
        remaining = [r for r in remaining if next(c for c in r["checks"] if c["name"] == name)["status"] == "pass"]
        funnel.append({"stage": name, "remaining": len(remaining)})
    needed = int(spec.get("needed") or 1)
    return {"shift": {"date": shift.date, "start": shift.start, "end": shift.end, "task": shift.assignment,
                      "skills": shift.required_skills, "certifications": shift.required_certifications},
            "eligible": eligible, "ineligible": ineligible, "funnel": funnel, "needed": needed,
            "sufficient": len(eligible) >= needed,
            "message": None if len(eligible) >= needed else INSUFFICIENT}


def _soft_notes(r: dict, best: dict) -> list[dict]:
    notes = []
    f, bf = r["fairness"]["contribution_load"], best["fairness"]["contribution_load"]
    notes.append({"label": "Workload fairness", "status": "good" if f <= bf + 0.5 else "warn",
                  "detail": f"recent extra-work load {f:g}" + ("" if f <= bf + 0.5 else " (higher recent workload)")})
    notes.append({"label": "Overtime", "status": "good" if r["overtime_added"] == 0 else "warn",
                  "detail": "no overtime" if r["overtime_added"] == 0 else f"+{r['overtime_added']:g}h overtime"})
    if not r["location_match"]:
        notes.append({"label": "Location", "status": "warn", "detail": "usually works elsewhere"})
    if not r["preference_ok"]:
        notes.append({"label": "Preference", "status": "warn", "detail": "prefers not to work this shift"})
    return notes


# ---------------------------------------------------------------- staffing gaps

def staffing_gaps(ds: Dataset, open_disruptions: list[Disruption] = ()) -> list[dict]:
    """Tasks whose required headcount exceeds the people actually able to work them.

    A task = shifts with the same assignment and time window. Required headcount = the largest
    ``attributes.required_headcount`` among them, or the number of shift slots."""
    amap = ds.assignment_map()
    emps = {e.id: e for e in ds.employees}
    groups: dict[tuple, list[Shift]] = defaultdict(list)
    for s in ds.shifts:
        groups[(s.assignment, s.date, s.start, s.end)].append(s)
    today = ds.reference_date or ""
    out = []
    for (task, day, start, end), shifts in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][2])):
        if today and day < today:
            continue
        required = max([len(shifts)] + [int(s.attributes.get("required_headcount", 0) or 0) for s in shifts])
        assigned = []
        for s in shifts:
            eid = amap.get(s.id)
            if not eid or emps.get(eid) is None or emps[eid].status != "active":
                continue
            if any(d.employee_id == eid and _overlap(s, d) for d in open_disruptions):
                continue
            assigned.append(eid)
        gap = required - len(assigned)
        if gap <= 0:
            continue
        s0 = shifts[0]
        out.append({"id": f"gap:{task}:{day}:{start}", "task": task, "date": day, "start": start, "end": end,
                    "department": s0.department, "location": s0.location,
                    "skills": sorted({q for s in shifts for q in s.required_skills}),
                    "certifications": sorted({q for s in shifts for q in s.required_certifications}),
                    "required": required, "assigned": len(assigned), "gap": gap,
                    "assigned_ids": assigned,
                    "priority": "critical" if any(s.priority == "critical" for s in shifts) else
                                "high" if gap >= 2 or any(s.priority == "high" for s in shifts) else "normal",
                    "shift_ids": [s.id for s in shifts]})
    return out


def _overlap(shift: Shift, d: Disruption) -> bool:
    from core.rules import overlaps
    return overlaps(shift.window, d.as_availability().window)


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:24] or "task"


def validate_request(body: dict) -> dict:
    """Server-side validation of a workforce request form."""
    errors = []
    for f in ("task", "date", "start", "end"):
        if not str(body.get(f) or "").strip():
            errors.append(f"{f} is required")
    try:
        Date.fromisoformat(str(body.get("date")))
    except ValueError:
        errors.append("date must be YYYY-MM-DD")
    for f in ("start", "end"):
        try:
            body[f] = normalize_hhmm(str(body.get(f)))
        except ValueError:
            errors.append(f"{f} must be 24-hour HH:MM")
    try:
        req, add = int(body.get("required_employees") or 0), int(body.get("additional_needed") or 0)
        if add < 1 or add > 50:
            errors.append("additional employees needed must be between 1 and 50")
        if req and req < add:
            errors.append("required employees can't be fewer than the additional employees needed")
    except (TypeError, ValueError):
        errors.append("employee counts must be whole numbers")
    if body.get("priority", "normal") not in ("critical", "high", "normal"):
        errors.append("priority must be critical, high or normal")
    if errors:
        raise ValueError("; ".join(errors))
    to_list = lambda v: [x.strip() for x in (v if isinstance(v, list) else str(v or "").split(",")) if str(x).strip()]  # noqa: E731
    return {"task": str(body["task"]).strip()[:120], "date": body["date"], "start": body["start"], "end": body["end"],
            "required_employees": int(body.get("required_employees") or body.get("additional_needed")),
            "additional_needed": int(body["additional_needed"]),
            "department": (str(body.get("department") or "").strip() or None),
            "skills": to_list(body.get("skills")), "certifications": to_list(body.get("certifications")),
            "location": (str(body.get("location") or "").strip() or None),
            "priority": body.get("priority", "normal"), "reason": str(body.get("reason") or "").strip()[:500],
            "emergency": bool(body.get("emergency")), "gap_id": body.get("gap_id")}


def as_spec(req: dict) -> dict:
    return {"date": req["date"], "start": req["start"], "end": req["end"], "task": req["task"],
            "skills": req["skills"], "certifications": req["certifications"], "department": req["department"],
            "location": req["location"], "priority": req["priority"], "needed": req["additional_needed"]}


def summary_counts(requests: list[dict]) -> dict[str, Any]:
    return {"open": sum(1 for r in requests if r["status"] in ("open", "partially_filled")),
            "filled": sum(1 for r in requests if r["status"] == "filled"),
            "volunteers": sum(len(r.get("volunteers", [])) for r in requests),
            "assigned": sum(len(r.get("assignments", [])) for r in requests),
            "completed": sum(1 for r in requests for a in r.get("assignments", []) if a["status"] == "completed")}
