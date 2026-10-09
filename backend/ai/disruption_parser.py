"""Manager message → validated Disruption(s), preferences and ad-hoc constraints.

    text → LLM extraction (untrusted) → schema validation (+1 corrective retry)
         → Resolver (names→IDs, dates, times, assignments) → canonical Disruption
         → ParseResult: READY / NEEDS_CLARIFICATION / UNSUPPORTED / ERROR
"""

from __future__ import annotations

from datetime import date as Date

from . import prompts
from .providers.base import AIProvider, LLMError
from .resolution import Resolver
from .schemas import (
    KNOWN_BUT_UNSUPPORTED_TYPES,
    AdHocConstraint,
    Issue,
    ManagerPreferences,
    Meta,
    ParseContext,
    ParseResult,
    Priority,
    RawExtraction,
)
from .structured import StructuredCallError, call_structured

MAX_REQUEST_CHARS = 2000


def build_user_prompt(request: str, ctx: ParseContext) -> str:
    ref = Date.fromisoformat(ctx.reference_date)
    return (prompts.reference_header(ctx.reference_date, ref.strftime("%A"), ctx.timezone) + "\n\n"
            + prompts.wrap_user_text("Manager message", request[:MAX_REQUEST_CHARS]))


def to_priority(value) -> Priority | None:
    try:
        return Priority(value) if value else None
    except ValueError:
        return None


class DisruptionParser:
    def __init__(self, provider: AIProvider | None) -> None:
        self.provider = provider  # None → only ``resolve`` (deterministic half) is usable

    def parse(self, request: str, ctx: ParseContext) -> ParseResult:
        request = (request or "").strip()
        meta = Meta(prompt=prompts.DISRUPTION.id, provider=self.provider.name, model=self.provider.model)
        base = {"raw_request": request, "meta": meta}
        if not request:
            return ParseResult(status="NEEDS_CLARIFICATION", **base,
                               issues=[Issue(code="NOT_A_DISRUPTION", message="The request is empty.")])
        try:
            raw, trace = call_structured(self.provider, prompts.DISRUPTION, build_user_prompt(request, ctx),
                                         RawExtraction)
            meta.trace_id = trace.trace_id
        except (StructuredCallError, LLMError) as exc:
            meta.trace_id = getattr(getattr(exc, "trace", None), "trace_id", "")
            return ParseResult(status="ERROR", **base, issues=[Issue(
                code="LLM_ERROR", message=f"Could not interpret the request ({exc}). Use the structured form.")])
        return self.resolve(raw, ctx, request, meta)

    def resolve(self, raw: RawExtraction, ctx: ParseContext, request: str = "", meta: Meta | None = None) -> ParseResult:
        """Deterministic half of parsing; also used directly by tests and the structured form."""
        base = {"raw_request": request, "meta": meta or Meta()}
        if not raw.is_disruption_report or not raw.disruptions:
            return ParseResult(status="UNSUPPORTED", **base, issues=[Issue(
                code="NOT_A_DISRUPTION",
                message="This doesn't look like a workforce disruption. "
                        "Try: 'Rahul is unavailable tomorrow from 09:00 to 17:00.'")])

        r = Resolver(ctx)
        disruptions, details = [], []
        for i, rd in enumerate(raw.disruptions):
            fp = f"disruptions[{i}]"
            if rd.type != "employee_unavailability":
                label = rd.type if rd.type in KNOWN_BUT_UNSUPPORTED_TYPES else "this kind of disruption"
                r.issues.append(Issue(code="UNSUPPORTED_DISRUPTION", field=f"{fp}.type",
                                      message=f"'{label}' is not supported yet; only employee unavailability is."))
                continue
            d, detail = r.disruption(rd, fp)
            if d is not None:
                disruptions.append(d)
                details.append(detail)

        rp = raw.preferences
        priority = to_priority(rp.priority)
        if rp.priority and priority is None:
            r.penalties.append((f"unrecognised priority '{rp.priority}' ignored", 0.1))
        prefs = ManagerPreferences(
            locked_employee_ids=r.employee_ids(rp.lock_employee_mentions, "preferences.locked_employee_ids"),
            excluded_employee_ids=r.employee_ids(rp.exclude_employee_mentions, "preferences.excluded_employee_ids"),
            allow_overtime=rp.allow_overtime, priority=priority)

        for emp_id in sorted({d.employee_id for d in disruptions} & set(prefs.locked_employee_ids)):
            r.issues.append(Issue(code="LOCKED_EMPLOYEE_CONFLICT", field="preferences.locked_employee_ids",
                                  message=f"{r.names.get(emp_id, emp_id)} is reported unavailable but also asked "
                                          "to keep their schedule unchanged. Which is it?"))
        for emp_id in sorted(set(prefs.locked_employee_ids) & set(prefs.excluded_employee_ids)):
            r.penalties.append((f"{r.names.get(emp_id, emp_id)} both locked and excluded", 0.05))

        ad_hoc, unsupported = self._ad_hoc(raw, r)

        if any(i.code == "UNSUPPORTED_DISRUPTION" for i in r.issues):
            status = "UNSUPPORTED"
        elif any(i.blocking for i in r.issues):
            status = "NEEDS_CLARIFICATION"
        else:
            status = "READY"
        result = ParseResult(
            status=status, disruptions=disruptions, details=details, preferences=prefs,
            ad_hoc_constraints=ad_hoc, unsupported_constraints=unsupported, issues=r.issues,
            assumptions=r.assumptions, confidence=r.confidence(), **base)
        if status == "READY":
            result.confirmation_summary = summarize(result, r.names)
        return result

    @staticmethod
    def _ad_hoc(raw: RawExtraction, r: Resolver) -> tuple[list[AdHocConstraint], list[str]]:
        out, unsupported = [], []
        for c in raw.ad_hoc_constraints:
            text = c.text or str(c.value or "")
            try:
                if c.kind == "max_daily_hours":
                    hours = float(c.value)
                    if not 1 <= hours <= 24:
                        raise ValueError
                    out.append(AdHocConstraint(kind="max_daily_hours", value=hours, text=text))
                elif c.kind in ("required_skill", "only_team") and isinstance(c.value, str) and c.value.strip():
                    out.append(AdHocConstraint(kind=c.kind, value=c.value.strip(), text=text))
                else:
                    raise ValueError
            except (TypeError, ValueError):
                unsupported.append(text)
        if unsupported:
            r.penalties.append(("some stated requirements can't be enforced", 0.1))
            for t in unsupported:
                r.issues.append(Issue(code="UNSUPPORTED_CONSTRAINT", blocking=False,
                                      message=f"ResQWork can't enforce: '{t}'. It will NOT be applied."))
        return out, unsupported


def summarize(result: ParseResult, names: dict[str, str]) -> str:
    parts = []
    for d, det in zip(result.disruptions, result.details):
        day = Date.fromisoformat(d.date).strftime("%a %d %b %Y")
        reason = "" if d.reason == "unspecified" else f" ({d.reason})"
        on = f" on {det.assignment_id}" if det.assignment_id else ""
        parts.append(f"{det.employee_name} ({d.employee_id}) unavailable {day}, {d.start_time}–{d.end_time}{on}{reason}.")
    p, rules = result.preferences, []
    if p.locked_employee_ids:
        rules.append("keep " + ", ".join(names.get(i, i) for i in p.locked_employee_ids) + " unchanged")
    if p.excluded_employee_ids:
        rules.append("don't use " + ", ".join(names.get(i, i) for i in p.excluded_employee_ids))
    if p.allow_overtime is False:
        rules.append("no overtime")
    elif p.allow_overtime is True:
        rules.append("overtime allowed")
    if p.priority:
        rules.append("priority: " + p.priority.value.replace("_", " "))
    rules += [c.text for c in result.ad_hoc_constraints]
    if rules:
        parts.append("Instructions: " + "; ".join(rules) + ".")
    if result.unsupported_constraints:
        parts.append("Not enforced: " + "; ".join(result.unsupported_constraints) + ".")
    return " ".join(parts)
