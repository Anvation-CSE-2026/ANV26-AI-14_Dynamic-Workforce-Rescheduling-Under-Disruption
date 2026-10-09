"""Must-have tests from the platform spec (§41–§48): hard and soft constraints separately, fairness with a
rolling window, AI conflict suggestions that can't bypass hard rules, workforce requests, rewards on
completion only, three-level notifications, imports, constraint center, repair center, what-if and
multi-user isolation. Reference "now" in every dataset: 2026-10-08 00:00 (Thursday, ISO week 41)."""

from __future__ import annotations

import csv
import io
import unittest

from ai.providers.mock import MockProvider
from ai.service import AIService
from analytics import fairness_engine
from core import xlsx
from core.models import Availability, Contribution, Dataset
from engine.evaluate import evaluate
from engine.problem import build_problem
from engine.repair import generate_repair
from services import constraint_center, notify, workforce
from services.auth import AuthError, AuthService, check_password
from services.workspace import ResQWork, ResQWorkError
from store import SqliteStore

DAY = "2026-10-09"


def base(**over) -> dict:
    """Small org: S1 (skill X, 09:00–17:00) is Asha's; Bala and Dev also have X; Chen has only Y."""
    emp = lambda i, n, skills, **kw: {"id": i, "name": n, "role": "Engineer", "department": "OPS",  # noqa: E731
                                      "email": f"{n.lower()}@example.com", "skills": skills, **kw}
    raw = {
        "organization": {"id": "org-test", "name": "Test Org", "domain": "technology"},
        "reference_date": "2026-10-08", "reference_time": "00:00",
        "departments": [{"id": "OPS", "name": "Operations"}],
        "employees": [emp("A", "Asha", ["X"]), emp("B", "Bala", ["X"]), emp("C", "Chen", ["Y"]),
                      emp("D", "Dev", ["X"])],
        "shifts": [{"id": "S1", "date": DAY, "start": "09:00", "end": "17:00", "assignment": "Platform On-call",
                    "department": "OPS", "required_skills": ["X"]}],
        "existing_schedule": [{"shift_id": "S1", "employee_id": "A"}],
        "constraints": {"min_rest_hours": 11},
    }
    for k, v in over.items():
        raw[k] = v
    return raw


def ds_of(raw: dict) -> Dataset:
    return Dataset.model_validate(raw)


def app_with(raw: dict, ai: AIService | None = None):
    app = ResQWork(SqliteStore(":memory:"), ai)
    report, ws = app.load_dataset(raw, "test")
    assert ws, report.summary
    return app, ws["org"]


def check(ds: Dataset, eid: str, shift_id: str = "S1", unavailable=None) -> dict:
    s = ds.shift(shift_id)
    others = {k: v for k, v in ds.assignment_map().items() if k != shift_id}
    unav = unavailable if unavailable is not None else [a for a in ds.availability]
    return workforce.evaluate_person(ds, ds.employee(eid), s, unav, others)


def failed(result: dict) -> str | None:
    return result["failed"]["name"] if result["failed"] else None


class HardConstraints(unittest.TestCase):
    """§41: every hard violation results in rejection, both in the eligibility filter and the optimizer's validator."""

    def assert_rejected(self, raw: dict, eid: str, expected: str, code: str | None = None):
        ds = ds_of(raw)
        r = check(ds, eid)
        self.assertFalse(r["eligible"], expected)
        self.assertEqual(failed(r), expected)
        if code:
            p = build_problem(ds, [])
            self.assertNotIn(eid, p.candidates["S1"])
            self.assertEqual(p.excluded[("S1", eid)].code, code)

    def test_1_employee_on_leave(self):
        self.assert_rejected(base(availability=[{"employee_id": "B", "date": DAY, "kind": "leave", "reason": "leave"}]),
                             "B", "Availability", "UNAVAILABLE")

    def test_2_employee_unavailable(self):
        self.assert_rejected(base(availability=[{"employee_id": "B", "date": DAY, "start": "08:00", "end": "12:00",
                                                 "kind": "unavailable"}]), "B", "Availability", "UNAVAILABLE")

    def test_3_double_booking(self):
        raw = base()
        raw["shifts"].append({"id": "S2", "date": DAY, "start": "10:00", "end": "14:00", "assignment": "Support",
                              "required_skills": ["X"]})
        raw["existing_schedule"].append({"shift_id": "S2", "employee_id": "B"})
        self.assert_rejected(raw, "B", "No double booking")
        ds = ds_of(raw)
        p = build_problem(ds, [])
        ev = evaluate(p, {"S1": "B", "S2": "B"}, full_check=True)       # optimizer validator rejects it too
        self.assertTrue(any(v["rule"] == "overlap" for v in ev.violations))
        self.assertFalse(ev.valid)

    def test_4_skill_mismatch(self):
        self.assert_rejected(base(), "C", "Required skill", "MISSING_SKILL")

    def test_5_certification_mismatch(self):
        raw = base()
        raw["shifts"][0]["required_certifications"] = ["ACLS"]
        raw["employees"][0]["certifications"] = ["ACLS"]
        self.assert_rejected(raw, "B", "Certification", "MISSING_CERTIFICATION")

    def test_6_max_daily_hours(self):
        raw = base(constraints={"min_rest_hours": 0})
        raw["employees"][1]["max_daily_hours"] = 8
        raw["shifts"].append({"id": "S0", "date": DAY, "start": "05:00", "end": "09:00", "assignment": "Early"})
        raw["existing_schedule"].append({"shift_id": "S0", "employee_id": "B"})
        self.assert_rejected(raw, "B", "Daily hours")

    def test_7_max_weekly_hours(self):
        raw = base(constraints={"min_rest_hours": 0, "allow_overtime": False})
        raw["employees"][1].update(contracted_weekly_hours=10, max_weekly_hours=10)
        raw["shifts"].append({"id": "S0", "date": "2026-10-06", "start": "09:00", "end": "17:00", "assignment": "Early"})
        raw["existing_schedule"].append({"shift_id": "S0", "employee_id": "B"})
        self.assert_rejected(raw, "B", "Weekly hours")

    def test_8_minimum_rest(self):
        raw = base()
        raw["shifts"].append({"id": "S0", "date": "2026-10-08", "start": "20:00", "end": "02:00", "assignment": "Night"})
        raw["existing_schedule"].append({"shift_id": "S0", "employee_id": "B"})
        self.assert_rejected(raw, "B", "Rest requirement")

    def test_9_minimum_staffing(self):
        raw = base()
        raw["employees"] = [e for e in raw["employees"] if e["id"] in ("A", "C")]   # nobody else can cover S1
        app, org = app_with(raw)
        app.report_disruption(org, structured={"employee_id": "A", "date": DAY})
        p = app.generate_repair(org)
        self.assertEqual(p["result"]["status"], "PARTIAL")
        with self.assertRaises(ResQWorkError) as cm:          # leaving a covered shift uncovered is not silent
            app.approve(org, p["id"])
        self.assertEqual(cm.exception.status, 409)
        res = constraint_center.test(app.store, org, app.dataset(org))
        self.assertTrue(any(r["constraint_id"] == "C010" for r in res["results"]))

    def test_10_no_qualified_replacement(self):
        raw = base()
        raw["shifts"][0]["required_skills"] = ["Z"]
        raw["employees"][0]["skills"] = ["X", "Z"]
        ds = ds_of(raw)
        from core.models import Disruption
        res = generate_repair(ds, [Disruption(id="d", employee_id="A", date=DAY)])
        best = res.options[0]
        self.assertIsNone(best.assignment.get("S1"), "never assigns an unqualified person")
        self.assertTrue(res.unresolved)
        self.assertEqual(res.unresolved[0].bottleneck, "availability", "the only Z-qualified person is the absent one")


class SoftConstraints(unittest.TestCase):
    """§41: soft constraints only reorder people who all pass every hard rule."""

    def winner(self, raw: dict) -> str:
        from core.models import Disruption
        res = generate_repair(ds_of(raw), [Disruption(id="d", employee_id="A", date=DAY)], strategies=["recommended"])
        return res.options[0].assignment["S1"]

    def two(self, **b_over) -> dict:
        raw = base()
        raw["employees"] = [e for e in raw["employees"] if e["id"] in ("A", "B", "D")]
        raw["employees"][1].update(b_over)
        return raw

    def test_fairness_and_recent_volunteer_contribution(self):
        raw = self.two(history={"contributions": [{"date": "2026-10-05", "kind": "volunteer", "hours": 8}] * 4})
        self.assertEqual(self.winner(raw), "D")

    def test_workload_balance(self):
        raw = self.two()
        for i in range(3):                       # Bala already has 24h this week
            raw["shifts"].append({"id": f"W{i}", "date": "2026-10-0" + str(5 + i), "start": "08:00", "end": "16:00",
                                  "assignment": "Ops"})
            raw["existing_schedule"].append({"shift_id": f"W{i}", "employee_id": "B"})
        raw["constraints"] = {"min_rest_hours": 0}
        self.assertEqual(self.winner(raw), "D")

    def test_minimize_schedule_changes(self):
        from core.models import Disruption
        res = generate_repair(ds_of(base()), [Disruption(id="d", employee_id="A", date=DAY)])
        self.assertEqual(res.options[0].impact.assignments_changed, 1, "one direct swap, nothing else moves")

    def test_minimize_overtime(self):
        raw = self.two(contracted_weekly_hours=4, max_weekly_hours=48)
        self.assertEqual(self.winner(raw), "D")

    def test_employee_preference(self):
        raw = self.two(preferences={"avoid_shift_types": ["Day"]})
        raw["shifts"][0]["shift_type"] = "Day"
        self.assertEqual(self.winner(raw), "D")

    def test_location_preference(self):
        raw = self.two(location="North")
        raw["employees"][2]["location"] = "South"
        raw["shifts"][0]["location"] = "South"
        self.assertEqual(self.winner(raw), "D")

    def test_continuity(self):
        raw = self.two()
        raw["shifts"].append({"id": "P0", "date": "2026-10-12", "start": "09:00", "end": "17:00",
                              "assignment": "Platform On-call"})
        raw["existing_schedule"].append({"shift_id": "P0", "employee_id": "D"})
        raw["shifts"].append({"id": "P1", "date": "2026-10-12", "start": "09:00", "end": "17:00", "assignment": "Ops"})
        raw["existing_schedule"].append({"shift_id": "P1", "employee_id": "B"})
        self.assertEqual(self.winner(raw), "D", "Dev already works Platform On-call")

    def test_soft_never_overrides_hard(self):
        raw = self.two(history={"contributions": [{"date": "2026-10-05", "kind": "volunteer", "hours": 8}] * 6})
        raw["availability"] = [{"employee_id": "D", "date": DAY, "kind": "leave"}]
        self.assertEqual(self.winner(raw), "B", "the fairer choice is on leave, so the only eligible person is used")


class Fairness(unittest.TestCase):
    """§42: A (40h, 8 volunteer) vs B (36h, 2 volunteer) → B first; old contributions decay."""

    def setUp(self):
        raw = base()
        raw["employees"] = [e for e in raw["employees"] if e["id"] in ("A", "B")]
        raw["employees"][0]["name"] = "Employee A"
        raw["employees"][1]["name"] = "Employee B"
        raw["constraints"] = {"min_rest_hours": 0}
        raw["shifts"], raw["existing_schedule"] = [], []
        for eid, hours in (("A", 40), ("B", 36)):
            for i, h in enumerate([8] * (hours // 8) + ([hours % 8] if hours % 8 else [])):
                raw["shifts"].append({"id": f"{eid}{i}", "date": f"2026-10-{5 + i:02d}", "start": "08:00",
                                      "end": f"{8 + h:02d}:00", "assignment": "Ops"})
                raw["existing_schedule"].append({"shift_id": f"{eid}{i}", "employee_id": eid})
        self.raw = raw

    def with_volunteers(self, a_date: str) -> Dataset:
        raw = dict(self.raw)
        emps = [dict(e) for e in raw["employees"]]
        emps[0]["history"] = {"contributions": [{"date": a_date, "kind": "volunteer", "hours": 4}] * 8}
        emps[1]["history"] = {"contributions": [{"date": "2026-10-01", "kind": "volunteer", "hours": 4}] * 2}
        raw["employees"] = emps
        return ds_of(raw)

    def test_b_ranks_above_a(self):
        ds = self.with_volunteers("2026-10-02")
        ranked = fairness_engine.rank(ds, ["A", "B"])
        self.assertEqual([r["employee_name"] for r in ranked], ["Employee B", "Employee A"])
        prof = {r["employee_id"]: r for r in ranked}
        self.assertEqual((prof["A"]["regular_hours"], prof["B"]["regular_hours"]), (40, 36))
        self.assertEqual((prof["A"]["volunteer_assignments"], prof["B"]["volunteer_assignments"]), (8, 2))
        # the optimizer agrees: B is the cheaper (fairer) person to give extra work
        p = build_problem(ds, [])
        from engine.evaluate import fairness_units
        self.assertLess(fairness_units(p, "B"), fairness_units(p, "A"))

    def test_old_contributions_decay(self):
        recent = fairness_engine.contribution_load(self.with_volunteers("2026-10-02").employee("A"),
                                                   ds_of(self.raw).today, 30)
        old_ds = self.with_volunteers("2026-07-01")         # ~99 days ago: outside the 30-day window
        old = fairness_engine.contribution_load(old_ds.employee("A"), old_ds.today, 30)
        self.assertLess(old, recent / 10, "old volunteer work has much less influence")
        self.assertEqual(fairness_engine.profile(old_ds, old_ds.employee("A"))["volunteer_assignments"], 0)
        self.assertEqual(fairness_engine.profile(old_ds, old_ds.employee("A"))["older_contributions"], 8)
        ranked = fairness_engine.rank(old_ds, ["A", "B"])
        self.assertEqual(ranked[0]["employee_id"], "A", "no permanent penalty for having volunteered")

    def test_window_is_configurable(self):
        ds = self.with_volunteers("2026-09-20")
        load7 = fairness_engine.contribution_load(ds.employee("A"), ds.today, 7)
        load90 = fairness_engine.contribution_load(ds.employee("A"), ds.today, 90)
        self.assertLess(load7, load90)


class AIConflictSuggestions(unittest.TestCase):
    """§43: AI writes suggestions, but only candidates that pass hard constraints survive."""

    def test_llm_cannot_bypass_hard_constraints(self):
        raw = base(availability=[{"employee_id": "D", "date": DAY, "kind": "leave"}])
        mock = MockProvider({"write_conflict_advice": {
            "summary": "Asha is unavailable on 2026-10-09 09:00–17:00, so Platform On-call needs cover.",
            "strategies": ["Reassign to Bala.", "Request volunteers."],
            "suggested_employee_ids": ["C", "D", "B"]}})
        app, org = app_with(raw, AIService(mock))
        app.report_disruption(org, structured={"employee_id": "A", "date": DAY})
        out = app.conflict_assistant(org)
        c = out["conflicts"][0]
        self.assertEqual(c["type"], "unavailable")
        self.assertEqual(c["recommended"]["employee_id"], "B")
        self.assertEqual(set(c["ai_discarded"]), {"C", "D"}, "Chen lacks skill X, Dev is on leave")
        self.assertIn("mock", c["explained_by"])
        self.assertTrue(all(ch["status"] == "PASS" for ch in c["recommended"]["checks"] if ch["label"] != "Workload fairness"))
        self.assertIn(c["confidence"], ("high", "medium", "low"))
        self.assertTrue(any(a["kind"] == "workforce_request" for a in c["alternatives"]))

    def test_template_without_llm(self):
        app, org = app_with(base())
        app.report_disruption(org, structured={"employee_id": "A", "date": DAY})
        c = app.conflict_assistant(org)["conflicts"][0]
        self.assertEqual(c["explained_by"], "template (facts only)")
        self.assertIn(c["recommended"]["employee_id"], ("B", "D"))
        self.assertNotIn("AM", c["explanation"] + c["why"])
        self.assertNotIn("PM", c["explanation"] + c["why"])


class WorkforceRequests(unittest.TestCase):
    """§44: a task needs 5, 3 are assigned → gap of 2; eligible search; insufficient workforce message."""

    def setUp(self):
        raw = base()
        raw["employees"] += [{"id": f"E{i}", "name": f"Extra {i}", "role": "Engineer", "skills": ["X"]} for i in range(4)]
        raw["shifts"] = [{"id": f"T{i}", "date": DAY, "start": "07:00", "end": "19:00", "assignment": "Emergency Support",
                          "required_skills": ["X"], "attributes": {"required_headcount": 5}} for i in range(3)]
        raw["existing_schedule"] = [{"shift_id": "T0", "employee_id": "A"}, {"shift_id": "T1", "employee_id": "B"},
                                    {"shift_id": "T2", "employee_id": "D"}]
        self.app, self.org = app_with(raw)

    def test_gap_detected_and_two_found(self):
        gaps = self.app.staffing_gaps(self.org)
        self.assertEqual((gaps[0]["required"], gaps[0]["assigned"], gaps[0]["gap"]), (5, 3, 2))
        found = self.app.find_employees(self.org, {"task": "Emergency Support", "date": DAY, "start": "07:00",
                                                   "end": "19:00", "skills": ["X"], "additional_needed": 2})
        self.assertTrue(found["sufficient"])
        self.assertEqual({c["employee_id"] for c in found["eligible"]}, {"E0", "E1", "E2", "E3"},
                         "A, B and D are already on the task (double booking); Chen lacks the skill")

    def test_insufficient_workforce(self):
        found = self.app.find_employees(self.org, {"task": "Specialist", "date": DAY, "start": "07:00", "end": "19:00",
                                                   "skills": ["Q"], "additional_needed": 2})
        self.assertFalse(found["sufficient"])
        self.assertEqual(found["message"], "No sufficient eligible workforce available.")
        wfr = self.app.create_workforce_request(self.org, {"task": "Specialist", "date": DAY, "start": "07:00",
                                                           "end": "19:00", "skills": ["Q"], "additional_needed": 2}, "admin")
        self.assertEqual(wfr["message"], workforce.INSUFFICIENT)
        with self.assertRaises(ResQWorkError):
            self.app.request_volunteers(self.org, wfr["id"], "volunteers", "admin")

    def test_volunteers_only_eligible_and_no_auto_assign(self):
        w = self.app.create_workforce_request(self.org, {"task": "Emergency Support", "date": DAY, "start": "07:00",
                                                         "end": "19:00", "skills": ["X"], "additional_needed": 2,
                                                         "required_employees": 5}, "admin")
        out = self.app.request_volunteers(self.org, w["id"], "broadcast", "admin")
        invited = set(out["request"]["invited"])
        self.assertEqual(invited, {"E0", "E1", "E2", "E3"})
        notified = {n["employee_id"] for n in self.app.notifications(self.org)}
        self.assertNotIn("C", notified, "ineligible employees are never contacted")
        before = len(self.app.dataset(self.org).shifts)
        self.app.volunteer(self.org, w["id"], "E1", True)
        self.assertEqual(len(self.app.dataset(self.org).shifts), before, "volunteering doesn't assign")
        with self.assertRaises(ResQWorkError):
            self.app.volunteer(self.org, w["id"], "C", True)     # not invited


class Rewards(unittest.TestCase):
    """§45: no reward for volunteering; reward after completion; points, badge, achievement, history."""

    def test_reward_only_after_completion(self):
        t = WorkforceRequests()
        t.setUp()
        app, org = t.app, t.org
        w = app.create_workforce_request(org, {"task": "Emergency Support", "date": DAY, "start": "07:00",
                                               "end": "19:00", "skills": ["X"], "additional_needed": 1}, "admin")
        app.request_volunteers(org, w["id"], "volunteers", "admin")
        app.volunteer(org, w["id"], "E2", True)
        self.assertEqual(app.employee_rewards(org, "E2")["points_total"], 0, "no reward for clicking Volunteer")
        doc = app.decide_volunteer(org, w["id"], "E2", True, "admin")
        self.assertEqual(doc["status"], "filled")
        self.assertEqual(app.dataset(org).assignment_map()[doc["assignments"][0]["shift_id"]], "E2")
        self.assertEqual(app.employee_rewards(org, "E2")["points_total"], 0, "assigned is not completed")
        app.complete_workforce_assignment(org, w["id"], "E2", "admin")
        r = app.employee_rewards(org, "E2")
        self.assertEqual(r["points_total"], 25)
        self.assertIn("team_supporter", [b["id"] for b in r["badges"]])
        self.assertTrue(next(a for a in r["achievements"] if a["id"] == "first_cover")["unlocked"])
        self.assertEqual(r["history"][0]["points"], 25)
        ledger = app.dataset(org).employee("E2").history.contributions
        self.assertTrue(ledger and ledger[-1].completed and ledger[-1].kind == "volunteer")

    def test_rewards_do_not_drive_scheduling(self):
        raw = base()
        ds1 = ds_of(raw)
        app, org = app_with(raw)
        app.give_reward(org, "B", "team_contribution", "Great handover notes", "admin")
        ds2 = app.dataset(org)
        self.assertEqual(fairness_engine.contribution_load(ds1.employee("B"), ds1.today),
                         fairness_engine.contribution_load(ds2.employee("B"), ds2.today))

    def test_admin_configurable_rules(self):
        app, org = app_with(base())
        cfg = app.rewards_overview(org)["config"]
        rules = [{**r, "points": 50, "requires_approval": True} if r["trigger"] == "coverage_completed" else r
                 for r in cfg["rules"]]
        app.save_reward_config(org, rules, "admin")
        app.report_disruption(org, structured={"employee_id": "A", "date": DAY})
        p = app.generate_repair(org)
        app.approve(org, p["id"])
        done = app.complete_repair(org, p["id"], "admin")["completed"]
        self.assertEqual(done[0]["status"], "pending_approval")
        e = app.approve_reward(org, done[0]["id"], "admin")
        self.assertEqual((e["status"], e["points"]), ("rewarded", 50))


class Notifications(unittest.TestCase):
    """§46: L1 dashboard+email · L2 dashboard+email, escalates to WhatsApp+SMS · L3 all four · no voice."""

    def setUp(self):
        self.app, self.org = app_with(base())

    def channels(self, n):
        return [c["channel"] for c in n["channels"]]

    def test_levels(self):
        l1 = self.app.notify_employee(self.org, "B", 1, "info", "Normal update", "x")
        l2 = self.app.notify_employee(self.org, "B", 2, "action", "Please confirm", "x")
        l3 = self.app.notify_employee(self.org, "B", 3, "emergency", "Critical shortage", "x")
        self.assertEqual(self.channels(l1), ["dashboard", "email"])
        self.assertEqual(self.channels(l2), ["dashboard", "email"])
        self.assertEqual(self.channels(l3), ["dashboard", "email", "whatsapp", "sms"])
        self.assertEqual((l1["color"], l2["color"], l3["color"]), ("green", "orange", "red"))
        self.assertNotIn("voice", self.channels(l3))
        self.assertTrue(all(c["provider"] in ("in-app", "simulated") for c in l3["channels"] if c["status"] != "skipped"))

    def test_l2_escalates_when_unacknowledged(self):
        notify.save_settings(self.app.store, self.org, 0)
        n = self.app.notify_employee(self.org, "B", 2, "action", "Please confirm", "x")
        acked = self.app.notify_employee(self.org, "D", 2, "action", "Please confirm", "x")
        self.app.acknowledge(self.org, acked["id"], "D")
        out = self.app.run_escalations(self.org)
        self.assertEqual([x["id"] for x in out], [n["id"]])
        n = self.app.store.get("notification", n["id"], self.org)
        self.assertEqual(self.channels(n), ["dashboard", "email", "whatsapp", "sms"])
        self.assertEqual((n["escalation_level"], n["status"]), (1, "escalated"))
        self.assertEqual(self.app.run_escalations(self.org), [], "escalates once")
        rows = notify.audit_rows([n])
        self.assertEqual({r["channel"] for r in rows}, {"dashboard", "email", "whatsapp", "sms"})
        for key in ("notification_id", "employee_id", "severity", "type", "message", "channel", "created_at",
                    "sent_at", "delivered_at", "acknowledged_at", "status", "escalation_level"):
            self.assertIn(key, rows[0])

    def test_not_escalated_inside_window(self):
        notify.save_settings(self.app.store, self.org, 30)
        self.app.notify_employee(self.org, "B", 2, "action", "Please confirm", "x")
        self.assertEqual(self.app.run_escalations(self.org), [])


def _csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


class Imports(unittest.TestCase):
    """§47: valid, duplicate, missing/invalid email, missing id, missing skill, invalid time, existing, mixed."""

    HEADER = ["employee_id", "name", "email", "phone", "department", "role", "skills", "availability_start",
              "availability_end", "max_hours", "certifications", "status"]

    def setUp(self):
        self.app, self.org = app_with(base())
        self.store = self.app.store
        self.auth = AuthService(self.store)

    def rows(self):
        return [self.HEADER,
                ["N1", "Nia Rao", "nia@example.com", "+91 90000 00001", "OPS", "Engineer", "X;Y", "07:00", "19:00", "40", "", "active"],
                ["N2", "Om Das", "om@example.com", "+91 90000 00002", "NEW", "Engineer", "X", "", "", "", "", ""],
                ["N2", "Om Again", "om2@example.com", "+91 90000 00003", "OPS", "Engineer", "X", "", "", "", "", ""],
                ["N3", "No Mail", "", "+91 90000 00004", "OPS", "Engineer", "X", "", "", "", "", ""],
                ["N4", "Bad Mail", "not-an-email", "+91 90000 00005", "OPS", "Engineer", "X", "", "", "", "", ""],
                ["", "No Id", "noid@example.com", "+91 90000 00006", "OPS", "Engineer", "X", "", "", "", "", ""],
                ["N5", "No Skill", "noskill@example.com", "+91 90000 00007", "OPS", "Engineer", "", "", "", "", "", ""],
                ["N6", "Bad Time", "badtime@example.com", "+91 90000 00008", "OPS", "Engineer", "X", "9 AM", "5 PM", "", "", ""],
                ["A", "Asha Again", "asha.new@example.com", "+91 90000 00009", "OPS", "Engineer", "X", "", "", "", "", ""]]

    def test_preview_reports_every_row(self):
        job = self.app.preview_employee_import(self.org, "people.csv", _csv(self.rows()), set(), "admin")
        r = job["report"]
        self.assertEqual(r["total"], 9, "nothing silently dropped")
        self.assertEqual((r["valid"], r["duplicates"], r["existing"], r["invalid"]), (2, 1, 1, 5))
        by_row = {x["row"]: x for x in r["rows"]}
        self.assertIn("email is required", by_row[5]["errors"])
        self.assertTrue(any("not valid" in e for e in by_row[6]["errors"]))
        self.assertIn("employee_id is required", by_row[7]["errors"])
        self.assertIn("skills is required", by_row[8]["errors"])
        self.assertTrue(any("24-hour" in e for e in by_row[9]["errors"]))
        self.assertTrue(any("department 'NEW' is new" in w for w in by_row[3]["warnings"]))

    def test_confirm_creates_only_new_with_one_time_hashed_passwords(self):
        job = self.app.preview_employee_import(self.org, "people.csv", _csv(self.rows()), set(), "admin")
        out = self.app.confirm_employee_import(self.org, job["id"], self.auth, set(), "admin")
        ds = self.app.dataset(self.org)
        self.assertEqual({e["id"] for e in out["created"]}, {"N1", "N2"})
        self.assertEqual(ds.employee("A").name, "Asha", "existing employees are never replaced")
        self.assertEqual(len(ds.employees), 6)
        self.assertNotIn("password", str(out).lower().replace("temporary", "").replace("credentials", "")
                         .replace("skipped_accounts", ""))
        rows = xlsx.records(self.app.take_credentials(out["credentials_token"]))
        self.assertEqual([r["employee_id"] for r in rows], ["N1", "N2"])
        pw = rows[0]["temporary_password"]
        with self.assertRaises(ResQWorkError):
            self.app.take_credentials(out["credentials_token"])           # exported once
        stored = self.store.get("user", "nia@example.com", "_global")
        self.assertNotEqual(stored["password"], pw)
        self.assertTrue(check_password(pw, stored["password"]) and stored["must_change_password"])
        login = self.auth.login("nia@example.com", pw)
        self.assertTrue(login["user"]["must_change_password"])
        self.assertNotIn("password", login["user"])
        with self.assertRaises(AuthError):
            self.auth.change_password("nia@example.com", pw, "short")
        self.auth.change_password("nia@example.com", pw, "N3w-passw0rd")
        self.assertFalse(self.store.get("user", "nia@example.com", "_global")["must_change_password"])
        # availability window 07:00–19:00 became real unavailability outside it
        self.assertTrue(any(a.employee_id == "N1" and a.start == "19:00" for a in ds.availability))
        with self.assertRaises(ResQWorkError):
            self.app.confirm_employee_import(self.org, job["id"], self.auth, set(), "admin")

    def test_xlsx_import(self):
        job = self.app.preview_employee_import(self.org, "people.xlsx", xlsx.write(self.rows()[:3]), set(), "admin")
        self.assertEqual(job["report"]["valid"], 2)

    def test_schedule_import(self):
        rows = [["schedule_id", "employee_id", "date", "shift_start", "shift_end", "location", "task", "required_skill"],
                ["SC1", "B", "2026-10-10", "07:00", "15:00", "Hub", "Night Ops", "X"],
                ["SC1", "D", "2026-10-10", "07:00", "15:00", "Hub", "Night Ops", "X"],
                ["SC2", "ZZ", "2026-10-10", "07:00", "15:00", "Hub", "Night Ops", "X"],
                ["SC3", "C", "2026-10-10", "7 PM", "15:00", "Hub", "Night Ops", "X"],
                ["SC4", "C", "2026-10-11", "07:00", "15:00", "Hub", "Night Ops", "X"],
                ["SC5", "A", DAY, "10:00", "12:00", "Hub", "Review", "X"]]
        job = self.app.preview_schedule_import(self.org, "sched.csv", _csv(rows), "admin")
        r = {x["row"]: x for x in job["report"]["rows"]}
        self.assertEqual(r[2]["status"], "valid")
        self.assertEqual(r[3]["status"], "duplicate")
        self.assertTrue(any("doesn't exist" in e for e in r[4]["errors"]))
        self.assertTrue(any("24-hour" in e for e in r[5]["errors"]))
        self.assertTrue(any("skill mismatch" in w for w in r[6]["warnings"]))
        self.assertTrue(r[7].get("hard_warning") and any("double booking" in w for w in r[7]["warnings"]))
        out = self.app.confirm_schedule_import(self.org, job["id"], False, "admin")
        self.assertEqual(out["imported"], 2, "valid rows; the double-booking row needs explicit consent")
        self.assertEqual(self.app.dataset(self.org).assignment_map()["SC1"], "B")

    def test_templates(self):
        from services import importers
        data, name, _ = importers.template("employees", "xlsx")
        self.assertEqual(list(xlsx.records(data)[0])[:7], list(importers.EMPLOYEE_REQUIRED))
        self.assertTrue(name.endswith(".xlsx"))


class ConstraintCenter(unittest.TestCase):
    def setUp(self):
        self.app, self.org = app_with(base())

    def row(self, cid):
        return next(r for r in self.app.constraints(self.org)["constraints"] if r["constraint_id"] == cid)

    def test_catalog_and_edits(self):
        cat = self.app.constraints(self.org)["constraints"]
        self.assertTrue({"HARD", "SOFT"} <= {r["type"] for r in cat})
        self.assertEqual(self.row("C006")["value"], 11)
        self.app.update_constraint(self.org, "C006", {"value": 12}, "admin")
        self.assertEqual(self.app.dataset(self.org).constraints.min_rest_hours, 12)
        self.app.update_constraint(self.org, "C006", {"enabled": False}, "admin")
        self.assertEqual(self.app.dataset(self.org).constraints.min_rest_hours, 0, "disabled means not enforced")
        self.app.update_constraint(self.org, "C006", {"enabled": True}, "admin")
        self.assertEqual(self.app.dataset(self.org).constraints.min_rest_hours, 12)
        with self.assertRaises(ResQWorkError):
            self.app.update_constraint(self.org, "C003", {"enabled": False}, "admin")
        self.app.update_constraint(self.org, "S004", {"weight": 100}, "admin")
        self.assertEqual(self.app.dataset(self.org).optimization.weights.fairness, 120)
        self.assertTrue(any(a["event_type"] == "CONSTRAINT_CHANGED" and a["previous"] == 11 and a["new"] == 12.0
                            for a in self.app.audit_trail(self.org)))

    def test_csv_and_json_import(self):
        bad = b"constraint_id,type,category,rule,priority,weight,enabled\nC9,MAYBE,skill,x,HIGH,100,true\n"
        res = self.app.import_constraints(self.org, "c.csv", bad, False, "admin")
        self.assertTrue(res["errors"])
        csv_ok = constraint_center.template_csv().encode()
        res = self.app.import_constraints(self.org, "c.csv", csv_ok, True, "admin")
        self.assertTrue(res["applied"])
        self.assertEqual(self.app.dataset(self.org).constraints.max_weekly_hours, 48)
        js = b'[{"constraint_id":"C030","type":"HARD","category":"required_skill","rule":"OPS needs Y",' \
             b'"scope":{"department":"OPS"},"value":["Y"]},' \
             b'{"constraint_id":"C031","type":"HARD","category":"union_rule","rule":"custom"}]'
        res = self.app.import_constraints(self.org, "c.json", js, True, "admin")
        self.assertEqual(res["unenforced"], ["C031"])
        self.assertEqual(constraint_center.run_overrides(self.app.store, self.org)["extra_required_skills"],
                         {"ICU": ["BLS"], "OPS": ["Y"]}, "the template's scoped rule and the JSON rule")
        tested = self.app.test_constraints(self.org)
        self.assertEqual(next(r for r in tested["results"] if r["constraint_id"] == "C031")["status"], "info")


class RepairCenterAndWhatIf(unittest.TestCase):
    def setUp(self):
        self.app, self.org = app_with(base())
        self.app.report_disruption(self.org, structured={"employee_id": "A", "date": DAY})
        self.p = self.app.generate_repair(self.org)

    def test_hide_show_complete(self):
        rc = self.app.repair_center(self.org)
        self.assertEqual(rc["counts"]["pending"], 1)
        self.app.set_repair_hidden(self.org, self.p["id"], True, "admin")
        self.assertEqual(self.app.repair_center(self.org)["repairs"], [])
        hidden = self.app.repair_center(self.org, include_hidden=True)["repairs"]
        self.assertTrue(hidden[0]["hidden"])
        self.assertIsNotNone(self.app.proposal(self.org, self.p["id"]), "hidden, never deleted")
        self.app.set_repair_hidden(self.org, self.p["id"], False, "admin")
        self.app.approve(self.org, self.p["id"])
        self.assertEqual(self.app.repair_center(self.org)["repairs"][0]["state"], "approved")
        self.app.complete_repair(self.org, self.p["id"], "admin")
        self.assertEqual(self.app.repair_center(self.org)["repairs"][0]["state"], "completed")

    def test_simulations_never_change_schedule(self):
        before = self.app.dataset(self.org).assignment_map()
        bad = self.app.simulate(self.org, self.p["id"], {"type": "assign", "shift_id": "S1", "employee_id": "C"})
        self.assertFalse(bad["feasible"])
        self.assertTrue(bad["conflicts_introduced"])
        ok = self.app.simulate(self.org, self.p["id"], {"type": "assign", "shift_id": "S1", "employee_id": "D"})
        self.assertTrue(ok["feasible"])
        self.assertEqual(ok["changes_count"], 1)
        more = self.app.simulate(self.org, self.p["id"], {"type": "add_employee"})
        self.assertTrue(more["feasible"])
        moved = self.app.simulate(self.org, self.p["id"], {"type": "move_shift", "shift_id": "S1", "start": "13:00",
                                                            "end": "21:00"})
        self.assertIn("13:00–21:00", moved["summary"])
        self.assertEqual(self.app.dataset(self.org).assignment_map(), before)


class MultiUser(unittest.TestCase):
    """§48: Admin A + Employees A, B, C: correct requests, notifications, rewards, audit, sync."""

    def test_flow(self):
        app, org = app_with(base())
        req = app.submit_availability(org, "B", "2026-10-12", None, None, "family", "time_off")
        self.assertIn(req["id"], [r["id"] for r in app.availability_requests(org)], "admin sees it at once")
        ar = app.create_admin_request(org, {"type": "schedule_confirmation", "title": "Confirm next week",
                                            "target": {"kind": "department", "value": "OPS"}}, "Admin A")
        self.assertEqual({r["employee_id"] for r in ar["recipients"]}, {"A", "B", "C", "D"})
        app.respond_admin_request(org, ar["id"], "B", "accept")
        app.respond_admin_request(org, ar["id"], "C", "decline", "on leave")
        mine = {r["id"]: r for r in app.admin_requests(org, "B")}
        self.assertEqual(mine[ar["id"]]["my_status"], "accepted")
        admin_view = next(r for r in app.admin_requests(org) if r["id"] == ar["id"])
        self.assertEqual({r["employee_id"]: r["status"] for r in admin_view["recipients"]},
                         {"A": "pending", "B": "accepted", "C": "declined", "D": "pending"})
        with self.assertRaises(ResQWorkError):
            app.respond_admin_request(org, ar["id"], "B", "acknowledge")       # not an action for this type
        app.decide_request(org, req["id"], "rejected", "busy week", "Admin A")
        b_notes = app.employee_view(org, "B")["notifications"]
        c_notes = app.employee_view(org, "C")["notifications"]
        self.assertTrue(any(n["title"].startswith("Request declined") for n in b_notes))
        self.assertFalse(any(n.get("request_id") == req["id"] for n in c_notes), "C never sees B's request")
        events = {a["event_type"] for a in app.audit_trail(org)}
        self.assertTrue({"REQUEST_SUBMITTED", "ADMIN_REQUEST_CREATED", "ADMIN_REQUEST_ACCEPTED",
                         "ADMIN_REQUEST_DECLINED", "REQUEST_REJECTED", "NOTIFICATION_SENT"} <= events)
        with self.assertRaises(ResQWorkError):
            app.respond_admin_request(org, "nope", "B", "accept")
        home = app.employee_home(org, "B")
        self.assertIn("rewards", home)
        self.assertTrue(all(n.get("opened_at") for n in app.employee_view(org, "B")["notifications"]),
                        "opening the dashboard marks notifications opened")

    def test_route_permissions(self):
        try:
            from app.api import routes
        except ImportError:
            self.skipTest("fastapi not installed")
        emp = routes.User(id="b", role="employee", org="org-test", employee_id="B")
        with self.assertRaises(ResQWorkError):
            routes.manager(emp)
        with self.assertRaises(ResQWorkError):
            routes.self_or_manager("C", emp)
        self.assertIs(routes.self_or_manager("B", emp), emp)
        admin = routes.User(id="a", role="admin", org="org-test")
        self.assertIs(routes.manager(admin), admin)
        with self.assertRaises(ResQWorkError):
            routes.employee_self(admin)


class Sessions(unittest.TestCase):
    def test_logout_revokes_session(self):
        auth = AuthService(SqliteStore(":memory:"))
        out = auth.register("ops@example.com", "s3cret-pass", "Ops", "admin")
        from services.auth import verify_token
        sid = verify_token(out["token"])["sid"]
        auth.check_session(sid)
        self.assertEqual(len(auth.sessions("ops@example.com", sid)), 1)
        auth.logout(sid, "ops@example.com")
        with self.assertRaises(AuthError):
            auth.check_session(sid)


class TwentyFourHourClock(unittest.TestCase):
    def test_voice_and_messages_use_24h(self):
        from services.voice import _clock
        self.assertEqual(_clock("17:30"), "17:30")
        self.assertEqual(_clock("07:00"), "07:00")
        app, org = app_with(base())
        app.report_disruption(org, structured={"employee_id": "A", "date": DAY, "start": "13:00", "end": "17:30"})
        p = app.generate_repair(org)
        app.approve(org, p["id"])
        text = " ".join(n["title"] + " " + n["body"] for n in app.notifications(org))
        self.assertNotRegex(text, r"\b\d{1,2}(:\d\d)? ?(AM|PM|am|pm)\b")


if __name__ == "__main__":
    unittest.main()


class FlagshipStory(unittest.TestCase):
    """§40/§64: the 100-employee demo tells the whole story with real engine output."""

    def test_story(self):
        import time
        from services.domains import scenario_dataset
        app = ResQWork(SqliteStore(":memory:"))
        _, ws = app.load_dataset(scenario_dataset("flagship-hospital-100"), "flagship")
        org = ws["org"]
        self.assertEqual(len(app.dataset(org).employees), 100)
        self.assertEqual(app.schedule_conflicts(org), [], "the baseline schedule is clean")
        app.report_disruption(org, preset_id="FLAG-ICU")
        t = time.monotonic()
        p = app.generate_repair(org)
        self.assertLess(time.monotonic() - t, 20)
        best = p["result"]["options"][0]
        self.assertEqual([c["to_employee_name"] for c in best["changes"]], ["Meera Pillai"])
        self.assertGreaterEqual(len(p["result"]["options"]), 2)
        why = {r["employee_name"]: r["reason_code"] for r in p["result"]["rejected"]}
        self.assertIn(why.get("Leela Iyer"), ("UNAVAILABLE",))
        self.assertIn(why.get("Arjun Menon"), ("HIGHER_IMPACT",), "valid, but less fair than Meera")
        ca = app.conflict_assistant(org)["conflicts"][0]
        self.assertEqual(ca["recommended"]["employee_name"], "Meera Pillai")
        self.assertEqual(ca["severity"], "critical")
        out = app.approve(org, p["id"])
        self.assertIn("ICU03", {n["employee_id"] for n in out["notifications"]})
        gap = next(g for g in app.staffing_gaps(org) if g["task"] == "Emergency Surge Team")
        self.assertEqual(gap["gap"], 2)
        w = app.create_workforce_request(org, {"task": gap["task"], "date": gap["date"], "start": gap["start"],
                                               "end": gap["end"], "skills": gap["skills"],
                                               "certifications": gap["certifications"], "additional_needed": 2,
                                               "required_employees": 5, "priority": "critical"}, "admin")
        self.assertTrue(w["sufficient"])
        top = w["candidates"]["eligible"][0]
        self.assertNotEqual(top["employee_id"], "ER02", "ER02 has 4 recent extra shifts: not first")


class RealUploadEmployeeLogins(unittest.TestCase):
    """Uploaded (non-demo) data: every employee can get a login, so both Admin and Employee views work."""

    def test_logins_for_uploaded_employees(self):
        app, org = app_with(base())
        auth = AuthService(app.store)
        out = app.create_employee_logins(org, auth, "admin")
        self.assertEqual(out["created"], 4)
        rows = xlsx.records(app.take_credentials(out["credentials_token"]))
        self.assertEqual({r["employee_id"] for r in rows}, {"A", "B", "C", "D"})
        user = auth.login(rows[0]["email"], rows[0]["temporary_password"])["user"]
        self.assertEqual((user["role"], user["org"], user["must_change_password"]), ("employee", org, True))
        with self.assertRaises(ResQWorkError):
            app.create_employee_logins(org, auth, "admin")        # nobody left without a login
        self.assertTrue(app.reset_employee_password(org, "A", auth, "admin")["credentials_token"])
