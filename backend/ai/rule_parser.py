"""Rule-based extraction for common disruption phrasing: the no-LLM fallback.

Produces the same ``RawExtraction`` the LLM would, so the deterministic
``DisruptionParser.resolve`` step (names→IDs, dates, times, validation) is
reused unchanged. Handles e.g.:

    "Rahul is unavailable tomorrow from 9 AM to 5 PM"
    "Priya called in sick today"
    "Arjun can't come on Friday 13:00-21:00, no overtime"
    "Meera is on leave on 2026-10-09; don't change Carlos's shift"
Anything it can't read confidently is left empty, so the resolver asks.
"""

from __future__ import annotations

import re
from typing import Optional

from .schemas import RawAdHoc, RawDisruption, RawExtraction, RawPreferences

_TRIGGER = re.compile(r"\b(unavailable|not available|sick|ill|on leave|leave|absent|out|off|can'?t (?:come|make it|work)|"
                      r"cannot (?:come|work)|won'?t be (?:in|available)|emergency|called in)\b", re.I)
_NAME = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b")
_STOP_NAMES = {"Tomorrow", "Today", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
               "Find", "Please", "The", "No", "Don", "Dont", "Keep", "Avoid", "Use", "From", "Mr", "Ms", "Mrs", "Dr",
               "Shift", "Overtime", "AM", "PM", "ICU", "ER", "Line"}
_DATE_ISO = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
_DATE_WORD = re.compile(r"\b(today|tonight|tomorrow|day after tomorrow|(?:this |next )?(?:monday|tuesday|wednesday|"
                        r"thursday|friday|saturday|sunday))\b", re.I)
_RANGE = re.compile(r"(?:from\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:-|–|to|until|till)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
                    re.I)
_REASON = {"sick": "sick", "ill": "sick", "called in": "sick", "emergency": "emergency", "leave": "leave",
           "personal": "personal"}


def _hhmm(h: str, m: Optional[str], ampm: Optional[str], other_ampm: Optional[str], is_end: bool, start_h: int = 0) -> str:
    hour, minute = int(h), int(m or 0)
    mer = (ampm or other_ampm or "").lower()
    if mer == "pm" and hour < 12:
        hour += 12
    elif mer == "am" and hour == 12:
        hour = 0
    elif not mer and is_end and hour <= start_h and hour < 12:
        hour += 12           # "9 to 5" → 09:00–17:00
    return f"{hour:02d}:{minute:02d}"


def _names_before(text: str, pattern: re.Pattern) -> list[str]:
    out = []
    for m in pattern.finditer(text):
        before = text[max(0, m.start() - 60):m.start()]
        found = [n for n in _NAME.findall(before) if n.split()[0] not in _STOP_NAMES]
        if found:
            out.append(found[-1])
    return out


def rule_extract(text: str) -> RawExtraction:
    if not _TRIGGER.search(text):
        return RawExtraction(is_disruption_report=False)
    clause = re.split(r"[.;]|\b(?:but|and)\s+(?:don'?t|do not|no)\b", text)[0]
    trig = _TRIGGER.search(clause) or _TRIGGER.search(text)
    names = [n for n in _NAME.findall(clause[:trig.start()]) if n.split()[0] not in _STOP_NAMES]
    mention = names[-1] if names else None

    date_word = _DATE_WORD.search(text)
    iso = _DATE_ISO.search(text)
    start = end = None
    rng = _RANGE.search(text)
    if rng:
        sh, sm, sa, eh, em, ea = rng.groups()
        start = _hhmm(sh, sm, sa, ea if not sa and ea else None, False)
        end = _hhmm(eh, em, ea, sa if not ea else None, True, int(start[:2]))
    time_expr = None
    for w in ("morning", "afternoon", "evening", "night", "all day", "whole day", "full day", "shift"):
        if re.search(rf"\b{w}\b", text, re.I) and not rng:
            time_expr = w
            break
    reason = next((v for k, v in _REASON.items() if re.search(rf"\b{k}\b", text, re.I)), None)

    prefs = RawPreferences(
        lock_employee_mentions=_names_before(text, re.compile(r"(?:'s|’s)?\s+(?:shift|schedule)\s+(?:unchanged|as is)|"
                                                               r"\b(?:don'?t|do not)\s+(?:change|move|touch)\b(?=\s+[A-Z])",
                                                               re.I)),
        exclude_employee_mentions=[m.group(1) for m in re.finditer(r"\b(?:don'?t|do not|never)\s+use\s+([A-Z][a-z]+)", text)],
        allow_overtime=False if re.search(r"\bno overtime\b|\bwithout overtime\b|\bavoid overtime\b", text, re.I) else None,
        priority=("minimize_affected_employees" if re.search(r"disturb|affect(ing)? (as )?few", text, re.I)
                  else "fairness" if re.search(r"\bfair", text, re.I) else
                  "minimize_changes" if re.search(r"minim\w+ change|as is|as few changes", text, re.I) else None))
    # "don't change Priya's shift" → names after the verb
    for m in re.finditer(r"\b(?:don'?t|do not)\s+(?:change|move|touch)\s+([A-Z][a-z]+)", text):
        prefs.lock_employee_mentions.append(m.group(1))
    prefs.lock_employee_mentions = sorted(set(prefs.lock_employee_mentions) - ({mention} if mention else set()))
    ad_hoc = [RawAdHoc(kind="required_skill", value=m.group(1), text=m.group(0))
              for m in re.finditer(r"must (?:know|have|speak)\s+([A-Z][\w\- ]+?)(?:[.,;]|$)", text)]
    return RawExtraction(
        is_disruption_report=True,
        disruptions=[RawDisruption(type="employee_unavailability", employee_mention=mention,
                                   date=iso.group(1) if iso else None,
                                   date_expression=date_word.group(1) if date_word else (iso.group(1) if iso else None),
                                   start_time=start, end_time=end, time_expression=time_expr, reason=reason)],
        preferences=prefs, ad_hoc_constraints=ad_hoc)
