"""Policy intelligence service: the one entry point the backend uses for policies.

    svc = PolicyService(provider)
    svc.ingest_directory("shared/policies")
    bundle = svc.build_bundle(request_text, roles=["L2 Support"], assignments=["SUPPORT_L2"])
    bundle.optimizer_config   → to CP-SAT (values only)
    bundle.citations()        → into ExplanationFacts.policies_applied
    bundle.conflicts / warnings → to the manager UI
    svc.lookup("how much rest between shifts?") → grounded passages or "no applicable policy found"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ai.providers.base import AIProvider
from ai.schemas import PolicyCitation

from .constraints import PolicyConflict, PolicyConstraint, resolve_conflicts, to_optimizer_config
from .documents import PolicyDocument, load_directory, load_file
from .embeddings import Embedder
from .policy_parser import PolicyTranslator, RejectedItem, UnsupportedRule
from .retriever import NO_POLICY, RetrievalResult, Retriever
from .store import PolicyStore

# Topics every reschedule must check, whatever the manager typed.
SCHEDULING_TOPICS: dict[str, str] = {
    "working_hours": "maximum working hours per day and per week",
    "rest": "minimum rest between shifts",
    "overtime": "overtime limits and approval",
    "consecutive_days": "maximum consecutive working days",
    "weekends": "weekend work limits per month",
    "staffing": "minimum staffing coverage agents on queue",
    "skills": "skills certification needed to cover queue or assignment",
    "schedule_changes": "how often an employee schedule can be changed reassigned",
    "preferences": "employee shift preferences",
    "fairness": "fair distribution rotation of overtime and shifts among employees",
}


class TopicCoverage(BaseModel):
    topic: str
    query: str
    status: Literal["found", "no_applicable_policy"]
    chunk_ids: list[str] = Field(default_factory=list)
    best_confidence: float = 0.0
    message: str = ""


class PolicyBundle(BaseModel):
    """Everything policy-related for one optimization run."""

    mode: Literal["llm", "rules", "none"]
    constraints: list[PolicyConstraint] = Field(default_factory=list, description="Applied after conflict resolution")
    conflicts: list[PolicyConflict] = Field(default_factory=list)
    unsupported: list[UnsupportedRule] = Field(default_factory=list)
    rejected: list[RejectedItem] = Field(default_factory=list)
    topics: list[TopicCoverage] = Field(default_factory=list)
    optimizer_config: dict[str, Any] = Field(default_factory=dict)
    trace_ids: list[str] = Field(default_factory=list)

    def citations(self) -> list[PolicyCitation]:
        return [PolicyCitation(policy_id=c.source.policy_id, document=c.source.document, section=c.source.section,
                               constraint_type=c.constraint_type, value=c.value, unit=c.unit)
                for c in self.constraints]

    def warnings(self) -> list[str]:
        out = [c.message for c in self.conflicts]
        out += [f"Not enforced (no supported rule type): {u.text} — {u.policy_id} §{u.section}" for u in self.unsupported]
        out += [f"Low-confidence interpretation: {c.interpretation} ({c.source.document} §{c.source.section})"
                for c in self.constraints if c.interpretation_confidence < 0.6]
        return out


class PolicyService:
    def __init__(self, provider: Optional[AIProvider] = None, store: Optional[PolicyStore] = None,
                 embedder: Optional[Embedder] = None, min_confidence: float = 0.35) -> None:
        self.store = store or PolicyStore(embedder)
        self.retriever = Retriever(self.store)
        self.translator = PolicyTranslator(provider)
        self.min_confidence = min_confidence

    # ------------------------------------------------------------ ingest

    def ingest(self, doc: PolicyDocument) -> int:
        return len(self.store.add_document(doc))

    def ingest_file(self, path: str | Path) -> int:
        return self.ingest(load_file(path))

    def ingest_directory(self, path: str | Path) -> int:
        return sum(self.ingest(d) for d in load_directory(path))

    # ---------------------------------------------------------- retrieval

    def lookup(self, question: str, k: int = 3) -> RetrievalResult:
        """Grounded policy lookup for a manager question. Returns passages, never generated policy."""
        return self.retriever.search(question, k=k, min_confidence=self.min_confidence)

    # ------------------------------------------------------------- bundle

    def build_bundle(self, request_text: str = "", roles: Optional[list[str]] = None,
                     assignments: Optional[list[str]] = None, k_per_topic: int = 5,
                     exhaustive: bool = False) -> PolicyBundle:
        """Constraints that apply to this reschedule.

        Retrieval picks the relevant passages per scheduling topic (plus the request
        and any roles/assignments involved). ``exhaustive=True`` translates every chunk
        instead: use it for a nightly "compile all policies" job or very small
        handbooks, where missing a rule is costlier than a few extra tokens.
        """
        if not len(self.store):
            return PolicyBundle(mode="none", topics=[TopicCoverage(topic=t, query=q, status="no_applicable_policy",
                                                                   message=NO_POLICY)
                                                     for t, q in SCHEDULING_TOPICS.items()])
        queries = dict(SCHEDULING_TOPICS)
        if request_text.strip():
            queries["request"] = request_text.strip()
        for r in roles or []:
            queries[f"role:{r}"] = f"{r} requirements hours skills staffing"
        for a in assignments or []:
            queries[f"assignment:{a}"] = f"{a.replace('_', ' ')} staffing skills requirements"

        topics: list[TopicCoverage] = []
        best: dict[str, float] = {}
        order: list[str] = []
        for topic, q in queries.items():
            res = self.retriever.search(q, k=k_per_topic, min_confidence=self.min_confidence)
            cov = TopicCoverage(topic=topic, query=q, status=res.status, message=res.message,
                                chunk_ids=[h.chunk.chunk_id for h in res.hits],
                                best_confidence=max((h.confidence for h in res.hits), default=0.0))
            topics.append(cov)
            for h in res.hits:
                if h.chunk.chunk_id not in best:
                    order.append(h.chunk.chunk_id)
                best[h.chunk.chunk_id] = max(best.get(h.chunk.chunk_id, 0.0), h.confidence)

        if exhaustive:
            for c in self.store.chunks:
                if c.chunk_id not in best:
                    order.append(c.chunk_id)
                    best[c.chunk_id] = 0.0
        chunks = [self.store.get_chunk(cid) for cid in order]
        tr = self.translator.translate([c for c in chunks if c], best)
        applied, conflicts = resolve_conflicts(tr.constraints)
        return PolicyBundle(
            mode=tr.mode, constraints=applied, conflicts=tr.mismatches + conflicts, unsupported=tr.unsupported,
            rejected=tr.rejected, topics=topics, optimizer_config=to_optimizer_config(applied),
            trace_ids=tr.trace_ids)
