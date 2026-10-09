"""Turn a dataset + disruption(s) + run settings into a repair problem.

The problem is solver-independent: CP-SAT and the fallback search both read
it, and ``engine.evaluate`` scores any assignment against it. Static
eligibility is computed once here, with a human-readable reason for every
(shift, employee) pair that is ruled out, so "why not X?" answers come
from the same rules the solver used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.models import Availability, Dataset, Disruption, Employee, OrgConstraints, Shift, interval
from core.rules import blocked_by, conflicts, effective_limits, missing_qualifications

Strategy = Literal["recommended", "min_employees", "min_overtime", "max_fairness"]

STRATEGY_INFO: dict[str, dict[str, str]] = {
    "recommended": {"label": "Option A", "title": "Recommended",
                    "goal": "Best overall balance: fewest changes, then overtime, fairness and preferences."},
    "min_employees": {"label": "Option B", "title": "Lowest employee impact",
                      "goal": "Touch as few people's schedules as possible."},
    "min_overtime": {"label": "Option C", "title": "Lowest overtime",
                     "goal": "Avoid overtime first, even if more shifts move."},
    "max_fairness": {"label": "Option D", "title": "Highest fairness",
                     "goal": "Give extra work to people who have absorbed the least disruption."},
}


class RunSettings(BaseModel):
    """Everything a manager, a what-if, feedback or policy can change for one run."""

    locked_employee_ids: list[str] = Field(default_factory=list)
    excluded_employee_ids: list[str] = Field(default_factory=list, description="hard: never newly assigned")
    avoid_employee_ids: list[str] = Field(default_factory=list, description="soft: penalized (manager feedback)")
    prefer_employee_ids: list[str] = Field(default_factory=list, description="soft: small bonus")
    allow_overtime: Optional[bool] = None
    removed_unavailability: list[str] = Field(default_factory=list, description="employee ids available after all")
    constraint_overrides: dict[str, float | bool] = Field(
        default_factory=dict, description="min_rest_hours, max_daily_hours, max_weekly_hours, "
                                          "max_overtime_hours_per_week, allow_overtime")
    extra_required_skills: dict[str, list[str]] = Field(
        default_factory=dict, description="'*', department or assignment → skills required (policy / ad hoc)")
    freeze_before: Optional[str] = Field(default=None, description="ISO datetime; shifts starting earlier are fixed")
    allowed_departments: list[str] = Field(default_factory=list, description="replacements only from these (ad hoc)")
    weight_multipliers: dict[str, float] = Field(default_factory=dict, description="e.g. {'preference': 10}")
    release_shift_ids: dict[str, str] = Field(
        default_factory=dict, description="shift id → why its current assignee must come off it (schedule conflict)")
    cover_shift_ids: list[str] = Field(default_factory=list, description="open shifts that must be covered")


@dataclass
class Exclusion:
    code: str          # UNAVAILABLE, MISSING_SKILL, SHIFT_OVERLAP, REST_PERIOD_VIOLATION, EXCLUDED_BY_MANAGER,
    #                    LOCKED_BY_MANAGER, SCHEDULE_CONFLICT (current assignee must come off: double-booked etc.)
    detail: str


@dataclass
class RepairProblem:
    dataset: Dataset
    disruptions: list[Disruption]
    settings: RunSettings
    constraints: OrgConstraints
    shifts: dict[str, Shift]
    employees: dict[str, Employee]
    original: dict[str, str]                 # shift_id → employee_id (existing schedule)
    frozen: dict[str, str]                   # fixed assignments (already started / out of horizon)
    slots: list[str]                         # decision shifts (ordered)
    candidates: dict[str, list[str]]         # slot → eligible employee ids
    excluded: dict[tuple[str, str], Exclusion] = field(default_factory=dict)
    unavailable: list[Availability] = field(default_factory=list)
    vacated: list[str] = field(default_factory=list)   # slots whose original assignee can no longer work them
    requirements: dict[str, list[str]] = field(default_factory=dict)
    grandfathered: list[tuple[str, str, str]] = field(default_factory=list)  # (slot, employee, pre-existing issue)

    def employee_name(self, eid: Optional[str]) -> str:
        e = self.employees.get(eid or "")
        return e.name if e else (eid or "nobody")

    def limits(self, eid: str) -> tuple[float, float, float]:
        return effective_limits(self.employees[eid], self.constraints)


def _merge_constraints(base: OrgConstraints, overrides: dict) -> OrgConstraints:
    data = base.model_dump()
    for k, v in overrides.items():
        if k in data and v is not None:
            data[k] = v
    return OrgConstraints.model_validate(data)


def build_problem(ds: Dataset, disruptions: list[Disruption], settings: Optional[RunSettings] = None) -> RepairProblem:
    settings = settings or RunSettings()
    overrides = dict(settings.constraint_overrides)
    if settings.allow_overtime is not None:
        overrides["allow_overtime"] = settings.allow_overtime
    constraints = _merge_constraints(ds.constraints, overrides)

    shifts = {s.id: s for s in ds.shifts}
    employees = {e.id: e for e in ds.employees}
    original = ds.assignment_map()
    removed = set(settings.removed_unavailability)

    unavailable = [a for a in ds.availability if a.kind != "preferred_off" and a.employee_id not in removed]
    unavailable += [d.as_availability() for d in disruptions if d.employee_id not in removed]

    if settings.freeze_before:
        freeze = datetime.fromisoformat(settings.freeze_before)
    elif ds.reference_date:
        freeze = interval(ds.reference_date, ds.reference_time or "00:00", "23:59")[0]
    else:
        freeze = datetime.min

    frozen = {sid: eid for sid, eid in original.items() if shifts[sid].window[0] < freeze}
    slots = sorted((sid for sid, s in shifts.items() if s.window[0] >= freeze),
                   key=lambda sid: (shifts[sid].window[0], sid))

    def reqs(s: Shift) -> list[str]:
        extra = settings.extra_required_skills
        out = list(dict.fromkeys(s.required_skills + s.required_certifications + extra.get("*", [])
                                 + extra.get(s.department or "", []) + extra.get(s.assignment, [])))
        return out

    locked = set(settings.locked_employee_ids)
    excluded_ids = set(settings.excluded_employee_ids)
    p = RepairProblem(dataset=ds, disruptions=disruptions, settings=settings, constraints=constraints,
                      shifts=shifts, employees=employees, original=original, frozen=frozen, slots=slots,
                      candidates={}, unavailable=unavailable)

    frozen_by_emp: dict[str, list[Shift]] = {}
    for sid, eid in frozen.items():
        frozen_by_emp.setdefault(eid, []).append(shifts[sid])

    for sid in slots:
        s = shifts[sid]
        required = reqs(s)
        p.requirements[sid] = required
        orig = original.get(sid)
        cands = []
        for eid, e in employees.items():
            have = e.qualifications
            miss = [q for q in required if q.lower() not in have]
            av = blocked_by(s, [u for u in unavailable if u.employee_id == eid])
            clash = next(((f, conflicts(s, f, constraints.min_rest_hours)) for f in frozen_by_emp.get(eid, [])
                          if conflicts(s, f, constraints.min_rest_hours)), None)
            if eid == orig and sid in settings.release_shift_ids:
                p.excluded[(sid, eid)] = Exclusion("SCHEDULE_CONFLICT", settings.release_shift_ids[sid])
            elif e.status == "inactive":
                p.excluded[(sid, eid)] = Exclusion("UNAVAILABLE", "account deactivated")
            elif av:
                p.excluded[(sid, eid)] = Exclusion("UNAVAILABLE", av.reason or "marked unavailable")
            elif miss:
                certs = {c.lower() for c in s.required_certifications}
                code = "MISSING_CERTIFICATION" if all(m.lower() in certs for m in miss) else "MISSING_SKILL"
                p.excluded[(sid, eid)] = Exclusion(code, "no " + ", ".join(miss))
            elif clash:
                f, why = clash
                if why == "overlap":
                    p.excluded[(sid, eid)] = Exclusion("SHIFT_OVERLAP", f"already working {f.assignment} {f.start}–{f.end}")
                else:
                    gap = abs((s.window[0] - f.window[1]).total_seconds() / 3600) if f.window[1] <= s.window[0] \
                        else abs((f.window[0] - s.window[1]).total_seconds() / 3600)
                    p.excluded[(sid, eid)] = Exclusion(
                        "REST_PERIOD_VIOLATION",
                        f"only {gap:g}h rest after {f.assignment} (minimum {constraints.min_rest_hours:g}h)")
            elif eid in excluded_ids and eid != orig:
                p.excluded[(sid, eid)] = Exclusion("EXCLUDED_BY_MANAGER", "excluded by the manager")
            elif eid in locked and eid != orig:
                p.excluded[(sid, eid)] = Exclusion("LOCKED_BY_MANAGER", "schedule locked by the manager")
            elif settings.allowed_departments and eid != orig and e.department not in settings.allowed_departments:
                p.excluded[(sid, eid)] = Exclusion("EXCLUDED_BY_MANAGER",
                                                   f"not in {', '.join(settings.allowed_departments)} (your instruction)")
            else:
                cands.append(eid)
                continue
            # Grandfathering: the person already on this shift keeps it unless they are now unavailable.
            # Pre-existing data problems (flagged at upload) must not force changes the disruption didn't cause.
            if eid == orig and p.excluded[(sid, eid)].code not in ("UNAVAILABLE", "SCHEDULE_CONFLICT"):
                p.grandfathered.append((sid, eid, p.excluded.pop((sid, eid)).detail))
                cands.append(eid)
        p.candidates[sid] = cands
        if orig is not None and orig not in cands:
            p.vacated.append(sid)
        elif orig is None and sid in settings.cover_shift_ids:
            p.vacated.append(sid)          # an open shift that must be covered (mandatory coverage)
    return p
