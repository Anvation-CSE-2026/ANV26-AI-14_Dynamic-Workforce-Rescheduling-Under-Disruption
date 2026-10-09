"""Start ResQWork: API + website on http://localhost:8000, then open the browser.

    python run.py            (the start scripts in the project root do this for you)

Reads backend/.env if present (copy .env.example to add API keys). Data is kept in backend/resqwork.db.
"""
from __future__ import annotations

import os
import secrets
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
sys.path.insert(0, str(HERE))

if sys.version_info < (3, 10):
    sys.exit("ResQWork needs Python 3.10 or newer (you have %d.%d)." % sys.version_info[:2])


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        if value and key.strip() not in os.environ:
            os.environ[key.strip()] = value


load_env(HERE / ".env")
secret_file = HERE / ".resqwork_secret"          # stable sign-in tokens across restarts
if not os.environ.get("RESQWORK_SECRET"):
    if not secret_file.exists():
        secret_file.write_text(secrets.token_urlsafe(48))
    os.environ["RESQWORK_SECRET"] = secret_file.read_text().strip()
os.environ.setdefault("RESQWORK_LLM_PROVIDER", "claude" if os.environ.get("ANTHROPIC_API_KEY") else "none")

try:
    import uvicorn  # noqa: E402
    from app.main import app  # noqa: E402
except ImportError as exc:
    sys.exit(f"A required package is missing ({exc.name}). Run:  pip install -r requirements.txt")

PORT = int(os.environ.get("PORT", "8000"))
URL = f"http://localhost:{PORT}"
DIST = HERE.parent / "frontend" / "dist" / "index.html"


def open_when_ready() -> None:
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{URL}/health", timeout=1)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    print(f"\n  ResQWork is running at {URL}\n  Demo logins: manager@healthcare.demo / demo1234 (more on the home page)\n"
          "  Press Ctrl+C to stop.\n")
    if os.environ.get("RESQWORK_NO_BROWSER") != "1":
        webbrowser.open(URL)


if __name__ == "__main__":
    if not DIST.exists():
        print("Note: frontend/dist is missing, so only the API will be served. Build the website with:"
              "  cd frontend && npm install && npm run build")
    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
