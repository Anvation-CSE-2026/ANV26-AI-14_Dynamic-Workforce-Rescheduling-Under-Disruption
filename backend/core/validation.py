"""Dataset import and validation (JSON, CSV, manual form, demo).

``validate_dataset(raw)`` never raises on bad data. It validates record by
record, drops what it can't use, and returns a ``ValidationReport`` the
upload screen shows before any repair starts:

* errors   — records that were rejected (and why), or a fatal problem
* warnings — data that loads but deserves attention (open shifts, existing
  rule violations, shifts nobody is qualified for, …)
* stats + preview — what will be loaded
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import date as Date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from .models import (
    DOMAINS,
    Assignment,
    Availability,
    Dataset,
    Department,
    Disruption,
    Employee,
    OptimizationSettings,
    OrgConstraints,
    Organization,
    Shift,
)
from .rules import missing_qualifications, schedule_violations

Category = Literal["missing_field", "invalid_record", "duplicate", "invalid_shift", "unknown_reference",
                   "skill_mismatch", "constraint_conflict", "coverage", "fatal"]


class Finding(BaseModel):
    severity: Literal["error", "warning"]
    category: Category
    path: str
    message: str
    record_id: Optional[str] = None


class ValidationReport(BaseModel):
    status: Literal["valid", "valid_with_warnings", "invalid"]
    errors: list[Finding] = Field(default_factory=list)
    warnings: list[Finding] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)
    summary: str = ""
    dataset: Optional[Dataset] = Field(default=None, exclude=True)

    @property
    def ok(self) -> bool:
        return self.status != "invalid"


def _friendly(exc: ValidationError) -> list[tuple[str, str, Category]]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "record"
        kind = err.get("type", "")
        if kind == "missing":
            out.append((loc, f"missing required field '{loc}'", "missing_field"))
        elif kind == "extra_forbidden":
            out.append((loc, f"unknown field '{loc}'", "invalid_record"))
        else:
            msg = str(err.get("msg", "invalid value")).removeprefix("Value error, ")
            out.append((loc, f"{loc}: {msg}", "invalid_shift" if loc in ("start", "end", "date") else "invalid_record"))
    return out


def _records(raw: Any, key: str, model, report: ValidationReport, id_field: Optional[str] = "id") -> list:
    items = raw.get(key, []) if isinstance(raw, dict) else []
    if items is None:
        items = []
    if not isinstance(items, list):
        report.errors.append(Finding(severity="error", category="invalid_record", path=key,
                                     message=f"'{key}' must be a list"))
        return []
    good, seen = [], Counter()
    for i, item in enumerate(items):
        rid = str(item.get(id_field)) if isinstance(item, dict) and id_field and item.get(id_field) else None
        try:
            rec = model.model_validate(item)
        except ValidationError as exc:
            for loc, msg, cat in _friendly(exc):
                report.errors.append(Finding(severity="error", category=cat, path=f"{key}[{i}].{loc}",
                                             message=f"{key}[{i}]{' (' + rid + ')' if rid else ''}: {msg}",
                                             record_id=rid))
            continue
        if id_field:
            rid = getattr(rec, id_field)
            seen[rid] += 1
            if seen[rid] > 1:
                report.errors.append(Finding(severity="error", category="duplicate", path=f"{key}[{i}]",
                                             record_id=rid, message=f"duplicate {key[:-1]} id '{rid}' (record ignored)"))
                continue
        good.append(rec)
    return good


def validate_dataset(raw: Any) -> ValidationReport:
    report = ValidationReport(status="valid")
    if not isinstance(raw, dict):
        report.errors.append(Finding(severity="error", category="fatal", path="", message="Dataset must be a JSON object."))
        report.status = "invalid"
        return report

    try:
        org = Organization.model_validate(raw.get("organization") or {})
    except ValidationError as exc:
        for loc, msg, cat in _friendly(exc):
            report.errors.append(Finding(severity="error", category="fatal", path=f"organization.{loc}",
                                         message=f"organization: {msg}" + (f" (one of {', '.join(DOMAINS)})"
                                                                            if loc == "domain" else "")))
        report.status = "invalid"
        report.summary = _summary(report)
        return report

    departments = _records(raw, "departments", Department, report)
    employees = _records(raw, "employees", Employee, report)
    shifts = _records(raw, "shifts", Shift, report)
    schedule = _records(raw, "existing_schedule", Assignment, report, id_field=None)
    availability = _records(raw, "availability", Availability, report, id_field=None)
    disruptions = _records(raw, "disruptions", Disruption, report)
    try:
        constraints = OrgConstraints.model_validate(raw.get("constraints") or {})
    except ValidationError as exc:
        constraints = OrgConstraints()
        for loc, msg, _ in _friendly(exc):
            report.errors.append(Finding(severity="error", category="invalid_record", path=f"constraints.{loc}",
                                         message=f"constraints: {msg} (defaults used)"))
    try:
        optimization = OptimizationSettings.model_validate(raw.get("optimization") or {})
    except ValidationError:
        optimization = OptimizationSettings()
        report.warnings.append(Finding(severity="warning", category="invalid_record", path="optimization",
                                       message="optimization settings invalid; defaults used"))

    ref = raw.get("reference_date")
    if ref:
        try:
            Date.fromisoformat(ref)
        except ValueError:
            report.errors.append(Finding(severity="error", category="invalid_record", path="reference_date",
                                         message=f"reference_date '{ref}' is not YYYY-MM-DD (ignored)"))
            ref = None

    emp_ids = {e.id for e in employees}
    shift_ids = {s.id for s in shifts}
    dept_ids = {d.id for d in departments} | {d.name for d in departments}

    # duplicate names are allowed (two Rahuls) but worth flagging
    for name, n in Counter(e.name for e in employees).items():
        if n > 1:
            report.warnings.append(Finding(severity="warning", category="duplicate", path="employees",
                                           message=f"{n} employees are named '{name}'; disambiguate by ID in requests"))

    if departments:
        for e in employees:
            if e.department and e.department not in dept_ids:
                report.warnings.append(Finding(severity="warning", category="unknown_reference", record_id=e.id,
                                               path=f"employees.{e.id}.department",
                                               message=f"{e.name}: unknown department '{e.department}'"))
        for s in shifts:
            if s.department and s.department not in dept_ids:
                report.warnings.append(Finding(severity="warning", category="unknown_reference", record_id=s.id,
                                               path=f"shifts.{s.id}.department",
                                               message=f"shift {s.id}: unknown department '{s.department}'"))

    clean_schedule, assigned = [], {}
    for a in schedule:
        if a.shift_id not in shift_ids or a.employee_id not in emp_ids:
            missing = "shift" if a.shift_id not in shift_ids else "employee"
            report.errors.append(Finding(severity="error", category="unknown_reference",
                                         path=f"existing_schedule.{a.shift_id}",
                                         message=f"assignment {a.shift_id}→{a.employee_id}: unknown {missing} (ignored)"))
            continue
        if a.shift_id in assigned:
            report.errors.append(Finding(severity="error", category="duplicate", path=f"existing_schedule.{a.shift_id}",
                                         message=f"shift {a.shift_id} is assigned twice; kept {assigned[a.shift_id]}, "
                                                 f"ignored {a.employee_id}. Use one shift record per person needed."))
            continue
        assigned[a.shift_id] = a.employee_id
        clean_schedule.append(a)

    clean_avail = []
    for a in availability:
        if a.employee_id not in emp_ids:
            report.errors.append(Finding(severity="error", category="unknown_reference", path="availability",
                                         message=f"availability for unknown employee '{a.employee_id}' (ignored)"))
        else:
            clean_avail.append(a)
    clean_disr = []
    for d in disruptions:
        if d.employee_id not in emp_ids:
            report.errors.append(Finding(severity="error", category="unknown_reference", record_id=d.id,
                                         path=f"disruptions.{d.id}",
                                         message=f"disruption {d.id}: unknown employee '{d.employee_id}' (ignored)"))
        else:
            clean_disr.append(d)

    if not employees or not shifts:
        report.errors.append(Finding(severity="error", category="fatal", path="",
                                     message="At least one valid employee and one valid shift are required."))
        report.status = "invalid"
        report.stats = {"employees": len(employees), "shifts": len(shifts)}
        report.summary = _summary(report)
        return report

    ref_time = raw.get("reference_time")
    if ref_time:
        try:
            from .models import normalize_hhmm
            ref_time = normalize_hhmm(ref_time)
        except ValueError:
            report.errors.append(Finding(severity="error", category="invalid_record", path="reference_time",
                                         message=f"reference_time '{ref_time}' is not HH:MM (ignored)"))
            ref_time = None

    ds = Dataset(organization=org, reference_date=ref, reference_time=ref_time, departments=departments, skills=raw.get("skills") or [],
                 employees=employees, shifts=shifts, existing_schedule=clean_schedule, availability=clean_avail,
                 disruptions=clean_disr, constraints=constraints, optimization=optimization)

    # coverage + qualification checks against the existing schedule
    emps = {e.id: e for e in employees}
    for s in shifts:
        if s.id not in assigned:
            report.warnings.append(Finding(severity="warning", category="coverage", record_id=s.id,
                                           path=f"shifts.{s.id}", message=f"shift {s.id} ({s.assignment}, {s.date} "
                                                                          f"{s.start}–{s.end}) has no one assigned"))
        if s.requirements and not any(not missing_qualifications(e, s) for e in employees):
            report.warnings.append(Finding(severity="warning", category="skill_mismatch", record_id=s.id,
                                           path=f"shifts.{s.id}",
                                           message=f"nobody is qualified for {s.id} ({', '.join(s.required_skills + s.required_certifications)})"))
    for v in schedule_violations(ds, assigned):
        rule = v["rule"]
        who = emps.get(v.get("employee_id"))
        name = who.name if who else v.get("employee_id")
        if rule == "qualification":
            msg, cat = f"{name} is assigned to {v['shift_id']} without {', '.join(v['missing'])}", "skill_mismatch"
        elif rule in ("overlap", "rest"):
            what = "overlapping shifts" if rule == "overlap" else f"only {v['gap_hours']}h rest between shifts"
            msg, cat = f"{name} has {what} ({' & '.join(v['shift_ids'])})", "constraint_conflict"
        elif rule == "daily_hours":
            msg, cat = f"{name} is scheduled {v['hours']}h on {v['date']}, above the daily limit", "constraint_conflict"
        elif rule == "weekly_hours":
            msg, cat = f"{name} is scheduled {v['hours']}h in {v['week']}, above the weekly limit", "constraint_conflict"
        elif rule == "unavailable":
            msg, cat = f"{name} is assigned to {v['shift_id']} while marked unavailable", "constraint_conflict"
        else:
            continue
        report.warnings.append(Finding(severity="warning", category=cat, path="existing_schedule",
                                       message=msg + " in the existing schedule", record_id=v.get("employee_id")))

    report.dataset = ds
    report.stats = {"employees": len(employees), "shifts": len(shifts), "assignments": len(clean_schedule),
                    "open_shifts": len(shifts) - len(assigned), "departments": len(departments),
                    "disruption_presets": len(clean_disr), "records_rejected": len(report.errors)}
    report.status = "valid_with_warnings" if (report.errors or report.warnings) else "valid"
    report.summary = _summary(report)
    return report


def _summary(r: ValidationReport) -> str:
    if r.status == "invalid":
        return "Dataset can't be used: " + "; ".join(f.message for f in r.errors if f.category == "fatal")
    s = r.stats
    parts = [f"{s['employees']} employees, {s['shifts']} shifts, {s['assignments']} assignments loaded."]
    if r.errors:
        parts.append(f"{len(r.errors)} record{'s' if len(r.errors) != 1 else ''} rejected.")
    if r.warnings:
        parts.append(f"{len(r.warnings)} item{'s' if len(r.warnings) != 1 else ''} require attention.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

_SPLIT = ";"


def _split(v: Optional[str]) -> list[str]:
    return [p.strip() for p in (v or "").replace("|", _SPLIT).split(_SPLIT) if p.strip()]


def _num(v: Optional[str], default: float) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


def dataset_from_csv(schedule_csv: str, organization: dict, employees_csv: Optional[str] = None) -> dict:
    """Build a raw dataset dict from CSV text, then run it through ``validate_dataset``.

    schedule CSV (one row per shift; ``employee_id`` empty = open shift):
        shift_id,date,start,end,assignment,department,required_skills,required_certifications,priority,employee_id
    employees CSV (optional; otherwise employees are inferred from the schedule):
        id,name,role,department,skills,certifications,max_daily_hours,contracted_weekly_hours,max_weekly_hours
    Multi-value cells use ';'.
    """
    raw: dict[str, Any] = {"organization": organization, "employees": [], "shifts": [], "existing_schedule": []}
    rows = list(csv.DictReader(io.StringIO(schedule_csv.strip())))
    for i, r in enumerate(rows):
        r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
        sid = r.get("shift_id") or f"S{i + 1:03d}"
        raw["shifts"].append({
            "id": sid, "date": r.get("date", ""), "start": r.get("start", ""), "end": r.get("end", ""),
            "assignment": r.get("assignment") or r.get("department") or sid,
            "department": r.get("department") or None, "shift_type": r.get("shift_type") or None,
            "required_skills": _split(r.get("required_skills")),
            "required_certifications": _split(r.get("required_certifications")),
            "priority": r.get("priority") or "normal"})
        if r.get("employee_id"):
            raw["existing_schedule"].append({"shift_id": sid, "employee_id": r["employee_id"]})
            if not employees_csv and r.get("employee_name"):
                if not any(e["id"] == r["employee_id"] for e in raw["employees"]):
                    raw["employees"].append({"id": r["employee_id"], "name": r["employee_name"],
                                             "role": r.get("role") or "Staff", "department": r.get("department") or None,
                                             "skills": _split(r.get("employee_skills"))})
    if employees_csv:
        for r in csv.DictReader(io.StringIO(employees_csv.strip())):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            raw["employees"].append({
                "id": r.get("id", ""), "name": r.get("name", ""), "role": r.get("role", ""),
                "department": r.get("department") or None, "skills": _split(r.get("skills")),
                "certifications": _split(r.get("certifications")),
                "max_daily_hours": _num(r.get("max_daily_hours"), 12),
                "contracted_weekly_hours": _num(r.get("contracted_weekly_hours"), 40),
                "max_weekly_hours": _num(r.get("max_weekly_hours"), 48)})
    return raw
