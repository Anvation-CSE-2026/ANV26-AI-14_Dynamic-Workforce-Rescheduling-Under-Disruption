"""Policy store: documents, chunks, vectors and lexical statistics.

In-memory with JSON persistence, which is plenty for an organization's
policy set (hundreds of chunks). The interface (add/remove/chunks/vectors)
is what a pgvector-backed store would implement for production.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Optional

from .chunker import PolicyChunk, chunk_document
from .documents import PolicyDocument
from .embeddings import Embedder, HashingEmbedder
from .text import tokenize


class PolicyStore:
    def __init__(self, embedder: Optional[Embedder] = None) -> None:
        self.embedder = embedder or HashingEmbedder()
        self.documents: dict[str, PolicyDocument] = {}
        self.chunks: list[PolicyChunk] = []
        self.vectors: list[list[float]] = []
        self.tokens: list[list[str]] = []
        self._df: Counter = Counter()
        self.avg_len: float = 0.0

    # ------------------------------------------------------------- writes

    def add_document(self, doc: PolicyDocument) -> list[PolicyChunk]:
        """Add or replace a document (same policy_id → new version replaces old)."""
        if doc.policy_id in self.documents:
            self.remove_document(doc.policy_id)
        self.documents[doc.policy_id] = doc
        new = chunk_document(doc)
        vecs = self.embedder.embed([c.context_text() for c in new], kind="document") if new else []
        self.chunks.extend(new)
        self.vectors.extend(vecs)
        self.tokens.extend(tokenize(c.context_text()) for c in new)
        self._reindex()
        return new

    def remove_document(self, policy_id: str) -> None:
        keep = [i for i, c in enumerate(self.chunks) if c.policy_id != policy_id]
        self.chunks = [self.chunks[i] for i in keep]
        self.vectors = [self.vectors[i] for i in keep]
        self.tokens = [self.tokens[i] for i in keep]
        self.documents.pop(policy_id, None)
        self._reindex()

    def _reindex(self) -> None:
        self._df = Counter()
        for toks in self.tokens:
            self._df.update(set(toks))
        self.avg_len = (sum(len(t) for t in self.tokens) / len(self.tokens)) if self.tokens else 0.0

    # -------------------------------------------------------------- reads

    def __len__(self) -> int:
        return len(self.chunks)

    def idf(self, term: str) -> float:
        n = len(self.chunks)
        df = self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def max_idf(self) -> float:
        return self.idf("__never_seen__")

    def get_chunk(self, chunk_id: str) -> Optional[PolicyChunk]:
        return next((c for c in self.chunks if c.chunk_id == chunk_id), None)

    # -------------------------------------------------------- persistence

    def save(self, path: str | Path) -> None:
        data = {"embedder": self.embedder.name,
                "documents": [d.model_dump() for d in self.documents.values()]}
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path, embedder: Optional[Embedder] = None) -> "PolicyStore":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        store = cls(embedder)
        for d in data.get("documents", []):
            store.add_document(PolicyDocument.model_validate(d))
        return store
