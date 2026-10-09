"""Generic grounding checks for any generated text built on a FACTS object.

Used by explanations, candidate comparisons and employee notices. A text
passes only if:
* every point cites ``fact_refs`` that resolve to real paths in the facts;
* every number in the text appears in the facts;
* every roster employee it names appears in the facts;
* (optionally) it contains no forbidden terms, e.g. a colleague's reason for absence.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

_NUM_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def _walk(obj: Any) -> Iterable[Any]:
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        yield len(obj)
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


def allowed_numbers(facts: dict) -> set[float]:
    allowed: set[float] = {100.0}  # scores are reported "out of 100"
    for v in _walk(facts):
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            allowed.add(float(v))
        elif isinstance(v, str):
            allowed.update(float(n) for n in _NUM_RE.findall(v))
    return allowed


def resolve_ref(facts: Any, ref: str) -> bool:
    cur = facts
    for part in ref.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False
    return True


def names_in(facts: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(facts, dict):
        for k, v in facts.items():
            if isinstance(v, str) and (k.endswith("_name") or k == "name"):
                out.add(v)
            else:
                out |= names_in(v)
    elif isinstance(facts, list):
        for v in facts:
            out |= names_in(v)
    return out


def check_narration(
    texts: list[str],
    points: list[tuple[str, list[str]]],
    facts: dict,
    roster_names: Optional[Iterable[str]] = None,
    forbidden_terms: Iterable[str] = (),
) -> list[str]:
    """Return problems (empty = grounded). ``texts`` = every sentence shown; ``points`` = (text, refs) pairs."""
    problems: list[str] = []
    for text, refs in points:
        if not refs:
            problems.append(f"point has no fact_refs: {text!r}")
        for ref in refs:
            if not resolve_ref(facts, ref):
                problems.append(f"unknown fact_ref {ref!r}")

    allowed = allowed_numbers(facts)
    for t in texts:
        for n in _NUM_RE.findall(t):
            if float(n) not in allowed:
                problems.append(f"number {n} not in facts: {t!r}")

    blob = " ".join(texts)
    if roster_names:
        in_facts = names_in(facts)
        first_names = {n.split()[0].lower() for n in in_facts if n.strip()}
        for name in roster_names:
            if not name.strip() or name in in_facts:
                continue
            first = name.split()[0]
            full_hit = re.search(rf"\b{re.escape(name)}\b", blob)
            first_hit = first.lower() not in first_names and re.search(rf"\b{re.escape(first)}\b", blob)
            if full_hit or first_hit:
                problems.append(f"mentions {name!r}, who is not in the facts")

    low = blob.lower()
    for term in forbidden_terms:
        if term and re.search(rf"\b{re.escape(term.lower())}\b", low):
            problems.append(f"contains forbidden term {term!r}")
    return problems
