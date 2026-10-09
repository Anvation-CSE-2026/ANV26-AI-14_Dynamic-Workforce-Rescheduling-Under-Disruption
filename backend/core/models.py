"""Canonical, domain-agnostic data model.

One engine serves every industry. A hospital ward shift, a CNC line shift,
a class period, an on-call block and a delivery route are all a ``Shift``: a
time window that needs one qualified person. Industry-specific fields live in
``attributes`` dicts, and the vocabulary shown to users comes from
``shared/domains/<domain>.json``, never from engine code.

Times are "HH:MM". A shift whose end is not after its start ends the next
day (night shifts).
"""

from __future__ import annotations

from datetime import date as Date, datetime, timedelta
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DomainId = Literal["healthcare", "manufacturing", "education", "technology", "logistics"]
DOMAINS: tuple[str, ...] = ("healthcare", "manufacturing", "education", "technology", "logistics")


def parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hh, mm = str(value).strip().split(":")
        h, m = int(hh), int(mm)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"time must be HH:MM, got {value!r}") from exc
    if h == 24 and m == 0:
        return 24, 0
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"time out of range: {value!r}")
    return h, m


def normalize_hhmm(value: str) -> str:
    h, m = parse_hhmm(value)
    return f"{h:02d}:{m:02d}"


def interval(day: str, start: str, end: str) -> tuple[datetime, datetime]:
    """Absolute [start, end) for a window on ``day``; end ≤ start means it ends the next day."""
    d = Date.fromisoformat(day)
    sh, sm = parse_hhmm(start)
    eh, em = parse_hhmm(end)
    s = datetime(d.year, d.month, d.day) + timedelta(hours=sh, minutes=sm)
    e = datetime(d.year, d.month, d.day) + timedelta(hours=eh, minutes=em)
    if e <= s:
        e += timedelta(days=1)
    return s, e


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Organization(_Model):
    id: str = "org-demo"
    name: str = Field(min_length=1)
    domain: DomainId
    location: Optional[str] = None
    timezone: str = "Asia/Kolkata"
    size: Optional[str] = None


class Department(_Model):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Optional[str] = Field(default=None, description="unit, line, grade, team, depot …")


class Preferences(_Model):
    avoid_weekends: bool = False
    preferred_shift_types: list[str] = Field(default_factory=list)
    avoid_shift_types: list[str] = Field(default_factory=list)


class Contribution(_Model):
    """One piece of extra work someone took on: the fairness engine's raw data (never reward points)."""

    date: str
    kind: Literal["additional", "volunteer", "emergency", "reschedule", "overtime"] = "additional"
    hours: float = Field(default=0, ge=0, le=48)
    completed: bool = True
    ref: Optional[str] = None

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        Date.fromisoformat(v)
        return v


class History(_Model):
    """Recent history used for historical fairness.

    The ``*_30d`` counters are the imported baseline; ``contributions`` is the dated ledger ResQWork keeps
    from then on (and that imports may provide). The fairness engine reads both, with time decay.
    """

    disruptions_absorbed_30d: int = 0
    overtime_hours_30d: float = 0
    schedule_changes_30d: int = 0
    contributions: list[Contribution] = Field(default_factory=list)


class Employee(_Model):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    department: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Literal["active", "inactive"] = "active"
    skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    max_daily_hours: float = Field(default=12, gt=0, le=24)
    contracted_weekly_hours: float = Field(default=40, gt=0, le=168, description="Hours above this are overtime")
    max_weekly_hours: float = Field(default=48, gt=0, le=168, description="Hard cap including overtime")
    preferences: Preferences = Field(default_factory=Preferences)
    history: History = Field(default_factory=History)
    attributes: dict[str, Any] = Field(default_factory=dict, description="Domain-specific fields")

    @model_validator(mode="after")
    def _caps(self) -> "Employee":
        if self.max_weekly_hours < self.contracted_weekly_hours:
            raise ValueError("max_weekly_hours must be ≥ contracted_weekly_hours")
        return self

    @property
    def qualifications(self) -> set[str]:
        return {q.lower() for q in self.skills + self.certifications}


class Shift(_Model):
    """A unit of demand: one person, one time window, one place."""

    id: str = Field(min_length=1)
    date: str
    start: str
    end: str
    assignment: str = Field(min_length=1, description="What is being covered: 'ICU Day', 'Line 2', 'Class 8B Maths'")
    department: Optional[str] = None
    shift_type: Optional[str] = Field(default=None, description="Day, Night, Morning, Period 2, On-call …")
    required_skills: list[str] = Field(default_factory=list, description="ALL are required")
    required_certifications: list[str] = Field(default_factory=list, description="ALL are required")
    priority: Literal["critical", "high", "normal"] = "normal"
    location: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        Date.fromisoformat(v)
        return v

    @field_validator("start", "end")
    @classmethod
    def _time(cls, v: str) -> str:
        return normalize_hhmm(v)

    @model_validator(mode="after")
    def _nonzero(self) -> "Shift":
        if self.start == self.end:
            raise ValueError("shift start and end are equal")
        return self

    @property
    def window(self) -> tuple[datetime, datetime]:
        return interval(self.date, self.start, self.end)

    @property
    def hours(self) -> float:
        s, e = self.window
        return round((e - s).total_seconds() / 3600, 2)

    @property
    def requirements(self) -> set[str]:
        return {q.lower() for q in self.required_skills + self.required_certifications}


class Assignment(_Model):
    shift_id: str = Field(min_length=1)
    employee_id: str = Field(min_length=1)


class Availability(_Model):
    employee_id: str = Field(min_length=1)
    date: str
    start: Optional[str] = None
    end: Optional[str] = None
    kind: Literal["unavailable", "leave", "preferred_off"] = "unavailable"
    reason: Optional[str] = None

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        Date.fromisoformat(v)
        return v

    @field_validator("start", "end")
    @classmethod
    def _time(cls, v: Optional[str]) -> Optional[str]:
        return normalize_hhmm(v) if v else v

    @property
    def window(self) -> tuple[datetime, datetime]:
        if self.start and self.end:
            return interval(self.date, self.start, self.end)
        s, _ = interval(self.date, "00:00", "23:59")
        return s, s + timedelta(days=1)


class Disruption(_Model):
    """Something that breaks the existing schedule. Round 2 repairs employee unavailability."""

    id: str = Field(min_length=1)
    type: Literal["employee_unavailability"] = "employee_unavailability"
    employee_id: str = Field(min_length=1)
    date: str
    start: Optional[str] = None
    end: Optional[str] = None
    reason: Optional[str] = None
    severity: Literal["critical", "high", "medium", "low"] = "high"
    label: Optional[str] = Field(default=None, description="Demo button text, e.g. 'ICU nurse unavailable'")

    def as_availability(self) -> Availability:
        return Availability(employee_id=self.employee_id, date=self.date, start=self.start, end=self.end,
                            kind="unavailable", reason=self.reason)


class OrgConstraints(_Model):
    """Organization-wide hard limits. Policy RAG can tighten these per run."""

    min_rest_hours: float = Field(default=11, ge=0, le=48)
    max_daily_hours: Optional[float] = Field(default=None, gt=0, le=24)
    max_weekly_hours: Optional[float] = Field(default=None, gt=0, le=168)
    allow_overtime: bool = True
    max_overtime_hours_per_week: float = Field(default=12, ge=0, le=80)
    fairness_window_days: int = Field(default=30, ge=1, le=365, description="Rolling fairness window")
    extra: dict[str, Any] = Field(default_factory=dict, description="Domain-specific constraint settings")


class Weights(_Model):
    unfilled: int = 100_000
    assignment_change: int = 1_000
    employee_affected: int = 400
    overtime_hour: int = 150
    fairness: int = 60
    preference: int = 40
    location: int = 30
    continuity: int = 20


class OptimizationSettings(_Model):
    minimum_change: bool = True
    fairness: bool = True
    skill_coverage: bool = True
    overtime_penalty: bool = True
    weights: Weights = Field(default_factory=Weights)


class Dataset(_Model):
    """Everything ResQWork needs about one organization. Matches shared/schemas/dataset.schema.json."""

    organization: Organization
    reference_date: Optional[str] = Field(default=None, description="'Today'; shifts that started before 'now' are frozen")
    reference_time: Optional[str] = Field(default=None, description="'Now' (HH:MM) on reference_date; default 00:00")
    departments: list[Department] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    employees: list[Employee]
    shifts: list[Shift]
    existing_schedule: list[Assignment]
    availability: list[Availability] = Field(default_factory=list)
    disruptions: list[Disruption] = Field(default_factory=list)
    constraints: OrgConstraints = Field(default_factory=OrgConstraints)
    optimization: OptimizationSettings = Field(default_factory=OptimizationSettings)

    # convenience lookups ----------------------------------------------------

    @property
    def today(self) -> Date:
        return Date.fromisoformat(self.reference_date) if self.reference_date else Date.today()

    def employee(self, emp_id: str) -> Optional[Employee]:
        return next((e for e in self.employees if e.id == emp_id), None)

    def shift(self, shift_id: str) -> Optional[Shift]:
        return next((s for s in self.shifts if s.id == shift_id), None)

    def assignment_map(self) -> dict[str, str]:
        return {a.shift_id: a.employee_id for a in self.existing_schedule}
