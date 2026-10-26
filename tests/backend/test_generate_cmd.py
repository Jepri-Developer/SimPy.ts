import os
import sys

import pytest

from simpy.codegen import CodegenError
from simpy_cli.generate import generate_client
from simpy_cli.main import main
from simpy_cli.project import ProjectError, load_app, load_project_config, prepare_environment
from simpy_cli.scaffold import create_project


@pytest.fixture
def clean_environ(monkeypatch):
    monkeypatch.setattr(os, "environ", {})


def make_project(tmp_path, secret=True):
    project = create_project("demo", tmp_path)
    if secret:
        (project / ".env").write_text("SIMPY_SECRET_KEY=rahasia-dev\n", encoding="utf-8")
    return project


def test_generate_client_for_template_project(tmp_path, clean_environ):
    project = make_project(tmp_path)
    prepare_environment(project)
    out = generate_client(project, load_project_config(project))
    assert out == project / ".simpy" / "api.ts"
    text = out.read_text(encoding="utf-8")
    assert "export interface Message {\n  message: string;\n}" in text
    assert "export interface GreetInput {\n  name: string;\n}" in text
    assert 'hello: () => request<Message>("GET", "/api/hello"),' in text
    assert 'greet: (body: GreetInput) => request<Message>("POST", "/api/greet", { body }),' in text
    assert 'me: () => request<UserOut>("GET", "/api/me"),' in text
    assert 'signOut: () => request<void>("POST", "/api/logout"),' in text
    assert 'register: (body: Credentials) => request<UserOut>("POST", "/api/register", { body }),' in text


def test_generate_does_not_leave_modules_behind(tmp_path, clean_environ):
    project = make_project(tmp_path)
    prepare_environment(project)
    config = load_project_config(project)
    before = set(sys.modules)
    path_before = list(sys.path)
    generate_client(project, config)
    generate_client(project, config)  # kedua kali tetap bersih dan idempoten
    assert set(sys.modules) == before
    assert sys.path == path_before


def test_load_app_errors(tmp_path, clean_environ):
    project = make_project(tmp_path)
    prepare_environment(project)
    config = load_project_config(project)

    missing = {**config, "backend": {**config["backend"], "entry": "app/tidak_ada.py"}}
    with pytest.raises(ProjectError) as exc:
        load_app(project, missing)
    assert "tidak_ada" in str(exc.value)

    wrong_name = {**config, "backend": {**config["backend"], "app": "bukan_app"}}
    with pytest.raises(ProjectError) as exc:
        load_app(project, wrong_name)
    assert "bukan objek SimPy" in str(exc.value)


def test_load_app_reports_errors_in_user_code(tmp_path, clean_environ):
    project = make_project(tmp_path)
    prepare_environment(project)
    (project / "app" / "routes.py").write_text("raise RuntimeError('rusak')\n", encoding="utf-8")
    with pytest.raises(ProjectError) as exc:
        load_app(project, load_project_config(project))
    assert "rusak" in str(exc.value)


def test_missing_secret_is_a_project_error(tmp_path, clean_environ):
    project = make_project(tmp_path, secret=False)
    with pytest.raises(ProjectError) as exc:
        prepare_environment(project)
    assert "SIMPY_SECRET_KEY" in str(exc.value)


def test_codegen_error_in_user_routes(tmp_path, clean_environ):
    project = make_project(tmp_path)
    prepare_environment(project)
    (project / "app" / "routes.py").write_text(
        "from simpy import Schema, SimPy\n"
        "app = SimPy()\n"
        "class Body(Schema):\n    a: int\n"
        "@app.get('/x')\n"
        "def x(data: Body):\n    return {}\n",
        encoding="utf-8",
    )
    with pytest.raises(CodegenError):
        generate_client(project, load_project_config(project))


def test_main_generate(tmp_path, monkeypatch, capsys, clean_environ):
    project = make_project(tmp_path)
    monkeypatch.chdir(project)
    assert main(["generate"]) == 0
    assert (project / ".simpy" / "api.ts").is_file()
    assert ".simpy/api.ts" in capsys.readouterr().out


def test_main_generate_errors(tmp_path, monkeypatch, capsys, clean_environ):
    monkeypatch.chdir(tmp_path)
    assert main(["generate"]) == 1
    assert "simpy.config.json" in capsys.readouterr().err
    project = make_project(tmp_path, secret=False)
    monkeypatch.chdir(project)
    assert main(["generate"]) == 1
    assert "SIMPY_SECRET_KEY" in capsys.readouterr().err
