# Architecture

## Principles

1. **Repair, don't rebuild.** The input is an existing schedule. The objective penalizes every change against it, so the best answer is usually one reassignment rather than a new roster.
2. **One engine, many industries.** Nothing in `core/`, `engine/` or `analytics/` knows which industry it is serving. Industry behaviour comes from data: `shared/domains/<id>.json` (UI, KPIs, labels), `shared/policies/<id>/` (rules), and the dataset itself (skills, certifications, priorities, attributes).
3. **The AI interprets and explains; the solver decides; a human approves.** The LLM never assigns anyone. Its outputs are schema-validated and grounding-checked, and there is a deterministic fallback for every AI step.
4. **Rules live in one place.** `core/rules.py` is used by the CP-SAT model, the exact search fallback, the post-solve validator and the why-not evidence, so the four cannot disagree.
5. **The optimizer is independent of the UI.** `engine.repair.generate_repair(dataset, disruptions, settings)` is a pure function. The API, the voice agent and the tests all call it the same way.

## Layers

```
frontend (React)            Landing · Onboarding · Command center · Sub-dashboards · Schedule · Repair center
                            Policies · Versions & audit · Analytics · Employee portal · Voice agent
        │ JSON over /api (Bearer token)
app/api/routes.py           auth + RBAC dependencies, request models, thin handlers
        │
services/workspace.py       ResQWork orchestrator: datasets, disruptions, proposals, what-if, approve/reject,
                            versions, notifications, availability requests, audit, dashboards
services/{domains,kpis,analytics,voice,auth,bridge}.py
        │                                  │
engine/ (repair)                           ai/ + rag/ (interpretation, explanation, policy constraints)
core/ (model, rules, validation)           analytics/metrics.py (impact, fairness)
        │
store/                      org-scoped documents: SQLite (default) or Postgres/Supabase (SQLAlchemy)
```

## Request flow: a disruption, end to end

1. **Report.** `POST /api/disruptions` with `{text}`, `{structured}` or `{preset_id}`. Text is parsed by the AI layer (or by the rule parser when no LLM is configured) into a `Disruption`. Ambiguity returns `NEEDS_CLARIFICATION` with candidate employees; nothing is guessed.
2. **Affected shifts.** The orchestrator finds assignments overlapping the unavailability window that start after "now" (`reference_date` + `reference_time`). Shifts that have already started are frozen.
3. **Policies.** RAG retrieves the relevant sections of the org's policy handbook and turns them into structured constraints, each with a verbatim quote. Policies can only *tighten* the base rules.
4. **Repair.** `generate_repair` builds a `RepairProblem` (eligibility plus a human-readable reason for every excluded pair) and solves it once per strategy: Recommended, Lowest employee impact, Lowest overtime, Highest fairness. Duplicate answers are merged, distinct alternatives are found with no-good cuts, and an alternative is shown only if it offers a real trade-off.
5. **Validate.** Every option is re-checked against all hard rules. Anything that fails is dropped.
6. **Evidence.** For selected people: hours before/after, rest, matched skills, overtime. For everyone else: the rule that excludes them, or a counterfactual re-solve that forces them in and measures the extra cost.
7. **Explain.** The explanation (LLM or template) is generated from those facts only. Grounding checks reject names and numbers that don't appear in the facts.
8. **Decide.** `POST /api/reschedule/approve` publishes a new version (`v1.1`, `v1.2`, …), notifies only employees whose shifts changed, updates fairness history and writes the audit log. `reject` keeps the current schedule.

## Security

- **Authentication:** email + password (PBKDF2), optional Google ID-token sign-in, and demo login. Tokens are HMAC-signed (`RESQWORK_SECRET`).
- **Roles:** `admin`, `operations_manager`, `department_manager`, `employee`. Managers can read and act on operations. Only admins and operations managers can load datasets or upload policies. Employees can only read their own schedule and notifications and submit their own availability.
- **Organization isolation:** every stored document is keyed by `org`. A signed-in user's org comes from their own user record, never from whatever another user loaded. The anonymous "active demo org" fallback exists only in `RESQWORK_AUTH_MODE=demo`.
- **Validation:** request bodies go through Pydantic models, and datasets go through `core/validation.py`, which reports missing fields, invalid records, duplicates, invalid shifts, unknown references, skill mismatches and constraint conflicts record by record.
- **Secrets:** server-side env vars only. The frontend bundle contains nothing secret.
- **Employee notices** are template-generated and checked to make sure they never leak the absent colleague's reason (`ai/employee_notice.py`).

## Storage

`store/` is a tiny document store (`put/get/list/delete` by `kind`, `id`, `org`).

| kind | contents |
|---|---|
| `workspace` | current dataset, version tag, original schedule |
| `disruption` | reported disruptions + affected shifts + status |
| `proposal` | repair run: options, explanations, comparison, policy bundle |
| `version` | published schedules with their changes and metrics |
| `notification` | per-employee change notices + acknowledgement |
| `availability_request` | employee-submitted conflicts |
| `feedback` | manager preferences learned from feedback |
| `policy_doc` | uploaded policy documents |
| `audit` | append-only event log |
| `user` (org `_global`) | accounts |

With `DATABASE_URL=postgresql+psycopg://…` the same table lives in Postgres (for example Supabase). Loading a dataset resets that org's operational state (disruptions, proposals, versions, notifications, requests) but keeps the audit history, feedback and uploaded policies.

## Added in the change-request round

| Concern | Where | Notes |
|---|---|---|
| Conflicts already in the schedule | `engine/conflicts.py`, `GET /api/conflicts`, `POST /api/conflicts/resolve` | Release/cover inputs to the same engine; nothing is fixed silently |
| Unresolved-constraint analysis | `engine/diagnosis.py` → `RepairResult.unresolved` | Funnel, bottleneck, ranked near misses, resolutions (overrides are never automatic) |
| Hard vs soft constraints | `RepairResult.hard_constraints / soft_objectives` | Shown in the Repair Centre's constraint analysis |
| Employee requests | `ResQWork.submit_availability / decide_request` | One record per request; `pending → approved → completed`, `rejected`, `needs_review`; dashboards poll it |
| Demo accounts | `services/demo_accounts.py` | Password accounts per industry; demo data loads once and is never reset by a login |
| Voice | `services/voice_agent.py`, `services/gemini_voice.py` | Gemini (`generateContent`, inline audio) for speech understanding; answers come from ResQWork data and can open the matching screen |
| Recognition | `services/recognition.py`, `shared/domains/*.json → recognition` | Behaviour-based signals, domain vocabulary, manager awards, 90-day tiers, anti-gaming caps |
| Test scenarios | `shared/scenarios/`, `scripts/build_scenarios.py` | Double booking, skill/cert mismatch, overtime trap, infeasible CNC shift |
