"""Compare alternative repairs produced by the optimizer.

The AI layer never creates candidates. The optimizer returns several feasible
repairs (e.g. one per objective profile); this module compares them
deterministically (best per dimension, dominated, non-compliant, trade-off
deltas) and optionally lets the LLM narrate that comparison, grounded in it.
"""

from __future__ import annotations

import json
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from . import prompts
from .grounding import check_narration
from .providers.base import AIProvider, LLMError
from .schemas import ChangeFact, ExplanationPoint, Meta, MetricsFact, Priority, SolveStatus
from .structured import call_structured


class CandidateFacts(BaseModel):
    """One optimizer-produced alternative."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    label: str = Field(description="Display name, e.g. 'Option A'")
    strategy: Optional[str] = Field(default=None, description="Objective profile used, e.g. 'minimize_changes'")
    status: SolveStatus
    metrics: MetricsFact
    changes: list[ChangeFact] = Field(default_factory=list)
    policy_violations: int = 0
    policy_warnings: list[str] = Field(default_factory=list)


Dimension = Literal["assignments_changed", "employees_affected", "overtime_hours", "impact_score",
                    "fairness_score", "preference_violations"]

_LOWER_IS_BETTER = {"assignments_changed", "employees_affected", "overtime_hours", "impact_score",
                    "preference_violations"}
_PRIORITY_DIM: dict[Priority, Dimension] = {
    Priority.minimize_changes: "assignments_changed",
    Priority.minimize_affected_employees: "employees_affected",
    Priority.minimize_overtime: "overtime_hours",
    Priority.fairness: "fairness_score",
    Priority.employee_preferences: "preference_violations",
}
_DIM_LABEL = {"assignments_changed": "assignment changes", "employees_affected": "employees affected",
              "overtime_hours": "overtime hours", "impact_score": "impact score",
              "fairness_score": "fairness score", "preference_violations": "preference violations"}


class Tradeoff(BaseModel):
    candidate_id: str
    versus: str
    better: dict[str, float] = Field(default_factory=dict, description="dimension → improvement (positive)")
    worse: dict[str, float] = Field(default_factory=dict, description="dimension → cost (positive)")
    text: str


class CandidateComparison(BaseModel):
    candidates: list[CandidateFacts]
    compliant: list[str]
    non_compliant: dict[str, str] = Field(default_factory=dict, description="candidate_id → reason")
    best_by: dict[str, list[str]] = Field(default_factory=dict)
    dominated: dict[str, str] = Field(default_factory=dict, description="candidate_id → dominating candidate_id")
    tradeoffs: list[Tradeoff] = Field(default_factory=list)
    recommended_id: Optional[str] = None
    recommendation_reason: str = ""
    headline: str = ""
    points: list[ExplanationPoint] = Field(default_factory=list)
    source: Literal["llm", "template"] = "template"
    grounding_warnings: list[str] = Field(default_factory=list)
    meta: Meta = Field(default_factory=Meta)


def _val(c: CandidateFacts, dim: str) -> Optional[float]:
    v = getattr(c.metrics, dim)
    return None if v is None else float(v)


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


def _better(dim: str, a: float, b: float) -> bool:
    return a < b if dim in _LOWER_IS_BETTER else a > b


def _noncompliance(c: CandidateFacts) -> Optional[str]:
    m = c.metrics
    if c.status not in ("OPTIMAL", "FEASIBLE"):
        return f"status {c.status}"
    if m.hard_constraint_violations:
        return f"{m.hard_constraint_violations} hard-constraint violations"
    if c.policy_violations:
        return f"{c.policy_violations} policy violations"
    if m.unfilled_requirements:
        return f"{m.unfilled_requirements} requirements left uncovered"
    return None


def compare(candidates: list[CandidateFacts], priority: Optional[Priority] = None) -> CandidateComparison:
    comp = CandidateComparison(candidates=candidates, compliant=[])
    for c in candidates:
        reason = _noncompliance(c)
        if reason:
            comp.non_compliant[c.candidate_id] = reason
        else:
            comp.compliant.append(c.candidate_id)
    pool = [c for c in candidates if c.candidate_id in comp.compliant]
    dims = [d for d in _DIM_LABEL if any(_val(c, d) is not None for c in pool)]

    for d in dims:
        vals = [(c.candidate_id, _val(c, d)) for c in pool if _val(c, d) is not None]
        if not vals:
            continue
        best = min(v for _, v in vals) if d in _LOWER_IS_BETTER else max(v for _, v in vals)
        comp.best_by[d] = [cid for cid, v in vals if v == best]

    for a in pool:
        for b in pool:
            if a is b:
                continue
            shared = [d for d in dims if _val(a, d) is not None and _val(b, d) is not None]
            if shared and all(not _better(d, _val(a, d), _val(b, d)) for d in shared) \
                    and any(_better(d, _val(b, d), _val(a, d)) for d in shared):
                comp.dominated[a.candidate_id] = b.candidate_id
                break

    # Baseline = least disruptive compliant candidate; trade-offs are measured against it.
    if pool:
        base_dim = "impact_score" if "impact_score" in comp.best_by else "assignments_changed"
        base = next(c for c in pool if c.candidate_id == comp.best_by.get(base_dim, [pool[0].candidate_id])[0])
        for c in pool:
            if c is base or c.candidate_id in comp.dominated:
                continue
            t = Tradeoff(candidate_id=c.candidate_id, versus=base.candidate_id, text="")
            for d in dims:
                a, b = _val(c, d), _val(base, d)
                if a is None or b is None or a == b:
                    continue
                delta = abs(a - b)
                (t.better if _better(d, a, b) else t.worse)[d] = delta
            gains = ", ".join(f"{_DIM_LABEL[d]} {_fmt(_val(c, d))} vs {_fmt(_val(base, d))}" for d in t.better)
            costs = ", ".join(f"{_DIM_LABEL[d]} {_fmt(_val(c, d))} vs {_fmt(_val(base, d))}" for d in t.worse)
            t.text = (f"{c.label} vs {base.label}: better on {gains or 'nothing'}"
                      + (f"; worse on {costs}" if costs else "") + ".")
            comp.tradeoffs.append(t)

        target = _PRIORITY_DIM.get(priority) if priority else None
        if target and target in comp.best_by:
            choices = [cid for cid in comp.best_by[target] if cid not in comp.dominated] or comp.best_by[target]
            comp.recommended_id = choices[0]
            comp.recommendation_reason = f"best on {_DIM_LABEL[target]}, your stated priority"
        else:
            comp.recommended_id = base.candidate_id
            comp.recommendation_reason = f"lowest {_DIM_LABEL[base_dim]} among compliant options"
    return comp


def template_narration(comp: CandidateComparison) -> tuple[str, list[ExplanationPoint]]:
    by_id = {c.candidate_id: (i, c) for i, c in enumerate(comp.candidates)}  # (index, candidate)
    points: list[ExplanationPoint] = []
    if comp.recommended_id:
        _, rec = by_id[comp.recommended_id]
        m = rec.metrics
        changes = f"{m.assignments_changed} assignment change{'' if m.assignments_changed == 1 else 's'}"
        headline = (f"{rec.label} is suggested ({comp.recommendation_reason}): "
                    f"{changes}, {_fmt(m.overtime_hours)}h overtime.")
    else:
        headline = "None of the alternatives is fully compliant."
    for j, t in enumerate(comp.tradeoffs):
        points.append(ExplanationPoint(text=t.text, fact_refs=[f"tradeoffs.{j}"]))
    for cid, by in comp.dominated.items():
        points.append(ExplanationPoint(
            text=f"{by_id[cid][1].label} is no better than {by_id[by][1].label} on any measure.",
            fact_refs=[f"dominated.{cid}"]))
    for cid, reason in comp.non_compliant.items():
        points.append(ExplanationPoint(text=f"{by_id[cid][1].label} is not compliant ({reason}).",
                                       fact_refs=[f"non_compliant.{cid}"]))
    return headline, points


class _RawNarration(BaseModel):
    model_config = ConfigDict(extra="ignore")
    headline: str
    points: list[ExplanationPoint] = []


class CandidateComparer:
    def __init__(self, provider: Optional[AIProvider] = None) -> None:
        self.provider = provider

    def compare(self, candidates: list[CandidateFacts], priority: Optional[Priority] = None,
                mode: Literal["auto", "template"] = "auto",
                roster_names: Optional[Iterable[str]] = None) -> CandidateComparison:
        comp = compare(candidates, priority)
        comp.headline, comp.points = template_narration(comp)
        if mode == "template" or self.provider is None or len(candidates) < 2:
            return comp
        facts = json.loads(comp.model_dump_json(include={"candidates", "compliant", "non_compliant", "best_by",
                                                         "dominated", "tradeoffs", "recommended_id",
                                                         "recommendation_reason"}))
        try:
            raw, trace = call_structured(self.provider, prompts.CANDIDATE_COMPARISON,
                                         "FACTS:\n" + json.dumps(facts, indent=2), _RawNarration)
        except LLMError as exc:
            comp.grounding_warnings = [str(exc)]
            return comp
        texts = [raw.headline] + [p.text for p in raw.points]
        problems = check_narration(texts, [(p.text, p.fact_refs) for p in raw.points], facts, roster_names)
        labels = {c.candidate_id: c.label for c in candidates}
        for cid in list(comp.dominated) + list(comp.non_compliant):
            if labels[cid] in raw.headline and any(w in raw.headline.lower() for w in ("recommend", "best", "choose")):
                problems.append(f"headline promotes {labels[cid]}, which is dominated or non-compliant")
        if problems:
            comp.grounding_warnings = problems
            return comp
        comp.headline, comp.points, comp.source = raw.headline, raw.points, "llm"
        comp.meta = Meta(prompt=prompts.CANDIDATE_COMPARISON.id, provider=self.provider.name,
                         model=self.provider.model, trace_id=trace.trace_id)
        return comp
