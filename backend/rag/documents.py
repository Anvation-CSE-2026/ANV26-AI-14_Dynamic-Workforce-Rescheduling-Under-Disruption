"""Policy documents and loaders.

Markdown/text files with optional front matter:

    ---
    policy_id: HR-WT-001
    title: Working Time Policy
    version: 3.1
    effective_date: 2026-01-01
    ---
    # 1. Scope
    ...

Without front matter, ``policy_id`` is derived from the file name.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class PolicyDocument(BaseModel):
    policy_id: str
    title: str
    text: str
    version: str = "1"
    effective_date: Optional[str] = None
    source_path: Optional[str] = None
    content_sha256: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)

    def model_post_init(self, _ctx) -> None:
        if not self.content_sha256:
            self.content_sha256 = hashlib.sha256(self.text.encode()).hexdigest()[:16]


def parse_document(text: str, default_id: str, source_path: Optional[str] = None) -> PolicyDocument:
    meta: dict[str, str] = {}
    m = _FRONT.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip().strip('"').strip("'")
        text = text[m.end():]
    title = meta.pop("title", None)
    if not title:
        h = re.search(r"^#\s+(.+)$", text, re.M)
        title = h.group(1).strip() if h else default_id
    return PolicyDocument(
        policy_id=meta.pop("policy_id", default_id), title=title, text=text.strip(),
        version=meta.pop("version", "1"), effective_date=meta.pop("effective_date", None),
        source_path=source_path, metadata=meta)


def load_file(path: str | Path) -> PolicyDocument:
    p = Path(path)
    if p.suffix.lower() not in (".md", ".markdown", ".txt"):
        raise ValueError(f"unsupported policy file type: {p.suffix} (use .md or .txt; convert PDFs first)")
    default_id = re.sub(r"[^A-Za-z0-9]+", "-", p.stem).strip("-").upper()
    return parse_document(p.read_text(encoding="utf-8"), default_id, str(p))


def load_directory(path: str | Path) -> list[PolicyDocument]:
    return [load_file(p) for p in sorted(Path(path).glob("*")) if p.suffix.lower() in (".md", ".markdown", ".txt")]
