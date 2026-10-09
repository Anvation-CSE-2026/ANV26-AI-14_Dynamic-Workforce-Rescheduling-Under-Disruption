"""The 'rebuild from scratch' baseline shown next to the repair.

A reasonable scheduler that ignores the existing schedule: shifts in time
order, each given to the qualified, available person with the fewest hours
so far, respecting overlaps, rest and hour caps. It is deliberately decent,
not a straw man. Its result is compared with the original schedule to show
how much a rebuild would disturb.
"""

from __future__ import annotations

from collections import defaultdict

from core.rules import conflicts, day_key, week_key

from .problem import RepairProblem


def rebuild_from_scratch(p: RepairProblem) -> tuple[int, int, int]:
    """(assignments changed, employees affected, shifts left uncovered) versus the original."""
    hours = defaultdict(float)
    day_h, week_h = defaultdict(float), defaultdict(float)
    taken: dict[str, list[str]] = defaultdict(list)
    for sid, eid in p.frozen.items():
        s = p.shifts[sid]
        taken[eid].append(sid)
        day_h[(eid, day_key(s))] += s.hours
        week_h[(eid, week_key(s))] += s.hours
        hours[eid] += s.hours

    result: dict[str, str | None] = {}
    for sid in p.slots:
        s = p.shifts[sid]
        best = None
        for eid in sorted(p.candidates[sid], key=lambda e: (hours[e], e)):
            daily, _, cap = p.limits(eid)
            if day_h[(eid, day_key(s))] + s.hours > daily or week_h[(eid, week_key(s))] + s.hours > cap:
                continue
            if any(conflicts(s, p.shifts[o], p.constraints.min_rest_hours) for o in taken[eid]):
                continue
            best = eid
            break
        result[sid] = best
        if best:
            taken[best].append(sid)
            day_h[(best, day_key(s))] += s.hours
            week_h[(best, week_key(s))] += s.hours
            hours[best] += s.hours

    changed = [sid for sid in p.slots if result[sid] != p.original.get(sid) and result[sid] is not None]
    affected = {result[s] for s in changed} | {p.original[s] for s in changed if p.original.get(s)}
    uncovered = sum(1 for sid in p.slots if result[sid] is None and p.original.get(sid))
    return len(changed), len(affected), uncovered
