"""Gemini speech understanding for the voice assistant.

One ``generateContent`` call takes the manager's recorded audio (or typed text) and returns JSON:
the transcript plus the ResQWork intent. Gemini only *understands* the request. The answer always
comes from ResQWork's own data (``services/voice_agent.py``), so the assistant can't invent schedule facts.

Configuration (server-side only; the key never reaches the browser):
    GEMINI_API_KEY (or GOOGLE_API_KEY)
    RESQWORK_GEMINI_VOICE_MODEL   default "gemini-3.8-flash" (Google's documented audio-capable model)

Uses the public REST endpoint ``v1beta/models/{model}:generateContent`` through urllib, so no SDK is required.
Every failure raises ``VoiceUnavailable`` with a message the UI can show next to its text fallback.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Callable, Optional

from ai.providers.json_repair import extract_json_object

DEFAULT_MODEL = "gemini-3.8-flash"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_AUDIO_BYTES = 15 * 1024 * 1024          # inline requests are capped at 20 MB in total
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/mp3", "audio/mpeg", "audio/aac", "audio/flac",
               "audio/m4a", "audio/mp4", "audio/opus", "audio/aiff"}

INTENTS = {
    "today_schedule": "show today's schedule / who is working today",
    "disruptions": "show today's or current disruptions / absences / what happened",
    "unresolved": "unresolved conflicts or constraints, impossible shifts, what can't be covered",
    "why_reassigned": "why was a specific person reassigned or chosen (put the person in 'employee')",
    "latest_changes": "what changed in the latest repair / latest published schedule",
    "affected_employees": "which employees are affected",
    "recommend": "what is the recommended repair",
    "alternatives": "what are the alternatives / other options",
    "why_not": "why NOT a specific person (put the person in 'employee')",
    "requests": "pending employee requests",
    "approve": "approve the recommended repair",
    "reject": "reject the repair",
    "status": "general status / coverage summary",
    "unknown": "anything else",
}

PROMPT = """You are the speech front-end of ResQWork, a workforce schedule-repair product.
{task}
Classify the request into exactly one intent:
{intents}
If the request names a person, copy the name exactly as said into "employee".
Answer with ONE JSON object: {{"transcript": "<what was said>", "intent": "<intent>", "employee": "<name or empty>"}}.
Do not answer the question yourself."""


class VoiceUnavailable(Exception):
    pass


def configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def model_name() -> str:
    return os.getenv("RESQWORK_GEMINI_VOICE_MODEL") or DEFAULT_MODEL


def _post(url: str, body: dict, key: str, timeout: float = 25) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 - fixed https endpoint
        return json.loads(resp.read().decode())


def understand(*, audio: Optional[bytes] = None, mime: str = "audio/webm", text: Optional[str] = None,
               post: Callable[[str, dict, str], dict] = _post) -> dict:
    """→ {"transcript", "intent", "employee", "model"}. ``post`` is injectable for tests."""
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise VoiceUnavailable("Gemini voice is not configured (set GEMINI_API_KEY on the server).")
    if audio is None and not text:
        raise VoiceUnavailable("Nothing to understand.")
    parts: list[dict] = []
    if audio is not None:
        mime = (mime or "audio/webm").split(";")[0].strip().lower()
        if mime not in AUDIO_TYPES:
            raise VoiceUnavailable(f"Unsupported audio type {mime}.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise VoiceUnavailable("That recording is too long; please keep commands short.")
        if len(audio) < 800:
            raise VoiceUnavailable("I didn't catch anything. Hold the mic button a little longer.")
        task = "Transcribe the manager's spoken request, then interpret it."
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}})
    else:
        task = f'Interpret this typed request: "{text}"'
    intents = "\n".join(f"- {k}: {v}" for k, v in INTENTS.items())
    parts.insert(0, {"text": PROMPT.format(task=task, intents=intents)})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": 300}}
    model = model_name()
    try:
        data = post(ENDPOINT.format(model=model), body, key)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode()).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            pass
        raise VoiceUnavailable(f"Gemini returned HTTP {exc.code}{': ' + detail if detail else ''}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VoiceUnavailable(f"Couldn't reach Gemini ({exc.__class__.__name__}).") from exc
    try:
        text_out = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        out = extract_json_object(text_out)
    except (KeyError, IndexError, ValueError) as exc:
        raise VoiceUnavailable("Gemini's answer couldn't be read; please try again or type the command.") from exc
    intent = out.get("intent") if out.get("intent") in INTENTS else "unknown"
    transcript = (out.get("transcript") or text or "").strip()
    return {"transcript": transcript, "intent": intent, "employee": (out.get("employee") or "").strip() or None,
            "model": model}
