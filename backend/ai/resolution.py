"""Deterministic resolution and validation used after LLM extraction.

Nothing here calls an LLM. These functions are what make the parser safe:
the LLM proposes, this module decides.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date as Date, timedelta
from typing import Optional

from .schemas import (
    AssignmentRef,
    Candidate,
    Confidence,
    Disruption,
    DisruptionDetail,
    EmployeeRef,
    Issue,
    ParseContext,
    ShiftRef,
)

# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

_POSSESSIVE = re.compile(r"(’s|'s)$")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")


def _norm(text: str) -> str:
    text = _POSSESSIVE.sub("", text.strip().lower())
    return " ".join(_NON_WORD.sub(" ", text).split())


@dataclass
class NameMatch:
    employee: Optional[EmployeeRef | AssignmentRef] = None
    candidates: list[Candidate] = field(default_factory=list)
    status: str = "UNKNOWN"  # MATCH | AMBIGUOUS | UNKNOWN


def resolve_employee(mention: str, employees: list) -> NameMatch:
    """Map a name as written by the manager to exactly one roster entry.

    Works for any entity with ``id``, ``name`` and ``aliases`` (employees, assignments).

    Order: exact id/name/alias → token-subset match ("Rahul" ⊂ "Rahul Sharma")
    → fuzzy suggestions (never auto-accepted).
    """
    m = _norm(mention)
    if not m:
        return NameMatch()

    exact = [
        e for e in employees
        if m in {_norm(e.id), _norm(e.name), *(_norm(a) for a in e.aliases)}
    ]
    if len(exact) == 1:
        return NameMatch(employee=exact[0], status="MATCH")
    if len(exact) > 1:
        return NameMatch(candidates=[Candidate(id=e.id, name=e.name) for e in exact], status="AMBIGUOUS")

    m_tokens = set(m.split())
    partial = []
    for e in employees:
        name_tokens = set(_norm(e.name).split())
        for alias in e.aliases:
            name_tokens |= set(_norm(alias).split())
        if m_tokens and m_tokens <= name_tokens:
            partial.append(e)
    if len(partial) == 1:
        return NameMatch(employee=partial[0], status="MATCH")
    if len(partial) > 1:
        return NameMatch(candidates=[Candidate(id=e.id, name=e.name) for e in partial], status="AMBIGUOUS")

    # Fuzzy suggestions only (typos like "Rahl").
    keys: dict[str, EmployeeRef] = {}
    for e in employees:
        keys[_norm(e.name)] = e
        first = _norm(e.name).split()[0] if e.name.strip() else ""
        if first:
            keys.setdefault(first, e)
    close = difflib.get_close_matches(m, list(keys), n=3, cutoff=0.7)
    seen: dict[str, EmployeeRef] = {}
    for k in close:
        seen.setdefault(keys[k].id, keys[k])
    return NameMatch(candidates=[Candidate(id=e.id, name=e.name) for e in seen.values()], status="UNKNOWN")


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def deterministic_date(expression: Optional[str], reference: Date) -> Optional[Date]:
    """Resolve the unambiguous relative expressions ourselves.

    Returns None when the expression is absent or not one we can resolve
    without guessing (e.g. "next Friday", "the 9th"); in that case the LLM's
    ISO date is used after range validation.
    """
    if not expression:
        return None
    e = _norm(expression)
    if "day after tomorrow" in e:
        return reference + timedelta(days=2)
    if re.search(r"\btomorrow\b", e):
        return reference + timedelta(days=1)
    if re.search(r"\b(today|tonight|this morning|this afternoon|this evening)\b", e):
        return reference
    if {"next", "last", "previous", "this"} & set(e.split()):
        # "next Friday" / "last Thursday" are ambiguous or relative to the past;
        # use the LLM's ISO date, which is then range-checked and confirmed.
        return None
    for i, wd in enumerate(_WEEKDAYS):
        if re.search(rf"\b{wd}\b", e):
            delta = (i - reference.weekday()) % 7
            return reference + timedelta(days=delta)
    return None


def parse_iso_date(value: Optional[str]) -> Optional[Date]:
    if not value:
        return None
    try:
        return Date.fromisoformat(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Times
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


def parse_hhmm(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = _TIME_RE.match(value)
    if not match:
        return None
    hh, mm = int(match.group(1)), int(match.group(2))
    if hh == 24 and mm == 0:
        return "23:59"
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return f"{hh:02d}:{mm:02d}"
    return None


FULL_DAY_WORDS = ("all day", "whole day", "full day", "entire day", "shift", "the day")
_PART_OF_DAY = {
    "morning": ("00:00", "13:00"),
    "afternoon": ("13:00", "18:00"),
    "evening": ("17:00", "23:59"),
}


def shift_window_for(employee_id: str, day: str, shifts: list[ShiftRef]) -> Optional[tuple[str, str]]:
    """Earliest start to latest end of the employee's shifts on ``day``."""
    todays = [s for s in shifts if s.employee_id == employee_id and s.date == day]
    if not todays:
        return None
    return min(s.start_time for s in todays), max(s.end_time for s in todays)


def window_from_expression(
    expression: Optional[str], shift: Optional[tuple[str, str]]
) -> tuple[Optional[tuple[str, str]], Optional[str]]:
    """Turn vague time words into a window, clipped to the scheduled shift.

    Returns (window, assumption_text). Window is None if we can't decide.
    """
    e = _norm(expression or "")
    if not e or any(w in e for w in FULL_DAY_WORDS):
        if shift:
            return shift, f"No times given; using the scheduled shift {shift[0]}–{shift[1]}."
        return None, None
    for word, (lo, hi) in _PART_OF_DAY.items():
        if word in e:
            if not shift:
                return None, None
            start, end = max(shift[0], lo), min(shift[1], hi)
            if start >= end:
                return None, None
            return (start, end), f"Interpreted '{expression}' as {start}–{end} within the scheduled shift."
    return None, None


# ---------------------------------------------------------------------------
# Resolver: shared by the disruption, what-if and feedback parsers
# ---------------------------------------------------------------------------

_REASONS = {"sick", "emergency", "leave", "personal", "other"}


class Resolver:
    """Turns raw model mentions into validated, ID-based values.

    Accumulates ``issues`` (ask the manager), ``assumptions`` (disclosed
    defaults) and ``penalties`` (confidence reductions) as it goes.
    """

    def __init__(self, ctx: "ParseContext") -> None:
        self.ctx = ctx
        self.ref = Date.fromisoformat(ctx.reference_date)
        self.issues: list[Issue] = []
        self.assumptions: list[str] = []
        self.penalties: list[tuple[str, float]] = []
        self.names: dict[str, str] = {}

    # ----------------------------------------------------------- entities

    def employee(self, mention: Optional[str], field: str, missing_message: str = "Which employee?") -> Optional[EmployeeRef]:
        if not mention:
            self.issues.append(Issue(code="MISSING_EMPLOYEE", field=field, message=missing_message))
            return None
        match = resolve_employee(mention, self.ctx.employees)
        if match.status == "MATCH":
            self.names[match.employee.id] = match.employee.name
            return match.employee
        if match.status == "AMBIGUOUS":
            self.issues.append(Issue(code="AMBIGUOUS_EMPLOYEE", field=field, candidates=match.candidates,
                                     message=f"More than one employee matches '{mention}'. Which one?"))
        else:
            hint = (" Did you mean " + " or ".join(c.name for c in match.candidates) + "?") if match.candidates else ""
            self.issues.append(Issue(code="UNKNOWN_EMPLOYEE", field=field, candidates=match.candidates,
                                     message=f"No employee named '{mention}' in this schedule.{hint}"))
        return None

    def employee_ids(self, mentions: list[str], field: str) -> list[str]:
        out = []
        for m in mentions:
            e = self.employee(m, field)
            if e:
                out.append(e.id)
        return sorted(set(out))

    def assignment(self, mention: str, field: str) -> Optional[AssignmentRef]:
        if not self.ctx.assignments:
            self.assumptions.append(f"Assignment '{mention}' could not be checked (no assignment list supplied).")
            self.penalties.append(("assignment not verifiable", 0.1))
            return None
        match = resolve_employee(mention, self.ctx.assignments)
        if match.status == "MATCH":
            return match.employee
        code = "AMBIGUOUS_ASSIGNMENT" if match.status == "AMBIGUOUS" else "UNKNOWN_ASSIGNMENT"
        self.issues.append(Issue(code=code, field=field, candidates=match.candidates,
                                 message=f"Couldn't match the assignment '{mention}'."))
        return None

    # ---------------------------------------------------------- disruption

    def disruption(self, rd, fp: str) -> tuple[Optional[Disruption], Optional[DisruptionDetail]]:
        emp = self.employee(rd.employee_mention, f"{fp}.employee_id", "Which employee is unavailable?")
        day = self.date(rd, fp)
        window = self.window(rd, emp, day.isoformat(), fp) if day is not None else None
        if emp is None or day is None or window is None:
            return None, None

        detail = DisruptionDetail(employee_name=emp.name)
        shift_assignments = {s.assignment_id for s in self.ctx.shifts
                             if s.employee_id == emp.id and s.date == day.isoformat() and s.assignment_id}
        if getattr(rd, "assignment_mention", None):
            a = self.assignment(rd.assignment_mention, f"{fp}.assignment")
            if a is not None:
                detail.assignment_id, detail.assignment_source = a.id, "stated"
                if shift_assignments and a.id not in shift_assignments:
                    self.assumptions.append(
                        f"{emp.name} is scheduled on {', '.join(sorted(shift_assignments))} that day, "
                        f"not {a.name}; check the request.")
                    self.penalties.append(("stated assignment differs from schedule", 0.2))
            elif self.ctx.assignments:
                return None, None
        elif len(shift_assignments) == 1:
            detail.assignment_id, detail.assignment_source = next(iter(shift_assignments)), "schedule"

        reason = rd.reason if rd.reason in _REASONS else "unspecified"
        try:
            d = Disruption(type="employee_unavailability", employee_id=emp.id, date=day.isoformat(),
                           start_time=window[0], end_time=window[1], reason=reason)
        except ValueError as exc:
            self.issues.append(Issue(code="INVALID_TIME", field=fp, message=f"The disruption is not valid: {exc}"))
            return None, None
        return d, detail

    def date(self, rd, fp: str) -> Optional[Date]:
        llm_day = parse_iso_date(rd.date)
        det_day = deterministic_date(rd.date_expression, self.ref)
        if rd.date and llm_day is None and det_day is None:
            self.issues.append(Issue(code="INVALID_DATE", field=f"{fp}.date",
                                     message=f"Couldn't understand the date '{rd.date_expression or rd.date}'."))
            return None
        day = det_day or llm_day
        if det_day and llm_day and det_day != llm_day:
            self.assumptions.append(f"'{rd.date_expression}' resolved to {det_day.isoformat()} "
                                    f"(model suggested {llm_day.isoformat()}; deterministic resolution used).")
            self.penalties.append(("model date disagreed with deterministic date", 0.15))
        if day is None:
            self.issues.append(Issue(code="MISSING_DATE", field=f"{fp}.date", message="Which date?"))
            return None
        if day < self.ref:
            self.issues.append(Issue(code="DATE_IN_PAST", field=f"{fp}.date",
                                     message=f"{day.isoformat()} is in the past. Past shifts can't be repaired."))
            return None
        if day > self.ref + timedelta(days=self.ctx.max_horizon_days):
            self.issues.append(Issue(code="DATE_OUT_OF_HORIZON", field=f"{fp}.date",
                                     message=f"{day.isoformat()} is more than {self.ctx.max_horizon_days} days ahead; "
                                             "only the current scheduling horizon can be repaired."))
            return None
        if det_day is None and rd.date_expression and llm_day is not None:
            self.penalties.append((f"date '{rd.date_expression}' resolved by the model only", 0.1))
        return day

    def window(self, rd, emp: Optional[EmployeeRef], day: str, fp: str) -> Optional[tuple[str, str]]:
        start, end = parse_hhmm(rd.start_time), parse_hhmm(rd.end_time)
        if (rd.start_time and not start) or (rd.end_time and not end):
            self.issues.append(Issue(code="INVALID_TIME", field=f"{fp}.start_time",
                                     message="Couldn't understand the time range."))
            return None
        shift = shift_window_for(emp.id, day, self.ctx.shifts) if emp else None

        if start and end:
            if end <= start:
                self.issues.append(Issue(code="INVALID_TIME", field=f"{fp}.end_time",
                                         message=f"End time {end} is not after start time {start}."))
                return None
            if emp and shift is None and self.ctx.shifts:
                self.assumptions.append(f"{emp.name} has no shift on {day}; they will only be excluded as a replacement.")
                self.penalties.append(("employee not scheduled that day", 0.1))
            return start, end

        if start or end:
            if shift:
                window = (start or shift[0], end or shift[1])
                if window[1] > window[0]:
                    self.assumptions.append(f"Only one time given; using {window[0]}–{window[1]} based on the scheduled shift.")
                    self.penalties.append(("one end of the time window taken from the schedule", 0.15))
                    return window
            self.issues.append(Issue(code="MISSING_TIME", field=f"{fp}.end_time" if start else f"{fp}.start_time",
                                     message="Please give both a start and an end time."))
            return None

        if emp is None:
            return None
        window, note = window_from_expression(rd.time_expression, shift)
        if window:
            self.assumptions.append(note)
            vague = rd.time_expression and not any(w in rd.time_expression.lower() for w in FULL_DAY_WORDS)
            self.penalties.append((("vague time interpreted" if vague else "time window taken from the schedule"),
                                   0.2 if vague else 0.05))
            return window
        self.issues.append(Issue(
            code="MISSING_TIME", field=f"{fp}.start_time",
            message=(f"{emp.name} has no scheduled shift on {day}. What time window are they unavailable?"
                     if shift is None else
                     f"What time is {emp.name} unavailable on {day}? ('{rd.time_expression}' is ambiguous.)")))
        return None

    # -------------------------------------------------------------- output

    def confidence(self) -> Confidence:
        return Confidence.from_penalties(self.penalties, blocked=any(i.blocking for i in self.issues))
