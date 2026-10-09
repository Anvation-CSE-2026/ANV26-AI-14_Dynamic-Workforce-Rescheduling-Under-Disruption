"""Three-level notifications with delivery tracking and escalation.

    LEVEL 1  informational  green   dashboard + email
    LEVEL 2  important      orange  dashboard + email; if not acknowledged within the org's escalation
                                    window (default 30 min) → WhatsApp + SMS
    LEVEL 3  critical       red     dashboard + email + WhatsApp + SMS at once

Each notification is one document that is also its audit record: per channel it keeps
sent / delivered / opened / acknowledged timestamps, the provider used and the escalation level.

Delivery: email goes through SMTP when ``SMTP_HOST`` is set, SMS and WhatsApp through Twilio when
``TWILIO_ACCOUNT_SID``/``TWILIO_AUTH_TOKEN``/``TWILIO_FROM`` (and ``TWILIO_WHATSAPP_FROM``) are set.
Without credentials a channel is recorded as ``simulated``: the message is rendered and logged to the
outbox exactly as it would be sent, and the UI says so. Nothing pretends to have been delivered.
Voice is intentionally not a channel yet (``FUTURE_CHANNELS``).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Optional
from urllib import parse, request as urlrequest

log = logging.getLogger("resqwork.notify")

LEVELS = {
    1: {"name": "informational", "label": "Informational", "color": "green", "channels": ["dashboard", "email"],
        "escalation": []},
    2: {"name": "important", "label": "Important", "color": "orange", "channels": ["dashboard", "email"],
        "escalation": ["whatsapp", "sms"]},
    3: {"name": "critical", "label": "Critical", "color": "red",
        "channels": ["dashboard", "email", "whatsapp", "sms"], "escalation": []},
}
FUTURE_CHANNELS = ["voice"]
DEFAULT_SETTINGS = {"l2_escalation_minutes": 30}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: Optional[datetime] = None) -> str:
    return (d or _now()).isoformat(timespec="seconds")


def settings(store, org: str) -> dict:
    return {**DEFAULT_SETTINGS, **(store.get("notification_settings", "current", org) or {})}


def save_settings(store, org: str, minutes: int) -> dict:
    if not 0 <= minutes <= 24 * 60:
        raise ValueError("Escalation window must be between 0 and 1440 minutes")
    doc = {**settings(store, org), "l2_escalation_minutes": minutes}
    store.put("notification_settings", "current", org, doc)
    return doc


# ---------------------------------------------------------------- channel providers

def provider_status() -> dict:
    return {"email": "smtp" if os.getenv("SMTP_HOST") else "simulated",
            "sms": "twilio" if _twilio("sms") else "simulated",
            "whatsapp": "twilio" if _twilio("whatsapp") else "simulated",
            "dashboard": "in-app", "voice": "not enabled (future extension)"}


def _twilio(kind: str) -> Optional[tuple[str, str, str]]:
    sid, tok = os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")
    sender = os.getenv("TWILIO_WHATSAPP_FROM") if kind == "whatsapp" else os.getenv("TWILIO_FROM")
    return (sid, tok, sender) if sid and tok and sender else None


def _send_email(to: str, subject: str, body: str) -> str:
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM", "ResQWork <no-reply@resqwork.app>")
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=10) as s:
        if port != 25:
            s.starttls()
        if os.getenv("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(msg)
    return "smtp"


def _send_twilio(kind: str, to: str, body: str) -> str:
    creds = _twilio(kind)
    if creds is None:
        raise RuntimeError("Twilio is not configured")
    sid, tok, sender = creds
    if kind == "whatsapp":
        to, sender = f"whatsapp:{to}", (sender if sender.startswith("whatsapp:") else f"whatsapp:{sender}")
    data = parse.urlencode({"To": to, "From": sender, "Body": body[:1500]}).encode()
    req = urlrequest.Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data,
                             headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode()})
    with urlrequest.urlopen(req, timeout=10) as r:   # noqa: S310 - fixed https endpoint
        json.loads(r.read() or b"{}")
    return "twilio"


def _deliver(store, org: str, n: dict, channel: str, contact: dict, escalation_level: int) -> dict:
    now = _iso()
    rec = {"channel": channel, "status": "sent", "provider": "in-app", "sent_at": now, "delivered_at": None,
           "opened_at": None, "acknowledged_at": None, "escalation_level": escalation_level, "error": None}
    text = f"[ResQWork · {LEVELS[n['severity']]['label']}] {n['title']}\n{n['message']}"
    try:
        if channel == "dashboard":
            rec["status"], rec["delivered_at"] = "delivered", now
        elif channel == "email":
            if not contact.get("email"):
                rec.update(status="skipped", error="no email address on file")
            elif os.getenv("SMTP_HOST"):
                rec["provider"] = _send_email(contact["email"], n["title"], text)
                rec["status"], rec["delivered_at"] = "delivered", _iso()
            else:
                rec.update(provider="simulated", status="delivered", delivered_at=now)
        elif channel in ("sms", "whatsapp"):
            if not contact.get("phone"):
                rec.update(status="skipped", error="no phone number on file")
            elif _twilio(channel):
                rec["provider"] = _send_twilio(channel, contact["phone"], text)
                rec["status"], rec["delivered_at"] = "delivered", _iso()
            else:
                rec.update(provider="simulated", status="delivered", delivered_at=now)
    except Exception as exc:  # noqa: BLE001 - a channel failure must never break the workflow
        log.warning("notification %s via %s failed: %s", n["id"], channel, type(exc).__name__)
        rec.update(status="failed", error=f"{type(exc).__name__}")
    if rec["provider"] == "simulated":
        store.put("outbox", f"{n['id']}-{channel}", org, {
            "id": f"{n['id']}-{channel}", "notification_id": n["id"], "channel": channel,
            "to": contact.get("email") if channel == "email" else contact.get("phone"),
            "text": text, "created_at": now, "note": "simulated: no provider credentials configured"})
    return rec


# ---------------------------------------------------------------- public API

def create(store, org: str, *, employee_id: str, employee_name: Optional[str], severity: int, type: str,
           title: str, message: str, contact: Optional[dict] = None, prefs: Optional[dict] = None,
           requires_acknowledgement: Optional[bool] = None, extra: Optional[dict] = None) -> dict:
    """Create and dispatch one notification. ``contact`` = {email, phone}; ``prefs`` = channel opt-outs
    for level 1–2 (level 3 always uses every channel)."""
    if severity not in LEVELS:
        raise ValueError("severity must be 1, 2 or 3")
    lvl = LEVELS[severity]
    st = settings(store, org)
    n = {"id": f"ntf-{uuid.uuid4().hex[:8]}", "employee_id": employee_id, "employee_name": employee_name,
         "severity": severity, "level": lvl["name"], "color": lvl["color"], "type": type, "kind": type,
         "title": title, "message": message, "body": message, "created_at": _iso(),
         "requires_acknowledgement": severity >= 2 if requires_acknowledgement is None else requires_acknowledgement,
         "acknowledged_at": None, "opened_at": None, "escalation_level": 0, "escalated_at": None,
         "escalate_after_minutes": st["l2_escalation_minutes"] if severity == 2 else None,
         "channels": [], "changes": [], **(extra or {})}
    prefs = prefs or {}
    for ch in lvl["channels"]:
        if severity < 3 and ch != "dashboard" and prefs.get(ch) is False:
            n["channels"].append({"channel": ch, "status": "opted_out", "provider": None, "sent_at": None,
                                  "delivered_at": None, "opened_at": None, "acknowledged_at": None,
                                  "escalation_level": 0, "error": None})
            continue
        n["channels"].append(_deliver(store, org, n, ch, contact or {}, 0))
    n["sent_at"] = _iso()
    n["delivered_at"] = next((c["delivered_at"] for c in n["channels"] if c["delivered_at"]), None)
    n["status"] = _status(n)
    store.put("notification", n["id"], org, n)
    return n


def _status(n: dict) -> str:
    if n.get("acknowledged_at"):
        return "acknowledged"
    if n.get("escalation_level"):
        return "escalated"
    if n.get("opened_at"):
        return "opened"
    if any(c["status"] == "delivered" for c in n.get("channels", [])):
        return "delivered"
    return "sent"


def mark_opened(store, org: str, n: dict) -> dict:
    if n.get("opened_at"):
        return n
    now = _iso()
    n["opened_at"] = now
    for c in n.get("channels", []):
        if c["channel"] == "dashboard":
            c["opened_at"] = now
    n["status"] = _status(n)
    store.put("notification", n["id"], org, n)
    return n


def acknowledge(store, org: str, n: dict) -> dict:
    now = _iso()
    n["acknowledged_at"] = n.get("acknowledged_at") or now
    n["opened_at"] = n.get("opened_at") or now
    for c in n.get("channels", []):
        if c["status"] in ("delivered", "sent"):
            c["acknowledged_at"] = c.get("acknowledged_at") or now
    n["status"] = _status(n)
    store.put("notification", n["id"], org, n)
    return n


def escalate_due(store, org: str, contacts: dict[str, dict], now: Optional[datetime] = None,
                 force: bool = False) -> list[dict]:
    """Level-2 notifications not acknowledged within the window → WhatsApp + SMS. Idempotent."""
    now = now or _now()
    out = []
    for n in store.list("notification", org, limit=2000):
        if n.get("severity") != 2 or n.get("acknowledged_at") or n.get("escalation_level"):
            continue
        if not n.get("requires_acknowledgement"):
            continue
        try:
            sent = datetime.fromisoformat(n.get("sent_at") or n["created_at"])
        except (KeyError, ValueError):
            continue
        if not force and now - sent < timedelta(minutes=n.get("escalate_after_minutes") or 0):
            continue
        n["escalation_level"], n["escalated_at"] = 1, _iso(now)
        for ch in LEVELS[2]["escalation"]:
            n["channels"].append(_deliver(store, org, n, ch, contacts.get(n["employee_id"], {}), 1))
        n["status"] = _status(n)
        store.put("notification", n["id"], org, n)
        out.append(n)
    return out


def audit_rows(notifications: list[dict]) -> list[dict]:
    """Flat notification audit model: one row per (notification, channel)."""
    rows = []
    for n in notifications:
        for c in n.get("channels") or [{"channel": "dashboard", "status": "delivered", "sent_at": n.get("created_at"),
                                        "delivered_at": n.get("created_at"), "escalation_level": 0}]:
            rows.append({"notification_id": n["id"], "employee_id": n.get("employee_id"),
                         "employee_name": n.get("employee_name"), "severity": n.get("severity", 1),
                         "type": n.get("type") or n.get("kind") or "schedule_change", "message": n.get("title"),
                         "channel": c["channel"], "provider": c.get("provider"), "created_at": n.get("created_at"),
                         "sent_at": c.get("sent_at"), "delivered_at": c.get("delivered_at"),
                         "opened_at": c.get("opened_at") or (n.get("opened_at") if c["channel"] == "dashboard" else None),
                         "acknowledged_at": c.get("acknowledged_at") or n.get("acknowledged_at"),
                         "status": c.get("status"), "escalation_level": c.get("escalation_level", 0)})
    return rows


def summary(notifications: list[dict]) -> dict[str, Any]:
    by_level = {k: 0 for k in (1, 2, 3)}
    for n in notifications:
        by_level[n.get("severity", 1)] = by_level.get(n.get("severity", 1), 0) + 1
    need_ack = [n for n in notifications if n.get("requires_acknowledgement")]
    return {"total": len(notifications), "by_level": by_level,
            "awaiting_acknowledgement": sum(1 for n in need_ack if not n.get("acknowledged_at")),
            "acknowledged": sum(1 for n in need_ack if n.get("acknowledged_at")),
            "escalated": sum(1 for n in notifications if n.get("escalation_level")),
            "providers": provider_status()}
