"""Voice alert & decision agent.

The agent never optimizes or invents. It speaks facts that already exist
(the latest proposal, its grounded explanation, the computed why-not list,
notifications, KPIs) and routes spoken commands to the same service
methods the UI uses. Approval by voice goes through ``ResQWork.approve``,
which keeps the human-in-the-loop guarantee.

Speech: the browser's Web Speech API (no key) by default. Optional server
TTS via ElevenLabs when ``ELEVENLABS_API_KEY`` is set; any TTS failure falls
back to text, so notifications are never lost.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
from datetime import date as Date
from typing import Optional

from ai.resolution import resolve_employee

from .domains import term


def _day(iso: str) -> str:
    return Date.fromisoformat(iso).strftime("%A")


def _clock(hhmm: str) -> str:
    """24-hour clock everywhere (product rule): 07:00, 17:30, never AM/PM."""
    h, m = map(int, hhmm.split(":"))
    return f"{h:02d}:{m:02d}"


def manager_alert(domain: str, disruption: dict) -> str:
    if disruption.get("kind") == "conflict":
        n = len(disruption["conflicts"])
        first = disruption["conflicts"][0]["message"]
        return (f"There {'are' if n != 1 else 'is'} {n} schedule conflict{'s' if n != 1 else ''} to resolve. "
                f"{first}")
    d = disruption["disruption"]
    n = len(disruption.get("affected_shifts", []))
    dept = term(domain, "department", "department").lower()
    when = f"on {_day(d['date'])}" + (f" from {_clock(d['start'])} to {_clock(d['end'])}" if d.get("start") else "")
    return (f"There is a new {term(domain, 'disruption', 'workforce disruption').lower()}. "
            f"{disruption['employee_name']} is unavailable {when}. {n} shift{'s are' if n != 1 else ' is'} at risk "
            f"in your {dept}.")


def recommendation(proposal: dict) -> str:
    r = proposal["result"]
    if not r["options"]:
        return "ResQWork could not find a feasible repair. " + " ".join(r.get("infeasibility_reasons", []))
    best = next(o for o in r["options"] if o["option_id"] == r["recommended_option_id"])
    who = ", ".join(sorted({s["employee_name"] for s in best["selected"]})) or "nobody new"
    i = best["impact"]
    if i["unfilled_shifts"]:
        text = (f"ResQWork could not find a complete repair. {i['unfilled_shifts']} shift"
                f"{'s stay' if i['unfilled_shifts'] != 1 else ' stays'} uncovered. "
                + " ".join(r.get("infeasibility_reasons", [])))
        if proposal.get("relaxation"):
            text += " " + proposal["relaxation"]["message"]
        return text
    parts = [f"ResQWork recommends {best['label']}: assign {who}.",
             f"This changes {i['assignments_changed']} assignment{'s' if i['assignments_changed'] != 1 else ''}, "
             f"affects {i['employees_affected']} employee{'s' if i['employees_affected'] != 1 else ''}, "
             f"keeps {i['skill_coverage_pct']:g} percent skill coverage, "
             + ("adds no overtime" if not i["overtime_hours_added"] else f"adds {i['overtime_hours_added']:g} hours of overtime")
             + f", and has a {i['impact_level'].lower()} scheduling impact."]
    if len(r["options"]) > 1:
        parts.append(f"There {'is' if len(r['options']) == 2 else 'are'} {len(r['options']) - 1} alternative"
                     f"{'s' if len(r['options']) > 2 else ''}.")
    return " ".join(parts)


def why_not(proposal: dict, name: str, employees: list[dict]) -> str:
    from ai.schemas import EmployeeRef
    match = resolve_employee(name, [EmployeeRef(id=e["id"], name=e["name"]) for e in employees])
    if match.status != "MATCH":
        return f"I couldn't identify {name}." + (" Did you mean " + " or ".join(c.name for c in match.candidates) + "?"
                                                 if match.candidates else "")
    r = proposal["result"]
    best = next((o for o in r["options"] if o["option_id"] == r.get("recommended_option_id")), None)
    if best and any(s["employee_id"] == match.employee.id for s in best["selected"]):
        return f"{match.employee.name} is the recommended replacement."
    rej = next((x for x in r["rejected"] if x["employee_id"] == match.employee.id), None)
    if not rej:
        return f"{match.employee.name} was not evaluated for this shift."
    text = {
        "REST_PERIOD_VIOLATION": "would violate the minimum rest-period requirement",
        "SHIFT_OVERLAP": "already has an overlapping shift",
        "MISSING_SKILL": "doesn't have the required skill",
        "MISSING_CERTIFICATION": "doesn't hold the required certification",
        "WOULD_UNCOVER_SHIFT": "would leave another shift uncovered",
        "SCHEDULE_CONFLICT": "has a schedule conflict on that shift",
        "UNAVAILABLE": "is unavailable at that time",
        "WOULD_CREATE_OVERTIME": "would need overtime",
        "WOULD_EXCEED_MAX_HOURS": "would exceed their working-hour limit",
        "HIGHER_IMPACT": "would cause more disruption to the schedule",
        "EXCLUDED_BY_MANAGER": "was excluded at your request",
        "LOCKED_BY_MANAGER": "has a locked schedule",
        "MANAGER_FEEDBACK": "was avoided because of your earlier feedback",
    }.get(rej["reason_code"], "ranked lower")
    return f"{match.employee.name} {text}: {rej['detail']}."


def employee_voice_line(notice, names: dict) -> str:
    c = notice.changes[0]
    if c.change_type == "shift_moved":
        return f"Your shift on {_day(c.date)} has changed from {c.from_shift} to {c.to_shift}."
    if c.change_type in ("added", "reassigned") and c.to_shift:
        start, end = c.to_shift.split("-")
        return (f"Your schedule has changed. On {_day(c.date)} you'll work {c.to_assignment} "
                f"from {_clock(start)} to {_clock(end)}. Please acknowledge in ResQWork.")
    return "Your schedule has changed. Please check ResQWork and acknowledge."


def ops_summary(domain: str, metrics: dict) -> str:
    at_risk = metrics.get("at_risk_assignments", {}).get("value", 0)
    cov = metrics.get("coverage_pct", {}).get("value", 100)
    shift = term(domain, "shift", "shift").lower()
    return (f"{at_risk} {shift}{'s are' if at_risk != 1 else ' is'} currently at risk due to employee unavailability. "
            f"Coverage is {cov:g} percent.")


INTENTS = [
    ("approve", re.compile(r"\b(approve|accept|go ahead|confirm)\b", re.I)),
    ("reject", re.compile(r"\b(reject|decline|cancel)\b", re.I)),
    ("why_not", re.compile(r"\bwhy (?:not|wasn'?t|isn'?t)\s+([A-Z]?[a-z]+(?:\s+[A-Z][a-z]+)?)", re.I)),
    ("alternatives", re.compile(r"\b(alternatives?|options?|other choices)\b", re.I)),
    ("recommend", re.compile(r"\b(recommend|recommended|suggest|repair|what should)\b", re.I)),
    ("status", re.compile(r"\b(status|at risk|coverage|summary|what'?s happening|disruption)\b", re.I)),
]


def detect(utterance: str) -> tuple[str, Optional[str]]:
    for name, pat in INTENTS:
        m = pat.search(utterance or "")
        if m:
            return name, (m.group(1) if name == "why_not" else None)
    return "unknown", None


def alternatives(proposal: dict) -> str:
    opts = proposal["result"]["options"]
    if len(opts) < 2:
        return "There is only one valid repair for this disruption."
    lines = []
    for o in opts:
        i = o["impact"]
        lines.append(f"{o['label']}, {o['title']}: {i['assignments_changed']} change"
                     f"{'s' if i['assignments_changed'] != 1 else ''}, {i['overtime_hours_added']:g} hours overtime, "
                     f"fairness {o['fairness']['fairness_score']:g}.")
    return " ".join(lines)


def tts(text: str) -> Optional[dict]:
    """Optional server-side speech. Returns {'mime', 'base64'} or None (caller falls back to browser speech/text)."""
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        return None
    voice = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}", method="POST",
        data=json.dumps({"text": text, "model_id": "eleven_turbo_v2_5"}).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310 - fixed https host
            return {"mime": "audio/mpeg", "base64": base64.b64encode(resp.read()).decode()}
    except Exception:  # noqa: BLE001 - voice must never break the flow
        return None
