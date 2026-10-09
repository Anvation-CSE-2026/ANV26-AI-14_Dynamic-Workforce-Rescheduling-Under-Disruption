"""Rewards & Recognition: points, badges and achievements for *successfully completed* contributions.

Lifecycle of a reward:

    extra work assigned (repair approved / workforce or volunteer assignment approved)
        → eligibility "pending_completion"           (no points yet: assignment ≠ contribution)
    work completed (admin confirms, or the shift has ended)
        → rule applied: points + badge, or "pending_approval" when the rule requires admin approval
    admin approves → granted

Volunteering alone never earns anything. Rewards are never read by the scheduler: fairness uses the
contribution ledger on the employee record (actual workload), not points.

Admin-configurable per organization: reward rules (trigger, points, badge, requires approval, enabled)
and the badge catalogue. Defaults come from the industry's recognition vocabulary
(``shared/domains/<domain>.json → recognition``), so labels stay domain-specific.
Points ledger documents are stored as kind ``recognition`` (shared with manager awards and the
reliability signals in ``services.recognition``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import recognition

TRIGGERS = {
    "coverage_completed": "Successfully completed additional coverage",
    "critical_completed": "Supported a critical task to completion",
    "emergency_completed": "Completed an emergency assignment",
    "volunteer_completed": "Completed a volunteered coverage",
    "reliability": "Consistent reliability (prompt acknowledgement, early notice)",
    "team_contribution": "Team contribution (admin award)",
    "exceptional_performance": "Exceptional performance (admin award)",
}

DEFAULT_BADGES = [
    {"id": "team_supporter", "name": "Team Supporter", "description": "Completed coverage for the team", "icon": "users"},
    {"id": "critical_support", "name": "Critical Support", "description": "Saw a critical task through", "icon": "shield"},
    {"id": "emergency_responder", "name": "Emergency Responder", "description": "Completed emergency coverage", "icon": "zap"},
    {"id": "dependable", "name": "Dependable", "description": "Prompt, reliable communication", "icon": "check"},
    {"id": "standout", "name": "Standout", "description": "Recognized by an admin", "icon": "star"},
]

ACHIEVEMENTS = [
    {"id": "first_cover", "name": "First Cover", "metric": "completed_covers", "target": 1},
    {"id": "five_covers", "name": "Reliable Backup", "metric": "completed_covers", "target": 5},
    {"id": "emergency_ready", "name": "Emergency Ready", "metric": "emergency_completed", "target": 1},
    {"id": "points_100", "name": "Century", "metric": "points_total", "target": 100},
    {"id": "points_250", "name": "Pillar of the Team", "metric": "points_total", "target": 250},
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _now().isoformat(timespec="seconds")


def default_config(domain: str) -> dict:
    cats = {c["id"]: c for c in recognition.config(domain)["categories"]}
    cover = next((c for c in cats.values() if "disruption_cover" in c["signals"]), None)
    crit = next((c for c in cats.values() if "critical_cover" in c["signals"]), None)
    rel = next((c for c in cats.values() if "prompt_acknowledgement" in c["signals"]), None)
    rules = [
        {"id": "R1", "trigger": "coverage_completed", "label": cover["label"] if cover else "Coverage completed",
         "category": cover["id"] if cover else None, "points": cover["points"] if cover else 20,
         "badge": "team_supporter", "requires_approval": False, "enabled": True},
        {"id": "R2", "trigger": "critical_completed", "label": crit["label"] if crit else "Critical support",
         "category": crit["id"] if crit else None, "points": crit["points"] if crit else 10,
         "badge": "critical_support", "requires_approval": False, "enabled": True},
        {"id": "R3", "trigger": "emergency_completed", "label": "Emergency response", "category": None,
         "points": 30, "badge": "emergency_responder", "requires_approval": False, "enabled": True},
        {"id": "R4", "trigger": "volunteer_completed", "label": "Volunteer coverage", "category": None,
         "points": 25, "badge": "team_supporter", "requires_approval": False, "enabled": True},
        {"id": "R5", "trigger": "reliability", "label": rel["label"] if rel else "Reliability",
         "category": rel["id"] if rel else None, "points": rel["points"] if rel else 5,
         "badge": "dependable", "requires_approval": False, "enabled": True},
        {"id": "R6", "trigger": "exceptional_performance", "label": "Exceptional performance", "category": None,
         "points": 30, "badge": "standout", "requires_approval": True, "enabled": True},
    ]
    return {"rules": rules, "badges": DEFAULT_BADGES, "achievements": ACHIEVEMENTS}


def config(store, org: str, domain: str) -> dict:
    saved = store.get("reward_config", "current", org)
    base = default_config(domain)
    if not saved:
        return base
    return {"rules": saved.get("rules", base["rules"]), "badges": saved.get("badges", base["badges"]),
            "achievements": ACHIEVEMENTS}


def save_config(store, org: str, domain: str, rules: list[dict], badges: Optional[list[dict]] = None) -> dict:
    current = config(store, org, domain)
    badge_ids = {b["id"] for b in (badges or current["badges"])}
    clean = []
    for r in rules:
        if r.get("trigger") not in TRIGGERS:
            raise ValueError(f"Unknown reward trigger '{r.get('trigger')}'")
        pts = int(r.get("points", 0))
        if not 0 <= pts <= 1000:
            raise ValueError("Points must be between 0 and 1000")
        if r.get("badge") and r["badge"] not in badge_ids:
            raise ValueError(f"Unknown badge '{r['badge']}'")
        clean.append({"id": str(r.get("id") or f"R{len(clean) + 1}"), "trigger": r["trigger"],
                      "label": str(r.get("label") or TRIGGERS[r["trigger"]])[:80], "category": r.get("category"),
                      "points": pts, "badge": r.get("badge") or None,
                      "requires_approval": bool(r.get("requires_approval")), "enabled": bool(r.get("enabled", True))})
    doc = {"rules": clean, "badges": badges or current["badges"], "updated_at": _iso()}
    store.put("reward_config", "current", org, doc)
    return config(store, org, domain)


def _rule(store, org: str, domain: str, trigger: str) -> Optional[dict]:
    return next((r for r in config(store, org, domain)["rules"] if r["trigger"] == trigger and r["enabled"]), None)


# ---------------------------------------------------------------- eligibility

def register(store, org: str, *, employee_id: str, employee_name: str, trigger: str, ref: str, shift_id: str,
             date: str, end: str, task: str, source: str, source_id: Optional[str] = None,
             critical: bool = False) -> dict:
    """Assigned extra work → eligibility pending completion (no points)."""
    existing = next((x for x in store.list("reward_eligibility", org, limit=5000)
                     if x["ref"] == ref and x["employee_id"] == employee_id), None)
    if existing:
        return existing
    doc = {"id": f"elg-{uuid.uuid4().hex[:8]}", "employee_id": employee_id, "employee_name": employee_name,
           "trigger": trigger, "ref": ref, "shift_id": shift_id, "date": date, "end": end, "task": task,
           "source": source, "source_id": source_id, "critical": critical,
           "status": "pending_completion", "created_at": _iso(),
           "completed_at": None, "award_id": None, "points": 0}
    store.put("reward_eligibility", doc["id"], org, doc)
    return doc


def eligibilities(store, org: str, employee_id: Optional[str] = None) -> list[dict]:
    rows = store.list("reward_eligibility", org, limit=5000)
    return [r for r in rows if employee_id is None or r["employee_id"] == employee_id]


def complete(store, org: str, domain: str, eligibility_id: str, actor: str) -> dict:
    """The work was done. Apply the reward rule (or queue it for approval)."""
    e = store.get("reward_eligibility", eligibility_id, org)
    if not e:
        raise KeyError("Unknown reward eligibility")
    if e["status"] != "pending_completion":
        return e
    e["status"], e["completed_at"], e["completed_by"] = "completed", _iso(), actor
    rule = _rule(store, org, domain, e["trigger"])
    if rule is None:
        e["status"] = "completed_no_reward"
    elif rule["requires_approval"]:
        e["status"], e["points"] = "pending_approval", rule["points"]
    else:
        award = _grant(store, org, e, rule, actor)
        e["status"], e["award_id"], e["points"] = "rewarded", award["id"], award["points"]
    bonus = _rule(store, org, domain, "critical_completed") if e.get("critical") else None
    if bonus and e["status"] == "rewarded" and not bonus["requires_approval"]:
        b = _grant(store, org, {**e, "ref": e["ref"] + ":critical"}, bonus, actor)
        e["bonus_award_id"], e["points"] = b["id"], e["points"] + b["points"]
    store.put("reward_eligibility", e["id"], org, e)
    return e


def approve(store, org: str, domain: str, eligibility_id: str, actor: str) -> dict:
    e = store.get("reward_eligibility", eligibility_id, org)
    if not e or e["status"] != "pending_approval":
        raise KeyError("Nothing to approve for this reward")
    rule = _rule(store, org, domain, e["trigger"]) or {"label": TRIGGERS[e["trigger"]], "points": e["points"],
                                                       "badge": None, "category": None}
    award = _grant(store, org, e, rule, actor)
    e["status"], e["award_id"] = "rewarded", award["id"]
    store.put("reward_eligibility", e["id"], org, e)
    return e


def _grant(store, org: str, e: dict, rule: dict, actor: str) -> dict:
    doc = {"id": f"rec-{uuid.uuid4().hex[:8]}", "created_at": _iso(), "employee_id": e["employee_id"],
           "employee_name": e["employee_name"], "category": rule.get("category") or e["trigger"],
           "category_label": rule["label"], "signal": e["trigger"], "points": int(rule["points"]),
           "badge": rule.get("badge"), "source": "reward", "reason": f"Completed: {e['task']} on {e['date']}",
           "ref": e["ref"], "awarded_by": actor, "eligibility_id": e["id"]}
    store.put("recognition", doc["id"], org, doc)
    return doc


def manager_award(store, org: str, domain: str, employee_id: str, employee_name: str, trigger: str, note: str,
                  actor: str) -> dict:
    """Admin award for team contribution / exceptional performance (configured rule, may need approval)."""
    if trigger not in ("team_contribution", "exceptional_performance"):
        raise ValueError("Admins can award team_contribution or exceptional_performance")
    if not note.strip():
        raise ValueError("Add a short note saying what the award is for")
    rule = _rule(store, org, domain, trigger) or {"label": TRIGGERS[trigger], "points": 15, "badge": "standout",
                                                  "category": None, "requires_approval": False}
    e = register(store, org, employee_id=employee_id, employee_name=employee_name, trigger=trigger,
                 ref=f"award:{uuid.uuid4().hex[:6]}", shift_id="", date=_now().date().isoformat(), end="",
                 task=note.strip()[:120], source="admin")
    e["status"] = "pending_completion"
    store.put("reward_eligibility", e["id"], org, e)
    out = complete(store, org, domain, e["id"], actor)
    if rule.get("requires_approval") and out["status"] == "pending_approval":
        return approve(store, org, domain, out["id"], actor)       # the admin giving it is the approver
    return out


# ---------------------------------------------------------------- summaries

def employee_summary(store, org: str, domain: str, employee_id: str, employee_name: str) -> dict:
    base = recognition.summary(store, org, domain, employee_id, employee_name)
    awards = [a for a in store.list("recognition", org, limit=5000) if a["employee_id"] == employee_id]
    cfg = config(store, org, domain)
    badge_info = {b["id"]: b for b in cfg["badges"]}
    badges: dict[str, dict] = {}
    for a in sorted(awards, key=lambda x: x["created_at"]):
        if a.get("badge") and a["badge"] in badge_info:
            b = badges.setdefault(a["badge"], {**badge_info[a["badge"]], "count": 0, "first_earned": a["created_at"]})
            b["count"] += 1
    elig = eligibilities(store, org, employee_id)
    metrics = {"completed_covers": sum(1 for x in elig if x["status"] in ("rewarded", "completed", "pending_approval")
                                       and x["trigger"] != "reliability" and x["source"] != "admin"),
               "emergency_completed": sum(1 for x in elig if x["trigger"] == "emergency_completed"
                                          and x["status"] in ("rewarded", "completed", "pending_approval")),
               "points_total": sum(a["points"] for a in awards)}
    achievements = [{**a, "progress": min(metrics[a["metric"]], a["target"]), "unlocked": metrics[a["metric"]] >= a["target"]}
                    for a in ACHIEVEMENTS]
    return {**base, "points_total": metrics["points_total"], "badges": list(badges.values()),
            "achievements": achievements, "history": awards[:50],
            "contributions": elig[:50],
            "pending": [x for x in elig if x["status"] in ("pending_completion", "pending_approval")]}


def overview(store, org: str, domain: str, employees: list[tuple[str, str]]) -> dict:
    people = [employee_summary(store, org, domain, eid, name) for eid, name in employees]
    people.sort(key=lambda s: (-s["points_90d"], s["employee_name"]))
    awards = store.list("recognition", org, limit=5000)
    since = _now() - timedelta(days=30)
    elig = eligibilities(store, org)
    return {"config": {**recognition.config(domain), **config(store, org, domain)}, "triggers": TRIGGERS,
            "employees": [{k: p[k] for k in ("employee_id", "employee_name", "points_90d", "points_total", "tier",
                                             "next_tier", "categories", "badges", "achievements")} for p in people],
            "recent": awards[:20],
            "pending_approval": [x for x in elig if x["status"] == "pending_approval"],
            "pending_completion": [x for x in elig if x["status"] == "pending_completion"],
            "stats": {"points_30d": sum(a["points"] for a in awards
                                        if datetime.fromisoformat(a["created_at"]) >= since),
                      "rewards_issued": len(awards), "badges_issued": sum(1 for a in awards if a.get("badge")),
                      "awaiting_completion": sum(1 for x in elig if x["status"] == "pending_completion")}}


def trigger_for(priority: str, emergency: bool = False, volunteer: bool = False) -> str:
    """Base trigger; critical work additionally earns the critical-support bonus (``critical=True``)."""
    if emergency:
        return "emergency_completed"
    return "volunteer_completed" if volunteer else "coverage_completed"

