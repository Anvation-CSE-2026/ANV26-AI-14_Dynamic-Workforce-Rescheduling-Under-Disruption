import unittest

from ai.providers import LLMError, MockProvider
from rag.constraints import PolicySource, resolve_conflicts, to_optimizer_config, validate_constraint
from rag.rule_extractor import extract_rules
from rag.service import PolicyService
from tests.fixtures import CANNED_POLICY, POLICY_DIR, policy_responder


def svc(provider=None) -> PolicyService:
    s = PolicyService(provider)
    s.ingest_directory(POLICY_DIR)
    return s


def by_type(bundle, ctype, **scope):
    return [c for c in bundle.constraints if c.constraint_type == ctype
            and all(getattr(c.scope, k) == v for k, v in scope.items())]


SRC = PolicySource(policy_id="P", document="Doc", section="1", chunk_id="P#1", quote="q")


def pc(ctype, value, severity="hard", **scope):
    return validate_constraint({"constraint_type": ctype, "value": value, "severity": severity, "scope": scope,
                                "source": SRC, "interpretation": "x"})


class Translation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = MockProvider(policy_responder())
        cls.bundle = svc(cls.provider).build_bundle("Rahul is unavailable tomorrow", roles=["L2 Support"],
                                                    assignments=["SUPPORT_L2"])

    def test_spec_example_minimum_rest(self):
        c = by_type(self.bundle, "minimum_rest")[0]
        self.assertEqual((c.value, c.unit, c.severity), (11, "hours", "hard"))
        self.assertEqual((c.source.policy_id, c.source.section), ("HR-WT-001", "3.1"))
        self.assertTrue(c.verified_by_rules)
        self.assertEqual(c.interpretation_confidence, 0.95)
        self.assertGreater(c.retrieval_confidence, 0.5)

    def test_scoped_constraints(self):
        staff = by_type(self.bundle, "min_staffing", assignment="SUPPORT_L2")[0]
        self.assertEqual(staff.value, 3)
        skills = self.bundle.optimizer_config["required_skills"]["by_assignment"]
        self.assertEqual(skills["SUPPORT_L2"], ["Tier-2 troubleshooting"])
        self.assertEqual(skills["KANNADA_DESK"], ["Kannada"])

    def test_scoped_looser_than_global_is_flagged(self):
        c = next(c for c in self.bundle.conflicts if c.kind == "scoped_looser_than_global")
        self.assertEqual((c.constraint_type, c.applied_value), ("max_weekly_hours", 40))
        self.assertIn("Customer Support Operations Staffing Rules §3 allows 45", c.message)
        self.assertEqual(self.bundle.optimizer_config["hard"]["global"]["max_weekly_hours"], 40)

    def test_unsupported_rules_are_reported(self):
        texts = [u.text for u in self.bundle.unsupported]
        self.assertTrue(any("notified" in t for t in texts))
        self.assertTrue(any("fairly" in t for t in texts))
        self.assertTrue(any("Not enforced" in w for w in self.bundle.warnings()))

    def test_optimizer_config_shape(self):
        cfg = self.bundle.optimizer_config
        self.assertEqual(cfg["hard"]["global"]["minimum_rest"], 11)
        self.assertEqual(cfg["hard"]["global"]["max_daily_hours"], 9)
        self.assertEqual(cfg["hard"]["by_assignment"]["SUPPORT_L2"]["min_staffing"], 3)
        self.assertEqual(cfg["hard"]["by_role"]["L2 Support"]["max_weekly_hours"], 45)
        self.assertEqual(cfg["soft"]["global"]["max_schedule_changes_per_month"], 3)

    def test_citations_for_explanations(self):
        cites = {(c.constraint_type, c.section) for c in self.bundle.citations()}
        self.assertIn(("minimum_rest", "3.1"), cites)

    def test_topic_coverage_and_traces(self):
        self.assertTrue(all(t.status == "found" for t in self.bundle.topics if t.topic != "request"))
        self.assertTrue(self.bundle.trace_ids)
        self.assertEqual(self.bundle.mode, "llm")

    def test_cache_avoids_repeat_calls(self):
        p = MockProvider(policy_responder())
        s = svc(p)
        s.build_bundle()
        n = len(p.calls)
        s.build_bundle()
        self.assertEqual(len(p.calls), n)


class TranslationSafety(unittest.TestCase):
    def bundle(self, overrides):
        return svc(MockProvider(policy_responder(overrides))).build_bundle()

    def test_fabricated_quote_rejected(self):
        b = self.bundle({"HR-WT-001#3.1": [{**CANNED_POLICY["HR-WT-001#3.1"][0], "value": 8,
                                            "quote": "Employees must receive at least 8 hours of rest."}]})
        self.assertTrue(any(r.reason == "quote not found in policy text" for r in b.rejected))
        # the rule safety net still recovers the real rule from the chunk
        rest = by_type(b, "minimum_rest")[0]
        self.assertEqual((rest.value, rest.extracted_by), (11, "rules"))

    def test_out_of_range_and_unknown_type_rejected(self):
        b = self.bundle({"HR-WT-001#2.2": [{**CANNED_POLICY["HR-WT-001#2.2"][0], "value": 400}],
                         "HR-WT-001#3.2": [{**CANNED_POLICY["HR-WT-001#3.2"][0], "constraint_type": "vibes"}]})
        reasons = " ".join(r.reason for r in b.rejected)
        self.assertIn("outside allowed range", reasons)
        self.assertIn("unsupported constraint type", reasons)

    def test_interpretation_mismatch_applies_strictest(self):
        b = self.bundle({"HR-WT-001#3.1": [{**CANNED_POLICY["HR-WT-001#3.1"][0], "value": 10}]})
        c = by_type(b, "minimum_rest")[0]
        self.assertEqual((c.value, c.verified_by_rules, c.interpretation_confidence), (11, False, 0.4))
        m = next(x for x in b.conflicts if x.kind == "interpretation_mismatch")
        self.assertIn("Model read 10 but the rule check read 11", m.message)
        self.assertTrue(any("Low-confidence" in w for w in b.warnings()))

    def test_missed_rule_is_added_from_rules(self):
        b = self.bundle({"HR-OT-002#2": []})
        c = by_type(b, "max_overtime_weekly")[0]
        self.assertEqual((c.value, c.extracted_by), (8, "rules"))

    def test_llm_failure_falls_back_to_rules(self):
        b = svc(MockProvider(lambda *a: LLMError("down"))).build_bundle()
        self.assertEqual(by_type(b, "minimum_rest")[0].value, 11)
        self.assertTrue(any("LLM translation failed" in r.reason for r in b.rejected))


class RulesOnlyMode(unittest.TestCase):
    def test_exhaustive_covers_every_chunk(self):
        s = svc(None)
        b = s.build_bundle(exhaustive=True)
        self.assertEqual({c.source.chunk_id for c in b.constraints} - {c.chunk_id for c in s.store.chunks}, set())
        self.assertIn(45, [o.value for c in b.conflicts for o in c.options])

    def test_bundle_without_llm(self):
        b = svc(None).build_bundle(roles=["L2 Support"])
        self.assertEqual(b.mode, "rules")
        cfg = b.optimizer_config["hard"]["global"]
        self.assertEqual((cfg["max_weekly_hours"], cfg["minimum_rest"], cfg["max_daily_hours"]), (40, 11, 9))
        # rules can't see that 45h is L2-only → reads it as global → conflict, strictest (40) applied
        self.assertTrue(any(c.applied_value == 40 for c in b.conflicts))

    def test_rule_extractor_patterns(self):
        cases = {
            "Employees must receive at least 11 hours of rest between shifts.": ("minimum_rest", 11, "hard"),
            "Overtime is capped at 8 hours per employee per week.": ("max_overtime_weekly", 8, "hard"),
            "No one may work more than six consecutive days.": ("max_consecutive_days", 6, "hard"),
            "Staff should not work more than 2 weekends per month.": ("max_weekends_per_month", 2, "soft"),
            "Overtime is not permitted for interns.": ("overtime_allowed", False, "hard"),
            "Shifts may not exceed 10 hours.": ("max_daily_hours", 10, "hard"),
        }
        for text, expected in cases.items():
            r = extract_rules(text)
            self.assertTrue(r, text)
            self.assertEqual((r[0].constraint_type, r[0].value, r[0].severity), expected, text)
        self.assertEqual(extract_rules("Timesheets must be submitted by Friday."), [])


class ConflictResolution(unittest.TestCase):
    def test_same_scope_different_values(self):
        applied, conflicts = resolve_conflicts([pc("max_weekly_hours", 40), pc("max_weekly_hours", 38)])
        self.assertEqual([c.value for c in applied], [38])
        self.assertEqual(conflicts[0].resolution, "strictest_applied")

    def test_higher_is_stricter_for_rest(self):
        applied, _ = resolve_conflicts([pc("minimum_rest", 11), pc("minimum_rest", 12)])
        self.assertEqual(applied[0].value, 12)

    def test_boolean_strictness(self):
        applied, _ = resolve_conflicts([pc("overtime_allowed", True), pc("overtime_allowed", False)])
        self.assertIs(applied[0].value, False)

    def test_hard_beats_soft(self):
        applied, conflicts = resolve_conflicts([pc("max_weekly_hours", 40), pc("max_weekly_hours", 35, "soft")])
        self.assertEqual(applied[0].value, 40)
        self.assertEqual(conflicts, [])

    def test_identical_values_merge_silently(self):
        applied, conflicts = resolve_conflicts([pc("minimum_rest", 11), pc("minimum_rest", 11)])
        self.assertEqual((len(applied), conflicts), (1, []))

    def test_multiple_required_skills_are_not_conflicts(self):
        applied, conflicts = resolve_conflicts([pc("required_skill", "A", assignment="Q"),
                                                pc("required_skill", "B", assignment="Q")])
        self.assertEqual(len(applied), 2)
        self.assertEqual(conflicts, [])
        self.assertEqual(to_optimizer_config(applied)["required_skills"]["by_assignment"]["Q"], ["A", "B"])

    def test_validation(self):
        with self.assertRaises(ValueError):
            pc("max_weekly_hours", "lots")
        with self.assertRaises(ValueError):
            pc("max_consecutive_days", 2.5)
        with self.assertRaises(ValueError):
            validate_constraint({"constraint_type": "minimum_rest", "value": 11, "unit": "km", "severity": "hard",
                                 "source": SRC, "interpretation": "x"})
        self.assertEqual(pc("minimum_rest", "11").value, 11)


if __name__ == "__main__":
    unittest.main()
