# Data model

The canonical format is JSON and is defined by `backend/core/models.py`. It is exported as a JSON Schema to `shared/schemas/dataset.schema.json` (regenerate with `python -m scripts.export_dataset_schema`). Every industry uses the same shape; industry-specific details go in `skills`, `certifications`, `priority` and the free-form `attributes`.

## Dataset

| Field | Required | Notes |
|---|---|---|
| `organization` | ✓ | `{id, name, domain, location?, timezone, size?}`; `domain` ∈ healthcare, manufacturing, education, technology, logistics |
| `employees` | ✓ | see below |
| `shifts` | ✓ | see below |
| `existing_schedule` | ✓ | `[{shift_id, employee_id}]`: the schedule being repaired |
| `reference_date`, `reference_time` | | "today" and "now". Shifts that already started are frozen and never changed |
| `departments` | | `[{id, name, kind?}]` |
| `skills` | | catalogue (informational) |
| `availability` | | `[{employee_id, date, start?, end?, kind: unavailable|leave|preferred_off, reason?}]` |
| `disruptions` | | demo "simulate" presets: `[{id, employee_id, date, start?, end?, reason?, severity, label}]` |
| `constraints` | | org defaults: `min_rest_hours` (11), `max_daily_hours`, `max_weekly_hours`, `allow_overtime` (true), `max_overtime_hours_per_week` (12) |
| `optimization` | | objective weights (see [optimization.md](optimization.md)) |

### Employee

`id`, `name`, `role` (required); `department`, `skills[]`, `certifications[]`, `contracted_weekly_hours` (40), `max_weekly_hours` (48), `max_daily_hours` (12), `preferences {avoid_weekends, preferred_shift_types[], avoid_shift_types[]}`, `history {disruptions_absorbed_30d, schedule_changes_30d, overtime_hours_30d}`, `attributes{}`.

`history` feeds the fairness objective. ResQWork updates it on every approval, so the same people are not asked again and again.

### Shift

`id`, `date` (YYYY-MM-DD), `start`, `end` (HH:MM), `assignment` (required); `department`, `shift_type`, `required_skills[]`, `required_certifications[]`, `priority` (critical|high|normal), `location`, `attributes{}`. Overnight shifts (`end` < `start`) end on the next day.

Industry examples of the same fields:

| | `assignment` | `required_skills` / `certifications` | `attributes` |
|---|---|---|---|
| Healthcare | ICU Day | RN, ICU Care / ACLS | ward, patient ratio |
| Manufacturing | Line 1 · CNC Machining (Shift A) | CNC Operation / Safety Level 2 | machine |
| Education | Grade 9 Mathematics, Period 2 | Mathematics | room, grade |
| Technology | Payments API sprint / On-call | Backend, Go / On-call trained | project, release |
| Logistics | Route R-21 · Hosur fuel run | Heavy Vehicle / Hazmat licence | vehicle, region |

## Uploading

- **JSON:** the canonical format above.
- **CSV:** one row per shift (`employee_id` empty means an open shift), plus an optional employees CSV. Multi-value cells use `;`. Samples are in `shared/samples/`.

  ```
  schedule.csv : shift_id,date,start,end,assignment,department,required_skills,required_certifications,priority,employee_id
  employees.csv: id,name,role,department,skills,certifications,max_daily_hours,contracted_weekly_hours,max_weekly_hours
  ```
- **Manual entry:** a small form in onboarding produces the same JSON.

## Validation

`core/validation.py` checks every record and reports problems instead of silently dropping them. Bad records are rejected individually and the rest still load.

| Category | Examples |
|---|---|
| `missing_field` | employee without `name`, shift without `date` |
| `invalid_record` | wrong types, bad dates, invalid constraint values |
| `duplicate` | repeated employee id, shift id, or double-booked assignment |
| `invalid_shift` | `25:00`, malformed date or time |
| `unknown_reference` | assignment to a shift or employee that doesn't exist |
| `skill_mismatch` | assigned person lacks a required skill or certification (warning: kept and flagged) |
| `constraint_conflict` | existing schedule already breaks rest / hours rules (warning: kept and flagged, not "repaired" behind your back) |
| `coverage` | open shifts with nobody assigned |

Problems already present in the uploaded schedule are *grandfathered*. The solver won't break more rules, but it also won't rewrite unrelated parts of your schedule to fix old issues.
