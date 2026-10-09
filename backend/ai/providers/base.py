"""Provider-independent model interface.

Everything in ``ai/`` and ``rag/`` talks to a model through
``AIProvider.generate_structured``. Adding a vendor means one subclass; no
other file changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMError(RuntimeError):
    """Provider failure: network, auth, refusal, or no usable structured output.

    ``transient=True`` marks errors worth retrying (timeouts, 429, 5xx).
    """

    def __init__(self, message: str, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class AIProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def generate_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        schema_name: str,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Return a JSON object intended to match ``schema``.

        Implementations return a ``dict`` or raise ``LLMError``. They do not
        validate; ``ai.structured.call_structured`` does.
        """


# Round 1 name, kept so existing imports keep working.
LLMProvider = AIProvider


def is_transient(exc: Exception) -> bool:
    """Best-effort classification of SDK exceptions without importing SDKs."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if any(k in name for k in ("timeout", "ratelimit", "connection", "overloaded", "internalserver", "apistatus")):
        return True
    return any(k in text for k in ("timeout", "rate limit", "429", "500", "502", "503", "529", "overloaded"))
