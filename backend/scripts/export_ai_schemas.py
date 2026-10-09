"""Export the AI/RAG contracts as JSON Schema into shared/schemas/ai/.

Run from backend/:  python -m scripts.export_ai_schemas
Frontend can generate TypeScript types from these (e.g. json-schema-to-typescript).
"""

import json
from pathlib import Path

from ai.candidates import CandidateComparison, CandidateFacts
from ai.employee_notice import EmployeeNotice
from ai.feedback import FeedbackResult
from ai.schemas import Disruption, Explanation, ExplanationFacts, ParseContext, ParseResult
from ai.service import InterpretResult
from ai.what_if import ScenarioSpec
from rag.retriever import RetrievalResult
from rag.service import PolicyBundle

OUT = Path(__file__).resolve().parents[2] / "shared" / "schemas" / "ai"

MODELS = {
    # backend → AI
    "ParseContext": ParseContext, "ExplanationFacts": ExplanationFacts, "CandidateFacts": CandidateFacts,
    # AI → backend / frontend
    "Disruption": Disruption, "ParseResult": ParseResult, "InterpretResult": InterpretResult,
    "ScenarioSpec": ScenarioSpec, "FeedbackResult": FeedbackResult, "PolicyBundle": PolicyBundle,
    "RetrievalResult": RetrievalResult, "Explanation": Explanation, "CandidateComparison": CandidateComparison,
    "EmployeeNotice": EmployeeNotice,
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, model in MODELS.items():
        (OUT / f"{name}.schema.json").write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
    print(f"wrote {len(MODELS)} schemas to {OUT}")
