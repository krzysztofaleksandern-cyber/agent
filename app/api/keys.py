"""API keys for client apps: generated once, stored only as SHA-256 hashes in SQLite."""

import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

KEY_PREFIX = "sk-dev-"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    last_used_at REAL,
    revoked_at REAL
);
"""


@dataclass(frozen=True)
class KeyRecord:
    id: int
    label: str
    prefix: str
    created_at: float
    last_used_at: float | None
    revoked_at: float | None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


def generate_secret(nbytes: int = 32) -> str:
    """Random URL-safe secret, e.g. for ADMIN_API_KEY or webhook secrets in .env."""
    return secrets.token_urlsafe(nbytes)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class KeyStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def create(self, label: str) -> tuple[str, KeyRecord]:
        """Create a key. The plaintext key is returned once and never stored."""
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO api_keys (label, prefix, key_hash, created_at) VALUES (?, ?, ?, ?)",
                (label, key[:14], _hash(key), time.time()),
            )
        record = self.get(int(cur.lastrowid or 0))
        assert record is not None
        return key, record

    def get(self, key_id: int) -> KeyRecord | None:
        row = self._conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        return _record(row) if row else None

    def list(self) -> list[KeyRecord]:
        rows = self._conn.execute("SELECT * FROM api_keys ORDER BY id").fetchall()
        return [_record(r) for r in rows]

    def verify(self, key: str) -> KeyRecord | None:
        """Return the active record for this key (and touch last_used_at), else None."""
        if not key.startswith(KEY_PREFIX):
            return None
        digest = _hash(key)
        row = self._conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL", (digest,)
        ).fetchone()
        if row is None or not hmac.compare_digest(row["key_hash"], digest):
            return None
        with self._conn:
            self._conn.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE id = ?", (time.time(), row["id"])
            )
        return _record(row)

    def revoke(self, key_id: int) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (time.time(), key_id),
            )
        return cur.rowcount > 0


def _record(row: sqlite3.Row) -> KeyRecord:
    return KeyRecord(
        id=row["id"],
        label=row["label"],
        prefix=row["prefix"],
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        revoked_at=row["revoked_at"],
    )
