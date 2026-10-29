"""A small local CRM (contacts + deals) the agents manage."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STAGES = ["new", "contacted", "qualified", "won", "lost"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    company TEXT,
    notes TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS deals (
    id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    title TEXT NOT NULL,
    stage TEXT NOT NULL,
    value REAL,
    source TEXT,
    notes TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS deals_stage ON deals (stage);
"""


class CrmError(Exception):
    """Invalid CRM operation."""


@dataclass(frozen=True)
class Contact:
    id: str
    name: str
    email: str | None
    phone: str | None
    company: str | None
    notes: str | None
    created_at: float

    def public(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class Deal:
    id: str
    contact_id: str
    title: str
    stage: str
    value: float | None
    source: str | None
    notes: str | None
    created_at: float
    updated_at: float

    def public(self) -> dict[str, Any]:
        return self.__dict__.copy()


class CrmStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def add_contact(
        self, name: str, email: str = "", phone: str = "", company: str = "", notes: str = ""
    ) -> Contact:
        if not name.strip():
            raise CrmError("contact name is required")
        # de-dupe by email when provided
        if email:
            existing = self._conn.execute(
                "SELECT * FROM contacts WHERE email = ?", (email.lower(),)
            ).fetchone()
            if existing:
                return _contact(existing)
        cid = uuid.uuid4().hex[:12]
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO contacts (id, name, email, phone, company, notes, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, name.strip(), email.lower() or None, phone or None, company or None,
                 notes or None, time.time()),
            )  # fmt: skip
        got = self.get_contact(cid)
        assert got is not None
        return got

    def get_contact(self, contact_id: str) -> Contact | None:
        row = self._conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        return _contact(row) if row else None

    def find_contacts(self, query: str, limit: int = 20) -> list[Contact]:
        like = f"%{query.lower()}%"
        rows = self._conn.execute(
            "SELECT * FROM contacts WHERE lower(name) LIKE ? OR email LIKE ? OR"
            " lower(coalesce(company,'')) LIKE ? ORDER BY created_at DESC LIMIT ?",
            (like, like, like, limit),
        ).fetchall()
        return [_contact(r) for r in rows]

    def add_deal(
        self, contact_id: str, title: str, value: float | None = None,
        source: str = "", notes: str = "", stage: str = "new",
    ) -> Deal:  # fmt: skip
        if self.get_contact(contact_id) is None:
            raise CrmError(f"unknown contact {contact_id}")
        if stage not in STAGES:
            raise CrmError(f"stage must be one of {STAGES}")
        if not title.strip():
            raise CrmError("deal title is required")
        did = uuid.uuid4().hex[:12]
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO deals (id, contact_id, title, stage, value, source, notes,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (did, contact_id, title.strip(), stage, value, source or None, notes or None,
                 now, now),
            )  # fmt: skip
        got = self.get_deal(did)
        assert got is not None
        return got

    def get_deal(self, deal_id: str) -> Deal | None:
        row = self._conn.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
        return _deal(row) if row else None

    def list_deals(self, stage: str = "") -> list[Deal]:
        if stage and stage not in STAGES:
            raise CrmError(f"stage must be one of {STAGES}")
        sql, args = "SELECT * FROM deals", []
        if stage:
            sql += " WHERE stage = ?"
            args.append(stage)
        rows = self._conn.execute(sql + " ORDER BY updated_at DESC", args).fetchall()
        return [_deal(r) for r in rows]

    def set_stage(self, deal_id: str, stage: str) -> Deal:
        if stage not in STAGES:
            raise CrmError(f"stage must be one of {STAGES}")
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE deals SET stage = ?, updated_at = ? WHERE id = ?",
                (stage, time.time(), deal_id),
            )
        if cur.rowcount == 0:
            raise CrmError(f"unknown deal {deal_id}")
        got = self.get_deal(deal_id)
        assert got is not None
        return got

    def capture_lead(
        self, name: str, email: str = "", phone: str = "", company: str = "",
        message: str = "", source: str = "website",
    ) -> dict[str, Any]:  # fmt: skip
        contact = self.add_contact(name, email, phone, company, message)
        deal = self.add_deal(contact.id, f"Lead: {name}", source=source, notes=message, stage="new")
        return {"contact_id": contact.id, "deal_id": deal.id}


def _contact(row: sqlite3.Row) -> Contact:
    return Contact(row["id"], row["name"], row["email"], row["phone"], row["company"],
                   row["notes"], row["created_at"])  # fmt: skip


def _deal(row: sqlite3.Row) -> Deal:
    return Deal(row["id"], row["contact_id"], row["title"], row["stage"], row["value"],
                row["source"], row["notes"], row["created_at"], row["updated_at"])  # fmt: skip
