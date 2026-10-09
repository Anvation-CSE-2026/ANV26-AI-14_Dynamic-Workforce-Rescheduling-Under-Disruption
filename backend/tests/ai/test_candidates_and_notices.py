import unittest

from ai.candidates import CandidateComparer, CandidateFacts, compare
from ai.employee_notice import build_notice, check_notice
from ai.providers import MockProvider
from ai.schemas import ChangeFact, MetricsFact, Priority
from ai.service import AIService
from tests.fixtures import NAMES, POLICIES_APPLIED, ROSTER_NAMES, TOMORROW, feasible_facts


def cand(cid, label, changed, affected, ot, fairness, impact, status="OPTIMAL", hard=0, policy=0, pref=0):
    return CandidateFacts(candidate_id=cid, label=label, status=status, policy_violations=policy,
                          metrics=MetricsFact(assignments_changed=changed, employees_affected=affected,
                                              overtime_hours=ot, fairness_score=fairness, impact_score=impact,
                                              hard_constraint_violations=hard, preference_violations=pref))


A = cand("A", "Option A", 1, 1, 0, 86, 14)            # least disruption
B = cand("B", "Option B", 2, 2, 0, 92, 22)            # fairer
C = cand("C", "Option C", 2, 2, 2, 85, 30)            # dominated by A
D = cand("D", "Option D", 1, 1, 0, 95, 10, hard=1)    # looks best but violates a hard constraint


class Comparison(unittest.TestCase):
    def test_deterministic_comparison(self):
        comp = compare([A, B, C, D])
        self.assertEqual(comp.compliant, ["A", "B", "C"])
        self.assertIn("D", comp.non_compliant)
        self.assertEqual(comp.best_by["assignments_changed"], ["A"])
        self.assertEqual(comp.best_by["fairness_score"], ["B"])
        self.assertEqual(comp.dominated, {"C": "A"})
        self.assertEqual(comp.recommended_id, "A")
        t = next(t for t in comp.tradeoffs if t.candidate_id == "B")
        self.assertEqual(t.better, {"fairness_score": 6.0})
        self.assertEqual(t.worse["assignments_changed"], 1.0)
        self.assertIn("fairness score 92 vs 86", t.text)

    def test_priority_changes_recommendation(self):
        self.assertEqual(compare([A, B, C], Priority.fairness).recommended_id, "B")
        self.assertEqual(compare([A, B, C], Priority.minimize_overtime).recommended_id, "A")

    def test_no_compliant_candidates(self):
        comp = compare([D])
        self.assertIsNone(comp.recommended_id)
        self.assertTrue(CandidateComparer(None).compare([D]).headline.startswith("None of the alternatives"))

    def test_template_narration_is_grounded(self):
        comp = CandidateComparer(None).compare([A, B, C, D])
        self.assertEqual(comp.source, "template")
        self.assertIn("Option A is suggested", comp.headline)
        self.assertTrue(any("Option D is not compliant" in p.text for p in comp.points))

    def test_llm_narration_accepted_when_grounded(self):
        good = {"headline": "Option A changes 1 assignment; Option B raises fairness to 92 for 1 more change.",
                "points": [{"text": "Option B: fairness 92 vs 86.", "fact_refs": ["tradeoffs.0.better"]}]}
        comp = CandidateComparer(MockProvider([good])).compare([A, B, C, D], roster_names=ROSTER_NAMES)
        self.assertEqual(comp.source, "llm", comp.grounding_warnings)

    def test_llm_narration_with_invented_number_rejected(self):
        bad = {"headline": "Option B is 40% fairer.", "points": [{"text": "x", "fact_refs": ["best_by"]}]}
        comp = CandidateComparer(MockProvider([bad])).compare([A, B, C])
        self.assertEqual(comp.source, "template")

    def test_llm_cannot_promote_non_compliant_option(self):
        bad = {"headline": "Option D is the best choice.", "points": [{"text": "Option D.", "fact_refs": ["candidates"]}]}
        comp = CandidateComparer(MockProvider([bad])).compare([A, B, D])
        self.assertEqual(comp.source, "template")
        self.assertTrue(any("Option D" in w for w in comp.grounding_warnings))


class EmployeeNotices(unittest.TestCase):
    def test_notice_content_and_privacy(self):
        changes = feasible_facts().changes
        n = build_notice("EMP003", "Arjun Mehta", changes, POLICIES_APPLIED, schedule_version="v42")
        self.assertIn("Hi Arjun", n.body)
        self.assertIn("you'll work SUPPORT_L2, 09:00-17:00 (previously KANNADA_DESK, 13:00-21:00)", n.body)
        self.assertIn("at least 11h rest between shifts (Working Time Policy §3.1)", n.body)
        self.assertNotIn("Rahul", n.body)
        self.assertNotIn("emergency", n.body)
        self.assertEqual(check_notice(n, ROSTER_NAMES), [])
        self.assertTrue(n.requires_acknowledgement)
        self.assertEqual(n.schedule_version, "v42")

    def test_check_catches_leaks(self):
        n = build_notice("EMP003", "Arjun Mehta", feasible_facts().changes)
        leaked = n.model_copy(update={"body": n.body + "\nRahul Sharma is sick."})
        problems = check_notice(leaked, ROSTER_NAMES)
        self.assertTrue(any("Rahul Sharma" in p for p in problems))
        self.assertTrue(any("sick" in p for p in problems))

    def test_service_skips_the_absent_employee(self):
        notices = AIService(None).employee_notices(feasible_facts().changes, NAMES, POLICIES_APPLIED)
        self.assertEqual([n.employee_id for n in notices], ["EMP003"])

    def test_shift_moved_and_added(self):
        changes = [ChangeFact(employee_id="EMP002", employee_name="Priya Nair", change_type="shift_moved",
                              date=TOMORROW, from_assignment="SUPPORT_L2", from_shift="09:00-17:00",
                              to_shift="11:00-19:00"),
                   ChangeFact(employee_id="EMP002", employee_name="Priya Nair", change_type="added",
                              date="2026-10-10", to_assignment="SUPPORT_L1", to_shift="09:00-13:00")]
        n = build_notice("EMP002", "Priya Nair", changes)
        self.assertIn("moves from 09:00-17:00 to 11:00-19:00", n.body)
        self.assertIn("added to SUPPORT_L1 on Saturday 10 October", n.body)
        self.assertEqual(check_notice(n, ROSTER_NAMES), [])


    def test_own_shift_names_are_not_absence_reasons(self):
        changes = [ChangeFact(employee_id="EMP002", employee_name="Priya Nair", change_type="reassigned",
                              date=TOMORROW, from_assignment="Ward Day", from_shift="07:00-19:00",
                              to_assignment="Emergency Day", to_shift="07:00-19:00")]
        n = build_notice("EMP002", "Priya Nair", changes)
        self.assertIn("Emergency Day", n.body)
        self.assertEqual(check_notice(n, ROSTER_NAMES), [])
        leaked = n.model_copy(update={"body": n.body + "\nThis is due to a family emergency."})
        self.assertTrue(any("emergency" in p for p in check_notice(leaked, ROSTER_NAMES)))


if __name__ == "__main__":
    unittest.main()
