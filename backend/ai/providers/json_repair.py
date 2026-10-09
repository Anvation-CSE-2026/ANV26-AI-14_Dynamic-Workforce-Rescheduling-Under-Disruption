"""Recover a JSON object from imperfect model text.

Handles the usual failure shapes: markdown fences, prose before/after the
object, trailing commas, smart quotes, and Python literals (True/None).
It does NOT guess missing content; if no object can be recovered it raises
``ValueError`` and the caller retries or reports an error.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_SMART = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
_PY_LITERALS = [(re.compile(r"(?<![\w\"])True(?![\w\"])"), "true"),
                (re.compile(r"(?<![\w\"])False(?![\w\"])"), "false"),
                (re.compile(r"(?<![\w\"])None(?![\w\"])"), "null")]


def _first_balanced_object(text: str) -> str | None:
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        start = text.find("{", start + 1)
    return None


def extract_json_object(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty model output")
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    last_err = "no JSON object found"
    for cand in candidates:
        cand = cand.translate(_SMART).strip()
        obj = _first_balanced_object(cand)
        if obj is None:
            continue
        for attempt in (obj, _TRAILING_COMMA.sub(r"\1", obj)):
            fixed = attempt
            for pattern, repl in _PY_LITERALS:
                fixed = pattern.sub(repl, fixed)
            for variant in (attempt, fixed):
                try:
                    value = json.loads(variant)
                except json.JSONDecodeError as exc:
                    last_err = str(exc)
                    continue
                if isinstance(value, dict):
                    return value
                last_err = "top-level JSON is not an object"
    raise ValueError(last_err)
