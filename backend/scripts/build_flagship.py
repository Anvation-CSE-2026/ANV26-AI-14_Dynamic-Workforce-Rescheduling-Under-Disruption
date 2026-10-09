"""Build the flagship demo: a 100-person hospital week that tells the whole ResQWork story.

    python -m scripts.build_flagship      → shared/scenarios/flagship-hospital-100.json

Story (reference "now": Thu 2026-10-08 07:30):
* Kavya Rao (ICU, ventilator-trained) calls in sick for Fri 09 ICU Ventilator Bay 07:00–15:00.
* Ventilator-trained ICU nurses: Arjun Menon (40h this week, 8 extra covers in the last 30 days),
  Meera Pillai (32h, 2 extra covers), Sunil Varma (would go into overtime), Farah Khan (night shift
  ending 07:00 on the 9th → rest rule), Leela Iyer (approved leave on the 9th).
  → hard constraints remove Farah and Leela; CP-SAT/exact search finds three feasible repairs;
    fairness prefers Meera over Arjun.
* Sat 10 "Emergency Surge Team" 07:00–19:00 needs 5 people; 3 are rostered → staffing gap of 2 →
  request additional workforce → eligible ER nurses volunteer → admin approves → completion → reward.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "shared" / "scenarios" / "flagship-hospital-100.json"

FIRST = ["Aarav", "Diya", "Ishaan", "Ananya", "Vihaan", "Saanvi", "Aditya", "Kiara", "Reyansh", "Myra", "Arnav",
         "Aadhya", "Kabir", "Anika", "Dhruv", "Riya", "Krishna", "Pari", "Shaurya", "Navya", "Atharv", "Ira",
         "Vivaan", "Tara", "Rudra", "Avni", "Ayaan", "Siya", "Yash", "Meher", "Om", "Nitya", "Pranav", "Zara",
         "Karthik", "Lavanya", "Nikhil", "Pooja", "Rahul", "Sneha", "Tanvi", "Uday", "Varun", "Gauri", "Harsh",
         "Jaya", "Kunal", "Lakshmi", "Manav", "Nisha"]
LAST = ["Sharma", "Reddy", "Nair", "Iyer", "Gupta", "Kulkarni", "Joshi", "Patel", "Bhat", "Rao", "Shetty",
        "Hegde", "Desai", "Menon", "Pillai", "Chopra", "Kapoor", "Bose", "Das", "Mishra"]

DEPTS = {  # id: (name, staff, skills, certs, headcount per Day/Evening/Night, priority)
    "ICU": ("Intensive Care Unit", 20, ["RN", "ICU Care"], ["ACLS"], (3, 3, 2), "critical"),
    "ER": ("Emergency Department", 20, ["RN", "Emergency Care"], ["BLS"], (3, 3, 2), "high"),
    "WARD": ("General Ward", 30, ["RN", "Ward Care"], ["BLS"], (4, 4, 3), "normal"),
    "PAEDS": ("Paediatrics", 15, ["RN", "Paediatric Care"], ["PALS"], (2, 2, 1), "high"),
    "OT": ("Operating Theatre", 15, ["RN", "Theatre"], ["BLS"], (3, 2, 0), "high"),
}
TYPES = (("Day", "07:00", "15:00"), ("Evening", "15:00", "23:00"), ("Night", "23:00", "07:00"))
DAYS = [date(2026, 10, 5) + timedelta(days=i) for i in range(7)]   # Mon 05 → Sun 11
REF = "2026-10-08"

# Named story people (ICU unless stated)
STORY = {"ICU01": "Kavya Rao", "ICU02": "Arjun Menon", "ICU03": "Meera Pillai", "ICU04": "Sunil Varma",
         "ICU05": "Farah Khan", "ICU06": "Leela Iyer", "ER01": "Rohan Das", "ER02": "Neha Kulkarni",
         "ER03": "Imran Shaikh"}


def build() -> dict:
    employees, shifts, schedule = [], [], []
    names = iter(f"{f} {l}" for l in LAST for f in FIRST)
    used = set(STORY.values())
    for dept, (_, n, skills, certs, _, _) in DEPTS.items():
        for i in range(1, n + 1):
            eid = f"{dept}{i:02d}"
            name = STORY.get(eid) or next(x for x in names if x not in used)
            used.add(name)
            first = name.split()[0].lower()
            e = {"id": eid, "name": name, "role": f"{DEPTS[dept][0].split()[0]} Nurse" if dept != "OT" else "Theatre Nurse",
                 "department": dept, "email": f"{first}.{eid.lower()}@flagship.demo",
                 "phone": f"+91 98{eid[-2:]}{len(dept)} {10000 + i * 37:05d}"[:17], "skills": list(skills),
                 "certifications": list(certs), "contracted_weekly_hours": 36 if i % 3 else 40,
                 "max_weekly_hours": 48, "max_daily_hours": 12, "location": "Main Campus",
                 "history": {"disruptions_absorbed_30d": 0, "schedule_changes_30d": 0, "overtime_hours_30d": 0,
                             "contributions": []}}
            employees.append(e)
    emp = {e["id"]: e for e in employees}

    # ventilator-trained ICU nurses (the only people who can take the ventilator bay)
    for eid in ("ICU01", "ICU02", "ICU03", "ICU04", "ICU05", "ICU06"):
        emp[eid]["skills"].append("Ventilator")
    emp["ICU02"]["history"]["contributions"] = [
        {"date": f"2026-{m}", "kind": "volunteer", "hours": 8, "completed": True, "ref": f"hist-a-{i}"}
        for i, m in enumerate(["10-06", "10-03", "10-01", "09-28", "09-25", "09-22", "09-18", "09-14"])]
    emp["ICU03"]["history"]["contributions"] = [
        {"date": d, "kind": "volunteer", "hours": 8, "completed": True, "ref": f"hist-b-{i}"}
        for i, d in enumerate(["2026-09-30", "2026-09-16"])]
    emp["ICU04"].update(contracted_weekly_hours=36, max_weekly_hours=48)
    emp["ICU02"].update(contracted_weekly_hours=48, max_weekly_hours=56)     # senior full-time: no overtime issue
    emp["ICU03"].update(contracted_weekly_hours=40, max_weekly_hours=48)
    emp["ER02"]["history"]["contributions"] = [
        {"date": d, "kind": "additional", "hours": 8, "completed": True, "ref": f"hist-er-{i}"}
        for i, d in enumerate(["2026-10-04", "2026-09-29", "2026-09-21", "2026-09-12"])]
    emp["ER03"]["history"]["contributions"] = [
        {"date": "2026-07-02", "kind": "volunteer", "hours": 12, "completed": True, "ref": "hist-er-old"}] * 1
    # a few people elsewhere with recent extra work, so the fairness column isn't all zeros
    for k, eid in enumerate(["WARD03", "WARD11", "PAEDS04", "OT07", "ER09", "ICU12"]):
        emp[eid]["history"]["disruptions_absorbed_30d"] = 1 + k % 2

    def add(sid, d, typ, start, end, dept, assignment, eid, extra_skills=(), priority=None, attrs=None):
        _, _, skills, certs, _, prio = DEPTS[dept]
        shifts.append({"id": sid, "date": d, "start": start, "end": end, "assignment": assignment, "department": dept,
                       "shift_type": typ, "required_skills": list(skills) + list(extra_skills),
                       "required_certifications": list(certs), "priority": priority or prio,
                       "location": "Main Campus", "attributes": attrs or {}})
        if eid:
            schedule.append({"shift_id": sid, "employee_id": eid})

    # fixed story shifts first
    hours: dict[str, list[tuple[str, str, str]]] = {e: [] for e in emp}

    def book(eid, d, start, end):
        hours[eid].append((d, start, end))

    story = [("ICU01", "2026-10-09", "Day"), ("ICU02", "2026-10-05", "Day"), ("ICU02", "2026-10-06", "Day"),
             ("ICU02", "2026-10-07", "Day"), ("ICU02", "2026-10-08", "Day"), ("ICU02", "2026-10-11", "Evening"),
             ("ICU03", "2026-10-05", "Evening"), ("ICU03", "2026-10-06", "Evening"), ("ICU03", "2026-10-07", "Evening"),
             ("ICU03", "2026-10-10", "Day"),
             ("ICU04", "2026-10-05", "Day"), ("ICU04", "2026-10-06", "Day"), ("ICU04", "2026-10-07", "Day"),
             ("ICU04", "2026-10-08", "Day"), ("ICU04", "2026-10-10", "Evening"),
             ("ICU05", "2026-10-08", "Night"), ("ICU01", "2026-10-06", "Day")]
    for eid in ("ER10", "ER11", "ER12"):          # rostered on the 12-hour surge team on Sat 10
        book(eid, "2026-10-10", "07:00", "19:00")
    taken: dict[tuple[str, str, str], list[str]] = {}
    for eid, d, typ in story:
        taken.setdefault(("ICU", d, typ), []).append(eid)
    for d in DAYS:
        ds = d.isoformat()
        for dept, (_, _, _, _, heads, _) in DEPTS.items():
            pool = [e for e in emp if emp[e]["department"] == dept]
            for (typ, start, end), need in zip(TYPES, heads):
                chosen = list(taken.get((dept, ds, typ), []))
                for eid in sorted(pool, key=lambda e: (len(hours[e]), e)):
                    if len(chosen) >= need:
                        break
                    if eid in chosen or eid in STORY or not _free(hours[eid], ds, start, end):
                        continue
                    chosen.append(eid)
                for k, eid in enumerate(chosen[:max(need, len(chosen))]):
                    sid = f"{dept}-{typ[0]}-{ds[5:7]}{ds[8:]}-{k + 1}"
                    special = dept == "ICU" and eid == "ICU01" and ds == "2026-10-09"
                    add(sid, ds, typ, start, end, dept, "ICU Ventilator Bay" if special else f"{dept} {typ}", eid,
                        extra_skills=("Ventilator",) if special else ())
                    book(eid, ds, start, end)
    # emergency surge team: needs 5, three rostered
    for k, eid in enumerate(["ER10", "ER11", "ER12"]):
        add(f"SURGE-1010-{k + 1}", "2026-10-10", "Day", "07:00", "19:00", "ER", "Emergency Surge Team", eid,
            priority="critical", attrs={"required_headcount": 5})
    raw = {
        "organization": {"id": "aster-flagship", "name": "Aster City Hospital (100 staff)", "domain": "healthcare",
                         "location": "Bengaluru", "timezone": "Asia/Kolkata", "size": "100 nursing staff"},
        "reference_date": REF, "reference_time": "07:30",
        "departments": [{"id": k, "name": v[0], "kind": "unit"} for k, v in DEPTS.items()],
        "skills": sorted({s for v in DEPTS.values() for s in v[2]} | {"Ventilator"}),
        "employees": employees, "shifts": shifts, "existing_schedule": schedule,
        "availability": [{"employee_id": "ICU06", "date": "2026-10-09", "kind": "leave", "reason": "approved leave"}],
        "disruptions": [{"id": "FLAG-ICU", "employee_id": "ICU01", "date": "2026-10-09", "start": "07:00",
                         "end": "15:00", "reason": "sick", "severity": "critical",
                         "label": "ICU ventilator nurse calls in sick"}],
        "constraints": {"min_rest_hours": 11, "allow_overtime": True, "max_overtime_hours_per_week": 12,
                        "fairness_window_days": 30},
    }
    return raw


def _free(booked: list[tuple[str, str, str]], d: str, start: str, end: str) -> bool:
    from core.models import interval
    s, e = interval(d, start, end)
    for bd, bs, be in booked:
        os_, oe = interval(bd, bs, be)
        gap = min(abs((s - oe).total_seconds()), abs((os_ - e).total_seconds())) / 3600
        if (s < oe and os_ < e) or gap < 11 or bd == d:
            return False
    return len(booked) < 5


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"wrote {OUT}: {len(data['employees'])} employees, {len(data['shifts'])} shifts")
