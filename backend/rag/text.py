"""Tokenization shared by the embedder, BM25 and confidence scoring.

Workforce policies use many words for the same idea ("rest", "break between
shifts", "time off between shifts"; "OT", "overtime", "extra hours"). A small
domain synonym map folds these onto one canonical term so lexical retrieval
and the local embedder agree with how managers and HR actually write.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")

STOPWORDS = frozenset("""
a an the and or of to in on for at by with from as is are was were be been being this that these those it its
any all each every per may can could should would will shall must not no nor than then there their they them we
our you your he she his her i me my do does did done have has had if into within without about over under up
out so such very also only own same other some what which who whom when where why how between more most less
much many need needs needed get gets got give tell please say says said know let us our company organization
policy policies rule rules guideline guidelines handbook allowed permitted anyone someone really actually
""".split())

# canonical ← variants (after lowercasing; single tokens)
_SYNONYMS = {
    "overtime": ["ot", "extra-hours", "overtime"],
    "rest": ["rest", "break", "breaks", "gap", "recovery", "off-duty"],
    "shift": ["shift", "shifts", "roster", "rostered", "rota"],
    "week": ["week", "weekly", "weeks", "wk"],
    "day": ["day", "daily", "days"],
    "hour": ["hour", "hours", "hrs", "hr", "h"],
    "employee": ["employee", "employees", "staff", "worker", "workers", "agent", "agents", "associate", "associates",
                 "personnel", "people", "person"],
    "approve": ["approve", "approval", "approved", "authorise", "authorize", "authorised", "authorized", "sign-off"],
    "skill": ["skill", "skills", "qualified", "qualification", "qualifications", "certified", "certification",
              "trained", "competency"],
    "staffing": ["staffing", "coverage", "cover", "covered", "headcount", "manning"],
    "weekend": ["weekend", "weekends", "saturday", "sunday", "saturdays", "sundays"],
    "consecutive": ["consecutive", "continuous", "straight", "row"],
    "preference": ["preference", "preferences", "preferred", "prefer"],
    "change": ["change", "changes", "changed", "reschedule", "rescheduled", "rescheduling", "reassign",
               "reassigned", "reassignment", "swap", "swaps"],
    "maximum": ["maximum", "max", "exceed", "exceeds", "cap", "capped", "limit", "limits", "limited", "most"],
    "minimum": ["minimum", "min", "least", "fewer", "atleast"],
    "notice": ["notice", "notify", "notified", "notification", "inform", "informed"],
}
SYNONYMS: dict[str, str] = {v: canon for canon, vs in _SYNONYMS.items() for v in vs}


def _stem(tok: str) -> str:
    if len(tok) <= 4 or tok[0].isdigit():
        return tok
    for suf in ("ations", "ation", "ings", "ing", "ies", "ed", "es", "s"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 3:
            return tok[: -len(suf)] + ("y" if suf == "ies" else "")
    return tok


def tokenize(text: str, keep_stopwords: bool = False) -> list[str]:
    text = text.lower().replace("extra hours", "extra-hours").replace("off duty", "off-duty")
    text = text.replace("at least", "atleast").replace("sign off", "sign-off")
    for phrase in ("no more than", "more than", "up to", "not exceed", "in excess of"):
        text = text.replace(phrase, " max ")
    out = []
    for tok in _WORD.findall(text):
        if not keep_stopwords and tok in STOPWORDS:
            continue
        canon = SYNONYMS.get(tok)
        out.append(canon if canon else _stem(tok))
    return out


def bigrams(tokens: list[str]) -> list[str]:
    return [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]


_SENT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(\"'])")


def sentences(text: str) -> list[str]:
    parts = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if line:
            parts.extend(s.strip() for s in _SENT.split(line) if s.strip())
    return parts


def normalize_for_match(text: str) -> str:
    text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    text = text.replace("**", "").replace("__", "")
    return " ".join(text.split()).lower()
