"""Domain configurations and demo datasets from shared/ (the single source of truth)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from core.models import DOMAINS

SHARED = Path(__file__).resolve().parents[2] / "shared"


@lru_cache(maxsize=None)
def domain_config(domain: str) -> dict:
    if domain not in DOMAINS:
        raise KeyError(f"unknown domain '{domain}'")
    return json.loads((SHARED / "domains" / f"{domain}.json").read_text(encoding="utf-8"))


def domain_index() -> list[dict]:
    return json.loads((SHARED / "domains" / "index.json").read_text(encoding="utf-8"))


def demo_dataset(domain: str) -> dict:
    if domain not in DOMAINS:
        raise KeyError(f"unknown domain '{domain}'")
    return json.loads((SHARED / "demo-data" / f"{domain}.json").read_text(encoding="utf-8"))


def scenario_list() -> list[dict]:
    """Small hand-checkable test datasets (shared/scenarios/*.json): repair cases and an infeasible one."""
    out = []
    for f in sorted((SHARED / "scenarios").glob("*.json")):
        raw = json.loads(f.read_text(encoding="utf-8"))
        out.append({"id": f.stem, "name": raw["organization"]["name"], "domain": raw["organization"]["domain"]})
    return out


def scenario_dataset(name: str) -> dict:
    path = SHARED / "scenarios" / f"{name}.json"
    if not name.replace("-", "").isalnum() or not path.exists():
        raise KeyError(f"unknown scenario '{name}'")
    return json.loads(path.read_text(encoding="utf-8"))


def policy_dir(domain: str) -> Path:
    return SHARED / "policies" / domain


def term(domain: str, key: str, default: str) -> str:
    try:
        return domain_config(domain)["terminology"].get(key, default)
    except KeyError:
        return default
