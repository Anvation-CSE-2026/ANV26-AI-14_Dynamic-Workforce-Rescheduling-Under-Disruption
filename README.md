# ResQWork

**Don't rebuild the schedule. Repair it intelligently.**

When someone can't make their shift, ResQWork takes the schedule you already have and finds the *smallest valid change* to it. A constraint solver checks every rule, each decision comes with an explanation built from the solver's own numbers, and a manager approves before anything is published.

It is one platform for five industries. The repair engine is shared, and each industry gets its own configuration: terminology, KPIs, dashboards, risk indicators and policy handbook.

| Industry | Command center | Sub-dashboards |
|---|---|---|
| Healthcare | Hospital Command Center | Clinical Staff · Hospital Workforce / HR |
| Manufacturing | Plant Operations Command Center | Shift Supervisor · Workforce / HR |
| Education | Academic Operations Dashboard | Teacher / Department · Academic Admin |
| IT / Technology | Technology Workforce Command Center | Engineering Manager · Resource Management |
| Logistics / Field Services | Field Operations Command Center | Dispatch · Resource Management |

## How it works

```
existing schedule ─┐
disruption ────────┼─▶ AI understands (parse, policies) ─▶ solver repairs (CP-SAT) ─▶ validator re-checks
manager intent ────┘                                                                    │
                                     manager approves ◀─ grounded explanation ◀─ options A–D
                                            │
                              new schedule version ─▶ only affected people are notified
```

- **The AI interprets and explains. It never decides.** Plain-language disruptions, what-ifs, manager feedback and policy documents become structured input, and explanations are written only from facts the solver computed. If no LLM key is set, rule-based parsers and template explanations take over.
- **The solver decides.** It uses OR-Tools CP-SAT when that's installed, and otherwise an exact bounded search. Both read the same rules (`backend/core/rules.py`), and every option passes a full post-solve validation.
- **A human approves.** Nothing is published without approval, either on screen or by voice. A partial repair (one that leaves a shift uncovered) needs an explicit acknowledgement.
- **Impossible is reported, not faked.** When no valid repair exists, ResQWork says so and shows the bottleneck constraint, who came closest, and what a manager could change. It never relaxes a hard rule on its own.
- **Conflicts already in the data are repaired too.** Double bookings, unqualified assignees and open shifts are detected and sent through the same repair-and-approve flow.

## Quick start

The website is already built (`frontend/dist`), so you only need **Python 3.10+**:

- **Windows:** double-click `start.bat`
- **macOS:** double-click `start.command`
- **Linux:** `./start.sh`

The first start creates `backend/.venv` and installs four Python packages (internet needed once). After that it opens http://localhost:8000. Sign in with `manager@healthcare.demo` / `demo1234`, or pick any demo account on the home page. See `START HERE.txt`.

Manual start: `cd backend && pip install -r requirements.txt && python run.py`.

Developing the website (hot reload, needs Node 20+): `cd frontend && npm install && npm run dev` (http://localhost:3000, with the API on :8000). `npm run build` refreshes `frontend/dist`.

Docker: `docker compose up --build` serves everything on http://localhost:8000.

## Repository

```
backend/
  core/        canonical data model, hard rules (single source), dataset validation + CSV import
  engine/      repair problem, CP-SAT model, exact search fallback, evaluation, options A–D, why-not
  analytics/   impact & fairness formulas
  ai/          LLM providers, structured parsing, grounded explanations, what-if, feedback
  rag/         policy retrieval → structured constraints with verbatim citations
  services/    ResQWork orchestrator, domains, KPIs, analytics, auth, voice
  store/       org-scoped document store (SQLite or Postgres/Supabase via DATABASE_URL)
  app/         FastAPI app + routes
  tests/       unittest suite (core, engine, services, ai, rag)
frontend/      React + Vite + Tailwind UI (domain-driven dashboards)
shared/
  domains/     per-industry config (terminology, KPIs, sub-dashboards, labels, actions)
  demo-data/   realistic dataset per industry, with "simulate" presets
  scenarios/   small hand-checkable test datasets (double booking, infeasible CNC shift)
  policies/    per-industry policy handbooks (Markdown) used by RAG
  schemas/     dataset.schema.json + AI JSON Schemas
docs/          architecture, API, data model, optimization, domains, AI, RAG, demo script
```

## Tests

```bash
cd backend
python -m unittest discover -s tests -t .
```

The suite runs 259 tests (8 skipped, which need live API keys or OR-Tools). They cover rules, validation, the repair engine across all five domains, the full disruption → approval → notification flow, RBAC/auth, voice, the AI layer and RAG.

## Configuration

All secrets are server-side environment variables; see `backend/.env.example`. The frontend only reads public `VITE_*` values (`frontend/.env.example`).

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `sqlite:///./resqwork.db` (default) or Postgres/Supabase `postgresql+psycopg://…` |
| `RESQWORK_AUTH_MODE` | `demo` (anonymous demo manager allowed) or `required` |
| `RESQWORK_SECRET` | token signing secret (set in production) |
| `RESQWORK_LLM_PROVIDER` | `claude` · `openai` · `gemini` · `none` (+ matching API key) |
| `GOOGLE_CLIENT_ID` / `VITE_GOOGLE_CLIENT_ID` | optional Google sign-in |
| `GEMINI_API_KEY` | voice assistant: Gemini transcribes and interprets spoken commands (`RESQWORK_GEMINI_VOICE_MODEL`, default `gemini-3.8-flash`). Without it, browser speech recognition or typing is used |
| `RESQWORK_DEMO_ACCOUNTS` | seed the demo logins (default: on in `demo` auth mode) |
| `ELEVENLABS_API_KEY` | optional server text-to-speech; the browser's speech is used otherwise |

## Docs

[Architecture](docs/architecture.md) · [API](docs/api-contract.md) · [Data model](docs/data-model.md) · [Optimization, impact & fairness](docs/optimization.md) · [Domains](docs/domains.md) · [AI layer](docs/ai-design.md) · [Policy RAG](docs/rag-design.md) · [Demo script](docs/demo-script.md) · [Contributing](CONTRIBUTING.md)
