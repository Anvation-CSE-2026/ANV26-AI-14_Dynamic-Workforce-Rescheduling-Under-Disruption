# ResQWork Policy RAG — Design (Round 2)

Owner: Member 2. Code: `backend/rag/`. Policies: one handbook per industry in `shared/policies/<domain>/` (loaded per organization); the original support-ops examples used by the RAG tests are in `shared/policies/examples-support-ops/`.

> LLM understands. **RAG retrieves.** Constraint engine structures. CP-SAT decides.
> Raw policy text never reaches the optimizer. Only validated, source-tracked `PolicyConstraint`s do.

## 1. Pipeline

```
policy .md/.txt ─► documents.py ─► chunker.py ─► store.py ─────────────► retriever.py
 (front matter:     PolicyDocument   section-aware   vectors (embeddings.py)   hybrid score +
  policy_id, version)                chunks §3.1     + BM25 stats              confidence
                                                                                   │
           scheduling topics (hours, rest, overtime, staffing, skills, ...) ──────►│ top-k per topic
           + manager request + roles + assignments involved                        │
                                                                                   ▼
                                   policy_parser.py (LLM, prompt policy_translation@2.0.0)
                                   ├─ chunk_id must be one we sent
                                   ├─ quote must appear verbatim in that chunk   ← no fabricated policy
                                   ├─ constraints.validate_constraint: type, value, unit, range
                                   ├─ rule_extractor re-reads the quote: agree → verified,
                                   │  disagree → strictest value + interpretation_mismatch conflict
                                   └─ rules the model missed are added from rule_extractor
                                                                                   ▼
                                   constraints.resolve_conflicts ─► PolicyBundle
                                     • optimizer_config  → CP-SAT
                                     • citations()       → explanations, employee notices
                                     • conflicts / warnings / unsupported → manager UI
                                     • topics: found | "no applicable policy found"
```

## 2. Components

| File | Role |
|---|---|
| `documents.py` | Load `.md`/`.txt` with front matter (`policy_id`, `title`, `version`, `effective_date`, any extra keys); content hash |
| `chunker.py` | Splits on headings and numbered sections, so `§3.1` stays one citable chunk. Long sections split on sentences. Keeps `heading_path` for context |
| `text.py` | Tokenizer with workforce synonyms (OT→overtime, break→rest, agents→employee, "no more than"→max, ...) and light stemming |
| `embeddings.py` | `HashingEmbedder` (default; local, deterministic, no key) and `VoyageEmbedder` (hosted; `RESQWORK_EMBEDDER=voyage`) |
| `store.py` | Documents, chunks, vectors and BM25 statistics. A new version of a `policy_id` replaces the old one. JSON persistence. Same interface a pgvector store would implement |
| `retriever.py` | Hybrid ranking and calibrated confidence. Below the threshold returns `"no applicable policy found"` |
| `constraints.py` | Constraint vocabulary, validation, strictness ordering, conflict resolution, optimizer config |
| `rule_extractor.py` | Deterministic patterns: verification and no-LLM fallback |
| `policy_parser.py` | LLM translation with all the checks above; cached per chunk text × prompt version × model |
| `service.py` | `PolicyService`: `ingest_*`, `lookup(question)`, `build_bundle(...)` |

## 3. Retrieval confidence

```
confidence = 0.65 × idf-weighted share of query terms present in the chunk
           + 0.35 × cosine(query, chunk)
rank       = 0.5 × BM25 (normalized per query) + 0.5 × confidence
```

Coverage is absolute, so confidence is comparable across queries. "How much rest between shifts?" scores about 0.8 on Working Time Policy §3.1, while "What's the dress code?" scores below 0.35 and returns `no applicable policy found` rather than the least-bad passage. Threshold: `PolicyService(min_confidence=0.35)`.

Every hit carries `policy_id`, `document`, `section`, `chunk_id`, `confidence` and `matched_terms`. Every translated constraint carries `retrieval_confidence`, `interpretation_confidence` (0.95 verified by rules, 0.75 not checkable, 0.6 rules-only, 0.4 mismatch), `interpretation` (one sentence) and the verbatim `quote`.

## 4. Constraint vocabulary

| `constraint_type` | value | stricter | example source |
|---|---|---|---|
| `max_daily_hours` | hours 1–24 | lower | "No employee may be scheduled for more than 9 hours in a working day" |
| `max_weekly_hours` | hours 1–168 | lower | "must not work more than 40 hours in a calendar week" |
| `minimum_rest` | hours 0–48 | higher | "at least 11 hours of rest between …" |
| `max_overtime_weekly` | hours 0–80 | lower | "Overtime is capped at 8 hours per employee per week" |
| `overtime_allowed` | bool | false wins | "Overtime is not permitted …" |
| `overtime_requires_approval` | bool | true wins | "All overtime requires prior approval …" |
| `max_consecutive_days` | days 1–14 | lower | "No employee may work more than 6 consecutive days" |
| `max_weekends_per_month` | 0–5 | lower | "should not be scheduled for more than 2 weekends per month" |
| `min_staffing` | people 0–1000 | higher | "The L2 Support queue must have at least 3 agents on shift …" |
| `required_skill` | text | (union) | "Only agents certified in Tier-2 troubleshooting may cover …" |
| `max_schedule_changes_per_month` | 0–31 | lower | "should not be changed more than 3 times in a calendar month" |
| `respect_employee_preferences` | bool | true wins | "preferences should be respected where possible" |

Severity is `hard` for mandatory language and `soft` for "should / where possible / preferably". When unclear, the rule extractor defaults to hard: misreading a soft rule as hard only costs flexibility, while the reverse could put someone over a legal limit.

Anything else is reported in `bundle.unsupported` (e.g. "notify agents 12 hours before a change", "offer overtime fairly by rotation") and shown as **Not enforced** in the UI.

The spec's example output, `{"constraint_type": "minimum_rest", "value": 11, "unit": "hours", "severity": "hard", "source": "policy_001"}`, is a `PolicyConstraint` whose `source` is the full object `{policy_id, document, section, chunk_id, quote}`.

## 5. Conflicts

| Kind | Example in the demo policies | Resolution |
|---|---|---|
| `different_values` (same type and scope) | two documents with 40h and 38h for everyone | strictest applied, flagged |
| `scoped_looser_than_global` | Ops §3: L2 agents up to **45h**/week vs HR §2.2: everyone **40h** | both enforced, so 40 binds; flagged *"Confirm which policy should win"* |
| `interpretation_mismatch` | model reads 10h rest, rule check reads 11h from the same quote | 11 applied, confidence 0.4, flagged |
| hard vs soft for the same type and scope | hard wins | no conflict |
| identical values from several documents | merged | no conflict |
| text rules with no ordering (none in vocabulary today) | — | `needs_review`, not applied |

The engine never silently picks a looser value, and every resolution is visible in `bundle.conflicts` and `bundle.warnings()`.

## 6. Optimizer config (what Member 4 consumes)

```json
{
  "hard": {"global": {"max_daily_hours": 9, "max_weekly_hours": 40, "minimum_rest": 11, "max_consecutive_days": 6,
                      "max_overtime_weekly": 8, "overtime_requires_approval": true},
           "by_role": {"L2 Support": {"max_weekly_hours": 45}},
           "by_assignment": {"SUPPORT_L2": {"min_staffing": 3}, "KANNADA_DESK": {"min_staffing": 1}},
           "by_team": {}},
  "soft": {"global": {"max_weekends_per_month": 2, "max_schedule_changes_per_month": 3,
                      "respect_employee_preferences": true}, "by_role": {}, "by_assignment": {}, "by_team": {}},
  "required_skills": {"global": [], "by_role": {}, "by_team": {},
                      "by_assignment": {"SUPPORT_L2": ["Tier-2 troubleshooting"], "KANNADA_DESK": ["Kannada"]}}
}
```

Apply global and scoped limits together: an L2 agent is bound by both 40 (global) and 45 (role), so 40 binds. The conflict exists so a human can change the policy, not so the optimizer can pick one. What-if `override_policy` values replace entries in `hard.global` for that scenario only.

## 7. Retrieval vs. exhaustive compilation

`build_bundle()` retrieves top passages for each scheduling topic (hours, rest, overtime, consecutive days, weekends, staffing, skills, schedule changes, preferences, fairness), plus the manager's request and every role/assignment involved. That is what makes the system scale to large handbooks. For small handbooks, or a nightly "compile all policies" job, `build_bundle(exhaustive=True)` translates every chunk, so no rule can be missed by retrieval. Translation is cached per chunk, so repeated runs make no model calls.

## 8. No-LLM mode

With no provider, `rule_extractor` alone produces constraints (always global, confidence 0.6). In the demo policies it recovers 9h/day, 40h/week, 11h rest, 6 days, 8h overtime and approval. It can't see that "45h" applies only to L2, so it reports a conflict and applies 40. That is conservative and correct.

## 9. Production path

- Swap `PolicyStore` for pgvector (same `add_document` / `chunks` / `vectors` interface) and `HashingEmbedder` for Voyage.
- Store `PolicyBundle` snapshots with each schedule version (`constraint_id`s plus `content_sha256` of each document) for audit.
- PDF/DOCX ingestion: convert to Markdown first; keep the original file hash in document metadata.
