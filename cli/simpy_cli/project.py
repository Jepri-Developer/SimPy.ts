"""Fungsi bersama CLI: config project, environment, dan memuat aplikasi pengguna."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from simpy.app import SimPy
from simpy.config import ConfigError, Settings, apply_dotenv, load_settings

CONFIG_FILE = "simpy.config.json"


class ProjectError(Exception):
    """Kesalahan yang aman ditampilkan ke pengguna."""


def entry_to_import_string(entry: str, app_name: str = "app") -> str:
    """'app/routes.py' + 'app' -> 'app.routes:app' (ditolak jika tidak aman/valid)."""
    path = PurePosixPath(entry.replace("\\", "/"))
    if path.suffix != ".py" or path.is_absolute() or ".." in path.parts:
        raise ProjectError(f"backend.entry '{entry}' harus berupa path relatif ke file .py di project.")
    parts = path.with_suffix("").parts
    if not parts or not all(part.isidentifier() for part in parts):
        raise ProjectError(
            f"backend.entry '{entry}' harus berisi nama folder/file yang valid untuk Python."
        )
    if not app_name.isidentifier():
        raise ProjectError(f"backend.app '{app_name}' bukan nama variabel Python yang valid.")
    return f"{'.'.join(parts)}:{app_name}"


def load_project_config(project_dir: Path) -> dict[str, Any]:
    path = project_dir / CONFIG_FILE
    if not path.is_file():
        raise ProjectError(
            f"{CONFIG_FILE} tidak ditemukan di {project_dir}. "
            "Jalankan perintah ini dari dalam folder project hasil `simpy create`."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectError(f"{CONFIG_FILE} tidak bisa dibaca: {exc}") from exc
    if not isinstance(data, dict):
        raise ProjectError(f"Isi {CONFIG_FILE} harus berupa objek JSON.")
    return data


def backend_import_string(config: dict[str, Any]) -> str:
    backend = config.get("backend", {})
    if not isinstance(backend, dict):
        raise ProjectError(f"'backend' di {CONFIG_FILE} harus berupa objek.")
    return entry_to_import_string(
        str(backend.get("entry", "app/routes.py")), str(backend.get("app", "app"))
    )


def prepare_environment(project_dir: Path) -> Settings:
    """Muat .env ke os.environ (tanpa menimpa) lalu validasi konfigurasi."""
    try:
        apply_dotenv(project_dir / ".env", os.environ)
        return load_settings(dotenv_path=None)
    except ConfigError as exc:
        raise ProjectError(str(exc)) from exc


def load_app(project_dir: Path, config: dict[str, Any]) -> SimPy:
    """Impor aplikasi pengguna dan kembalikan objek SimPy. Tidak meninggalkan modul di sys.modules."""
    module_name, _, attribute = backend_import_string(config).partition(":")
    top = module_name.split(".")[0]

    def owned(name: str) -> bool:
        return name == top or name.startswith(top + ".")

    saved = {name: mod for name, mod in sys.modules.items() if owned(name)}
    for name in saved:
        del sys.modules[name]
    location = str(project_dir)
    sys.path.insert(0, location)
    importlib.invalidate_caches()
    try:
        try:
            module = importlib.import_module(module_name)
        except ConfigError as exc:
            raise ProjectError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - tampilkan kesalahan kode pengguna dengan ramah
            raise ProjectError(
                f"Gagal mengimpor {module_name}: {type(exc).__name__}: {exc}"
            ) from exc
        app = getattr(module, attribute, None)
        if not isinstance(app, SimPy):
            raise ProjectError(f"'{attribute}' di {module_name} bukan objek SimPy.")
        return app
    finally:
        if location in sys.path:
            sys.path.remove(location)
        for name in [n for n in sys.modules if owned(n)]:
            del sys.modules[name]
        sys.modules.update(saved)
