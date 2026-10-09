"""Retrieved policy chunks → validated, source-tracked constraints.

For every model-proposed constraint:
1. ``chunk_id`` must be one of the chunks we sent;
2. ``quote`` must appear verbatim in that chunk (no fabricated policy);
3. type/value/unit/bounds pass ``validate_constraint``;
4. the deterministic rule extractor re-reads the quote:
   agree → verified; disagree → strictest value applied + flagged for review;
5. rules the model missed in a chunk are added from the rule extractor.

Raw policy text never reaches the optimizer; only these validated objects do.
"""

from __future__ import annotations

import hashlib
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from ai import prompts
from ai.providers.base import AIProvider, LLMError
from ai.structured import call_structured

from .chunker import PolicyChunk
from .constraints import (
    CONSTRAINT_TYPES,
    ConflictOption,
    PolicyConflict,
    PolicyConstraint,
    PolicySource,
    _strictest,
    validate_constraint,
)
from .rule_extractor import extract_rules, rule_value_for
from .text import normalize_for_match

BATCH_SIZE = 10


class UnsupportedRule(BaseModel):
    chunk_id: str
    policy_id: str
    section: str
    text: str


class RejectedItem(BaseModel):
    chunk_id: Optional[str] = None
    reason: str
    item: dict = Field(default_factory=dict)


class TranslationResult(BaseModel):
    mode: Literal["llm", "rules"]
    constraints: list[PolicyConstraint] = Field(default_factory=list)
    unsupported: list[UnsupportedRule] = Field(default_factory=list)
    rejected: list[RejectedItem] = Field(default_factory=list)
    mismatches: list[PolicyConflict] = Field(default_factory=list)
    trace_ids: list[str] = Field(default_factory=list)


class _RawConstraint(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chunk_id: str
    constraint_type: str
    value: Union[bool, float, str]
    unit: Optional[str] = None
    severity: str = "hard"
    scope: Optional[dict] = None
    quote: str = ""
    interpretation: str = ""


class _RawUnsupported(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chunk_id: str = ""
    text: str = ""


class _RawTranslation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    constraints: list[dict] = Field(default_factory=list)
    unsupported_rules: list[_RawUnsupported] = Field(default_factory=list)


def _source(chunk: PolicyChunk, quote: str) -> PolicySource:
    return PolicySource(policy_id=chunk.policy_id, document=chunk.document, section=chunk.section,
                        chunk_id=chunk.chunk_id, quote=quote)


def _passages(chunks: list[PolicyChunk]) -> str:
    return "\n\n".join(f"[chunk_id: {c.chunk_id}] {c.document} §{c.section} ({c.heading_path})\n<<<\n{c.text}\n>>>"
                       for c in chunks)


class PolicyTranslator:
    def __init__(self, provider: Optional[AIProvider] = None) -> None:
        self.provider = provider
        self._cache: dict[str, TranslationResult] = {}

    def _key(self, chunk: PolicyChunk) -> str:
        model = f"{self.provider.name}:{self.provider.model}" if self.provider else "rules"
        raw = f"{prompts.POLICY_TRANSLATION.id}|{model}|{chunk.chunk_id}|{chunk.text}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def translate(self, chunks: list[PolicyChunk], retrieval_confidence: Optional[dict[str, float]] = None) -> TranslationResult:
        rc = retrieval_confidence or {}
        if self.provider is None:
            return self._rules_only(chunks, rc)

        out = TranslationResult(mode="llm")
        todo = [c for c in chunks if self._key(c) not in self._cache]
        for i in range(0, len(todo), BATCH_SIZE):
            batch = todo[i:i + BATCH_SIZE]
            try:
                raw, trace = call_structured(self.provider, prompts.POLICY_TRANSLATION, _passages(batch), _RawTranslation)
            except LLMError as exc:
                # Model unavailable for this batch: fall back to rules for these chunks, and say so.
                fb = self._rules_only(batch, rc)
                fb.rejected.append(RejectedItem(reason=f"LLM translation failed, rules used: {exc}"))
                for c in batch:
                    self._cache[self._key(c)] = self._only(fb, c.chunk_id)
                continue
            per_chunk = self._validate(batch, raw)
            for c in batch:
                r = per_chunk[c.chunk_id]
                r.trace_ids.append(trace.trace_id)
                self._cache[self._key(c)] = r

        for c in chunks:
            self._merge(out, self._cache[self._key(c)], rc.get(c.chunk_id))
        return out

    # ------------------------------------------------------------------

    def _validate(self, batch: list[PolicyChunk], raw: _RawTranslation) -> dict[str, TranslationResult]:
        by_id = {c.chunk_id: c for c in batch}
        res = {c.chunk_id: TranslationResult(mode="llm") for c in batch}
        for item in raw.constraints:
            try:
                rc = _RawConstraint.model_validate(item)
            except Exception as exc:  # noqa: BLE001
                res[batch[0].chunk_id].rejected.append(RejectedItem(reason=f"malformed item: {exc}", item=item))
                continue
            chunk = by_id.get(rc.chunk_id)
            if chunk is None:
                res[batch[0].chunk_id].rejected.append(RejectedItem(chunk_id=rc.chunk_id, reason="unknown chunk_id", item=item))
                continue
            r = res[chunk.chunk_id]
            quote = rc.quote.strip()
            if len(quote) < 8 or normalize_for_match(quote) not in normalize_for_match(chunk.text):
                r.rejected.append(RejectedItem(chunk_id=chunk.chunk_id, reason="quote not found in policy text", item=item))
                continue
            try:
                c = validate_constraint({
                    "constraint_type": rc.constraint_type, "value": rc.value, "unit": rc.unit,
                    "severity": rc.severity if rc.severity in ("hard", "soft") else "hard",
                    "scope": {k: v for k, v in (rc.scope or {}).items() if k in ("role", "assignment", "team")},
                    "source": _source(chunk, quote), "interpretation": rc.interpretation or quote,
                    "extracted_by": "llm"})
            except ValueError as exc:
                r.rejected.append(RejectedItem(chunk_id=chunk.chunk_id, reason=str(exc), item=item))
                continue
            self._verify(c, r)
            r.constraints.append(c)

        for u in raw.unsupported_rules:
            chunk = by_id.get(u.chunk_id)
            if chunk and u.text.strip():
                res[chunk.chunk_id].unsupported.append(
                    UnsupportedRule(chunk_id=chunk.chunk_id, policy_id=chunk.policy_id, section=chunk.section, text=u.text))

        # Safety net: rules the model missed.
        for chunk in batch:
            r = res[chunk.chunk_id]
            have = {c.constraint_type for c in r.constraints}
            for m in extract_rules(chunk.text):
                if m.constraint_type not in have:
                    c = self._from_rule(chunk, m, confidence=0.6)
                    if c:
                        r.constraints.append(c)
                        r.rejected.append(RejectedItem(chunk_id=chunk.chunk_id,
                                                       reason=f"model missed {m.constraint_type}; added from rules"))
        return res

    @staticmethod
    def _verify(c: PolicyConstraint, r: TranslationResult) -> None:
        rv = rule_value_for(c.source.quote, c.constraint_type)
        if rv is None:
            c.verified_by_rules, c.interpretation_confidence = None, 0.75
        elif rv == c.value:
            c.verified_by_rules, c.interpretation_confidence = True, 0.95
        else:
            spec = CONSTRAINT_TYPES[c.constraint_type]
            strict = _strictest(spec, [c.value, rv])
            r.mismatches.append(PolicyConflict(
                constraint_type=c.constraint_type, scope=c.scope.label(), kind="interpretation_mismatch",
                options=[ConflictOption(value=c.value, severity=c.severity, scope=c.scope.label(), source=c.source),
                         ConflictOption(value=rv, severity=c.severity, scope=c.scope.label(), source=c.source)],
                applied_value=strict, resolution="strictest_applied",
                message=(f"Model read {c.value} but the rule check read {rv} from "
                         f"{c.source.document} §{c.source.section}. Applying the stricter value {strict}; please review.")))
            c.value, c.verified_by_rules, c.interpretation_confidence = strict, False, 0.4

    @staticmethod
    def _from_rule(chunk: PolicyChunk, m, confidence: float) -> Optional[PolicyConstraint]:
        try:
            c = validate_constraint({
                "constraint_type": m.constraint_type, "value": m.value, "severity": m.severity,
                "source": _source(chunk, m.quote), "interpretation": m.quote, "extracted_by": "rules"})
        except ValueError:
            return None
        c.interpretation_confidence, c.verified_by_rules = confidence, True
        return c

    def _rules_only(self, chunks: list[PolicyChunk], rc: dict[str, float]) -> TranslationResult:
        out = TranslationResult(mode="rules")
        for chunk in chunks:
            for m in extract_rules(chunk.text):
                c = self._from_rule(chunk, m, confidence=0.6)
                if c:
                    c.retrieval_confidence = rc.get(chunk.chunk_id)
                    out.constraints.append(c)
        return out

    @staticmethod
    def _only(res: TranslationResult, chunk_id: str) -> TranslationResult:
        return TranslationResult(
            mode=res.mode,
            constraints=[c for c in res.constraints if c.source.chunk_id == chunk_id],
            unsupported=[u for u in res.unsupported if u.chunk_id == chunk_id],
            rejected=[r for r in res.rejected if r.chunk_id in (chunk_id, None)],
            mismatches=[m for m in res.mismatches if m.options[0].source.chunk_id == chunk_id])

    @staticmethod
    def _merge(out: TranslationResult, part: TranslationResult, retrieval_conf: Optional[float]) -> None:
        for c in part.constraints:
            c = c.model_copy()
            c.retrieval_confidence = retrieval_conf
            out.constraints.append(c)
        out.unsupported += part.unsupported
        out.rejected += part.rejected
        out.mismatches += part.mismatches
        out.trace_ids += [t for t in part.trace_ids if t not in out.trace_ids]
