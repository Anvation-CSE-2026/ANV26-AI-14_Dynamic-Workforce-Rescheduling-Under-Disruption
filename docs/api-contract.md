# API contract

Base path: `/api`. JSON in, JSON out. Errors look like `{"error": "message"}` with a meaningful status (400 bad input, 401 not signed in, 403 wrong role or not your data, 404 not found, 409 conflict, 501 feature not configured).

Authentication: `Authorization: Bearer <token>` from any `/auth/*` call. Interactive docs are at `/docs` when the server runs.

Roles: **M** = manager (`admin`, `operations_manager`, `department_manager`), **A** = `admin` or `operations_manager`, **E** = the employee themself (or a manager), **any** = any signed-in user.

## Auth

| Method | Path | Role | Body → Response |
|---|---|---|---|
| POST | `/auth/register` | none | `{email, password(≥8), name, role}` → `{user, token}` |
| POST | `/auth/login` | none | `{email, password}` → `{user, token}` |
| POST | `/auth/google` | none | `{id_token}` → `{user, token}` (501 unless `GOOGLE_CLIENT_ID`) |
| POST | `/auth/demo` | none | `{role, domain?, employee_id?}` → `{user, token}`; with `domain`, loads that demo dataset |
| GET | `/auth/me` | any | → `user` |
| GET | `/auth/demo-accounts` | none | seeded demo logins (manager, admin, 2 employees per industry; password `demo1234`). Empty unless demo accounts are enabled |

`/auth/demo` with `domain` loads that demo **only the first time**; later logins reuse it so data flows between users. Pass `reset: true` to reload it.

## Domains & onboarding

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/domains` | none | list of `{id, label, tagline, icon, accent, dashboardName}` |
| GET | `/domains/{id}` | none | full domain config (`shared/domains/{id}.json`) |
| POST | `/datasets/validate` | none | raw dataset JSON → `ValidationReport` (nothing stored) |
| POST | `/datasets/validate-csv` | none | multipart `schedule_csv`, optional `employees_csv`, `organization` (JSON) → `{report, dataset}` |
| POST | `/datasets/load` | A | raw dataset → `{report, workspace}`; resets this org's operational state |
| POST | `/datasets/demo/{domain}` | A | loads the industry demo → `{report, workspace}` |
| GET | `/scenarios` | none | hand-checkable test datasets (`shared/scenarios/`) |
| POST | `/datasets/scenario/{name}` | A | load one (`repair-cases`, `infeasible-cnc`) |
| GET | `/workspace` | any | `WorkspaceSummary`: org, domain config, version, counts, simulate presets |

`ValidationReport`: `{status: valid|valid_with_warnings|invalid, errors[], warnings[], stats{}, summary}`. Each finding is `{severity, category, path, message, record_id}`. Categories include `missing_field`, `invalid_record`, `duplicate`, `invalid_shift`, `unknown_reference`, `skill_mismatch`, `constraint_conflict` and `coverage`.

## Operations

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/dashboard` | M | KPIs (domain + common), widgets, open disruptions, latest proposal card, pending employee requests |
| GET | `/employees` | M | employees |
| GET | `/schedule` | M | rows with `status: scheduled|open|disrupted|changed` and original assignee |
| POST | `/disruptions` | M | `{text}` · `{structured:{employee_id,date,start?,end?,reason?}}` · `{preset_id}` → `{status, interpretation, disruptions[]}` |
| GET | `/disruptions` | M | all disruption records |
| POST | `/disruptions/{id}/dismiss` | M | |
| GET | `/conflicts` | M | hard-rule conflicts already in the schedule: `double_booking, rest_violation, missing_skill, missing_certification, unavailable_assignee, daily_hours, weekly_hours, open_shift`, each with `release` (shift → why the assignee comes off) and `cover` |
| POST | `/conflicts/resolve` | M | `{conflict_ids?}` → `Proposal` (nothing changes until approval) |
| POST | `/reschedule` | M | `{disruption_ids?}` (default: all open) → `Proposal` |
| GET | `/reschedule/latest` | M | latest `Proposal` or `null` |
| GET | `/reschedule/{id}` | M | `Proposal` |
| POST | `/what-if` | M | `{proposal_id, text}` or `{proposal_id, spec}` → `{status, scenario, proposal?, delta?}`; never publishes |
| POST | `/reschedule/approve` | M | `{proposal_id, option_id?, notes?, allow_partial?}` → `{version, notifications[]}`. 409 if the proposal was already decided, or if the option leaves shifts uncovered and `allow_partial` is false |
| POST | `/reschedule/reject` | M | `{proposal_id, reason?}` → `Proposal` |
| POST | `/ai/interpret` | M | `{text}` → routes to disruption, what-if, feedback or policy question: `{intent, result, message?}` |
| POST | `/feedback` · GET `/feedback` | M | manager feedback becomes preferences for future runs |
| GET | `/availability-requests` | M | employee-submitted conflicts |
| POST | `/availability-requests/{id}/decision` | M | `{status: approved|rejected|needs_review, note}`. Approving an absence creates a disruption; the request becomes `completed` when that repair is approved |
| POST | `/availability-requests/{id}/accept` | M | alias for approving |
| GET | `/recognition` | M | `{config, employees[summary], recent}` |
| POST | `/recognition` | M | `{employee_id, category, note}` (note required) |
| GET | `/employees/{id}/recognition` | E | the employee's summary: points (90 days), tier, categories, awards |
| GET | `/notifications` | M | all notices + acknowledgement state |

### Proposal

```jsonc
{
  "id": "prop_…", "status": "pending|approved|rejected", "scenario": "allow overtime" /* what-if runs */,
  "result": {
    "status": "OPTIMAL|FEASIBLE|PARTIAL|INFEASIBLE", "solver": "OR-Tools CP-SAT | exact bounded search", "solve_ms": 91,
    "disrupted_shifts": ["ICU-D-1009"],
    "options": [{
      "option_id": "A", "label": "Option A", "title": "Recommended", "strategy": "recommended", "goal": "…",
      "changes": [{"shift_id", "date", "start", "end", "assignment", "from_employee_name", "to_employee_name", "kind"}],
      "selected": [{"employee_name", "weekly_hours_before", "weekly_hours_after", "rest_hours_before_shift", "matched_skills", "overtime_hours_added", …}],
      "impact": {"impact_score", "impact_level", "assignments_changed", "employees_affected", "overtime_hours_added", "unfilled_shifts", "preservation_rate", "formula", …},
      "fairness": {"fairness_score", "workload_balance", "overtime_distribution", "change_concentration", "preference_respect"}
    }],
    "recommended_option_id": "A",
    "rejected": [{"employee_name", "reason_code", "detail", "extra_cost"}],
    "baseline": {"method": "Rebuild from scratch (greedy, …)", "assignments_changed": 15, "employees_affected": 16, "uncovered": 0},
    "infeasibility_reasons": [],
    "unresolved": [{ /* per shift nobody can legally cover */
      "shift_id", "assignment", "why_open", "summary",
      "funnel": [{"stage": "skill|certification|availability|overlap|rest|hours", "remaining": 3, "eliminated": [{"name", "detail"}]}],
      "bottleneck": "overlap", "blocking": [{"stage", "eliminated", "near_misses": [{"name", "detail"}]}],
      "resolutions": [{"action", "detail", "kind": "operational|manual_override"}]
    }],
    "hard_constraints": [{"id", "label", "detail"}], "soft_objectives": [{"id", "label", "weight", "detail"}]
  },
  "problem": {"items": [{"kind", "title", "detail", "hard_constraint", "shift_ids"}], "affected_shifts": [...]},
  "comparison": {"headline", "points[]", "best_by": {"impact_score": ["A"], …}},
  "explanations": {"A": {"headline", "points[]", "why_not_others[]", "source": "llm|template", "grounding_warnings[]"}},
  "policy": {"mode", "constraints[] (with source + verbatim quote)", "conflicts[]", "warnings[]"},
  "relaxation": {"change", "message"} /* when PARTIAL: what would make it complete */
}
```

`reason_code` ∈ `REST_PERIOD_VIOLATION, SHIFT_OVERLAP, MISSING_SKILL, MISSING_CERTIFICATION, WOULD_UNCOVER_SHIFT, SCHEDULE_CONFLICT, UNAVAILABLE, WOULD_CREATE_OVERTIME, WOULD_EXCEED_MAX_HOURS, HIGHER_IMPACT, EXCLUDED_BY_MANAGER, LOCKED_BY_MANAGER, MANAGER_FEEDBACK`.

## Policies, versions, audit, analytics

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/policies` | M | documents, extracted constraints (with quotes), conflicts, unsupported clauses |
| GET | `/policies/search?q=` | any | `{status: found|no_applicable_policy, message, hits[{citation, text, confidence}]}` |
| POST | `/policies` | A | multipart `file` (.md/.txt) → indexed |
| GET | `/versions` · `/versions/{id}` | M | published schedule versions with changes + metrics |
| GET | `/audit` | M | event log (newest first) |
| GET | `/analytics` | M | disruptions, success rate, avg impact, changes avoided vs rebuild, overtime avoided, stability, trends, reasons |

## Employee

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/employees/{id}/schedule` | E | `{employee, schedule[], notifications[], requests[]}` |
| GET | `/employees/{id}/notifications` | E | |
| POST | `/notifications/{id}/acknowledge` | E | |
| POST | `/employees/{id}/availability` | E | `{date, start?, end?, reason, kind: unavailable|time_off|shift_swap|preference}` → request (`pending`). Lifecycle: `pending → approved → completed`, or `rejected` / `needs_review` |

## Voice

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/voice/alert` | M | `{text, audio?}`: spoken summary of the newest disruption, or the ops status |
| GET | `/voice/status` | any | `{gemini, model, server_tts}` |
| POST | `/voice` | M | `{utterance, speak?}` → `{intent, text, navigate?, action?, transcript, understood_by}`. Rules first; Gemini text understanding when rules don't match and a key is set |
| POST | `/voice/audio` | M | multipart `audio` (webm/ogg/wav/mp4…, ≤ 15 MB) → Gemini transcript + intent → same reply. 503 with a readable message if Gemini isn't configured or fails |

Voice intents: `today_schedule, disruptions, unresolved, why_reassigned, latest_changes, affected_employees, recommend, alternatives, why_not, requests, approve, reject, status`. `navigate` tells the UI which screen to open. Voice approval refuses repairs with an uncovered shift.
| POST | `/voice/tts` | any | `{text}` → `{text, audio?}` (server TTS when `ELEVENLABS_API_KEY` is set) |

`GET /health` (no prefix) reports the solver, LLM provider and auth mode.
