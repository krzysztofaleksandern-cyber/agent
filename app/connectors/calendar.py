"""Local calendar the agents manage, with .ics export for syncing to Outlook/Google."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT,
    location TEXT,
    notes TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_start ON events (start);
"""


class CalendarError(Exception):
    """Invalid calendar operation."""


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    start: str  # ISO 8601
    end: str | None
    location: str | None
    notes: str | None
    created_at: float

    def public(self) -> dict[str, Any]:
        return asdict(self)


def _parse(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CalendarError(
            f"invalid datetime {value!r} (use ISO 8601, e.g. 2026-05-01T09:00)"
        ) from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class CalendarStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def create(
        self, title: str, start: str, end: str = "", location: str = "", notes: str = ""
    ) -> Event:
        if not title.strip():
            raise CalendarError("title is required")
        start_dt = _parse(start)
        end_dt = _parse(end) if end else None
        if end_dt and end_dt < start_dt:
            raise CalendarError("end is before start")
        event_id = uuid.uuid4().hex[:12]
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO events (id, title, start, end, location, notes, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event_id, title.strip(), start_dt.isoformat(),
                 end_dt.isoformat() if end_dt else None, location or None, notes or None,
                 time.time()),
            )  # fmt: skip
        got = self.get(event_id)
        assert got is not None
        return got

    def get(self, event_id: str) -> Event | None:
        row = self._conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return _event(row) if row else None

    def list(self, start_from: str = "", start_to: str = "", limit: int = 50) -> list[Event]:
        sql, args = "SELECT * FROM events WHERE 1=1", []
        if start_from:
            sql += " AND start >= ?"
            args.append(_parse(start_from).isoformat())
        if start_to:
            sql += " AND start <= ?"
            args.append(_parse(start_to).isoformat())
        rows = self._conn.execute(sql + " ORDER BY start LIMIT ?", (*args, limit)).fetchall()
        return [_event(r) for r in rows]

    def delete(self, event_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        return cur.rowcount > 0

    def to_ics(self, events: list[Event]) -> str:
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//devagent//EN"]
        for e in events:
            lines += [
                "BEGIN:VEVENT",
                f"UID:{e.id}@devagent",
                f"SUMMARY:{e.title}",
                f"DTSTART:{_ics_dt(e.start)}",
            ]
            if e.end:
                lines.append(f"DTEND:{_ics_dt(e.end)}")
            if e.location:
                lines.append(f"LOCATION:{e.location}")
            if e.notes:
                lines.append(f"DESCRIPTION:{e.notes}")
            lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")
        return "\r\n".join(lines) + "\r\n"


def _ics_dt(value: str) -> str:
    return _parse(value).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"], title=row["title"], start=row["start"], end=row["end"],
        location=row["location"], notes=row["notes"], created_at=row["created_at"],
    )  # fmt: skip
