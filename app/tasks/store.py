"""SQLite-backed task queue."""

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"
FINAL = {DONE, FAILED, CANCELLED}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    client TEXT NOT NULL,
    agent TEXT NOT NULL,
    messages TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL,
    result TEXT,
    error TEXT,
    webhook_url TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    not_before REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS tasks_status ON tasks (status, not_before, created_at);
"""


@dataclass(frozen=True)
class Task:
    id: str
    client: str
    agent: str
    messages: list[dict[str, Any]]
    status: str
    attempts: int
    max_attempts: int
    result: str | None
    error: str | None
    webhook_url: str | None
    created_at: float
    updated_at: float

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("messages")
        return data


class TaskStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def create(
        self,
        client: str,
        agent: str,
        messages: list[dict[str, Any]],
        webhook_url: str | None = None,
        max_attempts: int = 3,
    ) -> Task:
        now = time.time()
        task_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO tasks (id, client, agent, messages, status, max_attempts, webhook_url,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, client, agent, json.dumps(messages), QUEUED, max_attempts, webhook_url,
                 now, now),
            )  # fmt: skip
        task = self.get(task_id)
        assert task is not None
        return task

    def get(self, task_id: str) -> Task | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task(row) if row else None

    def list(
        self, client: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[Task]:
        query, args = "SELECT * FROM tasks WHERE 1=1", []
        if client is not None:
            query += " AND client = ?"
            args.append(client)
        if status is not None:
            query += " AND status = ?"
            args.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        rows = self._conn.execute(query, (*args, limit)).fetchall()
        return [_task(r) for r in rows]

    def claim_next(self) -> Task | None:
        """Atomically move the oldest ready task to RUNNING."""
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT id FROM tasks WHERE status = ? AND not_before <= ?"
                    " ORDER BY created_at LIMIT 1",
                    (QUEUED, now),
                ).fetchone()
                if row is None:
                    self._conn.execute("COMMIT")
                    return None
                self._conn.execute(
                    "UPDATE tasks SET status = ?, attempts = attempts + 1, updated_at = ?"
                    " WHERE id = ?",
                    (RUNNING, now, row["id"]),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
        return self.get(row["id"])

    def _update(self, task_id: str, only_if: set[str], **fields: Any) -> bool:
        cols = ", ".join(f"{k} = ?" for k in fields)
        marks = ", ".join("?" for _ in only_if)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE tasks SET {cols}, updated_at = ? WHERE id = ? AND status IN ({marks})",  # noqa: S608
                (*fields.values(), time.time(), task_id, *only_if),
            )
        return cur.rowcount > 0

    def complete(self, task_id: str, result: str) -> bool:
        return self._update(task_id, {RUNNING}, status=DONE, result=result, error=None)

    def fail(self, task_id: str, error: str, retry_in: float | None = None) -> bool:
        if retry_in is not None:
            return self._update(
                task_id, {RUNNING}, status=QUEUED, error=error, not_before=time.time() + retry_in
            )
        return self._update(task_id, {RUNNING}, status=FAILED, error=error)

    def cancel(self, task_id: str) -> bool:
        return self._update(task_id, {QUEUED, RUNNING}, status=CANCELLED)

    def requeue(self, task_id: str) -> bool:
        """Put a task interrupted by shutdown back in the queue without consuming an attempt."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE tasks SET status = ?, attempts = MAX(attempts - 1, 0), updated_at = ?"
                " WHERE id = ? AND status = ?",
                (QUEUED, time.time(), task_id, RUNNING),
            )
        return cur.rowcount > 0

    def recover(self) -> int:
        """After a crash: tasks left RUNNING go back to the queue."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE status = ?",
                (QUEUED, time.time(), RUNNING),
            )
        return cur.rowcount


def _task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        client=row["client"],
        agent=row["agent"],
        messages=json.loads(row["messages"]),
        status=row["status"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        result=row["result"],
        error=row["error"],
        webhook_url=row["webhook_url"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
