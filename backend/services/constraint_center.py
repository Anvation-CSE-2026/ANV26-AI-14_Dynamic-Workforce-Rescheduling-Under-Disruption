"""Constraint Center: a data-driven view and editor of every rule the repair engine applies.

Single source of truth stays the dataset (``constraints`` = hard limits, ``optimization.weights`` = soft
weights) plus one per-organization document for things the dataset doesn't hold (enabled flags, scoped
skill rules, informational rules). Every edit is written back into the dataset, so CP-SAT, the exact
search and the post-solve validator keep reading the same numbers.

File formats (import and template download):

CSV   constraint_id,type,category,rule,priority,weight,enabled[,value][,scope]
      C001,HARD,availability,employee must be available,HIGH,100,true
      C003,SOFT,fairness,minimize recent additional workload,MEDIUM,30,true
JSON  [{"constraint_id": "C020", "type": "HARD", "category": "required_skill",
        "rule": "ICU shifts need BLS", "scope": {"department": "ICU"}, "value": ["BLS"]}]

Categories the engine can enforce are listed in ``HARD_CATEGORIES`` / ``SOFT_CATEGORIES``. A rule in any
other category is stored, shown and flagged ``enforced: false``: ResQWork never pretends to enforce a
rule it has no model for.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Optional

from core.models import Dataset, OrgConstraints, Weights
from core.rules import schedule_violations

PRIORITIES = ("HIGH", "MEDIUM", "LOW")

# category → (default id, rule text, dataset field it controls or None, locked)
HARD_CATEGORIES: dict[str, tuple[str, str, Optional[str], bool]] = {
    "availability": ("C001", "Employee must be available (approved leave, unavailability)", None, True),
    "double_booking": ("C002", "No overlapping shifts for the same person", None, True),
    "skill": ("C003", "Employee must have every required skill", None, True),
    "certification": ("C004", "Employee must hold every required certification", None, True),
    "active_status": ("C005", "Deactivated employees are never assigned", None, True),
    "minimum_rest": ("C006", "Minimum rest between two shifts", "min_rest_hours", False),
    "max_daily_hours": ("C007", "Maximum working hours per day", "max_daily_hours", False),
    "max_weekly_hours": ("C008", "Maximum working hours per week", "max_weekly_hours", False),
    "overtime_limit": ("C009", "Maximum overtime per week", "max_overtime_hours_per_week", False),
    "minimum_staffing": ("C010", "Covered shifts stay covered; a partial repair needs an explicit admin override",
                         None, False),
    "required_skill": ("C011", "Extra skill required for a department or assignment", None, False),
}
UNITS = {"minimum_rest": "h", "max_daily_hours": "h", "max_weekly_hours": "h", "overtime_limit": "h/week"}

# category → (default id, rule text, weight field, default importance shown in the UI)
SOFT_CATEGORIES: dict[str, tuple[str, str, str, int]] = {
    "minimize_changes": ("S001", "Minimize schedule changes / preserve existing assignments", "assignment_change", 100),
    "minimize_affected": ("S002", "Touch as few employees as possible", "employee_affected", 80),
    "minimize_overtime": ("S003", "Minimize overtime", "overtime_hour", 60),
    "fairness": ("S004", "Minimize recent additional workload (fairness, rolling window)", "fairness", 50),
    "preference": ("S005", "Respect employee shift preferences", "preference", 40),
    "location": ("S006", "Prefer people who already work at that location", "location", 30),
    "continuity": ("S007", "Prefer people who already work that assignment (continuity)", "continuity", 20),
}
_BASE_WEIGHTS = Weights().model_dump()
# what a disabled numeric hard rule falls back to (the employee's own contract limits still apply)
NEUTRAL = {"minimum_rest": 0, "max_daily_hours": None, "max_weekly_hours": None, "overtime_limit": 80}


class ConstraintError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _state(store, org: str) -> dict:
    st = store.get("constraint_config", "current", org) or {"disabled": [], "rules": [], "updated_at": None}
    st.setdefault("saved", {})
    return st


def catalog(store, org: str, ds: Dataset) -> list[dict]:
    """The full rule list, built from the dataset (values) and the org document (flags, extra rules)."""
    st = _state(store, org)
    disabled = set(st["disabled"])
    c, w = ds.constraints, ds.optimization.weights.model_dump()
    out = []
    for cat, (cid, text, field, locked) in HARD_CATEGORIES.items():
        if cat == "required_skill":
            continue
        value: Any = (st["saved"].get(cid, getattr(c, field)) if cid in disabled else getattr(c, field)) if field else None
        if cat == "overtime_limit" and not c.allow_overtime and cid not in disabled:
            value = 0
        out.append({"constraint_id": cid, "type": "HARD", "category": cat, "rule": text, "priority": "HIGH",
                    "weight": 100, "enabled": cid not in disabled, "locked": locked, "value": value,
                    "unit": UNITS.get(cat), "scope": None, "enforced": True, "source": "built-in"})
    for cat, (cid, text, field, default_ui) in SOFT_CATEGORIES.items():
        ui = round(default_ui * w.get(field, 0) / _BASE_WEIGHTS[field]) if _BASE_WEIGHTS[field] else 0
        extra = {"value": c.fairness_window_days, "unit": "days window"} if cat == "fairness" else {"value": None, "unit": None}
        out.append({"constraint_id": cid, "type": "SOFT", "category": cat, "rule": text,
                    "priority": "HIGH" if ui >= 80 else "MEDIUM" if ui >= 30 else "LOW", "weight": ui,
                    "enabled": ui > 0, "locked": False, **extra, "scope": None, "enforced": True, "source": "built-in"})
    for r in st["rules"]:
        out.append({**r, "enabled": r["constraint_id"] not in disabled})
    return out


def _engine_weight(category: str, ui_weight: float) -> int:
    _, _, field, default_ui = SOFT_CATEGORIES[category]
    return max(0, int(round(_BASE_WEIGHTS[field] * float(ui_weight) / default_ui)))


def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "on", "y")


def normalize(row: dict, index: int = 0) -> tuple[Optional[dict], list[str]]:
    """Validate one imported rule. Returns (rule, errors)."""
    errs = []
    cid = str(row.get("constraint_id") or "").strip()
    typ = str(row.get("type") or "").strip().upper()
    cat = str(row.get("category") or "").strip().lower().replace(" ", "_")
    rule = str(row.get("rule") or "").strip()
    prio = str(row.get("priority") or "MEDIUM").strip().upper()
    if not cid:
        errs.append("constraint_id is required")
    if typ not in ("HARD", "SOFT"):
        errs.append("type must be HARD or SOFT")
    if not rule:
        errs.append("rule text is required")
    if prio not in PRIORITIES:
        errs.append("priority must be HIGH, MEDIUM or LOW")
    try:
        weight = float(row.get("weight") if row.get("weight") not in (None, "") else 100)
        if not 0 <= weight <= 1000:
            errs.append("weight must be between 0 and 1000")
    except (TypeError, ValueError):
        errs.append("weight must be a number")
        weight = 0
    value = row.get("value")
    if isinstance(value, str) and value.strip():
        v = value.strip()
        try:
            value = json.loads(v) if v[0] in "[{" else float(v)
        except (ValueError, json.JSONDecodeError):
            value = [x.strip() for x in v.split("|")] if cat == "required_skill" else v
    elif value == "":
        value = None
    scope = row.get("scope")
    if isinstance(scope, str):
        scope = json.loads(scope) if scope.strip().startswith("{") else ({"department": scope.strip()} if scope.strip() else None)
    if typ == "HARD" and cat in HARD_CATEGORIES and HARD_CATEGORIES[cat][2] and value is not None \
            and not isinstance(value, (int, float)):
        errs.append(f"{cat} needs a numeric value")
    if cat == "required_skill" and not (isinstance(value, list) and value):
        errs.append("required_skill needs value: a list of skills, e.g. [\"BLS\"] or BLS|ACLS")
    if errs:
        return None, [f"row {index}: {e}" for e in errs]
    enforced = (typ == "HARD" and cat in HARD_CATEGORIES) or (typ == "SOFT" and cat in SOFT_CATEGORIES)
    return {"constraint_id": cid, "type": typ, "category": cat, "rule": rule, "priority": prio, "weight": weight,
            "enabled": _coerce_bool(row.get("enabled", True)), "locked": False, "value": value,
            "unit": UNITS.get(cat), "scope": scope, "enforced": enforced,
            "source": "imported"}, []


def parse_file(filename: str, data: bytes) -> list[dict]:
    text = data.decode("utf-8-sig")
    if filename.lower().endswith(".json") or text.lstrip().startswith(("[", "{")):
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConstraintError(f"Invalid JSON: {exc.msg} (line {exc.lineno})") from exc
        raw = raw.get("constraints", raw) if isinstance(raw, dict) else raw
        if not isinstance(raw, list):
            raise ConstraintError("JSON must be a list of constraints or {\"constraints\": [...]}")
        return [r for r in raw if isinstance(r, dict)]
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "constraint_id" not in [f.strip() for f in reader.fieldnames]:
        raise ConstraintError("CSV header must start with constraint_id,type,category,rule,priority,weight,enabled")
    return [{(k or "").strip(): v for k, v in row.items()} for row in reader]


def apply(store, org: str, ds: Dataset, rules: list[dict]) -> tuple[Dataset, dict]:
    """Apply validated rules: built-in categories update the dataset, others are stored."""
    st = _state(store, org)
    disabled = set(st["disabled"])
    extra = {r["constraint_id"]: r for r in st["rules"]}
    c = ds.constraints.model_dump()
    w = ds.optimization.weights.model_dump()
    changes = []
    for r in rules:
        cat, cid = r["category"], r["constraint_id"]
        if r["type"] == "HARD" and cat in HARD_CATEGORIES and cat != "required_skill":
            builtin_id, _, field, locked = HARD_CATEGORIES[cat]
            if locked and not r.get("enabled", True):
                raise ConstraintError(f"{builtin_id} ({cat}) is a core safety rule and can't be disabled.")
            enabled = r.get("enabled", True)
            if field:
                before = c[field]
                if not enabled and builtin_id not in disabled:
                    st["saved"][builtin_id] = c[field]
                    c[field] = NEUTRAL[cat]
                elif enabled and builtin_id in disabled:
                    c[field] = st["saved"].pop(builtin_id, c[field])
                if enabled and r.get("value") is not None:
                    c[field] = float(r["value"])
                elif not enabled and r.get("value") is not None:
                    st["saved"][builtin_id] = float(r["value"])
                if cat == "overtime_limit":
                    c["allow_overtime"] = (c[field] or 0) > 0
                if before != c[field]:
                    changes.append({"constraint_id": builtin_id, "field": field, "previous": before, "new": c[field]})
            if enabled != (builtin_id not in disabled):
                changes.append({"constraint_id": builtin_id, "field": "enabled", "previous": builtin_id not in disabled,
                                "new": enabled})
            (disabled.discard if enabled else disabled.add)(builtin_id)
        elif r["type"] == "SOFT" and cat in SOFT_CATEGORIES:
            builtin_id, _, field, _ = SOFT_CATEGORIES[cat]
            before = w[field]
            w[field] = _engine_weight(cat, r["weight"]) if r.get("enabled", True) else 0
            if cat == "fairness" and isinstance(r.get("value"), (int, float)):
                c["fairness_window_days"] = int(r["value"])
            changes.append({"constraint_id": builtin_id, "field": field, "previous": before, "new": w[field]})
        else:
            extra[cid] = {k: v for k, v in r.items() if k != "enabled"}
            (disabled.discard if r.get("enabled", True) else disabled.add)(cid)
            changes.append({"constraint_id": cid, "field": "rule", "previous": None, "new": r["rule"]})
    try:
        new_c = OrgConstraints.model_validate({**c, "max_daily_hours": c["max_daily_hours"] or None,
                                               "max_weekly_hours": c["max_weekly_hours"] or None})
        new_w = Weights.model_validate(w)
    except Exception as exc:  # noqa: BLE001 - pydantic message is user-facing here
        raise ConstraintError(f"Invalid value: {exc}") from exc
    new_ds = ds.model_copy(update={"constraints": new_c,
                                   "optimization": ds.optimization.model_copy(update={"weights": new_w})})
    store.put("constraint_config", "current", org,
              {"disabled": sorted(disabled), "rules": list(extra.values()), "saved": st["saved"], "updated_at": _now()})
    return new_ds, {"changes": changes}


def set_enabled(store, org: str, ds: Dataset, constraint_id: str, enabled: bool) -> tuple[Dataset, dict]:
    row = next((r for r in catalog(store, org, ds) if r["constraint_id"] == constraint_id), None)
    if row is None:
        raise ConstraintError(f"Unknown constraint {constraint_id}")
    if row["locked"] and not enabled:
        raise ConstraintError(f"{constraint_id} is a core safety rule and can't be disabled.")
    if row["type"] == "SOFT":
        weight = row["weight"] or SOFT_CATEGORIES[row["category"]][3]
        return apply(store, org, ds, [{**row, "weight": weight, "enabled": enabled}])
    return apply(store, org, ds, [{**row, "enabled": enabled}])


def remove(store, org: str, constraint_id: str) -> None:
    st = _state(store, org)
    if not any(r["constraint_id"] == constraint_id for r in st["rules"]):
        raise ConstraintError("Only imported rules can be removed; built-in rules can be disabled or re-weighted.")
    st["rules"] = [r for r in st["rules"] if r["constraint_id"] != constraint_id]
    st["disabled"] = [d for d in st["disabled"] if d != constraint_id]
    store.put("constraint_config", "current", org, st)


def is_enabled(store, org: str, constraint_id: str) -> bool:
    return constraint_id not in set(_state(store, org)["disabled"])


def run_overrides(store, org: str) -> dict:
    """What the next repair run must add to RunSettings: scoped skill rules."""
    st = _state(store, org)
    disabled = set(st["disabled"])
    skills: dict[str, list[str]] = {}
    for r in st["rules"]:
        if r["category"] == "required_skill" and r["type"] == "HARD" and r["constraint_id"] not in disabled:
            scope = r.get("scope") or {}
            key = scope.get("assignment") or scope.get("department") or "*"
            skills.setdefault(key, []).extend(str(v) for v in r["value"])
    return {"extra_required_skills": skills}


def test(store, org: str, ds: Dataset) -> dict:
    """Run every enforced hard rule against the current schedule and report per-constraint results."""
    violations = schedule_violations(ds, ds.assignment_map())
    rule_map = {"unavailable": "C001", "overlap": "C002", "qualification": "C003", "rest": "C006",
                "daily_hours": "C007", "weekly_hours": "C008"}
    counts: dict[str, int] = {}
    for v in violations:
        cid = rule_map.get(v["rule"], "C002")
        if v["rule"] == "qualification":
            certs = {c.lower() for s in ds.shifts if s.id == v["shift_id"] for c in s.required_certifications}
            cid = "C004" if all(m.lower() in certs for m in v.get("missing", [])) else "C003"
        counts[cid] = counts.get(cid, 0) + 1
    amap = ds.assignment_map()
    inactive = {e.id for e in ds.employees if e.status == "inactive"}
    counts["C005"] = sum(1 for eid in amap.values() if eid in inactive)
    open_shifts = sum(1 for s in ds.shifts if s.id not in amap)
    counts["C010"] = open_shifts
    extra = run_overrides(store, org)["extra_required_skills"]
    scoped = 0
    for s in ds.shifts:
        eid = amap.get(s.id)
        need = extra.get("*", []) + extra.get(s.department or "", []) + extra.get(s.assignment, [])
        e = ds.employee(eid) if eid else None
        if e and any(q.lower() not in e.qualifications for q in need):
            scoped += 1
    results = []
    for r in catalog(store, org, ds):
        n = counts.get(r["constraint_id"], scoped if r["category"] == "required_skill" else 0)
        results.append({"constraint_id": r["constraint_id"], "category": r["category"], "type": r["type"],
                        "enabled": r["enabled"], "enforced": r["enforced"],
                        "status": "info" if not r["enforced"] else ("skipped" if not r["enabled"] else
                                                                     ("pass" if n == 0 or r["type"] == "SOFT" else "fail")),
                        "violations": n if r["type"] == "HARD" else 0,
                        "message": ("No engine model for this category: stored for reference, not enforced."
                                    if not r["enforced"] else
                                    f"{n} open shift(s) in the current schedule" if r["constraint_id"] == "C010" and n else
                                    f"{n} violation(s) in the current schedule" if n and r["type"] == "HARD" else "OK")})
    return {"checked_at": _now(), "assignments": len(amap), "results": results,
            "summary": {"fail": sum(1 for x in results if x["status"] == "fail"),
                        "pass": sum(1 for x in results if x["status"] == "pass")}}


def template_csv() -> str:
    rows = [["constraint_id", "type", "category", "rule", "priority", "weight", "enabled", "value", "scope"],
            ["C001", "HARD", "availability", "employee must be available", "HIGH", "100", "true", "", ""],
            ["C003", "HARD", "skill", "employee must have required skill", "HIGH", "100", "true", "", ""],
            ["C006", "HARD", "minimum_rest", "minimum rest between shifts", "HIGH", "100", "true", "11", ""],
            ["C008", "HARD", "max_weekly_hours", "maximum weekly hours", "HIGH", "100", "true", "48", ""],
            ["C020", "HARD", "required_skill", "ICU shifts need BLS", "HIGH", "100", "true", "BLS", "ICU"],
            ["S004", "SOFT", "fairness", "minimize recent additional workload", "MEDIUM", "30", "true", "30", ""],
            ["S003", "SOFT", "minimize_overtime", "minimize overtime", "MEDIUM", "60", "true", "", ""]]
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def template_json() -> str:
    return json.dumps({"constraints": [
        {"constraint_id": "C020", "type": "HARD", "category": "required_skill", "rule": "ICU shifts need BLS",
         "priority": "HIGH", "weight": 100, "enabled": True, "scope": {"department": "ICU"}, "value": ["BLS"]},
        {"constraint_id": "C006", "type": "HARD", "category": "minimum_rest", "rule": "minimum rest between shifts",
         "priority": "HIGH", "weight": 100, "enabled": True, "value": 11},
        {"constraint_id": "S004", "type": "SOFT", "category": "fairness",
         "rule": "minimize recent additional workload", "priority": "MEDIUM", "weight": 30, "enabled": True,
         "value": 30}]}, indent=2)
