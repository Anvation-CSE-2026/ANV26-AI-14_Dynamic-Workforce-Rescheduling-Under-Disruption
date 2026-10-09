"""Route a free-text manager message to the right parser.

Unambiguous phrasings ("what if…", "next time…") are routed by rules without a
model call; everything else is classified by the LLM. With no provider, the
rules are the fallback and say so via ``method`` and a low confidence.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import prompts
from .providers.base import AIProvider, LLMError
from .schemas import Meta
from .structured import call_structured

Intent = Literal["report_disruption", "what_if", "manager_feedback", "policy_question", "other"]

_WHAT_IF = re.compile(r"^\s*(what\s+if|what\s+happens\s+if|what\s+would\s+happen|suppose|imagine|"
                      r"try\s+(it|again)\s+with|simulate)\b", re.I)
_FEEDBACK = re.compile(r"\b(next\s+time|from\s+now\s+on|in\s+(the\s+)?future|going\s+forward|"
                       r"always\s+prefer|i\s+(would\s+)?prefer|never\s+(use|assign|schedule))\b", re.I)
_POLICY_Q = re.compile(r"^\s*(what|which|is|are|does|do|can|how)\b.*\b(policy|policies|rule|rules|allowed|"
                       r"permitted|handbook)\b", re.I)
_DISRUPTION = re.compile(r"\b(unavailable|sick|leave|absent|out\s+(today|tomorrow|on)|can'?t\s+(come|make|work)|"
                         r"cannot\s+(come|work)|emergency|called\s+in|off\s+(today|tomorrow))\b", re.I)


class _RawIntent(BaseModel):
    intent: Intent
    confidence: Literal["low", "medium", "high"]


class IntentResult(BaseModel):
    intent: Intent
    confidence: Literal["low", "medium", "high"]
    method: Literal["rules", "llm", "fallback_rules"]
    meta: Meta = Field(default_factory=Meta)


def rule_intent(text: str) -> Optional[Intent]:
    if _WHAT_IF.search(text):
        return "what_if"
    if _FEEDBACK.search(text):
        return "manager_feedback"
    return None


class IntentRouter:
    def __init__(self, provider: Optional[AIProvider]) -> None:
        self.provider = provider

    def classify(self, text: str) -> IntentResult:
        text = (text or "").strip()
        rule = rule_intent(text)
        if rule:
            return IntentResult(intent=rule, confidence="high", method="rules")
        if self.provider is not None:
            try:
                raw, trace = call_structured(self.provider, prompts.INTENT,
                                             prompts.wrap_user_text("Manager message", text), _RawIntent)
                return IntentResult(intent=raw.intent, confidence=raw.confidence, method="llm",
                                    meta=Meta(prompt=prompts.INTENT.id, provider=self.provider.name,
                                              model=self.provider.model, trace_id=trace.trace_id))
            except LLMError:
                pass
        if _POLICY_Q.search(text):
            return IntentResult(intent="policy_question", confidence="low", method="fallback_rules")
        if _DISRUPTION.search(text):
            return IntentResult(intent="report_disruption", confidence="low", method="fallback_rules")
        return IntentResult(intent="other", confidence="low", method="fallback_rules")
