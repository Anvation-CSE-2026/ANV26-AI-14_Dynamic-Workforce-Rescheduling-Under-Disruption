"""ResQWork organization-policy RAG.

LLM understands, RAG retrieves, the constraint engine structures, CP-SAT decides.
Raw policy text never reaches the optimizer: only validated, source-tracked
``PolicyConstraint`` objects do.

``PolicyService``/``PolicyBundle`` are loaded lazily because they depend on
``ai`` (whose prompts depend on ``rag.constraints``).
"""

from .constraints import CONSTRAINT_TYPES, PolicyConflict, PolicyConstraint, resolve_conflicts, to_optimizer_config
from .documents import PolicyDocument, load_directory, load_file, parse_document
from .retriever import NO_POLICY, RetrievalResult, Retriever
from .store import PolicyStore


def __getattr__(name: str):
    if name in ("PolicyService", "PolicyBundle", "SCHEDULING_TOPICS"):
        from . import service  # noqa: PLC0415
        return getattr(service, name)
    raise AttributeError(name)


__all__ = ["CONSTRAINT_TYPES", "NO_POLICY", "PolicyBundle", "PolicyConflict", "PolicyConstraint", "PolicyDocument",
           "PolicyService", "PolicyStore", "RetrievalResult", "Retriever", "load_directory", "load_file",
           "parse_document", "resolve_conflicts", "to_optimizer_config"]
