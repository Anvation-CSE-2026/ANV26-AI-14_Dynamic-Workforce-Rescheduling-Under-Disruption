# ResQWork: status and remaining plan (platform spec, 66 sections)

> **Update (2026-10-09, later):** most of the frontend screens in section 2 are now built and were checked in a browser against the running backend:
> Conflicts (AI assistant), Repair Center (View / Hide / Show hidden / Mark completed), the What-if lab, Workforce requests and volunteers, Employees (directory, add, edit, deactivate, reset password, bulk import and schedule import with one-time password download), Constraint Center, Rewards & Recognition (admin), Notifications, Admin requests, Profile, forced password change, the admin overview on the command center, the employee action center (volunteer / respond / critical alerts, rewards, workload, profile), 24-hour time inputs, landing additions (100-person demo button, the 7-step flow, the fairness card), and Admin-only role wording. The `any` types in the frontend are gone.
> **Still open:** a mobile bottom tab bar for employees (the portal is already responsive), extra analytics charts (item 14), and a real `npm run build` and `tsc` run with @types/react on your machine.

Last updated 2026-10-09. Everything that worked before still works: the website, the demo logins and the 213 earlier tests, which are now part of the 259-test suite. The **backend for the whole spec is built and tested**. What's left is mostly **frontend screens** that call endpoints which already exist and are tested.

## 1. Done and verified (backend, `python -m unittest discover -s tests -t .` → 259 OK)

| Spec § | What exists | Where |
|---|---|---|
| 4 Roles | Only Admin / Operations and Employee are product roles. Legacy manager logins map to admin. The server enforces roles. | `services/auth.py`, `app/api/routes.py` (`manager`, `employee_self`, `self_or_manager`) |
| 5 Profiles | `GET/PATCH /api/profile` (name, phone, avatar, notification prefs), sessions, logout (one session or all) | routes, `services/auth.py` |
| 6–7 Bulk import + temporary passwords | CSV/XLSX → validate → preview (valid, invalid, duplicate, existing, warnings, row numbers) → confirm. Only new employees are created. Passwords are hashed and must be changed at first login (the API blocks everything else until then). The Excel export is **one-time** (in-memory vault, 15 min). | `services/importers.py`, `core/xlsx.py`, `services/operations.py` |
| 8 Schedule import | Template, duplicates, missing employee, invalid time (AM/PM rejected), skill mismatch, hard-constraint warnings, appends a new schedule version | same |
| 9 24-hour clock | Voice text and parser hints switched to 24-hour. New `fmtWhen`/`fmtTime`/`fmtRange`/`isHHMM`. `TimeInput` component. | `services/voice.py`, `frontend/src/lib/format.ts`, `components/common/ui.tsx` |
| 10–12 Constraint engine + Constraint Center API | Data-driven catalog (C001–C011 hard, S001–S007 soft). Enable/disable actually changes what the engine enforces; core safety rules are locked. Weights; CSV/JSON import with validation; scoped `required_skill` rules really enforced; unknown categories flagged "not enforced"; test against the schedule; templates. | `services/constraint_center.py` |
| 13 CP-SAT honesty | `solver_cpsat.status()` runs a self-test solve. The engine uses CP-SAT only if that passes, and every result is labelled with the solver that produced it. `GET /api/system/solver`, `/health`. CP-SAT now also models the location and continuity soft terms. | `engine/solver_cpsat.py`, `engine/repair.py` |
| 14 Fairness | Dated contribution ledger with a rolling window (7/30/90) and decay; older work has reduced influence. The same `burden_units` feeds CP-SAT and the search. Fairness profile per person. | `analytics/fairness_engine.py`, `engine/evaluate.py` |
| 15–17 AI conflict assistant | Each item has type, severity, employee, task, shift, impact, why, constraints, recommendation with PASS checks, alternatives, confidence, policy (RAG) citation and AI wording. LLM suggestions are re-checked: ineligible people are discarded and listed. Template fallback; results cached. | `services/operations.py::conflict_assistant`, `ai/prompts.py::CONFLICT_ADVICE` |
| 18 Repair Center API | List by state (pending, approved, completed, rejected, hidden); hide and unhide (never deletes); complete | routes `/api/repair-center…` |
| 19 What-if | Structured simulations that never save: assign X, accept a volunteer, choose another option, move a shift, add one employee | `simulate()` → `POST /api/what-if/simulate` |
| 20–22 Workforce + volunteers | Staffing gaps (from `required_headcount`); eligibility funnel; ranking; workforce requests; invite volunteers, broadcast or escalate (eligible people only); volunteer ≠ assignment; admin approves; assignment completed | `services/workforce.py`, `operations.py` |
| 23 Rewards & Recognition | Rewards only after completion. Configurable rules (points, badge, approval) plus badges and achievements, and a critical-support bonus. Rewards never influence scheduling (tested). | `services/rewards.py` |
| 24–25 Notifications | L1 green (dashboard + email). L2 orange (+ WhatsApp/SMS if unacknowledged within N minutes). L3 red (all channels). Per-channel sent, delivered, opened and acknowledged; audit rows. SMTP and Twilio are used when configured; otherwise "simulated" (logged to outbox, labelled honestly). No voice. | `services/notify.py` |
| 26 Admin requests | Send to an employee, several people, a department, a role or eligible people; accept/decline/acknowledge by type; synced | `operations.py` |
| 32/35/59 Security, errors | Sessions with revocation; deactivated accounts blocked; demo login only in demo mode; anonymous demo access off by default; JSON 404 for unknown `/api/*` (never HTML); generic 500 handler with no stack traces; validation errors as JSON | `app/main.py`, routes |
| 35 API client | Content-type-aware parsing, empty, HTML and malformed bodies, timeouts, network errors, 401 and password-change events, downloads | `frontend/src/api/client.ts` |
| C TypeScript | `src/vite-env.d.ts` (typed `import.meta.env`), `strict: true`, `(import.meta as any)` removed. A strict offline type-check passes. | `frontend/` |
| 37 Audit | `previous`, `new` and `reason` on every new action | `workspace.audit()` |
| 40 Demo data | 100-person flagship hospital. Meera beats Arjun on fairness; the surge team has a gap of 2. Logins: `admin@flagship.demo`, `meera@`, `arjun@`, `kavya@`, `rohan@flagship.demo` / `demo1234` | `scripts/build_flagship.py`, `shared/scenarios/flagship-hospital-100.json` |
| 41–48 Tests | Hard constraints 1–10 each tested on their own, soft constraints, fairness §42, AI §43, workforce §44, rewards §45, notifications §46, imports §47, multi-user §48, sessions, 24-hour clock, flagship story | `backend/tests/services/test_spec_must_haves.py` |

## 2. Remaining work (frontend), in the order to do it

All of these call existing, tested endpoints, and the client methods already exist in `src/api/client.ts` with types in `src/api/types.ts`. Shared building blocks are ready in `src/components/common/ui.tsx`: `PageHeader`, `Field`, `TimeInput`, `SeverityPill`, `Chip`, `CheckRow`, `Avatar`, `FileDrop`, `Notice`, `MiniBar`. New icons are in `icons.tsx`.

1. **App shell (`App.tsx`, `Shell.tsx`)**
   - Subscribe to `onAuthEvent`: on 401, sign out; on `password_change_required`, show a forced Change Password screen (`api.changePassword`). Also show that screen after login when `me().must_change_password` is true.
   - Navigation groups: Operations (Command center, Conflicts, Repair center, Workforce, Requests), Data (Schedule, Employees, Constraint center, Policies), Insights (Rewards & Recognition, Notifications, Analytics, Schedules & audit).
   - Add a Profile item and hide the Voice button. Keep `VoiceAgent` in the code but don't render it (spec §56).
   - Label the role "Admin / Operations".
2. **Conflicts screen**: `api.conflictAssistant()`. Show one card per conflict with a severity pill, why, constraints, a recommendation with `CheckRow` PASS list, alternatives with trade-offs, confidence, the policy citation, "explained by", and any discarded AI suggestions.
   - Generate optimized repair: `api.reschedule([disruption_id])` or `api.resolveConflicts([conflict_id])`.
   - Request workforce: prefill the Workforce form from `gap`.
3. **Repair Center list**: `api.repairCenter(showHidden)`.
   - Tabs for Pending, Approved, Completed and Rejected, plus a "Show hidden" toggle. Show counts, including active and critical disruptions.
   - Row actions:
     - View: open the existing `Repair` screen with that id.
     - Hide or Unhide: `hideRepair`/`unhideRepair`.
     - Mark completed: `completeRepair`.
   - In `Repair.tsx`, add a "What-if" panel with buttons calling `api.simulate`: assign a person (pick from the rejected list), choose option B, move the shift (two `TimeInput`s), or add one employee. Render `Simulation`: feasible/conflicts, changes, workload before→after, fairness before→after, score. Say clearly "not saved".
4. **Workforce screen**:
   - Staffing gaps (`staffingGaps`) with a "Find employees" button.
   - A form (`WorkforceForm`, with `TimeInput` for start and end) → `findEmployees` → eligibility funnel, ranked eligible people with soft notes and fairness load, and ineligible people with the failed rule. Show `message` when there isn't enough eligible workforce.
   - Request list (`workforceRequests`) with Assign, Invite volunteers / Broadcast / Escalate, volunteer approve/decline, Mark completed, and Cancel.
5. **Requests screen**: keep employee requests. Add an Admin requests tab: a create form (type, title, message, target kind/value, severity) and a list with each recipient's status (`adminRequests`, `closeAdminRequest`).
6. **Employees screen**: a directory (`directory`) with search, status, fairness load and shift count.
   - Add employee (form → `addEmployee`): show the temporary password once and offer the Excel download (`downloadCredentials`).
   - Edit admin-controlled fields (`updateEmployee`), deactivate or reactivate (`setEmployeeStatus`), and reset password (`resetPassword` → download).
   - Bulk import: `FileDrop` → `previewEmployeeImport` → a preview table showing every row with status, errors and warnings → Confirm (`confirmEmployeeImport`) → download credentials immediately (it's one-time). Template buttons (`downloadTemplate`).
   - Schedule import, the same flow, with an "Import rows with hard-constraint warnings" checkbox.
7. **Constraint Center**: tables of hard and soft rules (`constraints`) with an enable switch (locked rules show a lock), value/weight inputs (`updateConstraint`), an Import CSV/JSON panel (preview, then apply), templates, a Test button (`testConstraints`) with per-rule results, and a solver status card (`solver`).
8. **Rewards & Recognition** (rename the Recognition nav item and screen):
   - Admin view: leaderboard, stats, pending approvals (`approveReward`), awaiting completion (`completeEligibility`), a rule editor (`saveRewardRules`) and award buttons (`giveReward`).
   - Keep the existing category awards.
9. **Notifications screen**: summary by level, the audit table (`notificationAudit`) with a channel status for each row, the escalation window setting, "Run escalation now" (`escalate`), and the provider status (simulated vs SMTP/Twilio).
10. **Employee portal (mobile-first)**: build it on `employeeHome(id)`.
    - Bottom tab bar: Home, Schedule, Requests, Rewards, Profile.
    - Home:
      - next shift card
      - today
      - an "Action needed" list: admin requests (`respondAdminRequest`), coverage opportunities (Volunteer / Not now via `respondOpportunity`) and L2/L3 notices to acknowledge
      - conflict alerts
      - workload summary
    - Rewards: points, badges, achievements, history, pending.
    - Requests form: replace `<input type="time">` with `TimeInput`.
11. **Admin dashboard**: render `dashboard.overview`: staffing gaps, workforce counts, notification status, repair counts, fairness top-loads, rewards stats and solver status.
12. **Profile screen** (both roles): `profile()`/`updateProfile()` for name, phone, avatar upload as a data URL ≤ 300 KB, and notification switches; `changePassword`; the sessions list; sign out and sign out everywhere (`logout`).
13. **Landing page**:
    - Hero: "Don't Rebuild the Schedule. Repair It Intelligently."
    - A 7-step flow: Existing schedule → Disruption → AI conflict intelligence → Constraint validation → CP-SAT → Fair repair → Admin approval.
    - A product mockup of the recommendation card (Meera vs Arjun), flagship metrics and the domain grid.
    - CTA: "Open the 100-person demo" = `login('admin@flagship.demo','demo1234')`.
    - Keep the demo-accounts table.
14. **Analytics**: add charts from the new analytics fields: conflicts detected/resolved, average repair minutes, staffing gaps, workload and fairness distribution, volunteer participation, rewards by trigger and notification levels.
15. **Cleanup**: remove the remaining `any` usages (Widgets: use `WidgetData`; `catch (e: any)` → `catch (e) { toast(errorMessage(e)) }`).
16. **Build and verify**:
    - `npm install && npm run lint && npm run build`.
    - Run the backend tests.
    - Browser walk at 1280 px, 768 px and 390 px with the flagship story. Admin: simulate → assistant → repair → what-if → approve → workforce request → volunteers. Employee rohan: volunteer. Admin: approve → complete. Then check rohan's rewards.

## 3. Not possible in this build environment (do on your machine)
- **OR-Tools**: `pip install ortools` (the start scripts try it). Then `GET /api/system/solver` should report `cp_sat: true`, and repairs will be labelled "OR-Tools CP-SAT". The CP-SAT-only tests then run instead of skipping.
- **npm / Vite build and `tsc` with the real `@types/react`**: the source was type-checked here with strict mode against minimal React typings. The pre-built `frontend/dist` is current.
- **Real email/SMS/WhatsApp**: set `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM` and `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/`TWILIO_FROM`/`TWILIO_WHATSAPP_FROM` in `backend/.env`.

## 4. Behaviour changes to know about
- Rewards are granted at **completion**, not at approval. Approval creates a "pending completion" eligibility. The admin marks a repair or assignment completed, and the employee then sees points and a badge.
- Approving a repair now writes a dated entry to the fairness ledger instead of incrementing the 30-day counters.
- Unauthenticated "anonymous demo manager" access is off. Set `RESQWORK_ANONYMOUS_DEMO=on` to restore it for local experiments.
- `manager@<industry>.demo` still signs in, as an admin. The home page lists `admin@<industry>.demo` and three employees per industry, plus the flagship accounts.
