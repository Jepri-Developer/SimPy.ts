"""Build frontend: temukan halaman, hasilkan entry, panggil esbuild."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_STATIC_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_DYNAMIC_SEGMENT = re.compile(r"\[([A-Za-z][A-Za-z0-9_]*)\]")


class FrontendError(Exception):
    """Kesalahan yang aman ditampilkan ke pengguna."""


@dataclass(frozen=True)
class PageRoute:
    pattern: str
    file: str  # relatif ke project, gaya posix: "pages/users/[id].ts"


@dataclass(frozen=True)
class PageSet:
    routes: list[PageRoute]
    not_found: PageRoute | None


@dataclass(frozen=True)
class FrontendPaths:
    entry: Path
    out_dir: Path
    out_js: Path


def runtime_dir() -> Path:
    """Lokasi file runtime TypeScript (src/frontend atau paket terpasang)."""
    try:
        import simpy_frontend

        found = Path(simpy_frontend.__file__).resolve().parent
    except ImportError:
        found = Path(__file__).resolve().parents[2] / "src" / "frontend"
    if not (found / "index.ts").is_file():
        raise FrontendError(f"Runtime frontend tidak ditemukan di {found}.")
    return found


def _safe_relative_dir(value: str, label: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or str(path) in ("", "."):
        raise FrontendError(f"{label} '{value}' harus berupa folder relatif di dalam project.")
    return path.as_posix()


def file_to_pattern(rel: PurePosixPath) -> str:
    """'users/[id].ts' -> '/users/:id'; 'index.ts' -> '/'."""
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "index":
        parts = parts[:-1]
    out: list[str] = []
    for part in parts:
        dynamic = _DYNAMIC_SEGMENT.fullmatch(part)
        if _STATIC_SEGMENT.fullmatch(part):
            out.append(part)
        elif dynamic:
            out.append(":" + dynamic.group(1))
        else:
            raise FrontendError(
                f"Nama halaman tidak valid: '{rel}'. Pakai huruf/angka/'-'/'_', "
                "atau [nama] untuk parameter dinamis."
            )
    return "/" + "/".join(out)


def _sort_key(route: PageRoute) -> tuple[tuple[int, ...], str]:
    segments = [s for s in route.pattern.split("/") if s]
    return (tuple(1 if s.startswith(":") else 0 for s in segments), route.pattern)


def discover_pages(project_dir: Path, pages_dir: str) -> PageSet:
    root = project_dir / pages_dir
    if not root.is_dir():
        raise FrontendError(f"Folder halaman '{pages_dir}' tidak ditemukan.")
    routes: list[PageRoute] = []
    not_found: PageRoute | None = None
    shapes: dict[str, str] = {}

    for path in sorted(root.rglob("*.ts")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = PurePosixPath(path.relative_to(root).as_posix())
        if rel.name.endswith((".d.ts", ".test.ts")):
            continue
        if any(part.startswith("_") or part == "node_modules" for part in rel.parts):
            continue
        file = (PurePosixPath(pages_dir) / rel).as_posix()
        if str(rel) == "404.ts":
            not_found = PageRoute("/404", file)
            continue
        pattern = file_to_pattern(rel)
        shape = re.sub(r":\w+", ":", pattern)
        if shape in shapes:
            raise FrontendError(f"Route bentrok: '{shapes[shape]}' dan '{file}' ({pattern}).")
        shapes[shape] = file
        routes.append(PageRoute(pattern, file))

    if not routes:
        raise FrontendError(f"Tidak ada halaman di '{pages_dir}'. Buat minimal {pages_dir}/index.ts.")
    routes.sort(key=_sort_key)
    return PageSet(routes, not_found)


def generate_entry(pages: PageSet) -> str:
    ordered = list(pages.routes) + ([pages.not_found] if pages.not_found else [])
    lines = [
        "// Dibuat otomatis oleh `simpy build`. Jangan diedit.",
        'import { createApp } from "./frontend/index.ts";',
    ]
    for i, route in enumerate(ordered):
        lines.append(f"import page{i} from {json.dumps('../' + route.file)};")
    lines += ["", "createApp({", "  routes: ["]
    for i, route in enumerate(pages.routes):
        lines.append(f"    {{ pattern: {json.dumps(route.pattern)}, page: page{i} }},")
    lines.append("  ],")
    if pages.not_found:
        lines.append(f"  notFound: page{len(pages.routes)},")
    lines += ["}).start();", ""]
    return "\n".join(lines)


def index_html(title: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="id">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        "</head>\n<body>\n"
        '<div id="app"></div>\n'
        '<script type="module" src="/static/app.js"></script>\n'
        "</body>\n</html>\n"
    )


def prepare_frontend(project_dir: Path, config: dict[str, Any]) -> FrontendPaths:
    """Hasilkan .simpy/ (runtime + entry) dan dist/index.html. Belum menjalankan esbuild."""
    section = config.get("frontend", {})
    if not isinstance(section, dict):
        raise FrontendError("'frontend' di simpy.config.json harus berupa objek.")
    pages_dir = _safe_relative_dir(str(section.get("pagesDir", "pages")), "frontend.pagesDir")
    out_name = _safe_relative_dir(str(section.get("outDir", "dist")), "frontend.outDir")

    pages = discover_pages(project_dir, pages_dir)

    simpy_dir = project_dir / ".simpy"
    runtime_target = simpy_dir / "frontend"
    shutil.rmtree(runtime_target, ignore_errors=True)
    shutil.copytree(
        runtime_dir(),
        runtime_target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "__init__.py"),
    )
    entry = simpy_dir / "entry.ts"
    entry.write_text(generate_entry(pages), encoding="utf-8")

    out_dir = project_dir / out_name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(index_html(str(config.get("name", "SimPy.ts"))), "utf-8")
    return FrontendPaths(entry=entry, out_dir=out_dir, out_js=out_dir / "app.js")


def find_esbuild(project_dir: Path) -> Path:
    for name in ("esbuild", "esbuild.cmd"):
        candidate = project_dir / "node_modules" / ".bin" / name
        if candidate.exists():
            return candidate
    raise FrontendError("esbuild belum terpasang. Jalankan `npm install` di folder project.")


def esbuild_command(
    project_dir: Path, out_js: Path, *, minify: bool = False, watch: bool = False
) -> list[str]:
    command = [
        str(find_esbuild(project_dir)),
        ".simpy/entry.ts",
        "--bundle",
        f"--outfile={out_js.relative_to(project_dir).as_posix()}",
        "--format=esm",
        "--target=es2022",
        "--sourcemap",
    ]
    if minify:
        command.append("--minify")
    if watch:
        command.append("--watch=forever")
    return command


def build_frontend(
    project_dir: Path,
    config: dict[str, Any],
    *,
    minify: bool = False,
    runner: Callable[..., Any] = subprocess.run,
) -> Path:
    find_esbuild(project_dir)  # gagal cepat sebelum menulis file
    paths = prepare_frontend(project_dir, config)
    command = esbuild_command(project_dir, paths.out_js, minify=minify)
    try:
        result = runner(command, cwd=project_dir)
    except OSError as exc:
        raise FrontendError(f"Gagal menjalankan esbuild: {exc}") from exc
    if result.returncode != 0:
        raise FrontendError("Build gagal (lihat pesan esbuild di atas).")
    return paths.out_js


def start_frontend_watch(
    project_dir: Path,
    config: dict[str, Any],
    *,
    popen: Callable[..., Any] = subprocess.Popen,
) -> Any | None:
    """Jalankan esbuild --watch. None bila esbuild belum terpasang (backend tetap jalan)."""
    try:
        find_esbuild(project_dir)
    except FrontendError as exc:
        print(f"Peringatan: {exc} Frontend tidak di-build; hanya backend yang berjalan.")
        return None
    paths = prepare_frontend(project_dir, config)
    command = esbuild_command(project_dir, paths.out_js, watch=True)
    return popen(command, cwd=project_dir)
