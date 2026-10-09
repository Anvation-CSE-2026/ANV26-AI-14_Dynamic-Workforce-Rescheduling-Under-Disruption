"""``AIService``: the single entry point the backend (Member 4) uses.

    ai = AIService.from_env(policy_dir="shared/policies")

    ai.interpret(text, ctx)               chat box: route + parse any manager message
    ai.parse_request(text, ctx)           → ParseResult        (disruption + intent)
    ai.parse_what_if(text, ctx)           → ScenarioSpec       (re-run the optimizer with it)
    ai.parse_feedback(text, ctx)          → FeedbackResult     (store as standing preferences)
    ai.policy_bundle(text, roles, ...)    → PolicyBundle       (constraints for CP-SAT + citations)
    ai.lookup_policy(question)            → RetrievalResult    (grounded passages or "no applicable policy found")
    ai.explain(facts)                     → Explanation        (grounded; template fallback)
    ai.compare_candidates(candidates)     → CandidateComparison
    ai.employee_notices(changes, ...)     → [EmployeeNotice]

Nothing here assigns anyone. "AI interprets. Optimization decides."
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel

from rag.retriever import RetrievalResult
from rag.service import PolicyBundle, PolicyService

from .candidates import CandidateComparer, CandidateComparison, CandidateFacts
from .disruption_parser import DisruptionParser
from .rule_parser import rule_extract
from .employee_notice import EmployeeNotice, build_notice, check_notice
from .explanation import Explainer, Mode
from .feedback import FeedbackParser, FeedbackResult
from .intent import IntentResult, IntentRouter
from .providers import get_provider
from .providers.base import AIProvider
from .schemas import ChangeFact, Explanation, ExplanationFacts, Issue, Meta, ParseContext, ParseResult, PolicyCitation, Priority
from .what_if import ScenarioSpec, WhatIfParser

log = logging.getLogger("resqwork.ai")

_NO_LLM = "No language model is configured; use the structured form."


class InterpretResult(BaseModel):
    intent: IntentResult
    disruption: Optional[ParseResult] = None
    scenario: Optional[ScenarioSpec] = None
    feedback: Optional[FeedbackResult] = None
    policy: Optional[RetrievalResult] = None
    message: str = ""


class AIService:
    def __init__(self, provider: Optional[AIProvider], policies: Optional[PolicyService] = None) -> None:
        self.provider = provider
        self.router = IntentRouter(provider)
        self.disruptions = DisruptionParser(provider) if provider else None
        self.what_if = WhatIfParser(provider) if provider else None
        self.feedback = FeedbackParser(provider) if provider else None
        self.explainer = Explainer(provider)
        self.comparer = CandidateComparer(provider)
        self.policies = policies or PolicyService(provider)

    @classmethod
    def from_env(cls, policy_dir: str | Path | None = None) -> "AIService":
        """Provider from RESQWORK_LLM_PROVIDER (claude | openai | gemini | none); policies from ``policy_dir``."""
        provider = get_provider()
        svc = cls(provider)
        if policy_dir and Path(policy_dir).exists():
            n = svc.policies.ingest_directory(policy_dir)
            log.info("Indexed %d policy chunks from %s", n, policy_dir)
        return svc

    # ------------------------------------------------------------ language in

    def interpret(self, text: str, ctx: ParseContext) -> InterpretResult:
        intent = self.router.classify(text)
        out = InterpretResult(intent=intent)
        if intent.intent == "report_disruption":
            out.disruption = self.parse_request(text, ctx)
        elif intent.intent == "what_if":
            out.scenario = self.parse_what_if(text, ctx)
        elif intent.intent == "manager_feedback":
            out.feedback = self.parse_feedback(text, ctx)
        elif intent.intent == "policy_question":
            out.policy = self.lookup_policy(text)
        else:
            out.message = ("I can help with disruptions ('Rahul is out tomorrow 9-5'), what-ifs "
                           "('What if overtime is forbidden?'), feedback ('Prefer fairness next time') "
                           "and policy questions ('How much rest between shifts?').")
        return out

    def parse_request(self, text: str, ctx: ParseContext) -> ParseResult:
        """LLM extraction when a provider is configured; rule-based extraction when it isn't (or fails).
        Both go through the same deterministic resolver and validation."""
        if self.disruptions is not None:
            result = self.disruptions.parse(text, ctx)
            if result.status != "ERROR":
                return result
        raw = rule_extract(text or "")
        meta = Meta(prompt="rule_parser@1.0.0", provider="rules", model="regex")
        result = DisruptionParser(None).resolve(raw, ctx, (text or "").strip(), meta)
        if result.status == "UNSUPPORTED" and self.provider is None:
            result.issues.append(Issue(code="LLM_ERROR", blocking=False, message=_NO_LLM))
        return result

    def parse_what_if(self, text: str, ctx: ParseContext) -> ScenarioSpec:
        if self.what_if is None:
            return ScenarioSpec(status="ERROR", raw_request=text, issues=[Issue(code="LLM_ERROR", message=_NO_LLM)])
        return self.what_if.parse(text, ctx)

    def parse_feedback(self, text: str, ctx: ParseContext) -> FeedbackResult:
        if self.feedback is None:
            return FeedbackResult(status="ERROR", raw_request=text, issues=[Issue(code="LLM_ERROR", message=_NO_LLM)])
        return self.feedback.parse(text, ctx)

    # ---------------------------------------------------------------- policy

    def policy_bundle(self, request_text: str = "", roles: Optional[list[str]] = None,
                      assignments: Optional[list[str]] = None) -> PolicyBundle:
        return self.policies.build_bundle(request_text, roles, assignments)

    def lookup_policy(self, question: str, k: int = 3) -> RetrievalResult:
        return self.policies.lookup(question, k)

    # ------------------------------------------------------------- text out

    def explain(self, facts: ExplanationFacts, mode: Mode = "auto",
                roster_names: Optional[Iterable[str]] = None) -> Explanation:
        exp = self.explainer.explain(facts, mode=mode, roster_names=roster_names)
        if exp.grounding_warnings:
            log.warning("LLM explanation rejected, template used: %s", exp.grounding_warnings)
        return exp

    def compare_candidates(self, candidates: list[CandidateFacts], priority: Optional[Priority] = None,
                           roster_names: Optional[Iterable[str]] = None) -> CandidateComparison:
        return self.comparer.compare(candidates, priority, roster_names=roster_names)

    def conflict_advice(self, facts: dict, roster_names: Optional[Iterable[str]] = None) -> Optional[dict]:
        """LLM wording + strategy ideas for one conflict, or None (no provider / failed / ungrounded).

        The caller re-validates every suggested employee against the hard-constraint results: an LLM
        suggestion can never make an ineligible person eligible."""
        if self.provider is None:
            return None
        import json as _json

        from .grounding import check_narration
        from .prompts import CONFLICT_ADVICE, wrap_user_text
        from .structured import StructuredCallError, call_structured

        class _Advice(BaseModel):
            summary: str
            strategies: list[str] = []
            suggested_employee_ids: list[str] = []

        try:
            out, trace = call_structured(self.provider, CONFLICT_ADVICE,
                                         wrap_user_text("FACTS", _json.dumps(facts, default=str)), _Advice)
        except StructuredCallError:
            return None
        problems = check_narration([out.summary, *out.strategies], [], facts, roster_names)
        if problems:
            log.warning("conflict advice rejected (ungrounded): %s", problems[:3])
            return None
        return {**out.model_dump(), "prompt": trace.prompt, "provider": trace.provider}

    def employee_notices(self, changes: list[ChangeFact], names: dict[str, str],
                         policies: Optional[list[PolicyCitation]] = None,
                         schedule_version: Optional[str] = None,
                         notify_unassigned: Iterable[str] = ()) -> list[EmployeeNotice]:
        """One notice per affected employee who still works (removed-only rows are excluded:
        the absent employee already knows, and their notice would reveal nothing useful)."""
        notices = []
        keep = set(notify_unassigned)   # e.g. someone taken off a double-booked shift must be told
        for emp_id in dict.fromkeys(c.employee_id for c in changes if c.change_type != "unassigned"
                                    or c.employee_id in keep):
            n = build_notice(emp_id, names.get(emp_id, emp_id), changes, policies, schedule_version=schedule_version)
            problems = check_notice(n, names.values())
            if problems:
                # Never leak, never block the approval: send a minimal notice that points to the app instead.
                log.warning("notice for %s failed privacy check %s; sending minimal notice", emp_id, problems)
                n = n.model_copy(update={"body": f"Hi {names.get(emp_id, '').split(' ')[0] or 'there'},\n\n"
                                                 "Your schedule has been updated. Please open ResQWork to see "
                                                 "the change and acknowledge it.\n\nThank you!"})
            notices.append(n)
        return notices
