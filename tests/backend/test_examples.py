"""Contoh di examples/ harus selalu identik dengan hasil `simpy create` dan benar-benar jalan."""

import importlib.util
import os
import shutil
import sys
from pathlib import Path

from asgi_helper import Client

from simpy_cli.generate import generate_client
from simpy_cli.project import load_project_config, prepare_environment
from simpy_cli.scaffold import create_project

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "hello-world"
GENERATED_DIRS = {"node_modules", ".simpy", "dist", "instance", "__pycache__"}


def tree(root: Path) -> dict[str, bytes]:
    files = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not (set(rel.parts) & GENERATED_DIRS) and rel.name != ".env":
            files[rel.as_posix()] = path.read_bytes()
    return files


def test_example_matches_scaffold_output(tmp_path):
    generated = tree(create_project("hello-world", tmp_path))
    example = tree(EXAMPLE)
    assert sorted(example) == sorted(generated)
    differing = [name for name in generated if example[name] != generated[name]]
    assert differing == [], f"jalankan ulang `simpy create hello-world --dir examples`: {differing}"


def copy_example(tmp_path):
    target = tmp_path / "hello-world"
    shutil.copytree(EXAMPLE, target, ignore=shutil.ignore_patterns(*GENERATED_DIRS))
    return target


def test_example_required_files_exist():
    for name in (".env.example", ".gitignore", "README.md", "package.json", "tsconfig.json",
                 "simpy.config.json", "app/routes.py", "pages/index.ts"):
        assert (EXAMPLE / name).is_file(), name
    assert not (EXAMPLE / ".env").exists()


def test_example_runs_end_to_end(tmp_path, monkeypatch):
    project = copy_example(tmp_path)
    monkeypatch.chdir(project)
    monkeypatch.setenv("SIMPY_SECRET_KEY", "rahasia-dev")
    monkeypatch.setenv("SIMPY_SESSION_DB", ":memory:")

    spec = importlib.util.spec_from_file_location("example_routes", project / "app" / "routes.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "example_routes", module)
    spec.loader.exec_module(module)

    client = Client(module.app)
    assert client.get("/api/hello").json() == {"message": "Hello from hello-world"}
    assert client.post("/api/greet", json={"name": "Ani"}).json() == {"message": "Halo, Ani!"}
    assert client.post("/api/greet", json={"name": ""}).status == 422
    creds = {"username": "ani", "password": "sandi-panjang-1"}
    assert client.post("/api/register", json=creds).status == 201
    assert client.get("/api/me").json()["username"] == "ani"
    assert client.post("/api/logout").status == 204
    assert client.get("/api/me").status == 401
    assert "script-src 'self'" in client.get("/api/hello").headers["content-security-policy"]


def test_example_client_generation(tmp_path, monkeypatch):
    project = copy_example(tmp_path)
    monkeypatch.setattr(os, "environ", {"SIMPY_SECRET_KEY": "rahasia-dev"})
    prepare_environment(project)
    out = generate_client(project, load_project_config(project))
    assert 'greet: (body: GreetInput) => request<Message>("POST", "/api/greet", { body }),' in out.read_text()
