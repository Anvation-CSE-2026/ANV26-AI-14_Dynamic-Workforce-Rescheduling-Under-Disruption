"""Policy constraint vocabulary, validation, conflict resolution and optimizer config.

This module is the boundary between language and optimization: anything that
comes out of a policy (via LLM or rules) must pass ``validate_constraint``
before it can reach CP-SAT, and conflicts are resolved deterministically.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

Strictness = Literal["lower", "higher", "false_wins", "true_wins", "none"]


@dataclass(frozen=True)
class ConstraintTypeSpec:
    description: str
    value_kind: Literal["number", "integer", "boolean", "string"]
    unit: Optional[str] = None
    bounds: Optional[tuple[float, float]] = None
    stricter: Strictness = "none"
    unit_aliases: tuple[str, ...] = ()


_HOURS = ("h", "hr", "hrs", "hour", "hours")

CONSTRAINT_TYPES: dict[str, ConstraintTypeSpec] = {
    "max_daily_hours": ConstraintTypeSpec("maximum working hours per day", "number", "hours", (1, 24), "lower", _HOURS),
    "max_weekly_hours": ConstraintTypeSpec("maximum working hours per week", "number", "hours", (1, 168), "lower", _HOURS),
    "minimum_rest": ConstraintTypeSpec("minimum rest between two shifts", "number", "hours", (0, 48), "higher", _HOURS),
    "max_overtime_weekly": ConstraintTypeSpec("maximum overtime hours per week", "number", "hours", (0, 80), "lower", _HOURS),
    "overtime_allowed": ConstraintTypeSpec("whether overtime may be scheduled at all", "boolean", None, None, "false_wins"),
    "overtime_requires_approval": ConstraintTypeSpec("overtime needs explicit manager approval", "boolean", None, None, "true_wins"),
    "max_consecutive_days": ConstraintTypeSpec("maximum consecutive working days", "integer", "days", (1, 14), "lower", ("day", "days")),
    "max_weekends_per_month": ConstraintTypeSpec("maximum weekends worked per month", "integer", "weekends", (0, 5), "lower", ("weekend", "weekends")),
    "min_staffing": ConstraintTypeSpec("minimum people on an assignment/role at any time", "integer", "people", (0, 1000), "higher", ("people", "person", "employees", "agents", "staff")),
    "required_skill": ConstraintTypeSpec("skill required to work an assignment/role", "string"),
    "max_schedule_changes_per_month": ConstraintTypeSpec("maximum times one employee's schedule may be changed per month", "integer", "changes", (0, 31), "lower", ("change", "changes")),
    "respect_employee_preferences": ConstraintTypeSpec("employee shift preferences should be respected", "boolean", None, None, "true_wins"),
}


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Optional[str] = None
    assignment: Optional[str] = None
    team: Optional[str] = None

    @property
    def is_global(self) -> bool:
        return not (self.role or self.assignment or self.team)

    def key(self) -> tuple:
        return tuple((x or "").strip().lower() for x in (self.role, self.assignment, self.team))

    def label(self) -> str:
        parts = [f"{k}={v}" for k, v in (("role", self.role), ("assignment", self.assignment), ("team", self.team)) if v]
        return ", ".join(parts) or "everyone"


class PolicySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    document: str
    section: str
    chunk_id: str
    quote: str


class PolicyConstraint(BaseModel):
    """One validated, source-tracked constraint."""

    model_config = ConfigDict(extra="forbid")

    constraint_id: str = ""
    constraint_type: str
    value: Union[bool, float, int, str]
    unit: Optional[str] = None
    severity: Literal["hard", "soft"]
    scope: Scope = Field(default_factory=Scope)
    source: PolicySource
    interpretation: str
    retrieval_confidence: Optional[float] = None
    interpretation_confidence: float = 0.0
    verified_by_rules: Optional[bool] = Field(
        default=None, description="True if the deterministic rule extractor read the same value from the quote")
    extracted_by: Literal["llm", "rules"] = "llm"


class ConflictOption(BaseModel):
    value: Union[bool, float, int, str]
    severity: str
    scope: str
    source: PolicySource


class PolicyConflict(BaseModel):
    constraint_type: str
    scope: str
    kind: Literal["different_values", "scoped_looser_than_global", "interpretation_mismatch"]
    options: list[ConflictOption]
    applied_value: Union[bool, float, int, str, None]
    resolution: Literal["strictest_applied", "needs_review"]
    message: str


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _coerce(spec: ConstraintTypeSpec, value: Any) -> Union[bool, float, int, str]:
    if spec.value_kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false", "yes", "no"):
            return value.strip().lower() in ("true", "yes")
        raise ValueError("expected true/false")
    if spec.value_kind in ("number", "integer"):
        if isinstance(value, bool):
            raise ValueError("expected a number")
        try:
            num = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("expected a number") from exc
        if spec.bounds and not spec.bounds[0] <= num <= spec.bounds[1]:
            raise ValueError(f"value {num:g} outside allowed range {spec.bounds[0]:g}–{spec.bounds[1]:g}")
        if spec.value_kind == "integer":
            if not num.is_integer():
                raise ValueError("expected a whole number")
            return int(num)
        return int(num) if num.is_integer() else num
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected non-empty text")
    return value.strip()


def constraint_id(ctype: str, scope: Scope, chunk_id: str, value: Any) -> str:
    raw = f"{ctype}|{scope.key()}|{chunk_id}|{value}"
    return "pc_" + hashlib.sha1(raw.encode()).hexdigest()[:10]


def validate_constraint(data: dict[str, Any]) -> PolicyConstraint:
    """Validate type, value, unit and bounds. Raises ``ValueError`` with a reason."""
    ctype = data.get("constraint_type")
    spec = CONSTRAINT_TYPES.get(ctype or "")
    if spec is None:
        raise ValueError(f"unsupported constraint type {ctype!r}")
    value = _coerce(spec, data.get("value"))
    unit = data.get("unit")
    if spec.unit:
        if unit and unit.strip().lower() not in (spec.unit, *spec.unit_aliases):
            raise ValueError(f"unit {unit!r} does not match {spec.unit!r}")
        unit = spec.unit
    else:
        unit = None
    scope = Scope.model_validate(data.get("scope") or {})
    payload = {**data, "value": value, "unit": unit, "scope": scope}
    c = PolicyConstraint.model_validate(payload)
    if not c.constraint_id:
        c.constraint_id = constraint_id(ctype, scope, c.source.chunk_id, value)
    return c


# ---------------------------------------------------------------------------
# Conflict resolution
# ---------------------------------------------------------------------------


def _strictest(spec: ConstraintTypeSpec, values: list[Any]) -> Any:
    if spec.stricter == "lower":
        return min(values)
    if spec.stricter == "higher":
        return max(values)
    if spec.stricter == "false_wins":
        return all(values)
    if spec.stricter == "true_wins":
        return any(values)
    return None


def _looser(spec: ConstraintTypeSpec, a: Any, b: Any) -> bool:
    """Is ``a`` looser than ``b``?"""
    if spec.stricter == "lower":
        return a > b
    if spec.stricter == "higher":
        return a < b
    if spec.stricter == "false_wins":
        return bool(a) and not bool(b)
    if spec.stricter == "true_wins":
        return not bool(a) and bool(b)
    return False


def _option(c: PolicyConstraint) -> ConflictOption:
    return ConflictOption(value=c.value, severity=c.severity, scope=c.scope.label(), source=c.source)


def resolve_conflicts(constraints: list[PolicyConstraint]) -> tuple[list[PolicyConstraint], list[PolicyConflict]]:
    """Return (applied constraints, conflicts).

    * Same type + same scope, different values → strictest hard value applied,
      conflict reported (``strictest_applied``). Types with no ordering → ``needs_review``.
    * Hard beats soft for the same type + scope.
    * A role/assignment/team rule looser than the global rule → global still
      applies (both are enforced, so the stricter one binds); reported for review.
    * Identical values from several documents merge silently (first source kept).
    """
    applied: list[PolicyConstraint] = []
    conflicts: list[PolicyConflict] = []

    groups: dict[tuple, list[PolicyConstraint]] = {}
    for c in constraints:
        if c.constraint_type == "required_skill":
            groups.setdefault((c.constraint_type, c.scope.key(), str(c.value).lower()), []).append(c)
        else:
            groups.setdefault((c.constraint_type, c.scope.key()), []).append(c)

    for group in groups.values():
        spec = CONSTRAINT_TYPES[group[0].constraint_type]
        hard = [c for c in group if c.severity == "hard"]
        pool = hard or group
        values = {c.value for c in pool}
        if len(values) == 1:
            applied.append(pool[0])
            continue
        strict = _strictest(spec, [c.value for c in pool])
        if strict is None:
            conflicts.append(PolicyConflict(
                constraint_type=group[0].constraint_type, scope=group[0].scope.label(), kind="different_values",
                options=[_option(c) for c in pool], applied_value=None, resolution="needs_review",
                message=f"Policies disagree on {spec.description} for {group[0].scope.label()}; none applied until reviewed."))
            continue
        winner = next(c for c in pool if c.value == strict)
        applied.append(winner)
        conflicts.append(PolicyConflict(
            constraint_type=winner.constraint_type, scope=winner.scope.label(), kind="different_values",
            options=[_option(c) for c in pool], applied_value=strict, resolution="strictest_applied",
            message=(f"Policies disagree on {spec.description} for {winner.scope.label()}: "
                     + " vs ".join(f"{c.value} ({c.source.document} §{c.source.section})" for c in pool)
                     + f". Applying the strictest: {strict}.")))

    globals_by_type = {c.constraint_type: c for c in applied if c.scope.is_global and c.severity == "hard"}
    for c in applied:
        g = globals_by_type.get(c.constraint_type)
        if g is None or c.scope.is_global or c.severity != "hard":
            continue
        spec = CONSTRAINT_TYPES[c.constraint_type]
        if _looser(spec, c.value, g.value):
            conflicts.append(PolicyConflict(
                constraint_type=c.constraint_type, scope=c.scope.label(), kind="scoped_looser_than_global",
                options=[_option(g), _option(c)], applied_value=g.value, resolution="strictest_applied",
                message=(f"{c.source.document} §{c.source.section} allows {c.value} for {c.scope.label()}, "
                         f"but {g.source.document} §{g.source.section} sets {g.value} for everyone. "
                         f"Both are enforced, so {g.value} applies. Confirm which policy should win.")))
    return applied, conflicts


def to_optimizer_config(applied: list[PolicyConstraint]) -> dict[str, Any]:
    """Shape the optimizer consumes. Values only; sources stay in the bundle for audit/explanations.

    {
      "hard":   {"global": {...}, "by_role": {role: {...}}, "by_assignment": {...}, "by_team": {...}},
      "soft":   {same shape},
      "required_skills": {"by_role": {role: [skills]}, "by_assignment": {...}, "global": [...]}
    }
    """
    def empty() -> dict:
        return {"global": {}, "by_role": {}, "by_assignment": {}, "by_team": {}}

    out: dict[str, Any] = {"hard": empty(), "soft": empty(),
                           "required_skills": {"global": [], "by_role": {}, "by_assignment": {}, "by_team": {}}}
    for c in applied:
        s = c.scope
        if c.constraint_type == "required_skill":
            rs = out["required_skills"]
            if s.is_global:
                rs["global"].append(c.value)
            for key, val in (("by_role", s.role), ("by_assignment", s.assignment), ("by_team", s.team)):
                if val:
                    rs[key].setdefault(val, []).append(c.value)
            continue
        bucket = out[c.severity]
        if s.is_global:
            bucket["global"][c.constraint_type] = c.value
        for key, val in (("by_role", s.role), ("by_assignment", s.assignment), ("by_team", s.team)):
            if val:
                bucket[key].setdefault(val, {})[c.constraint_type] = c.value
    return out
