# ResQWork

### Don't rebuild the schedule. Repair it intelligently.

**Live Demo:** https://anv26-ai-14-dynamic-workforce.onrender.com

ResQWork is an AI-assisted workforce scheduling and disruption management platform that repairs existing schedules with the smallest valid changes possible. When an employee becomes unavailable or a scheduling conflict occurs, ResQWork evaluates alternative assignments, checks workforce constraints, explains the proposed changes, and allows a manager to review and approve the repair before it is published.

Instead of rebuilding an entire schedule, ResQWork aims to preserve existing assignments while balancing skill coverage, working-hour limits, rest periods, overtime, and fairness.

## Key Features

- **Intelligent Schedule Repair:** Find minimal changes to an existing workforce schedule when disruptions occur.
- **Constraint-Based Optimization:** Evaluate candidate repairs against scheduling rules and employee qualifications.
- **AI-Assisted Interpretation:** Convert natural-language disruptions and manager requests into structured input when an AI provider is configured.
- **Explainable Decisions:** Present reasons and impact information to help managers understand proposed changes.
- **Human-in-the-Loop Approval:** Let managers review repair options before publishing schedule changes.
- **Conflict Detection:** Identify scheduling problems such as double bookings, uncovered shifts, and qualification mismatches.
- **What-If Analysis:** Explore alternative staffing decisions and their potential impact.
- **Workforce Analytics:** Review staffing coverage, workload, overtime, and fairness indicators.
- **Policy-Aware Scheduling:** Use industry-specific policy documents to inform applicable scheduling constraints.
- **Multiple Industry Configurations:** Adapt dashboards, terminology, KPIs, and policies for different workforce environments.
- **Voice Interaction:** Support voice-assisted interaction where the required browser or AI capabilities are available.
- **Dataset Import:** Load a dataset in ResQWork's supported JSON format or import schedule data through supported CSV workflows.

## Supported Industries

| Industry | Command Center |
|---|---|
| Healthcare | Hospital Command Center |
| Manufacturing | Plant Operations Command Center |
| Education | Academic Operations Dashboard |
| IT / Technology | Technology Workforce Command Center |
| Logistics / Field Services | Field Operations Command Center |

Each industry uses a shared scheduling and repair engine with domain-specific configuration, policies, dashboards, terminology, and performance indicators.

## How ResQWork Works

1. **Load the schedule:** Start with the existing schedule and employee information.
2. **Describe the disruption:** Provide an absence, availability change, or other scheduling problem.
3. **Interpret the request:** The AI layer or rule-based parser converts the request into structured data.
4. **Generate repair options:** The optimization engine searches for valid alternatives that minimize unnecessary changes.
5. **Validate the options:** Candidate schedules are checked against the applicable constraints.
6. **Explain the results:** Review the proposed changes and their impact.
7. **Approve the repair:** A manager reviews the proposal and confirms the changes.
8. **Publish the updated schedule:** Apply the approved repair and process the associated notifications where configured.

**Core principle:** AI helps interpret and explain the problem; scheduling rules and the optimization engine determine the proposed repair.

When an AI provider is not configured, supported rule-based parsing and template explanations can be used instead. OR-Tools CP-SAT is an optional optimization dependency; a built-in search fallback is available for suitable problem sizes.

## Technology Stack

| Component | Technology |
|---|---|
| Frontend | React 19, TypeScript |
| Frontend tooling | Vite |
| Styling | Tailwind CSS |
| Backend API | Python, FastAPI |
| API server | Uvicorn |
| Data validation | Pydantic |
| Optimization | OR-Tools CP-SAT (optional), built-in search fallback |
| AI integration | Configurable AI providers and rule-based fallback |
| Data storage | SQLite by default; PostgreSQL support is optional |
| Deployment | Render, Docker |
| Data formats | JSON, CSV, and supported XLSX workflows |

## Live Demo

Open the deployed application:

**https://anv26-ai-14-dynamic-workforce.onrender.com**

The live application is hosted on Render. Availability and response time may depend on the deployment's current status and hosting configuration.

### Testing ResQWork with the Sample JSON Dataset

The repository's sample dataset is:

`ResQWork_sample_dataset.json`

This sample represents a technology workforce with 12 employees across five teams:

- Payments
- Search
- Web
- Platform & SRE
- Data

It contains employee skills, certifications, shifts, existing assignments, scheduling disruptions, constraints, and optimization preferences. The included disruption scenarios involve an unavailable backend engineer and an unavailable on-call engineer.

#### Steps to test the sample dataset

1. Open the [ResQWork live application](https://anv26-ai-14-dynamic-workforce.onrender.com).
2. Sign in using an available demo account or follow the application's onboarding flow.
3. Open the dataset setup/onboarding screen.
4. Select **JSON upload**.
5. Choose `ResQWork_sample_dataset.json` from your computer.
6. Review the dataset and complete the application's validation and loading steps.
7. Open the workforce dashboard and review the loaded employees, schedule, and disruptions.
8. Select a disruption or enter a supported scheduling request.
9. Generate and review the proposed repair options.
10. Inspect the explanations and validation results before approving any proposed changes.

**Note:** The sample JSON file must be available locally on your computer before uploading it. If you downloaded only the source-code repository, use the separate sample dataset file provided with the project. If the deployed application rejects the dataset, check the validation message and confirm that the file matches the canonical ResQWork dataset schema.

The JSON dataset is for demonstration and testing; it does not represent a live organization's actual workforce.

## Getting Started Locally

### Prerequisites

- Python 3.10 or newer
- Node.js 20 or newer for frontend development
- npm
- Git (recommended)

### 1. Clone the repository

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd ResQWork
```

Replace `<YOUR_GITHUB_REPOSITORY_URL>` with your repository's actual URL.

### 2. Run the application

For the bundled application, the frontend build is included in `frontend/dist`.

**Windows**

Double-click `start.bat`.

**macOS**

Run:

```bash
chmod +x start.command
./start.command
```

**Linux**

Run:

```bash
chmod +x start.sh
./start.sh
```

The startup scripts set up the required Python environment and dependencies. An internet connection is required for the initial dependency installation.

Open:

http://localhost:8000

### 3. Run manually

From the repository root:

```bash
cd backend
pip install -r requirements.txt
python run.py
```

The application runs locally on port `8000` by default.

### 4. Run the frontend in development mode

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

The Vite development server runs on:

http://localhost:3000

The backend API runs separately on port `8000`.

To build the frontend:

```bash
npm run build
```

The build output is generated in `frontend/dist`.

## Docker Deployment

Docker can be used to build and run the application as a single service.

From the repository root:

```bash
docker compose up --build
```

Open:

http://localhost:8000

The provided Docker configuration builds the frontend and serves the built UI alongside the FastAPI backend.

## Configuration

Backend configuration is documented in `backend/.env.example`. Create a local `.env` file in the backend directory when you need to configure optional integrations.

| Variable | Purpose |
|---|---|
| `PORT` | Port used by the application; defaults to `8000` |
| `DATABASE_URL` | Database connection configuration; SQLite is the default |
| `RESQWORK_AUTH_MODE` | Selects the configured authentication mode |
| `RESQWORK_SECRET` | Secret used for signing authentication tokens |
| `RESQWORK_LLM_PROVIDER` | Configures the selected AI provider or disables external LLM usage |
| `ANTHROPIC_API_KEY` | Optional Claude integration |
| `OPENAI_API_KEY` | Optional OpenAI integration when the provider is configured and its dependency is installed |
| `GEMINI_API_KEY` | Optional Gemini integration for supported voice functionality |
| `ELEVENLABS_API_KEY` | Optional text-to-speech integration |
| `GOOGLE_CLIENT_ID` | Optional Google sign-in configuration |

Only configure the variables needed by your deployment. API keys and signing secrets must remain on the server and must not be committed to GitHub or exposed through frontend environment variables.

Optional integrations may require additional packages listed in the backend's optional requirements files.

## Project Structure

```text
ResQWork/
├── backend/
│   ├── app/             # FastAPI application and API routes
│   ├── core/            # Data models, scheduling rules and validation
│   ├── engine/          # Repair optimization and candidate evaluation
│   ├── analytics/       # Workforce impact and fairness calculations
│   ├── ai/              # AI providers, parsing and explanations
│   ├── rag/             # Policy retrieval and constraint extraction
│   ├── services/        # Application services and orchestration
│   ├── store/           # Persistence and data access
│   ├── tests/           # Automated tests
│   ├── requirements.txt
│   └── run.py
├── frontend/
│   ├── src/             # React application and UI components
│   ├── dist/            # Production frontend build, when present
│   └── package.json
├── shared/
│   ├── domains/         # Industry-specific configuration
│   ├── demo-data/       # Industry demo datasets
│   ├── samples/         # Sample CSV files
│   ├── scenarios/       # Test and demonstration scenarios
│   ├── policies/        # Industry policy handbooks
│   └── schemas/         # Dataset and AI JSON schemas
├── docs/                # Architecture, API and design documentation
├── Dockerfile
├── docker-compose.yml
├── start.bat
├── start.command
├── start.sh
└── README.md
```

## Running Tests

From the repository root:

```bash
cd backend
python -m unittest discover -s tests -t .
```

The automated test suite covers areas including dataset validation, repair-engine behavior, AI parsing and explanations, policy retrieval, and application services.

Some tests may require optional dependencies or live API credentials. Install the relevant optional packages and configure the required environment variables before running those tests.

To check the frontend TypeScript types:

```bash
cd frontend
npm install
npm run lint
```

## Documentation

Additional project documentation is available in the `docs/` directory:

- `docs/architecture.md` — system architecture
- `docs/api-contract.md` — API contract
- `docs/data-model.md` — data model
- `docs/optimization.md` — optimization, impact, and fairness
- `docs/domains.md` — industry configurations
- `docs/ai-design.md` — AI integration and explanation design
- `docs/rag-design.md` — policy retrieval and constraint handling
- `docs/demo-script.md` — demonstration walkthrough

## Design Principles

- **Minimal disruption:** Preserve existing assignments wherever possible.
- **Constraint-aware decisions:** Respect the applicable scheduling rules.
- **Explainability:** Make proposed changes understandable to managers.
- **Human oversight:** Require review and approval before publishing repairs.
- **Graceful fallback:** Keep supported workflows usable without optional AI integrations.
- **Domain adaptability:** Share the repair engine across multiple workforce environments.

## Limitations

- Repair quality and runtime depend on dataset size, available constraints, and the optimization method.
- The built-in search fallback is intended for suitable problem sizes and is not a substitute for a scalable solver in every scenario.
- AI-powered interpretation and voice functionality depend on the configured provider, credentials, browser support, and network access.
- A proposed schedule should be reviewed by an authorized manager before it is used operationally.
- The sample dataset is synthetic demonstration data and should not be treated as production workforce information.

## Contributing

Contributions, bug reports, and suggestions are welcome. Before submitting changes, test the affected backend or frontend components and avoid committing API keys, credentials, or real employee data.

See `CONTRIBUTING.md` for contribution guidance.

---

**ResQWork — Don't rebuild the schedule. Repair it intelligently.**
