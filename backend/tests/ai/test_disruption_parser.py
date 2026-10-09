import unittest

from ai.disruption_parser import DisruptionParser
from ai.providers import LLMError, MockProvider
from ai.schemas import Disruption

from tests.fixtures import TOMORROW, context, extraction, raw


def parse(responses, text="Rahul is unavailable tomorrow from 9 AM to 5 PM.", **ctx):
    provider = MockProvider(list(responses))
    result = DisruptionParser(provider).parse(text, context(**ctx))
    return result, provider


def codes(result):
    return [i.code for i in result.issues]


class ValidDisruption(unittest.TestCase):
    def test_ready_with_canonical_fields(self):
        r, _ = parse([extraction([raw()])])
        self.assertEqual(r.status, "READY", r.issues)
        self.assertEqual(len(r.disruptions), 1)
        d = r.disruptions[0]
        self.assertEqual(d.model_dump(), {
            "type": "employee_unavailability", "employee_id": "EMP001", "date": TOMORROW,
            "start_time": "09:00", "end_time": "17:00", "reason": "emergency",
        })
        self.assertIn("Rahul Sharma (EMP001)", r.confirmation_summary)

    def test_disruption_matches_master_contract_keys(self):
        self.assertEqual(set(Disruption.model_fields),
                         {"type", "employee_id", "date", "start_time", "end_time", "reason"})

    def test_missing_reason_becomes_unspecified(self):
        r, _ = parse([extraction([raw(reason=None)])])
        self.assertEqual(r.disruptions[0].reason, "unspecified")

    def test_multiple_disruptions(self):
        r, _ = parse([extraction([raw(), raw(mention="Priya")])])
        self.assertEqual(r.status, "READY")
        self.assertEqual([d.employee_id for d in r.disruptions], ["EMP001", "EMP002"])

    def test_alias_resolves(self):
        r, _ = parse([extraction([raw(mention="Meeru", start="07:00", end="15:00")])])
        self.assertEqual(r.details[0].employee_name, "Meera Iyer")
        self.assertEqual(r.disruptions[0].employee_id, "EMP006")

    def test_full_name_and_possessive(self):
        r, _ = parse([extraction([raw(mention="Rahul Sharma's")])])
        self.assertEqual(r.disruptions[0].employee_id, "EMP001")

    def test_llm_cannot_inject_employee_id(self):
        bad = raw()
        bad["employee_id"] = "EMP999"  # not in the extraction schema; must be ignored
        r, _ = parse([extraction([bad])])
        self.assertEqual(r.disruptions[0].employee_id, "EMP001")


class AmbiguousAndInvalidEmployee(unittest.TestCase):
    def test_ambiguous_name(self):
        r, _ = parse([extraction([raw(mention="Sanjay")])])
        self.assertEqual(r.status, "NEEDS_CLARIFICATION")
        self.assertEqual(codes(r), ["AMBIGUOUS_EMPLOYEE"])
        self.assertEqual({c.id for c in r.issues[0].candidates}, {"EMP004", "EMP005"})

    def test_unknown_employee(self):
        r, _ = parse([extraction([raw(mention="Vikram")])])
        self.assertEqual(r.status, "NEEDS_CLARIFICATION")
        self.assertIn("UNKNOWN_EMPLOYEE", codes(r))
        self.assertEqual(r.disruptions, [])

    def test_typo_suggests_but_does_not_auto_accept(self):
        r, _ = parse([extraction([raw(mention="Rahl")])])
        self.assertEqual(r.status, "NEEDS_CLARIFICATION")
        self.assertEqual(r.issues[0].code, "UNKNOWN_EMPLOYEE")
        self.assertEqual([c.id for c in r.issues[0].candidates], ["EMP001"])

    def test_missing_employee(self):
        r, _ = parse([extraction([raw(mention=None)])], text="Someone is out tomorrow")
        self.assertIn("MISSING_EMPLOYEE", codes(r))


class Dates(unittest.TestCase):
    def test_missing_date(self):
        r, _ = parse([extraction([raw(date=None, date_expression=None)])], text="Rahul is out 9 to 5")
        self.assertEqual(r.status, "NEEDS_CLARIFICATION")
        self.assertIn("MISSING_DATE", codes(r))

    def test_tomorrow_is_resolved_deterministically(self):
        # Model gets the date wrong; deterministic resolution wins and is disclosed.
        r, _ = parse([extraction([raw(date="2026-10-10")])])
        self.assertEqual(r.status, "READY")
        self.assertEqual(r.disruptions[0].date, TOMORROW)
        self.assertTrue(any("deterministic" in a for a in r.assumptions))

    def test_weekday_name(self):
        r, _ = parse([extraction([raw(date=None, date_expression="Friday")])])
        self.assertEqual(r.disruptions[0].date, TOMORROW)  # ref is Thursday

    def test_invalid_date_string(self):
        r, _ = parse([extraction([raw(date="9th of Octember", date_expression="9th of Octember")])])
        self.assertIn("INVALID_DATE", codes(r))

    def test_past_date(self):
        r, _ = parse([extraction([raw(date="2026-10-01", date_expression="last Thursday")])])
        self.assertIn("DATE_IN_PAST", codes(r))

    def test_beyond_horizon(self):
        r, _ = parse([extraction([raw(date="2026-12-25", date_expression="Christmas")])])
        self.assertIn("DATE_OUT_OF_HORIZON", codes(r))


class Times(unittest.TestCase):
    def test_missing_time_defaults_to_scheduled_shift(self):
        r, _ = parse([extraction([raw(start=None, end=None)])], text="Rahul is off tomorrow")
        self.assertEqual(r.status, "READY")
        self.assertEqual((r.disruptions[0].start_time, r.disruptions[0].end_time), ("09:00", "17:00"))
        self.assertTrue(r.assumptions)

    def test_missing_time_without_shift_needs_clarification(self):
        r, _ = parse([extraction([raw(mention="Sanjay Kumar", start=None, end=None)])])
        self.assertEqual(r.status, "NEEDS_CLARIFICATION")
        self.assertIn("MISSING_TIME", codes(r))

    def test_morning_is_clipped_to_shift(self):
        r, _ = parse([extraction([raw(start=None, end=None, time_expression="morning")])])
        d = r.disruptions[0]
        self.assertEqual((d.start_time, d.end_time), ("09:00", "13:00"))

    def test_only_start_time_uses_shift_end(self):
        r, _ = parse([extraction([raw(start="13:00", end=None)])])
        self.assertEqual((r.disruptions[0].start_time, r.disruptions[0].end_time), ("13:00", "17:00"))

    def test_end_before_start(self):
        r, _ = parse([extraction([raw(start="17:00", end="09:00")])])
        self.assertIn("INVALID_TIME", codes(r))

    def test_garbage_time(self):
        r, _ = parse([extraction([raw(start="9am", end="5pm")])])
        self.assertIn("INVALID_TIME", codes(r))


class Unsupported(unittest.TestCase):
    def test_unsupported_type(self):
        r, _ = parse([extraction([raw(mention=None, type_="workload_increase")])],
                     text="We need two more people on Project A tomorrow")
        self.assertEqual(r.status, "UNSUPPORTED")
        self.assertIn("UNSUPPORTED_DISRUPTION", codes(r))

    def test_not_a_disruption(self):
        r, _ = parse([extraction(is_report=False)], text="What's the weather?")
        self.assertEqual(r.status, "UNSUPPORTED")
        self.assertEqual(codes(r), ["NOT_A_DISRUPTION"])

    def test_empty_request_does_not_call_llm(self):
        r, provider = parse([], text="   ")
        self.assertEqual(r.status, "NEEDS_CLARIFICATION")
        self.assertEqual(provider.calls, [])


class ManagerPreferences(unittest.TestCase):
    def test_preferences_resolved_to_ids(self):
        r, _ = parse([extraction([raw()], {
            "lock_employee_mentions": ["Priya"],
            "exclude_employee_mentions": ["Meera"],
            "allow_overtime": False,
            "priority": "minimize_affected_employees",
        })], text="Rahul is out tomorrow 9-5. Don't change Priya's shift, don't use Meera, no overtime, "
                  "disturb as few people as possible.")
        self.assertEqual(r.status, "READY", r.issues)
        p = r.preferences
        self.assertEqual(p.locked_employee_ids, ["EMP002"])
        self.assertEqual(p.excluded_employee_ids, ["EMP006"])
        self.assertIs(p.allow_overtime, False)
        self.assertEqual(p.priority.value, "minimize_affected_employees")
        self.assertIn("keep Priya Nair unchanged", r.confirmation_summary)
        self.assertIn("no overtime", r.confirmation_summary)

    def test_unknown_priority_is_dropped_not_crashing(self):
        r, _ = parse([extraction([raw()], {"priority": "make_everyone_happy"})])
        self.assertEqual(r.status, "READY")
        self.assertIsNone(r.preferences.priority)

    def test_unknown_locked_employee_blocks(self):
        r, _ = parse([extraction([raw()], {"lock_employee_mentions": ["Zoya"]})])
        self.assertEqual(r.status, "NEEDS_CLARIFICATION")
        self.assertEqual(r.issues[0].field, "preferences.locked_employee_ids")

    def test_locked_and_unavailable_conflict(self):
        r, _ = parse([extraction([raw()], {"lock_employee_mentions": ["Rahul"]})])
        self.assertIn("LOCKED_EMPLOYEE_CONFLICT", codes(r))


class MalformedOutput(unittest.TestCase):
    def test_retry_once_then_succeed(self):
        bad = {"is_disruption_report": True, "disruptions": "Rahul tomorrow", "preferences": {}}
        r, provider = parse([bad, extraction([raw()])])
        self.assertEqual(r.status, "READY")
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("previous output was invalid", provider.calls[1]["user"])

    def test_malformed_twice_is_error(self):
        bad = {"disruptions": 42}
        r, _ = parse([bad, bad])
        self.assertEqual(r.status, "ERROR")
        self.assertEqual(codes(r), ["LLM_ERROR"])

    def test_non_dict_output(self):
        r, _ = parse(["not json", ["also", "bad"]])
        self.assertEqual(r.status, "ERROR")

    def test_provider_failure(self):
        r, _ = parse([LLMError("timeout")])
        self.assertEqual(r.status, "ERROR")
        self.assertIn("timeout", r.issues[0].message)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- Round 2


class AssignmentsAndObjectives(unittest.TestCase):
    def test_assignment_inferred_from_schedule(self):
        r, _ = parse([extraction([raw()])])
        self.assertEqual(r.details[0].assignment_id, "SUPPORT_L2")
        self.assertEqual(r.details[0].assignment_source, "schedule")
        self.assertIn("on SUPPORT_L2", r.confirmation_summary)

    def test_assignment_stated(self):
        r, _ = parse([extraction([raw(assignment="L2 queue")])])
        self.assertEqual((r.details[0].assignment_id, r.details[0].assignment_source), ("SUPPORT_L2", "stated"))

    def test_stated_assignment_differs_from_schedule_lowers_confidence(self):
        r, _ = parse([extraction([raw(assignment="Kannada desk")])])
        self.assertEqual(r.status, "READY")
        self.assertTrue(any("check the request" in a for a in r.assumptions))
        self.assertLess(r.confidence.score, 0.85)

    def test_unknown_assignment_blocks(self):
        r, _ = parse([extraction([raw(assignment="Mars base")])])
        self.assertEqual(r.status, "NEEDS_CLARIFICATION")
        self.assertIn("UNKNOWN_ASSIGNMENT", codes(r))

    def test_demo_sentence_objective(self):
        r, _ = parse([extraction([raw()], {"priority": "minimize_affected_employees"})],
                     text="Rahul is unavailable tomorrow from 9 to 5. Find a replacement but don't disturb "
                          "anyone already scheduled unless necessary.")
        self.assertEqual(r.preferences.priority.value, "minimize_affected_employees")


class AdHocConstraints(unittest.TestCase):
    def test_supported_ad_hoc_constraints(self):
        r, _ = parse([extraction([raw()], ad_hoc=[
            {"kind": "required_skill", "value": "Kannada", "text": "replacement must speak Kannada"},
            {"kind": "max_daily_hours", "value": 9, "text": "nobody over 9 hours"}])])
        self.assertEqual(r.status, "READY")
        self.assertEqual([(c.kind, c.value) for c in r.ad_hoc_constraints],
                         [("required_skill", "Kannada"), ("max_daily_hours", 9.0)])
        self.assertIn("replacement must speak Kannada", r.confirmation_summary)

    def test_unsupported_constraint_is_disclosed_not_dropped(self):
        r, _ = parse([extraction([raw()], ad_hoc=[{"kind": "other", "text": "pick someone cheerful"}])])
        self.assertEqual(r.status, "READY")  # non-blocking, but...
        self.assertEqual(r.unsupported_constraints, ["pick someone cheerful"])
        self.assertIn("Not enforced: pick someone cheerful", r.confirmation_summary)
        self.assertIn("UNSUPPORTED_CONSTRAINT", codes(r))

    def test_invalid_ad_hoc_value_is_unsupported(self):
        r, _ = parse([extraction([raw()], ad_hoc=[{"kind": "max_daily_hours", "value": 40, "text": "40h day"}])])
        self.assertEqual(r.unsupported_constraints, ["40h day"])


class ConfidenceAndMeta(unittest.TestCase):
    def test_clean_request_high_confidence(self):
        r, _ = parse([extraction([raw()])])
        self.assertEqual((r.confidence.level, r.confidence.score), ("high", 1.0))

    def test_vague_time_lowers_confidence(self):
        r, _ = parse([extraction([raw(start=None, end=None, time_expression="morning")])])
        self.assertLess(r.confidence.score, 1.0)
        self.assertIn("vague time interpreted", r.confidence.factors)

    def test_blocked_request_has_no_confidence(self):
        r, _ = parse([extraction([raw(mention="Sanjay")])])
        self.assertEqual(r.confidence.level, "none")

    def test_prompt_version_and_trace_recorded(self):
        r, _ = parse([extraction([raw()])])
        self.assertEqual(r.meta.prompt, "disruption_extraction@2.0.0")
        self.assertEqual(r.meta.provider, "mock")
        self.assertTrue(r.meta.trace_id)

    def test_text_output_is_repaired(self):
        import json
        text = "Sure! Here it is:\n```json\n" + json.dumps(extraction([raw()])) + "\n```"
        r, _ = parse([text])
        self.assertEqual(r.status, "READY")
