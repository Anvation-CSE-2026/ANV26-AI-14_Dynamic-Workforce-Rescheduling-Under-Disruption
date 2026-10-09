"""HTTP API (FastAPI). Thin: every handler validates input, checks the role, calls the service layer.

Contract: docs/api-contract.md. Errors: {"error": message} with a meaningful status.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.validation import dataset_from_csv, validate_dataset
from services import demo_accounts, gemini_voice, voice, voice_agent
from services.auth import MANAGERS, AuthError, verify_token
from services.domains import demo_dataset, domain_config, domain_index, scenario_dataset, scenario_list
from services.workspace import ResQWorkError

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- dependencies

def app_state(request: Request):
    return request.app.state.resqwork, request.app.state.auth


class User(BaseModel):
    id: str
    role: str
    org: Optional[str] = None
    employee_id: Optional[str] = None
    name: Optional[str] = None
    sid: Optional[str] = None


# Paths a user who must change a temporary password can still call.
_PASSWORD_CHANGE_ALLOWED = ("/api/auth/change-password", "/api/auth/me", "/api/auth/logout", "/api/profile")


def current_user(request: Request, authorization: Optional[str] = Header(default=None)) -> User:
    if authorization and authorization.lower().startswith("bearer "):
        try:
            p = verify_token(authorization.split(" ", 1)[1])
            request.app.state.auth.check_session(p.get("sid"))
        except AuthError as exc:
            raise ResQWorkError(str(exc), exc.status) from exc
        user = User(id=p["sub"], role=p["role"], org=p.get("org"), employee_id=p.get("employee_id"), name=p.get("name"),
                    sid=p.get("sid"))
        # Organization isolation: the org comes from the user's own record (updated when they load a dataset),
        # never from whichever org another user loaded last. Role and status come from the record too.
        stored = request.app.state.store.get("user", user.id, "_global")
        if stored:
            if stored.get("status") == "inactive":
                raise ResQWorkError("This account is deactivated.", 403)
            user.role = stored.get("role", user.role)
            if stored.get("org"):
                user.org = stored["org"]
            if stored.get("must_change_password") and request.url.path not in _PASSWORD_CHANGE_ALLOWED:
                raise ResQWorkError("Please set a new password before continuing.", 403, code="PASSWORD_CHANGE_REQUIRED")
    elif request.app.state.auth_mode == "demo" and os.getenv("RESQWORK_ANONYMOUS_DEMO", "off").lower() in ("1", "on", "true"):
        # Unauthenticated demo mode only: act as a manager of the currently active demo org.
        user = User(id="demo-operations-manager", role="operations_manager", name="Demo Operations Manager")
        meta = request.app.state.store.get("meta", "active_org", "_global")
        user.org = meta["org"] if meta else None
    else:
        raise ResQWorkError("Sign in required", 401)
    return user


def manager(user: User = Depends(current_user)) -> User:
    """ADMIN / OPERATIONS (legacy manager roles map here; there is no separate manager dashboard)."""
    if user.role not in MANAGERS:
        raise ResQWorkError("Admin access required", 403)
    if not user.org:
        raise ResQWorkError("No organization loaded yet. Load a demo or upload a dataset.", 404)
    return user


def admin(user: User = Depends(current_user)) -> User:
    if user.role not in MANAGERS:
        raise ResQWorkError("Admin access required", 403)
    return user


def employee_self(user: User = Depends(current_user)) -> User:
    if user.role != "employee" or not user.employee_id:
        raise ResQWorkError("Employee access required", 403)
    if not user.org:
        raise ResQWorkError("No organization for this account.", 404)
    return user


def self_or_manager(employee_id: str, user: User = Depends(current_user)) -> User:
    if user.role not in MANAGERS and user.employee_id != employee_id:
        raise ResQWorkError("You can only access your own schedule", 403)
    return user


def _activate(request: Request, org: str) -> None:
    request.app.state.store.put("meta", "active_org", "_global", {"org": org})


# ---------------------------------------------------------------- domains & auth

@router.get("/domains")
def list_domains():
    return domain_index()


@router.get("/domains/{domain}")
def get_domain(domain: str):
    try:
        return domain_config(domain)
    except KeyError as exc:
        raise ResQWorkError(str(exc), 404) from exc


class Credentials(BaseModel):
    email: str
    password: str
    name: Optional[str] = None
    role: str = "operations_manager"


class DemoLogin(BaseModel):
    role: str = "operations_manager"
    domain: Optional[str] = None
    employee_id: Optional[str] = None
    reset: bool = False      # reload the demo dataset (wipes that demo's requests, repairs and schedules)


class GoogleLogin(BaseModel):
    id_token: str
    role: str = "operations_manager"


@router.post("/auth/register")
def register(body: Credentials, request: Request):
    _, auth = app_state(request)
    return _auth(lambda: auth.register(body.email, body.password, body.name or body.email, body.role))


@router.post("/auth/login")
def login(body: Credentials, request: Request):
    svc, auth = app_state(request)
    out = _auth(lambda: auth.login(body.email, body.password, request.headers.get("user-agent", "")))
    stored = request.app.state.store.get("user", out["user"]["id"], "_global") or {}
    if stored.get("demo_domain"):     # demo accounts always sign in to their own industry's demo organization
        org = _ensure_demo(svc, stored["demo_domain"], request)
        auth.set_org(out["user"]["id"], org)
        out["user"]["org"] = org
    return out


@router.get("/auth/demo-accounts")
def list_demo_accounts():
    """Documented demo credentials (only when demo accounts are enabled)."""
    return demo_accounts.public_list() if demo_accounts.enabled() else []


def _ensure_demo(svc, domain: str, request: Request, reset: bool = False) -> str:
    """Load an industry demo (or the flagship) once. Later logins reuse it, so data flows between users."""
    raw = demo_accounts.dataset_for(domain)
    org = raw["organization"]["id"]
    if reset or request.app.state.store.get("workspace", "current", org) is None:
        if domain == demo_accounts.FLAGSHIP:
            svc.load_dataset(raw, "flagship demo", actor="demo setup")
        else:
            svc.load_demo(domain, actor="demo setup")
    _activate(request, org)
    return org


@router.post("/auth/demo")
def demo_login(body: DemoLogin, request: Request):
    if not demo_accounts.enabled():
        raise ResQWorkError("Demo sign-in is disabled on this server.", 403)
    svc, auth = app_state(request)
    org = None
    if body.domain:
        if body.domain not in demo_accounts.keys():
            raise ResQWorkError(f"Unknown industry '{body.domain}'", 404)
        org = _ensure_demo(svc, body.domain, request, reset=body.reset)
    else:
        meta = request.app.state.store.get("meta", "active_org", "_global")
        org = meta and meta["org"]
    if body.role == "employee" and not body.employee_id and org:
        body.employee_id = svc.dataset(org).employees[0].id
    name = svc.dataset(org).employee(body.employee_id).name if (org and body.employee_id) else None
    return _auth(lambda: auth.demo(body.role, org, body.employee_id, name))


@router.post("/auth/google")
def google_login(body: GoogleLogin, request: Request):
    _, auth = app_state(request)
    return _auth(lambda: auth.google(body.id_token, body.role))


@router.get("/auth/me")
def me(request: Request, user: User = Depends(current_user)):
    stored = request.app.state.auth.public(user.id) or {}
    return {**user.model_dump(exclude={"sid"}), "must_change_password": bool(stored.get("must_change_password")),
            "avatar": stored.get("avatar"), "email": stored.get("email")}


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


@router.post("/auth/change-password")
def change_password(body: PasswordChange, request: Request, user: User = Depends(current_user)):
    _, auth = app_state(request)
    out = _auth(lambda: auth.change_password(user.id, body.current_password, body.new_password))
    if user.org:
        app_state(request)[0].audit(user.org, "PASSWORD_CHANGED", user.name or user.id, "Password changed.")
    return {"user": out}


class LogoutIn(BaseModel):
    everywhere: bool = False


@router.post("/auth/logout")
def logout(body: LogoutIn, request: Request, user: User = Depends(current_user)):
    return {"revoked": request.app.state.auth.logout(user.sid, user.id, body.everywhere)}


@router.get("/auth/sessions")
def sessions(request: Request, user: User = Depends(current_user)):
    return request.app.state.auth.sessions(user.id, user.sid)


def _auth(fn):
    try:
        return fn()
    except AuthError as exc:
        raise ResQWorkError(str(exc), exc.status) from exc


# ---------------------------------------------------------------- onboarding / datasets

@router.post("/datasets/validate")
def validate_json(raw: dict[str, Any]):
    report = validate_dataset(raw)
    return report.model_dump(mode="json")


@router.post("/datasets/validate-csv")
async def validate_csv(schedule_csv: UploadFile = File(...), employees_csv: Optional[UploadFile] = File(default=None),
                       organization: str = Form(..., description='JSON, e.g. {"name": "…", "domain": "healthcare"}')):
    try:
        org = json.loads(organization)
    except json.JSONDecodeError as exc:
        raise ResQWorkError(f"organization must be JSON: {exc}") from exc
    raw = dataset_from_csv((await schedule_csv.read()).decode("utf-8-sig"), org,
                           (await employees_csv.read()).decode("utf-8-sig") if employees_csv else None)
    report = validate_dataset(raw)
    return {"report": report.model_dump(mode="json"), "dataset": raw}


@router.post("/datasets/load")
def load_dataset(raw: dict[str, Any], request: Request, user: User = Depends(admin)):
    svc, auth = app_state(request)
    org = raw.get("organization") if isinstance(raw.get("organization"), dict) else None
    if org is not None and org.get("id") in (None, "", "org-demo"):
        # Real uploads get their own organization, so two admins never overwrite each other's data.
        import re as _re
        import uuid as _uuid
        slug = _re.sub(r"[^a-z0-9]+", "-", str(org.get("name") or "org").lower()).strip("-")[:24] or "org"
        org["id"] = f"{slug}-{_uuid.uuid4().hex[:6]}"
    report, ws = svc.load_dataset(raw, raw.get("source") or "upload", actor=user.name or user.id)
    if ws:
        _activate(request, ws["org"])
        auth.set_org(user.id, ws["org"])
    return {"report": report.model_dump(mode="json"), "workspace": ws and svc.workspace_summary(ws["org"])}


@router.post("/datasets/demo/{domain}")
def load_demo(domain: str, request: Request, user: User = Depends(admin)):
    svc, auth = app_state(request)
    report, ws = svc.load_demo(domain, actor=user.name or user.id)
    _activate(request, ws["org"])
    auth.set_org(user.id, ws["org"])
    return {"report": report.model_dump(mode="json"), "workspace": svc.workspace_summary(ws["org"])}


@router.get("/scenarios")
def scenarios():
    return scenario_list()


@router.post("/datasets/scenario/{name}")
def load_scenario(name: str, request: Request, user: User = Depends(admin)):
    svc, auth = app_state(request)
    try:
        raw = scenario_dataset(name)
    except KeyError as exc:
        raise ResQWorkError(str(exc), 404) from exc
    report, ws = svc.load_dataset(raw, f"scenario: {name}", actor=user.name or user.id)
    if ws:
        _activate(request, ws["org"])
        auth.set_org(user.id, ws["org"])
    return {"report": report.model_dump(mode="json"), "workspace": ws and svc.workspace_summary(ws["org"])}


@router.get("/workspace")
def workspace(request: Request, user: User = Depends(current_user)):
    svc, _ = app_state(request)
    if not user.org:
        raise ResQWorkError("No organization loaded yet.", 404)
    return svc.workspace_summary(user.org)


@router.get("/dashboard")
def dashboard(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].dashboard(user.org)


# ---------------------------------------------------------------- schedule & employees

@router.get("/employees")
def employees(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].employees(user.org)


@router.get("/schedule")
def schedule(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].schedule(user.org)


@router.get("/employees/{employee_id}/schedule")
def employee_schedule(employee_id: str, request: Request, user: User = Depends(self_or_manager)):
    return app_state(request)[0].employee_view(user.org, employee_id)


class AvailabilityIn(BaseModel):
    date: str
    start: Optional[str] = None
    end: Optional[str] = None
    reason: str = ""
    kind: str = "unavailable"


@router.post("/employees/{employee_id}/availability")
def employee_availability(employee_id: str, body: AvailabilityIn, request: Request,
                          user: User = Depends(self_or_manager)):
    return app_state(request)[0].submit_availability(user.org, employee_id, body.date, body.start, body.end,
                                                     body.reason, body.kind)


@router.get("/availability-requests")
def availability_requests(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].availability_requests(user.org)


class RequestDecision(BaseModel):
    status: str = Field(description="approved | rejected | needs_review")
    note: str = ""


@router.post("/availability-requests/{request_id}/decision")
def decide_request(request_id: str, body: RequestDecision, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].decide_request(user.org, request_id, body.status, body.note,
                                                actor=user.name or user.id)


@router.post("/availability-requests/{request_id}/accept")
def accept_request(request_id: str, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].accept_availability(user.org, request_id, actor=user.name or user.id)


@router.get("/employees/{employee_id}/recognition")
def employee_recognition(employee_id: str, request: Request, user: User = Depends(self_or_manager)):
    return app_state(request)[0].employee_recognition(user.org, employee_id)


@router.get("/recognition")
def recognition_overview(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].recognition_overview(user.org)


class RecognitionIn(BaseModel):
    employee_id: str
    category: str
    note: str


@router.post("/recognition")
def give_recognition(body: RecognitionIn, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].recognize(user.org, body.employee_id, body.category, body.note,
                                           actor=user.name or user.id)


@router.get("/employees/{employee_id}/notifications")
def employee_notifications(employee_id: str, request: Request, user: User = Depends(self_or_manager)):
    return app_state(request)[0].employee_view(user.org, employee_id)["notifications"]


@router.post("/notifications/{notification_id}/acknowledge")
def acknowledge(notification_id: str, request: Request, user: User = Depends(current_user)):
    svc, _ = app_state(request)
    n = svc.store.get("notification", notification_id, user.org)
    if not n:
        raise ResQWorkError("Unknown notification", 404)
    if user.role not in MANAGERS and user.employee_id != n["employee_id"]:
        raise ResQWorkError("Not your notification", 403)
    return svc.acknowledge(user.org, notification_id, n["employee_id"])


@router.get("/notifications")
def notifications(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].notifications(user.org)


# ---------------------------------------------------------------- disruptions & repair

class DisruptionIn(BaseModel):
    text: Optional[str] = Field(default=None, description="Natural language, e.g. 'Rahul is sick tomorrow 9 to 5'")
    structured: Optional[dict[str, Any]] = Field(default=None, description="{employee_id, date, start, end, reason}")
    preset_id: Optional[str] = Field(default=None, description="Demo 'Simulate disruption' preset")


@router.post("/disruptions")
def report_disruption(body: DisruptionIn, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].report_disruption(user.org, body.text, body.structured, body.preset_id,
                                                   actor=user.name or user.id)


@router.get("/disruptions")
def list_disruptions(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].store.list("disruption", user.org)


@router.post("/disruptions/{disruption_id}/dismiss")
def dismiss(disruption_id: str, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].dismiss_disruption(user.org, disruption_id, actor=user.name or user.id)


class RescheduleIn(BaseModel):
    disruption_ids: Optional[list[str]] = None


@router.get("/conflicts")
def conflicts(request: Request, user: User = Depends(manager)):
    """Hard-rule conflicts already in the schedule (double bookings, unqualified assignees, open shifts…)."""
    return app_state(request)[0].schedule_conflicts(user.org)


class ConflictsIn(BaseModel):
    conflict_ids: Optional[list[str]] = None


@router.post("/conflicts/resolve")
def resolve_conflicts(body: ConflictsIn, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].resolve_conflicts(user.org, body.conflict_ids, actor=user.name or user.id)


@router.post("/reschedule")
def reschedule(body: RescheduleIn, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].generate_repair(user.org, body.disruption_ids, actor=user.name or user.id)


@router.post("/reschedule/alternatives")
def alternatives(body: RescheduleIn, request: Request, user: User = Depends(manager)):
    p = app_state(request)[0].generate_repair(user.org, body.disruption_ids, actor=user.name or user.id)
    return {"proposal_id": p["id"], "options": p["result"]["options"], "comparison": p["comparison"]}


@router.get("/reschedule/latest")
def latest(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].latest_proposal(user.org)


@router.get("/reschedule/{proposal_id}")
def get_proposal(proposal_id: str, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].proposal(user.org, proposal_id)


class WhatIfIn(BaseModel):
    proposal_id: str
    text: Optional[str] = None
    spec: Optional[dict[str, Any]] = None


@router.post("/what-if")
def what_if(body: WhatIfIn, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].what_if(user.org, body.proposal_id, body.text, body.spec, actor=user.name or user.id)


class DecisionIn(BaseModel):
    proposal_id: str
    option_id: Optional[str] = None
    notes: str = ""
    reason: str = ""
    allow_partial: bool = False


@router.post("/reschedule/approve")
def approve(body: DecisionIn, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].approve(user.org, body.proposal_id, body.option_id, actor=user.name or user.id,
                                         notes=body.notes, allow_partial=body.allow_partial)


@router.post("/reschedule/reject")
def reject(body: DecisionIn, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].reject(user.org, body.proposal_id, actor=user.name or user.id,
                                        reason=body.reason or body.notes)


# ---------------------------------------------------------------- AI, feedback, policies

class TextIn(BaseModel):
    text: str


@router.post("/ai/interpret")
def interpret(body: TextIn, request: Request, user: User = Depends(manager)):
    """One command box: routes a manager message to disruption, what-if, feedback or policy lookup."""
    svc, _ = app_state(request)
    intent = svc.ai.router.classify(body.text)
    if intent.intent == "report_disruption":
        return {"intent": intent.model_dump(), "result": svc.report_disruption(user.org, text=body.text,
                                                                                actor=user.name or user.id)}
    if intent.intent == "what_if":
        p = svc.latest_proposal(user.org)
        if not p:
            raise ResQWorkError("Generate a repair first, then ask what-if questions.", 409)
        return {"intent": intent.model_dump(), "result": svc.what_if(user.org, p["id"], text=body.text,
                                                                      actor=user.name or user.id)}
    if intent.intent == "manager_feedback":
        return {"intent": intent.model_dump(), "result": svc.add_feedback(user.org, body.text, user.name or user.id)}
    if intent.intent == "policy_question":
        return {"intent": intent.model_dump(), "result": svc.policy_search(user.org, body.text)}
    return {"intent": intent.model_dump(), "result": None,
            "message": "Try a disruption, a what-if, feedback, or a policy question."}


@router.post("/feedback")
def feedback(body: TextIn, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].add_feedback(user.org, body.text, actor=user.name or user.id)


@router.get("/feedback")
def list_feedback(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].feedback(user.org)


@router.get("/policies")
def policies(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].policy_overview(user.org)


@router.get("/policies/search")
def policy_search(q: str, request: Request, user: User = Depends(current_user)):
    return app_state(request)[0].policy_search(user.org, q)


@router.post("/policies")
async def upload_policy(request: Request, file: UploadFile = File(...), user: User = Depends(admin)):
    text = (await file.read()).decode("utf-8-sig")
    return app_state(request)[0].upload_policy(user.org, file.filename or "policy.md", text, actor=user.name or user.id)


# ---------------------------------------------------------------- versions, audit, analytics

@router.get("/versions")
def versions(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].versions(user.org)


@router.get("/versions/{version_id}")
def version(version_id: str, request: Request, user: User = Depends(manager)):
    return app_state(request)[0].version(user.org, version_id)


@router.get("/audit")
def audit(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].audit_trail(user.org)


@router.get("/analytics")
def analytics(request: Request, user: User = Depends(manager)):
    return app_state(request)[0].analytics(user.org)


# ---------------------------------------------------------------- voice agent

class VoiceIn(BaseModel):
    utterance: str
    speak: bool = False


@router.get("/voice/alert")
def voice_alert(request: Request, user: User = Depends(manager)):
    svc, _ = app_state(request)
    ws = svc.workspace_summary(user.org)
    open_d = [r for r in svc.store.list("disruption", user.org) if r["status"] == "open"]
    if open_d:
        text = voice.manager_alert(ws["domain"], open_d[0])
    else:
        text = voice.ops_summary(ws["domain"], svc.dashboard(user.org)["metrics"])
    return {"text": text, "audio": voice.tts(text)}


@router.get("/voice/status")
def voice_status(user: User = Depends(current_user)):
    """Which speech path is live: Gemini (server key set) or browser speech / typing only."""
    return {"gemini": gemini_voice.configured(), "model": gemini_voice.model_name() if gemini_voice.configured() else None,
            "server_tts": bool(os.getenv("ELEVENLABS_API_KEY"))}


def _voice_reply(svc, user: User, utterance: str, intent: Optional[str], employee: Optional[str], speak: bool,
                 understood_by: str) -> dict:
    out = voice_agent.handle(svc, user.org, user.name or user.id, utterance, intent, employee)
    svc.store.put("voice_log", f"v{len(svc.store.list('voice_log', user.org)) + 1}", user.org,
                  {"utterance": utterance, "intent": out["intent"], "reply": out["text"], "via": understood_by})
    return {**out, "transcript": utterance, "understood_by": understood_by,
            "audio": voice.tts(out["text"]) if speak else None}


@router.post("/voice")
def voice_command(body: VoiceIn, request: Request, user: User = Depends(manager)):
    """Typed or browser-transcribed command → the same actions as the UI. Never optimizes or invents."""
    svc, _ = app_state(request)
    intent, employee = voice_agent.detect(body.utterance)
    via = "rules"
    if intent == "unknown" and gemini_voice.configured():
        try:
            g = gemini_voice.understand(text=body.utterance)
            intent, employee, via = g["intent"], g["employee"], f"gemini ({g['model']})"
        except gemini_voice.VoiceUnavailable:
            pass                                    # keep the rule-based answer (help text)
    return _voice_reply(svc, user, body.utterance, intent, employee, body.speak, via)


@router.post("/voice/audio")
async def voice_audio(request: Request, audio: UploadFile = File(...), speak: bool = Form(default=False),
                      user: User = Depends(manager)):
    """Recorded speech → Gemini transcript + intent → answer from ResQWork data. 503 if Gemini isn't available."""
    svc, _ = app_state(request)
    data = await audio.read()
    try:
        g = gemini_voice.understand(audio=data, mime=audio.content_type or "audio/webm")
    except gemini_voice.VoiceUnavailable as exc:
        raise ResQWorkError(str(exc), 503) from exc
    rule_intent, rule_emp = voice_agent.detect(g["transcript"])
    intent = g["intent"] if g["intent"] != "unknown" else rule_intent
    return _voice_reply(svc, user, g["transcript"], intent, g["employee"] or rule_emp, speak, f"gemini ({g['model']})")


class TTSIn(BaseModel):
    text: str


@router.post("/voice/tts")
def tts(body: TTSIn, user: User = Depends(current_user)):
    return {"text": body.text, "audio": voice.tts(body.text)}


# =================================================================== admin & employee operations
#
# Every handler: validate input (Pydantic), enforce the role on the server, call the service layer.

def _svc(request: Request):
    return request.app.state.resqwork


def _actor(user: User) -> str:
    return user.name or user.id


def _emails(request: Request) -> set[str]:
    return {u["id"] for u in request.app.state.store.list("user", "_global", limit=100000)}


async def _read_upload(file: UploadFile, limit_mb: int = 5) -> bytes:
    data = await file.read()
    if len(data) > limit_mb * 1024 * 1024:
        raise ResQWorkError(f"File is larger than {limit_mb} MB.", 413)
    if not data:
        raise ResQWorkError("The file is empty.")
    return data


def _download(data: bytes, filename: str, media: str) -> Response:
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------- system

@router.get("/system/solver")
def solver_status(user: User = Depends(current_user)):
    """Verified optimizer status (runs a CP-SAT self-test once per process)."""
    from engine import solver_cpsat
    return solver_cpsat.status()


# ---------------------------------------------------------------- profile (admin and employee)

class ProfilePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    phone: Optional[str] = Field(default=None, max_length=24)
    avatar: Optional[str] = Field(default=None, max_length=400_000)
    notification_preferences: Optional[dict[str, bool]] = None


@router.get("/profile")
def get_profile(request: Request, user: User = Depends(current_user)):
    svc, auth = app_state(request)
    me = auth.public(user.id) or {"id": user.id, "name": user.name, "role": user.role}
    out: dict[str, Any] = {"user": me, "role_label": "Employee" if user.role == "employee" else "Admin / Operations",
                           "sessions": auth.sessions(user.id, user.sid), "organization": None, "employee": None}
    if user.org and svc.store.get("workspace", "current", user.org):
        ws = svc.workspace_summary(user.org)
        out["organization"] = ws["organization"]
        if user.employee_id:
            e = svc.dataset(user.org).employee(user.employee_id)
            if e:
                prof = svc.store.get("profile", e.id, user.org) or {}
                r = svc.employee_rewards(user.org, e.id)
                out["employee"] = {**e.model_dump(exclude={"history"}), "phone": prof.get("phone") or e.phone,
                                   "points": r["points_total"], "points_90d": r["points_90d"],
                                   "tier": r["tier"], "badges": r["badges"],
                                   "availability": [a.model_dump() for a in svc.dataset(user.org).availability
                                                    if a.employee_id == e.id][:20]}
    return out


@router.patch("/profile")
def patch_profile(body: ProfilePatch, request: Request, user: User = Depends(current_user)):
    import re as _re
    svc, auth = app_state(request)
    patch = body.model_dump(exclude_none=True)
    if "phone" in patch and patch["phone"] and not _re.match(r"^\+?[0-9 ()-]{7,20}$", patch["phone"]):
        raise ResQWorkError("phone is not valid")
    if "avatar" in patch and patch["avatar"] and not _re.match(r"^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$",
                                                               patch["avatar"]):
        raise ResQWorkError("avatar must be a PNG, JPEG, WebP or GIF image")
    if "notification_preferences" in patch:
        patch["notification_preferences"] = {k: bool(v) for k, v in patch["notification_preferences"].items()
                                             if k in ("email", "sms", "whatsapp")}
    if "name" in patch:
        patch["name"] = patch["name"].strip()
    before = {k: (auth.get(user.id) or {}).get(k) for k in patch if k != "avatar"}
    out = _auth(lambda: auth.update_profile(user.id, patch))
    if user.org and user.employee_id:
        prof = svc.store.get("profile", user.employee_id, user.org) or {}
        prof.update({k: v for k, v in patch.items() if k in ("phone", "notification_preferences")})
        svc.store.put("profile", user.employee_id, user.org, prof)
        if "name" in patch:
            svc.update_employee(user.org, user.employee_id, {"name": patch["name"]}, _actor(user))
    if user.org:
        svc.audit(user.org, "PROFILE_UPDATED", _actor(user), f"Profile updated: {', '.join(sorted(patch))}.",
                  previous=before, new={k: v for k, v in patch.items() if k != "avatar"})
    return {"user": out}


# ---------------------------------------------------------------- employee home & self-service

@router.get("/employees/{employee_id}/home")
def employee_home(employee_id: str, request: Request, user: User = Depends(self_or_manager)):
    return _svc(request).employee_home(user.org, employee_id)


@router.get("/employees/{employee_id}/rewards")
def employee_rewards(employee_id: str, request: Request, user: User = Depends(self_or_manager)):
    return _svc(request).employee_rewards(user.org, employee_id)


class RespondIn(BaseModel):
    action: str = Field(pattern="^(accept|decline|acknowledge)$")
    note: str = Field(default="", max_length=500)


@router.get("/admin-requests")
def list_admin_requests(request: Request, user: User = Depends(current_user)):
    if not user.org:
        raise ResQWorkError("No organization loaded yet.", 404)
    if user.role in MANAGERS:
        return _svc(request).admin_requests(user.org)
    return _svc(request).admin_requests(user.org, user.employee_id or "")


@router.post("/admin-requests/{request_id}/respond")
def respond_admin_request(request_id: str, body: RespondIn, request: Request, user: User = Depends(employee_self)):
    return _svc(request).respond_admin_request(user.org, request_id, user.employee_id, body.action, body.note)


class VolunteerIn(BaseModel):
    accept: bool = True


@router.post("/workforce-requests/{wid}/respond")
def volunteer_response(wid: str, body: VolunteerIn, request: Request, user: User = Depends(employee_self)):
    return _svc(request).volunteer(user.org, wid, user.employee_id, body.accept)


# ---------------------------------------------------------------- repair center & what-if

@router.get("/repair-center")
def repair_center(request: Request, include_hidden: bool = False, user: User = Depends(manager)):
    return _svc(request).repair_center(user.org, include_hidden)


@router.post("/repair-center/{proposal_id}/hide")
def hide_repair(proposal_id: str, request: Request, user: User = Depends(manager)):
    return _svc(request).set_repair_hidden(user.org, proposal_id, True, _actor(user))


@router.post("/repair-center/{proposal_id}/unhide")
def unhide_repair(proposal_id: str, request: Request, user: User = Depends(manager)):
    return _svc(request).set_repair_hidden(user.org, proposal_id, False, _actor(user))


@router.post("/repair-center/{proposal_id}/complete")
def complete_repair(proposal_id: str, request: Request, user: User = Depends(manager)):
    return _svc(request).complete_repair(user.org, proposal_id, _actor(user))


class SimulateIn(BaseModel):
    proposal_id: str
    action: dict[str, Any]


@router.post("/what-if/simulate")
def simulate(body: SimulateIn, request: Request, user: User = Depends(manager)):
    """Structured what-if. Never changes the schedule."""
    return _svc(request).simulate(user.org, body.proposal_id, body.action)


@router.get("/conflicts/assistant")
def conflict_assistant(request: Request, user: User = Depends(manager)):
    return _svc(request).conflict_assistant(user.org)


# ---------------------------------------------------------------- workforce

class WorkforceIn(BaseModel):
    task: str = Field(min_length=1, max_length=120)
    date: str
    start: str
    end: str
    required_employees: Optional[int] = Field(default=None, ge=1, le=200)
    additional_needed: int = Field(ge=1, le=50)
    department: Optional[str] = Field(default=None, max_length=80)
    skills: list[str] = Field(default_factory=list, max_length=20)
    certifications: list[str] = Field(default_factory=list, max_length=20)
    location: Optional[str] = Field(default=None, max_length=120)
    priority: str = Field(default="normal", pattern="^(critical|high|normal)$")
    reason: str = Field(default="", max_length=500)
    emergency: bool = False
    gap_id: Optional[str] = None


@router.get("/staffing-gaps")
def staffing_gaps(request: Request, user: User = Depends(manager)):
    return _svc(request).staffing_gaps(user.org)


@router.post("/workforce/find")
def find_employees(body: WorkforceIn, request: Request, user: User = Depends(manager)):
    return _svc(request).find_employees(user.org, body.model_dump())


@router.get("/workforce-requests")
def workforce_requests(request: Request, user: User = Depends(manager)):
    return _svc(request).workforce_requests(user.org)


@router.post("/workforce-requests")
def create_workforce_request(body: WorkforceIn, request: Request, user: User = Depends(manager)):
    return _svc(request).create_workforce_request(user.org, body.model_dump(), _actor(user))


@router.get("/workforce-requests/{wid}")
def get_workforce_request(wid: str, request: Request, user: User = Depends(manager)):
    return _svc(request).workforce_request(user.org, wid)


class ModeIn(BaseModel):
    mode: str = Field(default="volunteers", pattern="^(volunteers|broadcast|escalate)$")


@router.post("/workforce-requests/{wid}/volunteers")
def request_volunteers(wid: str, body: ModeIn, request: Request, user: User = Depends(manager)):
    return _svc(request).request_volunteers(user.org, wid, body.mode, _actor(user))


class EmployeeRef(BaseModel):
    employee_id: str = Field(min_length=1, max_length=40)


@router.post("/workforce-requests/{wid}/assign")
def assign_workforce(wid: str, body: EmployeeRef, request: Request, user: User = Depends(manager)):
    return _svc(request).assign_from_request(user.org, wid, body.employee_id, _actor(user))


class ApproveIn(BaseModel):
    approve: bool = True


@router.post("/workforce-requests/{wid}/volunteers/{employee_id}/decision")
def decide_volunteer(wid: str, employee_id: str, body: ApproveIn, request: Request, user: User = Depends(manager)):
    return _svc(request).decide_volunteer(user.org, wid, employee_id, body.approve, _actor(user))


@router.post("/workforce-requests/{wid}/assignments/{employee_id}/complete")
def complete_assignment(wid: str, employee_id: str, request: Request, user: User = Depends(manager)):
    return _svc(request).complete_workforce_assignment(user.org, wid, employee_id, _actor(user))


@router.post("/workforce-requests/{wid}/cancel")
def cancel_workforce(wid: str, request: Request, user: User = Depends(manager)):
    return _svc(request).cancel_workforce_request(user.org, wid, _actor(user))


# ---------------------------------------------------------------- admin requests

class AdminRequestIn(BaseModel):
    type: str = Field(default="general", max_length=40)
    title: str = Field(min_length=1, max_length=140)
    message: str = Field(default="", max_length=2000)
    target: dict[str, Any]
    severity: Optional[int] = Field(default=None, ge=1, le=3)
    due: Optional[str] = Field(default=None, max_length=20)


@router.post("/admin-requests")
def create_admin_request(body: AdminRequestIn, request: Request, user: User = Depends(manager)):
    return _svc(request).create_admin_request(user.org, body.model_dump(), _actor(user))


@router.post("/admin-requests/{request_id}/close")
def close_admin_request(request_id: str, request: Request, user: User = Depends(manager)):
    return _svc(request).close_admin_request(user.org, request_id, _actor(user))


# ---------------------------------------------------------------- notifications

@router.get("/notifications/audit")
def notification_audit(request: Request, user: User = Depends(manager)):
    from services import notify
    return notify.audit_rows(_svc(request).notifications(user.org))


@router.get("/notifications/summary")
def notification_summary(request: Request, user: User = Depends(manager)):
    from services import notify
    return notify.summary(_svc(request).notifications(user.org))


class EscalationSettings(BaseModel):
    l2_escalation_minutes: int = Field(ge=0, le=1440)


@router.get("/notifications/settings")
def get_notification_settings(request: Request, user: User = Depends(manager)):
    from services import notify
    return {**notify.settings(_svc(request).store, user.org), "providers": notify.provider_status(),
            "levels": notify.LEVELS, "future_channels": notify.FUTURE_CHANNELS}


@router.put("/notifications/settings")
def put_notification_settings(body: EscalationSettings, request: Request, user: User = Depends(manager)):
    from services import notify
    svc = _svc(request)
    before = notify.settings(svc.store, user.org)["l2_escalation_minutes"]
    out = notify.save_settings(svc.store, user.org, body.l2_escalation_minutes)
    svc.audit(user.org, "NOTIFICATION_SETTINGS_CHANGED", _actor(user), "Level-2 escalation window changed.",
              previous=before, new=body.l2_escalation_minutes)
    return out


class EscalateIn(BaseModel):
    force: bool = False


@router.post("/notifications/escalate")
def escalate(body: EscalateIn, request: Request, user: User = Depends(manager)):
    return {"escalated": _svc(request).run_escalations(user.org, force=body.force)}


# ---------------------------------------------------------------- employees: directory, edit, status, import

class EmployeePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    email: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=24)
    department: Optional[str] = Field(default=None, max_length=80)
    role: Optional[str] = Field(default=None, min_length=1, max_length=80)
    skills: Optional[list[str]] = Field(default=None, max_length=40)
    certifications: Optional[list[str]] = Field(default=None, max_length=40)
    location: Optional[str] = Field(default=None, max_length=120)
    max_daily_hours: Optional[float] = Field(default=None, gt=0, le=24)
    contracted_weekly_hours: Optional[float] = Field(default=None, gt=0, le=168)
    max_weekly_hours: Optional[float] = Field(default=None, gt=0, le=168)


@router.get("/employees/directory")
def employee_directory(request: Request, user: User = Depends(manager)):
    svc, auth = app_state(request)
    ds = svc.dataset(user.org)
    rows = svc.employee_directory(user.org)
    for r, e in zip(rows, ds.employees):
        login = svc.login_email(user.org, e)
        r["login"] = login if auth.get(login) else None
    return rows


@router.post("/employees/logins")
def create_employee_logins(request: Request, user: User = Depends(manager)):
    """Logins for every employee who doesn't have one yet (temporary passwords, downloadable once)."""
    svc, auth = app_state(request)
    return svc.create_employee_logins(user.org, auth, _actor(user))


@router.get("/fairness")
def fairness(request: Request, window: Optional[int] = None, user: User = Depends(manager)):
    from analytics import fairness_engine
    ds = _svc(request).dataset(user.org)
    if window is not None and not 1 <= window <= 365:
        raise ResQWorkError("window must be 1–365 days")
    return {"window_days": window or ds.constraints.fairness_window_days,
            "employees": fairness_engine.team_distribution(ds, window)}


class NewEmployee(BaseModel):
    employee_id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=120)
    phone: str = Field(min_length=7, max_length=24)
    department: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=80)
    skills: str = Field(min_length=1, max_length=400)
    certifications: str = Field(default="", max_length=400)
    availability_start: str = Field(default="", max_length=5)
    availability_end: str = Field(default="", max_length=5)
    max_hours: str = Field(default="", max_length=6)
    status: str = Field(default="active", pattern="^(active|inactive)$")


@router.post("/employees")
def add_employee(body: NewEmployee, request: Request, user: User = Depends(manager)):
    svc, auth = app_state(request)
    return svc.add_employee(user.org, body.model_dump(), auth, _emails(request), _actor(user))


@router.patch("/employees/{employee_id}")
def update_employee(employee_id: str, body: EmployeePatch, request: Request, user: User = Depends(manager)):
    return _svc(request).update_employee(user.org, employee_id, body.model_dump(exclude_none=True), _actor(user))


class StatusIn(BaseModel):
    status: str = Field(pattern="^(active|inactive)$")
    reason: str = Field(default="", max_length=300)


@router.post("/employees/{employee_id}/status")
def employee_status(employee_id: str, body: StatusIn, request: Request, user: User = Depends(manager)):
    svc = _svc(request)
    out = svc.set_employee_status(user.org, employee_id, body.status, _actor(user), body.reason)
    e = svc.dataset(user.org).employee(employee_id)
    if e and e.email:                                    # the login follows the employee record
        stored = request.app.state.store.get("user", e.email.lower(), "_global")
        if stored and stored.get("org") == user.org:
            request.app.state.auth.update_profile(stored["id"], {"status": body.status})
            if body.status == "inactive":
                request.app.state.auth.logout(None, stored["id"], everywhere=True)
    return out


@router.post("/employees/{employee_id}/reset-password")
def reset_password(employee_id: str, request: Request, user: User = Depends(manager)):
    svc, auth = app_state(request)
    try:
        return svc.reset_employee_password(user.org, employee_id, auth, _actor(user))
    except AuthError as exc:
        raise ResQWorkError(str(exc), exc.status) from exc


@router.post("/employees/import/preview")
async def preview_employee_import(request: Request, file: UploadFile = File(...), user: User = Depends(manager)):
    data = await _read_upload(file)
    return _svc(request).preview_employee_import(user.org, file.filename or "employees.csv", data, _emails(request),
                                                 _actor(user))


@router.post("/employees/import/{job_id}/confirm")
def confirm_employee_import(job_id: str, request: Request, user: User = Depends(manager)):
    svc, auth = app_state(request)
    return svc.confirm_employee_import(user.org, job_id, auth, _emails(request), _actor(user))


@router.post("/credentials/{token}")
def download_credentials(token: str, request: Request, user: User = Depends(manager)):
    """One-time temporary-password workbook. POST so it is never cached, prefetched or logged as a URL visit."""
    data = _svc(request).take_credentials(token)
    _svc(request).audit(user.org, "CREDENTIALS_EXPORTED", _actor(user), "Temporary-password workbook downloaded (once).")
    return _download(data, "resqwork-temporary-passwords.xlsx",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/templates/{name}")
def template(name: str):
    from services import constraint_center, importers
    stem, _, fmt = name.rpartition(".")
    if stem in ("employees", "schedule") and fmt in ("csv", "xlsx"):
        data, filename, media = importers.template(stem, fmt)
        return _download(data, filename, media)
    if stem in ("sample-schedule", "sample-employees") and fmt == "csv":     # onboarding example files
        from services.domains import SHARED
        path = SHARED / "samples" / f"{stem.split('-')[1]}.csv"
        return _download(path.read_bytes(), f"resqwork-{stem}.csv", "text/csv")
    if stem == "constraints" and fmt == "csv":
        return _download(constraint_center.template_csv().encode(), "resqwork-constraints-template.csv", "text/csv")
    if stem == "constraints" and fmt == "json":
        return _download(constraint_center.template_json().encode(), "resqwork-constraints-template.json",
                         "application/json")
    raise ResQWorkError("Unknown template. Use employees|schedule (.csv/.xlsx) or constraints (.csv/.json).", 404)


@router.post("/schedule/import/preview")
async def preview_schedule_import(request: Request, file: UploadFile = File(...), user: User = Depends(manager)):
    data = await _read_upload(file)
    return _svc(request).preview_schedule_import(user.org, file.filename or "schedule.csv", data, _actor(user))


class ScheduleConfirm(BaseModel):
    include_warnings: bool = False


@router.post("/schedule/import/{job_id}/confirm")
def confirm_schedule_import(job_id: str, body: ScheduleConfirm, request: Request, user: User = Depends(manager)):
    return _svc(request).confirm_schedule_import(user.org, job_id, body.include_warnings, _actor(user))


# ---------------------------------------------------------------- constraint center

class ConstraintPatch(BaseModel):
    value: Optional[float] = None
    weight: Optional[float] = Field(default=None, ge=0, le=1000)
    enabled: Optional[bool] = None
    rule: Optional[str] = Field(default=None, max_length=200)
    priority: Optional[str] = Field(default=None, pattern="^(HIGH|MEDIUM|LOW)$")


@router.get("/constraints")
def constraints(request: Request, user: User = Depends(manager)):
    return _svc(request).constraints(user.org)


@router.patch("/constraints/{constraint_id}")
def patch_constraint(constraint_id: str, body: ConstraintPatch, request: Request, user: User = Depends(manager)):
    return _svc(request).update_constraint(user.org, constraint_id, body.model_dump(exclude_none=True), _actor(user))


@router.delete("/constraints/{constraint_id}")
def delete_constraint(constraint_id: str, request: Request, user: User = Depends(manager)):
    return _svc(request).remove_constraint(user.org, constraint_id, _actor(user))


@router.post("/constraints/import")
async def import_constraints(request: Request, file: UploadFile = File(...), apply: bool = Form(default=False),
                             user: User = Depends(manager)):
    data = await _read_upload(file, 1)
    return _svc(request).import_constraints(user.org, file.filename or "constraints.csv", data, apply, _actor(user))


@router.post("/constraints/test")
def test_constraints(request: Request, user: User = Depends(manager)):
    return _svc(request).test_constraints(user.org)


# ---------------------------------------------------------------- rewards & recognition

@router.get("/rewards")
def rewards_overview(request: Request, user: User = Depends(manager)):
    return _svc(request).rewards_overview(user.org)


class RewardRules(BaseModel):
    rules: list[dict[str, Any]] = Field(max_length=30)


@router.put("/rewards/config")
def reward_config(body: RewardRules, request: Request, user: User = Depends(manager)):
    return _svc(request).save_reward_config(user.org, body.rules, _actor(user))


@router.post("/rewards/eligibility/{eligibility_id}/complete")
def complete_eligibility(eligibility_id: str, request: Request, user: User = Depends(manager)):
    return _svc(request).complete_eligibility(user.org, eligibility_id, _actor(user))


@router.post("/rewards/eligibility/{eligibility_id}/approve")
def approve_reward(eligibility_id: str, request: Request, user: User = Depends(manager)):
    return _svc(request).approve_reward(user.org, eligibility_id, _actor(user))


class AwardIn(BaseModel):
    employee_id: str = Field(min_length=1, max_length=40)
    trigger: str = Field(pattern="^(team_contribution|exceptional_performance)$")
    note: str = Field(min_length=1, max_length=300)


@router.post("/rewards/award")
def give_reward(body: AwardIn, request: Request, user: User = Depends(manager)):
    return _svc(request).give_reward(user.org, body.employee_id, body.trigger, body.note, _actor(user))
