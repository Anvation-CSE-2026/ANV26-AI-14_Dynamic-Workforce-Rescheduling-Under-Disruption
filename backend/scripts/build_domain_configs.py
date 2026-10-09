"""Generate shared/domains/<domain>.json: the single source of domain adaptivity.

Run from backend/:  python -m scripts.build_domain_configs

The backend (KPIs, voice scripts, labels in notices) and the frontend
(dashboard names, KPI cards, terminology, sub-dashboards, demo buttons) both
read these files. Adding an industry means adding one config + one dataset;
no engine or UI code changes.

KPI ``metric`` keys and sub-dashboard ``widgets`` refer to generic
implementations (services/kpis.py and frontend/src/components/widgets).
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "shared" / "domains"


def kpi(id, label, metric, fmt, good, hint):
    return {"id": id, "label": label, "metric": metric, "format": fmt, "good": good, "hint": hint}


COMMON_KPIS = [
    kpi("workforce", "Workforce Status", "available_staff", "ratio", "high", "Available vs total people today and tomorrow"),
    kpi("coverage", "Schedule Coverage", "coverage_pct", "percent", "high", "Shifts with a qualified person assigned"),
    kpi("disruptions", "Active Disruptions", "active_disruptions", "count", "low", "Disruptions not yet repaired"),
    kpi("at_risk", "At-Risk Assignments", "at_risk_assignments", "count", "low", "Shifts affected by an open disruption"),
    kpi("overtime", "Overtime", "overtime_hours", "hours", "low", "Scheduled hours above contracted hours this week"),
    kpi("skills", "Skill Coverage", "skill_coverage_pct", "percent", "high", "Covered shifts staffed by fully qualified people"),
]


def rec(id, label, description, signals=(), points=15, manager=True):
    """A recognition category. ``signals`` = system-detected behaviours that earn it (see services/recognition.py)."""
    return {"id": id, "label": label, "description": description, "signals": list(signals), "points": points,
            "managerAwardable": manager}


def tiers(*benefits):
    return [{"points": p, "label": l, "benefit": b} for p, (l, b) in zip((40, 100, 200), benefits)]


DOMAINS = {
    "healthcare": {
        "label": "Healthcare", "tagline": "Hospitals, clinics & care homes", "icon": "HeartPulse", "accent": "#0f766e",
        "identity": "calm", "dashboardName": "Hospital Command Center",
        "terminology": {"employee": "Staff member", "employees": "Clinical staff", "shift": "Shift",
                        "assignment": "Unit assignment", "department": "Unit", "departments": "Units",
                        "skill": "Certification", "skills": "Certifications", "manager": "Nurse manager",
                        "disruption": "Staffing disruption", "organization": "Hospital"},
        "kpis": [kpi("staff_coverage", "Staff Coverage", "coverage_pct", "percent", "high", "Shifts with a qualified nurse assigned"),
                 kpi("critical", "Critical Shortages", "critical_uncovered", "count", "low", "Uncovered ICU/critical shifts"),
                 kpi("skills", "Skill Coverage", "skill_coverage_pct", "percent", "high", "Shifts staffed with all required certifications"),
                 kpi("overtime", "Overtime", "overtime_hours", "hours", "low", "Hours above contracted this week"),
                 kpi("at_risk_units", "At-Risk Units", "at_risk_departments", "count", "low", "Units with an open disruption")],
        "subDashboards": [
            {"id": "clinical", "name": "Clinical Staff Dashboard", "audience": "Charge nurses & unit leads",
             "widgets": ["department_coverage", "roster", "qualification_matrix", "fatigue_risk"]},
            {"id": "hr", "name": "Hospital Workforce / HR Dashboard", "audience": "HR & workforce planning",
             "widgets": ["overtime_by_person", "fairness_distribution", "disruption_history", "compliance"]}],
        "constraintLabels": {"required_skills": "Required certifications", "min_rest_hours": "Minimum rest between shifts",
                             "max_daily_hours": "Maximum shift length", "max_weekly_hours": "Weekly hours limit",
                             "overtime": "Overtime cap", "priority": "Patient-care priority"},
        "riskIndicators": [{"id": "fatigue", "label": "Fatigue risk", "metric": "fatigue_risk_count"},
                           {"id": "critical_units", "label": "Critical units affected", "metric": "critical_uncovered"}],
        "recommendedActions": ["Confirm the replacement with the charge nurse", "Check float-pool availability for the next 48h",
                               "Review overtime approvals for ICU staff"],
        "recognition": {
            "categories": [
                rec("shift_rescue", "Shift Rescue", "Covered a colleague's shift at short notice", ["disruption_cover"], 20),
                rec("critical_care", "Critical Care Support", "Covered a critical-unit shift (ICU, ED)", ["critical_cover"], 10),
                rec("reliability", "Reliability", "Acknowledged changes promptly and gave early notice of absences",
                    ["prompt_acknowledgement", "advance_notice"], 5),
                rec("patient_safety", "Patient Safety Champion", "Raised or prevented a patient-safety risk"),
                rec("teamwork", "Teamwork", "Went out of the way to support the unit"),
                rec("skill_development", "Skill Development", "Completed a certification or cross-training"),
            ],
            "tiers": tiers(("Recognized", "Name in the monthly unit newsletter"),
                           ("Valued", "First pick of preferred shifts next roster"),
                           ("Outstanding", "Half-day paid leave or a training voucher")),
        },
        "charts": ["department_coverage", "overtime_trend", "qualification_gaps"],
    },
    "manufacturing": {
        "label": "Manufacturing", "tagline": "Plants, lines & shifts", "icon": "Factory", "accent": "#b45309",
        "identity": "operations", "dashboardName": "Plant Operations Command Center",
        "terminology": {"employee": "Operator", "employees": "Operators", "shift": "Shift", "assignment": "Line station",
                        "department": "Line", "departments": "Lines", "skill": "Machine skill", "skills": "Machine skills",
                        "manager": "Shift supervisor", "disruption": "Line staffing disruption", "organization": "Plant"},
        "kpis": [kpi("production_coverage", "Production Coverage", "coverage_pct", "percent", "high", "Line stations staffed"),
                 kpi("at_risk_lines", "At-Risk Lines", "at_risk_departments", "count", "low", "Lines with an open disruption"),
                 kpi("skill_gaps", "Skill Gaps", "skill_gap_count", "count", "low", "Stations whose skill only 1 person has"),
                 kpi("overtime", "Overtime", "overtime_hours", "hours", "low", "Hours above contracted this week"),
                 kpi("availability", "Operator Availability", "available_staff", "ratio", "high", "Available operators")],
        "subDashboards": [
            {"id": "supervisor", "name": "Shift Supervisor Dashboard", "audience": "Shift supervisors",
             "widgets": ["department_coverage", "roster", "qualification_matrix", "fatigue_risk"]},
            {"id": "hr", "name": "Workforce / HR Dashboard", "audience": "Plant HR",
             "widgets": ["overtime_by_person", "fairness_distribution", "disruption_history", "compliance"]}],
        "constraintLabels": {"required_skills": "Machine & safety certification", "min_rest_hours": "Rest between shifts",
                             "max_daily_hours": "Maximum shift length", "max_weekly_hours": "Weekly hours limit",
                             "overtime": "Overtime cap", "priority": "Line criticality"},
        "riskIndicators": [{"id": "single_point", "label": "Single-skill stations", "metric": "skill_gap_count"},
                           {"id": "fatigue", "label": "Rotation fatigue", "metric": "fatigue_risk_count"}],
        "recommendedActions": ["Brief the replacement on the machine setup", "Cross-train a second CNC operator",
                               "Check maintenance windows before reassigning"],
        "recognition": {
            "categories": [
                rec("emergency_support", "Emergency Support", "Covered a colleague's shift at short notice", ["disruption_cover"], 20),
                rec("production_reliability", "Production Reliability", "Kept a critical line running", ["critical_cover"], 10),
                rec("reliability", "Reliability", "Acknowledged changes promptly and gave early notice of absences",
                    ["prompt_acknowledgement", "advance_notice"], 5),
                rec("safety_champion", "Safety Champion", "Spotted or prevented a safety hazard"),
                rec("quality_excellence", "Quality Excellence", "Zero-defect run or quality improvement"),
                rec("skill_development", "Skill Development", "Certified on a new machine or process"),
            ],
            "tiers": tiers(("Recognized", "Shift-floor recognition board"),
                           ("Valued", "Priority for preferred shift pattern"),
                           ("Outstanding", "Spot award or paid training course")),
        },
        "charts": ["department_coverage", "overtime_trend", "qualification_gaps"],
    },
    "education": {
        "label": "Education", "tagline": "Schools & colleges", "icon": "GraduationCap", "accent": "#4338ca",
        "identity": "academic", "dashboardName": "Academic Operations Dashboard",
        "terminology": {"employee": "Teacher", "employees": "Teachers", "shift": "Period", "assignment": "Class",
                        "department": "Department", "departments": "Departments", "skill": "Subject",
                        "skills": "Subjects", "manager": "Academic coordinator", "disruption": "Teacher absence",
                        "organization": "School"},
        "kpis": [kpi("teacher_coverage", "Teacher Coverage", "available_staff", "ratio", "high", "Teachers available"),
                 kpi("class_coverage", "Class Coverage", "coverage_pct", "percent", "high", "Periods with a teacher"),
                 kpi("subject_gaps", "Subject Gaps", "uncovered_shifts", "count", "low", "Periods without a qualified teacher"),
                 kpi("workload", "Teacher Workload", "avg_weekly_hours", "hours", "low", "Average scheduled teaching hours"),
                 kpi("conflicts", "Schedule Conflicts", "schedule_conflicts", "count", "low", "Double-booked teachers")],
        "subDashboards": [
            {"id": "department", "name": "Teacher / Department Dashboard", "audience": "Heads of department",
             "widgets": ["department_coverage", "roster", "qualification_matrix", "workload_balance"]},
            {"id": "admin", "name": "Academic Admin Dashboard", "audience": "Principal & admin office",
             "widgets": ["fairness_distribution", "disruption_history", "compliance", "overtime_by_person"]}],
        "constraintLabels": {"required_skills": "Subject qualification", "min_rest_hours": "Gap between periods",
                             "max_daily_hours": "Maximum teaching load per day", "max_weekly_hours": "Weekly teaching load",
                             "overtime": "Extra periods", "priority": "Exam-year classes"},
        "riskIndicators": [{"id": "load", "label": "Overloaded teachers", "metric": "fatigue_risk_count"},
                           {"id": "gaps", "label": "Uncovered periods", "metric": "uncovered_shifts"}],
        "recommendedActions": ["Share lesson plans with the substitute", "Inform class teachers of 8A and 9A",
                               "Balance substitute load across the week"],
        "recognition": {
            "categories": [
                rec("substitution_support", "Substitution Support", "Took a colleague's class at short notice", ["disruption_cover"], 20),
                rec("exam_support", "Critical Period Support", "Covered a high-priority class or exam period", ["critical_cover"], 10),
                rec("reliability", "Reliability", "Acknowledged changes promptly and gave early notice of absences",
                    ["prompt_acknowledgement", "advance_notice"], 5),
                rec("student_impact", "Student Impact", "Exceptional outcome or support for students"),
                rec("collaboration", "Collaboration", "Shared lesson plans or mentored a colleague"),
                rec("professional_development", "Professional Development", "Completed training or a new subject qualification"),
            ],
            "tiers": tiers(("Recognized", "Mention at the staff meeting"),
                           ("Valued", "A free period of choice next term"),
                           ("Outstanding", "Conference or course sponsorship")),
        },
        "charts": ["department_coverage", "workload_balance", "qualification_gaps"],
    },
    "technology": {
        "label": "IT / Technology", "tagline": "Engineering teams & on-call", "icon": "Cpu", "accent": "#2563eb",
        "identity": "engineering", "dashboardName": "Technology Workforce Command Center",
        "terminology": {"employee": "Engineer", "employees": "Engineers", "shift": "Work block",
                        "assignment": "Project / rotation", "department": "Team", "departments": "Teams",
                        "skill": "Skill", "skills": "Skills", "manager": "Engineering manager",
                        "disruption": "Capacity disruption", "organization": "Company"},
        "kpis": [kpi("project_coverage", "Project Coverage", "coverage_pct", "percent", "high", "Project blocks staffed"),
                 kpi("skill_gaps", "Skill Gaps", "skill_gap_count", "count", "low", "Work needing a skill only 1 person has"),
                 kpi("capacity", "Developer Capacity", "available_staff", "ratio", "high", "Engineers available"),
                 kpi("oncall", "On-Call Coverage", "oncall_coverage_pct", "percent", "high", "On-call rotations staffed"),
                 kpi("deadline_risk", "Deadline Risk", "deadline_risk", "count", "low", "Deadline work affected by a disruption")],
        "subDashboards": [
            {"id": "eng_manager", "name": "Engineering Manager Dashboard", "audience": "Engineering managers",
             "widgets": ["department_coverage", "roster", "qualification_matrix", "fatigue_risk"]},
            {"id": "resources", "name": "Resource Management Dashboard", "audience": "Resource & delivery managers",
             "widgets": ["workload_balance", "overtime_by_person", "fairness_distribution", "disruption_history"]}],
        "constraintLabels": {"required_skills": "Required skills", "min_rest_hours": "Rest after on-call",
                             "max_daily_hours": "Daily capacity", "max_weekly_hours": "Weekly capacity",
                             "overtime": "Extra hours", "priority": "Release criticality"},
        "riskIndicators": [{"id": "deadline", "label": "Deadline work at risk", "metric": "deadline_risk"},
                           {"id": "burnout", "label": "On-call fatigue", "metric": "fatigue_risk_count"}],
        "recommendedActions": ["Pair the replacement with a payments reviewer", "Update the on-call schedule in PagerDuty",
                               "Re-check release 4.2 scope"],
        "recognition": {
            "categories": [
                rec("incident_support", "Incident Support", "Picked up a colleague's work or on-call at short notice", ["disruption_cover"], 20),
                rec("release_support", "Critical Delivery Support", "Covered critical or release-blocking work", ["critical_cover"], 10),
                rec("reliability", "Reliability", "Acknowledged changes promptly and gave early notice of absences",
                    ["prompt_acknowledgement", "advance_notice"], 5),
                rec("collaboration", "Collaboration", "Unblocked another team or paired generously"),
                rec("knowledge_sharing", "Knowledge Sharing", "Documentation, talks or mentoring"),
                rec("delivery_excellence", "Delivery Excellence", "Shipped high-quality work on time"),
            ],
            "tiers": tiers(("Recognized", "Shout-out in the engineering all-hands"),
                           ("Valued", "Learning budget top-up"),
                           ("Outstanding", "Spot bonus or an extra day off")),
        },
        "charts": ["department_coverage", "overtime_trend", "qualification_gaps"],
    },
    "logistics": {
        "label": "Logistics / Field Services", "tagline": "Fleets, routes & technicians", "icon": "Truck",
        "accent": "#be123c", "identity": "control", "dashboardName": "Field Operations Command Center",
        "terminology": {"employee": "Driver", "employees": "Drivers & technicians", "shift": "Run",
                        "assignment": "Route", "department": "Depot", "departments": "Depots", "skill": "License",
                        "skills": "Licenses", "manager": "Dispatcher", "disruption": "Driver unavailability",
                        "organization": "Fleet"},
        "kpis": [kpi("assignment_coverage", "Assignment Coverage", "coverage_pct", "percent", "high", "Routes with a driver"),
                 kpi("route_risk", "Route Risk", "route_risk", "count", "low", "Routes affected by an open disruption"),
                 kpi("drivers", "Driver Availability", "available_staff", "ratio", "high", "Drivers available"),
                 kpi("certs", "Certification Coverage", "skill_coverage_pct", "percent", "high", "Routes driven with all required licenses"),
                 kpi("overtime", "Overtime", "overtime_hours", "hours", "low", "Driving hours above contracted")],
        "subDashboards": [
            {"id": "dispatch", "name": "Dispatch Dashboard", "audience": "Dispatchers",
             "widgets": ["department_coverage", "roster", "qualification_matrix", "fatigue_risk"]},
            {"id": "resources", "name": "Resource Management Dashboard", "audience": "Fleet managers",
             "widgets": ["overtime_by_person", "fairness_distribution", "disruption_history", "compliance"]}],
        "constraintLabels": {"required_skills": "License & permits", "min_rest_hours": "Rest between runs",
                             "max_daily_hours": "Daily driving limit", "max_weekly_hours": "Weekly driving limit",
                             "overtime": "Overtime cap", "priority": "Delivery-window criticality"},
        "riskIndicators": [{"id": "hazmat", "label": "Hazmat routes at risk", "metric": "route_risk"},
                           {"id": "fatigue", "label": "Driver fatigue", "metric": "fatigue_risk_count"}],
        "recommendedActions": ["Confirm the tanker handover at North Depot", "Notify the customer of the driver change",
                               "Check the replacement's hazmat permit expiry"],
        "recognition": {
            "categories": [
                rec("peak_coverage", "Peak Coverage", "Covered a colleague's run at short notice", ["disruption_cover"], 20),
                rec("delivery_reliability", "Delivery Reliability", "Kept a critical delivery on schedule", ["critical_cover"], 10),
                rec("dependability", "Schedule Dependability", "Acknowledged changes promptly and gave early notice of absences",
                    ["prompt_acknowledgement", "advance_notice"], 5),
                rec("safety", "Road Safety", "Incident-free driving or a safety report"),
                rec("customer_service", "Customer Service", "Praised by a customer"),
                rec("skill_development", "Skill Development", "New licence, permit or certification"),
            ],
            "tiers": tiers(("Recognized", "Depot recognition board"),
                           ("Valued", "Preferred route or run pattern next month"),
                           ("Outstanding", "Fuel card or spot award")),
        },
        "charts": ["department_coverage", "overtime_trend", "qualification_gaps"],
    },
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for did, cfg in DOMAINS.items():
        data = {"id": did, **cfg, "commonKpis": COMMON_KPIS, "demoDataset": f"shared/demo-data/{did}.json"}
        (OUT / f"{did}.json").write_text(json.dumps(data, indent=2) + "\n")
        index.append({"id": did, "label": cfg["label"], "tagline": cfg["tagline"], "icon": cfg["icon"],
                      "accent": cfg["accent"], "dashboardName": cfg["dashboardName"]})
    (OUT / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    print("wrote", len(DOMAINS), "domain configs")
