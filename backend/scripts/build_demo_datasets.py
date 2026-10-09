"""Generate the five demo datasets in shared/demo-data/ (canonical JSON format).

Run from backend/:  python -m scripts.build_demo_datasets

Every dataset is built around the same engineered situation so the demo
shows why an optimizer is needed, not just a lookup:
  * the obvious replacement just finished a night/late shift  → rest rule
  * another qualified person is already fully booked this week → overtime
  * a cross-trained person could move if someone backfills them → 2-step repair
  * a qualified person with a heavy recent-disruption history  → fairness trade-off
  * several people lack the required skill/certification       → coverage
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "shared" / "demo-data"

D_1, D0, D1, D2 = "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10"  # Wed, Thu (today), Fri, Sat


def emp(id, name, role, dept, skills, certs=(), contracted=40, cap=48, daily=12, hist=(0, 0, 0), prefs=None, **attrs):
    return {"id": id, "name": name, "role": role, "department": dept, "skills": list(skills),
            "certifications": list(certs), "contracted_weekly_hours": contracted, "max_weekly_hours": cap,
            "max_daily_hours": daily, "email": f"{name.split()[0].lower()}@demo.resqwork.app",
            "history": {"disruptions_absorbed_30d": hist[0], "schedule_changes_30d": hist[1],
                        "overtime_hours_30d": hist[2]},
            "preferences": prefs or {}, "attributes": attrs}


def tpl(assignment, dept, start, end, stype, skills=(), certs=(), priority="normal", **attrs):
    return {"assignment": assignment, "department": dept, "start": start, "end": end, "shift_type": stype,
            "required_skills": list(skills), "required_certifications": list(certs), "priority": priority,
            "attributes": attrs}


def build(org, departments, skills, employees, templates, roster, presets, constraints, ref_time, extra=None):
    shifts, schedule, counter = [], [], {}
    for day, tid, eid in roster:
        n = counter[(day, tid)] = counter.get((day, tid), 0) + 1
        sid = f"{tid}-{day[5:7]}{day[8:10]}-{n}"
        t = templates[tid]
        shifts.append({"id": sid, "date": day, **t})
        schedule.append({"shift_id": sid, "employee_id": eid})
    ds = {"organization": org, "reference_date": D0, "reference_time": ref_time,
          "departments": departments, "skills": skills, "employees": employees, "shifts": shifts,
          "existing_schedule": schedule, "availability": (extra or {}).get("availability", []),
          "disruptions": presets, "constraints": constraints,
          "optimization": {"minimum_change": True, "fairness": True, "skill_coverage": True, "overtime_penalty": True}}
    return ds


def R(day, tid, *eids):
    return [(day, tid, e) for e in eids]


# ---------------------------------------------------------------------------
# 1. Healthcare: St. Aster Hospital, ICU nurse unavailable
# ---------------------------------------------------------------------------

def healthcare():
    E = [
        emp("H01", "Rahul Sharma", "ICU Nurse", "ICU", ["RN", "ICU Care"], ["ACLS"], 36, 48, 12, (1, 1, 0)),
        emp("H02", "Priya Nair", "ICU Nurse", "ICU", ["RN", "ICU Care"], ["ACLS"], 36, 48, 12, (0, 1, 0)),
        emp("H03", "Elena Rostova", "ICU Nurse", "ICU", ["RN", "ICU Care"], ["ACLS"], 36, 48, 12, (1, 2, 4)),
        emp("H04", "Carlos Mendez", "ICU/ED Float Nurse", "ED", ["RN", "ICU Care", "ER Triage"], ["ACLS"], 36, 48, 12, (0, 1, 0)),
        emp("H05", "Hannah Schmidt", "ICU Nurse", "ICU", ["RN", "ICU Care"], ["ACLS"], 36, 48, 12, (0, 0, 0)),
        emp("H06", "Marcus Vance", "ER Nurse", "ED", ["RN", "ER Triage"], ["ACLS"], 36, 48, 12, (0, 0, 0)),
        emp("H07", "Aisha Patel", "ER Nurse", "ED", ["RN", "ER Triage"], ["ACLS"], 36, 48, 12, (1, 1, 0)),
        emp("H08", "David Chen", "ER Nurse", "ED", ["RN", "ER Triage"], ["ACLS"], 36, 48, 12, (0, 2, 0)),
        emp("H09", "Meera Iyer", "Ward Nurse", "WARD", ["RN"], [], 36, 48, 12, (0, 0, 0)),
        emp("H10", "Sanjay Rao", "Ward Nurse", "WARD", ["RN"], [], 36, 48, 12, (1, 0, 0)),
        emp("H11", "Grace Thomas", "Pediatric Nurse", "WARD", ["RN", "Pediatrics"], [], 36, 48, 12, (0, 0, 0)),
        emp("H12", "Arjun Mehta", "Ward Nurse", "WARD", ["RN"], [], 36, 48, 12, (0, 1, 0)),
        emp("H13", "Fatima Khan", "ER Nurse", "ED", ["RN", "ER Triage"], ["ACLS"], 36, 48, 12, (0, 0, 0)),
        emp("H14", "Kavya Reddy", "ICU Nurse", "ICU", ["RN", "ICU Care"], ["ACLS"], 36, 48, 12, (0, 0, 0)),
        emp("H15", "Rohan Gupta", "Ward Nurse", "WARD", ["RN"], [], 36, 48, 12, (0, 0, 0)),
        emp("H16", "Lisa Wong", "ER Nurse", "ED", ["RN", "ER Triage"], ["ACLS"], 36, 48, 12, (0, 0, 0)),
        emp("H17", "Neha Joshi", "ICU Nurse (Float)", "ICU", ["RN", "ICU Care"], ["ACLS"], 36, 48, 12, (3, 4, 10)),
    ]
    T = {
        "ICU-D": tpl("ICU Day", "ICU", "07:00", "19:00", "Day", ["RN", "ICU Care"], ["ACLS"], "critical", patient_care_level="critical"),
        "ICU-N": tpl("ICU Night", "ICU", "19:00", "07:00", "Night", ["RN", "ICU Care"], ["ACLS"], "critical", patient_care_level="critical"),
        "ED-D": tpl("Emergency Day", "ED", "07:00", "19:00", "Day", ["RN", "ER Triage"], ["ACLS"], "high"),
        "ED-N": tpl("Emergency Night", "ED", "19:00", "07:00", "Night", ["RN", "ER Triage"], [], "high"),
        "WARD-D": tpl("General Ward Day", "WARD", "07:00", "19:00", "Day", ["RN"]),
        "WARD-N": tpl("General Ward Night", "WARD", "19:00", "07:00", "Night", ["RN"]),
    }
    roster = (
        R(D_1, "ICU-D", "H05", "H02") + R(D_1, "ICU-N", "H14") + R(D_1, "ED-D", "H07", "H08") + R(D_1, "ED-N", "H13")
        + R(D_1, "WARD-D", "H09", "H12") + R(D_1, "WARD-N", "H15")
        + R(D0, "ICU-D", "H05", "H01") + R(D0, "ICU-N", "H03") + R(D0, "ED-D", "H06", "H16") + R(D0, "ED-N", "H13")
        + R(D0, "WARD-D", "H10", "H11") + R(D0, "WARD-N", "H15")
        + R(D1, "ICU-D", "H01", "H02") + R(D1, "ICU-N", "H14") + R(D1, "ED-D", "H04", "H07") + R(D1, "ED-N", "H08")
        + R(D1, "WARD-D", "H09", "H12") + R(D1, "WARD-N", "H10")
        + R(D2, "ICU-D", "H05", "H03") + R(D2, "ICU-N", "H17") + R(D2, "ED-D", "H16", "H06") + R(D2, "ED-N", "H13")
        + R(D2, "WARD-D", "H11", "H15") + R(D2, "WARD-N", "H12")
    )
    presets = [
        {"id": "DEMO-ICU", "employee_id": "H01", "date": D1, "start": "07:00", "end": "19:00", "reason": "sick",
         "severity": "critical", "label": "ICU nurse unavailable"},
        {"id": "DEMO-ED", "employee_id": "H07", "date": D1, "start": "07:00", "end": "19:00", "reason": "emergency",
         "severity": "high", "label": "ER nurse unavailable"},
        {"id": "DEMO-WARD", "employee_id": "H12", "date": D1, "start": "07:00", "end": "19:00", "reason": "leave",
         "severity": "medium", "label": "Ward nurse unavailable"},
    ]
    return build({"id": "st-aster", "name": "St. Aster Multispeciality Hospital", "domain": "healthcare",
                  "location": "Bengaluru", "timezone": "Asia/Kolkata", "size": "350 beds"},
                 [{"id": "ICU", "name": "Intensive Care Unit", "kind": "unit"},
                  {"id": "ED", "name": "Emergency Department", "kind": "unit"},
                  {"id": "WARD", "name": "General Ward", "kind": "unit"}],
                 ["RN", "ICU Care", "ER Triage", "Pediatrics", "ACLS"], E, T, roster, presets,
                 {"min_rest_hours": 11, "allow_overtime": True, "max_overtime_hours_per_week": 12,
                  "extra": {"minimum_nurse_ratio_icu": "1:2"}}, "20:00")


# ---------------------------------------------------------------------------
# 2. Manufacturing: Vega Precision Components, CNC operator unavailable
# ---------------------------------------------------------------------------

def manufacturing():
    E = [
        emp("M01", "Ravi Kumar", "CNC Operator", "L1", ["CNC Operation"], ["Safety Level 2"], hist=(1, 1, 0), daily=10),
        emp("M02", "Suresh Pillai", "CNC Operator", "L1", ["CNC Operation"], ["Safety Level 2"], hist=(0, 1, 6), daily=10),
        emp("M03", "Anil Deshmukh", "Senior Operator", "L2", ["CNC Operation", "Assembly"], ["Safety Level 2"], daily=10),
        emp("M04", "Kiran Bhat", "CNC Operator", "L1", ["CNC Operation"], ["Safety Level 2"], daily=10),
        emp("M05", "Deepa Menon", "Assembly Technician", "L2", ["Assembly"], [], daily=10),
        emp("M06", "Farhan Ali", "Assembly Technician", "L2", ["Assembly"], [], daily=10, hist=(0, 2, 0)),
        emp("M07", "Lakshmi Nair", "Packaging Operator", "L3", ["Packaging", "Forklift"], [], daily=10),
        emp("M08", "Joseph D'Souza", "Quality Inspector", "QC", ["Quality Inspection"], [], daily=10),
        emp("M09", "Pooja Shetty", "CNC Trainee", "L1", ["CNC Operation"], [], daily=10),
        emp("M10", "Vinod Rao", "Assembly Technician", "L2", ["Assembly"], [], daily=10),
        emp("M11", "Sunita Verma", "Packaging Operator", "L3", ["Packaging"], [], daily=10),
        emp("M12", "Mohan Das", "CNC Operator", "L1", ["CNC Operation"], ["Safety Level 2"], daily=10, hist=(3, 5, 12)),
        emp("M13", "Rekha Iyer", "Quality Inspector", "QC", ["Quality Inspection", "Assembly"], [], daily=10),
        emp("M14", "Ajay Singh", "Maintenance Tech", "MAINT", ["Maintenance", "CNC Operation"], [], daily=10),
        emp("M15", "Harish Gowda", "CNC Operator", "L1", ["CNC Operation"], ["Safety Level 2"], daily=10),
    ]
    T = {
        "CNC-A": tpl("Line 1 · CNC Machining (Shift A)", "L1", "06:00", "14:00", "Shift A", ["CNC Operation"], ["Safety Level 2"], "critical", machine="HAAS VF-4"),
        "CNC-B": tpl("Line 1 · CNC Machining (Shift B)", "L1", "14:00", "22:00", "Shift B", ["CNC Operation"], ["Safety Level 2"], "critical", machine="HAAS VF-4"),
        "CNC-C": tpl("Line 1 · CNC Machining (Shift C)", "L1", "22:00", "06:00", "Shift C", ["CNC Operation"], ["Safety Level 2"], "high", machine="HAAS VF-4"),
        "ASM-A": tpl("Line 2 · Assembly (Shift A)", "L2", "06:00", "14:00", "Shift A", ["Assembly"], [], "high"),
        "ASM-B": tpl("Line 2 · Assembly (Shift B)", "L2", "14:00", "22:00", "Shift B", ["Assembly"]),
        "PKG-A": tpl("Line 3 · Packaging (Shift A)", "L3", "06:00", "14:00", "Shift A", ["Packaging", "Forklift"]),
        "QC-A": tpl("Quality Control (Shift A)", "QC", "06:00", "14:00", "Shift A", ["Quality Inspection"], [], "high"),
    }
    roster = (
        R(D_1, "CNC-A", "M04", "M01") + R(D_1, "CNC-B", "M12") + R(D_1, "CNC-C", "M02") + R(D_1, "ASM-A", "M05", "M06")
        + R(D_1, "ASM-B", "M10") + R(D_1, "PKG-A", "M07") + R(D_1, "QC-A", "M08")
        + R(D0, "CNC-A", "M04", "M01") + R(D0, "CNC-B", "M12") + R(D0, "CNC-C", "M02") + R(D0, "ASM-A", "M03", "M06")
        + R(D0, "ASM-B", "M10") + R(D0, "PKG-A", "M07") + R(D0, "QC-A", "M13")
        + R(D1, "CNC-A", "M01", "M15") + R(D1, "CNC-B", "M12") + R(D1, "CNC-C", "M02") + R(D1, "ASM-A", "M03", "M06")
        + R(D1, "ASM-B", "M10") + R(D1, "PKG-A", "M07") + R(D1, "QC-A", "M08")
        + R(D2, "CNC-A", "M15", "M01") + R(D2, "ASM-A", "M05", "M03") + R(D2, "PKG-A", "M07") + R(D2, "QC-A", "M13")
    )
    # Kiran (M04) is fully booked this week: give him two extra A shifts earlier in the week
    roster += [("2026-10-05", "CNC-A", "M04"), ("2026-10-06", "CNC-A", "M04")]
    presets = [
        {"id": "DEMO-CNC", "employee_id": "M01", "date": D1, "start": "06:00", "end": "14:00", "reason": "sick",
         "severity": "critical", "label": "CNC operator unavailable"},
        {"id": "DEMO-ASM", "employee_id": "M06", "date": D1, "start": "06:00", "end": "14:00", "reason": "personal",
         "severity": "high", "label": "Assembly technician unavailable"},
    ]
    return build({"id": "vega", "name": "Vega Precision Components", "domain": "manufacturing",
                  "location": "Peenya, Bengaluru", "timezone": "Asia/Kolkata", "size": "3 lines"},
                 [{"id": "L1", "name": "Line 1 · CNC", "kind": "line"}, {"id": "L2", "name": "Line 2 · Assembly", "kind": "line"},
                  {"id": "L3", "name": "Line 3 · Packaging", "kind": "line"}, {"id": "QC", "name": "Quality Control", "kind": "line"},
                  {"id": "MAINT", "name": "Maintenance", "kind": "line"}],
                 ["CNC Operation", "Assembly", "Packaging", "Forklift", "Quality Inspection", "Maintenance", "Safety Level 2"],
                 E, T, roster, presets, {"min_rest_hours": 11, "allow_overtime": True, "max_overtime_hours_per_week": 8,
                                         "extra": {"min_operators_per_line": 1}}, "23:00")


# ---------------------------------------------------------------------------
# 3. Education: Greenfield Public School, Mathematics teacher unavailable
# ---------------------------------------------------------------------------

def education():
    E = [
        emp("T01", "Anjali Rao", "Mathematics Teacher", "MATH", ["Mathematics"], ["B.Ed"], 24, 30, 5, (0, 1, 0), subjects=["Mathematics"]),
        emp("T02", "Vikram Joshi", "Mathematics Teacher", "MATH", ["Mathematics", "Physics"], ["B.Ed"], 24, 30, 5, (0, 0, 0), subjects=["Mathematics", "Physics"]),
        emp("T03", "Sneha Kulkarni", "Science Teacher", "SCI", ["Physics", "Chemistry"], ["B.Ed"], 24, 30, 5),
        emp("T04", "Rajesh Menon", "English Teacher", "ENG", ["English"], ["B.Ed"], 24, 30, 5),
        emp("T05", "Fatima Sheikh", "Mathematics Teacher", "MATH", ["Mathematics"], ["B.Ed"], 24, 30, 5, (3, 4, 0)),
        emp("T06", "Arvind Nair", "Biology Teacher", "SCI", ["Biology", "Chemistry"], ["B.Ed"], 24, 30, 5),
        emp("T07", "Meenakshi Iyer", "English Teacher", "ENG", ["English", "History"], ["B.Ed"], 24, 30, 5),
        emp("T08", "Rohit Sinha", "Social Studies Teacher", "SOC", ["History", "Geography"], ["B.Ed"], 24, 30, 5),
        emp("T09", "Kavitha Reddy", "Substitute Teacher", "POOL", ["Mathematics", "English"], ["B.Ed"], 24, 30, 5, (0, 0, 0)),
        emp("T10", "Daniel Mathew", "Computer Science Teacher", "SCI", ["Computer Science", "Mathematics"], [], 24, 30, 5),
    ]
    T = {}
    classes = ["8A", "8B", "9A", "9B"]
    periods = [("P1", "08:00", "09:00"), ("P2", "09:00", "10:00"), ("P3", "10:15", "11:15"),
               ("P4", "11:15", "12:15"), ("P5", "13:00", "14:00")]
    plan = {  # (class, period) -> (subject, teacher) for Friday
        ("8A", "P1"): ("Mathematics", "T01"), ("8A", "P2"): ("English", "T04"), ("8A", "P3"): ("Physics", "T03"),
        ("8A", "P4"): ("History", "T08"), ("8A", "P5"): ("Computer Science", "T10"),
        ("8B", "P1"): ("English", "T07"), ("8B", "P2"): ("Mathematics", "T05"), ("8B", "P3"): ("Biology", "T06"),
        ("8B", "P4"): ("Mathematics", "T01"), ("8B", "P5"): ("Geography", "T08"),
        ("9A", "P1"): ("Physics", "T02"), ("9A", "P2"): ("Chemistry", "T03"), ("9A", "P3"): ("Mathematics", "T01"),
        ("9A", "P4"): ("English", "T04"), ("9A", "P5"): ("Mathematics", "T05"),
        ("9B", "P1"): ("Biology", "T06"), ("9B", "P2"): ("Mathematics", "T02"), ("9B", "P3"): ("English", "T07"),
        ("9B", "P4"): ("Chemistry", "T03"), ("9B", "P5"): ("History", "T07"),
    }
    roster = []
    for (cls, per), (subject, teacher) in plan.items():
        start, end = next((s, e) for p, s, e in periods if p == per)
        tid = f"{cls}-{per}"
        T[tid] = tpl(f"Class {cls} · {subject} ({per})", "MATH" if subject == "Mathematics" else "SCI" if subject in
                     ("Physics", "Chemistry", "Biology", "Computer Science") else "ENG" if subject == "English" else "SOC",
                     start, end, per, [subject], [], "high" if cls.startswith("9") else "normal",
                     grade=cls[0], section=cls[1], classroom=f"Room {cls}", subject=subject)
        roster += R(D1, tid, teacher)
    # earlier-this-week load so weekly limits matter (Thursday teaching blocks)
    for tid_, (subj, start, end, teacher) in {
        "THU-AM-T02": ("Mathematics", "08:00", "12:00", "T02"), "THU-AM-T09": ("English", "08:00", "11:00", "T09"),
        "THU-AM-T05": ("Mathematics", "08:00", "12:15", "T05")}.items():
        T[tid_] = tpl(f"Thursday block · {subj}", "MATH", start, end, "Block", [subj])
        roster += R(D0, tid_, teacher)
    presets = [
        {"id": "DEMO-MATH", "employee_id": "T01", "date": D1, "reason": "sick", "severity": "high",
         "label": "Mathematics teacher unavailable"},
        {"id": "DEMO-ENG", "employee_id": "T04", "date": D1, "reason": "leave", "severity": "medium",
         "label": "English teacher unavailable"},
    ]
    return build({"id": "greenfield", "name": "Greenfield Public School", "domain": "education", "location": "Mysuru",
                  "timezone": "Asia/Kolkata", "size": "1,200 students"},
                 [{"id": "MATH", "name": "Mathematics", "kind": "department"}, {"id": "SCI", "name": "Science", "kind": "department"},
                  {"id": "ENG", "name": "English", "kind": "department"}, {"id": "SOC", "name": "Social Studies", "kind": "department"},
                  {"id": "POOL", "name": "Substitute Pool", "kind": "department"}],
                 ["Mathematics", "Physics", "Chemistry", "Biology", "English", "History", "Geography", "Computer Science"],
                 E, T, roster, presets, {"min_rest_hours": 0, "allow_overtime": False, "max_overtime_hours_per_week": 0,
                                         "extra": {"max_periods_per_day": 5}}, "07:30")


# ---------------------------------------------------------------------------
# 4. Technology: Nimbus Pay, backend engineer unavailable
# ---------------------------------------------------------------------------

def technology():
    E = [
        emp("E01", "Rohit Verma", "Senior Backend Engineer", "PAY", ["Python", "Payments Domain", "PostgreSQL"], [], hist=(0, 1, 2), programming_languages=["Python", "Go"]),
        emp("E02", "Sara Thomas", "Backend Engineer", "PAY", ["Python", "Payments Domain", "Go"], ["On-call Certified"], hist=(1, 1, 6)),
        emp("E03", "Vikram Shah", "Backend Engineer", "SEARCH", ["Python", "Payments Domain", "Elasticsearch"], ["On-call Certified"]),
        emp("E04", "Ananya Gupta", "Backend Engineer", "SEARCH", ["Python", "Elasticsearch"], []),
        emp("E05", "Kunal Mehra", "Staff Engineer", "PAY", ["Python", "Payments Domain", "Go", "PostgreSQL"], ["On-call Certified"], hist=(0, 0, 0)),
        emp("E06", "Divya Saxena", "Frontend Engineer", "WEB", ["React", "TypeScript"], []),
        emp("E07", "Arjun Pillai", "SRE", "PLAT", ["Kubernetes", "AWS", "Python"], ["On-call Certified"]),
        emp("E08", "Neha Kapoor", "Backend Engineer", "PAY", ["Python", "Payments Domain"], [], hist=(4, 5, 14)),
        emp("E09", "Imran Qureshi", "SRE", "PLAT", ["Kubernetes", "AWS", "Go", "Python"], ["On-call Certified"]),
        emp("E10", "Priyanka Das", "QA Engineer", "PAY", ["Test Automation", "Python"], []),
        emp("E11", "Tom Fernandes", "Frontend Engineer", "WEB", ["React", "TypeScript", "Node.js"], []),
        emp("E12", "Meghna Rao", "Data Engineer", "DATA", ["Python", "Spark", "PostgreSQL"], []),
    ]
    T = {
        "PAY": tpl("Payments API · Release 4.2 build", "PAY", "09:00", "17:00", "Day", ["Python", "Payments Domain"], [], "critical", project="Payments API", deadline="2026-10-10"),
        "SRCH": tpl("Search Service · Indexing sprint", "SEARCH", "09:00", "17:00", "Day", ["Python", "Elasticsearch"], [], "normal", project="Search Service"),
        "WEB": tpl("Checkout UI · Sprint 18", "WEB", "10:00", "18:00", "Day", ["React", "TypeScript"], [], "normal", project="Checkout UI"),
        "OC1": tpl("Primary on-call (evening)", "PLAT", "17:00", "01:00", "On-call", ["Python"], ["On-call Certified"], "critical", on_call=True),
        "PLAT": tpl("Platform · Kubernetes upgrade", "PLAT", "09:00", "17:00", "Day", ["Kubernetes"], [], "high", project="K8s 1.31"),
        "DATA": tpl("Data · Settlement pipeline", "DATA", "09:00", "17:00", "Day", ["Python", "Spark"], [], "normal", project="Settlements"),
        "QA": tpl("Payments API · Regression testing", "PAY", "09:00", "17:00", "Day", ["Test Automation"], [], "high", project="Payments API"),
    }
    roster = (
        R(D0, "PAY", "E01", "E08") + R(D0, "SRCH", "E03", "E04") + R(D0, "WEB", "E06", "E11") + R(D0, "OC1", "E02")
        + R(D0, "PLAT", "E07") + R(D0, "DATA", "E12") + R(D0, "QA", "E10")
        + R(D1, "PAY", "E01", "E08") + R(D1, "SRCH", "E03", "E04") + R(D1, "WEB", "E06", "E11") + R(D1, "OC1", "E09")
        + R(D1, "PLAT", "E07") + R(D1, "DATA", "E12") + R(D1, "QA", "E10")
    )
    # Kunal is booked on architecture reviews all week (fully loaded)
    T["ARCH"] = tpl("Architecture review board", "PAY", "09:00", "17:00", "Day", ["Payments Domain"])
    roster += [("2026-10-05", "ARCH", "E05"), ("2026-10-06", "ARCH", "E05"), (D_1, "ARCH", "E05"), (D0, "ARCH", "E05"),
               (D2, "ARCH", "E05")]
    presets = [
        {"id": "DEMO-BACKEND", "employee_id": "E01", "date": D1, "start": "09:00", "end": "17:00", "reason": "sick",
         "severity": "critical", "label": "Backend engineer unavailable"},
        {"id": "DEMO-ONCALL", "employee_id": "E09", "date": D1, "start": "17:00", "end": "01:00", "reason": "personal",
         "severity": "critical", "label": "On-call engineer unavailable"},
    ]
    return build({"id": "nimbus", "name": "Nimbus Pay", "domain": "technology", "location": "Bengaluru",
                  "timezone": "Asia/Kolkata", "size": "120 engineers"},
                 [{"id": "PAY", "name": "Payments", "kind": "team"}, {"id": "SEARCH", "name": "Search", "kind": "team"},
                  {"id": "WEB", "name": "Web", "kind": "team"}, {"id": "PLAT", "name": "Platform & SRE", "kind": "team"},
                  {"id": "DATA", "name": "Data", "kind": "team"}],
                 ["Python", "Go", "Payments Domain", "PostgreSQL", "Elasticsearch", "React", "TypeScript", "Kubernetes",
                  "AWS", "Spark", "Test Automation", "On-call Certified"],
                 E, T, roster, presets, {"min_rest_hours": 10, "allow_overtime": True, "max_overtime_hours_per_week": 8,
                                         "extra": {"on_call_rotation": "weekly"}}, "18:00")


# ---------------------------------------------------------------------------
# 5. Logistics: SwiftRoute Logistics, driver unavailable
# ---------------------------------------------------------------------------

def logistics():
    E = [
        emp("L01", "Ramesh Gowda", "Heavy Vehicle Driver", "NORTH", ["HMV License", "Hazmat"], ["Hazmat Permit"], hist=(0, 1, 2), license_type="HMV", vehicle_type="Tanker"),
        emp("L02", "Imran Pasha", "Heavy Vehicle Driver", "NORTH", ["HMV License", "Hazmat"], ["Hazmat Permit"], license_type="HMV"),
        emp("L03", "Joseph Fernandes", "Heavy Vehicle Driver", "SOUTH", ["HMV License", "Hazmat"], ["Hazmat Permit"], license_type="HMV"),
        emp("L04", "Pradeep Shetty", "Heavy Vehicle Driver", "SOUTH", ["HMV License"], [], license_type="HMV"),
        emp("L05", "Venkatesh Murthy", "Heavy Vehicle Driver", "NORTH", ["HMV License", "Hazmat"], ["Hazmat Permit"], license_type="HMV"),
        emp("L06", "Salma Begum", "Light Vehicle Driver", "CITY", ["LMV License"], [], license_type="LMV"),
        emp("L07", "Arun Kumar", "Light Vehicle Driver", "CITY", ["LMV License"], [], license_type="LMV", hist=(0, 2, 0)),
        emp("L08", "Naveen Raj", "Field Technician", "CITY", ["LMV License", "Cold Chain"], [], license_type="LMV"),
        emp("L09", "Kiran Patil", "Heavy Vehicle Driver", "SOUTH", ["HMV License"], [], license_type="HMV"),
        emp("L10", "Ganesh Rao", "Heavy Vehicle Driver", "NORTH", ["HMV License", "Hazmat"], ["Hazmat Permit"], hist=(3, 4, 10), license_type="HMV"),
        emp("L11", "Divya Hegde", "Light Vehicle Driver", "CITY", ["LMV License", "Cold Chain"], [], license_type="LMV"),
        emp("L12", "Suresh Babu", "Heavy Vehicle Driver", "SOUTH", ["HMV License"], [], license_type="HMV"),
    ]
    T = {
        "R21": tpl("Route R-21 · Hosur fuel run (hazmat)", "NORTH", "06:00", "14:00", "Morning", ["HMV License", "Hazmat"], ["Hazmat Permit"], "critical", route="R-21", vehicle="Tanker KA-05-T-221", delivery_window="08:00–12:00"),
        "R12": tpl("Route R-12 · Whitefield distribution", "SOUTH", "07:00", "15:00", "Morning", ["HMV License"], [], "high", route="R-12", vehicle="Truck KA-03-B-112"),
        "R07": tpl("Route R-07 · Electronic City parcels", "CITY", "08:00", "16:00", "Morning", ["LMV License"], [], "normal", route="R-07", vehicle="Van KA-01-V-707"),
        "R30": tpl("Route R-30 · Pharma cold chain", "CITY", "09:00", "17:00", "Day", ["LMV License", "Cold Chain"], [], "high", route="R-30", vehicle="Reefer KA-01-R-030"),
        "N21": tpl("Route N-21 · Overnight linehaul (hazmat)", "NORTH", "22:00", "06:00", "Night", ["HMV License", "Hazmat"], ["Hazmat Permit"], "high", route="N-21", vehicle="Tanker KA-05-T-219"),
        "R15": tpl("Route R-15 · Tumkur Road industrial", "SOUTH", "14:00", "22:00", "Evening", ["HMV License"], [], "normal", route="R-15"),
    }
    roster = (
        R(D0, "R21", "L01") + R(D0, "R12", "L03", "L09") + R(D0, "R07", "L06") + R(D0, "R30", "L08") + R(D0, "N21", "L02")
        + R(D0, "R15", "L12")
        + R(D1, "R21", "L01") + R(D1, "R12", "L03", "L09") + R(D1, "R07", "L07") + R(D1, "R30", "L11") + R(D1, "N21", "L10")
        + R(D1, "R15", "L04")
        + R(D2, "R21", "L05") + R(D2, "R12", "L09", "L12") + R(D2, "R07", "L06")
    )
    # Venkatesh has driven long runs all week
    for d in ("2026-10-05", "2026-10-06", D_1, D0):
        roster.append((d, "R21" if d != D0 else "R15", "L05"))
    presets = [
        {"id": "DEMO-DRIVER", "employee_id": "L01", "date": D1, "start": "06:00", "end": "14:00", "reason": "sick",
         "severity": "critical", "label": "Driver unavailable"},
        {"id": "DEMO-COLD", "employee_id": "L11", "date": D1, "start": "09:00", "end": "17:00", "reason": "personal",
         "severity": "high", "label": "Cold-chain driver unavailable"},
    ]
    return build({"id": "swiftroute", "name": "SwiftRoute Logistics", "domain": "logistics", "location": "Bengaluru",
                  "timezone": "Asia/Kolkata", "size": "60 vehicles"},
                 [{"id": "NORTH", "name": "North Depot · Yelahanka", "kind": "depot"},
                  {"id": "SOUTH", "name": "South Depot · Bommasandra", "kind": "depot"},
                  {"id": "CITY", "name": "City Hub · Koramangala", "kind": "depot"}],
                 ["HMV License", "LMV License", "Hazmat", "Cold Chain", "Hazmat Permit"],
                 E, T, roster, presets, {"min_rest_hours": 10, "allow_overtime": True, "max_overtime_hours_per_week": 8,
                                         "extra": {"max_driving_hours_per_day": 9}}, "23:00")


BUILDERS = {"healthcare": healthcare, "manufacturing": manufacturing, "education": education,
            "technology": technology, "logistics": logistics}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in BUILDERS.items():
        (OUT / f"{name}.json").write_text(json.dumps(fn(), indent=2) + "\n")
        print("wrote", name)
