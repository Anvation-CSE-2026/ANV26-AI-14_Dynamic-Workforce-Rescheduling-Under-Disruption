import unittest

from ai.feedback import FeedbackParser, _RawFeedback
from ai.intent import IntentRouter
from ai.providers import MockProvider
from ai.schemas import ManagerPreferences, Priority
from ai.service import AIService
from ai.what_if import WhatIfParser, _RawScenario
from tests.fixtures import TOMORROW, context, extraction, raw


class Intent(unittest.TestCase):
    def test_rules_route_without_llm_call(self):
        p = MockProvider([])
        r = IntentRouter(p)
        self.assertEqual(r.classify("What if overtime is forbidden?").intent, "what_if")
        self.assertEqual(r.classify("Don't assign Arjun next time.").intent, "manager_feedback")
        self.assertEqual(p.calls, [])

    def test_llm_classification(self):
        r = IntentRouter(MockProvider([{"intent": "report_disruption", "confidence": "high"}]))
        res = r.classify("Rahul called in sick")
        self.assertEqual((res.intent, res.method), ("report_disruption", "llm"))
        self.assertEqual(res.meta.prompt, "intent_router@2.0.0")

    def test_fallback_without_provider_is_low_confidence(self):
        r = IntentRouter(None)
        self.assertEqual(r.classify("Rahul is sick tomorrow").model_dump(include={"intent", "confidence"}),
                         {"intent": "report_disruption", "confidence": "low"})
        self.assertEqual(r.classify("What is our overtime policy?").intent, "policy_question")
        self.assertEqual(r.classify("tell me a joke").intent, "other")

    def test_interpret_routes_to_the_right_parser(self):
        ai = AIService(MockProvider({
            "classify_message": {"intent": "report_disruption", "confidence": "high"},
            "record_disruption_request": extraction([raw()]),
        }))
        out = ai.interpret("Rahul is unavailable tomorrow 9 to 5", context())
        self.assertEqual(out.intent.intent, "report_disruption")
        self.assertTrue(out.disruption.ready)
        self.assertIsNone(out.scenario)


def scenario(*changes, is_what_if=True):
    return _RawScenario.model_validate({"is_what_if": is_what_if, "changes": list(changes)})


def wi(raw_spec):
    return WhatIfParser(MockProvider([])).resolve(raw_spec, context())


class WhatIf(unittest.TestCase):
    def test_overtime_forbidden(self):
        s = wi(scenario({"op": "set_overtime", "value": False, "text": "overtime is forbidden"}))
        self.assertEqual(s.status, "READY")
        self.assertIs(s.apply_to(ManagerPreferences()).allow_overtime, False)
        self.assertEqual(s.summary, "Scenario: overtime forbidden.")

    def test_fairness_more_important(self):
        s = wi(scenario({"op": "set_priority", "priority": "fairness", "text": "fairness is more important"}))
        self.assertEqual(s.apply_to(ManagerPreferences()).priority, Priority.fairness)

    def test_minimum_employees_affected(self):
        s = wi(scenario({"op": "set_priority", "priority": "minimize_affected_employees", "text": "x"}))
        self.assertEqual(s.changes[0].priority, Priority.minimize_affected_employees)

    def test_two_employees_without_names_asks(self):
        s = wi(scenario({"op": "add_unavailability", "employee_mention": None, "count": 2,
                         "text": "two employees are unavailable"}))
        self.assertEqual(s.status, "NEEDS_CLARIFICATION")
        self.assertEqual(s.issues[0].code, "NEEDS_NAMES")
        self.assertIn("Which 2 employee(s)", s.issues[0].message)

    def test_named_second_absence(self):
        s = wi(scenario({"op": "add_unavailability", "employee_mention": "Priya", "date": TOMORROW,
                         "date_expression": "tomorrow", "text": "Priya is also out"}))
        self.assertEqual(s.status, "READY", s.issues)
        d = s.added_disruptions()[0]
        self.assertEqual((d.employee_id, d.start_time, d.end_time), ("EMP002", "09:00", "17:00"))

    def test_override_policy_valid_and_invalid(self):
        ok = wi(scenario({"op": "override_policy", "policy_type": "max_weekly_hours", "value": 45, "text": "45h"}))
        self.assertEqual(ok.policy_overrides(), {"max_weekly_hours": 45})
        bad = wi(scenario({"op": "override_policy", "policy_type": "max_weekly_hours", "value": 400, "text": "400h"}))
        self.assertEqual(bad.status, "NEEDS_CLARIFICATION")
        self.assertEqual(bad.issues[0].code, "INVALID_VALUE")

    def test_lock_exclude_include(self):
        s = wi(scenario({"op": "lock_employee", "employee_mention": "Priya", "text": "don't move Priya"},
                        {"op": "exclude_employee", "employee_mention": "Arjun", "text": "can't use Arjun"}))
        p = s.apply_to(ManagerPreferences(excluded_employee_ids=["EMP006"]))
        self.assertEqual(p.locked_employee_ids, ["EMP002"])
        self.assertEqual(p.excluded_employee_ids, ["EMP003", "EMP006"])
        back = wi(scenario({"op": "include_employee", "employee_mention": "Meera", "text": "Meera could cover"}))
        self.assertEqual(back.apply_to(p).excluded_employee_ids, ["EMP003"])

    def test_contradictions_block(self):
        s = wi(scenario({"op": "set_overtime", "value": False, "text": "a"},
                        {"op": "set_overtime", "value": True, "text": "b"}))
        self.assertEqual(s.status, "NEEDS_CLARIFICATION")
        self.assertEqual(s.issues[0].code, "CONTRADICTORY_CHANGES")

    def test_unsupported_part_is_disclosed(self):
        s = wi(scenario({"op": "set_overtime", "value": False, "text": "no overtime"},
                        {"op": "other", "text": "what if it rains"}))
        self.assertEqual(s.status, "READY")
        self.assertEqual(s.unsupported, ["what if it rains"])
        only = wi(scenario({"op": "other", "text": "what if it rains"}))
        self.assertEqual(only.status, "UNSUPPORTED")

    def test_not_a_what_if(self):
        self.assertEqual(wi(scenario(is_what_if=False)).status, "UNSUPPORTED")

    def test_end_to_end_with_mock(self):
        p = MockProvider([{"is_what_if": True, "changes": [{"op": "set_overtime", "value": False, "text": "x"}]}])
        s = WhatIfParser(p).parse("What if overtime is forbidden?", context())
        self.assertEqual(s.meta.prompt, "what_if_extraction@2.0.0")
        self.assertEqual(s.status, "READY")


def fb(*items):
    return FeedbackParser(MockProvider([])).resolve(_RawFeedback.model_validate({"items": list(items)}), context())


class Feedback(unittest.TestCase):
    def test_dont_assign_next_time(self):
        r = fb({"kind": "avoid_employee", "employee_mention": "Arjun", "scope": "next_reschedule",
                "strength": "hard", "text": "Don't assign Arjun next time."})
        p = r.preferences[0]
        self.assertEqual((p.employee_id, p.scope, p.strength), ("EMP003", "next_reschedule", "hard"))
        self.assertEqual(r.summary, "never use Arjun Mehta as a replacement next time.")

    def test_prefer_minimum_disruption_and_fairness(self):
        r = fb({"kind": "objective_priority", "priority": "minimize_changes", "scope": "until_revoked",
                "strength": "hard", "text": "Prefer minimum disruption."})
        self.assertEqual(r.preferences[0].priority, Priority.minimize_changes)
        self.assertEqual(r.preferences[0].strength, "soft")  # priorities are always weights
        r2 = fb({"kind": "objective_priority", "priority": "fairness", "scope": "until_revoked",
                 "strength": "soft", "text": "Prioritize fairness."})
        self.assertEqual(r2.preferences[0].priority, Priority.fairness)

    def test_overtime_unless_unavoidable_is_soft(self):
        r = fb({"kind": "overtime_rule", "overtime_mode": "only_if_unavoidable", "scope": "until_revoked",
                "strength": "hard", "text": "Never use overtime unless unavoidable."})
        p = r.preferences[0]
        self.assertEqual((p.overtime_mode, p.strength), ("only_if_unavoidable", "soft"))

    def test_contradiction(self):
        r = fb({"kind": "avoid_employee", "employee_mention": "Arjun", "scope": "until_revoked", "strength": "soft",
                "text": "a"},
               {"kind": "prefer_employee", "employee_mention": "Arjun", "scope": "until_revoked", "strength": "soft",
                "text": "b"})
        self.assertEqual(r.status, "NEEDS_CLARIFICATION")

    def test_unknown_employee(self):
        r = fb({"kind": "avoid_employee", "employee_mention": "Zoya", "scope": "until_revoked", "strength": "soft",
                "text": "avoid Zoya"})
        self.assertEqual(r.issues[0].code, "UNKNOWN_EMPLOYEE")

    def test_not_actionable(self):
        r = fb({"kind": "other", "scope": "until_revoked", "strength": "soft", "text": "great job team"})
        self.assertEqual(r.status, "UNSUPPORTED")
        self.assertEqual(r.unsupported, ["great job team"])

    def test_stable_preference_ids(self):
        item = {"kind": "avoid_employee", "employee_mention": "Arjun", "scope": "until_revoked", "strength": "soft",
                "text": "x"}
        self.assertEqual(fb(item).preferences[0].preference_id, fb(item).preferences[0].preference_id)


if __name__ == "__main__":
    unittest.main()
