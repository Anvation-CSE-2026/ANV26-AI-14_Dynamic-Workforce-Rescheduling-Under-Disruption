"""ResQWork AI layer: language in → validated structure out; optimizer facts in → grounded text out.

"AI interprets. Optimization decides." Nothing in this package assigns an
employee or edits a schedule.

``AIService`` is loaded lazily to keep ``ai`` ↔ ``rag`` imports acyclic.
"""

from .providers import (
    AIProvider,
    ClaudeProvider,
    GeminiProvider,
    LLMError,
    LLMProvider,
    MockProvider,
    OpenAIProvider,
    get_provider,
)
from .schemas import (
    AssignmentRef,
    ChangeFact,
    Disruption,
    EmployeeRef,
    Explanation,
    ExplanationFacts,
    Issue,
    ManagerPreferences,
    MetricsFact,
    ParseContext,
    ParseResult,
    PolicyCitation,
    Priority,
    RejectedFact,
    SelectedFact,
    ShiftRef,
)


def __getattr__(name: str):
    if name == "AIService":
        from .service import AIService  # noqa: PLC0415
        return AIService
    raise AttributeError(name)


__all__ = [
    "AIProvider", "AIService", "AssignmentRef", "ChangeFact", "ClaudeProvider", "Disruption", "EmployeeRef",
    "Explanation", "ExplanationFacts", "GeminiProvider", "Issue", "LLMError", "LLMProvider", "ManagerPreferences",
    "MetricsFact", "MockProvider", "OpenAIProvider", "ParseContext", "ParseResult", "PolicyCitation", "Priority",
    "RejectedFact", "SelectedFact", "ShiftRef", "get_provider",
]
