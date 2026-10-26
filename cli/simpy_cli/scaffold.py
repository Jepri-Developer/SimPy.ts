"""Pembuatan project baru dari template."""

from __future__ import annotations

import re
from pathlib import Path

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
TEMPLATE_DIR = Path(__file__).parent / "templates" / "default"

# Nama file di template -> nama akhir (dotfile disimpan tanpa titik agar ikut paket).
RENAMES = {"gitignore": ".gitignore", "env.example": ".env.example"}


class ScaffoldError(Exception):
    """Kesalahan yang aman ditampilkan ke pengguna."""


def validate_name(name: str) -> None:
    if not NAME_PATTERN.fullmatch(name):
        raise ScaffoldError(
            f"Nama project '{name}' tidak valid. Pakai huruf kecil, angka, '-' atau '_', "
            "diawali huruf, maksimal 64 karakter."
        )


def create_project(name: str, parent: Path | None = None) -> Path:
    """Buat folder project baru bernama `name` di dalam `parent`. Mengembalikan path-nya."""
    validate_name(name)
    parent = parent or Path.cwd()
    target = parent / name

    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ScaffoldError(f"'{target}' sudah ada dan tidak kosong.")

    try:
        for src in sorted(TEMPLATE_DIR.rglob("*")):
            if src.is_dir():
                continue
            rel = src.relative_to(TEMPLATE_DIR)
            final = rel.name.removesuffix(".tmpl")
            dest = target / rel.with_name(RENAMES.get(final, final))
            dest.parent.mkdir(parents=True, exist_ok=True)
            text = src.read_text(encoding="utf-8").replace("{{name}}", name)
            dest.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ScaffoldError(
            f"Tidak bisa menulis ke '{exc.filename}': {exc.strerror}. "
            "Coba folder lain (mis. folder home) dengan --dir."
        ) from exc

    return target
