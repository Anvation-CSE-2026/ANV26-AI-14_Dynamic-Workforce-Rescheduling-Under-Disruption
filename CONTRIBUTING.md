# Contributing

## Ground rules

- **Rules live in `backend/core/rules.py` only.** If you add a constraint, add it there so CP-SAT, the search fallback and the validator stay in sync, then add a test in `tests/core` or `tests/engine`.
- **The engine never imports from `services/`, `app/`, `ai/` or the frontend.** `generate_repair(dataset, disruptions, settings)` must stay a pure function.
- **AI output is input, not a decision.** Anything from an LLM is validated with Pydantic, grounding-checked, and needs a deterministic fallback.
- **No industry `if` statements in the engine or the UI.** Industry differences belong in `shared/domains/`, `shared/policies/` or the dataset.
- **Explanations are built from computed facts only.** Don't add a number to an explanation unless it comes from `RepairOption` or `RejectedEvidence`.
- **Secrets stay server-side.** Never put a key in a `VITE_*` variable.

## Workflow

```bash
cd backend && python -m unittest discover -s tests -t .     # must stay green
cd frontend && npm run lint && npm run build
```

Regenerate derived files after changing their sources:

```bash
python -m scripts.build_domain_configs      # shared/domains/*.json
python -m scripts.build_demo_datasets       # shared/demo-data/*.json
python -m scripts.export_dataset_schema     # shared/schemas/dataset.schema.json
python -m scripts.export_ai_schemas         # shared/schemas/ai/*.json
python -m scripts.dev.try_repair healthcare # print options and why-not for each preset
```

## Layout conventions

- Backend: one module per concern; typed Pydantic models at boundaries; `ResQWorkError(message, status)` for user-facing errors.
- Frontend: screens in `src/screens`, generic widgets in `src/components/widgets`, all API calls through `src/api/client.ts`, and every screen handles loading, error and empty states.
- Commits: imperative mood ("Add on-call coverage KPI"), one logical change each.
