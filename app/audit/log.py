"""Audit log: a durable record of every tool action an agent takes."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    agent TEXT NOT NULL,
    client TEXT NOT NULL,
    tool TEXT NOT NULL,
    args TEXT NOT NULL,
    ok INTEGER NOT NULL,
    note TEXT
);
CREATE INDEX IF NOT EXISTS audit_ts ON audit (ts);
"""


@dataclass(frozen=True)
class AuditEntry:
    id: int
    ts: float
    agent: str
    client: str
    tool: str
    args: str
    ok: bool
    note: str | None

    def public(self) -> dict[str, Any]:
        return {**self.__dict__, "ok": bool(self.ok)}


class AuditLog:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def record(
        self, agent: str, client: str, tool: str, args: str, ok: bool, note: str | None = None
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO audit (ts, agent, client, tool, args, ok, note)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), agent, client, tool, args[:500], int(ok), note),
            )

    def recent(
        self, limit: int = 100, agent: str | None = None, client: str | None = None
    ) -> list[AuditEntry]:
        sql, args = "SELECT * FROM audit WHERE 1=1", []
        if agent:
            sql += " AND agent = ?"
            args.append(agent)
        if client:
            sql += " AND client = ?"
            args.append(client)
        rows = self._conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        return [
            AuditEntry(r["id"], r["ts"], r["agent"], r["client"], r["tool"], r["args"],
                       bool(r["ok"]), r["note"])
            for r in rows
        ]  # fmt: skip
