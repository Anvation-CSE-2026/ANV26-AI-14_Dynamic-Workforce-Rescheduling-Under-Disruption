"""Translations between the engine's canonical model and the AI/RAG contracts.

Keeps ``engine`` free of AI concerns and ``ai`` free of engine internals:
everything the explainer, comparer and notice builder see is assembled
here from solver output, never invented.
"""

from __future__ import annotations

from typing import Iterable, Optional

from ai.candidates import CandidateFacts
from ai.feedback import FeedbackPreference
from ai.schemas import (
    AssignmentRef,
    ChangeFact,
    Disruption as AIDisruption,
    EmployeeRef,
    ExplanationFacts,
    MetricsFact,
    ParseContext,
    ParseResult,
    PolicyCitation,
    Priority,
    RejectedFact,
    SelectedFact,
    ShiftRef,
)
from core.models import Dataset, Disruption, interval
from engine.problem import RunSettings
from engine.repair import RepairOption, RepairResult

_AI_REASONS = {"sick", "emergency", "leave", "personal", "other"}

PRIORITY_STRATEGY = {
    Priority.minimize_changes: "recommended",
    Priority.minimize_affected_employees: "min_employees",
    Priority.minimize_overtime: "min_overtime",
    Priority.fairness: "max_fairness",
    Priority.employee_preferences: "recommended",
}


# ---------------------------------------------------------------- language in

def parse_context(ds: Dataset) -> ParseContext:
    assignments = {s.assignment for s in ds.shifts}
    return ParseContext(
        reference_date=ds.reference_date or min(s.date for s in ds.shifts),
        timezone=ds.organization.timezone,
        employees=[EmployeeRef(id=e.id, name=e.name, role=e.role, team=e.department) for e in ds.employees],
        assignments=[AssignmentRef(id=a, name=a) for a in sorted(assignments)]
                    + [AssignmentRef(id=d.id, name=d.name) for d in ds.departments if d.name not in assignments],
        shifts=[ShiftRef(employee_id=a.employee_id, date=ds.shift(a.shift_id).date, start_time=ds.shift(a.shift_id).start,
                         end_time=ds.shift(a.shift_id).end, assignment_id=ds.shift(a.shift_id).assignment)
                for a in ds.existing_schedule if ds.shift(a.shift_id)],
        max_horizon_days=21)


def core_disruptions(parsed: ParseResult, prefix: str) -> list[Disruption]:
    return [Disruption(id=f"{prefix}-{i + 1}", employee_id=d.employee_id, date=d.date, start=d.start_time,
                       end=d.end_time, reason=d.reason if d.reason != "unspecified" else None,
                       severity="high", label=None) for i, d in enumerate(parsed.disruptions)]


def ai_disruption(d: Disruption) -> AIDisruption:
    start, end = d.start or "00:00", d.end or "23:59"
    if (interval(d.date, start, end)[1] - interval(d.date, start, end)[0]).days >= 1 or end <= start:
        start, end = "00:00", "23:59"
    reason = d.reason if d.reason in _AI_REASONS else ("other" if d.reason else "unspecified")
    return AIDisruption(type="employee_unavailability", employee_id=d.employee_id, date=d.date,
                        start_time=start, end_time=end, reason=reason)


# ---------------------------------------------------------- settings for a run

POLICY_TO_CONSTRAINT = {
    "minimum_rest": ("min_rest_hours", max),
    "max_daily_hours": ("max_daily_hours", min),
    "max_weekly_hours": ("max_weekly_hours", min),
    "max_overtime_weekly": ("max_overtime_hours_per_week", min),
}


def settings_from(ds: Dataset, parsed: Optional[ParseResult] = None, feedback: Iterable[dict] = (),
                  policy_config: Optional[dict] = None, disruptions: Iterable[Disruption] = ()) -> tuple[RunSettings, Optional[Priority], list[str]]:
    """Combine manager instructions, standing feedback and policy into engine settings.

    Returns (settings, priority, notes) where notes explain what was applied (shown in the UI).
    """
    s = RunSettings()
    notes: list[str] = []
    priority: Optional[Priority] = None

    # standing feedback first, so explicit request instructions override it
    for raw in feedback:
        fb = FeedbackPreference.model_validate({k: v for k, v in raw.items() if k != "active"})
        if fb.kind == "avoid_employee" and fb.employee_id:
            (s.excluded_employee_ids if fb.strength == "hard" else s.avoid_employee_ids).append(fb.employee_id)
            notes.append(f"Feedback: {'never use' if fb.strength == 'hard' else 'avoid'} {fb.employee_name}")
        elif fb.kind == "prefer_employee" and fb.employee_id:
            s.prefer_employee_ids.append(fb.employee_id)
            notes.append(f"Feedback: prefer {fb.employee_name}")
        elif fb.kind == "overtime_rule" and fb.overtime_mode == "never":
            s.allow_overtime = False
            notes.append("Feedback: never use overtime")
        elif fb.kind == "overtime_rule" and fb.overtime_mode == "only_if_unavoidable":
            s.weight_multipliers["overtime_hour"] = 25.0
            notes.append("Feedback: overtime only if unavoidable")
        elif fb.kind == "objective_priority" and fb.priority:
            priority = fb.priority
            notes.append(f"Feedback: prioritize {fb.priority.value.replace('_', ' ')}")

    if parsed is not None:
        p = parsed.preferences
        s.locked_employee_ids = sorted(set(s.locked_employee_ids) | set(p.locked_employee_ids))
        s.excluded_employee_ids = sorted(set(s.excluded_employee_ids) | set(p.excluded_employee_ids))
        if p.allow_overtime is not None:
            s.allow_overtime = p.allow_overtime
        if p.priority:
            priority = p.priority
        disrupted_assignments = {ds.shift(a.shift_id).assignment for a in ds.existing_schedule
                                 for d in parsed.disruptions if a.employee_id == d.employee_id
                                 and ds.shift(a.shift_id) and ds.shift(a.shift_id).date == d.date}
        for c in parsed.ad_hoc_constraints:
            if c.kind == "required_skill":
                for a in disrupted_assignments or {"*"}:
                    s.extra_required_skills.setdefault(a, []).append(str(c.value))
            elif c.kind == "max_daily_hours":
                s.constraint_overrides["max_daily_hours"] = float(c.value)
            elif c.kind == "only_team":
                depts = [d.id for d in ds.departments if str(c.value).lower() in (d.id.lower(), d.name.lower())]
                s.allowed_departments = depts or [str(c.value)]
            notes.append(f"Instruction: {c.text}")

    if priority == Priority.employee_preferences:
        s.weight_multipliers["preference"] = 10.0

    if policy_config:
        hard = policy_config.get("hard", {}).get("global", {})
        base = ds.constraints.model_dump()
        for key, (field, stricter) in POLICY_TO_CONSTRAINT.items():
            if key in hard:
                current = s.constraint_overrides.get(field, base.get(field))
                value = float(hard[key]) if current is None else stricter(float(hard[key]), float(current))
                if current is None or value != float(current):
                    s.constraint_overrides[field] = value
                    notes.append(f"Policy: {field.replace('_', ' ')} = {value:g}")
        if hard.get("overtime_allowed") is False:
            s.allow_overtime = False
            notes.append("Policy: overtime not allowed")
        skills = policy_config.get("required_skills", {})
        known = {sh.assignment for sh in ds.shifts} | {d.id for d in ds.departments}
        for scope in ("by_assignment", "by_team"):
            for key, vals in skills.get(scope, {}).items():
                target = next((k for k in known if k.lower() == key.lower()), None)
                if target:
                    s.extra_required_skills.setdefault(target, []).extend(vals)
    return s, priority, notes


def strategy_order(priority: Optional[Priority]) -> list[str]:
    order = ["recommended", "min_employees", "min_overtime", "max_fairness"]
    if priority is not None:
        first = PRIORITY_STRATEGY[priority]
        order.remove(first)
        order.insert(0, first)
    return order


# ------------------------------------------------------------- facts out

def change_facts(ds: Dataset, option: RepairOption) -> list[ChangeFact]:
    names = {e.id: e.name for e in ds.employees}
    out: list[ChangeFact] = []
    lost: dict[str, list] = {}
    for c in option.changes:
        if c.from_employee_id:
            lost.setdefault(c.from_employee_id, []).append(c)
    for c in option.changes:
        shift = f"{c.start}-{c.end}"
        if c.from_employee_id:
            out.append(ChangeFact(employee_id=c.from_employee_id, employee_name=names[c.from_employee_id],
                                  change_type="unassigned", date=c.date, from_assignment=c.assignment, from_shift=shift))
        if c.to_employee_id:
            moved = next((x for x in lost.get(c.to_employee_id, []) if x.date == c.date), None)
            if moved:
                out.append(ChangeFact(employee_id=c.to_employee_id, employee_name=names[c.to_employee_id],
                                      change_type="reassigned", date=c.date, from_assignment=moved.assignment,
                                      to_assignment=c.assignment, from_shift=f"{moved.start}-{moved.end}", to_shift=shift))
            else:
                out.append(ChangeFact(employee_id=c.to_employee_id, employee_name=names[c.to_employee_id],
                                      change_type="added", date=c.date, to_assignment=c.assignment, to_shift=shift))
    # an employee who moved should not also appear as simply 'unassigned' from the slot they left
    moved_ids = {(f.employee_id, f.date) for f in out if f.change_type == "reassigned"}
    return [f for f in out if not (f.change_type == "unassigned" and (f.employee_id, f.date) in moved_ids)]


def explanation_facts(ds: Dataset, result: RepairResult, option: RepairOption,
                      citations: Iterable[PolicyCitation] = (), labels: Optional[dict] = None) -> ExplanationFacts:
    names = {e.id: e.name for e in ds.employees}
    if result.disruptions:
        d = result.disruptions[0]
    else:   # a schedule-conflict run: describe the first shift that had to be re-covered
        s = ds.shift(result.disrupted_shifts[0])
        d = Disruption(id="conflict", employee_id=ds.assignment_map().get(s.id) or "", date=s.date,
                       start=s.start, end=s.end, reason=None)
    labels = labels or {}
    c = result.constraints_used
    checked = [labels.get("required_skills", "Required skills"),
               f"{labels.get('min_rest_hours', 'Minimum rest')}: {c.get('min_rest_hours', 0):g}h",
               labels.get("max_weekly_hours", "Weekly hours limit"), "No overlapping shifts", "Availability"]
    if not c.get("allow_overtime", True):
        checked.append("No overtime")
    return ExplanationFacts(
        status="PARTIAL" if option.impact.unfilled_shifts else ("OPTIMAL" if option.status == "OPTIMAL" else "FEASIBLE"),
        disruption=ai_disruption(d), disrupted_employee_name=names.get(d.employee_id, d.employee_id),
        changes=change_facts(ds, option),
        selected=[SelectedFact(employee_id=s.employee_id, employee_name=s.employee_name, covers_assignment=s.covers,
                               available=s.available, skills_match=s.skills_match, matched_skills=s.matched_skills,
                               overtime_hours=s.overtime_hours_added, weekly_hours_before=s.weekly_hours_before,
                               weekly_hours_after=s.weekly_hours_after, max_weekly_hours=s.max_weekly_hours,
                               rest_hours_before_shift=s.rest_hours_before_shift,
                               previous_changes_this_period=s.previous_changes_30d) for s in option.selected],
        rejected=[RejectedFact(employee_id=r.employee_id, employee_name=r.employee_name, reason_code=r.reason_code,
                               detail=r.detail) for r in result.rejected[:6]] if option.option_id == result.recommended_option_id else [],
        metrics=MetricsFact(assignments_changed=option.impact.assignments_changed,
                            employees_affected=option.impact.employees_affected,
                            overtime_hours=option.impact.overtime_hours_added, hard_constraint_violations=0,
                            unfilled_requirements=option.impact.unfilled_shifts,
                            preference_violations=option.fairness.preference_violations,
                            impact_score=option.impact.impact_score, impact_level=option.impact.impact_level,
                            fairness_score=option.fairness.fairness_score),
        constraints_checked=checked, policies_applied=list(citations),
        infeasibility_reasons=result.infeasibility_reasons)


def candidate_facts(ds: Dataset, result: RepairResult) -> list[CandidateFacts]:
    return [CandidateFacts(candidate_id=o.option_id, label=o.label, strategy=o.strategy,
                           status="PARTIAL" if o.impact.unfilled_shifts else ("OPTIMAL" if o.status == "OPTIMAL" else "FEASIBLE"),
                           changes=change_facts(ds, o),
                           metrics=MetricsFact(assignments_changed=o.impact.assignments_changed,
                                               employees_affected=o.impact.employees_affected,
                                               overtime_hours=o.impact.overtime_hours_added,
                                               unfilled_requirements=o.impact.unfilled_shifts,
                                               preference_violations=o.fairness.preference_violations,
                                               impact_score=o.impact.impact_score, impact_level=o.impact.impact_level,
                                               fairness_score=o.fairness.fairness_score))
            for o in result.options]
