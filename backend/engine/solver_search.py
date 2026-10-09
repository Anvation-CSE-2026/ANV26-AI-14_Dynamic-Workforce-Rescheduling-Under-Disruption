"""Exact bounded search: the fallback when OR-Tools isn't installed.

Repairs are explored as *chains*: fill an open shift with an eligible person;
if that person must leave one of their own shifts (overlap or rest), that
shift opens up and is filled in turn. Every repair with up to ``max_changes``
reassignments is enumerated, hard rules are checked by ``engine.evaluate``,
and the cheapest valid repair per strategy wins.

Within that bound the result is exact. Because the objective charges heavily
for every change, real optima almost always fall inside it; CP-SAT
(``solver_cpsat``) has no such bound and is used whenever available.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from core.rules import conflicts

from .evaluate import Assignment, evaluate
from .problem import RepairProblem

MAX_CHANGES = 3
MAX_LEAVES = 50_000


def start_state(p: RepairProblem) -> Assignment:
    return {sid: (p.original.get(sid) if p.original.get(sid) in p.candidates[sid] else None) for sid in p.slots}


def enumerate_repairs(p: RepairProblem, max_changes: int = MAX_CHANGES) -> list[Assignment]:
    locked = set(p.settings.locked_employee_ids)

    @lru_cache(maxsize=None)
    def clash(a: str, b: str) -> bool:
        return conflicts(p.shifts[a], p.shifts[b], p.constraints.min_rest_hours) is not None

    results: dict[tuple, Assignment] = {}
    state = start_state(p)
    open0 = [sid for sid in p.slots if state[sid] is None and (sid in p.original or sid in p.vacated)]
    open0 += [sid for sid in p.slots if state[sid] is None and sid not in open0]

    def key(st: Assignment) -> tuple:
        return tuple(st[s] for s in p.slots)

    def dfs(st: Assignment, open_slots: list[str], changes: int) -> None:
        if len(results) >= MAX_LEAVES:
            return
        if not open_slots:
            results.setdefault(key(st), dict(st))
            return
        sid, rest = open_slots[0], open_slots[1:]
        # option 1: leave it uncovered (heavily penalized, but keeps the search honest)
        dfs(st, rest, changes)
        if changes >= max_changes:
            return
        for eid in p.candidates[sid]:
            mine = [s for s, e in st.items() if e == eid and s != sid]
            blocking = [s for s in mine if clash(s, sid)]
            if any(eid in locked and p.original.get(s) == eid for s in blocking):
                continue
            nxt = dict(st)
            nxt[sid] = eid
            for b in blocking:
                nxt[b] = None
            dfs(nxt, rest + [b for b in blocking if b not in rest], changes + 1)

    dfs(state, open0, 0)
    return list(results.values())


def solve(p: RepairProblem, strategy: str, exclude: Optional[list[Assignment]] = None,
          force: Optional[tuple[str, str]] = None, pool: Optional[list[Assignment]] = None) -> Optional[Assignment]:
    """Best valid repair for ``strategy``; ``exclude`` = repairs to skip; ``force`` = (slot, employee) required."""
    pool = pool if pool is not None else enumerate_repairs(p)
    excluded = [tuple(e.get(s) for s in p.slots) for e in (exclude or [])]
    best, best_cost = None, float("inf")
    for a in pool:
        if tuple(a.get(s) for s in p.slots) in excluded:
            continue
        if force and a.get(force[0]) != force[1]:
            continue
        ev = evaluate(p, a, strategy)
        if ev.valid and ev.cost < best_cost:
            best, best_cost = a, ev.cost
    return best
