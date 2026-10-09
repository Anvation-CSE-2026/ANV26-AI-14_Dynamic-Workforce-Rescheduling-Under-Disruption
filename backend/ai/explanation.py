"""Grounded explanations of optimizer results.

Two generators share one contract (``ExplanationFacts`` → ``Explanation``):

* ``TemplateExplainer`` — deterministic, always available, always grounded.
* ``LLMExplainer`` — more natural wording; its output is checked by
  ``check_grounding`` and replaced by the template output if it fails.

Round 2: explanations cite the organization policies the optimizer enforced
(``ExplanationFacts.policies_applied``, filled from ``rag.PolicyBundle``).

The explainer never sees the schedule or the CP-SAT model, only the facts the
backend chose to expose. If a fact isn't in ``ExplanationFacts``, it can't be
said.
"""

from __future__ import annotations

import json
from datetime import date as Date
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict

from . import prompts
from .grounding import check_narration
from .providers.base import AIProvider, LLMError
from .schemas import (
    Explanation,
    ExplanationFacts,
    ExplanationPoint,
    Meta,
    PolicyCitation,
    RejectedFact,
)
from .structured import call_structured

Mode = Literal["auto", "llm", "template"]

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


def _plural(n: float, word: str) -> str:
    return f"{_num(n)} {word}{'' if n == 1 else 's'}"


def _day(iso: str) -> str:
    return Date.fromisoformat(iso).strftime("%a %d %b")


_REJECTION_TEXT = {
    "UNAVAILABLE": "is not available at that time",
    "MISSING_SKILL": "doesn't have the required skill",
    "MISSING_CERTIFICATION": "doesn't hold the required certification",
    "WOULD_UNCOVER_SHIFT": "would leave another shift uncovered",
    "SCHEDULE_CONFLICT": "has to come off this shift because of a schedule conflict",
    "WOULD_EXCEED_MAX_HOURS": "would exceed their maximum working hours",
    "WOULD_CREATE_OVERTIME": "would go into overtime",
    "REST_PERIOD_VIOLATION": "wouldn't get the required rest between shifts",
    "SHIFT_OVERLAP": "already has an overlapping shift",
    "LOCKED_BY_MANAGER": "was kept unchanged at your request",
    "EXCLUDED_BY_MANAGER": "was excluded at your request",
    "MANAGER_FEEDBACK": "was avoided because of your earlier feedback",
    "HIGHER_IMPACT": "would have caused more disruption to the schedule",
}

_POLICY_LABEL = {
    "max_daily_hours": "max {v}h per day", "max_weekly_hours": "max {v}h per week",
    "minimum_rest": "at least {v}h rest between shifts", "max_overtime_weekly": "max {v}h overtime per week",
    "overtime_allowed": "overtime {allowed}", "overtime_requires_approval": "overtime needs approval",
    "max_consecutive_days": "max {v} consecutive days", "max_weekends_per_month": "max {v} weekends per month",
    "min_staffing": "at least {v} people on shift", "required_skill": "requires {v}",
    "max_schedule_changes_per_month": "max {v} schedule changes per month",
    "respect_employee_preferences": "employee preferences respected",
}


def policy_label(c: PolicyCitation) -> str:
    v = _num(c.value) if isinstance(c.value, (int, float)) and not isinstance(c.value, bool) else c.value
    text = _POLICY_LABEL.get(c.constraint_type, c.constraint_type.replace("_", " ") + " {v}")
    return text.format(v=v, allowed="allowed" if c.value is True else "not allowed")


# ---------------------------------------------------------------------------
# Template explainer
# ---------------------------------------------------------------------------


class TemplateExplainer:
    def explain(self, f: ExplanationFacts) -> Explanation:
        d = f.disruption
        who = f.disrupted_employee_name
        when = f"{_day(d.date)}, {d.start_time}–{d.end_time}"
        m = f.metrics

        if f.status in ("INFEASIBLE", "PARTIAL"):
            return self._infeasible(f, who, when)

        points: list[ExplanationPoint] = []

        # Headline
        mine = next((c for c in f.changes if f.selected and c.employee_id == f.selected[0].employee_id and c.to_shift), None)
        if len(f.selected) == 1 and mine is not None:   # describe the shift actually covered, not the absence window
            when = f"{_day(mine.date)}, {mine.to_shift.replace('-', '–')}"
        if len(f.selected) == 1 and not who:
            s = f.selected[0]
            headline = (f"{s.employee_name} covers the open {s.covers_assignment} shift on {when}. "
                        f"{_plural(m.assignments_changed, 'assignment')} changed, "
                        f"{_num(m.overtime_hours)}h overtime.")
        elif len(f.selected) == 1:
            s = f.selected[0]
            headline = (f"{s.employee_name} covers {who}'s {s.covers_assignment} work on {when}. "
                        f"{_plural(m.assignments_changed, 'assignment')} changed, "
                        f"{_num(m.overtime_hours)}h overtime.")
        else:
            headline = (f"{who}'s absence on {when} is covered with "
                        f"{_plural(m.assignments_changed, 'assignment change')} and "
                        f"{_num(m.overtime_hours)}h overtime.")

        # Why each selected person
        for i, s in enumerate(f.selected):
            refs = [f"selected.{i}.available", f"selected.{i}.skills_match"]
            skills = f" ({', '.join(s.matched_skills)})" if s.matched_skills else ""
            if s.matched_skills:
                refs.append(f"selected.{i}.matched_skills")
            if s.available and s.skills_match:
                text = f"{s.employee_name} is available then and has the required skills{skills}."
            elif s.available:
                text = f"{s.employee_name} is available then."
            else:
                text = f"{s.employee_name} was assigned by the optimizer."
            points.append(ExplanationPoint(text=text, fact_refs=refs))

            if s.weekly_hours_before is not None and s.weekly_hours_after is not None:
                limit = f" (limit {_num(s.max_weekly_hours)}h)" if s.max_weekly_hours is not None else ""
                ot = ("no overtime" if s.overtime_hours == 0
                      else f"{_num(s.overtime_hours)}h overtime")
                refs = [f"selected.{i}.weekly_hours_before", f"selected.{i}.weekly_hours_after",
                        f"selected.{i}.overtime_hours"]
                if s.max_weekly_hours is not None:
                    refs.append(f"selected.{i}.max_weekly_hours")
                if s.weekly_hours_before == s.weekly_hours_after:
                    hours = f"Their weekly hours stay at {_num(s.weekly_hours_after)}h{limit}"
                else:
                    hours = (f"Their week goes from {_num(s.weekly_hours_before)}h to "
                             f"{_num(s.weekly_hours_after)}h{limit}")
                points.append(ExplanationPoint(text=f"{hours}, so {ot}.", fact_refs=refs))
            elif s.overtime_hours == 0:
                points.append(ExplanationPoint(text=f"This adds no overtime for {s.employee_name}.",
                                               fact_refs=[f"selected.{i}.overtime_hours"]))
            if s.rest_hours_before_shift is not None:
                points.append(ExplanationPoint(
                    text=f"{s.employee_name} has {_num(s.rest_hours_before_shift)}h of rest before the shift.",
                    fact_refs=[f"selected.{i}.rest_hours_before_shift"]))
            if s.previous_changes_this_period is not None:
                n = s.previous_changes_this_period
                text = (f"{s.employee_name} hasn't had any other schedule changes this period."
                        if n == 0 else
                        f"{s.employee_name} has had {_plural(n, 'schedule change')} this period.")
                points.append(ExplanationPoint(
                    text=text, fact_refs=[f"selected.{i}.previous_changes_this_period"]))

        # Chain moves (someone else shifted to backfill)
        for i, c in enumerate(f.changes):
            if c.change_type == "reassigned" and c.from_assignment and c.to_assignment:
                if any(s.employee_id == c.employee_id and s.covers_assignment == c.to_assignment
                       for s in f.selected) and len(f.changes) <= 2:
                    continue  # already told the main story
                points.append(ExplanationPoint(
                    text=f"{c.employee_name} moves from {c.from_assignment} to {c.to_assignment}.",
                    fact_refs=[f"changes.{i}.from_assignment", f"changes.{i}.to_assignment"],
                ))

        # Overall impact
        impact = ""
        if m.impact_level:
            impact = f" Impact: {m.impact_level}"
            impact += f" ({_num(m.impact_score)}/100)." if m.impact_score is not None else "."
        points.append(ExplanationPoint(
            text=f"{_plural(m.employees_affected, 'employee')} affected, "
                 f"{_plural(m.hard_constraint_violations, 'hard-constraint violation')}.{impact}",
            fact_refs=["metrics.employees_affected", "metrics.hard_constraint_violations"]
            + (["metrics.impact_level"] if m.impact_level else []),
        ))
        if f.constraints_checked:
            points.append(ExplanationPoint(
                text="Rules checked: " + "; ".join(f.constraints_checked) + ".",
                fact_refs=["constraints_checked"],
            ))
        points += self._policies(f)

        return Explanation(headline=headline, points=points,
                           why_not_others=self._why_not(f.rejected), source="template")

    def _infeasible(self, f: ExplanationFacts, who: str, when: str) -> Explanation:
        m = f.metrics
        if f.status == "PARTIAL":
            headline = (f"Only a partial repair was found for {who}'s absence on {when}: "
                        f"{_plural(m.unfilled_requirements, 'requirement')} still uncovered.")
        else:
            headline = f"No feasible reschedule found for {who}'s absence on {when}."
        points = [
            ExplanationPoint(text=r if r.endswith(".") else r + ".", fact_refs=[f"infeasibility_reasons.{i}"])
            for i, r in enumerate(f.infeasibility_reasons)
        ]
        if f.constraints_checked:
            points.append(ExplanationPoint(text="Rules enforced: " + "; ".join(f.constraints_checked) + ".",
                                           fact_refs=["constraints_checked"]))
        points += self._policies(f)
        return Explanation(headline=headline, points=points,
                           why_not_others=self._why_not(f.rejected), source="template")

    @staticmethod
    def _why_not(rejected: list[RejectedFact]) -> list[ExplanationPoint]:
        out = []
        for i, r in enumerate(rejected):
            detail = f" ({r.detail})" if r.detail else ""
            refs = [f"rejected.{i}.reason_code"] + ([f"rejected.{i}.detail"] if r.detail else [])
            policy = ""
            if r.policy_id:
                policy, refs = f" under policy {r.policy_id}", refs + [f"rejected.{i}.policy_id"]
            out.append(ExplanationPoint(text=f"{r.employee_name} {_REJECTION_TEXT[r.reason_code]}{detail}{policy}.",
                                        fact_refs=refs))
        return out

    @staticmethod
    def _policies(f: ExplanationFacts) -> list[ExplanationPoint]:
        ok = [(i, c) for i, c in enumerate(f.policies_applied) if c.satisfied]
        bad = [(i, c) for i, c in enumerate(f.policies_applied) if not c.satisfied]
        out = []
        if ok:
            out.append(ExplanationPoint(
                text="Complies with " + "; ".join(f"{policy_label(c)} ({c.document} §{c.section})" for _, c in ok) + ".",
                fact_refs=[f"policies_applied.{i}" for i, _ in ok]))
        for i, c in bad:
            out.append(ExplanationPoint(text=f"Does NOT satisfy {policy_label(c)} ({c.document} §{c.section}).",
                                        fact_refs=[f"policies_applied.{i}.satisfied"]))
        return out


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------

_NEGATIVE_WORDS = ("no ", "not ", "couldn't", "could not", "unable", "partial", "uncovered", "infeasible")


def check_grounding(exp: Explanation, facts: ExplanationFacts,
                    roster_names: Optional[Iterable[str]] = None) -> list[str]:
    """Problems with ``exp`` relative to ``facts``. Empty list = grounded."""
    fd = json.loads(facts.model_dump_json())
    pts = list(exp.points) + list(exp.why_not_others)
    problems = check_narration([exp.headline] + [p.text for p in pts], [(p.text, p.fact_refs) for p in pts],
                               fd, roster_names)
    if facts.status in ("INFEASIBLE", "PARTIAL") and not any(w in exp.headline.lower() for w in _NEGATIVE_WORDS):
        problems.append("headline does not say the repair is incomplete")
    return problems


# ---------------------------------------------------------------------------
# LLM explainer
# ---------------------------------------------------------------------------


class _RawExplanation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    headline: str
    points: list[ExplanationPoint] = []
    why_not_others: list[ExplanationPoint] = []


class LLMExplainer:
    def __init__(self, provider: AIProvider) -> None:
        self.provider = provider

    def explain(self, facts: ExplanationFacts) -> Explanation:
        raw, trace = call_structured(self.provider, prompts.EXPLANATION,
                                     "FACTS:\n" + facts.model_dump_json(indent=2), _RawExplanation)
        return Explanation(headline=raw.headline, points=raw.points, why_not_others=raw.why_not_others,
                           source="llm", meta=Meta(prompt=prompts.EXPLANATION.id, provider=self.provider.name,
                                                    model=self.provider.model, trace_id=trace.trace_id))


class Explainer:
    """Tries the LLM in ``auto`` mode and always falls back to the template."""

    def __init__(self, provider: Optional[AIProvider] = None) -> None:
        self.template = TemplateExplainer()
        self.llm = LLMExplainer(provider) if provider else None

    def explain(self, facts: ExplanationFacts, mode: Mode = "auto",
                roster_names: Optional[Iterable[str]] = None) -> Explanation:
        if mode == "template" or self.llm is None:
            return self.template.explain(facts)
        warnings: list[str] = []
        try:
            exp = self.llm.explain(facts)
            warnings = check_grounding(exp, facts, roster_names)
            if not warnings:
                return exp
        except LLMError as exc:
            warnings = [str(exc)]
        if mode == "llm":
            raise LLMError("LLM explanation failed grounding: " + "; ".join(warnings))
        return self.template.explain(facts).model_copy(update={"grounding_warnings": warnings})
