"""Recurring jobs: a schedule + an agent prompt, stored in SQLite."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    agent TEXT NOT NULL,
    prompt TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run REAL,
    next_run REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_next ON jobs (enabled, next_run);
"""

KINDS = {"every_minutes", "daily", "weekly"}


class JobError(Exception):
    """Invalid job definition."""


@dataclass(frozen=True)
class Job:
    id: str
    name: str
    agent: str
    prompt: str
    kind: str
    value: str
    enabled: bool
    last_run: float | None
    next_run: float
    created_at: float

    def public(self) -> dict[str, Any]:
        return {**self.__dict__, "enabled": bool(self.enabled)}


def compute_next(kind: str, value: str, now: datetime) -> float:
    """Return the next run time (epoch seconds, UTC) strictly after `now`."""
    if kind == "every_minutes":
        minutes = _positive_int(value, "every_minutes")
        return (now + timedelta(minutes=minutes)).timestamp()
    if kind == "daily":
        hh, mm = _hhmm(value)
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.timestamp()
    if kind == "weekly":
        day_str, _, clock = value.partition(":")
        weekday = _positive_int(day_str, "weekday", lo=0, hi=6)
        hh, mm = _hhmm(clock)
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        delta = (weekday - candidate.weekday()) % 7
        candidate += timedelta(days=delta)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate.timestamp()
    raise JobError(f"unknown schedule kind {kind!r} (use {sorted(KINDS)})")


def _positive_int(value: str, field: str, lo: int = 1, hi: int = 10_000_000) -> int:
    try:
        n = int(value)
    except ValueError as exc:
        raise JobError(f"{field} must be an integer") from exc
    if not lo <= n <= hi:
        raise JobError(f"{field} must be between {lo} and {hi}")
    return n


def _hhmm(value: str) -> tuple[int, int]:
    try:
        hh, mm = value.split(":")
        h, m = int(hh), int(mm)
    except ValueError as exc:
        raise JobError("time must be HH:MM (24h)") from exc
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise JobError("time must be a valid HH:MM (24h)")
    return h, m


class JobStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def create(self, name: str, agent: str, prompt: str, kind: str, value: str) -> Job:
        if not name.strip() or not prompt.strip():
            raise JobError("name and prompt are required")
        if kind not in KINDS:
            raise JobError(f"unknown schedule kind {kind!r} (use {sorted(KINDS)})")
        next_run = compute_next(kind, value, datetime.now(UTC))
        job_id = uuid.uuid4().hex[:12]
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO jobs (id, name, agent, prompt, kind, value, next_run, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, name.strip(), agent, prompt.strip(), kind, value, next_run, time.time()),
            )
        got = self.get(job_id)
        assert got is not None
        return got

    def get(self, job_id: str) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _job(row) if row else None

    def list(self) -> list[Job]:
        rows = self._conn.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
        return [_job(r) for r in rows]

    def set_enabled(self, job_id: str, enabled: bool) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE jobs SET enabled = ? WHERE id = ?", (int(enabled), job_id)
            )
        return cur.rowcount > 0

    def delete(self, job_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return cur.rowcount > 0

    def due(self, now: float) -> list[Job]:
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE enabled = 1 AND next_run <= ? ORDER BY next_run", (now,)
        ).fetchall()
        return [_job(r) for r in rows]

    def mark_ran(self, job_id: str, now: datetime) -> None:
        job = self.get(job_id)
        if job is None:
            return
        next_run = compute_next(job.kind, job.value, now)
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE jobs SET last_run = ?, next_run = ? WHERE id = ?",
                (now.timestamp(), next_run, job_id),
            )


def _job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"], name=row["name"], agent=row["agent"], prompt=row["prompt"],
        kind=row["kind"], value=row["value"], enabled=bool(row["enabled"]),
        last_run=row["last_run"], next_run=row["next_run"], created_at=row["created_at"],
    )  # fmt: skip
