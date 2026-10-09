"""Generate repair options A–D with computed evidence.

    result = generate_repair(dataset, [disruption], settings)

For each strategy the solver (CP-SAT if installed, otherwise the exact
bounded search) finds the cheapest valid repair. Every candidate is then
re-validated against ``core.rules`` and dropped if anything is violated.
Duplicate repairs are merged (the option records every goal it is best
for), and a distinct alternative is searched for the strategy instead.

All evidence is computed from the data and the chosen assignment: hours
before/after, rest before the shift, matched skills, overtime, and for every
other employee *why they were not chosen*. That comes either from a hard
rule or from a counterfactual re-solve that forces them in and measures
the extra cost.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Literal, Optional

from pydantic import BaseModel, Field

from analytics.metrics import FairnessMetrics, ImpactMetrics
from core.models import Dataset, Disruption
from core.rules import conflicts, week_key

from . import solver_cpsat, solver_search
from .diagnosis import UnresolvedShift, diagnose
from .baseline import rebuild_from_scratch
from .evaluate import Assignment, Evaluation, evaluate, full_assignment, measure
from .problem import STRATEGY_INFO, RepairProblem, RunSettings, build_problem

STRATEGIES = ["recommended", "min_employees", "min_overtime", "max_fairness"]
COUNTERFACTUALS = 15


class Change(BaseModel):
    shift_id: str
    date: str
    start: str
    end: str
    assignment: str
    department: Optional[str] = None
    from_employee_id: Optional[str] = None
    from_employee_name: Optional[str] = None
    to_employee_id: Optional[str] = None
    to_employee_name: Optional[str] = None
    kind: Literal["reassigned", "uncovered", "filled"]


class SelectedEvidence(BaseModel):
    employee_id: str
    employee_name: str
    shift_id: str
    covers: str
    available: bool = True
    skills_match: bool
    matched_skills: list[str]
    weekly_hours_before: float
    weekly_hours_after: float
    contracted_weekly_hours: float
    max_weekly_hours: float
    overtime_hours_added: float
    rest_hours_before_shift: Optional[float]
    previous_changes_30d: int
    disruptions_absorbed_30d: int


class RejectedEvidence(BaseModel):
    employee_id: str
    employee_name: str
    shift_id: str
    reason_code: str
    detail: str
    extra_cost: Optional[float] = None


class RepairOption(BaseModel):
    option_id: str
    label: str
    title: str
    strategy: str
    goal: str
    note: Optional[str] = None
    best_for: list[str] = Field(default_factory=list, description="strategies whose optimum this repair is")
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL"]
    assignment: dict[str, Optional[str]]
    changes: list[Change]
    selected: list[SelectedEvidence]
    impact: ImpactMetrics
    fairness: FairnessMetrics
    cost: float
    cost_breakdown: dict[str, float]
    rule_check: str = "passed"


class Baseline(BaseModel):
    method: str
    assignments_changed: int
    employees_affected: int
    uncovered: int


class RepairResult(BaseModel):
    status: Literal["OPTIMAL", "FEASIBLE", "PARTIAL", "INFEASIBLE"]
    solver: str
    solve_ms: int
    disruptions: list[Disruption]
    disrupted_shifts: list[str]
    options: list[RepairOption]
    recommended_option_id: Optional[str]
    rejected: list[RejectedEvidence]
    baseline: Optional[Baseline] = None
    original_fairness: Optional[FairnessMetrics] = None
    infeasibility_reasons: list[str] = Field(default_factory=list)
    unresolved: list[UnresolvedShift] = Field(default_factory=list,
                                              description="bottleneck analysis for every shift left uncovered")
    hard_constraints: list[dict] = Field(default_factory=list, description="hard rules every option satisfies")
    soft_objectives: list[dict] = Field(default_factory=list, description="soft goals used to rank options")
    constraints_used: dict = Field(default_factory=dict)


def _solver_name() -> str:
    return "OR-Tools CP-SAT" if solver_cpsat.usable() else "exact bounded search (OR-Tools not installed)"


class _Solver:
    def __init__(self, p: RepairProblem):
        self.p = p
        self.pool = None if solver_cpsat.usable() else solver_search.enumerate_repairs(p)

    def solve(self, strategy: str, exclude=None, force=None) -> Optional[Assignment]:
        if solver_cpsat.usable():
            return solver_cpsat.solve(self.p, strategy, exclude=exclude, force=force)
        return solver_search.solve(self.p, strategy, exclude=exclude, force=force, pool=self.pool)


def _changes(p: RepairProblem, a: Assignment) -> list[Change]:
    out = []
    for sid in p.slots:
        orig, now = p.original.get(sid), a.get(sid)
        if orig == now:
            continue
        if now is None and orig is None:
            continue
        s = p.shifts[sid]
        kind = "uncovered" if now is None else ("filled" if orig is None else "reassigned")
        out.append(Change(shift_id=sid, date=s.date, start=s.start, end=s.end, assignment=s.assignment,
                          department=s.department, from_employee_id=orig,
                          from_employee_name=p.employee_name(orig) if orig else None,
                          to_employee_id=now, to_employee_name=p.employee_name(now) if now else None, kind=kind))
    return out


def _rest_before(p: RepairProblem, full: dict[str, str], eid: str, sid: str) -> Optional[float]:
    s = p.shifts[sid]
    prev = [p.shifts[x] for x, e in full.items() if e == eid and x != sid and p.shifts[x].window[1] <= s.window[0]]
    if not prev:
        return None
    last = max(prev, key=lambda z: z.window[1])
    return round((s.window[0] - last.window[1]).total_seconds() / 3600, 1)


def _selected(p: RepairProblem, a: Assignment, ev: Evaluation) -> list[SelectedEvidence]:
    full = full_assignment(p, a)
    out = []
    for sid, eid in ev.new_assignments:
        e, s = p.employees[eid], p.shifts[sid]
        wk = week_key(s)
        before = sum(p.shifts[x].hours for x, y in p.original.items() if y == eid and week_key(p.shifts[x]) == wk)
        after = sum(p.shifts[x].hours for x, y in full.items() if y == eid and week_key(p.shifts[x]) == wk)
        _, contracted, cap = p.limits(eid)
        reqs = p.requirements.get(sid, [])
        out.append(SelectedEvidence(
            employee_id=eid, employee_name=e.name, shift_id=sid, covers=s.assignment,
            skills_match=all(r.lower() in e.qualifications for r in reqs), matched_skills=reqs,
            weekly_hours_before=round(before, 2), weekly_hours_after=round(after, 2),
            contracted_weekly_hours=contracted, max_weekly_hours=cap,
            overtime_hours_added=round(ev.overtime_added.get(eid, 0.0), 2),
            rest_hours_before_shift=_rest_before(p, full, eid, sid),
            previous_changes_30d=e.history.schedule_changes_30d,
            disruptions_absorbed_30d=e.history.disruptions_absorbed_30d))
    return out


def _option(p: RepairProblem, strategy: str, a: Assignment, idx: int, note: Optional[str] = None) -> RepairOption:
    ev = evaluate(p, a, strategy)
    imp, fair = measure(p, a, ev)
    info = STRATEGY_INFO[strategy]
    return RepairOption(
        option_id=chr(ord("A") + idx), label=f"Option {chr(ord('A') + idx)}", title=info["title"],
        strategy=strategy, goal=info["goal"], note=note, best_for=[strategy],
        status="PARTIAL" if ev.unfilled else ("OPTIMAL" if solver_cpsat.usable() else "FEASIBLE"),
        assignment=a, changes=_changes(p, a), selected=_selected(p, a, ev), impact=imp, fairness=fair,
        cost=ev.cost, cost_breakdown=ev.breakdown)


_MEASURES = (("impact_score", -1), ("employees_affected", -1), ("overtime_hours_added", -1),
             ("assignments_changed", -1))


def _offers_tradeoff(opt: RepairOption, others: list[RepairOption]) -> bool:
    """True if ``opt`` is strictly better than *each* existing option on at least one measure."""
    def better(a: RepairOption, b: RepairOption) -> bool:
        if a.fairness.fairness_score > b.fairness.fairness_score + 0.05:
            return True
        return any(getattr(a.impact, m) < getattr(b.impact, m) - 1e-9 for m, _ in _MEASURES)
    return all(better(opt, o) for o in others)


def _advantage(o: RepairOption, options: list[RepairOption], used: set[str]) -> tuple[str, str]:
    """Title an alternative by what it measurably does best (vs Option A), each title used once.

    'Lowest …' / 'Highest …' titles are only given to the option that is actually best on that measure.
    """
    a = options[0]
    best_ot = min(x.impact.overtime_hours_added for x in options)
    best_aff = min(x.impact.employees_affected for x in options)
    best_fair = max(x.fairness.fairness_score for x in options)
    cands = []
    if o.impact.overtime_hours_added < a.impact.overtime_hours_added - 1e-9 and o.impact.overtime_hours_added == best_ot:
        cands.append(("Lowest overtime", f"{o.impact.overtime_hours_added:g}h overtime instead of "
                                         f"{a.impact.overtime_hours_added:g}h."))
    if o.impact.employees_affected < a.impact.employees_affected and o.impact.employees_affected == best_aff:
        cands.append(("Lowest employee impact", f"{o.impact.employees_affected} people affected instead of "
                                                f"{a.impact.employees_affected}."))
    if o.fairness.fairness_score > a.fairness.fairness_score + 0.05 and o.fairness.fairness_score == best_fair:
        cands.append(("Highest fairness", f"Fairness {o.fairness.fairness_score:g} instead of "
                                          f"{a.fairness.fairness_score:g}: extra work goes to people with a "
                                          f"lighter recent load."))
    if o.fairness.fairness_score > a.fairness.fairness_score + 0.05:
        cands.append(("Fairer alternative", f"Fairness {o.fairness.fairness_score:g} instead of "
                                            f"{a.fairness.fairness_score:g}."))
    if o.impact.overtime_hours_added < a.impact.overtime_hours_added - 1e-9:
        cands.append(("Less overtime", f"{o.impact.overtime_hours_added:g}h overtime instead of "
                                       f"{a.impact.overtime_hours_added:g}h."))
    for title, goal in cands:
        if title not in used:
            return title, goal
    return "Alternative repair", "A different valid repair with its own trade-offs."


def _key(p: RepairProblem, a: Assignment) -> tuple:
    return tuple(a.get(s) for s in p.slots)


def _rejected(p: RepairProblem, solver: _Solver, best: Assignment, target: str) -> list[RejectedEvidence]:
    chosen = best.get(target)
    base = evaluate(p, best, "recommended")
    out: list[RejectedEvidence] = []
    eligible = []
    absent = {d.employee_id for d in p.disruptions}
    for eid, e in p.employees.items():
        if eid == chosen or eid in absent:
            continue
        ex = p.excluded.get((target, eid))
        if ex:
            out.append(RejectedEvidence(employee_id=eid, employee_name=e.name, shift_id=target,
                                        reason_code=ex.code, detail=ex.detail))
        else:
            eligible.append(eid)
    # counterfactuals for eligible people: force them in and measure
    eligible.sort(key=lambda eid: (p.original.get(target) == eid, p.employees[eid].name))
    for eid in eligible[:COUNTERFACTUALS]:
        e = p.employees[eid]
        forced = solver.solve("recommended", force=(target, eid))
        if forced is None:
            out.append(RejectedEvidence(employee_id=eid, employee_name=e.name, shift_id=target,
                                        reason_code="WOULD_EXCEED_MAX_HOURS",
                                        detail=_infeasible_reason(p, best, target, eid)))
            continue
        ev = evaluate(p, forced, "recommended")
        diffs = []
        if len(ev.changed_slots) != len(base.changed_slots):
            diffs.append(f"{len(ev.changed_slots)} change{'' if len(ev.changed_slots) == 1 else 's'} vs {len(base.changed_slots)}")
        ot_f, ot_b = sum(ev.overtime_added.values()), sum(base.overtime_added.values())
        if ot_f != ot_b:
            diffs.append(f"{ot_f:g}h overtime vs {ot_b:g}h")
        if len(ev.affected) != len(base.affected):
            diffs.append(f"{len(ev.affected)} {'person' if len(ev.affected) == 1 else 'people'} affected vs {len(base.affected)}")
        new_gaps = [s for s in ev.unfilled if s not in base.unfilled]
        if new_gaps:
            diffs.insert(0, "would leave " + ", ".join(p.shifts[s].assignment for s in new_gaps) + " uncovered")
        code = "WOULD_UNCOVER_SHIFT" if new_gaps else "WOULD_CREATE_OVERTIME" if ot_f > ot_b else "HIGHER_IMPACT"
        if not diffs:
            fb, ff = base.breakdown, ev.breakdown
            if ff.get("fairness", 0) > fb.get("fairness", 0):
                diffs.append("higher recent workload/disruption burden than the chosen person")
            if ff.get("preference", 0) > fb.get("preference", 0):
                diffs.append("against their shift preferences")
            if ff.get("manager_feedback", 0) > fb.get("manager_feedback", 0):
                diffs.append("you asked to avoid using them")
                code = "MANAGER_FEEDBACK"
        out.append(RejectedEvidence(employee_id=eid, employee_name=e.name, shift_id=target, reason_code=code,
                                    detail="; ".join(diffs) or "equal cost; the chosen person ranked first",
                                    extra_cost=round(ev.cost - base.cost, 2)))
    for eid in eligible[COUNTERFACTUALS:]:
        out.append(RejectedEvidence(employee_id=eid, employee_name=p.employees[eid].name, shift_id=target,
                                    reason_code="HIGHER_IMPACT", detail="eligible, ranked lower (not re-solved)"))
    order = {"WOULD_UNCOVER_SHIFT": 0, "REST_PERIOD_VIOLATION": 1, "SHIFT_OVERLAP": 2, "WOULD_EXCEED_MAX_HOURS": 3,
             "WOULD_CREATE_OVERTIME": 4, "HIGHER_IMPACT": 5, "MANAGER_FEEDBACK": 6, "EXCLUDED_BY_MANAGER": 7,
             "LOCKED_BY_MANAGER": 8, "MISSING_CERTIFICATION": 9, "MISSING_SKILL": 10, "UNAVAILABLE": 11,
             "SCHEDULE_CONFLICT": 12}
    out.sort(key=lambda r: (order.get(r.reason_code, 9), r.extra_cost or 0, r.employee_name))
    return out


def _infeasible_reason(p: RepairProblem, best: Assignment, target: str, eid: str) -> str:
    s = p.shifts[target]
    full = full_assignment(p, best)
    for sid, e in full.items():
        if e == eid and conflicts(s, p.shifts[sid], p.constraints.min_rest_hours):
            return f"would clash with their {p.shifts[sid].assignment} shift and no valid cover exists for it"
    _, _, cap = p.limits(eid)
    return f"would exceed the {cap:g}h weekly limit"


def generate_repair(ds: Dataset, disruptions: list[Disruption], settings: Optional[RunSettings] = None,
                    strategies: Optional[list[str]] = None, with_baseline: bool = True) -> RepairResult:
    t0 = time.monotonic()
    p = build_problem(ds, disruptions, settings)
    solver = _Solver(p)
    strategies = strategies or STRATEGIES
    original_ev = evaluate(p, {sid: p.original.get(sid) for sid in p.slots})
    _, original_fair = measure(p, {sid: p.original.get(sid) for sid in p.slots}, original_ev)

    if not p.vacated:
        return RepairResult(status="OPTIMAL", solver=_solver_name(), solve_ms=0, disruptions=disruptions,
                            disrupted_shifts=[], options=[], recommended_option_id=None, rejected=[],
                            original_fairness=original_fair,
                            infeasibility_reasons=["No scheduled shift is affected by this disruption."],
                            constraints_used=p.constraints.model_dump())

    options: list[RepairOption] = []
    found: list[Assignment] = []
    for strategy in strategies:
        a = solver.solve(strategy)
        if a is None:
            continue
        dup = next((o for o in options if _key(p, o.assignment) == _key(p, a)), None)
        is_alt = dup is not None
        if is_alt:
            dup.best_for.append(strategy)
            a = solver.solve(strategy, exclude=found)
            if a is None:
                continue
        opt = _option(p, strategy, a, len(options),
                      note=f"{dup.label} is already the best repair for this goal; this is the best different "
                           f"repair that still offers a trade-off." if is_alt else None)
        if is_alt:
            opt.best_for = []
        if evaluate(p, a, strategy, full_check=True).violations:   # safety net: never show an invalid repair
            continue
        if options and opt.impact.unfilled_shifts > min(o.impact.unfilled_shifts for o in options):
            continue                                  # never offer worse coverage as an "alternative"
        if options and not _offers_tradeoff(opt, options):
            continue                                  # an option must beat every other one on something
        options.append(opt)
        found.append(a)
    used: set[str] = set()
    for i, o in enumerate(options):                   # relabel A, B, C … after filtering
        o.option_id, o.label = chr(ord("A") + i), f"Option {chr(ord('A') + i)}"
        if i > 0:
            o.title, o.goal = _advantage(o, options, used)
            used.add(o.title)

    elapsed = int((time.monotonic() - t0) * 1000)
    if not options:
        unresolved = diagnose(p, None)
        return RepairResult(status="INFEASIBLE", solver=_solver_name(), solve_ms=elapsed, disruptions=disruptions,
                            disrupted_shifts=p.vacated, options=[], recommended_option_id=None, rejected=[],
                            original_fairness=original_fair, infeasibility_reasons=[u.summary for u in unresolved],
                            unresolved=unresolved, hard_constraints=hard_constraints(p),
                            soft_objectives=soft_objectives(p), constraints_used=p.constraints.model_dump())

    best = options[0]
    rejected = _rejected(p, solver, best.assignment, p.vacated[0])
    status = "PARTIAL" if best.impact.unfilled_shifts else best.status
    unresolved = diagnose(p, best.assignment) if best.impact.unfilled_shifts else []
    reasons = [u.summary for u in unresolved]
    baseline = None
    if with_baseline:
        rb = rebuild_from_scratch(p)
        baseline = Baseline(method="Rebuild from scratch (greedy, ignores the existing schedule)",
                            assignments_changed=rb[0], employees_affected=rb[1], uncovered=rb[2])
    return RepairResult(status=status, solver=_solver_name(), solve_ms=int((time.monotonic() - t0) * 1000),
                        disruptions=disruptions, disrupted_shifts=p.vacated, options=options,
                        recommended_option_id=best.option_id, rejected=rejected, baseline=baseline,
                        original_fairness=original_fair, infeasibility_reasons=reasons, unresolved=unresolved,
                        hard_constraints=hard_constraints(p), soft_objectives=soft_objectives(p),
                        constraints_used=p.constraints.model_dump())


def hard_constraints(p: RepairProblem) -> list[dict]:
    """The hard rules every shown option has been checked against (by the solver and again by the validator)."""
    c = p.constraints
    rules = [
        ("availability", "Availability", "nobody is assigned while unavailable, on leave or reported absent"),
        ("overlap", "No overlapping shifts", "nobody works two shifts at the same time"),
        ("skills", "Required skills", "every assignee has the shift's required skills"),
        ("certifications", "Required certifications", "every assignee holds the shift's required certifications"),
        ("rest", "Minimum rest", f"at least {c.min_rest_hours:g}h between shifts"),
        ("daily_hours", "Maximum daily hours", f"per-person daily limit"
         + (f" (org cap {c.max_daily_hours:g}h)" if c.max_daily_hours else "")),
        ("weekly_hours", "Maximum weekly hours", f"per-person weekly limit"
         + (f" (org cap {c.max_weekly_hours:g}h)" if c.max_weekly_hours else "")
         + ("; no overtime" if not c.allow_overtime else f"; overtime ≤ {c.max_overtime_hours_per_week:g}h/week")),
        ("coverage", "Mandatory coverage", "every affected shift is covered, or reported as unresolved"),
        ("frozen", "Started shifts are fixed", "shifts that already started are never changed"),
    ]
    if p.settings.excluded_employee_ids or p.settings.locked_employee_ids:
        rules.append(("manager", "Manager instructions", "excluded / locked people are respected"))
    return [{"id": i, "label": label, "detail": detail, "kind": "hard"} for i, label, detail in rules]


def soft_objectives(p: RepairProblem) -> list[dict]:
    """Soft goals: they rank valid repairs, they never make an invalid one acceptable."""
    w = p.dataset.optimization.weights
    return [{"id": "minimum_change", "label": "Minimum change", "weight": w.assignment_change,
             "detail": "fewest existing assignments changed"},
            {"id": "employees_affected", "label": "Fewest people affected", "weight": w.employee_affected,
             "detail": "fewest people whose schedule changes"},
            {"id": "overtime", "label": "Avoid overtime", "weight": w.overtime_hour, "detail": "per overtime hour added"},
            {"id": "fairness", "label": "Fairness", "weight": w.fairness,
             "detail": "prefer people who absorbed fewer recent disruptions and have lighter workloads"},
            {"id": "preferences", "label": "Employee preferences", "weight": w.preference,
             "detail": "preferred / avoided shift types, weekends"}]


def _why_infeasible(p: RepairProblem) -> list[str]:
    out = []
    for sid in p.vacated:
        s = p.shifts[sid]
        codes: dict[str, int] = {}
        for (slot, _), ex in p.excluded.items():
            if slot == sid:
                codes[ex.code] = codes.get(ex.code, 0) + 1
        if not p.candidates[sid]:
            parts = ", ".join(f"{n} {c.lower().replace('_', ' ')}" for c, n in sorted(codes.items()))
            out.append(f"Nobody can cover {s.assignment} on {s.date} {s.start}–{s.end} ({parts}).")
        else:
            out.append(f"Everyone qualified for {s.assignment} on {s.date} would break an hours or rest rule "
                       f"elsewhere, or would leave another shift uncovered.")
    return out


def week_window(p: RepairProblem) -> timedelta:  # pragma: no cover - helper for analytics
    return timedelta(days=7)
