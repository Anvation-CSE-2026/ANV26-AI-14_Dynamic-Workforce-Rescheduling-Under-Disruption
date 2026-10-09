from __future__ import annotations

import logging
import os
from typing import Optional

from .base import AIProvider, LLMError, LLMProvider
from .claude import ClaudeProvider
from .gemini_provider import GeminiProvider
from .mock import MockProvider
from .openai_provider import OpenAIProvider

log = logging.getLogger("resqwork.ai")

_REGISTRY = {"claude": ClaudeProvider, "openai": OpenAIProvider, "gemini": GeminiProvider}


def get_provider(name: Optional[str] = None) -> Optional[AIProvider]:
    """Provider from ``RESQWORK_LLM_PROVIDER`` (claude | openai | gemini | none).

    Returns None (and logs) when the provider can't start, so the app still
    runs with deterministic fallbacks.
    """
    name = (name or os.getenv("RESQWORK_LLM_PROVIDER", "claude")).lower()
    if name in ("none", "off", ""):
        return None
    cls = _REGISTRY.get(name)
    if cls is None:
        log.warning("Unknown provider %r; running without an LLM", name)
        return None
    try:
        return cls()
    except LLMError as exc:
        log.warning("LLM provider %s unavailable, running without it: %s", name, exc)
        return None


__all__ = ["AIProvider", "LLMProvider", "LLMError", "ClaudeProvider", "OpenAIProvider",
           "GeminiProvider", "MockProvider", "get_provider"]
