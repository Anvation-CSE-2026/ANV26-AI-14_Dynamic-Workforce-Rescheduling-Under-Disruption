# Optimization, impact and fairness

## Decision variables

For each **slot to fill** (an assignment vacated by the disruption, or one freed because its holder moved to cover another shift), the solver picks one eligible employee or leaves it uncovered. Every slot that starts after "now" can change, but each change is penalized, so the solver only moves people when that's cheaper than the alternative. This is what makes chains possible: Carlos covers ICU, and Marcus covers Carlos's ED shift.

## Hard rules (`core/rules.py`)

These are checked identically by CP-SAT, the exact search and the post-solve validator:

- availability (disruptions, leave, unavailability windows)
- no overlapping shifts
- minimum rest between shifts (org default 11h; policy can raise it)
- maximum daily hours, maximum weekly hours
- overtime: allowed or not, and a weekly overtime cap
- required skills and certifications
- shifts that already started are frozen
- manager locks and exclusions (from feedback or what-if)

Policies from RAG can only tighten these. If two documents disagree, the stricter value wins and the conflict is reported.

## Objective (minimize)

```
cost = 100 000 · uncovered shifts
     +   1 000 · assignments changed vs the existing schedule
     +     400 · employees affected
     +     150 · overtime hours added
     +      60 · fairness burden of the people given new work
     +      40 · preference violations
```

Weights are per dataset (`optimization.weights`). The fairness burden of giving extra work to a person is `2 + 2·disruptions absorbed (30d) + schedule changes (30d) + overtime (30d)/4 + current scheduled hours/12`.

### Options A–D

Each option re-weights the same objective:

| Option | Strategy | Multipliers |
|---|---|---|
| A · Recommended | `recommended` | none |
| B · Lowest employee impact | `min_employees` | employees affected ×10, changes ×0.6 |
| C · Lowest overtime | `min_overtime` | overtime ×25 |
| D · Highest fairness | `max_fairness` | fairness ×20, changes ×0.6, overtime ×5 |

If two strategies produce the same repair, it's shown once and lists every goal it is best for. A distinct alternative is then searched with a no-good cut. An alternative is shown only if it is better than the recommendation on at least one measure, so a demo with one obvious answer shows one option and doesn't pad the list. Labels are assigned A, B, C… in display order, and the title states each option's measured advantage.

## Solvers

- **OR-Tools CP-SAT** (`engine/solver_cpsat.py`) is used when `ortools` is installed. Boolean x[slot, employee], with linear rest, overlap and hours constraints and the weighted objective.
- **Exact bounded search** (`engine/solver_search.py`) runs otherwise: depth-first search over eligible candidates with incremental validation and branch-and-bound on cost. It is exact for demo-sized horizons (tens of slots) and solves in milliseconds to a few hundred milliseconds.
- **Baseline** (`engine/baseline.py`): a greedy from-scratch rebuild that ignores the existing schedule, shown for comparison ("repairing changes 1; rebuilding would change 15").

Whichever solver runs, `full_check` re-validates every option and drops any that violate a rule.

## Why not X?

For each other plausible employee, the answer is one of:
- a **hard rule** (REST_PERIOD_VIOLATION, SHIFT_OVERLAP, MISSING_SKILL, UNAVAILABLE, WOULD_EXCEED_MAX_HOURS…), with the computed numbers ("only 0h rest after ICU Night (minimum 11h)"); or
- a **counterfactual**: re-solve with X forced in and report the extra cost ("2 changes vs 1; 2 people affected vs 1", "12h overtime vs 0").

## Conflicts already in the schedule

`engine/conflicts.py` finds hard-rule violations in the *current* schedule (double bookings, rest violations, unqualified or unavailable assignees, daily/weekly over-limit, open shifts) and turns each into repair input:

- **release**: the shift whose assignee must come off it. For an overlap or rest pair this is the lower-priority shift, then the later one. Hours violations are only reported if they remain after those releases, so one double booking isn't reported twice.
- **cover**: an open shift that must be filled (mandatory coverage).

The engine treats released shifts like vacated ones (`RunSettings.release_shift_ids`, `cover_shift_ids`), finds valid cover under the same hard rules, and shows the result in the Repair Centre for approval. People taken off a shift are notified too.

## No feasible repair: unresolved-constraint analysis

If a shift can't be covered without breaking a hard rule, the result is `PARTIAL` (other shifts covered) or `INFEASIBLE` (nothing). Nobody is placed illegally, and the requirement is never quietly changed. `engine/diagnosis.py` explains each uncovered shift:

1. **Funnel.** Every employee is checked in order: required skill → required certification → availability → overlapping shift → rest → hours. The count of survivors after each step is shown, with each eliminated person and the reason.
2. **Bottleneck.** The step where the count reaches zero, stated as one sentence, e.g. *"Required certification Safety Level 2 cannot be satisfied: none of the 3 people with the required skill holds it"* or *"…the only qualified, available person is already working an overlapping shift (Bala Krishnan)"*.
3. **Ranked blocking constraints.** Each constraint, the number of people it blocks, and its *near misses* (people blocked by that constraint alone). Constraints with more near misses rank higher, because relaxing them would open the most options.
4. **Possible resolutions.** Operational ones (ask a near miss about availability, free up an overlapping person, change the timing, add a qualified person, split the shift) and *manual overrides* (relax a certification or skill, approve extra hours). Overrides are labelled as needing a manager decision and are never applied automatically.

Publishing a partial repair needs an explicit override with a reason, which goes to the audit log. The voice assistant refuses to do it.

## Scheduling impact (0–100, lower is better)

```
points = 1.0 × assignments changed
       + 0.5 × employees affected beyond the first
       + overtime hours added / 8
       + 3.0 × shifts left uncovered
impact % = min(100, 100 × points / shifts in the repair horizon)
LOW < 15 ≤ MEDIUM < 35 ≤ HIGH
```

The UI shows the formula next to the score. *Preservation rate* is the share of horizon shifts left untouched.

## Fairness (0–100, higher is better)

```
workload balance      = 100 × (1 − coefficient of variation of weekly hours)
overtime distribution = 100 × (1 − Gini of overtime hours)   (100 if nobody has overtime)
change concentration  = 100 − 15 × mean recent disruptions (30d) of the people given new work
preference respect    = 100 × (1 − preference violations / new assignments)
fairness score        = 0.35·workload + 0.25·overtime + 0.25·concentration + 0.15·preferences
```

All formulas are in `backend/analytics/metrics.py`, and none of them use hidden constants.
