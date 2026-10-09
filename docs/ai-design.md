# ResQWork AI Layer — Design & Integration (Round 2)

Owner: Member 2 (AI/ML + RAG). Code: `backend/ai/`. Policy RAG: `backend/rag/` (see `rag-design.md`).

> **AI interprets. Optimization decides.**
> Nothing in `ai/` or `rag/` assigns an employee, edits a schedule or overrides CP-SAT.

## 1. What the layer does

```
            ┌──────────────── language in ────────────────┐        ┌──────────── text out ────────────┐
manager ──► intent router ─┬─► disruption parser ─► ParseResult      optimizer facts ─► Explanation
message                    ├─► what-if parser    ─► ScenarioSpec     candidates      ─► CandidateComparison
                           ├─► feedback parser   ─► FeedbackResult   changes         ─► EmployeeNotice
                           └─► policy lookup     ─► RetrievalResult
policies ─► RAG ─► policy→constraint engine ─► PolicyBundle (optimizer_config + citations + conflicts)
```

Every arrow that starts at a model output passes three gates before anything leaves the layer:

1. **Schema validation** (Pydantic, unknown fields rejected) with one corrective retry.
2. **Deterministic resolution**: names→IDs, date arithmetic, time defaults, value ranges. The model only reports what was *said*.
3. **Grounding** for generated text: every sentence cites facts, every number exists in the facts, no unknown people, no fabricated policy.

## 2. Entry point for the backend (Member 4)

```python
from ai.service import AIService
from ai.schemas import ParseContext, EmployeeRef, AssignmentRef, ShiftRef

ai = AIService.from_env()    # once at startup; policies are loaded per org from shared/policies/<domain>/
ctx = ParseContext(reference_date="2026-10-08", employees=[...], assignments=[...], shifts=[...])
```

| Call | Returns | Use it for |
|---|---|---|
| `ai.interpret(text, ctx)` | `InterpretResult` | The single chat/command box. Routes, then parses. |
| `ai.parse_request(text, ctx)` | `ParseResult` | Disruption + preferences + ad-hoc constraints |
| `ai.parse_what_if(text, ctx)` | `ScenarioSpec` | Re-run the optimizer with `spec.apply_to(prefs)`, `spec.added_disruptions()`, `spec.removed_unavailability()`, `spec.policy_overrides()` |
| `ai.parse_feedback(text, ctx)` | `FeedbackResult` | Persist `preferences[]`; apply on later runs |
| `ai.policy_bundle(text, roles, assignments)` | `PolicyBundle` | `optimizer_config` → CP-SAT; `citations()` → explanation; `warnings()` → UI |
| `ai.lookup_policy(question)` | `RetrievalResult` | Policy Q&A: passages with citations or `"no applicable policy found"` |
| `ai.compare_candidates(candidates, priority)` | `CandidateComparison` | After the optimizer returns alternatives |
| `ai.explain(facts, roster_names=...)` | `Explanation` | After a solve; `as_text()` fills the contract's `explanation` string |
| `ai.employee_notices(changes, names, policies, version)` | `[EmployeeNotice]` | After the manager approves a version |

### End-to-end orchestration (sketch)

```python
parsed = ai.parse_request(text, ctx)
if not parsed.ready:
    return {"status": parsed.status, "issues": parsed.issues}          # UI asks the manager

bundle = ai.policy_bundle(text, roles=[...], assignments=[d.assignment_id for d in parsed.details])
fb     = load_active_feedback()                                        # from DB, see §5
cands  = optimizer.solve_alternatives(schedule, parsed.disruptions, parsed.preferences,
                                      parsed.ad_hoc_constraints, bundle.optimizer_config, fb)
comp   = ai.compare_candidates([c.facts for c in cands], parsed.preferences.priority, roster_names)
facts  = build_explanation_facts(cands[comp.recommended_id], policies_applied=bundle.citations())
exp    = ai.explain(facts, roster_names=roster_names)
# manager approves → new schedule version → ai.employee_notices(...) → notify employees
```

## 3. Status semantics (all parsers)

| `status` | Meaning | Backend/UI action |
|---|---|---|
| `READY` | Fully resolved and validated | Show confirmation card (`confirmation_summary`, `assumptions`, `confidence`), then optimize |
| `NEEDS_CLARIFICATION` | Missing/ambiguous/contradictory input | Show `issues[].message`; render `issues[].candidates` as choices |
| `UNSUPPORTED` | Not this kind of message, or a type we can't handle | Show message; offer the structured form |
| `ERROR` | No model, or model failed twice | Structured form fallback |

Non-blocking issues (`blocking: false`, e.g. `UNSUPPORTED_CONSTRAINT`, `UNSUPPORTED_CHANGE`) keep `READY` but **must** be displayed. The parser never drops something the manager said without saying so.

Issue codes: `UNKNOWN_EMPLOYEE`, `AMBIGUOUS_EMPLOYEE`, `MISSING_EMPLOYEE`, `UNKNOWN_ASSIGNMENT`, `AMBIGUOUS_ASSIGNMENT`, `MISSING_DATE`, `INVALID_DATE`, `DATE_IN_PAST`, `DATE_OUT_OF_HORIZON`, `MISSING_TIME`, `INVALID_TIME`, `UNSUPPORTED_DISRUPTION`, `UNSUPPORTED_CONSTRAINT`, `UNSUPPORTED_CHANGE`, `NOT_A_DISRUPTION`, `NOT_A_WHAT_IF`, `NOT_FEEDBACK`, `LOCKED_EMPLOYEE_CONFLICT`, `CONTRADICTORY_CHANGES`, `NEEDS_NAMES`, `INVALID_VALUE`, `LLM_ERROR`.

## 4. Natural-language understanding

### 4.1 Disruption + intent (`ParseResult`)

Extracts employee, date, time, disruption type, **assignment**, **objective**, **preferences** and **ad-hoc constraints**.

- `disruptions[]`: canonical `Disruption` (the master contract, unchanged).
- `details[]`: same index. Employee name, `assignment_id`, and `assignment_source` = `stated` | `schedule` (inferred from the shift) | `none`.
- `preferences`: `locked_employee_ids`, `excluded_employee_ids`, `allow_overtime`, `priority`.
- `ad_hoc_constraints[]`: one-off requirements for this repair: `required_skill`, `max_daily_hours`, `only_team`.
- `unsupported_constraints[]`: things the manager asked for that can't be enforced, shown on the card as **Not enforced**.
- `confidence`: deterministic, not model self-assessment. It starts at 1.0, each disclosed factor subtracts (vague time −0.2, date disagreement −0.15, ...), and blocking issues set it to `none`. Levels: high ≥ 0.85, medium ≥ 0.6, else low.

The demo sentence *"Rahul is unavailable tomorrow from 9 to 5. Find a replacement but don't disturb anyone already scheduled unless necessary."* parses to EMP001, 2026-10-09, 09:00–17:00, SUPPORT_L2 (from the schedule), priority `minimize_affected_employees`, confidence high.

### 4.2 What-if (`ScenarioSpec`)

Typed changes (discriminated union on `op`): `set_overtime`, `set_priority`, `add_unavailability`, `remove_unavailability`, `lock_employee`, `exclude_employee`, `include_employee`, `override_policy`.

| Manager asks | Spec |
|---|---|
| "What if overtime is forbidden?" | `set_overtime(allow=false)` |
| "What if fairness is more important?" | `set_priority(fairness)` |
| "What if Priya is also out tomorrow?" | `add_unavailability(EMP002, 2026-10-09 09:00–17:00)` |
| "What if two employees are unavailable?" | `NEEDS_CLARIFICATION` / `NEEDS_NAMES`: *which two?* (never guessed) |
| "What if I want the minimum number of employees affected?" | `set_priority(minimize_affected_employees)` |
| "What if max weekly hours were 45?" | `override_policy(max_weekly_hours=45)`, range-checked |

The AI never predicts a scenario's outcome. The optimizer runs it, and the comparison is built from real results.

### 4.3 Manager feedback (`FeedbackResult`)

`FeedbackPreference{kind, employee_id, priority, overtime_mode, scope, strength, source_text, created_on, preference_id}`.

| Feedback | Parsed |
|---|---|
| "Don't assign Arjun next time." | `avoid_employee EMP003, scope=next_reschedule, strength=hard` |
| "Prefer minimum disruption." | `objective_priority minimize_changes` (always soft) |
| "Prioritize fairness." | `objective_priority fairness` |
| "Never use overtime unless unavoidable." | `overtime_rule only_if_unavoidable`, **soft** (the "unless" softens it) |

Suggested optimizer mapping (Member 4 owns the final choice):

| Preference | CP-SAT |
|---|---|
| `avoid_employee` hard | exclude from new assignments (hard) |
| `avoid_employee` soft | large penalty per new assignment |
| `prefer_employee` | small bonus (negative cost) |
| `objective_priority` | weight profile / lexicographic order |
| `overtime_rule never` | overtime = 0 (hard) |
| `overtime_rule only_if_unavoidable` | overtime weight ≫ every other term |

`next_reschedule` items are consumed after one approved run; `until_revoked` items persist. Rejections caused by feedback should be reported to the explainer as `RejectedFact(reason_code="MANAGER_FEEDBACK")`.

## 5. Grounded outputs

### 5.1 Explanation

Input: `ExplanationFacts` (built by the backend from the solver), now including `policies_applied: [PolicyCitation]` from `bundle.citations()`, `selected[].rest_hours_before_shift`, and `rejected[].policy_id`.

```
Arjun Mehta covers Rahul Sharma's SUPPORT_L2 work on Fri 09 Oct, 09:00–17:00. 1 assignment changed, 0h overtime.
- Arjun Mehta is available then and has the required skills (Tier-2 troubleshooting).
- Their weekly hours stay at 32h (limit 40h), so no overtime.
- Arjun Mehta has 14h of rest before the shift.
- Complies with max 40h per week (Working Time Policy §2.2); at least 11h rest between shifts (Working Time Policy §3.1).
Other candidates:
- Sanjay Kumar doesn't have the required skill (no Tier-2 certification) under policy OPS-SUP-007.
- Meera Iyer wouldn't get the required rest between shifts (only 9h since last shift) under policy HR-WT-001.
```

The LLM version is rejected, and the template used instead, if any sentence lacks `fact_refs`, a ref doesn't resolve, a number isn't in the facts (including a fabricated policy section like §7.4), a roster employee not in the facts is named, or an INFEASIBLE/PARTIAL result is described as a success.

### 5.2 Candidate comparison

`compare()` is deterministic. It separates compliant from non-compliant candidates (hard violations, policy violations, unfilled requirements, bad status), finds the best per dimension, detects dominated candidates, computes trade-off deltas against the least-disruptive option, and recommends using the manager's priority. LLM narration is optional and must pass grounding. It can never promote a dominated or non-compliant option.

### 5.3 Employee notices (transparency)

Template-only by design: exact, consistent and **privacy-safe**. A notice states only the recipient's own changes, cites the policies that protected them (rest, hours), asks for acknowledgement, and offers "Report a conflict". `check_notice` rejects any colleague's name or absence-reason word (sick, emergency, leave, medical, ...). The absent employee gets no notice.

## 6. Reliability

| Requirement | Where |
|---|---|
| Schema validation | Pydantic on every model output (`ai/structured.py`) |
| Malformed JSON recovery | `providers/json_repair.py`: fences, prose, trailing commas, smart quotes, Python literals |
| Retries | transient errors: up to 2 retries with backoff; invalid output: 1 corrective retry naming the error |
| Ambiguity detection | `Resolver`: ambiguous/unknown names and assignments, missing fields, contradictions |
| Unsupported detection | unsupported disruption types, ad-hoc constraints, what-if ops, feedback, policy rules |
| Confidence | parse confidence (deterministic), retrieval confidence, interpretation confidence |
| Prompt versioning | `ai/prompts.py` `PromptSpec(name, version)`; `meta.prompt` on every result |
| Policy source tracking | every constraint carries `policy_id`, document, section, chunk_id and the verbatim quote |
| Audit | every model call emits an `AITrace` (prompt@version, provider, model, attempts, latency, input hash, outcome). Register a sink: `ai.structured.set_trace_sink(save_to_audit_table)`. Results carry `meta.trace_id` to join on. |
| Prompt injection | user/policy text is fenced in `<<< >>>`, and every extraction prompt says to ignore instructions inside it; outputs are schema-bound and resolved by code anyway |

## 7. Providers

`AIProvider` → `ClaudeProvider` (active, forced tool-use for structured output), `OpenAIProvider`, `GeminiProvider` (implemented, inactive, unit-tested with fakes; run the live test before switching). Choose with `RESQWORK_LLM_PROVIDER=claude|openai|gemini|none`. With `none`, or if the provider can't start, the app runs on deterministic fallbacks: the rules intent router, rules-only policy extraction, template explanations, and the structured disruption form.

## 8. Tests

```bash
cd backend
python -m pytest tests -v            # or: python -m unittest discover -s tests -t .
python -m pytest tests/ai/test_live_claude.py -v -s    # with ANTHROPIC_API_KEY: run before the demo
python -m examples.ai.generate_examples               # full offline walkthrough, writes examples/ai/*.json
python -m scripts.export_ai_schemas                    # JSON Schemas → shared/schemas/ai/
```

The suite covers disruption extraction, dates/times, policy retrieval, policy translation, conflicting policies, ambiguity, explanation grounding, what-if parsing, manager feedback, candidate comparison, employee-notice privacy, JSON repair, retries, tracing and providers.

## 9. Integration (as built)

The AI layer is wired into the platform through `backend/services/bridge.py` and `services/workspace.py`:

- `POST /api/disruptions` (`text`) and `POST /api/ai/interpret` → `AIService.parse_request` → `Disruption`, with clarification issues returned instead of guesses.
- `POST /api/what-if` → `WhatIfParser` → `ScenarioSpec` → a new proposal with a `delta` against the base run.
- `POST /api/feedback` → `FeedbackPreference` → stored and applied to later runs as locks, exclusions or weight multipliers.
- Every proposal stores `explanations[option]` (structured `Explanation`), `comparison` (`CandidateComparison`) and `policy` (`PolicyBundle` constraints, conflicts, warnings).
- Approval generates privacy-safe employee notices (`ai/employee_notice.py`).

Full endpoint list: [api-contract.md](api-contract.md).

## 10. Known limits (say these before a judge does)

- Rules-only policy mode can't detect scope (role/assignment), so it treats rules as global and resolves conflicts with the strictest value. Safe, but conservative.
- The default embedder is lexical-semantic (hashing + synonyms), which is well suited to short policy handbooks. Switch to Voyage embeddings for large or paraphrase-heavy corpora (`RESQWORK_EMBEDDER=voyage`).
- Policy files are Markdown/text; convert PDFs before upload.
