"""Konfigurasi dari environment variable (dan file .env). Secret tidak pernah di-hardcode."""

from __future__ import annotations

import dataclasses
import os
import re
from collections.abc import Mapping, MutableMapping
from pathlib import Path

PLACEHOLDER_SECRET = "ganti-dengan-string-acak-panjang"
MIN_PRODUCTION_SECRET_LENGTH = 32
ENVIRONMENTS = ("development", "production", "test")
_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ConfigError(Exception):
    """Konfigurasi tidak valid. Pesannya aman ditampilkan (tidak memuat nilai secret)."""


@dataclasses.dataclass(frozen=True)
class Settings:
    env: str
    secret_key: str = dataclasses.field(repr=False)
    host: str = "127.0.0.1"
    port: int = 8000
    session_db: str = "instance/sessions.db"

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def parse_dotenv(text: str) -> dict[str, str]:
    """Parser .env sederhana: KEY=VALUE, komentar '#', 'export' opsional, kutip dilepas."""
    result: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not _KEY_PATTERN.fullmatch(key):
            # Sengaja tidak menyertakan isi baris: bisa berisi secret.
            raise ConfigError(f"Baris {lineno} di file .env tidak valid (format: KEY=VALUE).")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key] = value
    return result


def read_dotenv(path: str | Path | None) -> dict[str, str]:
    if path is None:
        return {}
    file = Path(path)
    if not file.is_file():
        return {}
    try:
        return parse_dotenv(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"File {file.name} tidak bisa dibaca: {exc.strerror}") from exc


def apply_dotenv(path: str | Path | None, environ: MutableMapping[str, str]) -> None:
    """Salin isi .env ke `environ` tanpa menimpa variabel yang sudah ada."""
    for key, value in read_dotenv(path).items():
        environ.setdefault(key, value)


def load_settings(
    environ: Mapping[str, str] | None = None,
    dotenv_path: str | Path | None = ".env",
) -> Settings:
    """Baca Settings. Variabel environment menang atas .env. Gagal jika secret kosong."""
    env_vars = os.environ if environ is None else environ
    merged = {**read_dotenv(dotenv_path), **env_vars}

    mode = merged.get("SIMPY_ENV", "development").strip().lower()
    if mode not in ENVIRONMENTS:
        raise ConfigError(f"SIMPY_ENV harus salah satu dari: {', '.join(ENVIRONMENTS)}.")

    secret = merged.get("SIMPY_SECRET_KEY", "").strip()
    if not secret:
        raise ConfigError(
            "SIMPY_SECRET_KEY belum diisi. Salin .env.example menjadi .env lalu isi nilainya."
        )
    if mode == "production" and (
        secret == PLACEHOLDER_SECRET or len(secret) < MIN_PRODUCTION_SECRET_LENGTH
    ):
        raise ConfigError(
            f"Di production, SIMPY_SECRET_KEY harus acak dan minimal "
            f"{MIN_PRODUCTION_SECRET_LENGTH} karakter (bukan nilai contoh)."
        )

    host = merged.get("SIMPY_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port_text = merged.get("SIMPY_PORT", "8000").strip()
    try:
        port = int(port_text)
    except ValueError:
        raise ConfigError("SIMPY_PORT harus berupa angka 1-65535.") from None
    if not 1 <= port <= 65535:
        raise ConfigError("SIMPY_PORT harus berupa angka 1-65535.")

    session_db = merged.get("SIMPY_SESSION_DB", "instance/sessions.db").strip()
    if not session_db:
        raise ConfigError("SIMPY_SESSION_DB tidak boleh kosong.")

    return Settings(env=mode, secret_key=secret, host=host, port=port, session_db=session_db)
