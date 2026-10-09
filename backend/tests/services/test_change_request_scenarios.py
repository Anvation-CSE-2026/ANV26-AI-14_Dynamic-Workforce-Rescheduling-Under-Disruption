"""Acceptance scenarios A–L from the change request (service level; the UI is checked in the browser run)."""

import json
import os
import unittest
from unittest import mock

from services import demo_accounts, gemini_voice, voice_agent
from services.auth import AuthService
from services.domains import scenario_dataset
from services.workspace import ResQWork, ResQWorkError
from store import SqliteStore


def scenario(name):
    app = ResQWork(SqliteStore(":memory:"))
    _, ws = app.load_dataset(scenario_dataset(name), f"scenario: {name}")
    return app, ws["org"]


def demo(domain="healthcare"):
    app = ResQWork(SqliteStore(":memory:"))
    _, ws = app.load_demo(domain)
    return app, ws["org"]


class RequestLifecycle(unittest.TestCase):          # Tests A and B
    def test_submit_approve_repair_complete(self):
        app, org = demo()
        req = app.submit_availability(org, "H01", "2026-10-09", None, None, "family event", "time_off")
        self.assertEqual(req["status"], "pending")
        # A: the manager sees the same request (single source of truth)
        self.assertIn(req["id"], [r["id"] for r in app.availability_requests(org)])
        self.assertIn(req["id"], [r["id"] for r in app.dashboard(org)["pending_requests"]])
        # B: the manager approves; the employee sees Approved, then Completed once cover is published
        app.decide_request(org, req["id"], "approved", "Get well soon")
        mine = app.employee_view(org, "H01")["requests"][0]
        self.assertEqual(mine["status"], "approved")
        self.assertEqual(mine["manager_note"], "Get well soon")
        self.assertNotIn(req["id"], [r["id"] for r in app.dashboard(org)["pending_requests"]])
        app.approve(org, app.generate_repair(org)["id"])
        mine = app.employee_view(org, "H01")["requests"][0]
        self.assertEqual(mine["status"], "completed")
        self.assertEqual([h["status"] for h in mine["history"]], ["pending", "approved", "completed"])
        self.assertTrue(any(n["title"].startswith("Request approved") for n in app.employee_view(org, "H01")["notifications"]))

    def test_reject_and_needs_review(self):
        app, org = demo("manufacturing")
        a = app.submit_availability(org, "M02", "2026-10-09", "06:00", "14:00", "", "unavailable")
        b = app.submit_availability(org, "M03", "2026-10-09", None, None, "", "preference")
        app.decide_request(org, a["id"], "needs_review", "Who covers Line 1?")
        self.assertEqual(app.employee_view(org, "M02")["requests"][0]["status"], "needs_review")
        app.decide_request(org, a["id"], "rejected", "Line 1 has no cover that day")
        self.assertEqual(app.employee_view(org, "M02")["requests"][0]["status"], "rejected")
        self.assertEqual(app.open_disruptions(org), [], "a rejected request must not create a disruption")
        with self.assertRaises(ResQWorkError):
            app.decide_request(org, a["id"], "approved")
        self.assertEqual(app.decide_request(org, b["id"], "approved")["request"]["status"], "completed")

    def test_invalid_requests_are_refused(self):
        app, org = demo()
        for bad in [dict(date="tomorrow"), dict(date="2026-10-09", start="09:00"), dict(date="2026-10-09", kind="x")]:
            with self.assertRaises(ResQWorkError):
                app.submit_availability(org, "H01", bad["date"], bad.get("start"), None, "", bad.get("kind", "unavailable"))


class RepairCases(unittest.TestCase):
    def setUp(self):
        self.app, self.org = scenario("repair-cases")
        self.ds = self.app.dataset(self.org)

    def test_C_double_booking_detected_and_repaired(self):
        conflicts = self.app.schedule_conflicts(self.org)
        self.assertEqual([c["type"] for c in conflicts], ["double_booking"])
        self.assertEqual(list(conflicts[0]["release"]), ["ASM-B-16"], "the normal-priority, later shift is released")
        p = self.app.resolve_conflicts(self.org)
        best = p["result"]["options"][0]
        self.assertEqual([(c["shift_id"], c["from_employee_id"], c["to_employee_id"]) for c in best["changes"]],
                         [("ASM-B-16", "E02", "E05")])
        out = self.app.approve(self.org, p["id"])
        self.assertEqual(self.app.schedule_conflicts(self.org), [])
        self.assertEqual({n["employee_id"] for n in out["notifications"]}, {"E02", "E05"},
                         "the person taken off the double-booked shift is told too")

    def _repair(self):
        self.app.report_disruption(self.org, preset_id="E01-out")
        return self.app.generate_repair(self.org)

    def test_D_and_I_qualified_replacement_minimum_change(self):
        before = dict(self.ds.assignment_map())
        p = self._repair()
        best = p["result"]["options"][0]
        self.assertEqual(p["result"]["status"], "OPTIMAL" if best["status"] == "OPTIMAL" else "FEASIBLE")
        self.assertEqual([(c["shift_id"], c["to_employee_id"]) for c in best["changes"]], [("CNC-A-16", "E03")])
        after = {**before, **{k: v for k, v in best["assignment"].items() if v}}
        unchanged = [s for s in before if s != "CNC-A-16" and before[s] == after[s]]
        self.assertEqual(len(unchanged), len(before) - 1, "I: every unrelated assignment stays as it was")

    def test_F_G_skill_and_certification_mismatch_rejected(self):
        why = {r["employee_id"]: r for r in self._repair()["result"]["rejected"]}
        self.assertEqual(why["E05"]["reason_code"], "MISSING_SKILL")
        self.assertEqual(why["E04"]["reason_code"], "MISSING_CERTIFICATION")
        self.assertIn("Safety Level 2", why["E04"]["detail"])

    def test_H_overtime_avoided_when_a_better_candidate_exists(self):
        p = self._repair()
        best = p["result"]["options"][0]
        self.assertEqual(best["impact"]["overtime_hours_added"], 0)
        farid = next(r for r in p["result"]["rejected"] if r["employee_id"] == "E06")
        self.assertEqual(farid["reason_code"], "WOULD_CREATE_OVERTIME")

    def test_hard_and_soft_constraints_are_listed(self):
        r = self._repair()["result"]
        self.assertTrue({"overlap", "skills", "certifications", "rest", "weekly_hours", "availability"}
                        <= {c["id"] for c in r["hard_constraints"]})
        self.assertIn("fairness", {c["id"] for c in r["soft_objectives"]})


class Infeasible(unittest.TestCase):               # Test E
    def setUp(self):
        self.app, self.org = scenario("infeasible-cnc")
        self.app.report_disruption(self.org, preset_id="E01-out")
        self.p = self.app.generate_repair(self.org)

    def test_no_feasible_repair_is_reported_not_faked(self):
        r = self.p["result"]
        self.assertIn(r["status"], ("PARTIAL", "INFEASIBLE"))
        for o in r["options"]:
            for sid, eid in o["assignment"].items():
                if eid:   # nobody unqualified, unavailable or double-booked is ever placed
                    self.assertNotIn(eid, ("E01", "E03", "E04", "E05") if sid == "CNC-1-16" else ())
        u = r["unresolved"][0]
        self.assertEqual(u["shift_id"], "CNC-1-16")
        self.assertEqual(u["bottleneck"], "overlap")
        self.assertEqual([f["remaining"] for f in u["funnel"]], [3, 2, 1, 0, 0, 0])
        self.assertIn("Bala Krishnan", u["summary"])
        near = {b["stage"]: [n["name"] for n in b["near_misses"]] for b in u["blocking"]}
        self.assertEqual(near["certification"], ["Chitra Nair"])
        self.assertEqual(near["availability"], ["Asha Rao"])
        kinds = {x["action"]: x["kind"] for x in u["resolutions"]}
        self.assertEqual(kinds["Relax the certification (manual override)"], "manual_override")
        self.assertIn(u["summary"], r["infeasibility_reasons"])

    def test_cannot_be_approved_silently(self):
        with self.assertRaises(ResQWorkError):
            self.app.approve(self.org, self.p["id"])
        reply = voice_agent.handle(self.app, self.org, "mgr", "approve the repair")
        self.assertIn("can't approve", reply["text"])
        self.assertEqual(self.app.proposal(self.org, self.p["id"])["status"], "pending")
        self.assertIn("No feasible cover", voice_agent.handle(self.app, self.org, "mgr", "what is unresolved?")["text"])

    def test_all_certified_unavailable_names_the_certification(self):
        raw = scenario_dataset("infeasible-cnc")
        raw["availability"] = [{"employee_id": "E02", "date": "2026-10-16", "kind": "leave", "reason": "leave"}]
        raw["existing_schedule"] = [a for a in raw["existing_schedule"] if a["shift_id"] != "CNC-2-16"]
        app = ResQWork(SqliteStore(":memory:"))
        _, ws = app.load_dataset(raw, "variant")
        app.report_disruption(ws["org"], preset_id="E01-out")
        u = app.generate_repair(ws["org"])["result"]["unresolved"][0]
        self.assertEqual(u["bottleneck"], "availability")
        self.assertIn("all 2 qualified people are unavailable", u["summary"])


class DemoAccountsAndRoles(unittest.TestCase):      # Test J
    def test_every_domain_has_admin_and_employee_logins(self):
        store = SqliteStore(":memory:")
        demo_accounts.seed(store)
        auth = AuthService(store)
        listed = demo_accounts.public_list()
        for domain in demo_accounts.EMPLOYEES:
            roles = {a["role"] for a in listed if a["domain"] == domain}
            self.assertEqual(roles, {"admin", "employee"}, f"{domain}: only Admin and Employee are product roles")
            self.assertGreaterEqual(sum(1 for a in listed if a["domain"] == domain and a["role"] == "employee"), 3)
        self.assertEqual(auth.login("manager@healthcare.demo", demo_accounts.PASSWORD)["user"]["role"], "admin",
                         "legacy manager login still works, as an admin")
        emp = next(a for a in listed if a["domain"] == "healthcare" and a["role"] == "employee")
        user = auth.login(emp["email"], demo_accounts.PASSWORD)["user"]
        self.assertEqual((user["role"], user["org"]), ("employee", "st-aster"))
        self.assertTrue(user["employee_id"])
        with self.assertRaises(Exception):
            auth.login(emp["email"], "wrong-password")


class Voice(unittest.TestCase):                    # Test K
    COMMANDS = {
        "Show today's schedule": "today_schedule",
        "What conflicts are unresolved?": "unresolved",
        "Why was Neha Joshi reassigned?": "why_reassigned",
        "Show me today's disruptions": "disruptions",
        "What changed in the latest repair?": "latest_changes",
        "Which employees are affected?": "affected_employees",
        "Show unresolved constraints": "unresolved",
        "What is the recommended repair?": "recommend",
    }

    def test_commands_map_to_intents_and_live_data(self):
        for text, intent in self.COMMANDS.items():
            self.assertEqual(voice_agent.detect(text)[0], intent, text)
        app, org = demo()
        app.report_disruption(org, preset_id=app.workspace_summary(org)["presets"][0]["id"])
        p = app.generate_repair(org)
        reply = voice_agent.handle(app, org, "mgr", "Why was Neha Joshi reassigned?")
        self.assertIn("Neha Joshi", reply["text"])
        self.assertIn("48 hour limit", reply["text"])
        self.assertEqual(reply["navigate"], {"screen": "repair", "proposal_id": p["id"]})
        self.assertEqual(voice_agent.handle(app, org, "mgr", "Show today's schedule")["navigate"], {"screen": "schedule"})

    def test_gemini_understanding_and_graceful_failure(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            os.environ.pop("GOOGLE_API_KEY", None)
            with self.assertRaises(gemini_voice.VoiceUnavailable):
                gemini_voice.understand(text="hello")
        sent = {}

        def fake_post(url, body, key):
            sent.update(url=url, body=body, key=key)
            answer = {"transcript": "why was neha reassigned", "intent": "why_reassigned", "employee": "Neha"}
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}]}

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "RESQWORK_GEMINI_VOICE_MODEL": "m-test"}):
            out = gemini_voice.understand(audio=b"\x00" * 2000, mime="audio/webm;codecs=opus", post=fake_post)
        self.assertEqual((out["intent"], out["employee"], out["model"]), ("why_reassigned", "Neha", "m-test"))
        self.assertIn("m-test:generateContent", sent["url"])
        self.assertEqual(sent["body"]["contents"][0]["parts"][1]["inline_data"]["mime_type"], "audio/webm")
        self.assertNotIn("test-key", json.dumps(sent["body"]), "the key travels in a header, not the body")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            with self.assertRaises(gemini_voice.VoiceUnavailable):
                gemini_voice.understand(audio=b"x", mime="audio/webm", post=fake_post)   # too short
            with self.assertRaises(gemini_voice.VoiceUnavailable):
                gemini_voice.understand(text="hi", post=lambda *a: {"candidates": []})


class Recognition(unittest.TestCase):              # Test L (Rewards & Recognition: reward on completion only)
    def test_cover_and_manager_recognition_visible_to_both(self):
        app, org = demo("logistics")
        app.report_disruption(org, preset_id=app.workspace_summary(org)["presets"][0]["id"])
        p = app.generate_repair(org)
        out = app.approve(org, p["id"])
        covered = {c["to_employee_id"] for c in out["version"]["changes"] if c.get("to_employee_id")}
        self.assertTrue(covered)
        self.assertTrue(out["recognition"] and all(e["status"] == "pending_completion" and e["points"] == 0
                                                   for e in out["recognition"]), "no points before completion")
        eid = sorted(covered)[0]
        self.assertEqual(app.employee_rewards(org, eid)["points_total"], 0)
        app.complete_repair(org, p["id"], "Depot manager")
        mine = app.employee_rewards(org, eid)
        self.assertGreater(mine["points_90d"], 0)
        self.assertIn("Peak Coverage", {a["category_label"] for a in mine["history"]}, "logistics vocabulary")
        self.assertIn("team_supporter", {b["id"] for b in mine["badges"]})
        app.recognize(org, eid, "safety", "Reported a brake fault before the run", "Depot manager")
        board = {e["employee_id"]: e for e in app.recognition_overview(org)["employees"]}
        self.assertIn("Road Safety", [c["label"] for c in board[eid]["categories"]])
        self.assertTrue(any(n["title"] == "Recognition: Road Safety" for n in app.employee_view(org, eid)["notifications"]))
        with self.assertRaises(ResQWorkError):
            app.recognize(org, eid, "safety", "  ", "Depot manager")
        with self.assertRaises(ResQWorkError):
            app.recognize(org, eid, "not-a-category", "x", "Depot manager")

    def test_no_points_for_hours_or_overtime(self):
        app, org = demo("technology")         # preset 1's best repair adds overtime
        app.report_disruption(org, preset_id=app.workspace_summary(org)["presets"][0]["id"])
        p = app.generate_repair(org)
        best = p["result"]["options"][0]
        self.assertGreater(best["impact"]["overtime_hours_added"], 0)
        app.approve(org, p["id"])
        done = app.complete_repair(org, p["id"], "manager")["completed"]
        self.assertEqual([e["points"] for e in done if e["trigger"] == "coverage_completed"], [30],
                         "same award with or without overtime: 20 cover + 10 critical-support bonus")


if __name__ == "__main__":
    unittest.main()
