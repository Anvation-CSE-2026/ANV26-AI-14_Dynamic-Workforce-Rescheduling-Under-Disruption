"""Manager feedback → standing preferences for future reschedules.

The backend stores these and turns them into optimizer inputs on later runs
(suggested mapping in docs/ai-design.md). ``next_reschedule`` items should be
consumed after one run; ``until_revoked`` items persist until removed.
"""

from __future__ import annotations

import hashlib
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from . import prompts
from .disruption_parser import to_priority
from .providers.base import AIProvider, LLMError
from .resolution import Resolver
from .schemas import Confidence, Issue, Meta, ParseContext, Priority
from .structured import call_structured


class FeedbackPreference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preference_id: str
    kind: Literal["avoid_employee", "prefer_employee", "objective_priority", "overtime_rule"]
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    priority: Optional[Priority] = None
    overtime_mode: Optional[Literal["never", "only_if_unavoidable", "allowed"]] = None
    scope: Literal["next_reschedule", "until_revoked"]
    strength: Literal["hard", "soft"]
    source_text: str
    created_on: str


class FeedbackResult(BaseModel):
    status: Literal["READY", "NEEDS_CLARIFICATION", "UNSUPPORTED", "ERROR"]
    preferences: list[FeedbackPreference] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    summary: str = ""
    confidence: Confidence = Field(default_factory=lambda: Confidence(score=0, level="none"))
    raw_request: str = ""
    meta: Meta = Field(default_factory=Meta)


class _RawItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str
    employee_mention: Optional[str] = None
    priority: Optional[str] = None
    overtime_mode: Optional[str] = None
    scope: str = "until_revoked"
    strength: str = "soft"
    text: str = ""


class _RawFeedback(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[_RawItem] = Field(default_factory=list)


def _pid(*parts: str) -> str:
    return "fb_" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]


class FeedbackParser:
    def __init__(self, provider: AIProvider) -> None:
        self.provider = provider

    def parse(self, text: str, ctx: ParseContext) -> FeedbackResult:
        text = (text or "").strip()
        meta = Meta(prompt=prompts.FEEDBACK.id, provider=self.provider.name, model=self.provider.model)
        try:
            raw, trace = call_structured(self.provider, prompts.FEEDBACK,
                                         prompts.wrap_user_text("Manager feedback", text[:2000]), _RawFeedback)
            meta.trace_id = trace.trace_id
        except LLMError as exc:
            return FeedbackResult(status="ERROR", raw_request=text, meta=meta,
                                  issues=[Issue(code="LLM_ERROR", message=f"Could not interpret the feedback ({exc}).")])
        result = self.resolve(raw, ctx)
        result.raw_request, result.meta = text, meta
        return result

    def resolve(self, raw: _RawFeedback, ctx: ParseContext) -> FeedbackResult:
        r = Resolver(ctx)
        prefs: list[FeedbackPreference] = []
        unsupported: list[str] = []
        for i, it in enumerate(raw.items):
            fp = f"items[{i}]"
            scope = it.scope if it.scope in ("next_reschedule", "until_revoked") else "until_revoked"
            strength = it.strength if it.strength in ("hard", "soft") else "soft"
            common = dict(scope=scope, strength=strength, source_text=it.text, created_on=ctx.reference_date)
            if it.kind in ("avoid_employee", "prefer_employee"):
                e = r.employee(it.employee_mention, f"{fp}.employee_id", "Which employee does this feedback refer to?")
                if e:
                    prefs.append(FeedbackPreference(preference_id=_pid(it.kind, e.id, scope), kind=it.kind,
                                                    employee_id=e.id, employee_name=e.name, **common))
            elif it.kind == "objective_priority" and to_priority(it.priority):
                p = to_priority(it.priority)
                prefs.append(FeedbackPreference(preference_id=_pid(it.kind, p.value, scope), kind=it.kind,
                                                priority=p, **{**common, "strength": "soft"}))
            elif it.kind == "overtime_rule" and it.overtime_mode in ("never", "only_if_unavoidable", "allowed"):
                strength = {"never": "hard", "only_if_unavoidable": "soft", "allowed": "soft"}[it.overtime_mode]
                prefs.append(FeedbackPreference(preference_id=_pid(it.kind, it.overtime_mode, scope), kind=it.kind,
                                                overtime_mode=it.overtime_mode, **{**common, "strength": strength}))
            else:
                unsupported.append(it.text or it.kind)

        avoid = {p.employee_id for p in prefs if p.kind == "avoid_employee"}
        prefer = {p.employee_id for p in prefs if p.kind == "prefer_employee"}
        for emp in sorted(avoid & prefer):
            r.issues.append(Issue(code="CONTRADICTORY_CHANGES",
                                  message=f"{r.names.get(emp, emp)} is both preferred and avoided."))
        if len({p.priority for p in prefs if p.kind == "objective_priority"}) > 1:
            r.issues.append(Issue(code="CONTRADICTORY_CHANGES", message="More than one top priority given."))
        for t in unsupported:
            r.issues.append(Issue(code="UNSUPPORTED_CHANGE", blocking=False,
                                  message=f"Can't turn this into a scheduling preference: '{t}'."))
        if unsupported:
            r.penalties.append(("part of the feedback is not actionable", 0.15))

        if not prefs and not any(i.blocking for i in r.issues):
            status = "UNSUPPORTED"
            if not unsupported:
                r.issues.append(Issue(code="NOT_FEEDBACK", message="No scheduling preference found in this message."))
        elif any(i.blocking for i in r.issues):
            status = "NEEDS_CLARIFICATION"
        else:
            status = "READY"
        res = FeedbackResult(status=status, preferences=prefs, unsupported=unsupported, issues=r.issues,
                             confidence=r.confidence())
        if status == "READY":
            res.summary = "; ".join(describe(p) for p in prefs) + "."
        return res


def describe(p: FeedbackPreference) -> str:
    when = " next time" if p.scope == "next_reschedule" else " from now on"
    if p.kind == "avoid_employee":
        verb = "never use" if p.strength == "hard" else "avoid using"
        return f"{verb} {p.employee_name} as a replacement{when}"
    if p.kind == "prefer_employee":
        return f"prefer {p.employee_name} as a replacement{when}"
    if p.kind == "objective_priority":
        return f"prioritize {p.priority.value.replace('_', ' ')}{when}"
    return {"never": "never use overtime", "only_if_unavoidable": "use overtime only if unavoidable",
            "allowed": "overtime is allowed"}[p.overtime_mode] + when
