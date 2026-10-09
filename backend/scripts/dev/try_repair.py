"""Dev helper: print validation + repair options for demo datasets.  python -m scripts.dev.try_repair healthcare"""
import json, sys, time
from core.validation import validate_dataset
from engine.repair import generate_repair

for dom in sys.argv[1:]:
    rep = validate_dataset(json.load(open(f"../shared/demo-data/{dom}.json")))
    print(f"\n######## {dom}: {rep.status} — {rep.summary}")
    for f in rep.errors + rep.warnings:
        print("   ", f.severity, f.category, f.message)
    ds = rep.dataset
    for d in ds.disruptions:
        t = time.time()
        res = generate_repair(ds, [d])
        print(f"\n== {d.label} ({res.status}, {res.solver}, {int((time.time()-t)*1000)}ms) vacated={res.disrupted_shifts}")
        if res.baseline:
            print("   baseline:", res.baseline.model_dump())
        for o in res.options:
            ch = "; ".join(f"{c.assignment[:30]} {c.from_employee_name}→{c.to_employee_name}" for c in o.changes)
            print(f"   {o.label} {o.title:23} best_for={o.best_for} cost={o.cost:.0f} impact={o.impact.impact_score}% "
                  f"{o.impact.impact_level} chg={o.impact.assignments_changed} aff={o.impact.employees_affected} "
                  f"ot={o.impact.overtime_hours_added} fair={o.fairness.fairness_score} | {ch}")
        for r in res.rejected[:9]:
            print("     why-not:", r.employee_name, r.reason_code, "-", r.detail)
        for r in res.infeasibility_reasons:
            print("     infeasible:", r)
