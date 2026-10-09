"""Section-aware chunking for policy documents.

Policies are cited by section ("HR-WT-001 §3.2"), so chunks follow headings
rather than fixed windows. Long sections are split on sentence boundaries,
and every chunk keeps its heading path for context and citation.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from .documents import PolicyDocument
from .text import sentences

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+([A-Z].{0,80})$")  # "3.2 Rest periods" as a bare line
_SECTION_NO = re.compile(r"^(?:section\s+)?(\d+(?:\.\d+)*)[.)]?\s+", re.I)


class PolicyChunk(BaseModel):
    chunk_id: str
    policy_id: str
    document: str
    section: str          # "3.2" if numbered, else heading text
    heading_path: str     # "3. Rest and recovery > 3.2 Rest between shifts"
    text: str
    position: int

    def context_text(self) -> str:
        """Text used for embedding/BM25: heading path adds topic words the body may omit."""
        return f"{self.heading_path}\n{self.text}"


def _section_label(heading: str) -> str:
    m = _SECTION_NO.match(heading)
    return m.group(1) if m else heading.strip()


def chunk_document(doc: PolicyDocument, max_words: int = 140) -> list[PolicyChunk]:
    stack: list[tuple[int, str]] = []
    blocks: list[tuple[list[str], list[str]]] = []  # (heading path, lines)
    current: list[str] = []

    def flush() -> None:
        if any(line.strip() for line in current):
            blocks.append(([h for _, h in stack], list(current)))
        current.clear()

    for line in doc.text.splitlines():
        m = _HEADING.match(line)
        n = None if m else _NUMBERED.match(line.strip())
        if m or (n and len(line.split()) <= 10):
            flush()
            level = len(m.group(1)) if m else n.group(1).count(".") + 2
            title = m.group(2) if m else line.strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        else:
            current.append(line)
    flush()

    chunks: list[PolicyChunk] = []
    for path, lines in blocks:
        body = "\n".join(lines).strip()
        heading = path[-1] if path else doc.title
        section = _section_label(heading)
        heading_path = " > ".join(path) if path else doc.title
        pieces = _split(body, max_words)
        for j, piece in enumerate(pieces):
            suffix = f"-{j + 1}" if len(pieces) > 1 else ""
            slug = re.sub(r"[^A-Za-z0-9.]+", "-", section).strip("-").lower()[:40]
            chunks.append(PolicyChunk(
                chunk_id=f"{doc.policy_id}#{slug}{suffix}", policy_id=doc.policy_id, document=doc.title,
                section=section, heading_path=heading_path, text=piece, position=len(chunks)))
    return _dedupe_ids(chunks)


def _split(body: str, max_words: int) -> list[str]:
    if len(body.split()) <= max_words:
        return [body]
    out, cur, n = [], [], 0
    for s in sentences(body):
        w = len(s.split())
        if cur and n + w > max_words:
            out.append(" ".join(cur))
            cur, n = [], 0
        cur.append(s)
        n += w
    if cur:
        out.append(" ".join(cur))
    return out


def _dedupe_ids(chunks: list[PolicyChunk]) -> list[PolicyChunk]:
    seen: dict[str, int] = {}
    for c in chunks:
        if c.chunk_id in seen:
            seen[c.chunk_id] += 1
            c.chunk_id = f"{c.chunk_id}~{seen[c.chunk_id]}"
        else:
            seen[c.chunk_id] = 1
    return chunks


def find_chunk(chunks: list[PolicyChunk], chunk_id: str) -> Optional[PolicyChunk]:
    return next((c for c in chunks if c.chunk_id == chunk_id), None)
