"""Claude implementation of ``AIProvider`` (the active provider).

Structured output comes from forcing one tool call whose ``input_schema`` is
the schema we want. If the response somehow carries text instead, the text is
run through JSON repair. The SDK is imported lazily.
"""

from __future__ import annotations

import os
from typing import Any

from .base import AIProvider, LLMError, is_transient
from .json_repair import extract_json_object

DEFAULT_MODEL = "claude-sonnet-5-5"


class ClaudeProvider(AIProvider):
    name = "claude"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout_s: float = 20.0, client: Any | None = None) -> None:
        self.model = model or os.getenv("RESQWORK_LLM_MODEL") or DEFAULT_MODEL
        if client is not None:
            self._client = client
            return
        try:
            import anthropic  # noqa: PLC0415
        except ImportError as exc:
            raise LLMError("anthropic SDK not installed: pip install anthropic") from exc
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=key, timeout=timeout_s, max_retries=0)

    def generate_structured(self, *, system: str, user: str, schema: dict[str, Any],
                            schema_name: str, max_tokens: int = 1024) -> dict[str, Any]:
        tool = {"name": schema_name, "description": f"Return the result as {schema_name}.",
                "input_schema": schema}
        try:
            resp = self._client.messages.create(
                model=self.model, max_tokens=max_tokens, temperature=0, system=system,
                messages=[{"role": "user", "content": user}],
                tools=[tool], tool_choice={"type": "tool", "name": schema_name},
            )
        except Exception as exc:  # noqa: BLE001 - SDK raises many types
            raise LLMError(f"Claude request failed: {exc}", transient=is_transient(exc)) from exc

        texts = []
        for block in getattr(resp, "content", None) or []:
            kind = getattr(block, "type", None)
            if kind == "tool_use" and getattr(block, "name", None) == schema_name and isinstance(block.input, dict):
                return block.input
            if kind == "text":
                texts.append(block.text)
        if texts:
            try:
                return extract_json_object("\n".join(texts))
            except ValueError as exc:
                raise LLMError(f"Claude returned unparseable text: {exc}") from exc
        if getattr(resp, "stop_reason", None) == "max_tokens":
            raise LLMError("Claude output was truncated (max_tokens)", transient=True)
        raise LLMError("Claude returned no structured output")
