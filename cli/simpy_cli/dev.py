"""Perintah `simpy dev`: server pengembangan (uvicorn + auto-reload) dan build frontend."""

from __future__ import annotations

import os
import signal
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from simpy.codegen import CodegenError
from simpy_cli.frontend import FrontendError, start_frontend_watch
from simpy_cli.generate import generate_client
from simpy_cli.project import (  # noqa: F401 - diekspor ulang untuk kompatibilitas
    ProjectError,
    backend_import_string,
    entry_to_import_string,
    load_project_config,
    prepare_environment,
)

DevError = ProjectError


def _terminate(signum: int, frame: Any) -> None:
    raise SystemExit(0)  # supaya blok finally (mematikan esbuild) tetap jalan


def _check_port(value: Any, source: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise DevError(f"{source} harus berupa angka 1-65535.")
    return value


def run_dev(
    project_dir: Path,
    *,
    host: str | None = None,
    port: int | None = None,
    reload: bool = True,
    runner: Callable[..., Any] | None = None,
    frontend: Callable[[Path, dict[str, Any]], Any] | None = start_frontend_watch,
    generate: Callable[[Path, dict[str, Any]], Any] | None = generate_client,
) -> None:
    project_dir = Path(project_dir)
    config = load_project_config(project_dir)
    backend = config.get("backend", {})
    import_string = backend_import_string(config)

    # Preflight: gagal cepat dengan pesan jelas bila secret belum diisi.
    settings = prepare_environment(project_dir)

    final_host = host or settings.host
    if port is not None:
        final_port = _check_port(port, "--port")
    elif "SIMPY_PORT" in os.environ:
        final_port = settings.port
    else:
        final_port = _check_port(backend.get("port", settings.port), "backend.port")

    if generate is not None:
        try:
            generate(project_dir, config)
        except CodegenError as exc:
            raise DevError(f"Gagal membuat klien API: {exc}") from exc

    if runner is None:
        try:
            import uvicorn
        except ImportError:
            raise DevError("uvicorn belum terpasang. Jalankan: pip install -e .") from None
        runner = uvicorn.run

    print(f"SimPy.ts dev server: http://{final_host}:{final_port}  (Ctrl+C untuk berhenti)")
    options: dict[str, Any] = {
        "host": final_host,
        "port": final_port,
        "reload": reload,
        "app_dir": str(project_dir),
    }
    if reload:
        options["reload_dirs"] = [str(project_dir)]

    watcher = None
    previous_handler = None
    can_trap = hasattr(signal, "SIGTERM") and threading.current_thread() is threading.main_thread()
    if can_trap:
        previous_handler = signal.signal(signal.SIGTERM, _terminate)
    try:
        if frontend is not None:
            try:
                watcher = frontend(project_dir, config)
            except FrontendError as exc:
                raise DevError(str(exc)) from exc
        runner(import_string, **options)
    finally:
        if can_trap:
            signal.signal(signal.SIGTERM, previous_handler or signal.SIG_DFL)
        if watcher is not None:
            watcher.terminate()
            try:
                watcher.wait(timeout=5)
            except Exception:  # noqa: BLE001 - pembersihan best-effort
                pass
