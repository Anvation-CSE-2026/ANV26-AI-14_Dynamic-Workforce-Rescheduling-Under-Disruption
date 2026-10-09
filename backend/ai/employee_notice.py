"""Employee-facing change notices (Round 2: employee transparency).

Deliberately template-only. A notice goes to a real person about their own
schedule, so it must be exact, consistent and privacy-safe:
* it states what changed for THIS employee only (from ``ChangeFact``);
* it never names the absent colleague or their reason ("sick", "emergency"...);
* it cites the policies that protected the employee (rest, hours) so the
  change is visibly compliant;
* it always asks for acknowledgement and offers a way to flag a conflict.

``check_notice`` enforces the privacy rules and can be applied to any notice
text the frontend or backend produces.
"""

from __future__ import annotations

import json
from datetime import date as Date
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from .explanation import policy_label
from .grounding import check_narration
from .schemas import ChangeFact, PolicyCitation

PRIVATE_TERMS = ("sick", "illness", "ill", "emergency", "leave", "personal", "medical", "hospital",
                 "family", "pregnant", "bereavement", "absent", "absence", "unavailable")


class EmployeeNotice(BaseModel):
    employee_id: str
    title: str
    body: str
    changes: list[ChangeFact]
    policies: list[PolicyCitation] = Field(default_factory=list)
    requires_acknowledgement: bool = True
    schedule_version: Optional[str] = None


def _day(iso: str) -> str:
    return Date.fromisoformat(iso).strftime("%A %d %B")


def _line(c: ChangeFact) -> str:
    day = _day(c.date)
    if c.change_type == "added":
        return f"You've been added to {c.to_assignment} on {day}, {c.to_shift}."
    if c.change_type == "unassigned":
        return f"Your {c.from_assignment} shift on {day} ({c.from_shift}) has been removed."
    if c.change_type == "shift_moved":
        return f"Your shift on {day} moves from {c.from_shift} to {c.to_shift} ({c.to_assignment or c.from_assignment})."
    shift = f", {c.to_shift}" if c.to_shift else ""
    was = f" (previously {c.from_assignment}{', ' + c.from_shift if c.from_shift and c.from_shift != c.to_shift else ''})" \
        if c.from_assignment else ""
    return f"On {day} you'll work {c.to_assignment}{shift}{was}."


def build_notice(employee_id: str, employee_name: str, changes: list[ChangeFact],
                 policies: Optional[list[PolicyCitation]] = None, manager_name: str = "your manager",
                 schedule_version: Optional[str] = None) -> EmployeeNotice:
    mine = [c for c in changes if c.employee_id == employee_id]
    if not mine:
        raise ValueError(f"no changes for {employee_id}")
    protective = [p for p in (policies or []) if p.satisfied and p.constraint_type in
                  ("minimum_rest", "max_weekly_hours", "max_daily_hours", "max_overtime_weekly",
                   "max_consecutive_days")]
    first = employee_name.split()[0]
    intro = ("Your schedule has been updated to resolve a scheduling conflict:"
             if all(c.change_type == "unassigned" for c in mine) else
             "Your schedule has been updated to cover a gap in the team:")
    lines = [f"Hi {first},", "", intro]
    lines += [f"• {_line(c)}" for c in mine]
    if protective:
        lines += ["", "This change keeps you within: " + "; ".join(
            f"{policy_label(p)} ({p.document} §{p.section})" for p in protective) + "."]
    lines += ["", f"Please acknowledge this change in ResQWork. If it conflicts with something, use "
                  f"'Report a conflict' and {manager_name} will review it.", "", "Thank you!"]
    title = "Schedule change: " + ", ".join(sorted({_day(c.date) for c in mine}))
    return EmployeeNotice(employee_id=employee_id, title=title, body="\n".join(lines), changes=mine,
                          policies=protective, schedule_version=schedule_version)


def check_notice(notice: EmployeeNotice, roster_names: Optional[Iterable[str]] = None) -> list[str]:
    """Privacy + grounding check: no colleague names, no absence reasons, no unsupported numbers.

    The recipient's own name is allowed (it is in ``notice.changes``); every other roster name is not.
    """
    facts = json.loads(notice.model_dump_json(include={"changes", "policies"}))
    problems = check_narration([notice.title, notice.body], [], facts, roster_names, ())
    # Absence-reason terms are checked on the text *minus* the recipient's own work context, so a shift called
    # "Emergency Day" or a "Nursing … Policy" title doesn't count as leaking a colleague's reason.
    own = sorted({v for v in _strings(facts) if len(v) > 2}, key=len, reverse=True)
    title, body = notice.title, notice.body
    for v in own:
        title, body = title.replace(v, " "), body.replace(v, " ")
    problems += [p for p in check_narration([title, body], [], facts, None, PRIVATE_TERMS) if "forbidden term" in p]
    return problems


def _strings(obj) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)
