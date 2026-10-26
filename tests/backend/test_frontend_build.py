import json
from pathlib import PurePosixPath
from types import SimpleNamespace

import pytest

from simpy_cli.frontend import (
    FrontendError,
    build_frontend,
    discover_pages,
    esbuild_command,
    file_to_pattern,
    find_esbuild,
    generate_entry,
    prepare_frontend,
    start_frontend_watch,
)
from simpy_cli.main import main
from simpy_cli.scaffold import create_project


def write(path, text="export default () => null;\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fake_esbuild(project):
    write(project / "node_modules" / ".bin" / "esbuild", "#!/bin/sh\n")


def load_config(project):
    return json.loads((project / "simpy.config.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "rel, expected",
    [
        ("index.ts", "/"),
        ("about.ts", "/about"),
        ("users/index.ts", "/users"),
        ("users/[id].ts", "/users/:id"),
        ("blog/[slug]/edit.ts", "/blog/:slug/edit"),
    ],
)
def test_file_to_pattern(rel, expected):
    assert file_to_pattern(PurePosixPath(rel)) == expected


@pytest.mark.parametrize("rel", ["a.b.ts", "[__x].ts", "a b.ts", "[id.ts", "-a.ts", "x/ü.ts"])
def test_file_to_pattern_rejects_invalid_names(rel):
    with pytest.raises(FrontendError):
        file_to_pattern(PurePosixPath(rel))


def test_discover_pages_ordering_and_ignores(tmp_path):
    pages = tmp_path / "pages"
    for name in ["index.ts", "about.ts", "users/[id].ts", "users/new.ts", "404.ts"]:
        write(pages / name)
    for ignored in ["_helper.ts", "types.d.ts", "x.test.ts", "_private/a.ts", "readme.md"]:
        write(pages / ignored)
    result = discover_pages(tmp_path, "pages")
    assert [r.pattern for r in result.routes] == ["/", "/about", "/users/new", "/users/:id"]
    assert result.routes[3].file == "pages/users/[id].ts"
    assert result.not_found.file == "pages/404.ts"


def test_discover_pages_errors(tmp_path):
    with pytest.raises(FrontendError):
        discover_pages(tmp_path, "pages")  # folder tidak ada
    pages = tmp_path / "pages"
    write(pages / "404.ts")
    with pytest.raises(FrontendError):
        discover_pages(tmp_path, "pages")  # tidak ada halaman
    write(pages / "users.ts")
    write(pages / "users" / "index.ts")
    with pytest.raises(FrontendError) as exc:
        discover_pages(tmp_path, "pages")
    assert "bentrok" in str(exc.value)


def test_conflicting_dynamic_names_are_rejected(tmp_path):
    write(tmp_path / "pages" / "[id].ts")
    write(tmp_path / "pages" / "[slug].ts")
    with pytest.raises(FrontendError):
        discover_pages(tmp_path, "pages")


def test_invalid_page_name_is_rejected(tmp_path):
    write(tmp_path / "pages" / "bad name.ts")
    with pytest.raises(FrontendError):
        discover_pages(tmp_path, "pages")


def test_generate_entry(tmp_path):
    for name in ["index.ts", "users/[id].ts", "404.ts"]:
        write(tmp_path / "pages" / name)
    entry = generate_entry(discover_pages(tmp_path, "pages"))
    assert 'import { createApp } from "./frontend/index.ts";' in entry
    assert 'import page0 from "../pages/index.ts";' in entry
    assert 'import page1 from "../pages/users/[id].ts";' in entry
    assert 'import page2 from "../pages/404.ts";' in entry
    assert '{ pattern: "/users/:id", page: page1 },' in entry
    assert "notFound: page2," in entry
    assert entry.rstrip().endswith("}).start();")


def test_prepare_frontend_for_generated_project(tmp_path):
    project = create_project("demo", tmp_path)
    paths = prepare_frontend(project, load_config(project))
    assert (project / ".simpy" / "frontend" / "html.ts").is_file()
    assert (project / ".simpy" / "frontend" / "index.ts").is_file()
    assert not (project / ".simpy" / "frontend" / "__init__.py").exists()
    entry = paths.entry.read_text(encoding="utf-8")
    assert '"/about"' in entry and "notFound" in entry
    index = (project / "dist" / "index.html").read_text(encoding="utf-8")
    assert '<div id="app"></div>' in index
    assert 'src="/static/app.js"' in index
    assert "<title>demo</title>" in index
    assert "<script>" not in index  # tanpa script inline (siap CSP)


def test_index_title_is_escaped(tmp_path):
    project = create_project("demo", tmp_path)
    config = load_config(project)
    config["name"] = "a&<b>"
    prepare_frontend(project, config)
    assert "<title>a&amp;&lt;b&gt;</title>" in (project / "dist" / "index.html").read_text()


@pytest.mark.parametrize("key", ["pagesDir", "outDir"])
@pytest.mark.parametrize("bad", ["../x", "/abs", ".", ""])
def test_unsafe_directories_are_rejected(tmp_path, key, bad):
    project = create_project("demo", tmp_path)
    config = load_config(project)
    config["frontend"][key] = bad
    with pytest.raises(FrontendError):
        prepare_frontend(project, config)


def test_find_esbuild_and_command(tmp_path):
    with pytest.raises(FrontendError) as exc:
        find_esbuild(tmp_path)
    assert "npm install" in str(exc.value)
    fake_esbuild(tmp_path)
    out_js = tmp_path / "dist" / "app.js"
    cmd = esbuild_command(tmp_path, out_js)
    assert cmd[1:3] == [".simpy/entry.ts", "--bundle"]
    assert "--outfile=dist/app.js" in cmd
    assert "--minify" not in cmd and "--watch=forever" not in cmd
    assert "--minify" in esbuild_command(tmp_path, out_js, minify=True)
    assert "--watch=forever" in esbuild_command(tmp_path, out_js, watch=True)


def test_build_frontend_runs_esbuild(tmp_path):
    project = create_project("demo", tmp_path)
    fake_esbuild(project)
    calls = []

    def runner(cmd, cwd):
        calls.append((cmd, cwd))
        return SimpleNamespace(returncode=0)

    out = build_frontend(project, load_config(project), minify=True, runner=runner)
    assert out == project / "dist" / "app.js"
    assert calls[0][1] == project
    assert "--minify" in calls[0][0]


def test_build_frontend_failure_modes(tmp_path):
    project = create_project("demo", tmp_path)
    config = load_config(project)
    with pytest.raises(FrontendError):  # esbuild belum ada
        build_frontend(project, config, runner=lambda *a, **k: None)
    fake_esbuild(project)
    with pytest.raises(FrontendError):  # exit code != 0
        build_frontend(project, config, runner=lambda *a, **k: SimpleNamespace(returncode=1))

    def broken(*a, **k):
        raise OSError("tidak bisa dieksekusi")

    with pytest.raises(FrontendError):
        build_frontend(project, config, runner=broken)


def test_start_frontend_watch(tmp_path, capsys):
    project = create_project("demo", tmp_path)
    config = load_config(project)
    assert start_frontend_watch(project, config, popen=lambda *a, **k: 1 / 0) is None
    assert "npm install" in capsys.readouterr().out

    fake_esbuild(project)
    calls = []

    def popen(cmd, cwd):
        calls.append((cmd, cwd))
        return "proses"

    assert start_frontend_watch(project, config, popen=popen) == "proses"
    assert "--watch=forever" in calls[0][0]


def test_main_build_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["build"]) == 1
    assert "simpy.config.json" in capsys.readouterr().err
    project = create_project("demo", tmp_path)
    monkeypatch.chdir(project)
    assert main(["build"]) == 1
    assert "npm install" in capsys.readouterr().err
