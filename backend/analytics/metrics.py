"""Impact and fairness metrics: documented formulas, no hidden constants.

Scheduling impact (0–100, lower is better):
    points = 1.0 × assignments changed
           + 0.5 × employees affected beyond the first
           + overtime hours added / 8
           + 3.0 × shifts left uncovered
    impact % = min(100, 100 × points / shifts in the repair horizon)
    LOW < 15 ≤ MEDIUM < 35 ≤ HIGH

Fairness (0–100, higher is better), over the employees in the dataset:
    workload balance     = 100 × (1 − coefficient of variation of weekly hours), clipped
    overtime distribution= 100 × (1 − Gini of overtime hours); 100 when nobody has overtime
    change concentration = 100 − 15 × mean recent disruptions (30d) of the people given new work
    preference respect   = 100 × (1 − preference violations / new assignments)
    fairness score       = 0.35·workload + 0.25·overtime + 0.25·concentration + 0.15·preferences
"""

from __future__ import annotations

import statistics
from typing import Iterable

from pydantic import BaseModel


class ImpactMetrics(BaseModel):
    impact_score: float
    impact_level: str
    assignments_changed: int
    employees_affected: int
    overtime_hours_added: float
    unfilled_shifts: int
    horizon_shifts: int
    preservation_rate: float
    skill_coverage_pct: float
    departments_affected: list[str]
    formula: str = "100 × (changes + 0.5·(affected−1) + overtime/8 + 3·unfilled) / horizon shifts"


class FairnessMetrics(BaseModel):
    fairness_score: float
    workload_balance: float
    overtime_distribution: float
    change_concentration: float
    preference_respect: float
    preference_violations: int


def impact(changed: int, affected: int, overtime_added: float, unfilled: int, horizon: int,
           skill_coverage_pct: float, departments: Iterable[str]) -> ImpactMetrics:
    points = changed + 0.5 * max(0, affected - 1) + overtime_added / 8 + 3 * unfilled
    score = round(min(100.0, 100 * points / max(1, horizon)), 1)
    level = "LOW" if score < 15 else "MEDIUM" if score < 35 else "HIGH"
    return ImpactMetrics(impact_score=score, impact_level=level, assignments_changed=changed,
                         employees_affected=affected, overtime_hours_added=round(overtime_added, 2),
                         unfilled_shifts=unfilled, horizon_shifts=horizon,
                         preservation_rate=round(100 * (1 - changed / max(1, horizon)), 1),
                         skill_coverage_pct=round(skill_coverage_pct, 1),
                         departments_affected=sorted(set(d for d in departments if d)))


def _gini(values: list[float]) -> float:
    vals = sorted(v for v in values if v >= 0)
    n, total = len(vals), sum(vals)
    if n == 0 or total == 0:
        return 0.0
    cum = sum((i + 1) * v for i, v in enumerate(vals))
    return (2 * cum) / (n * total) - (n + 1) / n


def fairness(weekly_hours: list[float], overtime_hours: list[float], new_assignee_disruptions: list[int],
             new_assignments: int, preference_violations: int) -> FairnessMetrics:
    active = [h for h in weekly_hours if h > 0] or [0.0]
    mean = statistics.fmean(active)
    cv = (statistics.pstdev(active) / mean) if mean > 0 else 0.0
    workload = max(0.0, min(100.0, 100 * (1 - cv)))
    overtime = 100.0 if sum(overtime_hours) == 0 else max(0.0, 100 * (1 - _gini(overtime_hours)))
    conc = 100.0 if not new_assignee_disruptions else max(0.0, 100 - 15 * statistics.fmean(new_assignee_disruptions))
    pref = 100.0 if new_assignments == 0 else max(0.0, 100 * (1 - preference_violations / new_assignments))
    score = 0.35 * workload + 0.25 * overtime + 0.25 * conc + 0.15 * pref
    return FairnessMetrics(fairness_score=round(score, 1), workload_balance=round(workload, 1),
                           overtime_distribution=round(overtime, 1), change_concentration=round(conc, 1),
                           preference_respect=round(pref, 1), preference_violations=preference_violations)
