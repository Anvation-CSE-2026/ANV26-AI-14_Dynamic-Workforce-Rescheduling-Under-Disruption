"""Live checks against the real Claude API: run these before the demo.

Skipped unless ANTHROPIC_API_KEY is set and the anthropic SDK is installed:
    cd backend && python -m pytest tests/ai/test_live_claude.py -v -s
They catch prompt regressions that mocked tests can't.
"""

import importlib.util
import os
import unittest

from ai.providers import ClaudeProvider
from ai.service import AIService
from tests.fixtures import POLICY_DIR, ROSTER_NAMES, TOMORROW, context, feasible_facts

LIVE = bool(os.getenv("ANTHROPIC_API_KEY")) and importlib.util.find_spec("anthropic") is not None


@unittest.skipUnless(LIVE, "set ANTHROPIC_API_KEY and install anthropic to run live tests")
class LiveClaude(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai = AIService(ClaudeProvider())
        cls.ai.policies.ingest_directory(POLICY_DIR)

    def test_demo_sentence(self):
        out = self.ai.interpret("Rahul is unavailable tomorrow from 9 to 5. Find a replacement but don't "
                                "disturb anyone already scheduled unless necessary.", context())
        r = out.disruption
        self.assertEqual(r.status, "READY", r.issues)
        d = r.disruptions[0]
        self.assertEqual((d.employee_id, d.date, d.start_time, d.end_time), ("EMP001", TOMORROW, "09:00", "17:00"))
        self.assertEqual(r.preferences.priority.value, "minimize_affected_employees")

    def test_preferences(self):
        r = self.ai.parse_request("Rahul called in sick for tomorrow. Don't touch Priya's shift and no overtime.",
                                  context())
        self.assertEqual(r.status, "READY", r.issues)
        self.assertEqual(r.preferences.locked_employee_ids, ["EMP002"])
        self.assertIs(r.preferences.allow_overtime, False)

    def test_ambiguous(self):
        self.assertEqual(self.ai.parse_request("Sanjay can't make it tomorrow morning.", context()).status,
                         "NEEDS_CLARIFICATION")

    def test_what_ifs(self):
        s = self.ai.interpret("What if overtime is forbidden?", context()).scenario
        self.assertEqual(s.status, "READY", s.issues)
        self.assertIs(s.changes[0].allow, False)
        s2 = self.ai.parse_what_if("What if two employees are unavailable?", context())
        self.assertEqual(s2.status, "NEEDS_CLARIFICATION")

    def test_feedback(self):
        f = self.ai.interpret("Don't assign Arjun next time.", context()).feedback
        self.assertEqual(f.status, "READY", f.issues)
        self.assertEqual((f.preferences[0].employee_id, f.preferences[0].scope), ("EMP003", "next_reschedule"))

    def test_policy_bundle(self):
        b = self.ai.policy_bundle("Rahul is out tomorrow", roles=["L2 Support"], assignments=["SUPPORT_L2"])
        cfg = b.optimizer_config["hard"]["global"]
        self.assertEqual((cfg.get("minimum_rest"), cfg.get("max_weekly_hours")), (11, 40))
        print("\nconflicts:", [c.message for c in b.conflicts])
        print("warnings:", b.warnings())

    def test_explanation_grounded(self):
        exp = self.ai.explain(feasible_facts(with_policies=True), roster_names=ROSTER_NAMES)
        print("\n" + exp.as_text(), "\nsource:", exp.source, "warnings:", exp.grounding_warnings)
        self.assertTrue(exp.headline)


if __name__ == "__main__":
    unittest.main()
