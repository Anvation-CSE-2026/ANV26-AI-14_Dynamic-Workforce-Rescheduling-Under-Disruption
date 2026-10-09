"""Bulk employee and schedule import (CSV or XLSX): upload → validate → preview → admin confirms.

Rules:
* every row is reported back, with its row number and status
  (valid · invalid · duplicate · existing) and its errors and warnings, so nothing is silently dropped;
* existing employees are never replaced or deleted: a row for someone who already exists is reported
  as ``existing`` and skipped;
* times must be 24-hour HH:MM (``9 AM`` is rejected with a hint) and dates YYYY-MM-DD (or real Excel dates).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date as Date
from typing import Any, Optional

from core import xlsx
from core.models import Assignment, Availability, Dataset, Employee, Shift, normalize_hhmm
from core.rules import schedule_violations

EMPLOYEE_REQUIRED = ("employee_id", "name", "email", "phone", "department", "role", "skills")
EMPLOYEE_OPTIONAL = ("availability_start", "availability_end", "max_hours", "certifications", "status")
SCHEDULE_REQUIRED = ("schedule_id", "employee_id", "date", "shift_start", "shift_end", "location", "task",
                     "required_skill")

_EMAIL = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_PHONE = re.compile(r"^\+?[0-9 ()-]{7,20}$")
_AMPM = re.compile(r"\b(am|pm|a\.m\.|p\.m\.)\b", re.I)
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")


class ImportError_(ValueError):
    pass


def read_table(filename: str, data: bytes) -> list[dict[str, Any]]:
    name = (filename or "").lower()
    if name.endswith(".xlsx") or data[:2] == b"PK":
        try:
            return xlsx.records(data)
        except xlsx.XlsxError as exc:
            raise ImportError_(str(exc)) from exc
    if name.endswith(".xls"):
        raise ImportError_("Old .xls files aren't supported. Save as .xlsx or .csv.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportError_("The file isn't UTF-8 text. Save it as CSV (UTF-8) or .xlsx.") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ImportError_("The file is empty.")
    return [{(k or "").strip().lower(): (v or "").strip() if isinstance(v, str) else v for k, v in r.items()}
            for r in reader]


def _s(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _split(v: Any) -> list[str]:
    return [x.strip() for x in re.split(r"[;|,]", _s(v)) if x.strip()]


def _time(v: Any, field: str, errors: list[str]) -> Optional[str]:
    v = xlsx.excel_time(v)
    raw = _s(v)
    if not raw:
        return None
    if _AMPM.search(raw):
        errors.append(f"{field} '{raw}' uses AM/PM. Use 24-hour time, e.g. 07:00 or 17:30")
        return None
    try:
        return normalize_hhmm(raw[:5] if re.match(r"^\d{1,2}:\d{2}:\d{2}$", raw) else raw)
    except ValueError:
        errors.append(f"{field} '{raw}' is not a valid time (24-hour HH:MM)")
        return None


def _date(v: Any, errors: list[str]) -> Optional[str]:
    raw = _s(xlsx.excel_date(v))[:10]
    try:
        return Date.fromisoformat(raw).isoformat()
    except ValueError:
        errors.append(f"date '{_s(v)}' must be YYYY-MM-DD")
        return None


def _missing(row: dict, required: tuple[str, ...]) -> list[str]:
    return [f"{f} is required" for f in required if not _s(row.get(f))]


# ---------------------------------------------------------------- employees

def validate_employees(ds: Dataset, rows: list[dict], existing_emails: set[str]) -> dict:
    known_ids = {e.id.lower() for e in ds.employees}
    known_emails = {(e.email or "").lower() for e in ds.employees if e.email} | {x.lower() for x in existing_emails}
    departments = {d.id.lower() for d in ds.departments} | {d.name.lower() for d in ds.departments}
    seen_ids: dict[str, int] = {}
    seen_emails: dict[str, int] = {}
    out = []
    for i, row in enumerate(rows):
        n = i + 2                                      # spreadsheet row number (header is row 1)
        errors, warnings = [], []
        if not any(_s(v) for v in row.values()):
            out.append({"row": n, "status": "invalid", "errors": ["empty row"], "warnings": [], "data": {}})
            continue
        errors += _missing(row, EMPLOYEE_REQUIRED)
        eid, email = _s(row.get("employee_id")), _s(row.get("email")).lower()
        if eid and not _ID.match(eid):
            errors.append("employee_id may only use letters, digits, '-', '_' and '.' (max 40)")
        if email and not _EMAIL.match(email):
            errors.append(f"email '{email}' is not valid")
        phone = _s(row.get("phone"))
        if phone and not _PHONE.match(phone):
            errors.append(f"phone '{phone}' is not valid")
        skills = _split(row.get("skills"))
        if _s(row.get("skills")) and not skills:
            errors.append("skills is required")
        start = _time(row.get("availability_start"), "availability_start", errors)
        end = _time(row.get("availability_end"), "availability_end", errors)
        if bool(start) != bool(end) and not errors:
            errors.append("give both availability_start and availability_end, or neither")
        max_hours = None
        if _s(row.get("max_hours")):
            try:
                max_hours = float(_s(row.get("max_hours")))
                if not 1 <= max_hours <= 168:
                    errors.append("max_hours must be between 1 and 168")
            except ValueError:
                errors.append(f"max_hours '{_s(row.get('max_hours'))}' is not a number")
        status = (_s(row.get("status")) or "active").lower()
        if status not in ("active", "inactive"):
            errors.append("status must be active or inactive")
        dept = _s(row.get("department"))
        if dept and dept.lower() not in departments:
            warnings.append(f"department '{dept}' is new and will be created")
        data = {"employee_id": eid, "name": _s(row.get("name")), "email": email, "phone": phone,
                "department": dept, "role": _s(row.get("role")), "skills": skills,
                "certifications": _split(row.get("certifications")), "availability_start": start,
                "availability_end": end, "max_hours": max_hours, "status": status}
        if errors:
            st = "invalid"
        elif eid.lower() in known_ids or email in known_emails:
            st = "existing"
            warnings.append("already exists: kept as is (imports never replace existing employees)")
        elif eid.lower() in seen_ids or email in seen_emails:
            st = "duplicate"
            first = seen_ids.get(eid.lower()) or seen_emails.get(email)
            errors.append(f"duplicate of row {first} in this file")
        else:
            st = "valid"
            seen_ids[eid.lower()] = n
            seen_emails[email] = n
        out.append({"row": n, "status": st, "errors": errors, "warnings": warnings, "data": data})
    return _summary(out)


def _summary(rows: list[dict]) -> dict:
    count = lambda s: sum(1 for r in rows if r["status"] == s)  # noqa: E731
    return {"rows": rows, "total": len(rows), "valid": count("valid"), "invalid": count("invalid"),
            "duplicates": count("duplicate"), "existing": count("existing"),
            "warnings": sum(len(r["warnings"]) for r in rows)}


def horizon_dates(ds: Dataset) -> list[str]:
    return sorted({s.date for s in ds.shifts})


def availability_window(employee_id: str, start: str, end: str, dates: list[str]) -> list[Availability]:
    """A daily availability window (e.g. 07:00–19:00) as unavailability records outside it, per date."""
    out = []
    for d in dates:
        if start < end:
            if start != "00:00":
                out.append(Availability(employee_id=employee_id, date=d, start="00:00", end=start,
                                        kind="unavailable", reason="outside availability window"))
            if end != "24:00" and end != "23:59":
                out.append(Availability(employee_id=employee_id, date=d, start=end, end="00:00",
                                        kind="unavailable", reason="outside availability window"))
        elif start > end:                     # overnight window, e.g. 19:00–07:00
            out.append(Availability(employee_id=employee_id, date=d, start=end, end=start, kind="unavailable",
                                    reason="outside availability window"))
    return out


def build_employee(d: dict) -> Employee:
    cap = d.get("max_hours")
    return Employee(id=d["employee_id"], name=d["name"], role=d["role"], department=d["department"] or None,
                    email=d["email"] or None, phone=d["phone"] or None, status=d.get("status", "active"),
                    skills=d["skills"], certifications=d.get("certifications", []),
                    contracted_weekly_hours=min(40.0, cap) if cap else 40.0,
                    max_weekly_hours=max(cap, min(40.0, cap)) if cap else 48.0,
                    attributes={k: v for k, v in (("availability", f"{d['availability_start']}–{d['availability_end']}"
                                                   if d.get("availability_start") else None),) if v})


# ---------------------------------------------------------------- schedule

def validate_schedule(ds: Dataset, rows: list[dict]) -> dict:
    emps = {e.id: e for e in ds.employees}
    shift_ids = {s.id for s in ds.shifts}
    seen: dict[str, int] = {}
    out = []
    new_shifts: dict[int, Shift] = {}
    for i, row in enumerate(rows):
        n = i + 2
        errors, warnings = [], []
        if not any(_s(v) for v in row.values()):
            out.append({"row": n, "status": "invalid", "errors": ["empty row"], "warnings": [], "data": {}})
            continue
        errors += _missing(row, SCHEDULE_REQUIRED)
        sid, eid = _s(row.get("schedule_id")), _s(row.get("employee_id"))
        day = _date(row.get("date"), errors) if _s(row.get("date")) else None
        start = _time(row.get("shift_start"), "shift_start", errors)
        end = _time(row.get("shift_end"), "shift_end", errors)
        if start and end and start == end:
            errors.append("shift_start and shift_end are equal")
        emp = emps.get(eid)
        if eid and emp is None:
            errors.append(f"employee '{eid}' doesn't exist (import employees first)")
        elif emp is not None and emp.status == "inactive":
            errors.append(f"employee '{eid}' is deactivated")
        skill = _s(row.get("required_skill"))
        data = {"schedule_id": sid, "employee_id": eid, "employee_name": emp.name if emp else None, "date": day,
                "shift_start": start, "shift_end": end, "location": _s(row.get("location")),
                "task": _s(row.get("task")), "required_skill": skill}
        if emp is not None and skill and skill.lower() not in emp.qualifications:
            warnings.append(f"skill mismatch: {emp.name} doesn't have '{skill}'")
        if not errors and sid in shift_ids:
            st = "duplicate"
            errors.append(f"schedule_id '{sid}' already exists in the schedule")
        elif not errors and sid in seen:
            st = "duplicate"
            errors.append(f"duplicate of row {seen[sid]} in this file")
        else:
            st = "invalid" if errors else "valid"
        if st == "valid":
            seen[sid] = n
            new_shifts[n] = Shift(id=sid, date=day, start=start, end=end, assignment=data["task"],
                                  department=emp.department if emp else None, location=data["location"] or None,
                                  required_skills=[skill] if skill else [])
        out.append({"row": n, "status": st, "errors": errors, "warnings": warnings, "data": data})

    # hard-constraint warnings against the schedule as it would be after the import
    if new_shifts:
        trial = ds.model_copy(update={"shifts": ds.shifts + list(new_shifts.values()),
                                      "existing_schedule": ds.existing_schedule + [
                                          Assignment(shift_id=s.id, employee_id=r["data"]["employee_id"])
                                          for r in out for s in [new_shifts.get(r["row"])] if s]})
        by_shift = {s.id: n for n, s in new_shifts.items()}
        for v in schedule_violations(trial, trial.assignment_map()):
            touched = [by_shift[x] for x in ([v["shift_id"]] if v.get("shift_id") else v.get("shift_ids", []))
                       if x in by_shift]
            if not touched and v["rule"] in ("daily_hours", "weekly_hours"):
                touched = [n for n, s in new_shifts.items()
                           if trial.assignment_map().get(s.id) == v["employee_id"]][:1]
            for n in touched:
                row = next(r for r in out if r["row"] == n)
                msg = _violation_text(v)
                if v["rule"] != "qualification" and msg not in row["warnings"]:
                    row["warnings"].append(msg)
                    row["hard_warning"] = True
    return _summary(out)


def _violation_text(v: dict) -> str:
    return {"overlap": "hard constraint: overlaps another shift for the same person (double booking)",
            "rest": f"hard constraint: only {v.get('gap_hours')}h rest between shifts",
            "daily_hours": f"hard constraint: {v.get('hours')}h on {v.get('date')} exceeds the daily maximum",
            "weekly_hours": f"hard constraint: {v.get('hours')}h in {v.get('week')} exceeds the weekly maximum",
            "unavailable": "hard constraint: the employee is unavailable then"}.get(v["rule"], f"hard constraint: {v['rule']}")


def schedule_rows_to_dataset(ds: Dataset, rows: list[dict]) -> tuple[list[Shift], list[Assignment]]:
    emps = {e.id: e for e in ds.employees}
    shifts, assigns = [], []
    for r in rows:
        d = r["data"]
        e = emps[d["employee_id"]]
        shifts.append(Shift(id=d["schedule_id"], date=d["date"], start=d["shift_start"], end=d["shift_end"],
                            assignment=d["task"], department=e.department, location=d["location"] or None,
                            required_skills=[d["required_skill"]] if d["required_skill"] else []))
        assigns.append(Assignment(shift_id=d["schedule_id"], employee_id=d["employee_id"]))
    return shifts, assigns


# ---------------------------------------------------------------- templates

EMPLOYEE_TEMPLATE = [list(EMPLOYEE_REQUIRED + EMPLOYEE_OPTIONAL),
                     ["EMP101", "Asha Menon", "asha.menon@example.com", "+91 98450 11223", "ICU", "Staff Nurse",
                      "ICU;BLS", "07:00", "19:00", "40", "ACLS", "active"],
                     ["EMP102", "Rohan Das", "rohan.das@example.com", "+91 98450 44556", "Emergency", "Staff Nurse",
                      "ER;BLS", "", "", "36", "", "active"]]
SCHEDULE_TEMPLATE = [list(SCHEDULE_REQUIRED),
                     ["SCH-1001", "EMP101", "2026-10-12", "07:00", "15:00", "Ward A", "ICU Day", "ICU"],
                     ["SCH-1002", "EMP102", "2026-10-12", "15:00", "23:00", "Emergency", "ER Evening", "ER"]]


def template(kind: str, fmt: str) -> tuple[bytes, str, str]:
    rows = EMPLOYEE_TEMPLATE if kind == "employees" else SCHEDULE_TEMPLATE
    name = f"resqwork-{kind}-template"
    if fmt == "xlsx":
        return xlsx.write(rows, kind.title()), f"{name}.xlsx", \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue().encode(), f"{name}.csv", "text/csv"
