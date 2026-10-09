"""Deterministic scheduling rules shared by validation, the solvers and the checker.

Every hard rule lives here exactly once, so the CP-SAT model, the fallback
search and the post-solve validator cannot disagree about what is allowed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable, Optional

from .models import Availability, Dataset, Employee, OrgConstraints, Shift


def missing_qualifications(emp: Employee, shift: Shift) -> list[str]:
    have = emp.qualifications
    return [q for q in shift.required_skills + shift.required_certifications if q.lower() not in have]


def overlaps(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def gap_hours(a: Shift, b: Shift) -> float:
    """Hours between the end of the earlier shift and the start of the later one (negative = overlap)."""
    (s1, e1), (s2, e2) = a.window, b.window
    if s1 > s2:
        (s1, e1), (s2, e2) = (s2, e2), (s1, e1)
    return (s2 - e1).total_seconds() / 3600


def conflicts(a: Shift, b: Shift, min_rest_hours: float) -> Optional[str]:
    """Why one person can't work both shifts, or None."""
    if a.id == b.id:
        return None
    if overlaps(a.window, b.window):
        return "overlap"
    if min_rest_hours > 0 and gap_hours(a, b) < min_rest_hours:
        return "rest"
    return None


def blocked_by(shift: Shift, unavailable: Iterable[Availability]) -> Optional[Availability]:
    for av in unavailable:
        if av.kind in ("unavailable", "leave") and overlaps(shift.window, av.window):
            return av
    return None


def week_key(shift: Shift) -> str:
    y, w, _ = shift.window[0].isocalendar()
    return f"{y}-W{w:02d}"


def day_key(shift: Shift) -> str:
    return shift.date


def effective_limits(emp: Employee, c: OrgConstraints) -> tuple[float, float, float]:
    """(max daily, contracted weekly, max weekly incl. overtime) after org limits."""
    daily = min(emp.max_daily_hours, c.max_daily_hours or emp.max_daily_hours)
    contracted = emp.contracted_weekly_hours
    cap = emp.max_weekly_hours
    if c.max_weekly_hours is not None:
        cap = min(cap, c.max_weekly_hours)
        contracted = min(contracted, cap)
    if not c.allow_overtime:
        cap = min(cap, contracted)
    else:
        cap = min(cap, contracted + c.max_overtime_hours_per_week)
    return daily, contracted, cap


def hours_by(assignments: dict[str, str], shifts: dict[str, Shift], key) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = defaultdict(float)
    for sid, eid in assignments.items():
        s = shifts.get(sid)
        if s is not None and eid:
            out[(eid, key(s))] += s.hours
    return out


def schedule_violations(ds: Dataset, assignments: dict[str, str],
                        unavailable: Optional[Iterable[Availability]] = None,
                        constraints: Optional[OrgConstraints] = None) -> list[dict]:
    """Every hard-rule violation in an assignment (shift_id → employee_id). Empty list = valid.

    ``unavailable`` defaults to the dataset's availability records; the engine passes its own
    list (dataset records + disruptions − what-if removals).
    """
    c = constraints or ds.constraints
    shifts = {s.id: s for s in ds.shifts}
    emps = {e.id: e for e in ds.employees}
    if unavailable is None:
        unavailable = [a for a in ds.availability if a.kind != "preferred_off"]
    unavailable = list(unavailable)
    by_emp: dict[str, list[Shift]] = defaultdict(list)
    out: list[dict] = []

    for sid, eid in assignments.items():
        s, e = shifts.get(sid), emps.get(eid)
        if s is None or e is None:
            out.append({"rule": "unknown_reference", "shift_id": sid, "employee_id": eid})
            continue
        by_emp[eid].append(s)
        miss = missing_qualifications(e, s)
        if miss:
            out.append({"rule": "qualification", "shift_id": sid, "employee_id": eid, "missing": miss})
        av = blocked_by(s, [u for u in unavailable if u.employee_id == eid])
        if av:
            out.append({"rule": "unavailable", "shift_id": sid, "employee_id": eid, "reason": av.reason})

    for eid, lst in by_emp.items():
        lst.sort(key=lambda s: s.window[0])
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                why = conflicts(lst[i], lst[j], c.min_rest_hours)
                if why:
                    out.append({"rule": why, "employee_id": eid, "shift_ids": [lst[i].id, lst[j].id],
                                "gap_hours": round(gap_hours(lst[i], lst[j]), 2)})

    daily = hours_by(assignments, shifts, day_key)
    weekly = hours_by(assignments, shifts, week_key)
    for (eid, day), h in daily.items():
        if eid in emps and h > effective_limits(emps[eid], c)[0] + 1e-6:
            out.append({"rule": "daily_hours", "employee_id": eid, "date": day, "hours": h})
    for (eid, wk), h in weekly.items():
        if eid in emps and h > effective_limits(emps[eid], c)[2] + 1e-6:
            out.append({"rule": "weekly_hours", "employee_id": eid, "week": wk, "hours": h})
    return out
