"""Embedding layer.

``HashingEmbedder`` (default) is local, deterministic and dependency-free:
domain-normalized unigrams + bigrams, signed feature hashing, L2 norm. It
needs no API key and no model download, which keeps the demo and CI offline.

``VoyageEmbedder`` is the hosted option (Anthropic's recommended embeddings
partner). Switch with ``RESQWORK_EMBEDDER=voyage``. The store doesn't care
which one is used.
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Protocol

from .text import bigrams, tokenize


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]: ...


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # vectors are L2-normalized


class HashingEmbedder:
    name = "hashing-v1"

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def _index(self, feature: str) -> tuple[int, float]:
        h = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")
        return h % self.dim, (1.0 if (h >> 63) & 1 else -1.0)

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        out = []
        for t in texts:
            toks = tokenize(t)
            vec = [0.0] * self.dim
            counts: dict[str, int] = {}
            for f in toks + bigrams(toks):
                counts[f] = counts.get(f, 0) + 1
            for f, c in counts.items():
                i, sign = self._index(f)
                vec[i] += sign * (1.0 + math.log(c)) * (0.7 if "_" in f else 1.0)
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class VoyageEmbedder:
    """Hosted embeddings via Voyage AI. Requires ``pip install voyageai`` and VOYAGE_API_KEY."""

    name = "voyage"

    def __init__(self, model: str | None = None) -> None:
        try:
            import voyageai  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("voyageai not installed: pip install voyageai") from exc
        self.model = model or os.getenv("RESQWORK_EMBED_MODEL", "voyage-3.5")
        self.name = f"voyage:{self.model}"
        self._client = voyageai.Client()

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        res = self._client.embed(texts, model=self.model, input_type="query" if kind == "query" else "document")
        vecs = res.embeddings
        return [[x / (math.sqrt(sum(y * y for y in v)) or 1.0) for x in v] for v in vecs]


def get_embedder(name: str | None = None) -> Embedder:
    name = (name or os.getenv("RESQWORK_EMBEDDER", "hashing")).lower()
    if name == "voyage":
        return VoyageEmbedder()
    return HashingEmbedder()
