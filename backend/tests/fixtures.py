"""Shared demo data for AI and RAG tests. Reference 'today' is Thu 2026-10-08.

Scenario: a customer-support operations team. Rahul (L2 Support) is out
tomorrow; the optimizer repairs the schedule; the AI layer interprets and explains.
"""

import re
from pathlib import Path

from ai.schemas import (
    AssignmentRef,
    ChangeFact,
    Disruption,
    EmployeeRef,
    ExplanationFacts,
    MetricsFact,
    ParseContext,
    PolicyCitation,
    RejectedFact,
    SelectedFact,
    ShiftRef,
)

TODAY = "2026-10-08"
TOMORROW = "2026-10-09"
POLICY_DIR = Path(__file__).resolve().parents[2] / "shared" / "policies" / "examples-support-ops"

EMPLOYEES = [
    EmployeeRef(id="EMP001", name="Rahul Sharma", role="L2 Support"),
    EmployeeRef(id="EMP002", name="Priya Nair", role="L2 Support"),
    EmployeeRef(id="EMP003", name="Arjun Mehta", role="L2 Support"),
    EmployeeRef(id="EMP004", name="Sanjay Kumar", role="L1 Support"),
    EmployeeRef(id="EMP005", name="Sanjay Rao", role="L1 Support"),
    EmployeeRef(id="EMP006", name="Meera Iyer", aliases=["Meeru"], role="L2 Support"),
]
ASSIGNMENTS = [
    AssignmentRef(id="SUPPORT_L2", name="L2 Support queue", aliases=["L2 queue", "L2"]),
    AssignmentRef(id="SUPPORT_L1", name="L1 Support queue", aliases=["L1 queue", "L1"]),
    AssignmentRef(id="KANNADA_DESK", name="Kannada language desk", aliases=["Kannada desk"]),
]
SHIFTS = [
    ShiftRef(employee_id="EMP001", date=TOMORROW, start_time="09:00", end_time="17:00", assignment_id="SUPPORT_L2"),
    ShiftRef(employee_id="EMP002", date=TOMORROW, start_time="09:00", end_time="17:00", assignment_id="SUPPORT_L2"),
    ShiftRef(employee_id="EMP003", date=TOMORROW, start_time="13:00", end_time="21:00", assignment_id="KANNADA_DESK"),
    ShiftRef(employee_id="EMP006", date=TOMORROW, start_time="07:00", end_time="15:00", assignment_id="SUPPORT_L2"),
]
ROSTER_NAMES = [e.name for e in EMPLOYEES]
NAMES = {e.id: e.name for e in EMPLOYEES}


def context(**overrides) -> ParseContext:
    data = dict(reference_date=TODAY, employees=EMPLOYEES, assignments=ASSIGNMENTS, shifts=SHIFTS)
    data.update(overrides)
    return ParseContext(**data)


# --------------------------------------------------------------- disruption


def extraction(disruptions=None, preferences=None, is_report=True, ad_hoc=None) -> dict:
    return {
        "is_disruption_report": is_report,
        "disruptions": disruptions or [],
        "preferences": {"lock_employee_mentions": [], "exclude_employee_mentions": [], "allow_overtime": None,
                        "priority": None, **(preferences or {})},
        "ad_hoc_constraints": ad_hoc or [],
    }


def raw(mention="Rahul", date=TOMORROW, date_expression="tomorrow", start="09:00", end="17:00",
        time_expression=None, reason="emergency", type_="employee_unavailability", assignment=None) -> dict:
    return {"type": type_, "employee_mention": mention, "assignment_mention": assignment, "date": date,
            "date_expression": date_expression, "start_time": start, "end_time": end,
            "time_expression": time_expression, "reason": reason}


# -------------------------------------------------------------- explanation

POLICIES_APPLIED = [
    PolicyCitation(policy_id="HR-WT-001", document="Working Time Policy", section="3.1",
                   constraint_type="minimum_rest", value=11, unit="hours"),
    PolicyCitation(policy_id="HR-WT-001", document="Working Time Policy", section="2.2",
                   constraint_type="max_weekly_hours", value=40, unit="hours"),
]


def feasible_facts(with_policies: bool = False) -> ExplanationFacts:
    return ExplanationFacts(
        status="OPTIMAL",
        disruption=Disruption(type="employee_unavailability", employee_id="EMP001", date=TOMORROW,
                              start_time="09:00", end_time="17:00", reason="emergency"),
        disrupted_employee_name="Rahul Sharma",
        changes=[
            ChangeFact(employee_id="EMP001", employee_name="Rahul Sharma", change_type="unassigned",
                       date=TOMORROW, from_assignment="SUPPORT_L2", from_shift="09:00-17:00"),
            ChangeFact(employee_id="EMP003", employee_name="Arjun Mehta", change_type="reassigned",
                       date=TOMORROW, from_assignment="KANNADA_DESK", to_assignment="SUPPORT_L2",
                       from_shift="13:00-21:00", to_shift="09:00-17:00"),
        ],
        selected=[SelectedFact(employee_id="EMP003", employee_name="Arjun Mehta", covers_assignment="SUPPORT_L2",
                               available=True, skills_match=True, matched_skills=["Tier-2 troubleshooting"],
                               overtime_hours=0, weekly_hours_before=32, weekly_hours_after=32,
                               max_weekly_hours=40, rest_hours_before_shift=14, previous_changes_this_period=0)],
        rejected=[
            RejectedFact(employee_id="EMP002", employee_name="Priya Nair", reason_code="SHIFT_OVERLAP"),
            RejectedFact(employee_id="EMP004", employee_name="Sanjay Kumar", reason_code="MISSING_SKILL",
                         detail="no Tier-2 certification", policy_id="OPS-SUP-007"),
            RejectedFact(employee_id="EMP006", employee_name="Meera Iyer", reason_code="REST_PERIOD_VIOLATION",
                         detail="only 9h since last shift", policy_id="HR-WT-001"),
        ],
        metrics=MetricsFact(assignments_changed=1, employees_affected=1, overtime_hours=0,
                            hard_constraint_violations=0, impact_score=14, impact_level="LOW", fairness_score=92),
        constraints_checked=["availability", "required skills", "max 40h/week", "11h rest between shifts"],
        policies_applied=POLICIES_APPLIED if with_policies else [],
    )


def infeasible_facts() -> ExplanationFacts:
    return ExplanationFacts(
        status="INFEASIBLE",
        disruption=Disruption(type="employee_unavailability", employee_id="EMP001", date=TOMORROW,
                              start_time="09:00", end_time="17:00"),
        disrupted_employee_name="Rahul Sharma",
        metrics=MetricsFact(assignments_changed=0, employees_affected=0, unfilled_requirements=1),
        infeasibility_reasons=["No available agent has Tier-2 certification between 09:00 and 17:00"],
        constraints_checked=["required skills", "max 40h/week"],
    )


# ------------------------------------------------------- policy translation

# What a well-behaved model returns for the demo policy chunks (quotes are verbatim).
CANNED_POLICY = {
    "HR-WT-001#2.1": [{"constraint_type": "max_daily_hours", "value": 9, "unit": "hours", "severity": "hard",
                       "quote": "No employee may be scheduled for more than 9 hours in a working day",
                       "interpretation": "Nobody works more than 9 hours in a day."}],
    "HR-WT-001#2.2": [{"constraint_type": "max_weekly_hours", "value": 40, "unit": "hours", "severity": "hard",
                       "quote": "Employees must not work more than 40 hours in a calendar week.",
                       "interpretation": "Weekly hours are capped at 40."}],
    "HR-WT-001#3.1": [{"constraint_type": "minimum_rest", "value": 11, "unit": "hours", "severity": "hard",
                       "quote": "Employees must receive at least 11 hours of rest between the end of one shift "
                                "and the start of the next.",
                       "interpretation": "At least 11 hours between shifts."}],
    "HR-WT-001#3.2": [{"constraint_type": "max_consecutive_days", "value": 6, "unit": "days", "severity": "hard",
                       "quote": "No employee may work more than 6 consecutive days.",
                       "interpretation": "At most 6 days in a row."}],
    "HR-WT-001#4": [{"constraint_type": "max_weekends_per_month", "value": 2, "severity": "soft",
                     "quote": "Employees should not be scheduled for more than 2 weekends per month.",
                     "interpretation": "Preferably at most 2 weekends a month."}],
    "HR-OT-002#1": [{"constraint_type": "overtime_requires_approval", "value": True, "severity": "hard",
                     "quote": "All overtime requires prior approval from the operations manager.",
                     "interpretation": "Overtime needs manager approval."}],
    "HR-OT-002#2": [{"constraint_type": "max_overtime_weekly", "value": 8, "unit": "hours", "severity": "hard",
                     "quote": "Overtime is capped at 8 hours per employee per week.",
                     "interpretation": "At most 8 overtime hours a week."}],
    "OPS-SUP-007#1.1": [{"constraint_type": "min_staffing", "value": 3, "severity": "hard",
                         "scope": {"assignment": "SUPPORT_L2"},
                         "quote": "The L2 Support queue must have at least 3 agents on shift between 09:00 and 21:00.",
                         "interpretation": "Three agents on the L2 queue from 09:00 to 21:00."}],
    "OPS-SUP-007#1.2": [{"constraint_type": "min_staffing", "value": 1, "severity": "hard",
                         "scope": {"assignment": "KANNADA_DESK"},
                         "quote": "At least 1 Kannada-speaking agent must be on shift during business hours.",
                         "interpretation": "One Kannada speaker on shift in business hours."},
                        {"constraint_type": "required_skill", "value": "Kannada", "severity": "hard",
                         "scope": {"assignment": "KANNADA_DESK"},
                         "quote": "At least 1 Kannada-speaking agent must be on shift during business hours.",
                         "interpretation": "The Kannada desk needs Kannada speakers."}],
    "OPS-SUP-007#2": [{"constraint_type": "required_skill", "value": "Tier-2 troubleshooting", "severity": "hard",
                       "scope": {"assignment": "SUPPORT_L2"},
                       "quote": "Only agents certified in Tier-2 troubleshooting may cover the L2 Support queue.",
                       "interpretation": "L2 queue needs Tier-2 certification."}],
    "OPS-SUP-007#3": [{"constraint_type": "max_weekly_hours", "value": 45, "unit": "hours", "severity": "hard",
                       "scope": {"role": "L2 Support"},
                       "quote": "During peak season, L2 Support agents may work up to 45 hours per week.",
                       "interpretation": "L2 agents may work 45 hours in peak season."}],
    "OPS-SUP-007#4": [{"constraint_type": "max_schedule_changes_per_month", "value": 3, "severity": "soft",
                       "quote": "An agent's schedule should not be changed more than 3 times in a calendar month.",
                       "interpretation": "Avoid changing someone's schedule more than 3 times a month."}],
    "OPS-SUP-007#5": [{"constraint_type": "respect_employee_preferences", "value": True, "severity": "soft",
                       "quote": "Agent shift preferences should be respected where possible.",
                       "interpretation": "Respect shift preferences where possible."}],
}
CANNED_UNSUPPORTED = {
    "HR-OT-002#3": "Overtime opportunities should be offered fairly, rotating among qualified employees.",
    "OPS-SUP-007#6": "Agents must be notified at least 12 hours before a schedule change.",
}

_CHUNK_ID = re.compile(r"\[chunk_id: ([^\]]+)\]")


def policy_responder(overrides=None):
    """MockProvider responder: answers policy_translation calls from CANNED_POLICY for the chunks in the prompt."""
    table = {**CANNED_POLICY, **(overrides or {})}

    def respond(system, user, schema_name):
        ids = _CHUNK_ID.findall(user)
        return {
            "constraints": [{**c, "chunk_id": cid} for cid in ids for c in table.get(cid, [])],
            "unsupported_rules": [{"chunk_id": cid, "text": CANNED_UNSUPPORTED[cid]}
                                  for cid in ids if cid in CANNED_UNSUPPORTED],
        }
    return respond
