"""Authentication & role-based access.

* Email/password: PBKDF2-SHA256 (200k rounds, per-user salt), stored in the document store.
* Tokens: HMAC-SHA256 signed, expiring, stdlib only (``RESQWORK_SECRET``).
* Google sign-in: verifies a Google ID token when ``GOOGLE_CLIENT_ID`` is set and
  ``google-auth`` is installed; otherwise the endpoint reports it is disabled.
* Demo login: one click per role for judges; creates the user on the fly.

Roles shown in the product: ADMIN / OPERATIONS and EMPLOYEE. ``operations_manager`` and
``department_manager`` are kept only so older tokens and accounts keep working; they get the admin
experience (there is no separate manager dashboard).
Organization isolation: every token carries ``org``; services scope every
read and write by it.

Sessions: every login creates a server-side session (``sid`` in the token). Logout revokes it, the
profile page lists active sessions, and a revoked or expired session is rejected even if the token's
signature is valid. Accounts created by an admin (bulk import) carry ``must_change_password``: the API
refuses everything except changing the password until the user has done so.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Optional

log = logging.getLogger("resqwork.auth")

ROLES = ("admin", "operations_manager", "department_manager", "employee")
MANAGERS = {"admin", "operations_manager", "department_manager"}      # all get the ADMIN / OPERATIONS experience
PUBLIC_FIELDS = ("id", "email", "name", "role", "org", "employee_id", "provider", "phone", "avatar", "status",
                 "created_at", "last_login", "must_change_password", "notification_preferences", "department")
GLOBAL = "_global"
TOKEN_TTL_S = 12 * 3600

_SECRET = os.getenv("RESQWORK_SECRET") or ""
if not _SECRET:
    _SECRET = secrets.token_hex(32)
    log.warning("RESQWORK_SECRET not set; using a random per-process secret (tokens reset on restart)")


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"pbkdf2${salt}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, _ = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def password_problem(password: str) -> Optional[str]:
    if len(password) < 8:
        return "password must be at least 8 characters"
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "password must contain letters and digits"
    return None


def issue_token(user: dict, sid: Optional[str] = None) -> str:
    payload = {"sub": user["id"], "email": user.get("email"), "name": user.get("name"), "role": user["role"],
               "org": user.get("org"), "employee_id": user.get("employee_id"), "exp": int(time.time()) + TOKEN_TTL_S}
    if sid:
        payload["sid"] = sid
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_SECRET.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str) -> dict:
    try:
        body, sig = token.split(".")
    except ValueError as exc:
        raise AuthError("Malformed token") from exc
    expected = _b64(hmac.new(_SECRET.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise AuthError("Invalid token")
    payload = json.loads(_unb64(body))
    if payload.get("exp", 0) < time.time():
        raise AuthError("Token expired")
    return payload


class AuthService:
    def __init__(self, store) -> None:
        self.store = store

    def _public(self, u: dict) -> dict:
        return {k: u.get(k) for k in PUBLIC_FIELDS if k in u}

    # ------------------------------------------------------------ sessions

    def _session(self, user: dict, user_agent: str = "") -> str:
        sid = secrets.token_urlsafe(12)
        now = int(time.time())
        self.store.put("session", sid, GLOBAL, {"sid": sid, "user_id": user["id"], "created_at": now,
                                                 "last_seen": now, "user_agent": (user_agent or "")[:160],
                                                 "revoked": False})
        return sid

    def _issue(self, user: dict, user_agent: str = "") -> dict:
        user["last_login"] = int(time.time())
        self.store.put("user", user["id"], GLOBAL, user)
        return {"user": self._public(user), "token": issue_token(user, self._session(user, user_agent))}

    def check_session(self, sid: Optional[str]) -> None:
        if not sid:
            return
        s = self.store.get("session", sid, GLOBAL)
        if not s or s.get("revoked"):
            raise AuthError("Your session has ended. Please sign in again.")
        now = int(time.time())
        if now - s.get("last_seen", 0) > 60:
            s["last_seen"] = now
            self.store.put("session", sid, GLOBAL, s)

    def sessions(self, user_id: str, current: Optional[str] = None) -> list[dict]:
        rows = [s for s in self.store.list("session", GLOBAL, limit=5000)
                if s["user_id"] == user_id and not s.get("revoked") and time.time() - s["created_at"] < TOKEN_TTL_S]
        return [{**{k: s[k] for k in ("sid", "created_at", "last_seen", "user_agent")}, "current": s["sid"] == current}
                for s in rows]

    def logout(self, sid: Optional[str], user_id: str, everywhere: bool = False) -> int:
        n = 0
        for s in self.store.list("session", GLOBAL, limit=5000):
            if s["user_id"] == user_id and not s.get("revoked") and (everywhere or s["sid"] == sid):
                s["revoked"] = True
                self.store.put("session", s["sid"], GLOBAL, s)
                n += 1
        return n

    # ------------------------------------------------------------ accounts

    def get(self, user_id: str) -> Optional[dict]:
        return self.store.get("user", user_id, GLOBAL)

    def public(self, user_id: str) -> Optional[dict]:
        u = self.get(user_id)
        return self._public(u) if u else None

    def create_employee_account(self, email: str, password: str, name: str, org: str, employee_id: str,
                                reset: bool = False) -> dict:
        """Admin-created login with a temporary password (hashed; must be changed at first login)."""
        email = email.strip().lower()
        existing = self.store.get("user", email, GLOBAL)
        if existing and not reset:
            raise AuthError("an account with this email already exists", 409)
        if reset and not existing:
            raise AuthError("no account for this employee yet", 404)
        user = existing or {"id": email, "email": email, "name": name, "role": "employee", "org": org,
                            "employee_id": employee_id, "provider": "password", "created_at": int(time.time()),
                            "status": "active"}
        user.update(password=hash_password(password), must_change_password=True)
        self.store.put("user", email, GLOBAL, user)
        if reset:
            self.logout(None, email, everywhere=True)
        return self._public(user)

    def change_password(self, user_id: str, current: str, new: str) -> dict:
        user = self.store.get("user", user_id, GLOBAL)
        if not user or not user.get("password"):
            raise AuthError("This account signs in without a password (demo or Google).", 400)
        if not check_password(current, user["password"]):
            raise AuthError("Current password is incorrect", 400)
        problem = password_problem(new)
        if problem:
            raise AuthError(problem, 400)
        if check_password(new, user["password"]):
            raise AuthError("Choose a new password that differs from the current one", 400)
        user["password"], user["must_change_password"] = hash_password(new), False
        user["password_changed_at"] = int(time.time())
        self.store.put("user", user_id, GLOBAL, user)
        return self._public(user)

    def update_profile(self, user_id: str, patch: dict) -> dict:
        user = self.store.get("user", user_id, GLOBAL)
        if not user:
            raise AuthError("Unknown user", 404)
        for k, v in patch.items():
            user[k] = v
        self.store.put("user", user_id, GLOBAL, user)
        return self._public(user)

    def register(self, email: str, password: str, name: str, role: str = "operations_manager",
                 org: Optional[str] = None, employee_id: Optional[str] = None) -> dict:
        email = email.strip().lower()
        if role not in ROLES:
            raise AuthError(f"role must be one of {', '.join(ROLES)}", 400)
        if len(password) < 8:
            raise AuthError("password must be at least 8 characters", 400)
        if self.store.get("user", email, GLOBAL):
            raise AuthError("an account with this email already exists", 409)
        user = {"id": email, "email": email, "name": name, "role": role, "org": org, "employee_id": employee_id,
                "password": hash_password(password), "provider": "password", "created_at": int(time.time()),
                "status": "active"}
        self.store.put("user", email, GLOBAL, user)
        return self._issue(user)

    def login(self, email: str, password: str, user_agent: str = "") -> dict:
        user = self.store.get("user", email.strip().lower(), GLOBAL)
        if not user or not user.get("password") or not check_password(password, user["password"]):
            raise AuthError("Incorrect email or password")
        if user.get("status") == "inactive":
            raise AuthError("This account is deactivated. Contact your admin.", 403)
        return self._issue(user, user_agent)

    def demo(self, role: str, org: str, employee_id: Optional[str] = None, name: Optional[str] = None) -> dict:
        if role not in ROLES:
            raise AuthError(f"role must be one of {', '.join(ROLES)}", 400)
        uid = f"demo-{role}-{org}" + (f"-{employee_id}" if employee_id else "")
        user = self.store.get("user", uid, GLOBAL) or {"created_at": int(time.time())}
        user.update({"id": uid, "email": f"{uid}@demo.resqwork.app", "role": role, "org": org, "employee_id": employee_id,
                "name": name or {"admin": "Demo Admin", "operations_manager": "Demo Operations Manager",
                                 "department_manager": "Demo Department Manager", "employee": "Demo Employee"}[role],
                "provider": "demo", "status": "active"})
        return self._issue(user)

    def google(self, id_token: str, role: str = "operations_manager", org: Optional[str] = None) -> dict:
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        if not client_id:
            raise AuthError("Google sign-in is not configured (set GOOGLE_CLIENT_ID).", 501)
        try:
            from google.auth.transport import requests as g_requests  # noqa: PLC0415
            from google.oauth2 import id_token as g_id_token  # noqa: PLC0415
        except ImportError as exc:
            raise AuthError("Google sign-in needs `pip install google-auth`.", 501) from exc
        try:
            info = g_id_token.verify_oauth2_token(id_token, g_requests.Request(), client_id)
        except ValueError as exc:
            raise AuthError(f"Invalid Google token: {exc}") from exc
        email = info["email"].lower()
        user = self.store.get("user", email, GLOBAL) or {
            "id": email, "email": email, "name": info.get("name", email), "role": role, "org": org,
            "employee_id": None, "provider": "google", "created_at": int(time.time())}
        return self._issue(user)

    def set_org(self, user_id: str, org: str) -> None:
        u = self.store.get("user", user_id, GLOBAL)
        if u:
            u["org"] = org
            self.store.put("user", user_id, GLOBAL, u)
