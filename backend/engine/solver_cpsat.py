"""Google OR-Tools CP-SAT repair model (primary solver).

Builds on Member 4's original formulation (one person per shift, availability,
skills, no overlaps, minimum-change objective) and adds what Round 2 needs:
rest periods, daily and weekly hour caps, overtime as a penalized variable,
graceful "uncovered" slack, locked/excluded employees, manager feedback,
strategy weight profiles, no-good cuts for distinct alternatives, and forced
assignments for "why not X?" counterfactuals.

The objective mirrors ``engine.evaluate.cost`` term for term (in minutes ×
weights), so CP-SAT and the fallback search rank repairs identically; the
returned assignment is re-evaluated and validated in Python afterwards.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from core.rules import conflicts, day_key, week_key

from .evaluate import Assignment, fairness_units, lacks_continuity, location_mismatch, preference_violation, weights
from .problem import RepairProblem

try:  # pragma: no cover - availability depends on the machine
    from ortools.sat.python import cp_model
    AVAILABLE = True
except ImportError:  # pragma: no cover
    cp_model = None
    AVAILABLE = False

TIME_LIMIT_S = 10.0
_STATUS: Optional[dict] = None


def status() -> dict:
    """Is CP-SAT really installed and solving? Runs a tiny model once per process (cached).

    The repair engine labels every result with the solver that produced it, so a demo can never
    claim CP-SAT while it is running the exact-search fallback."""
    global _STATUS
    if _STATUS is not None:
        return _STATUS
    if not AVAILABLE:
        _STATUS = {"engine": "exact bounded search", "cp_sat": False, "installed": False, "version": None,
                   "self_test": None,
                   "message": "OR-Tools is not installed, so repairs use the exact bounded search fallback "
                              "(same rules, same objective). Run: pip install ortools"}
        return _STATUS
    import time
    try:
        import ortools
        version = getattr(ortools, "__version__", "unknown")
    except Exception:  # noqa: BLE001
        version = "unknown"
    t0 = time.monotonic()
    m = cp_model.CpModel()
    a, b = m.NewBoolVar("a"), m.NewBoolVar("b")
    m.AddExactlyOne([a, b])
    m.Minimize(3 * a + 2 * b)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    st = solver.Solve(m)
    ok = st == cp_model.OPTIMAL and solver.Value(b) == 1 and solver.ObjectiveValue() == 2
    _STATUS = {"engine": "OR-Tools CP-SAT" if ok else "exact bounded search", "cp_sat": ok, "installed": True,
               "version": version, "self_test": {"ok": ok, "status": solver.StatusName(st),
                                                 "ms": int((time.monotonic() - t0) * 1000)},
               "message": f"OR-Tools CP-SAT {version} verified by a self-test solve." if ok else
                          "OR-Tools is installed but its self-test failed; using the exact search fallback."}
    return _STATUS


def usable() -> bool:
    return bool(status()["cp_sat"])


def _minutes(h: float) -> int:
    return int(round(h * 60))


def solve(p: RepairProblem, strategy: str, exclude: Optional[list[Assignment]] = None,
          force: Optional[tuple[str, str]] = None, time_limit_s: float = TIME_LIMIT_S) -> Optional[Assignment]:
    if not AVAILABLE:
        raise RuntimeError("ortools is not installed")
    m = cp_model.CpModel()
    w = weights(p, strategy)
    S = lambda v: int(round(v * 60))  # noqa: E731  (weights scaled to the minute)

    x: dict[tuple[str, str], object] = {}
    u: dict[str, object] = {}
    for sid in p.slots:
        for eid in p.candidates[sid]:
            x[(sid, eid)] = m.NewBoolVar(f"x[{sid},{eid}]")
        u[sid] = m.NewBoolVar(f"u[{sid}]")
        m.AddExactlyOne([x[(sid, e)] for e in p.candidates[sid]] + [u[sid]])

    if force:
        if force not in x:
            return None
        m.Add(x[force] == 1)

    locked = set(p.settings.locked_employee_ids)
    for sid in p.slots:
        orig = p.original.get(sid)
        if orig in locked and (sid, orig) in x:
            m.Add(x[(sid, orig)] == 1)

    # no overlaps / minimum rest between two decision slots for the same person
    by_emp: dict[str, list[str]] = defaultdict(list)
    for (sid, eid) in x:
        by_emp[eid].append(sid)
    for eid, sids in by_emp.items():
        sids.sort(key=lambda s: p.shifts[s].window[0])
        for i in range(len(sids)):
            for j in range(i + 1, len(sids)):
                if conflicts(p.shifts[sids[i]], p.shifts[sids[j]], p.constraints.min_rest_hours):
                    m.Add(x[(sids[i], eid)] + x[(sids[j], eid)] <= 1)

    # daily and weekly caps, counting frozen shifts as constants
    frozen_day, frozen_week, orig_week = defaultdict(int), defaultdict(int), defaultdict(int)
    for sid, eid in p.frozen.items():
        frozen_day[(eid, day_key(p.shifts[sid]))] += _minutes(p.shifts[sid].hours)
        frozen_week[(eid, week_key(p.shifts[sid]))] += _minutes(p.shifts[sid].hours)
    for sid, eid in p.original.items():
        if sid not in p.settings.release_shift_ids:
            orig_week[(eid, week_key(p.shifts[sid]))] += _minutes(p.shifts[sid].hours)

    day_terms, week_terms = defaultdict(list), defaultdict(list)
    for (sid, eid), var in x.items():
        mins = _minutes(p.shifts[sid].hours)
        day_terms[(eid, day_key(p.shifts[sid]))].append(mins * var)
        week_terms[(eid, week_key(p.shifts[sid]))].append(mins * var)

    for (eid, day), terms in day_terms.items():
        daily, _, _ = p.limits(eid)
        m.Add(sum(terms) + frozen_day[(eid, day)] <= _minutes(daily))

    overtime_vars = []
    for (eid, wk), terms in week_terms.items():
        _, contracted, cap = p.limits(eid)
        total = sum(terms) + frozen_week[(eid, wk)]
        m.Add(total <= max(_minutes(cap), orig_week[(eid, wk)]))
        base = max(_minutes(contracted), orig_week[(eid, wk)])
        ot = m.NewIntVar(0, 7 * 24 * 60, f"ot[{eid},{wk}]")
        m.Add(ot >= total - base)
        overtime_vars.append(ot)

    # objective terms (same as engine.evaluate.cost)
    obj = []
    affected: dict[str, object] = {}

    def aff(eid: str):
        if eid not in affected:
            affected[eid] = m.NewBoolVar(f"aff[{eid}]")
        return affected[eid]

    avoid, prefer = set(p.settings.avoid_employee_ids), set(p.settings.prefer_employee_ids)
    for sid in p.slots:
        orig = p.original.get(sid)
        has_orig_slot = sid in p.original or sid in p.vacated
        if has_orig_slot:
            obj.append(S(w["unfilled"]) * u[sid])
        for eid in p.candidates[sid]:
            if eid == orig:
                continue
            var = x[(sid, eid)]
            obj.append(S(w["assignment_change"]) * var)
            obj.append(S(w["fairness"] * fairness_units(p, eid)) * var)
            if preference_violation(p, eid, sid):
                obj.append(S(w["preference"]) * var)
            if location_mismatch(p, eid, sid):
                obj.append(S(w.get("location", 0)) * var)
            if lacks_continuity(p, eid, sid):
                obj.append(S(w.get("continuity", 0)) * var)
            if eid in avoid:
                obj.append(S(2 * w["assignment_change"]) * var)
            if eid in prefer:
                obj.append(-S(5 * w["preference"]) * var)
            m.Add(aff(eid) >= var)
            if orig and sid not in p.vacated:
                m.Add(aff(orig) >= var)
    obj += [S(w["employee_affected"]) * v for v in affected.values()]
    obj += [int(round(w["overtime_hour"])) * v for v in overtime_vars]

    for prev in exclude or []:
        lits = [x[(sid, eid)] if eid else u[sid] for sid, eid in prev.items()
                if (eid is None) or (sid, eid) in x]
        if lits:
            m.Add(sum(lits) <= len(lits) - 1)

    m.Minimize(sum(obj))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 8
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    out: Assignment = {}
    for sid in p.slots:
        out[sid] = next((e for e in p.candidates[sid] if solver.Value(x[(sid, e)])), None)
    return out
