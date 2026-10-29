"""SQLite store for interactions (Q/A + rating) and learned lessons."""

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.memory.embedder import Vector, cosine

_SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client TEXT NOT NULL,
    agent TEXT NOT NULL,
    prompt TEXT NOT NULL,
    answer TEXT NOT NULL,
    rating INTEGER,
    comment TEXT,
    embedding TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS interactions_agent ON interactions (agent, rating);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    interaction_id INTEGER,
    embedding TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS lessons_agent ON lessons (agent);
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    title TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS knowledge_doc ON knowledge (doc_id);
"""


@dataclass(frozen=True)
class Interaction:
    id: int
    client: str
    agent: str
    prompt: str
    answer: str
    rating: int | None
    comment: str | None
    created_at: float


@dataclass(frozen=True)
class Lesson:
    id: int
    agent: str
    text: str
    source: str
    interaction_id: int | None
    created_at: float

    def public(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class KnowledgeChunk:
    id: int
    doc_id: str
    title: str
    chunk_index: int
    text: str
    created_at: float


def _dump(vec: Vector | None) -> str | None:
    return json.dumps([round(v, 6) for v in vec]) if vec else None


class MemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def _write(self, sql: str, args: tuple[Any, ...]) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, args)

    def add_interaction(
        self, client: str, agent: str, prompt: str, answer: str, embedding: Vector | None
    ) -> int:
        cur = self._write(
            "INSERT INTO interactions (client, agent, prompt, answer, embedding, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (client, agent, prompt, answer, _dump(embedding), time.time()),
        )
        return int(cur.lastrowid or 0)

    def get_interaction(self, interaction_id: int) -> Interaction | None:
        row = self._conn.execute(
            "SELECT * FROM interactions WHERE id = ?", (interaction_id,)
        ).fetchone()
        return _interaction(row) if row else None

    def rate(self, interaction_id: int, rating: int, comment: str | None) -> bool:
        cur = self._write(
            "UPDATE interactions SET rating = ?, comment = ? WHERE id = ?",
            (rating, comment, interaction_id),
        )
        return cur.rowcount > 0

    def rated(self, min_rating: int, agent: str | None = None) -> list[Interaction]:
        sql, args = "SELECT * FROM interactions WHERE rating >= ?", [min_rating]
        if agent:
            sql += " AND agent = ?"
            args.append(agent)
        rows = self._conn.execute(sql + " ORDER BY id", args).fetchall()
        return [_interaction(r) for r in rows]

    def add_lesson(
        self,
        agent: str,
        text: str,
        source: str,
        embedding: Vector | None,
        interaction_id: int | None = None,
    ) -> int:
        cur = self._write(
            "INSERT INTO lessons (agent, text, source, interaction_id, embedding, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (agent, text, source, interaction_id, _dump(embedding), time.time()),
        )
        return int(cur.lastrowid or 0)

    def lessons(self, agent: str | None = None) -> list[Lesson]:
        sql, args = "SELECT * FROM lessons", []
        if agent:
            sql += " WHERE agent = ?"
            args.append(agent)
        rows = self._conn.execute(sql + " ORDER BY id", args).fetchall()
        return [_lesson(r) for r in rows]

    def delete_lesson(self, lesson_id: int) -> bool:
        return self._write("DELETE FROM lessons WHERE id = ?", (lesson_id,)).rowcount > 0

    def owner_rules(self, agent: str, limit: int = 20) -> list[Lesson]:
        rows = self._conn.execute(
            "SELECT * FROM lessons WHERE agent IN (?, '*') AND source = 'owner'"
            " ORDER BY id DESC LIMIT ?",
            (agent, limit),
        ).fetchall()
        return [_lesson(r) for r in reversed(rows)]

    def search_lessons(
        self, agent: str, query: Vector, k: int, min_score: float
    ) -> list[tuple[float, Lesson]]:
        rows = self._conn.execute(
            "SELECT * FROM lessons WHERE agent IN (?, '*') AND source != 'owner'"
            " AND embedding IS NOT NULL",
            (agent,),
        ).fetchall()
        return _top(rows, query, k, min_score, _lesson)

    def search_interactions(
        self, agent: str, query: Vector, k: int, min_score: float, min_rating: int
    ) -> list[tuple[float, Interaction]]:
        rows = self._conn.execute(
            "SELECT * FROM interactions WHERE agent = ? AND rating >= ? AND embedding IS NOT NULL",
            (agent, min_rating),
        ).fetchall()
        return _top(rows, query, k, min_score, _interaction)

    def add_knowledge_chunk(
        self, doc_id: str, title: str, index: int, text: str, embedding: Vector | None
    ) -> None:
        self._write(
            "INSERT INTO knowledge (doc_id, title, chunk_index, text, embedding, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, title, index, text, _dump(embedding), time.time()),
        )

    def search_knowledge(
        self, query: Vector, k: int, min_score: float
    ) -> list[tuple[float, KnowledgeChunk]]:
        rows = self._conn.execute("SELECT * FROM knowledge WHERE embedding IS NOT NULL").fetchall()
        return _top(rows, query, k, min_score, _knowledge)

    def list_documents(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT doc_id, title, COUNT(*) n, MIN(created_at) created_at"
            " FROM knowledge GROUP BY doc_id, title ORDER BY created_at DESC"
        ).fetchall()
        return [
            {"doc_id": r["doc_id"], "title": r["title"], "chunks": r["n"],
             "created_at": r["created_at"]}
            for r in rows
        ]  # fmt: skip

    def delete_document(self, doc_id: str) -> int:
        return self._write("DELETE FROM knowledge WHERE doc_id = ?", (doc_id,)).rowcount


def _top(rows, query, k, min_score, build):
    scored = [(cosine(query, json.loads(r["embedding"])), r) for r in rows]
    scored = [(s, r) for s, r in scored if s >= min_score]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(s, build(r)) for s, r in scored[:k]]


def _interaction(row: sqlite3.Row) -> Interaction:
    return Interaction(
        id=row["id"],
        client=row["client"],
        agent=row["agent"],
        prompt=row["prompt"],
        answer=row["answer"],
        rating=row["rating"],
        comment=row["comment"],
        created_at=row["created_at"],
    )


def _lesson(row: sqlite3.Row) -> Lesson:
    return Lesson(
        id=row["id"],
        agent=row["agent"],
        text=row["text"],
        source=row["source"],
        interaction_id=row["interaction_id"],
        created_at=row["created_at"],
    )


def _knowledge(row: sqlite3.Row) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=row["id"],
        doc_id=row["doc_id"],
        title=row["title"],
        chunk_index=row["chunk_index"],
        text=row["text"],
        created_at=row["created_at"],
    )
