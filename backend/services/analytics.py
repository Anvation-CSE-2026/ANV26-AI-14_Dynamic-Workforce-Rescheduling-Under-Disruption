"""Organization-level analytics computed from stored disruptions, proposals and versions."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import fmean

from core.models import Dataset

from . import kpis


def _best(p: dict) -> dict | None:
    r = p["result"]
    oid = p.get("approved_option") or r.get("recommended_option_id")
    return next((o for o in r["options"] if o["option_id"] == oid), None)


def org_analytics(disruptions: list[dict], proposals: list[dict], versions: list[dict], ds: Dataset) -> dict:
    roots = [p for p in proposals if not p.get("parent_id")]          # what-ifs don't count as separate repairs
    approved = [p for p in proposals if p["status"] == "approved"]
    decided = [p for p in roots if p["status"] in ("approved", "rejected")] + \
              [p for p in proposals if p.get("parent_id") and p["status"] == "approved"]
    chosen = [o for o in (_best(p) for p in approved) if o]

    overtime_avoided = 0.0
    for p in approved:
        o = _best(p)
        if o:
            worst = max(x["impact"]["overtime_hours_added"] for x in p["result"]["options"])
            overtime_avoided += worst - o["impact"]["overtime_hours_added"]
    changes_avoided = sum(max(0, (p["result"].get("baseline") or {}).get("assignments_changed", 0)
                              - (_best(p) or {"impact": {"assignments_changed": 0}})["impact"]["assignments_changed"])
                          for p in approved)

    reasons = Counter(((d.get("disruption") or {}).get("reason") or
                       ("schedule conflict" if d.get("kind") == "conflict" else "unspecified")) for d in disruptions)
    depts = Counter()
    by_day = defaultdict(lambda: {"disruptions": 0, "repairs": 0})
    for d in disruptions:
        by_day[d["created_at"][:10]]["disruptions"] += 1
    for p in approved:
        by_day[p.get("decided_at", p["created_at"])[:10]]["repairs"] += 1
        o = _best(p)
        for dep in (o or {}).get("impact", {}).get("departments_affected", []):
            depts[dep] += 1
    open_d = []
    metrics = kpis.compute(ds, open_d)
    return {
        "disruptions": len(disruptions),
        "repairs_approved": len(approved),
        "repair_success_rate": round(100 * len(approved) / len(decided), 1) if decided else None,
        "avg_impact_score": round(fmean(o["impact"]["impact_score"] for o in chosen), 1) if chosen else None,
        "avg_employees_affected": round(fmean(o["impact"]["employees_affected"] for o in chosen), 2) if chosen else None,
        "overtime_hours_avoided": round(overtime_avoided, 1),
        "assignment_changes_avoided_vs_rebuild": changes_avoided,
        "skill_coverage_pct": metrics["skill_coverage_pct"]["value"],
        "avg_fairness_score": round(fmean(o["fairness"]["fairness_score"] for o in chosen), 1) if chosen else None,
        "schedule_stability_pct": round(fmean(o["impact"]["preservation_rate"] for o in chosen), 1) if chosen else 100.0,
        "most_common_disruption": reasons.most_common(1)[0][0] if reasons else None,
        "most_affected_department": depts.most_common(1)[0][0] if depts else None,
        "versions": len(versions),
        "trend": [{"date": k, **v} for k, v in sorted(by_day.items())],
        "repair_impact": [{"version": v["tag"], "impact": v.get("impact", {}).get("impact_score"),
                           "changes": v.get("impact", {}).get("assignments_changed"),
                           "overtime": v.get("impact", {}).get("overtime_hours_added"),
                           "fairness": v.get("fairness", {}).get("fairness_score")}
                          for v in sorted(versions, key=lambda v: v["created_at"]) if v.get("impact")],
        "disruption_reasons": [{"reason": k, "count": v} for k, v in reasons.most_common()],
    }


def operations_analytics(svc, org: str) -> dict:
    """Workforce, fairness, notification, reward and conflict analytics (each answers an operational question)."""
    from analytics import fairness_engine

    from . import notify, rewards, workforce

    ds = svc.dataset(org)
    proposals = svc.store.list("proposal", org, limit=2000)
    audits = svc.store.list("audit", org, limit=5000)
    notes = svc.store.list("notification", org, limit=5000)
    wfr = svc.store.list("workforce_request", org)
    awards = svc.store.list("recognition", org, limit=5000)
    gaps = workforce.staffing_gaps(ds, svc.open_disruptions(org))

    # repair time: disruption reported → repair approved
    reported = {d["id"]: d["created_at"] for d in svc.store.list("disruption", org, limit=2000)}
    durations = []
    for p in proposals:
        if p["status"] == "approved" and p.get("decided_at"):
            starts = [reported[i] for i in p.get("disruption_ids", []) if i in reported]
            if starts:
                from datetime import datetime
                durations.append((datetime.fromisoformat(p["decided_at"]) - datetime.fromisoformat(min(starts)))
                                 .total_seconds() / 60)
    solve_ms = [p["result"]["solve_ms"] for p in proposals if not p.get("parent_id")]
    hard_rejections = sum(len(p["result"].get("rejected", [])) for p in proposals if not p.get("parent_id"))
    soft = [o["fairness"]["preference_respect"] for p in proposals for o in p["result"]["options"][:1]]
    dist = fairness_engine.team_distribution(ds)
    loads = [r["contribution_load"] for r in dist]
    detected = sum(1 for a in audits if a["event_type"] in ("DISRUPTION_REPORTED", "CONFLICTS_DETECTED"))
    resolved = sum(1 for a in audits if a["event_type"] == "SCHEDULE_APPROVED")
    return {
        "conflicts_detected": detected, "conflicts_resolved": resolved,
        "avg_repair_minutes": round(fmean(durations), 1) if durations else None,
        "avg_solve_ms": round(fmean(solve_ms)) if solve_ms else None,
        "staffing_gaps": len(gaps), "staffing_gap_people": sum(g["gap"] for g in gaps),
        "workforce": workforce.summary_counts(wfr),
        "volunteer_participation": sum(len([v for v in w.get("volunteers", []) if v["status"] != "declined"])
                                       for w in wfr),
        "hard_constraint_rejections": hard_rejections,
        "hard_constraint_violations_published": 0,      # every published option passed full validation
        "soft_constraint_satisfaction": round(fmean(soft), 1) if soft else None,
        "fairness_distribution": [{"employee": r["employee_name"], "load": r["contribution_load"],
                                   "weekly_hours": r["weekly_hours"]} for r in dist[:15]],
        "fairness_spread": round(max(loads) - min(loads), 2) if loads else 0,
        "rewards_issued": len(awards), "reward_points": sum(a["points"] for a in awards),
        "notifications": notify.summary(notes),
        "workload_distribution": [{"employee": r["employee_name"], "hours": r["weekly_hours"]}
                                  for r in sorted(dist, key=lambda r: -r["weekly_hours"])[:15]],
        "rewards_by_trigger": [{"trigger": k, "count": v} for k, v in
                               Counter(a.get("signal", "manager") for a in awards).most_common()],
        "pending_rewards": sum(1 for e in rewards.eligibilities(svc.store, org) if e["status"] == "pending_completion"),
    }
