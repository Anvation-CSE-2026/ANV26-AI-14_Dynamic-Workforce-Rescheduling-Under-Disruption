import time
import unittest

from ai.employee_notice import PRIVATE_TERMS
from core.models import DOMAINS
from services import auth as auth_mod
from services import voice
from services.auth import AuthError, AuthService, check_password, hash_password, issue_token, verify_token
from services.workspace import ResQWork, ResQWorkError
from store import SqliteStore


def fresh(domain="healthcare"):
    app = ResQWork(SqliteStore(":memory:"))
    _, ws = app.load_demo(domain)
    return app, ws["org"]


class FullFlowEveryDomain(unittest.TestCase):
    def test_disruption_to_notified_employee(self):
        for domain in DOMAINS:
            with self.subTest(domain=domain):
                app, org = fresh(domain)
                before = app.dashboard(org)
                self.assertEqual(before["metrics"]["at_risk_assignments"]["value"], 0)
                preset = app.workspace_summary(org)["presets"][0]
                rec = app.report_disruption(org, preset_id=preset["id"])["disruptions"][0]
                self.assertTrue(rec["affected_shifts"])
                self.assertGreaterEqual(app.dashboard(org)["metrics"]["at_risk_assignments"]["value"], 1)

                prop = app.generate_repair(org)
                self.assertTrue(prop["result"]["options"])
                self.assertIn("A", prop["explanations"])
                self.assertTrue(prop["policy"]["constraints"], "domain policies should be retrieved")

                out = app.approve(org, prop["id"])
                self.assertEqual(out["version"]["tag"], "v1.1")
                self.assertEqual(app.dashboard(org)["metrics"]["at_risk_assignments"]["value"], 0)
                absent = app.dataset(org).employee(preset["employee_id"]).name
                for n in out["notifications"]:
                    self.assertNotIn(absent, n["body"])
                    self.assertFalse(any(f" {t} " in f" {n['body'].lower()} " for t in PRIVATE_TERMS))
                    self.assertTrue(n["voice_text"])
                self.assertEqual(app.analytics(org)["repairs_approved"], 1)
                events = [a["event_type"] for a in app.audit_trail(org)]
                for e in ("DATASET_LOADED", "DISRUPTION_REPORTED", "REPAIR_GENERATED", "SCHEDULE_APPROVED"):
                    self.assertIn(e, events)


class Decisions(unittest.TestCase):
    def setUp(self):
        self.app, self.org = fresh()
        self.app.report_disruption(self.org, preset_id="DEMO-ICU")
        self.prop = self.app.generate_repair(self.org)

    def test_approve_applies_assignment_and_history(self):
        best = self.prop["result"]["options"][0]
        sid, eid = next((s, e) for s, e in best["assignment"].items() if e and e != "H01" and s in
                        [c["shift_id"] for c in best["changes"]])
        ledger_before = len(self.app.dataset(self.org).employee(eid).history.contributions)
        self.app.approve(self.org, self.prop["id"], "A")
        ds = self.app.dataset(self.org)
        self.assertEqual(ds.assignment_map()[sid], eid)
        # historical fairness: the extra work is recorded, dated, in the contribution ledger
        ledger = ds.employee(eid).history.contributions
        self.assertEqual(len(ledger), ledger_before + 1)
        self.assertEqual(ledger[-1].ref, f"{self.prop['id']}:{sid}")
        self.assertTrue(any(a.employee_id == "H01" for a in ds.availability))
        with self.assertRaises(ResQWorkError):
            self.app.approve(self.org, self.prop["id"], "A")        # can't approve twice

    def test_reject(self):
        self.app.reject(self.org, self.prop["id"], reason="prefer someone else")
        self.assertEqual(self.app.proposal(self.org, self.prop["id"])["status"], "rejected")
        self.assertEqual(self.app.dataset(self.org).assignment_map()["ICU-D-1009-1"], "H01")   # unchanged

    def test_what_if_with_structured_spec(self):
        out = self.app.what_if(self.org, self.prop["id"], spec={"changes": [
            {"op": "exclude_employee", "employee_mention": "Neha", "text": "can't use Neha"}]})
        self.assertEqual(out["status"], "READY")
        new_best = out["proposal"]["result"]["options"][0]
        self.assertNotIn("H17", [s["employee_id"] for s in new_best["selected"]])
        self.assertTrue(out["delta"]["comparable"])

    def test_feedback_changes_the_next_run(self):
        res = self.app.add_feedback(self.org, "Don't assign Neha next time")
        self.assertEqual(res["status"], "READY")
        again = self.app.generate_repair(self.org)
        self.assertIn("Feedback: never use Neha Joshi", again["run_notes"])
        for o in again["result"]["options"]:
            self.assertNotIn("H17", [s["employee_id"] for s in o["selected"]])

    def test_partial_needs_explicit_confirmation(self):
        app, org = fresh("technology")
        app.report_disruption(org, text="Rohit is sick tomorrow 9 to 5, no overtime")
        p = app.generate_repair(org)
        self.assertEqual(p["result"]["status"], "PARTIAL")
        self.assertIsNotNone(p["relaxation"])
        self.assertIn("Kunal Mehra", p["relaxation"]["message"])
        with self.assertRaises(ResQWorkError):
            app.approve(org, p["id"])
        self.assertEqual(app.approve(org, p["id"], allow_partial=True)["version"]["tag"], "v1.1")


class Employees(unittest.TestCase):
    def test_availability_request_becomes_disruption(self):
        app, org = fresh()
        req = app.submit_availability(org, "H09", "2026-10-09", "07:00", "19:00", "family event")
        self.assertEqual(app.dashboard(org)["pending_requests"][0]["id"], req["id"])
        out = app.accept_availability(org, req["id"])
        self.assertEqual(out["disruptions"][0]["employee_name"], "Meera Iyer")

    def test_acknowledge(self):
        app, org = fresh()
        app.report_disruption(org, preset_id="DEMO-ICU")
        out = app.approve(org, app.generate_repair(org)["id"])
        n = out["notifications"][0]
        acked = app.acknowledge(org, n["id"], n["employee_id"])
        self.assertIsNotNone(acked["acknowledged_at"])
        with self.assertRaises(ResQWorkError):
            app.acknowledge(org, n["id"], "SOMEONE_ELSE")


class NaturalLanguageWithoutLLM(unittest.TestCase):
    def test_rule_parser_drives_the_flow(self):
        app, org = fresh()
        out = app.report_disruption(org, text="Rahul is unavailable tomorrow from 7 AM to 7 PM, no overtime")
        self.assertEqual(out["status"], "READY")
        self.assertEqual(out["interpretation"]["meta"]["provider"], "rules")
        p = app.generate_repair(org)
        self.assertIn("Policy: max daily hours = 12", p["run_notes"])

    def test_unclear_text_asks(self):
        app, org = fresh()
        out = app.report_disruption(org, text="Zoya is out tomorrow")
        self.assertEqual(out["status"], "NEEDS_CLARIFICATION")


class Policies(unittest.TestCase):
    def test_domain_policies_are_compiled_with_sources(self):
        for domain in DOMAINS:
            app, org = fresh(domain)
            ov = app.policy_overview(org)
            self.assertTrue(ov["documents"], domain)
            types = {c["type"] for c in ov["constraints"]}
            self.assertIn("max_weekly_hours", types, domain)
            self.assertTrue(all(c["quote"] and c["source"] for c in ov["constraints"]))

    def test_search_and_upload(self):
        app, org = fresh("logistics")
        self.assertEqual(app.policy_search(org, "dress code")["status"], "no_applicable_policy")
        app.upload_policy(org, "night.md", "# Night driving\n## 1. Limit\nNo driver may work more than 5 consecutive days.")
        hit = app.policy_search(org, "consecutive days limit")["hits"][0]
        self.assertIn("5 consecutive days", hit["text"])


class Voice(unittest.TestCase):
    def test_scripts_are_fact_based(self):
        app, org = fresh()
        rec = app.report_disruption(org, preset_id="DEMO-ICU")["disruptions"][0]
        self.assertIn("Rahul Sharma is unavailable on Friday", voice.manager_alert("healthcare", rec))
        p = app.generate_repair(org)
        self.assertIn("ResQWork recommends Option A", voice.recommendation(p))
        self.assertIn("minimum rest-period", voice.why_not(p, "Elena", app.employees(org)))
        self.assertEqual(voice.detect("why not Elena?"), ("why_not", "Elena"))
        self.assertEqual(voice.detect("approve the recommended repair")[0], "approve")


class Auth(unittest.TestCase):
    def test_password_hashing(self):
        h = hash_password("correct horse")
        self.assertTrue(check_password("correct horse", h))
        self.assertFalse(check_password("wrong", h))

    def test_tokens(self):
        tok = issue_token({"id": "u1", "role": "employee", "org": "o", "employee_id": "E1"})
        self.assertEqual(verify_token(tok)["employee_id"], "E1")
        body, sig = tok.split(".")
        with self.assertRaises(AuthError):
            verify_token(body + "." + sig[::-1])
        old = auth_mod.TOKEN_TTL_S
        auth_mod.TOKEN_TTL_S = -1
        try:
            with self.assertRaises(AuthError):
                verify_token(issue_token({"id": "u1", "role": "admin"}))
        finally:
            auth_mod.TOKEN_TTL_S = old

    def test_register_login(self):
        a = AuthService(SqliteStore(":memory:"))
        a.register("Ops@Example.com", "s3cret-pass", "Ops", "operations_manager")
        self.assertEqual(a.login("ops@example.com", "s3cret-pass")["user"]["role"], "operations_manager")
        with self.assertRaises(AuthError):
            a.login("ops@example.com", "nope")
        with self.assertRaises(AuthError):
            a.register("ops@example.com", "another-pass", "Dup")
        with self.assertRaises(AuthError):
            a.register("x@y.z", "short", "X")


if __name__ == "__main__":
    unittest.main()


class ReloadResetsOperationalState(unittest.TestCase):
    def test_reloading_demo_starts_from_clean_baseline(self):
        app, org = fresh("healthcare")
        preset = app.workspace_summary(org)["presets"][0]
        app.report_disruption(org, preset_id=preset["id"])
        app.approve(org, app.generate_repair(org)["id"])
        self.assertEqual(app.workspace_summary(org)["version"], "v1.1")
        app.load_demo("healthcare")
        self.assertEqual(app.open_disruptions(org), [])
        self.assertIsNone(app.latest_proposal(org))
        self.assertEqual([v["tag"] for v in app.versions(org)], ["v1.0"])
        self.assertEqual(app.notifications(org), [])
        self.assertTrue(any(e["event_type"] == "DATASET_LOADED" for e in app.audit_trail(org)), "audit is kept")


class RuleBasedWhatIf(unittest.TestCase):
    """Without an LLM, the suggested what-ifs in the UI must still work."""

    def test_exclude_and_minimize_overtime(self):
        app, org = fresh("healthcare")
        app.report_disruption(org, preset_id=app.workspace_summary(org)["presets"][0]["id"])
        base = app.generate_repair(org)
        chosen = {s["employee_name"] for s in base["result"]["options"][0]["selected"]}
        name = sorted(chosen)[0]
        out = app.what_if(org, base["id"], f"don't use {name}")
        self.assertEqual(out["status"], "READY")
        for o in out["proposal"]["result"]["options"]:
            self.assertNotIn(name, {s["employee_name"] for s in o["selected"]})
        self.assertEqual(app.what_if(org, base["id"], "minimize overtime")["status"], "READY")
        self.assertEqual(app.proposal(org, base["id"])["status"], "pending", "what-ifs never publish")
