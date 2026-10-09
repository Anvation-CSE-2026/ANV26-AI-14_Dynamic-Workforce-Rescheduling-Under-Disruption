"""Deterministic provider for tests and offline demos.

``responses`` can be:
* a list of canned responses, returned in order;
* a dict ``{schema_name: response | [responses]}`` for multi-task flows;
* a function ``(system, user, schema_name) -> response``.

A response that is an ``Exception`` is raised; a ``str`` is passed through
JSON repair (to simulate text-returning providers). Every call is recorded.
"""

from __future__ import annotations

from typing import Any, Callable, Union

from .base import AIProvider, LLMError
from .json_repair import extract_json_object

Responder = Callable[[str, str, str], Any]


class MockProvider(AIProvider):
    name = "mock"
    model = "mock-1"

    def __init__(self, responses: Union[list[Any], dict[str, Any], Responder, None] = None) -> None:
        self._responses = responses if responses is not None else []
        self.calls: list[dict[str, Any]] = []

    def _next(self, system: str, user: str, schema_name: str) -> Any:
        r = self._responses
        if callable(r):
            return r(system, user, schema_name)
        if isinstance(r, dict):
            if schema_name not in r:
                raise LLMError(f"MockProvider has no response for {schema_name}")
            v = r[schema_name]
            if isinstance(v, list):
                if not v:
                    raise LLMError(f"MockProvider ran out of responses for {schema_name}")
                return v.pop(0)
            return v
        if not r:
            raise LLMError("MockProvider has no more responses")
        return r.pop(0)

    def generate_structured(self, *, system: str, user: str, schema: dict[str, Any],
                            schema_name: str, max_tokens: int = 1024) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        out = self._next(system, user, schema_name)
        if isinstance(out, Exception):
            raise out
        if isinstance(out, str):
            try:
                return extract_json_object(out)
            except ValueError as exc:
                raise LLMError(f"unparseable output: {exc}") from exc
        return out
