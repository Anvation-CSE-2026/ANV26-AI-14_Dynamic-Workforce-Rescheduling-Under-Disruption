"""ResQWork API server.

Run (from backend/):
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8000

Env:
    DATABASE_URL          sqlite:///./resqwork.db (default) | postgresql+psycopg://… (e.g. Supabase)
    RESQWORK_AUTH_MODE    demo (default: unauthenticated requests act as a demo manager) | required
    RESQWORK_SECRET       token signing secret
    RESQWORK_LLM_PROVIDER claude | openai | gemini | none     (+ ANTHROPIC_API_KEY …)
    ELEVENLABS_API_KEY    optional server-side voice
    GOOGLE_CLIENT_ID      optional Google sign-in
    CORS_ORIGINS          comma-separated (default *)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ai.service import AIService
from engine import solver_cpsat
from services import demo_accounts
from services.auth import AuthService
from services.workspace import ResQWork, ResQWorkError
from store import make_store

from .api.routes import router

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="ResQWork API",
              description="Workforce schedule repair: one engine, many industries. "
                          "AI interprets, CP-SAT decides, managers approve.",
              version="2.0.0")

app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

store = make_store()
app.state.store = store
app.state.resqwork = ResQWork(store, AIService.from_env())
app.state.auth = AuthService(store)
app.state.auth_mode = os.getenv("RESQWORK_AUTH_MODE", "demo")
if demo_accounts.enabled():
    demo_accounts.seed(store)


@app.exception_handler(ResQWorkError)
async def resqwork_error(_: Request, exc: ResQWorkError):
    body = {"error": str(exc)}
    if getattr(exc, "code", None):
        body["code"] = exc.code
    return JSONResponse(status_code=exc.status, content=body)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    errs = exc.errors()
    first = errs[0] if errs else {}
    where = ".".join(str(x) for x in first.get("loc", []) if x not in ("body", "query", "path"))
    return JSONResponse(status_code=422, content={"error": f"Invalid input{f' ({where})' if where else ''}: "
                                                           f"{first.get('msg', 'check the form')}",
                                                  "fields": [{"field": ".".join(str(x) for x in e.get("loc", [])),
                                                              "message": e.get("msg")} for e in errs[:10]]})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    # Never leak stack traces or data to the client; log the type and path only.
    logging.getLogger("resqwork").error("unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path,
                                        exc_info=os.getenv("LOG_TRACEBACKS") == "1")
    return JSONResponse(status_code=500, content={"error": "Something went wrong on our side. Please try again."})


@app.get("/health")
def health():
    ai = app.state.resqwork.ai
    return {"status": "ok", "solver": solver_cpsat.status()["engine"], "cp_sat": solver_cpsat.status(),
            "llm": ai.provider.name if ai.provider else "none (rule-based fallbacks)",
            "auth_mode": app.state.auth_mode}


app.include_router(router)

_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):     # unknown API path: JSON 404, never the HTML page
            return JSONResponse(status_code=404, content={"error": f"Unknown API endpoint /{path}"})
        target = _dist / path
        return FileResponse(target if path and target.is_file() else _dist / "index.html")
