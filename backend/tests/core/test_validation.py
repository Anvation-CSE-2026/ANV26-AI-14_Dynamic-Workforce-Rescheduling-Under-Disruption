import copy
import json
import unittest

from core.models import DOMAINS
from core.validation import dataset_from_csv, validate_dataset
from services.domains import demo_dataset


def minimal():
    return {
        "organization": {"name": "Test Org", "domain": "healthcare"},
        "employees": [
            {"id": "E1", "name": "Asha Rao", "role": "Nurse", "skills": ["RN"]},
            {"id": "E2", "name": "Ben Paul", "role": "Nurse", "skills": ["RN"]},
        ],
        "shifts": [
            {"id": "S1", "date": "2026-10-09", "start": "07:00", "end": "19:00", "assignment": "Ward Day",
             "required_skills": ["RN"]},
            {"id": "S2", "date": "2026-10-09", "start": "19:00", "end": "07:00", "assignment": "Ward Night",
             "required_skills": ["RN"]},
        ],
        "existing_schedule": [{"shift_id": "S1", "employee_id": "E1"}, {"shift_id": "S2", "employee_id": "E2"}],
    }


class DemoDatasets(unittest.TestCase):
    def test_every_demo_dataset_is_clean(self):
        for d in DOMAINS:
            rep = validate_dataset(demo_dataset(d))
            self.assertEqual(rep.status, "valid", (d, [f.message for f in rep.errors + rep.warnings]))
            self.assertGreaterEqual(len(rep.dataset.disruptions), 2, d)
            self.assertEqual(rep.dataset.organization.domain, d)


class JsonValidation(unittest.TestCase):
    def test_minimal_valid(self):
        rep = validate_dataset(minimal())
        self.assertEqual(rep.status, "valid")
        self.assertEqual(rep.stats["assignments"], 2)
        self.assertEqual(rep.dataset.shift("S2").hours, 12)   # overnight shift

    def test_unknown_domain_is_fatal(self):
        raw = minimal()
        raw["organization"]["domain"] = "space"
        rep = validate_dataset(raw)
        self.assertEqual(rep.status, "invalid")
        self.assertIn("one of healthcare", rep.errors[0].message)

    def test_bad_records_are_rejected_individually(self):
        raw = minimal()
        raw["employees"].append({"id": "E3", "role": "Nurse"})                       # missing name
        raw["employees"].append({"id": "E1", "name": "Dup", "role": "Nurse"})         # duplicate id
        raw["shifts"].append({"id": "S3", "date": "2026-10-09", "start": "25:00", "end": "07:00",
                              "assignment": "X"})                                     # invalid time
        raw["existing_schedule"].append({"shift_id": "S9", "employee_id": "E1"})      # unknown shift
        raw["existing_schedule"].append({"shift_id": "S1", "employee_id": "E2"})      # double assignment
        rep = validate_dataset(raw)
        self.assertEqual(rep.status, "valid_with_warnings")
        cats = {f.category for f in rep.errors}
        self.assertTrue({"missing_field", "duplicate", "invalid_shift", "unknown_reference"} <= cats, cats)
        self.assertEqual(rep.stats["employees"], 2)
        self.assertEqual(rep.dataset.assignment_map()["S1"], "E1")
        self.assertIn("rejected", rep.summary)

    def test_semantic_warnings(self):
        raw = minimal()
        raw["shifts"].append({"id": "S3", "date": "2026-10-10", "start": "07:00", "end": "19:00",
                              "assignment": "ICU", "required_skills": ["ICU Care"]})
        raw["shifts"].append({"id": "S4", "date": "2026-10-10", "start": "07:00", "end": "19:00",
                              "assignment": "Ward"})
        raw["existing_schedule"].append({"shift_id": "S3", "employee_id": "E2"})    # E2 lacks ICU, only 0h rest
        rep = validate_dataset(raw)
        cats = [f.category for f in rep.warnings]
        self.assertIn("skill_mismatch", cats)
        self.assertIn("constraint_conflict", cats)
        self.assertIn("coverage", cats)                                              # S4 open

    def test_not_an_object(self):
        self.assertEqual(validate_dataset([1, 2]).status, "invalid")

    def test_no_employees_is_fatal(self):
        raw = minimal()
        raw["employees"] = []
        self.assertEqual(validate_dataset(raw).status, "invalid")


class CsvImport(unittest.TestCase):
    def test_single_schedule_csv(self):
        csv_text = ("shift_id,date,start,end,assignment,department,required_skills,employee_id,employee_name,role,employee_skills\n"
                    "S1,2026-10-09,07:00,15:00,Line 1,L1,CNC Operation,M1,Ravi,Operator,CNC Operation;Forklift\n"
                    "S2,2026-10-09,15:00,23:00,Line 1,L1,CNC Operation,M2,Suresh,Operator,CNC Operation\n"
                    "S3,2026-10-10,07:00,15:00,Line 1,L1,CNC Operation,,,,\n")
        raw = dataset_from_csv(csv_text, {"name": "Plant", "domain": "manufacturing"})
        rep = validate_dataset(raw)
        self.assertTrue(rep.ok, [f.message for f in rep.errors])
        self.assertEqual(rep.stats["employees"], 2)
        self.assertEqual(rep.stats["open_shifts"], 1)
        self.assertIn("Forklift", rep.dataset.employee("M1").skills)

    def test_separate_employees_csv(self):
        sched = "shift_id,date,start,end,assignment,required_skills,employee_id\nS1,2026-10-09,09:00,17:00,Desk,English,T1\n"
        emps = "id,name,role,skills,max_daily_hours\nT1,Anu,Teacher,English;Maths,5\n"
        rep = validate_dataset(dataset_from_csv(sched, {"name": "School", "domain": "education"}, emps))
        self.assertTrue(rep.ok)
        self.assertEqual(rep.dataset.employee("T1").max_daily_hours, 5)


if __name__ == "__main__":
    unittest.main()
