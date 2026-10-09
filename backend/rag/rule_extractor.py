"""Deterministic policy rule extraction.

Two jobs:
1. **Verification**: after the LLM translates a policy sentence, the same
   quote is run through these patterns. Agreement raises interpretation
   confidence; disagreement is surfaced for review (never silently resolved
   in the model's favour).
2. **Fallback**: with no LLM available, common rules are still extracted so
   the optimizer gets the organization's limits. Scope can't be inferred
   reliably here, so rules-only output is always global; conflict resolution
   then applies the strictest value, which is safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

from .text import sentences

_NUM_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
              "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_N = r"(\d+(?:\.\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_LIMIT = r"(?:more than|exceed(?:ing)?|in excess of|over|a maximum of|maximum of|no more than|up to|capped at|at most)"
_PERIOD_WEEK = r"(?:in (?:a|any|one)|per|a|each|every)\s+(?:calendar\s+)?week"
_PERIOD_DAY = r"(?:in (?:a|any|one)|per|a|each|every)\s+(?:working\s+|calendar\s+)?(?:day|shift)"

_SOFT = re.compile(r"\b(should|where possible|wherever possible|preferably|ideally|encouraged|try to|aim to)\b", re.I)


@dataclass
class RuleMatch:
    constraint_type: str
    value: Union[float, int, bool]
    quote: str
    severity: str


def _num(s: str) -> float:
    s = s.lower()
    return float(_NUM_WORDS[s]) if s in _NUM_WORDS else float(s)


_PATTERNS: list[tuple[str, re.Pattern, Optional[Union[bool, str]]]] = [
    ("minimum_rest", re.compile(rf"\b(?:at least|minimum of|no less than|no fewer than)\s+{_N}\s+(?:consecutive\s+)?hours?\s+(?:of\s+)?(?:rest|off|break|uninterrupted rest)", re.I), None),
    ("minimum_rest", re.compile(rf"\b{_N}\s*(?:-|\s)?hours?\s+(?:of\s+)?(?:rest|break)\s+between", re.I), None),
    ("max_overtime_weekly", re.compile(rf"\bovertime\b[^.]*?\b{_LIMIT}\s+{_N}\s+hours?", re.I), None),
    ("max_overtime_weekly", re.compile(rf"\b{_LIMIT}\s+{_N}\s+hours?\s+of\s+overtime", re.I), None),
    ("max_weekly_hours", re.compile(rf"\b{_LIMIT}\s+{_N}\s+(?:working\s+|scheduled\s+)?hours?\s+{_PERIOD_WEEK}", re.I), None),
    ("max_weekly_hours", re.compile(rf"\b{_N}\s+hours?\s+{_PERIOD_WEEK}\s+(?:is the|as a)\s+(?:maximum|limit)", re.I), None),
    ("max_daily_hours", re.compile(rf"\b{_LIMIT}\s+{_N}\s+(?:working\s+|scheduled\s+)?hours?\s+{_PERIOD_DAY}", re.I), None),
    ("max_daily_hours", re.compile(rf"\bshifts?\s+(?:may|must|shall)\s+not\s+exceed\s+{_N}\s+hours?", re.I), None),
    ("max_consecutive_days", re.compile(rf"\b{_LIMIT}\s+{_N}\s+consecutive\s+(?:working\s+)?days", re.I), None),
    ("max_weekends_per_month", re.compile(rf"\b{_LIMIT}\s+{_N}\s+weekends?\s+(?:in a|per|a|each)\s+(?:calendar\s+)?month", re.I), None),
    ("max_schedule_changes_per_month", re.compile(rf"\b(?:changed|rescheduled|modified|reassigned)\s+{_LIMIT}\s+{_N}\s+times?\s+(?:in a|per|a|each)\s+(?:calendar\s+)?month", re.I), None),
    ("overtime_allowed", re.compile(r"\bovertime\s+(?:is|shall be|will be)\s+(?:not permitted|prohibited|not allowed|forbidden)", re.I), False),
    ("overtime_requires_approval", re.compile(r"\bovertime\b[^.]*\b(?:requires?|needs?|subject to|must be)\b[^.]*\b(?:approv|authori[sz]|sign-?off)", re.I), True),
    ("respect_employee_preferences", re.compile(r"\bpreferences?\s+(?:should|must|shall|will)\s+be\s+(?:respected|honou?red|taken into account|considered)", re.I), True),
]


def _severity(sentence: str) -> str:
    """Policy statements are mandatory unless softened ("should", "where possible").

    Defaulting to hard is the safe direction: a misread soft rule only costs
    flexibility, while a misread hard rule could put people over legal limits.
    """
    return "soft" if _SOFT.search(sentence) else "hard"


def extract_rules(text: str) -> list[RuleMatch]:
    out: list[RuleMatch] = []
    for s in sentences(text):
        seen: set[str] = set()
        for ctype, pat, fixed in _PATTERNS:
            if ctype in seen:
                continue
            m = pat.search(s)
            if not m:
                continue
            if fixed is not None:
                value: Union[float, int, bool] = fixed
            else:
                v = _num(m.group(1))
                value = int(v) if v.is_integer() else v
            # "overtime is capped at N hours per week" also matches weekly-hours wording; keep the overtime reading
            # only (but "no more than 48 hours a week, including overtime" is a weekly limit)
            if ctype == "max_weekly_hours" and "max_overtime_weekly" in seen:
                continue
            seen.add(ctype)
            out.append(RuleMatch(ctype, value, s, _severity(s)))
    return out


def rule_value_for(quote: str, constraint_type: str) -> Optional[Union[float, int, bool]]:
    """Value the rules read from ``quote`` for this type, or None if no pattern applies."""
    for r in extract_rules(quote):
        if r.constraint_type == constraint_type:
            return r.value
    return None
