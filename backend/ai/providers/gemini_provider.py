"""Gemini implementation of ``AIProvider`` (inactive; Claude is the active provider).

Gemini's response-schema dialect differs from JSON Schema (no union types),
so the schema is given in the prompt and JSON mime type is requested. The
output goes through JSON repair and the same Pydantic validation.
Not exercised in CI; verify with the live test before switching to it.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .base import AIProvider, LLMError, is_transient
from .json_repair import extract_json_object

DEFAULT_MODEL = "gemini-2.5-pro"


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 client: Any | None = None) -> None:
        self.model = model or os.getenv("RESQWORK_GEMINI_MODEL") or DEFAULT_MODEL
        if client is not None:
            self._client, self._types = client, None
            return
        try:
            from google import genai  # noqa: PLC0415
            from google.genai import types  # noqa: PLC0415
        except ImportError as exc:
            raise LLMError("google-genai SDK not installed: pip install google-genai") from exc
        key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise LLMError("GEMINI_API_KEY is not set")
        self._client, self._types = genai.Client(api_key=key), types

    def generate_structured(self, *, system: str, user: str, schema: dict[str, Any],
                            schema_name: str, max_tokens: int = 1024) -> dict[str, Any]:
        prompt = (f"{user}\n\nRespond with ONE JSON object named {schema_name} "
                  f"matching this JSON Schema:\n{json.dumps(schema)}")
        try:
            config = None
            if self._types is not None:
                config = self._types.GenerateContentConfig(
                    system_instruction=system, temperature=0, max_output_tokens=max_tokens,
                    response_mime_type="application/json")
            resp = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
            text = getattr(resp, "text", "") or ""
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Gemini request failed: {exc}", transient=is_transient(exc)) from exc
        try:
            return extract_json_object(text)
        except ValueError as exc:
            raise LLMError(f"Gemini returned unparseable output: {exc}") from exc
