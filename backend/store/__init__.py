"""Document store: workspaces, disruptions, proposals, versions, notifications, audit, users.

Two interchangeable implementations behind one interface:

* ``SqliteStore`` (stdlib sqlite3): default; file or in-memory; zero dependencies.
* ``SqlAlchemyStore``: any SQLAlchemy URL, e.g. Supabase Postgres
  (``DATABASE_URL=postgresql+psycopg://…``). Same table, same JSON documents.

Documents are JSON objects keyed by (kind, id) and scoped by organization,
which gives organization-level data isolation at the storage layer.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Optional, Protocol


class Store(Protocol):
    def put(self, kind: str, doc_id: str, org: str, body: dict) -> None: ...
    def get(self, kind: str, doc_id: str, org: str) -> Optional[dict]: ...
    def list(self, kind: str, org: str, limit: int = 500) -> list[dict]: ...
    def delete(self, kind: str, doc_id: str, org: str) -> None: ...


_DDL = """CREATE TABLE IF NOT EXISTS documents (
    kind TEXT NOT NULL, id TEXT NOT NULL, org TEXT NOT NULL,
    created REAL NOT NULL, updated REAL NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (org, kind, id))"""


class SqliteStore:
    def __init__(self, path: str = ":memory:") -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(_DDL)
        self._db.execute("CREATE INDEX IF NOT EXISTS ix_docs ON documents (org, kind, created)")
        self._db.commit()

    def put(self, kind: str, doc_id: str, org: str, body: dict) -> None:
        now = time.time()
        with self._lock:
            self._db.execute(
                "INSERT INTO documents (kind, id, org, created, updated, body) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(org, kind, id) DO UPDATE SET body = excluded.body, updated = excluded.updated",
                (kind, doc_id, org, now, now, json.dumps(body, default=str)))
            self._db.commit()

    def get(self, kind: str, doc_id: str, org: str) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT body FROM documents WHERE org=? AND kind=? AND id=?",
                                   (org, kind, doc_id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind: str, org: str, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT body FROM documents WHERE org=? AND kind=? ORDER BY created DESC, rowid DESC "
                                    "LIMIT ?", (org, kind, limit)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def delete(self, kind: str, doc_id: str, org: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM documents WHERE org=? AND kind=? AND id=?", (org, kind, doc_id))
            self._db.commit()


class SqlAlchemyStore:  # pragma: no cover - exercised on deployments with Postgres
    def __init__(self, url: str) -> None:
        from sqlalchemy import Column, Float, MetaData, String, Table, Text, create_engine

        self._engine = create_engine(url, pool_pre_ping=True)
        meta = MetaData()
        self._t = Table("documents", meta,
                        Column("org", String, primary_key=True), Column("kind", String, primary_key=True),
                        Column("id", String, primary_key=True), Column("created", Float, nullable=False),
                        Column("updated", Float, nullable=False), Column("body", Text, nullable=False))
        meta.create_all(self._engine)

    def put(self, kind: str, doc_id: str, org: str, body: dict) -> None:
        from sqlalchemy import and_, insert, select, update

        t, now = self._t, time.time()
        with self._engine.begin() as c:
            exists = c.execute(select(t.c.id).where(and_(t.c.org == org, t.c.kind == kind, t.c.id == doc_id))).first()
            data = json.dumps(body, default=str)
            if exists:
                c.execute(update(t).where(and_(t.c.org == org, t.c.kind == kind, t.c.id == doc_id))
                          .values(body=data, updated=now))
            else:
                c.execute(insert(t).values(org=org, kind=kind, id=doc_id, created=now, updated=now, body=data))

    def get(self, kind: str, doc_id: str, org: str) -> Optional[dict]:
        from sqlalchemy import and_, select

        t = self._t
        with self._engine.connect() as c:
            row = c.execute(select(t.c.body).where(and_(t.c.org == org, t.c.kind == kind, t.c.id == doc_id))).first()
        return json.loads(row[0]) if row else None

    def list(self, kind: str, org: str, limit: int = 500) -> list[dict]:
        from sqlalchemy import and_, select

        t = self._t
        with self._engine.connect() as c:
            rows = c.execute(select(t.c.body).where(and_(t.c.org == org, t.c.kind == kind))
                             .order_by(t.c.created.desc()).limit(limit)).all()
        return [json.loads(r[0]) for r in rows]

    def delete(self, kind: str, doc_id: str, org: str) -> None:
        from sqlalchemy import and_, delete

        t = self._t
        with self._engine.begin() as c:
            c.execute(delete(t).where(and_(t.c.org == org, t.c.kind == kind, t.c.id == doc_id)))


def make_store(url: Optional[str] = None) -> Any:
    url = url if url is not None else os.getenv("DATABASE_URL", "sqlite:///./resqwork.db")
    if url.startswith("sqlite:///"):
        return SqliteStore(url.removeprefix("sqlite:///") or ":memory:")
    if url in ("", "memory", ":memory:"):
        return SqliteStore(":memory:")
    return SqlAlchemyStore(url)
