import itertools
import unittest

from core.models import DOMAINS, Disruption
from core.rules import schedule_violations
from core.validation import validate_dataset
from engine import solver_cpsat, solver_search
from engine.evaluate import evaluate, full_assignment
from engine.problem import RunSettings, build_problem
from engine.repair import generate_repair
from services.domains import demo_dataset


def ds_for(domain):
    return validate_dataset(demo_dataset(domain)).dataset


class EveryDomain(unittest.TestCase):
    def test_every_preset_produces_valid_minimal_repairs(self):
        for domain in DOMAINS:
            ds = ds_for(domain)
            for preset in ds.disruptions:
                with self.subTest(domain=domain, preset=preset.id):
                    res = generate_repair(ds, [preset])
                    self.assertIn(res.status, ("OPTIMAL", "FEASIBLE"))
                    self.assertTrue(res.options)
                    p = build_problem(ds, [preset])
                    for o in res.options:
                        self.assertEqual(evaluate(p, o.assignment, full_check=True).violations, [])
                        self.assertEqual(o.impact.unfilled_shifts, 0)
                        self.assertEqual(o.impact.skill_coverage_pct, 100.0)
                    best = res.options[0]
                    self.assertLess(best.impact.assignments_changed, res.baseline.assignments_changed)
                    self.assertEqual(len({o.title for o in res.options}), len(res.options))

    def test_alternatives_each_offer_a_tradeoff(self):
        res = generate_repair(ds_for("healthcare"), [ds_for("healthcare").disruptions[0]])
        a = res.options[0]
        for o in res.options[1:]:
            better = (o.fairness.fairness_score > a.fairness.fairness_score or
                      o.impact.overtime_hours_added < a.impact.overtime_hours_added or
                      o.impact.employees_affected < a.impact.employees_affected)
            self.assertTrue(better, o.title)


class HealthcareScenario(unittest.TestCase):
    def setUp(self):
        self.ds = ds_for("healthcare")
        self.icu = next(d for d in self.ds.disruptions if d.id == "DEMO-ICU")

    def test_why_not_reasons_come_from_rules_and_counterfactuals(self):
        res = generate_repair(self.ds, [self.icu])
        why = {r.employee_name: r for r in res.rejected}
        self.assertEqual(why["Elena Rostova"].reason_code, "REST_PERIOD_VIOLATION")      # mid night shift (frozen)
        self.assertEqual(why["Hannah Schmidt"].reason_code, "WOULD_CREATE_OVERTIME")
        self.assertIn("12h overtime", why["Hannah Schmidt"].detail)
        self.assertEqual(why["Lisa Wong"].reason_code, "MISSING_SKILL")
        self.assertNotIn("Rahul Sharma", why)                                            # the absent person

    def test_locked_and_excluded_are_respected(self):
        res = generate_repair(self.ds, [self.icu], RunSettings(excluded_employee_ids=["H17"], locked_employee_ids=["H04"]))
        for o in res.options:
            self.assertNotIn("H17", [s.employee_id for s in o.selected])
            self.assertNotIn("H04", {c.from_employee_id for c in o.changes})

    def test_no_overtime_and_no_cover_is_partial_not_fabricated(self):
        res = generate_repair(self.ds, [self.icu], RunSettings(excluded_employee_ids=["H17", "H04", "H14", "H02"],
                                                               allow_overtime=False))
        self.assertEqual(res.status, "PARTIAL")
        self.assertTrue(res.infeasibility_reasons)
        self.assertEqual(res.options[0].impact.unfilled_shifts, 1)

    def test_what_if_removal_restores_availability(self):
        res = generate_repair(self.ds, [self.icu], RunSettings(removed_unavailability=["H01"]))
        self.assertFalse(res.disrupted_shifts)

    def test_evidence_is_computed(self):
        res = generate_repair(self.ds, [self.icu])
        s = res.options[0].selected[0]
        self.assertTrue(s.skills_match)
        self.assertEqual(s.weekly_hours_after - s.weekly_hours_before, 12)
        self.assertEqual(s.overtime_hours_added, 0)


class Grandfathering(unittest.TestCase):
    def test_preexisting_issue_does_not_force_changes(self):
        raw = demo_dataset("manufacturing")
        raw["employees"] = [dict(e, certifications=[]) if e["id"] == "M15" else e for e in raw["employees"]]
        ds = validate_dataset(raw).dataset
        res = generate_repair(ds, [next(d for d in ds.disruptions if d.id == "DEMO-CNC")])
        moved = {c.from_employee_id for o in res.options for c in o.changes}
        self.assertNotIn("M15", moved)          # uncertified on paper, but not this disruption's business


class SearchIsExact(unittest.TestCase):
    """The fallback search must find the true optimum (checked by brute force on a small instance)."""

    def test_matches_brute_force(self):
        ds = ds_for("logistics")
        d = ds.disruptions[0]
        p = build_problem(ds, [d])
        affected = sorted({s for s in p.slots if p.shifts[s].date == d.date})[:6]
        best_bf = None
        others = {s: p.original.get(s) for s in p.slots if s not in affected}
        options = [p.candidates[s] + [None] for s in affected]
        for combo in itertools.product(*options):
            a = dict(others)
            a.update(dict(zip(affected, combo)))
            ev = evaluate(p, a)
            if ev.valid and (best_bf is None or ev.cost < best_bf):
                best_bf = ev.cost
        found = solver_search.solve(p, "recommended")
        self.assertAlmostEqual(evaluate(p, found).cost, best_bf)

    def test_every_returned_assignment_passes_the_global_rule_check(self):
        ds = ds_for("manufacturing")
        p = build_problem(ds, [ds.disruptions[0]])
        for a in solver_search.enumerate_repairs(p)[:200]:
            ev = evaluate(p, a)
            if ev.valid:
                full = full_assignment(p, a)
                self.assertEqual([v for v in schedule_violations(ds, full, p.unavailable, p.constraints)
                                  if v["rule"] in ("overlap", "rest", "qualification")
                                  and any(x in (v.get("shift_ids") or [v.get("shift_id")]) for x in ev.changed_slots)], [])


@unittest.skipUnless(solver_cpsat.AVAILABLE, "OR-Tools not installed")
class CpSatParity(unittest.TestCase):
    """Run on machines with OR-Tools: CP-SAT must be at least as good as the exact bounded search."""

    def test_cpsat_matches_search(self):
        for domain in DOMAINS:
            ds = ds_for(domain)
            for preset in ds.disruptions:
                p = build_problem(ds, [preset])
                for strategy in ("recommended", "min_overtime", "max_fairness"):
                    a = solver_cpsat.solve(p, strategy)
                    b = solver_search.solve(p, strategy)
                    self.assertIsNotNone(a, (domain, preset.id))
                    self.assertTrue(evaluate(p, a, full_check=True).valid)
                    self.assertLessEqual(evaluate(p, a, strategy).cost, evaluate(p, b, strategy).cost + 1e-6,
                                         (domain, preset.id, strategy))


if __name__ == "__main__":
    unittest.main()
