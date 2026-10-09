import json
import unittest

from ai.explanation import Explainer, TemplateExplainer, check_grounding
from ai.providers import LLMError, MockProvider
from tests.fixtures import ROSTER_NAMES, feasible_facts, infeasible_facts


def llm_answer(headline, points, why_not=None):
    return {"headline": headline, "points": points, "why_not_others": why_not or []}


GOOD = llm_answer(
    "Arjun Mehta takes over Rahul Sharma's SUPPORT_L2 work with 1 assignment change and no overtime.",
    [
        {"text": "Arjun is available and certified in Tier-2 troubleshooting.",
         "fact_refs": ["selected.0.available", "selected.0.matched_skills"]},
        {"text": "His week stays at 32h, under the 40h limit, and he has 14h of rest before the shift.",
         "fact_refs": ["selected.0.weekly_hours_after", "selected.0.max_weekly_hours",
                       "selected.0.rest_hours_before_shift"]},
        {"text": "This satisfies the 11h rest rule in Working Time Policy §3.1.",
         "fact_refs": ["policies_applied.0"]},
        {"text": "Impact is LOW (14/100) with 0 hard-constraint violations.",
         "fact_refs": ["metrics.impact_score", "metrics.hard_constraint_violations"]},
    ],
    [{"text": "Meera Iyer would only have had 9h of rest.", "fact_refs": ["rejected.2.detail"]}],
)


class TemplateIsGrounded(unittest.TestCase):
    """The fallback must pass the same checks applied to the LLM."""

    def test_feasible_template_passes_grounding(self):
        facts = feasible_facts(with_policies=True)
        exp = TemplateExplainer().explain(facts)
        self.assertEqual(check_grounding(exp, facts, ROSTER_NAMES), [])
        self.assertIn("Arjun Mehta covers Rahul Sharma's SUPPORT_L2", exp.headline)
        self.assertEqual(len(exp.why_not_others), 3)

    def test_policies_are_cited(self):
        text = TemplateExplainer().explain(feasible_facts(with_policies=True)).as_text()
        self.assertIn("at least 11h rest between shifts (Working Time Policy §3.1)", text)
        self.assertIn("max 40h per week (Working Time Policy §2.2)", text)
        self.assertIn("under policy OPS-SUP-007", text)

    def test_unsatisfied_policy_is_called_out(self):
        facts = feasible_facts(with_policies=True)
        facts.policies_applied[0].satisfied = False
        self.assertIn("Does NOT satisfy at least 11h rest", TemplateExplainer().explain(facts).as_text())

    def test_infeasible_template_says_so(self):
        facts = infeasible_facts()
        exp = TemplateExplainer().explain(facts)
        self.assertTrue(exp.headline.startswith("No feasible reschedule found"))
        self.assertEqual(check_grounding(exp, facts, ROSTER_NAMES), [])

    def test_as_text(self):
        text = TemplateExplainer().explain(feasible_facts()).as_text()
        self.assertIn("Other candidates:", text)
        self.assertIn("Priya Nair already has an overlapping shift.", text)


class LLMExplanationGrounding(unittest.TestCase):
    def explain(self, response, facts=None, mode="auto"):
        return Explainer(MockProvider([response, response])).explain(
            facts or feasible_facts(with_policies=True), mode=mode, roster_names=ROSTER_NAMES)

    @staticmethod
    def mutate(fn):
        bad = json.loads(json.dumps(GOOD))
        fn(bad)
        return bad

    def test_grounded_llm_output_is_used(self):
        exp = self.explain(GOOD)
        self.assertEqual(exp.source, "llm", exp.grounding_warnings)
        self.assertEqual(exp.meta.prompt, "explanation@2.0.0")

    def test_invented_number_falls_back(self):
        exp = self.explain(self.mutate(lambda b: b["points"][1].update(text="Arjun has 6 fewer hours.")))
        self.assertEqual(exp.source, "template")
        self.assertTrue(any("number 6" in w for w in exp.grounding_warnings))

    def test_invented_policy_section_falls_back(self):
        exp = self.explain(self.mutate(lambda b: b["points"][2].update(text="Per Working Time Policy §7.4.")))
        self.assertEqual(exp.source, "template")

    def test_invented_person_falls_back(self):
        exp = self.explain(self.mutate(lambda b: b["points"].append(
            {"text": "Sanjay Rao was also considered.", "fact_refs": ["rejected"]})))
        self.assertEqual(exp.source, "template")
        self.assertTrue(any("Sanjay Rao" in w for w in exp.grounding_warnings))

    def test_bad_fact_ref_falls_back(self):
        exp = self.explain(self.mutate(lambda b: b["points"][0].update(fact_refs=["selected.0.seniority"])))
        self.assertEqual(exp.source, "template")

    def test_missing_fact_refs_falls_back(self):
        self.assertEqual(self.explain(self.mutate(lambda b: b["points"][0].update(fact_refs=[]))).source, "template")

    def test_malformed_output_falls_back(self):
        self.assertEqual(self.explain({"headline": 5}).source, "template")

    def test_provider_error_falls_back(self):
        self.assertEqual(self.explain(LLMError("rate limited")).source, "template")

    def test_infeasible_must_not_claim_success(self):
        claim = llm_answer("Rahul Sharma's shift was covered successfully.",
                           [{"text": "All good.", "fact_refs": ["status"]}])
        exp = self.explain(claim, facts=infeasible_facts())
        self.assertEqual(exp.source, "template")
        self.assertTrue(exp.headline.startswith("No feasible"))

    def test_strict_llm_mode_raises(self):
        with self.assertRaises(LLMError):
            self.explain(self.mutate(lambda b: b.update(headline="Arjun saves 5 hours.")), mode="llm")

    def test_template_mode_never_calls_llm(self):
        provider = MockProvider([])
        Explainer(provider).explain(feasible_facts(), mode="template")
        self.assertEqual(provider.calls, [])

    def test_no_provider_uses_template(self):
        self.assertEqual(Explainer(None).explain(feasible_facts()).source, "template")


if __name__ == "__main__":
    unittest.main()
