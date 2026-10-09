"""Hybrid retrieval with an interpretable confidence.

ranking score  = 0.5 · BM25 (normalized per query) + 0.5 · confidence
confidence     = 0.65 · idf-weighted query-term coverage + 0.35 · cosine

Coverage is absolute ("how much of what was asked does this passage talk
about"), so it doubles as a calibrated relevance signal: a query about
parking against a working-time handbook scores ~0 and returns
"no applicable policy found" instead of the least-bad passage.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .chunker import PolicyChunk
from .embeddings import cosine
from .store import PolicyStore
from .text import tokenize

NO_POLICY = "no applicable policy found"
DEFAULT_MIN_CONFIDENCE = 0.35


class RetrievedPolicy(BaseModel):
    chunk: PolicyChunk
    confidence: float = Field(ge=0, le=1)
    score: float
    matched_terms: list[str]

    @property
    def policy_id(self) -> str:
        return self.chunk.policy_id

    def citation(self) -> str:
        return f"{self.chunk.document} §{self.chunk.section} ({self.chunk.policy_id})"


class RetrievalResult(BaseModel):
    query: str
    status: Literal["found", "no_applicable_policy"]
    hits: list[RetrievedPolicy] = Field(default_factory=list)
    message: str = ""


class Retriever:
    def __init__(self, store: PolicyStore, k1: float = 1.4, b: float = 0.75) -> None:
        self.store, self.k1, self.b = store, k1, b

    def _bm25(self, q_terms: list[str], i: int) -> float:
        toks = self.store.tokens[i]
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        dl, avg = len(toks), self.store.avg_len or 1.0
        s = 0.0
        for t in set(q_terms):
            f = tf.get(t, 0)
            if f:
                s += self.store.idf(t) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / avg))
        return s

    def search(self, query: str, k: int = 4, min_confidence: float = DEFAULT_MIN_CONFIDENCE,
               policy_ids: Optional[set[str]] = None) -> RetrievalResult:
        q_terms = list(dict.fromkeys(tokenize(query)))
        if not q_terms or not len(self.store):
            return RetrievalResult(query=query, status="no_applicable_policy", message=NO_POLICY)
        q_vec = self.store.embedder.embed([query], kind="query")[0]
        weights = {t: self.store.idf(t) for t in q_terms}
        total = sum(weights.values()) or 1.0

        rows = []
        for i, chunk in enumerate(self.store.chunks):
            if policy_ids and chunk.policy_id not in policy_ids:
                continue
            present = set(self.store.tokens[i])
            matched = [t for t in q_terms if t in present]
            coverage = sum(weights[t] for t in matched) / total
            cos = max(0.0, cosine(q_vec, self.store.vectors[i]))
            conf = min(1.0, 0.65 * coverage + 0.35 * cos)
            rows.append((i, conf, self._bm25(q_terms, i), matched))

        if not rows:
            return RetrievalResult(query=query, status="no_applicable_policy", message=NO_POLICY)
        bm_max = max(r[2] for r in rows) or 1.0
        hits = [RetrievedPolicy(chunk=self.store.chunks[i], confidence=round(conf, 3),
                                score=round(0.5 * bm / bm_max + 0.5 * conf, 4), matched_terms=matched)
                for i, conf, bm, matched in rows if conf >= min_confidence]
        hits.sort(key=lambda h: h.score, reverse=True)
        if not hits:
            return RetrievalResult(query=query, status="no_applicable_policy", message=NO_POLICY)
        return RetrievalResult(query=query, status="found", hits=hits[:k])
