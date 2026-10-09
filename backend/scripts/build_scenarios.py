"""Build the small, hand-checkable scenario datasets in shared/scenarios/ (used by tests and for judging).

    python -m scripts.build_scenarios

repair-cases.json : double booking, unavailability, skill/certification mismatch, overtime trap, minimum change
infeasible-cnc.json: a shift nobody can legally cover; ResQWork must say so and explain why
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "shared" / "scenarios"
CNC, ASM, SL2 = "CNC Operation", "Assembly", "Safety Level 2"


def emp(i, name, role, skills, certs, contracted=40, max_weekly=48, dept="L1"):
    return {"id": i, "name": name, "role": role, "department": dept, "skills": skills, "certifications": certs,
            "contracted_weekly_hours": contracted, "max_weekly_hours": max_weekly, "max_daily_hours": 10,
            "history": {"disruptions_absorbed_30d": 0, "schedule_changes_30d": 0, "overtime_hours_30d": 0}}


def shift(i, date, start, end, assignment, skills, certs=(), priority="normal", dept="L1"):
    return {"id": i, "date": date, "start": start, "end": end, "assignment": assignment, "department": dept,
            "required_skills": list(skills), "required_certifications": list(certs), "priority": priority}


def base(org_id, name):
    return {"organization": {"id": org_id, "name": name, "domain": "manufacturing", "location": "Test plant",
                             "timezone": "Asia/Kolkata", "size": "1 line"},
            "reference_date": "2026-10-14", "reference_time": "00:00",
            "departments": [{"id": "L1", "name": "Line 1"}, {"id": "L2", "name": "Line 2"}],
            "skills": [CNC, ASM, SL2],
            "constraints": {"min_rest_hours": 11, "allow_overtime": True, "max_overtime_hours_per_week": 12}}


def repair_cases():
    d = base("scenario-repair", "Scenario Plant: repair cases")
    d["employees"] = [
        emp("E01", "Asha Rao", "CNC Operator", [CNC], [SL2]),
        emp("E02", "Bala Krishnan", "CNC Operator", [CNC, ASM], [SL2]),
        emp("E03", "Chitra Nair", "CNC Operator", [CNC], [SL2]),                    # the right replacement
        emp("E04", "Dev Patel", "CNC Operator", [CNC], []),                           # certification mismatch
        emp("E05", "Esha Menon", "Assembler", [ASM], [SL2], dept="L2"),               # skill mismatch for CNC
        emp("E06", "Farid Khan", "CNC Operator", [CNC], [SL2], contracted=32, max_weekly=48),  # overtime trap
        emp("E07", "Gita Shah", "Assembler", [ASM], [], dept="L2"),
    ]
    d["shifts"] = [
        # Mon/Tue (before "now"): Farid already has 32h this week → any extra shift is overtime
        *[shift(f"CNC-F-{day}", f"2026-10-{day}", "06:00", "14:00", "Line 1 · CNC (Farid)", [CNC], [SL2]) for day in (12, 13)],
        shift("CNC-F-14", "2026-10-14", "06:00", "14:00", "Line 1 · CNC (Farid)", [CNC], [SL2]),
        shift("CNC-F-15", "2026-10-15", "06:00", "14:00", "Line 1 · CNC (Farid)", [CNC], [SL2]),
        # Fri 16 Oct: the scenario day
        shift("CNC-A-16", "2026-10-16", "06:00", "14:00", "Line 1 · CNC Machining (Task A)", [CNC], [SL2], "critical"),
        shift("ASM-B-16", "2026-10-16", "08:00", "12:00", "Line 2 · Assembly (Task B)", [ASM], [], "normal", "L2"),
        shift("CNC-C-16", "2026-10-16", "06:00", "14:00", "Line 1 · CNC Machining (Task C)", [CNC], [SL2], "critical"),
        shift("ASM-D-16", "2026-10-16", "14:00", "22:00", "Line 2 · Assembly (evening)", [ASM], [], "normal", "L2"),
        shift("CNC-E-17", "2026-10-17", "06:00", "14:00", "Line 1 · CNC Machining", [CNC], [SL2], "high"),
    ]
    d["existing_schedule"] = [
        {"shift_id": "CNC-F-12", "employee_id": "E06"}, {"shift_id": "CNC-F-13", "employee_id": "E06"},
        {"shift_id": "CNC-F-14", "employee_id": "E06"}, {"shift_id": "CNC-F-15", "employee_id": "E06"},
        {"shift_id": "CNC-A-16", "employee_id": "E01"},
        {"shift_id": "ASM-B-16", "employee_id": "E02"},     # E02 double-booked: Task B overlaps Task C
        {"shift_id": "CNC-C-16", "employee_id": "E02"},
        {"shift_id": "ASM-D-16", "employee_id": "E07"},
        {"shift_id": "CNC-E-17", "employee_id": "E03"},
    ]
    d["disruptions"] = [{"id": "E01-out", "employee_id": "E01", "date": "2026-10-16", "start": "06:00", "end": "14:00",
                         "reason": "sick", "severity": "critical", "label": "E01 unavailable 06:00–14:00"}]
    return d


def infeasible():
    d = base("scenario-infeasible", "Scenario Plant: infeasible")
    d["employees"] = [
        emp("E01", "Asha Rao", "CNC Operator", [CNC], [SL2]),
        emp("E02", "Bala Krishnan", "CNC Operator", [CNC], [SL2]),
        emp("E03", "Chitra Nair", "CNC Trainee", [CNC], []),            # skill, but no certification
        emp("E04", "Dev Patel", "Assembler", [ASM], [SL2], dept="L2"),  # certification, but no CNC skill
        emp("E05", "Esha Menon", "Assembler", [ASM], [], dept="L2"),
    ]
    d["shifts"] = [
        shift("CNC-1-16", "2026-10-16", "06:00", "14:00", "Line 1 · CNC Machining", [CNC], [SL2], "critical"),
        shift("CNC-2-16", "2026-10-16", "06:00", "14:00", "Line 2 · CNC Machining (mandatory)", [CNC], [SL2], "critical", "L2"),
        shift("ASM-1-16", "2026-10-16", "06:00", "14:00", "Line 2 · Assembly", [ASM], [], "normal", "L2"),
    ]
    d["existing_schedule"] = [{"shift_id": "CNC-1-16", "employee_id": "E01"},
                              {"shift_id": "CNC-2-16", "employee_id": "E02"},
                              {"shift_id": "ASM-1-16", "employee_id": "E05"}]
    d["disruptions"] = [{"id": "E01-out", "employee_id": "E01", "date": "2026-10-16", "start": "06:00", "end": "14:00",
                         "reason": "sick", "severity": "critical", "label": "Only free CNC-certified operator unavailable"}]
    return d


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("repair-cases", repair_cases()), ("infeasible-cnc", infeasible())):
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")
        print("wrote", OUT / f"{name}.json")
