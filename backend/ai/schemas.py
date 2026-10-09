"""Schemas shared by the AI layer.

* ``Disruption`` is the canonical shared contract (Member 1). Do not add fields
  without a documented contract change; extra parse details live in
  ``DisruptionDetail``.
* Every model that receives model output forbids unknown fields, so malformed
  output fails loudly instead of leaking into the optimizer.
"""

from __future__ import annotations

from datetime import date as Date, time as Time
from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Canonical shared contract
# ---------------------------------------------------------------------------

DisruptionType = Literal["employee_unavailability"]
KNOWN_BUT_UNSUPPORTED_TYPES = {"workload_increase", "shift_understaffed", "assignment_unavailable"}
DisruptionReason = Literal["sick", "emergency", "leave", "personal", "other", "unspecified"]


def _parse_hhmm(value: str) -> Time:
    try:
        hh, mm = value.split(":")
        return Time(int(hh), int(mm))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"time must be HH:MM, got {value!r}") from exc


class Disruption(_Strict):
    """Canonical disruption passed to the optimizer. Matches the master contract."""

    type: DisruptionType
    employee_id: str = Field(min_length=1)
    date: str = Field(description="ISO date YYYY-MM-DD")
    start_time: str = Field(description="HH:MM, 24h")
    end_time: str = Field(description="HH:MM, 24h")
    reason: DisruptionReason = "unspecified"

    @field_validator("date")
    @classmethod
    def _valid_date(cls, v: str) -> str:
        Date.fromisoformat(v)
        return v

    @field_validator("start_time", "end_time")
    @classmethod
    def _valid_time(cls, v: str) -> str:
        return _parse_hhmm(v).strftime("%H:%M")

    @model_validator(mode="after")
    def _end_after_start(self) -> "Disruption":
        # end < start means the window ends the next day (night shifts); equal is meaningless
        if _parse_hhmm(self.end_time) == _parse_hhmm(self.start_time):
            raise ValueError("start_time and end_time are equal")
        return self


# ---------------------------------------------------------------------------
# Context the backend supplies
# ---------------------------------------------------------------------------


class EmployeeRef(_Strict):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    role: Optional[str] = None
    team: Optional[str] = None


class AssignmentRef(_Strict):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)


class ShiftRef(_Strict):
    """Subset of the canonical ScheduleEntry."""

    employee_id: str
    date: str
    start_time: str
    end_time: str
    assignment_id: Optional[str] = None


class ParseContext(_Strict):
    reference_date: str = Field(description="The manager's 'today', ISO date")
    timezone: str = "Asia/Kolkata"
    employees: list[EmployeeRef]
    assignments: list[AssignmentRef] = Field(default_factory=list)
    shifts: list[ShiftRef] = Field(default_factory=list)
    max_horizon_days: int = 14

    @field_validator("reference_date")
    @classmethod
    def _valid_date(cls, v: str) -> str:
        Date.fromisoformat(v)
        return v


# ---------------------------------------------------------------------------
# Shared result pieces
# ---------------------------------------------------------------------------


class Priority(str, Enum):
    minimize_changes = "minimize_changes"
    minimize_affected_employees = "minimize_affected_employees"
    minimize_overtime = "minimize_overtime"
    fairness = "fairness"
    employee_preferences = "employee_preferences"


class ManagerPreferences(_Strict):
    """Request-level manager intent, resolved to IDs."""

    locked_employee_ids: list[str] = Field(default_factory=list, description="Schedules that must not change")
    excluded_employee_ids: list[str] = Field(default_factory=list, description="Must not be used as replacements")
    allow_overtime: Optional[bool] = Field(default=None, description="None = organization policy")
    priority: Optional[Priority] = Field(default=None, description="None = default weights")


IssueCode = Literal[
    "UNKNOWN_EMPLOYEE", "AMBIGUOUS_EMPLOYEE", "MISSING_EMPLOYEE",
    "UNKNOWN_ASSIGNMENT", "AMBIGUOUS_ASSIGNMENT",
    "MISSING_DATE", "INVALID_DATE", "DATE_IN_PAST", "DATE_OUT_OF_HORIZON",
    "MISSING_TIME", "INVALID_TIME",
    "UNSUPPORTED_DISRUPTION", "UNSUPPORTED_CONSTRAINT", "UNSUPPORTED_CHANGE",
    "NOT_A_DISRUPTION", "NOT_A_WHAT_IF", "NOT_FEEDBACK",
    "LOCKED_EMPLOYEE_CONFLICT", "CONTRADICTORY_CHANGES", "NEEDS_NAMES", "INVALID_VALUE",
    "LLM_ERROR",
]


class Candidate(_Strict):
    id: str
    name: str


class Issue(_Strict):
    code: IssueCode
    message: str
    field: Optional[str] = None
    blocking: bool = True
    candidates: list[Candidate] = Field(default_factory=list)


class Confidence(_Strict):
    """Deterministic confidence: starts at 1.0, reduced by each disclosed factor.

    Not model self-assessment. Blocking issues force ``level='none'``.
    """

    score: float = Field(ge=0, le=1)
    level: Literal["high", "medium", "low", "none"]
    factors: list[str] = Field(default_factory=list)

    @classmethod
    def from_penalties(cls, penalties: list[tuple[str, float]], blocked: bool = False) -> "Confidence":
        if blocked:
            return cls(score=0.0, level="none", factors=[p[0] for p in penalties])
        score = max(0.0, round(1.0 - sum(p[1] for p in penalties), 2))
        level = "high" if score >= 0.85 else "medium" if score >= 0.6 else "low"
        return cls(score=score, level=level, factors=[p[0] for p in penalties])


class Meta(_Strict):
    """Audit metadata attached to every AI result."""

    prompt: str = ""
    provider: str = ""
    model: str = ""
    trace_id: str = ""


# ---------------------------------------------------------------------------
# Disruption parsing
# ---------------------------------------------------------------------------


class DisruptionDetail(_Strict):
    """Extra parse information aligned with ``ParseResult.disruptions`` (same index)."""

    employee_name: str
    assignment_id: Optional[str] = None
    assignment_source: Literal["stated", "schedule", "none"] = "none"


class AdHocConstraint(_Strict):
    """A one-off requirement the manager stated for this repair."""

    kind: Literal["required_skill", "max_daily_hours", "only_team"]
    value: Union[str, float]
    text: str


ParseStatus = Literal["READY", "NEEDS_CLARIFICATION", "UNSUPPORTED", "ERROR"]


class ParseResult(_Strict):
    """Only when ``status == "READY"`` may disruptions/preferences/constraints go to the optimizer."""

    status: ParseStatus
    disruptions: list[Disruption] = Field(default_factory=list)
    details: list[DisruptionDetail] = Field(default_factory=list)
    preferences: ManagerPreferences = Field(default_factory=ManagerPreferences)
    ad_hoc_constraints: list[AdHocConstraint] = Field(default_factory=list)
    unsupported_constraints: list[str] = Field(default_factory=list,
                                               description="Stated by the manager but NOT enforced. Show on the card.")
    issues: list[Issue] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list, description="What the parser filled in. Show on the card.")
    confidence: Confidence = Field(default_factory=lambda: Confidence(score=0, level="none"))
    confirmation_summary: str = ""
    raw_request: str = ""
    meta: Meta = Field(default_factory=Meta)

    @property
    def ready(self) -> bool:
        return self.status == "READY"


# Raw model output (never leaves the AI layer) --------------------------------


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RawDisruption(_Loose):
    type: str = "employee_unavailability"
    employee_mention: Optional[str] = None
    assignment_mention: Optional[str] = None
    date: Optional[str] = None
    date_expression: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    time_expression: Optional[str] = None
    reason: Optional[str] = None


class RawPreferences(_Loose):
    lock_employee_mentions: list[str] = Field(default_factory=list)
    exclude_employee_mentions: list[str] = Field(default_factory=list)
    allow_overtime: Optional[bool] = None
    priority: Optional[str] = None


class RawAdHoc(_Loose):
    kind: str
    value: Optional[Union[str, float]] = None
    text: str = ""


class RawExtraction(_Loose):
    is_disruption_report: bool = True
    disruptions: list[RawDisruption] = Field(default_factory=list)
    preferences: RawPreferences = Field(default_factory=RawPreferences)
    ad_hoc_constraints: list[RawAdHoc] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Explanation contract (optimizer → AI)
# ---------------------------------------------------------------------------

ChangeType = Literal["unassigned", "reassigned", "shift_moved", "added"]


class ChangeFact(_Strict):
    employee_id: str
    employee_name: str
    change_type: ChangeType
    date: str
    from_assignment: Optional[str] = None
    to_assignment: Optional[str] = None
    from_shift: Optional[str] = Field(default=None, description="e.g. '09:00-17:00'")
    to_shift: Optional[str] = None


class SelectedFact(_Strict):
    employee_id: str
    employee_name: str
    covers_assignment: str
    available: bool
    skills_match: bool
    matched_skills: list[str] = Field(default_factory=list)
    overtime_hours: float = 0
    weekly_hours_before: Optional[float] = None
    weekly_hours_after: Optional[float] = None
    max_weekly_hours: Optional[float] = None
    rest_hours_before_shift: Optional[float] = None
    previous_changes_this_period: Optional[int] = None


RejectionCode = Literal[
    "UNAVAILABLE", "MISSING_SKILL", "WOULD_EXCEED_MAX_HOURS", "WOULD_CREATE_OVERTIME",
    "REST_PERIOD_VIOLATION", "SHIFT_OVERLAP", "LOCKED_BY_MANAGER", "EXCLUDED_BY_MANAGER",
    "MANAGER_FEEDBACK", "HIGHER_IMPACT", "MISSING_CERTIFICATION", "WOULD_UNCOVER_SHIFT", "SCHEDULE_CONFLICT",
]


class RejectedFact(_Strict):
    employee_id: str
    employee_name: str
    reason_code: RejectionCode
    detail: Optional[str] = Field(default=None, description="Short factual detail, e.g. 'impact 22 vs 14'")
    policy_id: Optional[str] = Field(default=None, description="Policy behind the rejection, if any")


class MetricsFact(_Strict):
    assignments_changed: int
    employees_affected: int
    shift_changes: int = 0
    overtime_hours: float = 0
    hard_constraint_violations: int = 0
    unfilled_requirements: int = 0
    preference_violations: int = 0
    impact_score: Optional[float] = None
    impact_level: Optional[Literal["LOW", "MEDIUM", "HIGH"]] = None
    fairness_score: Optional[float] = None


class PolicyCitation(_Strict):
    """A policy constraint the optimizer enforced, with its source (from rag.PolicyBundle)."""

    policy_id: str
    document: str
    section: str
    constraint_type: str
    value: Union[bool, float, int, str]
    unit: Optional[str] = None
    satisfied: bool = True


SolveStatus = Literal["FEASIBLE", "OPTIMAL", "INFEASIBLE", "PARTIAL"]


class ExplanationFacts(_Strict):
    """Everything the explainer may talk about. If it's not here, it can't be said."""

    status: SolveStatus
    disruption: Disruption
    disrupted_employee_name: str
    changes: list[ChangeFact] = Field(default_factory=list)
    selected: list[SelectedFact] = Field(default_factory=list)
    rejected: list[RejectedFact] = Field(default_factory=list)
    metrics: MetricsFact
    constraints_checked: list[str] = Field(default_factory=list)
    policies_applied: list[PolicyCitation] = Field(default_factory=list)
    infeasibility_reasons: list[str] = Field(default_factory=list)


class ExplanationPoint(_Strict):
    text: str
    fact_refs: list[str] = Field(default_factory=list)


class Explanation(_Strict):
    headline: str
    points: list[ExplanationPoint] = Field(default_factory=list)
    why_not_others: list[ExplanationPoint] = Field(default_factory=list)
    source: Literal["llm", "template"] = "template"
    grounding_warnings: list[str] = Field(default_factory=list)
    meta: Meta = Field(default_factory=Meta)

    def as_text(self) -> str:
        lines = [self.headline] + [f"- {p.text}" for p in self.points]
        if self.why_not_others:
            lines.append("Other candidates:")
            lines += [f"- {p.text}" for p in self.why_not_others]
        return "\n".join(lines)
