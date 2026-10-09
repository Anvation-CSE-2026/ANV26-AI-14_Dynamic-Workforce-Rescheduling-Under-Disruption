"""One reliable path for every structured model call.

    call_structured(provider, spec, user_text, PydanticModel) -> (model, trace)

* transient provider errors (timeouts, 429, 5xx) → retried with backoff
* output that fails schema validation → one corrective retry that tells the
  model what was wrong
* every call → an ``AITrace`` (prompt name@version, provider, model, attempts,
  latency, input hash, outcome) sent to the registered trace sink, which the
  backend persists in its audit log.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, ValidationError

from .prompts import PromptSpec
from .providers.base import AIProvider, LLMError

log = logging.getLogger("resqwork.ai")

T = TypeVar("T", bound=BaseModel)

RETRY_BACKOFF_S = 0.6  # tests set this to 0


class AITrace(BaseModel):
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    task: str
    prompt: str
    provider: str
    model: str
    attempts: int = 0
    status: Literal["ok", "invalid_output", "provider_error"] = "ok"
    errors: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    input_sha256: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


TraceSink = Callable[[AITrace], None]
_sink: Optional[TraceSink] = None
_recent: deque[AITrace] = deque(maxlen=200)


def set_trace_sink(sink: Optional[TraceSink]) -> None:
    """Register a callable that persists traces (e.g. into the audit table)."""
    global _sink
    _sink = sink


def recent_traces() -> list[AITrace]:
    return list(_recent)


def _emit(trace: AITrace) -> None:
    _recent.append(trace)
    if _sink is not None:
        try:
            _sink(trace)
        except Exception:  # noqa: BLE001 - auditing must never break the request
            log.exception("trace sink failed")


class StructuredCallError(LLMError):
    def __init__(self, message: str, trace: AITrace) -> None:
        super().__init__(message)
        self.trace = trace


def call_structured(
    provider: AIProvider,
    spec: PromptSpec,
    user: str,
    model_cls: type[T],
    *,
    max_validation_retries: int = 1,
    max_transient_retries: int = 2,
) -> tuple[T, AITrace]:
    trace = AITrace(task=spec.name, prompt=spec.id, provider=provider.name, model=getattr(provider, "model", ""),
                    input_sha256=hashlib.sha256(user.encode()).hexdigest()[:16])
    started = time.monotonic()
    prompt = user
    validation_failures = transient_failures = 0

    while True:
        trace.attempts += 1
        try:
            out = provider.generate_structured(system=spec.system, user=prompt, schema=spec.schema,
                                               schema_name=spec.schema_name, max_tokens=spec.max_tokens)
        except LLMError as exc:
            trace.errors.append(str(exc))
            if exc.transient and transient_failures < max_transient_retries:
                transient_failures += 1
                time.sleep(RETRY_BACKOFF_S * (2 ** (transient_failures - 1)))
                continue
            trace.status = "provider_error"
            break
        try:
            if not isinstance(out, dict):
                raise ValueError(f"expected a JSON object, got {type(out).__name__}")
            result = model_cls.model_validate(out)
            trace.status = "ok"
            trace.latency_ms = int((time.monotonic() - started) * 1000)
            _emit(trace)
            return result, trace
        except (ValidationError, ValueError) as exc:
            msg = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
            loc = ".".join(str(x) for x in exc.errors()[0]["loc"]) if isinstance(exc, ValidationError) else ""
            trace.errors.append(f"invalid output at {loc or 'root'}: {msg}")
            if validation_failures < max_validation_retries:
                validation_failures += 1
                prompt = (f"{user}\n\nYour previous output was invalid ({loc or 'root'}: {msg}). "
                          "Return output that matches the schema exactly.")
                continue
            trace.status = "invalid_output"
            break

    trace.latency_ms = int((time.monotonic() - started) * 1000)
    _emit(trace)
    raise StructuredCallError(f"{spec.name}: {trace.errors[-1] if trace.errors else 'failed'}", trace)
