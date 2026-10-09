"""Unresolved-constraint analysis: *why* a shift can't be covered, and what a manager could do about it.

For every shift the best repair still leaves uncovered, each employee is run through the hard
constraints in a fixed order, the same order a staffing manager would check them:

    required skill → required certification → availability → overlapping shift → rest → hours limits

The funnel shows how many people survive each check. The *bottleneck* is the check that brings the
count to zero. People who fail exactly one check are "near misses". Grouping them by constraint
ranks the constraints by how many options relaxing them would open. Every resolution is a suggestion
for a human. Nothing here relaxes a hard constraint.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.rules import blocked_by, conflicts, day_key, effective_limits, gap_hours, week_key

from .evaluate import Assignment, full_assignment
from .problem import RepairProblem

Stage = Literal["skill", "certification", "availability", "overlap", "rest", "hours"]
STAGES: list[Stage] = ["skill", "certification", "availability", "overlap", "rest", "hours"]
STAGE_LABEL = {
    "skill": "Required skill",
    "certification": "Required certification",
    "availability": "Availability",
    "overlap": "No overlapping shifts",
    "rest": "Minimum rest",
    "hours": "Daily / weekly hours limits",
}


class Blocked(BaseModel):
    employee_id: str
    name: str
    detail: str


class FunnelStep(BaseModel):
    stage: Stage
    label: str
    requirement: str
    remaining: int
    eliminated: list[Blocked] = Field(default_factory=list)


class BlockingConstraint(BaseModel):
    stage: Stage
    label: str
    eliminated: int
    near_misses: list[Blocked] = Field(default_factory=list, description="people blocked only by this constraint")


class Resolution(BaseModel):
    action: str
    detail: str
    kind: Literal["operational", "manual_override"]


class UnresolvedShift(BaseModel):
    shift_id: str
    date: str
    start: str
    end: str
    assignment: str
    department: Optional[str] = None
    priority: str
    required_skills: list[str]
    required_certifications: list[str]
    original_employee_name: Optional[str] = None
    why_open: str
    total_employees: int
    funnel: list[FunnelStep]
    bottleneck: Optional[Stage] = None
    bottleneck_label: str
    blocking: list[BlockingConstraint]
    resolutions: list[Resolution]
    summary: str


def _names(blocked: list[Blocked], n: int = 3) -> str:
    names = [b.name for b in blocked[:n]]
    more = len(blocked) - len(names)
    return ", ".join(names) + (f" and {more} more" if more > 0 else "")


def diagnose_slot(p: RepairProblem, sid: str, best: Optional[Assignment]) -> UnresolvedShift:
    s = p.shifts[sid]
    reference = full_assignment(p, best) if best else \
        {**{k: v for k, v in p.original.items() if k not in p.vacated}, **p.frozen}
    reference = {k: v for k, v in reference.items() if k != sid}
    by_emp: dict[str, list[str]] = defaultdict(list)
    for k, e in reference.items():
        by_emp[e].append(k)

    certs = list(s.required_certifications)
    cert_set = {c.lower() for c in certs}
    skills = [q for q in p.requirements.get(sid, s.required_skills) if q.lower() not in cert_set]
    orig = p.original.get(sid)

    failures: dict[str, dict[Stage, str]] = {}
    for eid, e in p.employees.items():
        have = e.qualifications
        f: dict[Stage, str] = {}
        miss_s = [q for q in skills if q.lower() not in have]
        miss_c = [q for q in certs if q.lower() not in have]
        if miss_s:
            f["skill"] = "no " + ", ".join(miss_s)
        if miss_c:
            f["certification"] = "no " + ", ".join(miss_c)
        ex = p.excluded.get((sid, eid))
        if eid == orig and ex is not None:
            f["availability"] = ex.detail if ex.code != "UNAVAILABLE" else f"unavailable ({ex.detail})"
        else:
            av = blocked_by(s, [u for u in p.unavailable if u.employee_id == eid])
            if av:
                f["availability"] = f"unavailable ({av.reason or av.kind})"
            elif ex is not None and ex.code in ("EXCLUDED_BY_MANAGER", "LOCKED_BY_MANAGER"):
                f["availability"] = ex.detail
        overlap = rest = None
        for k in by_emp.get(eid, []):
            why = conflicts(s, p.shifts[k], p.constraints.min_rest_hours)
            if why == "overlap" and overlap is None:
                overlap = f"already on {p.shifts[k].assignment} {p.shifts[k].start}–{p.shifts[k].end}"
            elif why == "rest" and rest is None:
                rest = (f"only {max(0.0, gap_hours(s, p.shifts[k])):g}h rest next to {p.shifts[k].assignment} "
                        f"(minimum {p.constraints.min_rest_hours:g}h)")
        if overlap:
            f["overlap"] = overlap
        if rest:
            f["rest"] = rest
        daily, contracted, cap = effective_limits(e, p.constraints)
        # hours are judged without shifts that already clash with this one (that's the overlap/rest check)
        others = [k for k in by_emp.get(eid, []) if not conflicts(s, p.shifts[k], p.constraints.min_rest_hours)]
        day_h = s.hours + sum(p.shifts[k].hours for k in others if day_key(p.shifts[k]) == day_key(s))
        week_h = s.hours + sum(p.shifts[k].hours for k in others if week_key(p.shifts[k]) == week_key(s))
        if day_h > daily + 1e-6:
            f["hours"] = f"{day_h:g}h that day (limit {daily:g}h)"
        elif week_h > cap + 1e-6:
            f["hours"] = (f"{week_h:g}h that week (limit {cap:g}h"
                          + ("; overtime not allowed)" if not p.constraints.allow_overtime else ")"))
        failures[eid] = f

    names = {eid: e.name for eid, e in p.employees.items()}
    alive = set(p.employees)
    funnel: list[FunnelStep] = []
    bottleneck: Optional[Stage] = None
    requirement = {
        "skill": ", ".join(skills) or "none",
        "certification": ", ".join(certs) or "none",
        "availability": f"free {s.date} {s.start}–{s.end}",
        "overlap": "not already working then",
        "rest": f"≥ {p.constraints.min_rest_hours:g}h rest",
        "hours": "within daily/weekly limits",
    }
    for st in STAGES:
        out = sorted((Blocked(employee_id=eid, name=names[eid], detail=failures[eid][st])
                      for eid in alive if st in failures[eid]), key=lambda b: b.name)
        alive -= {b.employee_id for b in out}
        funnel.append(FunnelStep(stage=st, label=STAGE_LABEL[st], requirement=requirement[st],
                                 remaining=len(alive), eliminated=out))
        if not alive and bottleneck is None:
            bottleneck = st

    blocking = []
    for st in STAGES:
        near = sorted((Blocked(employee_id=eid, name=names[eid], detail=f[st])
                       for eid, f in failures.items() if list(f) == [st]), key=lambda b: b.name)
        elim = sum(1 for f in failures.values() if st in f)
        if elim:
            blocking.append(BlockingConstraint(stage=st, label=STAGE_LABEL[st], eliminated=elim, near_misses=near))
    blocking.sort(key=lambda b: (-len(b.near_misses), STAGES.index(b.stage)))

    resolutions: list[Resolution] = []
    near_by = {b.stage: b.near_misses for b in blocking}
    if near_by.get("availability"):
        resolutions.append(Resolution(kind="operational", action="Ask about availability",
                                      detail=f"Check whether {_names(near_by['availability'])} can work after all; "
                                             "they meet every other requirement."))
    if near_by.get("overlap"):
        resolutions.append(Resolution(kind="operational", action="Free up a qualified person",
                                      detail=f"Move {_names(near_by['overlap'])} off their overlapping shift "
                                             "(that shift then needs its own cover), or change this shift's timing."))
    if near_by.get("rest"):
        resolutions.append(Resolution(kind="operational", action="Change the shift timing",
                                      detail=f"Starting later would give {_names(near_by['rest'])} the required "
                                             f"{p.constraints.min_rest_hours:g}h rest."))
    if near_by.get("hours"):
        resolutions.append(Resolution(kind="manual_override", action="Approve extra hours (manual override)",
                                      detail=f"{_names(near_by['hours'])} would exceed an hours limit. Only a manager "
                                             "can approve this; ResQWork will not relax it automatically."))
    if near_by.get("certification"):
        resolutions.append(Resolution(kind="manual_override", action="Relax the certification (manual override)",
                                      detail=f"{_names(near_by['certification'])} meet everything except "
                                             f"{', '.join(certs)}. Only do this if policy allows supervised cover."))
    if near_by.get("skill"):
        resolutions.append(Resolution(kind="manual_override", action="Relax the skill requirement (manual override)",
                                      detail=f"{_names(near_by['skill'])} meet everything except {', '.join(skills)}."))
    resolutions.append(Resolution(kind="operational", action="Add a qualified person",
                                  detail=f"Bring in someone with {', '.join(skills + certs) or 'the right profile'} "
                                         "from another team, the float pool or an agency."))
    if s.hours > 6:
        resolutions.append(Resolution(kind="operational", action="Split the shift",
                                      detail=f"Split the {s.hours:g}h shift into two parts that different people can cover."))

    total = len(p.employees)
    if bottleneck is not None:
        step = next(f for f in funnel if f.stage == bottleneck)
        idx = STAGES.index(bottleneck)
        before = funnel[idx - 1].remaining if idx else total
        quals = ", ".join(skills + certs) or "qualification"
        if bottleneck == "skill":
            summary = f"Required skill {step.requirement} cannot be satisfied: nobody on the roster has it."
        elif bottleneck == "certification":
            summary = (f"Required certification {step.requirement} cannot be satisfied: "
                       + ("nobody on the roster holds it." if before == total else
                          f"none of the {before} people with the required skill holds it."))
        elif bottleneck == "availability":
            who = "the only qualified person is" if before == 1 else f"all {before} qualified people are"
            summary = (f"Required {quals} cannot be satisfied: {who} unavailable or barred from this shift "
                       f"({_names(step.eliminated)}).")
        else:
            who = "the only qualified, available person is" if before == 1 else \
                f"all {before} qualified, available people are"
            blocked = {"overlap": "already working an overlapping shift", "rest": "blocked by the minimum-rest rule",
                       "hours": "blocked by daily/weekly hours limits"}[bottleneck]
            summary = f"No feasible cover for {s.assignment}: {who} {blocked} ({_names(step.eliminated)})."
        bottleneck_label = STAGE_LABEL[bottleneck]
    else:
        survivors = [names[e] for e in sorted(alive)]
        summary = (f"{', '.join(survivors[:3])} pass every individual check, but covering {s.assignment} would "
                   "leave another shift uncovered or break a rule elsewhere, so no complete valid repair exists.")
        bottleneck_label = "Knock-on coverage (no valid chain of moves)"

    if orig and orig in p.employees:
        ex = p.excluded.get((sid, orig))
        why_open = f"{names[orig]} can't work it: {ex.detail}" if ex else f"{names[orig]} can't work it"
    else:
        why_open = "Nobody is assigned and the shift must be covered."
    return UnresolvedShift(
        shift_id=sid, date=s.date, start=s.start, end=s.end, assignment=s.assignment, department=s.department,
        priority=s.priority, required_skills=skills, required_certifications=certs,
        original_employee_name=names.get(orig) if orig else None, why_open=why_open, total_employees=total,
        funnel=funnel, bottleneck=bottleneck, bottleneck_label=bottleneck_label, blocking=blocking,
        resolutions=resolutions, summary=summary)


def diagnose(p: RepairProblem, best: Optional[Assignment]) -> list[UnresolvedShift]:
    """Analysis for every must-cover shift the best repair leaves uncovered (all of them if there is none)."""
    todo = [sid for sid in p.vacated if best is None or best.get(sid) is None]
    return [diagnose_slot(p, sid, best) for sid in todo]
