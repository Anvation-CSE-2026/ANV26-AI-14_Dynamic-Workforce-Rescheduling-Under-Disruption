"""Fairness engine: who has carried extra work recently, with time decay.

Fairness is a SOFT objective. It never makes an ineligible person eligible and never blocks an
eligible one; it only changes the order of people who all pass every hard rule.

Contribution load (higher = has done more extra work recently = should be asked later):

    imported baseline   2 × disruptions absorbed (30d) + schedule changes (30d) + overtime hours (30d) / 4
                        (counters supplied with the data, by definition inside the last 30 days)
    ledger              Σ kind_weight × decay(age) over every dated contribution
                        decay(age) = 0.5 ** (age / half_life), half_life = window / 2
                        × 0.25 more once the contribution is older than the window
    kind_weight         volunteer 1.0 · additional 1.0 · emergency 1.5 · reschedule 0.5 · overtime 0.25

So an employee who volunteered 8 times last week ranks below one who volunteered twice, but
volunteering frequently is not a permanent penalty: three months later those contributions are
worth almost nothing. Reward points are never read here (rewards must not drive scheduling).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date as Date, timedelta
from typing import Iterable, Optional

from core.models import Dataset, Employee

KIND_WEIGHT = {"volunteer": 1.0, "additional": 1.0, "emergency": 1.5, "reschedule": 0.5, "overtime": 0.25}
OUTSIDE_WINDOW_FACTOR = 0.25
WINDOWS = (7, 30, 90)


def decay(age_days: int, window: int) -> float:
    age = max(0, age_days)
    w = 0.5 ** (age / max(1.0, window / 2))
    return w * OUTSIDE_WINDOW_FACTOR if age > window else w


def baseline_load(e: Employee) -> float:
    h = e.history
    return 2 * h.disruptions_absorbed_30d + h.schedule_changes_30d + h.overtime_hours_30d / 4


def ledger_load(e: Employee, today: Date, window: int) -> float:
    total = 0.0
    for c in e.history.contributions:          # assigned extra work counts as workload, done or not yet
        age = (today - Date.fromisoformat(c.date)).days
        total += KIND_WEIGHT.get(c.kind, 1.0) * decay(age, window)
    return total


def contribution_load(e: Employee, today: Date, window: int = 30) -> float:
    return round(baseline_load(e) + ledger_load(e, today, window), 1)


def burden_units(e: Employee, today: Date, window: int, scheduled_hours: float) -> int:
    """Integer cost of giving this person extra work (used by CP-SAT and the search alike).

    2 (base) + 2 × disruptions absorbed + schedule changes + overtime / 4  (imported 30-day counters)
    + round(2 × decayed ledger)  + scheduled hours / 12  (current workload)
    """
    h = e.history
    return (2 + 2 * h.disruptions_absorbed_30d + h.schedule_changes_30d + round(h.overtime_hours_30d / 4)
            + round(2 * ledger_load(e, today, window)) + round(scheduled_hours / 12))


def _hours(ds: Dataset) -> dict[str, list[tuple[Date, float]]]:
    shifts = {s.id: s for s in ds.shifts}
    out: dict[str, list[tuple[Date, float]]] = defaultdict(list)
    for a in ds.existing_schedule:
        s = shifts.get(a.shift_id)
        if s:
            out[a.employee_id].append((Date.fromisoformat(s.date), s.hours))
    return out


def profile(ds: Dataset, e: Employee, window: Optional[int] = None) -> dict:
    """Everything the spec asks the fairness engine to track, for one person."""
    window = window or ds.constraints.fairness_window_days
    today = ds.today
    hours = _hours(ds).get(e.id, [])
    wk_start = today - timedelta(days=today.weekday())
    weekly = sum(h for d, h in hours if wk_start <= d < wk_start + timedelta(days=7))
    monthly = sum(h for d, h in hours if today - timedelta(days=30) <= d <= today + timedelta(days=30))
    in_win = [c for c in e.history.contributions if (today - Date.fromisoformat(c.date)).days <= window]

    def last(kinds: Iterable[str]) -> Optional[str]:
        ds_ = sorted((c.date for c in e.history.contributions if c.kind in kinds and c.completed), reverse=True)
        return ds_[0] if ds_ else None

    return {
        "employee_id": e.id, "employee_name": e.name, "window_days": window,
        "regular_hours": round(sum(h for _, h in hours), 2), "weekly_hours": round(weekly, 2),
        "monthly_hours": round(monthly, 2), "contracted_weekly_hours": e.contracted_weekly_hours,
        "overtime_hours": round(max(0.0, weekly - e.contracted_weekly_hours) + e.history.overtime_hours_30d, 2),
        "additional_assignments": sum(1 for c in in_win if c.kind == "additional")
                                  + e.history.disruptions_absorbed_30d,
        "volunteer_assignments": sum(1 for c in in_win if c.kind == "volunteer"),
        "completed_volunteer_assignments": sum(1 for c in in_win if c.kind == "volunteer" and c.completed),
        "emergency_coverage": sum(1 for c in in_win if c.kind == "emergency"),
        "recent_reschedules": sum(1 for c in in_win if c.kind == "reschedule") + e.history.schedule_changes_30d,
        "recent_additional_hours": round(sum(c.hours for c in in_win if c.kind != "reschedule"), 2),
        "last_additional_assignment": last(("additional", "volunteer")),
        "last_emergency_assignment": last(("emergency",)),
        "contribution_load": contribution_load(e, today, window),
        "older_contributions": sum(1 for c in e.history.contributions
                                   if (today - Date.fromisoformat(c.date)).days > window),
    }


def rank(ds: Dataset, employee_ids: Iterable[str], window: Optional[int] = None) -> list[dict]:
    """Fairness order among already-eligible people: lowest recent load first, then lower hours."""
    rows = [profile(ds, e, window) for e in ds.employees if e.id in set(employee_ids)]
    rows.sort(key=lambda r: (r["contribution_load"], r["weekly_hours"], r["employee_name"]))
    for i, r in enumerate(rows):
        r["fairness_rank"] = i + 1
    return rows


def team_distribution(ds: Dataset, window: Optional[int] = None) -> list[dict]:
    return sorted((profile(ds, e, window) for e in ds.employees if e.status == "active"),
                  key=lambda r: -r["contribution_load"])
