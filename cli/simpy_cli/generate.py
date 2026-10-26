"""Perintah `simpy generate`: buat klien TypeScript bertipe dari route Python."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from simpy.codegen import generate_typescript, write_if_changed
from simpy_cli.project import load_app


def generate_client(project_dir: Path, config: dict[str, Any]) -> Path:
    """Tulis .simpy/api.ts. Mengimpor aplikasi pengguna (butuh environment/secret valid)."""
    app = load_app(project_dir, config)
    target = project_dir / ".simpy" / "api.ts"
    write_if_changed(target, generate_typescript(app.routes_info()))
    return target
