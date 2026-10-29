"""One-time-password login and short-lived sessions for the phone console (PWA).

OTPs and sessions live in SQLite (as hashes) so the admin CLI (`python -m app.cli
console-otp`) and the running server share them. The owner types the OTP once in the
browser and gets a session token stored in the browser; the OTP is single-use and
short-lived, so the downloaded page itself is then irrelevant.
"""

import hashlib
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS console_otps (otp_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS console_sessions (token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL);
"""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Session:
    token: str
    expires_at: float


class ConsoleManager:
    def __init__(
        self, db_path: str | Path, otp_ttl: float = 300.0, session_ttl: float = 43200.0
    ) -> None:
        self.otp_ttl = otp_ttl
        self.session_ttl = session_ttl
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def create_otp(self) -> tuple[str, int]:
        otp = f"{secrets.randbelow(1_000_000):06d}"
        with self._lock, self._conn:
            self._gc()
            self._conn.execute(
                "INSERT OR REPLACE INTO console_otps VALUES (?, ?)",
                (_hash(otp), time.time() + self.otp_ttl),
            )
        return otp, int(self.otp_ttl)

    def redeem(self, otp: str) -> Session | None:
        digest = _hash(otp.strip())
        with self._lock, self._conn:
            self._gc()
            row = self._conn.execute(
                "SELECT expires_at FROM console_otps WHERE otp_hash = ?", (digest,)
            ).fetchone()
            if row is None or row[0] < time.time():
                return None
            self._conn.execute("DELETE FROM console_otps WHERE otp_hash = ?", (digest,))
            token = "cs-" + secrets.token_urlsafe(32)
            expires = time.time() + self.session_ttl
            self._conn.execute(
                "INSERT INTO console_sessions VALUES (?, ?)", (_hash(token), expires)
            )
        return Session(token, expires)

    def verify(self, token: str) -> bool:
        row = self._conn.execute(
            "SELECT expires_at FROM console_sessions WHERE token_hash = ?", (_hash(token),)
        ).fetchone()
        return row is not None and row[0] >= time.time()

    def logout(self, token: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM console_sessions WHERE token_hash = ?", (_hash(token),))

    def _gc(self) -> None:
        now = time.time()
        self._conn.execute("DELETE FROM console_otps WHERE expires_at < ?", (now,))
        self._conn.execute("DELETE FROM console_sessions WHERE expires_at < ?", (now,))
