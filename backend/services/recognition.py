"""Recognition: a professional, domain-configured layer that rewards *behaviour that helps the team*.

Categories, points and benefit tiers come from ``shared/domains/<domain>.json → recognition``, so each
industry uses its own vocabulary (Shift Rescue, Safety Champion, Incident Support…). The engine only
knows a handful of generic, observable signals:

    disruption_cover        took on work in an approved repair to cover a colleague's absence or a conflict
    critical_cover          …and that shift was critical priority
    prompt_acknowledgement  acknowledged a schedule change within 12 hours of being told
    advance_notice          reported an absence at least 48 hours before the shift
    history                 disruptions absorbed in the 30 days before the data was loaded (imported baseline)
    manager                 a manager recognized someone in a category, with a note

To avoid perverse incentives, by design:
* nothing is earned for hours worked, shift counts or overtime, and covering with overtime earns the
  same as covering without;
* absences never cost points, and giving early notice earns them;
* system signals are capped at 3 awards per category per rolling 30 days;
* tiers use a rolling 90-day window, so recognition reflects recent contribution.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from .domains import domain_config

SIGNAL_CAP_30D = 3
TIER_WINDOW_DAYS = 90
ACK_WINDOW_HOURS = 12
NOTICE_DAYS = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def config(domain: str) -> dict:
    return domain_config(domain).get("recognition", {"categories": [], "tiers": []})


def _category_for(domain: str, signal: str) -> Optional[dict]:
    return next((c for c in config(domain)["categories"] if signal in c["signals"]), None)


def _store_award(store, org: str, doc: dict) -> dict:
    doc = {"id": f"rec-{uuid.uuid4().hex[:8]}", "created_at": _now().isoformat(timespec="seconds"), **doc}
    store.put("recognition", doc["id"], org, doc)
    return doc


def award_signal(store, org: str, domain: str, employee_id: str, employee_name: str, signal: str,
                 reason: str, ref: Optional[str] = None, points: Optional[int] = None) -> Optional[dict]:
    """System award for an observed behaviour. Returns None when the domain has no category for it or
    the 30-day cap for that category is reached."""
    cat = _category_for(domain, "disruption_cover" if signal == "history" else signal)
    if cat is None:
        return None
    since = _now() - timedelta(days=30)
    recent = [a for a in store.list("recognition", org, limit=2000)
              if a["employee_id"] == employee_id and a["category"] == cat["id"] and a["source"] == "system"
              and datetime.fromisoformat(a["created_at"]) >= since]
    if signal != "history" and len(recent) >= SIGNAL_CAP_30D:
        return None
    if ref and any(a.get("ref") == ref and a.get("signal") == signal for a in recent):
        return None                                   # one award per event
    return _store_award(store, org, {"employee_id": employee_id, "employee_name": employee_name,
                                     "category": cat["id"], "category_label": cat["label"], "signal": signal,
                                     "points": cat["points"] if points is None else points, "source": "system",
                                     "reason": reason, "ref": ref, "awarded_by": "ResQWork",
                                     "badge": "dependable" if signal in ("prompt_acknowledgement", "advance_notice")
                                     else None})


def manager_award(store, org: str, domain: str, employee_id: str, employee_name: str, category: str,
                  note: str, actor: str) -> dict:
    cat = next((c for c in config(domain)["categories"] if c["id"] == category), None)
    if cat is None or not cat.get("managerAwardable", True):
        raise ValueError(f"'{category}' is not a recognition category managers can award here")
    if not note.strip():
        raise ValueError("Add a short note saying what the recognition is for")
    return _store_award(store, org, {"employee_id": employee_id, "employee_name": employee_name,
                                     "category": cat["id"], "category_label": cat["label"], "signal": "manager",
                                     "points": cat["points"], "source": "manager", "reason": note.strip(),
                                     "ref": None, "awarded_by": actor})


def seed_from_history(store, org: str, domain: str, employees) -> int:
    """Imported baseline: people who absorbed disruptions before the data was loaded get credit for it."""
    n = 0
    for e in employees:
        k = min(e.history.disruptions_absorbed_30d, SIGNAL_CAP_30D)
        if k > 0:
            cat = _category_for(domain, "disruption_cover")
            if cat and award_signal(store, org, domain, e.id, e.name, "history",
                                    f"Covered {k} disruption{'s' if k > 1 else ''} in the 30 days before ResQWork "
                                    "(imported history)", ref=f"history:{e.id}", points=cat["points"] * k // 2):
                n += 1
    return n


def _tier(domain: str, points: int) -> tuple[Optional[dict], Optional[dict]]:
    tiers = sorted(config(domain)["tiers"], key=lambda t: t["points"])
    reached = [t for t in tiers if points >= t["points"]]
    nxt = next((t for t in tiers if points < t["points"]), None)
    return (reached[-1] if reached else None), nxt


def summary(store, org: str, domain: str, employee_id: str, employee_name: str) -> dict:
    awards = [a for a in store.list("recognition", org, limit=2000) if a["employee_id"] == employee_id]
    since = _now() - timedelta(days=TIER_WINDOW_DAYS)
    recent_points = sum(a["points"] for a in awards if datetime.fromisoformat(a["created_at"]) >= since)
    tier, nxt = _tier(domain, recent_points)
    by_cat: dict[str, dict] = {}
    for a in awards:
        c = by_cat.setdefault(a["category"], {"category": a["category"], "label": a["category_label"], "count": 0,
                                              "points": 0})
        c["count"] += 1
        c["points"] += a["points"]
    return {"employee_id": employee_id, "employee_name": employee_name, "points_90d": recent_points,
            "tier": tier, "next_tier": nxt, "categories": sorted(by_cat.values(), key=lambda c: -c["points"]),
            "awards": awards[:20]}


def on_approval(store, org: str, domain: str, option: dict, shifts: dict, conflict_run: bool) -> list[dict]:
    """Recognize the people who took on work in an approved repair (never for the hours themselves)."""
    out = []
    covered: dict[str, list] = {}
    for c in option["changes"]:
        if c.get("to_employee_id"):
            covered.setdefault(c["to_employee_id"], []).append(c)
    for eid, changes in covered.items():
        name = changes[0]["to_employee_name"]
        what = ", ".join(sorted({ch["assignment"] for ch in changes}))
        a = award_signal(store, org, domain, eid, name, "disruption_cover",
                         f"Took on {what} to {'resolve a schedule conflict' if conflict_run else 'cover a colleague'}",
                         ref=f"{option['option_id']}:{changes[0]['shift_id']}:{changes[0]['date']}")
        if a:
            out.append(a)
        crit = [ch for ch in changes if shifts.get(ch["shift_id"]) is not None
                and shifts[ch["shift_id"]].priority == "critical"]
        if crit:
            b = award_signal(store, org, domain, eid, name, "critical_cover",
                             f"Covered critical work: {crit[0]['assignment']}", ref=f"crit:{crit[0]['shift_id']}")
            if b:
                out.append(b)
    return out


def on_acknowledge(store, org: str, domain: str, notification: dict) -> Optional[dict]:
    try:
        told = datetime.fromisoformat(notification["created_at"])
    except (KeyError, ValueError):
        return None
    if (_now() - told) > timedelta(hours=ACK_WINDOW_HOURS) or not notification.get("requires_acknowledgement"):
        return None
    return award_signal(store, org, domain, notification["employee_id"], notification.get("employee_name") or "",
                        "prompt_acknowledgement", "Acknowledged a schedule change promptly", ref=notification["id"])


def on_request(store, org: str, domain: str, req: dict) -> Optional[dict]:
    if req.get("kind") not in ("unavailable", "time_off"):
        return None
    try:
        lead = datetime.fromisoformat(req["date"] + "T00:00:00+00:00") - datetime.fromisoformat(req["created_at"])
    except ValueError:
        return None
    if lead < timedelta(days=NOTICE_DAYS):
        return None
    return award_signal(store, org, domain, req["employee_id"], req["employee_name"], "advance_notice",
                        f"Gave {lead.days} days' notice of an absence", ref=req["id"])
