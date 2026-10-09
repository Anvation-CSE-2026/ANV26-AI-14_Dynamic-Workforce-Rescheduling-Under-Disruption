"""OpenAI implementation of ``AIProvider`` (inactive; Claude is the active provider).

Uses JSON-schema response formatting in non-strict mode, because ResQWork
schemas use optional fields. Output text goes through JSON repair and then
the same Pydantic validation as every other provider.
Not exercised in CI; verify with the live test before switching to it.
"""

from __future__ import annotations

import os
from typing import Any

from .base import AIProvider, LLMError, is_transient
from .json_repair import extract_json_object

DEFAULT_MODEL = "gpt-4.1"


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout_s: float = 20.0, client: Any | None = None) -> None:
        self.model = model or os.getenv("RESQWORK_OPENAI_MODEL") or DEFAULT_MODEL
        if client is not None:
            self._client = client
            return
        try:
            import openai  # noqa: PLC0415
        except ImportError as exc:
            raise LLMError("openai SDK not installed: pip install openai") from exc
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise LLMError("OPENAI_API_KEY is not set")
        self._client = openai.OpenAI(api_key=key, timeout=timeout_s, max_retries=0)

    def generate_structured(self, *, system: str, user: str, schema: dict[str, Any],
                            schema_name: str, max_tokens: int = 1024) -> dict[str, Any]:
        try:
            resp = self._client.chat.completions.create(
                model=self.model, temperature=0, max_tokens=max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": schema_name, "schema": schema, "strict": False}},
            )
            text = resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"OpenAI request failed: {exc}", transient=is_transient(exc)) from exc
        try:
            return extract_json_object(text)
        except ValueError as exc:
            raise LLMError(f"OpenAI returned unparseable output: {exc}") from exc
