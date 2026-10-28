"""Fine-tuned model versions per alias: candidate -> active | rejected; rollback support."""

import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CANDIDATE, ACTIVE, REJECTED, RETIRED = "candidate", "active", "rejected", "retired"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias TEXT NOT NULL,
    model TEXT NOT NULL,
    base_model TEXT NOT NULL,
    status TEXT NOT NULL,
    score REAL,
    baseline_score REAL,
    note TEXT,
    created_at REAL NOT NULL,
    activated_at REAL
);
"""


@dataclass(frozen=True)
class ModelVersion:
    id: int
    alias: str
    model: str
    base_model: str
    status: str
    score: float | None
    baseline_score: float | None
    note: str | None
    created_at: float
    activated_at: float | None

    def public(self) -> dict[str, Any]:
        return asdict(self)


class VersionStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def add(self, alias: str, model: str, base_model: str, note: str | None = None) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO model_versions (alias, model, base_model, status, note, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (alias, model, base_model, CANDIDATE, note, time.time()),
            )
        return int(cur.lastrowid or 0)

    def get(self, version_id: int) -> ModelVersion | None:
        row = self._conn.execute(
            "SELECT * FROM model_versions WHERE id = ?", (version_id,)
        ).fetchone()
        return ModelVersion(**dict(row)) if row else None

    def list(self, alias: str | None = None) -> list[ModelVersion]:
        sql, args = "SELECT * FROM model_versions", []
        if alias:
            sql += " WHERE alias = ?"
            args.append(alias)
        rows = self._conn.execute(sql + " ORDER BY id", args).fetchall()
        return [ModelVersion(**dict(r)) for r in rows]

    def set_scores(self, version_id: int, score: float, baseline: float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE model_versions SET score = ?, baseline_score = ? WHERE id = ?",
                (score, baseline, version_id),
            )

    def activate(self, version_id: int) -> None:
        version = self.get(version_id)
        assert version is not None
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE model_versions SET status = ? WHERE alias = ? AND status = ?",
                (RETIRED, version.alias, ACTIVE),
            )
            self._conn.execute(
                "UPDATE model_versions SET status = ?, activated_at = ? WHERE id = ?",
                (ACTIVE, time.time(), version_id),
            )

    def reject(self, version_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE model_versions SET status = ? WHERE id = ?", (REJECTED, version_id)
            )

    def active(self) -> dict[str, ModelVersion]:
        rows = self._conn.execute(
            "SELECT * FROM model_versions WHERE status = ?", (ACTIVE,)
        ).fetchall()
        return {r["alias"]: ModelVersion(**dict(r)) for r in rows}

    def rollback(self, alias: str) -> ModelVersion | None:
        """Retire the active version; reactivate the previously active one (if any).
        Returns the version now active, or None (= back to the base model)."""
        current = self.active().get(alias)
        if current is None:
            return None
        previous = self._conn.execute(
            "SELECT id FROM model_versions WHERE alias = ? AND status = ? AND id < ?"
            " ORDER BY activated_at DESC LIMIT 1",
            (alias, RETIRED, current.id),
        ).fetchone()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE model_versions SET status = ? WHERE id = ?", (REJECTED, current.id)
            )
        if previous is None:
            return None
        self.activate(previous["id"])
        return self.get(previous["id"])
