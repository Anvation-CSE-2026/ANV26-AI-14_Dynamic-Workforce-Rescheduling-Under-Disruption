"""Static demo accounts for hackathon judging: one ADMIN / OPERATIONS login and three employees per industry.

They are ordinary password accounts (PBKDF2-hashed, same login path as everyone else), seeded only
when ``RESQWORK_DEMO_ACCOUNTS`` is on (the default in ``RESQWORK_AUTH_MODE=demo``). Each one belongs
to its industry's demo organization. Logging in loads that demo the first time, and never reloads it
afterwards, so judges can switch between roles and watch the same requests, repairs and notifications
flow between dashboards.

The two employees per industry are chosen to make the story visible:
* ``coverer``: the person the first "Simulate" repair asks to cover, who sees the change and the recognition;
* ``requester``: the person who is out in that scenario, who can file a request from their dashboard;
* a third colleague, so multi-user flows (requests, volunteers, notifications) can be checked with three people.

``manager@<industry>.demo`` still signs in (older docs and bookmarks use it) but is an admin account and is
not listed: the product has no separate manager dashboard. The shared password is demo-only and is exposed
only while demo accounts are enabled.
"""

from __future__ import annotations

import os
import time

from .auth import GLOBAL, hash_password
from .domains import demo_dataset

PASSWORD = "demo1234"

# domain → (coverer employee id, requester employee id)
EMPLOYEES = {
    "healthcare": ("H17", "H01"),
    "manufacturing": ("M04", "M01"),
    "education": ("T09", "T01"),
    "technology": ("E05", "E01"),
    "logistics": ("L10", "L01"),
}


# The 100-person flagship hospital (shared/scenarios/flagship-hospital-100.json) tells the full story:
# fairness picks Meera over Arjun, a staffing gap needs volunteers, rewards follow completion.
FLAGSHIP = "flagship"
FLAGSHIP_SCENARIO = "flagship-hospital-100"
FLAGSHIP_EMPLOYEES = (("ICU03", "meera", "recommended cover: lower recent workload"),
                      ("ICU02", "arjun", "eligible, but already did 8 extra covers this month"),
                      ("ICU01", "kavya", "calls in sick in the demo"),
                      ("ER01", "rohan", "eligible volunteer for the surge team"))


def dataset_for(key: str) -> dict:
    from .domains import scenario_dataset
    return scenario_dataset(FLAGSHIP_SCENARIO) if key == FLAGSHIP else demo_dataset(key)


def keys() -> list[str]:
    return [FLAGSHIP, *EMPLOYEES]


def enabled() -> bool:
    flag = os.getenv("RESQWORK_DEMO_ACCOUNTS")
    if flag is not None:
        return flag.lower() in ("1", "true", "on", "yes")
    return os.getenv("RESQWORK_AUTH_MODE", "demo") == "demo"


def accounts() -> list[dict]:
    raw = dataset_for(FLAGSHIP)
    names = {e["id"]: (e["name"], e["role"]) for e in raw["employees"]}
    out = [{"email": "admin@flagship.demo", "role": "admin", "name": "Nursing operations admin", "domain": FLAGSHIP,
            "org": raw["organization"]["id"], "employee_id": None, "title": f"Admin / Operations, {raw['organization']['name']}",
            "story": "runs the 100-person flagship demo"}]
    for eid, login, story in FLAGSHIP_EMPLOYEES:
        out.append({"email": f"{login}@flagship.demo", "role": "employee", "name": names[eid][0], "domain": FLAGSHIP,
                    "org": raw["organization"]["id"], "employee_id": eid, "title": names[eid][1], "story": story})
    for domain, (coverer, requester) in EMPLOYEES.items():
        raw = demo_dataset(domain)
        org = raw["organization"]["id"]
        names = {e["id"]: (e["name"], e["role"]) for e in raw["employees"]}
        third = next(e["id"] for e in raw["employees"][1:] if e["id"] not in (coverer, requester))
        out += [
            {"email": f"admin@{domain}.demo", "role": "admin", "name": "Operations admin",
             "domain": domain, "org": org, "employee_id": None,
             "title": f"Admin / Operations, {raw['organization']['name']}"},
            {"email": f"manager@{domain}.demo", "role": "admin", "name": "Operations admin",
             "domain": domain, "org": org, "employee_id": None, "title": "legacy alias of the admin login",
             "hidden": True},
        ]
        for eid, story in ((coverer, "covers the first simulated disruption"),
                           (requester, "is out in the first simulated disruption"),
                           (third, "a colleague for multi-user checks")):
            name, role = names[eid]
            out.append({"email": f"{name.split()[0].lower()}@{domain}.demo", "role": "employee", "name": name,
                        "domain": domain, "org": org, "employee_id": eid, "title": role, "story": story})
    return out


def public_list() -> list[dict]:
    """What the landing page shows (the password is public on purpose: these are demo-only accounts)."""
    return [{**{k: a[k] for k in ("email", "role", "name", "domain", "org", "title")}, "story": a.get("story"),
             "password": PASSWORD} for a in accounts() if not a.get("hidden")]


def seed(store) -> int:
    n = 0
    for a in accounts():
        existing = store.get("user", a["email"], GLOBAL)
        store.put("user", a["email"], GLOBAL, {
            "id": a["email"], "email": a["email"], "name": a["name"], "role": a["role"], "org": a["org"],
            "employee_id": a["employee_id"], "provider": "demo-account", "demo_domain": a["domain"],
            "status": "active", "created_at": (existing or {}).get("created_at") or int(time.time()),
            "last_login": (existing or {}).get("last_login"),
            "password": existing["password"] if existing else hash_password(PASSWORD)})
        n += existing is None
    return n
