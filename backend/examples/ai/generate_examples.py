"""End-to-end Round 2 demo of the AI + RAG layer, and example payload generator.

Walks the full flow with a stand-in for the optimizer's output:

  manager message → intent → disruption (+ preferences)
                  → policy bundle (RAG → constraints → conflicts → optimizer config)
                  → [optimizer returns 3 candidates]  ← stand-in data
                  → candidate comparison → grounded explanation with policy citations
                  → what-if → feedback → employee notice → policy question

Run from backend/:
    python -m examples.ai.generate_examples           # scripted LLM output, fully offline
    python -m examples.ai.generate_examples --live    # real Claude (needs ANTHROPIC_API_KEY)

Writes one JSON file per step into examples/ai/ for the frontend and backend to build against.
"""

import json
import sys
from pathlib import Path

from ai.candidates import CandidateFacts
from ai.providers import ClaudeProvider, LLMError, MockProvider
from ai.schemas import ChangeFact, MetricsFact
from ai.service import AIService
from tests.fixtures import (NAMES, POLICY_DIR, ROSTER_NAMES, TOMORROW, context, extraction, feasible_facts,
                            policy_responder, raw)

OUT = Path(__file__).parent

MESSAGES = {
    "disruption": "Rahul is unavailable tomorrow from 9 to 5. Find a replacement but don't disturb anyone "
                  "already scheduled unless necessary.",
    "what_if": "What if overtime is forbidden and Priya is also out tomorrow?",
    "feedback": "Don't assign Arjun next time, and never use overtime unless it's unavoidable.",
    "policy_question": "How much rest do agents need between shifts?",
    "policy_question_none": "What is the dress code for the support floor?",
}


def scripted_provider() -> MockProvider:
    """Offline stand-in for Claude: returns what the live model returns for these messages."""
    policy = policy_responder()
    canned = {
        "record_disruption_request": extraction([raw()], {"priority": "minimize_affected_employees"}),
        "record_scenario_changes": {"is_what_if": True, "changes": [
            {"op": "set_overtime", "value": False, "text": "overtime is forbidden"},
            {"op": "add_unavailability", "employee_mention": "Priya", "date": TOMORROW,
             "date_expression": "tomorrow", "text": "Priya is also out tomorrow"}]},
        "record_manager_feedback": {"items": [
            {"kind": "avoid_employee", "employee_mention": "Arjun", "scope": "next_reschedule", "strength": "hard",
             "text": "Don't assign Arjun next time"},
            {"kind": "overtime_rule", "overtime_mode": "only_if_unavoidable", "scope": "until_revoked",
             "strength": "soft", "text": "never use overtime unless it's unavoidable"}]},
    }

    def respond(system, user, schema_name):
        if schema_name == "record_policy_constraints":
            return policy(system, user, schema_name)
        if schema_name == "classify_message":
            return {"intent": "report_disruption" if "unavailable" in user else "policy_question",
                    "confidence": "high"}
        if schema_name in canned:
            return canned[schema_name]
        return LLMError("offline demo: deterministic text used")  # explanations → template
    return MockProvider(respond)


def optimizer_candidates() -> list[CandidateFacts]:
    """Stand-in for what Member 4's optimizer returns for this disruption."""
    base = feasible_facts().changes
    chain = base + [ChangeFact(employee_id="EMP006", employee_name="Meera Iyer", change_type="shift_moved",
                               date=TOMORROW, from_assignment="SUPPORT_L2", to_assignment="KANNADA_DESK",
                               from_shift="07:00-15:00", to_shift="13:00-21:00")]
    return [
        CandidateFacts(candidate_id="A", label="Option A", strategy="minimize_changes", status="OPTIMAL",
                       changes=base, metrics=MetricsFact(assignments_changed=1, employees_affected=1,
                                                         overtime_hours=0, fairness_score=86, impact_score=14)),
        CandidateFacts(candidate_id="B", label="Option B", strategy="fairness", status="FEASIBLE",
                       changes=chain, metrics=MetricsFact(assignments_changed=2, employees_affected=2,
                                                          overtime_hours=0, fairness_score=92, impact_score=22)),
        CandidateFacts(candidate_id="C", label="Option C", strategy="minimize_overtime", status="FEASIBLE",
                       metrics=MetricsFact(assignments_changed=2, employees_affected=2, overtime_hours=2,
                                           fairness_score=84, impact_score=31)),
    ]


def dump(name: str, payload) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n")


def show(title: str, text: str) -> None:
    print(f"\n=== {title} ===\n{text}")


def main(live: bool) -> None:
    ai = AIService(ClaudeProvider() if live else scripted_provider())
    ai.policies.ingest_directory(POLICY_DIR)
    ctx = context()

    step = ai.interpret(MESSAGES["disruption"], ctx)
    dump("01_interpret_disruption", {"request": MESSAGES["disruption"], "response": step.model_dump(mode="json")})
    show("1. Understood", f"{step.disruption.confirmation_summary}\nconfidence: {step.disruption.confidence.level}")

    bundle = ai.policy_bundle(MESSAGES["disruption"], roles=["L2 Support"], assignments=["SUPPORT_L2"])
    dump("02_policy_bundle", bundle.model_dump(mode="json"))
    show("2. Policies → constraints", "\n".join(
        f"{c.severity:4} {c.constraint_type}={c.value} [{c.scope.label()}] ← {c.source.document} §{c.source.section}"
        for c in bundle.constraints) + "\nWarnings:\n- " + "\n- ".join(bundle.warnings()))

    comp = ai.compare_candidates(optimizer_candidates(), step.disruption.preferences.priority, ROSTER_NAMES)
    dump("03_candidate_comparison", comp.model_dump(mode="json"))
    show("3. Alternatives", comp.headline + "\n- " + "\n- ".join(p.text for p in comp.points))

    facts = feasible_facts()
    facts.policies_applied = [c for c in bundle.citations()
                              if c.constraint_type in ("minimum_rest", "max_weekly_hours") and c.section != "3"]
    exp = ai.explain(facts, roster_names=ROSTER_NAMES)
    dump("04_explanation", {"facts": facts.model_dump(mode="json"), "response": exp.model_dump(mode="json")})
    show("4. Why this change", exp.as_text())

    s = ai.parse_what_if(MESSAGES["what_if"], ctx)
    dump("05_what_if", {"request": MESSAGES["what_if"], "response": s.model_dump(mode="json"),
                        "preferences_after": s.apply_to(step.disruption.preferences).model_dump(mode="json")})
    show("5. What-if", s.summary)

    f = ai.parse_feedback(MESSAGES["feedback"], ctx)
    dump("06_feedback", {"request": MESSAGES["feedback"], "response": f.model_dump(mode="json")})
    show("6. Feedback stored", f.summary)

    notices = ai.employee_notices(facts.changes, NAMES, facts.policies_applied, schedule_version="v42")
    dump("07_employee_notices", [n.model_dump(mode="json") for n in notices])
    show(f"7. Notice to {NAMES[notices[0].employee_id]}", notices[0].body)

    for key in ("policy_question", "policy_question_none"):
        r = ai.lookup_policy(MESSAGES[key])
        dump(f"08_{key}", {"question": MESSAGES[key], "response": r.model_dump(mode="json")})
        show(f"8. {MESSAGES[key]}", r.message or "\n".join(
            f"{h.citation()} [confidence {h.confidence}]: {h.chunk.text}" for h in r.hits))
    print(f"\nWrote examples to {OUT}")


if __name__ == "__main__":
    main(live="--live" in sys.argv)
