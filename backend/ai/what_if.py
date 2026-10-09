"""What-if question → ``ScenarioSpec`` the optimizer can re-run.

The AI layer never predicts the outcome of a scenario. It only describes the
change; the optimizer produces the new candidate, and the comparison is
summarized from real results (see ``ai.candidates``).
"""

from __future__ import annotations

from datetime import date as Date
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from rag.constraints import CONSTRAINT_TYPES, _coerce

from . import prompts
from .disruption_parser import to_priority
from .providers.base import AIProvider, LLMError
from .resolution import Resolver
from .schemas import Confidence, Disruption, Issue, ManagerPreferences, Meta, ParseContext, Priority
from .structured import call_structured


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetOvertime(_Op):
    op: Literal["set_overtime"] = "set_overtime"
    allow: bool


class SetPriority(_Op):
    op: Literal["set_priority"] = "set_priority"
    priority: Priority


class AddUnavailability(_Op):
    op: Literal["add_unavailability"] = "add_unavailability"
    disruption: Disruption
    employee_name: str


class RemoveUnavailability(_Op):
    op: Literal["remove_unavailability"] = "remove_unavailability"
    employee_id: str
    employee_name: str


class LockEmployee(_Op):
    op: Literal["lock_employee"] = "lock_employee"
    employee_id: str
    employee_name: str


class ExcludeEmployee(_Op):
    op: Literal["exclude_employee"] = "exclude_employee"
    employee_id: str
    employee_name: str


class IncludeEmployee(_Op):
    op: Literal["include_employee"] = "include_employee"
    employee_id: str
    employee_name: str


class OverridePolicy(_Op):
    op: Literal["override_policy"] = "override_policy"
    constraint_type: str
    value: Union[bool, float, int]


ScenarioChange = Annotated[
    Union[SetOvertime, SetPriority, AddUnavailability, RemoveUnavailability, LockEmployee,
          ExcludeEmployee, IncludeEmployee, OverridePolicy],
    Field(discriminator="op"),
]


class ScenarioSpec(BaseModel):
    """Changes to apply on top of the current scenario before re-optimizing."""

    status: Literal["READY", "NEEDS_CLARIFICATION", "UNSUPPORTED", "ERROR"]
    changes: list[ScenarioChange] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    summary: str = ""
    confidence: Confidence = Field(default_factory=lambda: Confidence(score=0, level="none"))
    raw_request: str = ""
    meta: Meta = Field(default_factory=Meta)

    # ---- helpers for the backend -------------------------------------

    def apply_to(self, prefs: ManagerPreferences) -> ManagerPreferences:
        """New preferences with this scenario's overtime/priority/lock/exclude changes applied."""
        p = prefs.model_copy(deep=True)
        locked, excluded = set(p.locked_employee_ids), set(p.excluded_employee_ids)
        for c in self.changes:
            if isinstance(c, SetOvertime):
                p.allow_overtime = c.allow
            elif isinstance(c, SetPriority):
                p.priority = c.priority
            elif isinstance(c, LockEmployee):
                locked.add(c.employee_id)
            elif isinstance(c, ExcludeEmployee):
                excluded.add(c.employee_id)
            elif isinstance(c, IncludeEmployee):
                excluded.discard(c.employee_id)
        p.locked_employee_ids, p.excluded_employee_ids = sorted(locked), sorted(excluded)
        return p

    def added_disruptions(self) -> list[Disruption]:
        return [c.disruption for c in self.changes if isinstance(c, AddUnavailability)]

    def removed_unavailability(self) -> list[str]:
        return [c.employee_id for c in self.changes if isinstance(c, RemoveUnavailability)]

    def policy_overrides(self) -> dict[str, Union[bool, float, int]]:
        return {c.constraint_type: c.value for c in self.changes if isinstance(c, OverridePolicy)}


class _RawChange(BaseModel):
    model_config = ConfigDict(extra="ignore")
    op: str
    employee_mention: Optional[str] = None
    count: Optional[int] = None
    priority: Optional[str] = None
    value: Optional[Union[bool, float, str]] = None
    policy_type: Optional[str] = None
    date: Optional[str] = None
    date_expression: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    time_expression: Optional[str] = None
    reason: Optional[str] = None
    text: str = ""


class _RawScenario(BaseModel):
    model_config = ConfigDict(extra="ignore")
    is_what_if: bool = True
    changes: list[_RawChange] = Field(default_factory=list)


_OVERRIDABLE = {k for k, v in CONSTRAINT_TYPES.items() if v.value_kind != "string"}


class WhatIfParser:
    def __init__(self, provider: AIProvider) -> None:
        self.provider = provider

    def parse(self, question: str, ctx: ParseContext) -> ScenarioSpec:
        question = (question or "").strip()
        meta = Meta(prompt=prompts.WHAT_IF.id, provider=self.provider.name, model=self.provider.model)
        ref = Date.fromisoformat(ctx.reference_date)
        user = (prompts.reference_header(ctx.reference_date, ref.strftime("%A"), ctx.timezone) + "\n\n"
                + prompts.wrap_user_text("What-if question", question[:2000]))
        try:
            raw, trace = call_structured(self.provider, prompts.WHAT_IF, user, _RawScenario)
            meta.trace_id = trace.trace_id
        except LLMError as exc:
            return ScenarioSpec(status="ERROR", raw_request=question, meta=meta,
                                issues=[Issue(code="LLM_ERROR", message=f"Could not interpret the question ({exc}).")])
        spec = self.resolve(raw, ctx)
        spec.raw_request, spec.meta = question, meta
        return spec

    def resolve(self, raw: _RawScenario, ctx: ParseContext) -> ScenarioSpec:
        if not raw.is_what_if or not raw.changes:
            return ScenarioSpec(status="UNSUPPORTED", issues=[Issue(
                code="NOT_A_WHAT_IF", message="Ask a what-if, e.g. 'What if overtime is forbidden?'")])
        r = Resolver(ctx)
        changes: list = []
        unsupported: list[str] = []

        for i, c in enumerate(raw.changes):
            fp = f"changes[{i}]"
            if c.op == "set_overtime" and isinstance(c.value, bool):
                changes.append(SetOvertime(allow=c.value))
            elif c.op == "set_priority" and to_priority(c.priority):
                changes.append(SetPriority(priority=to_priority(c.priority)))
            elif c.op == "add_unavailability":
                if not c.employee_mention:
                    n = f"{c.count} " if c.count else ""
                    r.issues.append(Issue(code="NEEDS_NAMES", field=f"{fp}.employee_id",
                                          message=f"Which {n}employee(s) should be unavailable in this scenario?"))
                    continue
                d, det = r.disruption(c, fp)
                if d is not None:
                    changes.append(AddUnavailability(disruption=d, employee_name=det.employee_name))
            elif c.op in ("remove_unavailability", "lock_employee", "exclude_employee", "include_employee"):
                e = r.employee(c.employee_mention, f"{fp}.employee_id")
                if e is not None:
                    cls = {"remove_unavailability": RemoveUnavailability, "lock_employee": LockEmployee,
                           "exclude_employee": ExcludeEmployee, "include_employee": IncludeEmployee}[c.op]
                    changes.append(cls(employee_id=e.id, employee_name=e.name))
            elif c.op == "override_policy" and c.policy_type in _OVERRIDABLE:
                try:
                    value = _coerce(CONSTRAINT_TYPES[c.policy_type], c.value)
                    changes.append(OverridePolicy(constraint_type=c.policy_type, value=value))
                except ValueError as exc:
                    r.issues.append(Issue(code="INVALID_VALUE", field=f"{fp}.value",
                                          message=f"Can't set {c.policy_type.replace('_', ' ')} to {c.value!r}: {exc}."))
            else:
                unsupported.append(c.text or c.op)

        self._contradictions(changes, r)
        for t in unsupported:
            r.issues.append(Issue(code="UNSUPPORTED_CHANGE", blocking=False,
                                  message=f"Can't simulate: '{t}'. It will be ignored."))
        if unsupported:
            r.penalties.append(("part of the question can't be simulated", 0.15))

        if not changes and unsupported and not any(i.blocking for i in r.issues):
            status = "UNSUPPORTED"
        elif any(i.blocking for i in r.issues):
            status = "NEEDS_CLARIFICATION"
        else:
            status = "READY"
        spec = ScenarioSpec(status=status, changes=changes, unsupported=unsupported, issues=r.issues,
                            assumptions=r.assumptions, confidence=r.confidence())
        if status == "READY":
            spec.summary = describe(spec)
        return spec

    @staticmethod
    def _contradictions(changes: list, r: Resolver) -> None:
        overtime = {c.allow for c in changes if isinstance(c, SetOvertime)}
        priorities = {c.priority for c in changes if isinstance(c, SetPriority)}
        if len(overtime) > 1:
            r.issues.append(Issue(code="CONTRADICTORY_CHANGES", message="Overtime is both allowed and forbidden."))
        if len(priorities) > 1:
            r.issues.append(Issue(code="CONTRADICTORY_CHANGES",
                                  message="More than one top priority given: "
                                          + ", ".join(p.value.replace("_", " ") for p in priorities) + "."))
        by_emp: dict[str, set[str]] = {}
        for c in changes:
            emp = getattr(c, "employee_id", None) or getattr(getattr(c, "disruption", None), "employee_id", None)
            if emp:
                by_emp.setdefault(emp, set()).add(c.op)
        for emp, ops in by_emp.items():
            name = r.names.get(emp, emp)
            if {"lock_employee", "exclude_employee"} <= ops or {"add_unavailability", "remove_unavailability"} <= ops \
                    or {"exclude_employee", "include_employee"} <= ops:
                r.issues.append(Issue(code="CONTRADICTORY_CHANGES", message=f"Contradictory changes for {name}."))


def describe(spec: ScenarioSpec) -> str:
    parts = []
    for c in spec.changes:
        if isinstance(c, SetOvertime):
            parts.append("overtime " + ("allowed" if c.allow else "forbidden"))
        elif isinstance(c, SetPriority):
            parts.append("priority: " + c.priority.value.replace("_", " "))
        elif isinstance(c, AddUnavailability):
            d = c.disruption
            parts.append(f"{c.employee_name} also unavailable {d.date} {d.start_time}–{d.end_time}")
        elif isinstance(c, RemoveUnavailability):
            parts.append(f"{c.employee_name} available after all")
        elif isinstance(c, LockEmployee):
            parts.append(f"keep {c.employee_name} unchanged")
        elif isinstance(c, ExcludeEmployee):
            parts.append(f"don't use {c.employee_name}")
        elif isinstance(c, IncludeEmployee):
            parts.append(f"{c.employee_name} may be used")
        elif isinstance(c, OverridePolicy):
            parts.append(f"{c.constraint_type.replace('_', ' ')} = {c.value}")
    return "Scenario: " + "; ".join(parts) + "."
