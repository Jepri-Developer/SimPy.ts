"""Auth dan sesi: hash password (scrypt), SQLite, sesi di server. Hanya pustaka standar."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --- hash password -----------------------------------------------------------------------

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
_MAX_PASSWORD_LENGTH = 1024
_MAX_MEMORY = 64 * 1024 * 1024


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    secret = unicodedata.normalize("NFKC", password).encode("utf-8")
    return hashlib.scrypt(secret, salt=salt, n=n, r=r, p=p, maxmem=_MAX_MEMORY, dklen=32)


def hash_password(password: str) -> str:
    """Hash dengan scrypt + salt acak. Format: scrypt$n$r$p$salt$hash."""
    if not isinstance(password, str) or not 0 < len(password) <= _MAX_PASSWORD_LENGTH:
        raise ValueError(f"password harus 1-{_MAX_PASSWORD_LENGTH} karakter")
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Cek password terhadap hash. Tidak pernah melempar error; hash rusak berarti False."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt" or not isinstance(password, str):
            return False
        if not 0 < len(password) <= _MAX_PASSWORD_LENGTH:
            return False
        n_i, r_i, p_i = int(n), int(r), int(p)
        if not (2 <= n_i <= 2**20 and n_i & (n_i - 1) == 0 and 1 <= r_i <= 32 and 1 <= p_i <= 16):
            return False
        expected = _unb64(digest)
        actual = _scrypt(password, _unb64(salt), n_i, r_i, p_i)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


_dummy_hash: str | None = None


def _dummy() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_urlsafe(12))
    return _dummy_hash


# --- database ---------------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    last_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
"""


class Database:
    """Satu koneksi SQLite (autocommit) yang aman dipakai lintas thread lewat lock."""

    def __init__(self, path: str) -> None:
        self._lock = threading.RLock()
        in_memory = path == ":memory:"
        if not in_memory:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        if not in_memory:
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass  # beberapa filesystem tidak mendukung WAL
        with self._lock:
            self._conn.executescript(_SCHEMA)
        if not in_memory:
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def run(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self._lock:
            return self._conn.execute(sql, params).rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# --- pengguna -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class User:
    id: str
    username: str


class UserExists(Exception):
    """Username sudah dipakai (tanpa membedakan huruf besar/kecil)."""


class UserStore:
    """Tabel pengguna sederhana. Hash scrypt memakan waktu: panggil dari handler sync (`def`)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, username: str, password: str) -> User:
        password_hash = hash_password(password)
        try:
            self._db.run(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, time.time()),
            )
        except sqlite3.IntegrityError:
            raise UserExists(username) from None
        rows = self._db.query("SELECT id FROM users WHERE username = ?", (username,))
        return User(str(rows[0][0]), username)

    def authenticate(self, username: str, password: str) -> User | None:
        rows = self._db.query(
            "SELECT id, username, password_hash FROM users WHERE username = ?", (username,)
        )
        if not rows:
            verify_password(password, _dummy())  # samakan waktu agar username tidak bisa ditebak
            return None
        user_id, name, password_hash = rows[0]
        return User(str(user_id), name) if verify_password(password, password_hash) else None

    def get(self, user_id: str) -> User | None:
        if not str(user_id).isdigit():
            return None
        rows = self._db.query("SELECT id, username FROM users WHERE id = ?", (int(user_id),))
        return User(str(rows[0][0]), rows[0][1]) if rows else None


# --- sesi -------------------------------------------------------------------------------------------

_RAW_ID = re.compile(r"[A-Za-z0-9_-]{20,100}")


@dataclass(frozen=True)
class Session:
    user_id: str
    created_at: float
    expires_at: float


def _hash_id(raw_id: str) -> str:
    return hashlib.sha256(raw_id.encode()).hexdigest()


class SessionStore:
    """Sesi di server. Cookie hanya berisi id acak; DB hanya menyimpan hash-nya."""

    def __init__(
        self,
        db: Database,
        *,
        lifetime: float = 7 * 86400,
        idle_timeout: float = 86400,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db = db
        self.lifetime = lifetime
        self._idle = idle_timeout
        self._clock = clock
        self._last_purge = 0.0

    def create(self, user_id: str) -> tuple[str, Session]:
        now = self._clock()
        if now - self._last_purge > 600:
            self.purge_expired()
        raw_id = secrets.token_urlsafe(32)
        expires = now + self.lifetime
        self._db.run(
            "INSERT INTO sessions (id_hash, user_id, created_at, expires_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (_hash_id(raw_id), str(user_id), now, expires, now),
        )
        return raw_id, Session(str(user_id), now, expires)

    def get(self, raw_id: str | None) -> Session | None:
        if not raw_id or not _RAW_ID.fullmatch(raw_id):
            return None
        now = self._clock()
        digest = _hash_id(raw_id)
        rows = self._db.query(
            "SELECT user_id, created_at, expires_at, last_seen FROM sessions WHERE id_hash = ?",
            (digest,),
        )
        if not rows:
            return None
        user_id, created, expires, last_seen = rows[0]
        if expires <= now or last_seen + self._idle <= now:
            self._db.run("DELETE FROM sessions WHERE id_hash = ?", (digest,))
            return None
        if now - last_seen > 60:
            self._db.run("UPDATE sessions SET last_seen = ? WHERE id_hash = ?", (now, digest))
        return Session(user_id, created, expires)

    def delete(self, raw_id: str | None) -> None:
        if raw_id:
            self._db.run("DELETE FROM sessions WHERE id_hash = ?", (_hash_id(raw_id),))

    def delete_user(self, user_id: str) -> int:
        """Cabut semua sesi seorang pengguna (mis. setelah ganti password)."""
        return self._db.run("DELETE FROM sessions WHERE user_id = ?", (str(user_id),))

    def purge_expired(self) -> int:
        now = self._clock()
        self._last_purge = now
        return self._db.run(
            "DELETE FROM sessions WHERE expires_at <= ? OR last_seen + ? <= ?",
            (now, self._idle, now),
        )


# --- fungsi untuk handler -----------------------------------------------------------------------------


def _app_of(request: Any) -> Any:
    app = request.scope.get("simpy.app")
    if app is None:
        raise RuntimeError("login()/logout() hanya bisa dipanggil dari handler route SimPy.")
    return app


def login(request: Any, user_id: Any) -> Session:
    """Mulai sesi baru untuk `user_id`: sesi lama dicabut (anti session fixation) dan token
    CSRF diganti. Cookie ditulis otomatis ke respons."""
    return _app_of(request)._login(request.scope, request.headers.get("cookie", ""), str(user_id))


def logout(request: Any) -> None:
    """Akhiri sesi di server, hapus cookie, dan ganti token CSRF."""
    _app_of(request)._logout(request.scope, request.headers.get("cookie", ""))
