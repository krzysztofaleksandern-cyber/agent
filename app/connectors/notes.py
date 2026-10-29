"""A simple personal notes / to-do list stored in SQLite."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    done_at REAL
);
"""


class NoteError(Exception):
    """Invalid note operation."""


@dataclass(frozen=True)
class Note:
    id: str
    text: str
    done: bool
    created_at: float
    done_at: float | None

    def public(self) -> dict[str, Any]:
        return {**self.__dict__, "done": bool(self.done)}


class NotesStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def add(self, text: str) -> Note:
        if not text.strip():
            raise NoteError("note text is required")
        note_id = uuid.uuid4().hex[:8]
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO notes (id, text, created_at) VALUES (?, ?, ?)",
                (note_id, text.strip(), time.time()),
            )
        got = self.get(note_id)
        assert got is not None
        return got

    def get(self, note_id: str) -> Note | None:
        row = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return _note(row) if row else None

    def list(self, include_done: bool = False) -> list[Note]:
        sql = "SELECT * FROM notes"
        if not include_done:
            sql += " WHERE done = 0"
        rows = self._conn.execute(sql + " ORDER BY created_at").fetchall()
        return [_note(r) for r in rows]

    def set_done(self, note_id: str, done: bool = True) -> Note:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE notes SET done = ?, done_at = ? WHERE id = ?",
                (int(done), time.time() if done else None, note_id),
            )
        if cur.rowcount == 0:
            raise NoteError(f"unknown note {note_id}")
        got = self.get(note_id)
        assert got is not None
        return got

    def delete(self, note_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return cur.rowcount > 0


def _note(row: sqlite3.Row) -> Note:
    return Note(row["id"], row["text"], bool(row["done"]), row["created_at"], row["done_at"])
