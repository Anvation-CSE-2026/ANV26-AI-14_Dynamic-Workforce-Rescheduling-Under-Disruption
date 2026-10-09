"""Detect hard-rule conflicts already present in the current schedule and say how to repair each one.

A conflict is turned into repair input, never fixed silently:

* ``release``: shifts whose current assignee must come off them (double-booked, rest, unqualified,
  unavailable, over the daily/weekly limit). The repair engine then looks for valid cover.
* ``cover``: open shifts that must be covered (mandatory coverage).

Which shift to release is deterministic: the lower-priority one, then the later one, so the shift the
person has "always had" stays with them. Shifts that have already started can't be changed; those
conflicts are reported with ``repairable = False``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.models import Dataset, Shift, interval
from core.rules import schedule_violations

ConflictType = Literal["double_booking", "rest_violation", "missing_skill", "missing_certification",
                       "unavailable_assignee", "daily_hours", "weekly_hours", "open_shift"]

LABELS: dict[str, str] = {
    "double_booking": "Double-booked",
    "rest_violation": "Rest period violated",
    "missing_skill": "Missing required skill",
    "missing_certification": "Missing required certification",
    "unavailable_assignee": "Assigned while unavailable",
    "daily_hours": "Over the daily hours limit",
    "weekly_hours": "Over the weekly hours limit",
    "open_shift": "Shift not covered",
}

_PRIORITY = {"critical": 0, "high": 1, "normal": 2}


class ScheduleConflict(BaseModel):
    id: str
    type: ConflictType
    label: str
    hard_constraint: str
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    shift_ids: list[str]
    release: dict[str, str] = Field(default_factory=dict, description="shift id → reason the assignee comes off it")
    cover: list[str] = Field(default_factory=list)
    message: str
    repairable: bool = True


def freeze_point(ds: Dataset) -> datetime:
    if ds.reference_date:
        return interval(ds.reference_date, ds.reference_time or "00:00", "23:59")[0]
    return datetime.min


def _describe(s: Shift) -> str:
    return f"{s.assignment} ({s.date} {s.start}–{s.end})"


def _release_of(v: dict, shifts: dict, future) -> list[str]:
    if v["rule"] in ("overlap", "rest"):
        a, b = (shifts[x] for x in v["shift_ids"])
        keep, drop = sorted((a, b), key=lambda s: (_PRIORITY.get(s.priority, 2), s.window[0], s.id))
        if not future(drop.id) and future(keep.id):
            drop = keep
        return [drop.id] if future(drop.id) else []
    if v["rule"] in ("qualification", "unavailable"):
        return [v["shift_id"]] if future(v["shift_id"]) else []
    return []


def _remaining_hours(ds: Dataset, amap: dict, first: list[dict], shifts: dict, future) -> list[dict]:
    released = {sid for v in first for sid in _release_of(v, shifts, future)}
    rest = {sid: e for sid, e in amap.items() if sid not in released}
    return [v for v in schedule_violations(ds, rest) if v["rule"] in ("daily_hours", "weekly_hours")]


def detect_conflicts(ds: Dataset) -> list[ScheduleConflict]:
    shifts = {s.id: s for s in ds.shifts}
    emps = {e.id: e for e in ds.employees}
    amap = ds.assignment_map()
    freeze = freeze_point(ds)
    future = lambda sid: shifts[sid].window[0] >= freeze  # noqa: E731
    out: list[ScheduleConflict] = []
    seen: set[str] = set()

    def add(c: ScheduleConflict) -> None:
        if c.id not in seen:
            seen.add(c.id)
            out.append(c)

    violations = schedule_violations(ds, amap)
    # Root causes first; hours limits are re-checked after those releases so one double-booking isn't
    # reported twice (as an overlap *and* as too many hours that day).
    first = [v for v in violations if v["rule"] not in ("daily_hours", "weekly_hours")]
    for v in first + _remaining_hours(ds, amap, first, shifts, future):
        rule, eid = v["rule"], v.get("employee_id")
        e = emps.get(eid)
        name = e.name if e else eid
        if rule in ("overlap", "rest"):
            a, b = (shifts[x] for x in v["shift_ids"])
            # keep the more important / earlier shift; release the other (if it hasn't started)
            keep, drop = sorted((a, b), key=lambda s: (_PRIORITY.get(s.priority, 2), s.window[0], s.id))
            if not future(drop.id) and future(keep.id):
                keep, drop = drop, keep
            if rule == "overlap":
                typ, hc = "double_booking", "No overlapping shifts"
                why = f"double-booked: also on {_describe(keep)}"
                msg = f"{name} is on {_describe(a)} and {_describe(b)} at the same time."
            else:
                typ, hc = "rest_violation", "Minimum rest between shifts"
                why = f"only {v['gap_hours']:g}h rest next to {_describe(keep)}"
                msg = (f"{name} has only {v['gap_hours']:g}h rest between {_describe(a)} and {_describe(b)} "
                       f"(minimum {ds.constraints.min_rest_hours:g}h).")
            add(ScheduleConflict(id=f"{typ}:{eid}:{':'.join(sorted(v['shift_ids']))}", type=typ, label=LABELS[typ],
                                 hard_constraint=hc, employee_id=eid, employee_name=name,
                                 shift_ids=[a.id, b.id], release={drop.id: why} if future(drop.id) else {},
                                 message=msg, repairable=future(drop.id)))
        elif rule == "qualification":
            s = shifts[v["shift_id"]]
            certs = {c.lower() for c in s.required_certifications}
            missing_certs = [m for m in v["missing"] if m.lower() in certs]
            typ = "missing_certification" if missing_certs else "missing_skill"
            hc = "Required certification" if missing_certs else "Required skill"
            why = f"lacks {', '.join(v['missing'])}"
            add(ScheduleConflict(id=f"{typ}:{eid}:{s.id}", type=typ, label=LABELS[typ], hard_constraint=hc,
                                 employee_id=eid, employee_name=name, shift_ids=[s.id],
                                 release={s.id: why} if future(s.id) else {},
                                 message=f"{name} is assigned to {_describe(s)} without {', '.join(v['missing'])}.",
                                 repairable=future(s.id)))
        elif rule == "unavailable":
            s = shifts[v["shift_id"]]
            add(ScheduleConflict(id=f"unavailable_assignee:{eid}:{s.id}", type="unavailable_assignee",
                                 label=LABELS["unavailable_assignee"], hard_constraint="Availability",
                                 employee_id=eid, employee_name=name, shift_ids=[s.id],
                                 release={s.id: f"unavailable ({v.get('reason') or 'marked unavailable'})"}
                                 if future(s.id) else {},
                                 message=f"{name} is assigned to {_describe(s)} but is marked unavailable.",
                                 repairable=future(s.id)))
        elif rule in ("daily_hours", "weekly_hours"):
            released = {sid for v0 in first for sid in _release_of(v0, shifts, future)}
            mine = sorted((shifts[sid] for sid, x in amap.items() if x == eid and sid not in released and (
                shifts[sid].date == v.get("date") if rule == "daily_hours" else True)), key=lambda s: s.window[0])
            if rule == "weekly_hours":
                from core.rules import week_key
                mine = [s for s in mine if week_key(s) == v["week"]]
            drop = next((s for s in reversed(mine) if future(s.id)), None)
            period = v.get("date") or v.get("week")
            hc = "Maximum daily hours" if rule == "daily_hours" else "Maximum weekly hours"
            add(ScheduleConflict(id=f"{rule}:{eid}:{period}", type=rule, label=LABELS[rule], hard_constraint=hc,
                                 employee_id=eid, employee_name=name, shift_ids=[s.id for s in mine],
                                 release={drop.id: f"{v['hours']:g}h scheduled in {period}, above the limit"}
                                 if drop else {},
                                 message=f"{name} is scheduled {v['hours']:g}h in {period}, above the limit.",
                                 repairable=drop is not None))
    for s in ds.shifts:
        if s.id not in amap:
            add(ScheduleConflict(id=f"open_shift:{s.id}", type="open_shift", label=LABELS["open_shift"],
                                 hard_constraint="Mandatory shift coverage", shift_ids=[s.id],
                                 cover=[s.id] if future(s.id) else [],
                                 message=f"{_describe(s)} has nobody assigned.", repairable=future(s.id)))
    order = {t: i for i, t in enumerate(LABELS)}
    out.sort(key=lambda c: (not c.repairable, order[c.type], c.id))
    return out
