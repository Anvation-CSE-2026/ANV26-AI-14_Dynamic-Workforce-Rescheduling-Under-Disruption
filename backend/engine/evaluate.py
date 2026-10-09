"""Score and measure any assignment of a repair problem.

Single source of truth for the objective: the fallback search optimizes
``cost()`` directly, and the CP-SAT model encodes the same terms (see
``solver_cpsat``). Every option shown to a manager is also run through
``core.rules.schedule_violations`` here; an option with any hard-rule
violation is never returned.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as Date
from typing import Optional

from analytics.fairness_engine import burden_units
from analytics.metrics import FairnessMetrics, ImpactMetrics, fairness, impact
from core.rules import conflicts, day_key, schedule_violations, week_key

from .problem import RepairProblem

Assignment = dict[str, Optional[str]]   # decision slot → employee id (None = left uncovered)

MULTIPLIERS: dict[str, dict[str, float]] = {
    "recommended":   {},
    "min_employees": {"employee_affected": 10.0, "assignment_change": 0.6},
    "min_overtime":  {"overtime_hour": 25.0},
    "max_fairness":  {"fairness": 20.0, "assignment_change": 0.6, "overtime_hour": 5.0},
}


def weights(p: RepairProblem, strategy: str) -> dict[str, float]:
    w = p.dataset.optimization.weights.model_dump()
    for k, m in MULTIPLIERS.get(strategy, {}).items():
        w[k] = w[k] * m
    for k, m in p.settings.weight_multipliers.items():
        if k in w:
            w[k] = w[k] * m
    return w


def fairness_units(p: RepairProblem, eid: str) -> int:
    """Integer 'burden' of giving this person extra work (see analytics.fairness_engine.burden_units):
    imported 30-day counters + time-decayed contribution ledger + current scheduled hours / 12."""
    cache = p.__dict__.setdefault("_units", {})
    if eid not in cache:
        scheduled = sum(p.shifts[sid].hours for sid, e in p.original.items() if e == eid)
        cache[eid] = burden_units(p.employees[eid], p.dataset.today, p.constraints.fairness_window_days, scheduled)
    return cache[eid]


def location_mismatch(p: RepairProblem, eid: str, sid: str) -> bool:
    """Soft: the person normally works somewhere else (both locations known and different)."""
    a, b = p.employees[eid].location, p.shifts[sid].location
    return bool(a and b and a.strip().lower() != b.strip().lower())


def lacks_continuity(p: RepairProblem, eid: str, sid: str) -> bool:
    """Soft: the person doesn't already work this assignment anywhere in the existing schedule."""
    cache = p.__dict__.setdefault("_continuity", None)
    if cache is None:
        cache = {(e, p.shifts[s].assignment) for s, e in p.original.items()}
        p.__dict__["_continuity"] = cache
    return (eid, p.shifts[sid].assignment) not in cache


def preference_violation(p: RepairProblem, eid: str, sid: str) -> bool:
    e, s = p.employees[eid], p.shifts[sid]
    prefs = e.preferences
    if s.shift_type and s.shift_type in prefs.avoid_shift_types:
        return True
    return prefs.avoid_weekends and Date.fromisoformat(s.date).weekday() >= 5


def full_assignment(p: RepairProblem, a: Assignment) -> dict[str, str]:
    out = dict(p.frozen)
    out.update({sid: eid for sid, eid in a.items() if eid})
    return out


def original_assignment(p: RepairProblem) -> dict[str, str]:
    return dict(p.original)


def _key(v: dict) -> str:
    return repr(sorted((k, str(x)) for k, x in v.items() if k != "hours"))


def baseline_violations(p: RepairProblem) -> set[str]:
    """Pre-existing problems in the part of the schedule the repair doesn't touch.

    The original schedule minus vacated slots is the baseline; a repair is judged only
    on violations it introduces, so a data warning elsewhere can't block every option.
    """
    cached = getattr(p, "_baseline", None)
    if cached is None:
        base = {sid: eid for sid, eid in p.original.items() if sid not in p.vacated}
        cached = {_key(v) for v in schedule_violations(p.dataset, base, p.unavailable, p.constraints)}
        p._baseline = cached
    return cached


@dataclass
class Evaluation:
    cost: float
    violations: list[dict]
    changed_slots: list[str]
    new_assignments: list[tuple[str, str]]       # (slot, employee) not in the original
    affected: list[str]
    overtime_added: dict[str, float]             # employee → hours added this run
    weekly_hours: dict[str, float]
    unfilled: list[str]
    preference_violations: list[tuple[str, str]]
    breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.violations


def _fast_violations(p: RepairProblem, full: dict[str, str], new: list[tuple[str, str]]) -> list[dict]:
    """Hard-rule check limited to people who gained shifts (losing a shift can't break a rule).

    Mirrors the CP-SAT constraints exactly: pairwise overlap/rest, daily cap, weekly cap
    (never below the person's original hours for that week).
    """
    out: list[dict] = []
    by_emp: dict[str, list[str]] = defaultdict(list)
    for sid, eid in full.items():
        by_emp[eid].append(sid)
    gained: dict[str, list[str]] = defaultdict(list)
    for sid, eid in new:
        gained[eid].append(sid)
    for eid, sids in gained.items():
        mine = by_emp[eid]
        seen = set()
        for ns in sids:
            for o in mine:
                pair = tuple(sorted((ns, o)))
                if o == ns or pair in seen:
                    continue
                seen.add(pair)
                why = conflicts(p.shifts[ns], p.shifts[o], p.constraints.min_rest_hours)
                if why:
                    out.append({"rule": why, "employee_id": eid, "shift_ids": list(pair)})
        daily, _, cap = p.limits(eid)
        day_h, week_h, orig_w = defaultdict(float), defaultdict(float), defaultdict(float)
        for sid in mine:
            day_h[day_key(p.shifts[sid])] += p.shifts[sid].hours
            week_h[week_key(p.shifts[sid])] += p.shifts[sid].hours
        for sid, e in p.original.items():
            if e == eid and sid not in p.settings.release_shift_ids:   # released hours don't grandfather a cap
                orig_w[week_key(p.shifts[sid])] += p.shifts[sid].hours
        touched_days = {day_key(p.shifts[s]) for s in sids}
        touched_weeks = {week_key(p.shifts[s]) for s in sids}
        for d in touched_days:
            if day_h[d] > daily + 1e-6:
                out.append({"rule": "daily_hours", "employee_id": eid, "date": d, "hours": day_h[d]})
        for wk in touched_weeks:
            if week_h[wk] > max(cap, orig_w[wk]) + 1e-6:
                out.append({"rule": "weekly_hours", "employee_id": eid, "week": wk, "hours": week_h[wk]})
    return out


@dataclass
class _Components:
    violations: list[dict]
    changed: list[str]
    new: list[tuple[str, str]]
    affected: list[str]
    ot_added: dict[str, float]
    weekly: dict[str, float]
    unfilled: list[str]
    prefs: list[tuple[str, str]]
    units: int
    location: int
    continuity: int


def _components(p: RepairProblem, a: Assignment) -> _Components:
    cache = p.__dict__.setdefault("_eval_cache", {})
    key = tuple(a.get(s) for s in p.slots)
    if key in cache:
        return cache[key]
    full = full_assignment(p, a)
    changed, new, affected, unfilled, prefs = [], [], set(), [], []
    for sid in p.slots:
        orig, now = p.original.get(sid), a.get(sid)
        if now is None:
            if orig is not None or sid in p.vacated:   # was covered before (or must be covered) → a gap
                unfilled.append(sid)
            continue
        if now != orig:
            changed.append(sid)
            new.append((sid, now))
            affected.add(now)
            if orig and sid not in p.vacated:
                affected.add(orig)
            if preference_violation(p, now, sid):
                prefs.append((sid, now))
    violations = []
    for sid, eid in a.items():
        if eid and eid not in p.candidates[sid]:
            reason = p.excluded.get((sid, eid))
            violations.append({"rule": "ineligible", "shift_id": sid, "employee_id": eid,
                               "reason": reason.code if reason else "unknown"})
    violations += _fast_violations(p, full, new)

    shifts = p.shifts
    orig_week, new_week = defaultdict(float), defaultdict(float)
    for sid, eid in p.original.items():
        if sid not in p.settings.release_shift_ids:
            orig_week[(eid, week_key(shifts[sid]))] += shifts[sid].hours
    for sid, eid in full.items():
        new_week[(eid, week_key(shifts[sid]))] += shifts[sid].hours
    ot_added: dict[str, float] = defaultdict(float)
    for (eid, wk), h in new_week.items():
        _, contracted, _ = p.limits(eid)
        base = max(contracted, orig_week.get((eid, wk), 0.0))
        if h > base + 1e-9:
            ot_added[eid] += h - base
    weekly = defaultdict(float)
    for (eid, _), h in new_week.items():
        weekly[eid] = max(weekly[eid], h)
    comp = _Components(violations, changed, new, sorted(affected), dict(ot_added), dict(weekly), unfilled, prefs,
                       sum(fairness_units(p, eid) for _, eid in new),
                       sum(1 for sid, eid in new if location_mismatch(p, eid, sid)),
                       sum(1 for sid, eid in new if lacks_continuity(p, eid, sid)))
    cache[key] = comp
    return comp


def evaluate(p: RepairProblem, a: Assignment, strategy: str = "recommended", full_check: bool = False) -> Evaluation:
    """Cost + measurements. ``full_check`` re-validates the whole schedule against core.rules (used
    on every option before it is shown); the default fast check is what the search uses."""
    c = _components(p, a)
    w = weights(p, strategy)
    avoid, prefer = set(p.settings.avoid_employee_ids), set(p.settings.prefer_employee_ids)
    terms = {
        "unfilled": w["unfilled"] * len(c.unfilled),
        "assignment_change": w["assignment_change"] * len(c.changed),
        "employee_affected": w["employee_affected"] * len(c.affected),
        "overtime": w["overtime_hour"] * sum(c.ot_added.values()),
        "fairness": w["fairness"] * c.units,
        "preference": w["preference"] * len(c.prefs),
        "location": w.get("location", 0) * c.location,
        "continuity": w.get("continuity", 0) * c.continuity,
        "manager_feedback": sum(2 * w["assignment_change"] for _, eid in c.new if eid in avoid)
                            - sum(5 * w["preference"] for _, eid in c.new if eid in prefer),
    }
    violations = list(c.violations)
    if full_check:
        full = full_assignment(p, a)
        violations += [v for v in schedule_violations(p.dataset, full, p.unavailable, p.constraints)
                       if _key(v) not in baseline_violations(p)]
    return Evaluation(cost=round(sum(terms.values()), 3), violations=violations, changed_slots=c.changed,
                      new_assignments=c.new, affected=c.affected, overtime_added=c.ot_added,
                      weekly_hours=c.weekly, unfilled=c.unfilled, preference_violations=c.prefs,
                      breakdown={k: round(v, 2) for k, v in terms.items()})


def measure(p: RepairProblem, a: Assignment, ev: Evaluation) -> tuple[ImpactMetrics, FairnessMetrics]:
    full = full_assignment(p, a)
    horizon = len(p.slots)
    qualified = sum(1 for sid in p.slots if a.get(sid))
    depts = [p.shifts[sid].department or p.shifts[sid].assignment for sid in ev.changed_slots + ev.unfilled]
    imp = impact(changed=len(ev.changed_slots), affected=len(ev.affected),
                 overtime_added=sum(ev.overtime_added.values()), unfilled=len(ev.unfilled), horizon=horizon,
                 skill_coverage_pct=100 * qualified / max(1, horizon), departments=depts)

    week_hours = defaultdict(float)
    for sid, eid in full.items():
        week_hours[eid] += p.shifts[sid].hours
    weekly = [week_hours.get(e, 0.0) for e in p.employees]
    overtime = []
    for eid in p.employees:
        _, contracted, _ = p.limits(eid)
        overtime.append(max(0.0, week_hours.get(eid, 0.0) - contracted))
    fair = fairness(weekly_hours=weekly, overtime_hours=overtime,
                    new_assignee_disruptions=[p.employees[e].history.disruptions_absorbed_30d
                                              for _, e in ev.new_assignments],
                    new_assignments=len(ev.new_assignments), preference_violations=len(ev.preference_violations))
    return imp, fair


def daily_hours(p: RepairProblem, a: Assignment, eid: str, day: str) -> float:
    return sum(p.shifts[sid].hours for sid, e in full_assignment(p, a).items()
               if e == eid and day_key(p.shifts[sid]) == day)
