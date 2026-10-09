"""Generic KPI and widget computations; domain configs choose which to show and what to call them.

All values are computed from the current schedule, open disruptions and the
engine's rules, with no placeholder numbers. "Future" means shifts that have not
started relative to the dataset's reference date/time.
"""

from __future__ import annotations

from datetime import date as Date

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from core.models import Availability, Dataset, Disruption, interval
from core.rules import blocked_by, conflicts, effective_limits, missing_qualifications, week_key


def _now(ds: Dataset) -> datetime:
    if ds.reference_date:
        return interval(ds.reference_date, ds.reference_time or "00:00", "23:59")[0]
    return min((s.window[0] for s in ds.shifts), default=datetime.min)


def compute(ds: Dataset, open_disruptions: list[Disruption]) -> dict[str, Any]:
    now = _now(ds)
    amap = ds.assignment_map()
    emps = {e.id: e for e in ds.employees}
    unavailable: list[Availability] = [a for a in ds.availability if a.kind != "preferred_off"]
    unavailable += [d.as_availability() for d in open_disruptions]
    future = [s for s in ds.shifts if s.window[0] >= now]

    at_risk, uncovered, qualified_ok, covered = [], [], 0, 0
    for s in future:
        eid = amap.get(s.id)
        if not eid:
            uncovered.append(s)
            continue
        if blocked_by(s, [u for u in unavailable if u.employee_id == eid]):
            at_risk.append(s)
            continue
        covered += 1
        if not missing_qualifications(emps[eid], s):
            qualified_ok += 1

    window_end = now + timedelta(hours=48)
    out_ids = {u.employee_id for u in unavailable if u.window[0] < window_end and u.window[1] > now}
    available = len([e for e in ds.employees if e.id not in out_ids])

    weekly = defaultdict(float)
    wk_now = None
    for s in ds.shifts:
        eid = amap.get(s.id)
        if eid:
            weekly[(eid, week_key(s))] += s.hours
    if future:
        wk_now = week_key(future[0])
    week_hours = {eid: h for (eid, wk), h in weekly.items() if wk == wk_now} if wk_now else {}
    overtime = sum(max(0.0, h - effective_limits(emps[e], ds.constraints)[1]) for e, h in week_hours.items() if e in emps)

    holders = Counter()
    for s in future:
        reqs = tuple(sorted(r.lower() for r in s.required_skills + s.required_certifications))
        if reqs and reqs not in holders:
            holders[reqs] = sum(1 for e in ds.employees if not missing_qualifications(e, s))
    skill_gap = sum(1 for s in future if holders.get(tuple(sorted(r.lower() for r in s.required_skills
                                                                   + s.required_certifications)), 99) <= 1)

    by_emp = defaultdict(list)
    for s in ds.shifts:
        if amap.get(s.id):
            by_emp[amap[s.id]].append(s)
    conflicts_n, fatigue = 0, set()
    for eid, lst in by_emp.items():
        lst.sort(key=lambda z: z.window[0])
        for a, b in zip(lst, lst[1:]):
            why = conflicts(a, b, 0)
            if why == "overlap":
                conflicts_n += 1
            gap = (b.window[0] - a.window[1]).total_seconds() / 3600
            if 0 <= gap < ds.constraints.min_rest_hours + 2 and b.window[0] >= now:
                fatigue.add(eid)
        if week_hours.get(eid, 0) >= effective_limits(emps[eid], ds.constraints)[1] and eid in emps:
            fatigue.add(eid)

    def pct(a: int, b: int) -> float:
        return round(100.0 * a / b, 1) if b else 100.0

    oncall = [s for s in future if s.attributes.get("on_call")]
    oncall_ok = [s for s in oncall if s not in at_risk and amap.get(s.id)]
    risk_set = at_risk + uncovered
    return {
        "coverage_pct": {"value": pct(covered, len(future)), "unit": "%"},
        "at_risk_assignments": {"value": len(at_risk)},
        "uncovered_shifts": {"value": len(risk_set)},
        "critical_uncovered": {"value": sum(1 for s in risk_set if s.priority == "critical")},
        "at_risk_departments": {"value": len({s.department or s.assignment for s in risk_set}),
                                "items": sorted({s.department or s.assignment for s in risk_set})},
        "available_staff": {"value": available, "total": len(ds.employees)},
        "active_disruptions": {"value": len(open_disruptions)},
        "overtime_hours": {"value": round(overtime, 1), "unit": "h"},
        "skill_coverage_pct": {"value": pct(qualified_ok, covered), "unit": "%"},
        "skill_gap_count": {"value": skill_gap},
        "avg_weekly_hours": {"value": round(sum(week_hours.values()) / max(1, len(week_hours)), 1), "unit": "h"},
        "schedule_conflicts": {"value": conflicts_n},
        "oncall_coverage_pct": {"value": pct(len(oncall_ok), len(oncall)), "unit": "%"},
        "deadline_risk": {"value": sum(1 for s in risk_set if s.attributes.get("deadline") or s.priority == "critical")},
        "route_risk": {"value": sum(1 for s in risk_set if s.attributes.get("route"))},
        "fatigue_risk_count": {"value": len(fatigue), "items": sorted(emps[e].name for e in fatigue if e in emps)},
    }


def widgets(ds: Dataset, open_disruptions: list[Disruption], history: list[dict]) -> dict[str, Any]:
    now = _now(ds)
    amap = ds.assignment_map()
    emps = {e.id: e for e in ds.employees}
    unavailable = [a for a in ds.availability if a.kind != "preferred_off"] + \
                  [d.as_availability() for d in open_disruptions]
    future = [s for s in ds.shifts if s.window[0] >= now]
    dept_names = {d.id: d.name for d in ds.departments}

    dept = defaultdict(lambda: {"covered": 0, "total": 0, "at_risk": 0})
    for s in future:
        key = s.department or s.assignment
        dept[key]["total"] += 1
        eid = amap.get(s.id)
        if eid and blocked_by(s, [u for u in unavailable if u.employee_id == eid]):
            dept[key]["at_risk"] += 1
        elif eid:
            dept[key]["covered"] += 1

    demand = Counter(r for s in future for r in s.required_skills + s.required_certifications)
    supply = Counter(q for e in ds.employees for q in set(e.skills + e.certifications))

    week_hours = defaultdict(float)
    wk_now = week_key(future[0]) if future else None
    for s in ds.shifts:
        if amap.get(s.id) and week_key(s) == wk_now:
            week_hours[amap[s.id]] += s.hours

    fatigue = []
    by_emp = defaultdict(list)
    for s in ds.shifts:
        if amap.get(s.id):
            by_emp[amap[s.id]].append(s)
    for eid, lst in by_emp.items():
        lst.sort(key=lambda z: z.window[0])
        for a, b in zip(lst, lst[1:]):
            gap = (b.window[0] - a.window[1]).total_seconds() / 3600
            if 0 <= gap < ds.constraints.min_rest_hours + 2 and b.window[0] >= now:
                fatigue.append({"employee_id": eid, "employee": emps[eid].name,
                                "reason": f"{gap:g}h rest before {b.assignment} ({b.date})"})
        _, contracted, cap = effective_limits(emps[eid], ds.constraints)
        if week_hours.get(eid, 0) >= contracted:
            fatigue.append({"employee_id": eid, "employee": emps[eid].name,
                            "reason": f"{week_hours[eid]:g}h scheduled this week (contracted {contracted:g}h)"})

    return {
        "department_coverage": [{"department": dept_names.get(k, k), **v} for k, v in sorted(dept.items())],
        "qualification_matrix": [{"skill": k, "demand": demand[k], "holders": supply.get(k, 0)}
                                 for k in sorted(set(demand) | set(ds.skills)) if k],
        "fatigue_risk": fatigue,
        "overtime_by_person": sorted(
            [{"employee_id": e.id, "employee": e.name, "hours": round(week_hours.get(e.id, 0), 1),
              "contracted": effective_limits(e, ds.constraints)[1],
              "overtime": round(max(0.0, week_hours.get(e.id, 0) - effective_limits(e, ds.constraints)[1]), 1)}
             for e in ds.employees], key=lambda r: -r["hours"]),
        "workload_balance": [{"employee": e.name, "hours": round(week_hours.get(e.id, 0), 1)} for e in ds.employees],
        "fairness_distribution": [{"employee": e.name, "disruptions_absorbed_30d": e.history.disruptions_absorbed_30d
                                   + sum(1 for c in e.history.contributions
                                         if 0 <= (ds.today - Date.fromisoformat(c.date)).days <= 30),
                                   "schedule_changes_30d": e.history.schedule_changes_30d,
                                   "overtime_hours_30d": e.history.overtime_hours_30d} for e in ds.employees],
        "disruption_history": history,
    }
