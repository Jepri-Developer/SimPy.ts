"""Entry point perintah `simpy`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from simpy import __version__
from simpy_cli.scaffold import ScaffoldError, create_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simpy", description="SimPy.ts: framework web Python + TypeScript."
    )
    parser.add_argument("--version", action="version", version=f"simpy {__version__}")
    sub = parser.add_subparsers(dest="command")

    create = sub.add_parser("create", help="buat project baru")
    create.add_argument("name", help="nama project (huruf kecil, angka, - atau _)")
    create.add_argument("--dir", default=".", help="folder induk (default: folder saat ini)")

    dev = sub.add_parser("dev", help="jalankan server pengembangan")
    dev.add_argument("--host", default=None, help="alamat bind (default: SIMPY_HOST / 127.0.0.1)")
    dev.add_argument("--port", type=int, default=None, help="port (default: config / 8000)")
    dev.add_argument("--no-reload", action="store_true", help="matikan auto-reload")

    sub.add_parser("generate", help="buat klien API TypeScript dari route Python")

    build = sub.add_parser("build", help="build frontend TypeScript ke folder dist/")
    build.add_argument("--minify", action="store_true", help="kecilkan ukuran bundle")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "create":
        try:
            target = create_project(args.name, Path(args.dir))
        except ScaffoldError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Project dibuat di {target}")
        print(f"Langkah berikutnya: cd {args.name}")
        return 0

    if args.command == "generate":
        from simpy.codegen import CodegenError
        from simpy_cli.generate import generate_client
        from simpy_cli.project import ProjectError, load_project_config, prepare_environment

        project = Path.cwd()
        try:
            config = load_project_config(project)
            prepare_environment(project)
            out = generate_client(project, config)
        except (ProjectError, CodegenError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Klien API dibuat: {out.relative_to(project).as_posix()}")
        return 0

    if args.command == "build":
        from simpy.codegen import CodegenError
        from simpy_cli.frontend import FrontendError, build_frontend, find_esbuild
        from simpy_cli.generate import generate_client
        from simpy_cli.project import ProjectError, load_project_config, prepare_environment

        project = Path.cwd()
        try:
            config = load_project_config(project)
            find_esbuild(project)  # gagal cepat bila esbuild belum terpasang
            prepare_environment(project)
            generate_client(project, config)
            out = build_frontend(project, config, minify=args.minify)
        except (ProjectError, FrontendError, CodegenError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Build selesai: {out.relative_to(project).as_posix()}")
        return 0

    if args.command == "dev":
        from simpy_cli.dev import DevError, run_dev

        try:
            run_dev(Path.cwd(), host=args.host, port=args.port, reload=not args.no_reload)
        except DevError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
