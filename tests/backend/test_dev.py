import os

import pytest

from simpy_cli.dev import DevError, entry_to_import_string, run_dev
from simpy.codegen import CodegenError
from simpy_cli.frontend import FrontendError
from simpy_cli.main import main
from simpy_cli.scaffold import create_project


@pytest.fixture
def clean_environ(monkeypatch):
    monkeypatch.setattr(os, "environ", {})


def make_project(tmp_path, secret=True):
    project = create_project("demo", tmp_path)
    if secret:
        (project / ".env").write_text("SIMPY_SECRET_KEY=rahasia-dev\n", encoding="utf-8")
    return project


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, target, **options):
        self.calls.append((target, options))


def test_entry_to_import_string():
    assert entry_to_import_string("app/routes.py", "app") == "app.routes:app"
    assert entry_to_import_string("main.py", "server") == "main:server"


@pytest.mark.parametrize(
    "entry", ["../x.py", "/etc/x.py", "app/routes.txt", "a-b/c.py", "app/1x.py", ".py"]
)
def test_entry_rejects_unsafe_values(entry):
    with pytest.raises(DevError):
        entry_to_import_string(entry)


def test_invalid_app_name_is_rejected():
    with pytest.raises(DevError):
        entry_to_import_string("app/routes.py", "app; import os")


def test_missing_config_file(tmp_path, clean_environ):
    with pytest.raises(DevError) as exc:
        run_dev(tmp_path, runner=FakeRunner())
    assert "simpy.config.json" in str(exc.value)


def test_missing_secret_fails_fast(tmp_path, clean_environ):
    project = make_project(tmp_path, secret=False)
    runner = FakeRunner()
    with pytest.raises(DevError) as exc:
        run_dev(project, runner=runner)
    assert "SIMPY_SECRET_KEY" in str(exc.value)
    assert runner.calls == []


def test_run_dev_passes_expected_options(tmp_path, clean_environ):
    project = make_project(tmp_path)
    runner = FakeRunner()
    run_dev(project, runner=runner)
    target, options = runner.calls[0]
    assert target == "app.routes:app"
    assert options["host"] == "127.0.0.1"
    assert options["port"] == 8000
    assert options["reload"] is True
    assert options["reload_dirs"] == [str(project)]
    assert options["app_dir"] == str(project)
    assert os.environ["SIMPY_SECRET_KEY"] == "rahasia-dev"


def test_flags_override_and_no_reload(tmp_path, clean_environ):
    project = make_project(tmp_path)
    runner = FakeRunner()
    run_dev(project, host="0.0.0.0", port=9001, reload=False, runner=runner)
    _, options = runner.calls[0]
    assert (options["host"], options["port"], options["reload"]) == ("0.0.0.0", 9001, False)
    assert "reload_dirs" not in options


def test_invalid_port_flag(tmp_path, clean_environ):
    project = make_project(tmp_path)
    with pytest.raises(DevError):
        run_dev(project, port=70000, runner=FakeRunner())


def test_main_dev_reports_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["dev"]) == 1
    assert "simpy.config.json" in capsys.readouterr().err


class FakeProcess:
    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


def test_frontend_watcher_is_started_and_stopped(tmp_path, clean_environ):
    project = make_project(tmp_path)
    proc = FakeProcess()
    runner = FakeRunner()
    run_dev(project, runner=runner, frontend=lambda directory, config: proc)
    assert runner.calls and proc.terminated


def test_frontend_watcher_is_stopped_when_server_crashes(tmp_path, clean_environ):
    project = make_project(tmp_path)
    proc = FakeProcess()

    def crashing(target, **options):
        raise RuntimeError("server mati")

    with pytest.raises(RuntimeError):
        run_dev(project, runner=crashing, frontend=lambda directory, config: proc)
    assert proc.terminated


def test_frontend_error_becomes_dev_error(tmp_path, clean_environ):
    project = make_project(tmp_path)
    runner = FakeRunner()

    def failing(directory, config):
        raise FrontendError("halaman bentrok")

    with pytest.raises(DevError) as exc:
        run_dev(project, runner=runner, frontend=failing)
    assert "bentrok" in str(exc.value)
    assert runner.calls == []


def test_missing_esbuild_does_not_block_backend(tmp_path, clean_environ, capsys):
    project = make_project(tmp_path)
    runner = FakeRunner()
    run_dev(project, runner=runner)  # frontend default: esbuild tidak ada
    assert runner.calls
    assert "npm install" in capsys.readouterr().out


def test_client_is_generated_before_server_starts(tmp_path, clean_environ):
    project = make_project(tmp_path)
    order = []
    runner = FakeRunner()

    def fake_generate(directory, config):
        order.append("generate")
        assert runner.calls == []

    run_dev(project, runner=runner, frontend=None, generate=fake_generate)
    assert order == ["generate"] and runner.calls


def test_codegen_error_becomes_dev_error(tmp_path, clean_environ):
    project = make_project(tmp_path)
    runner = FakeRunner()

    def failing(directory, config):
        raise CodegenError("nama bentrok")

    with pytest.raises(DevError) as exc:
        run_dev(project, runner=runner, frontend=None, generate=failing)
    assert "nama bentrok" in str(exc.value)
    assert runner.calls == []


def test_real_generation_writes_client(tmp_path, clean_environ):
    project = make_project(tmp_path)
    run_dev(project, runner=FakeRunner(), frontend=None)
    assert "request<Message>" in (project / ".simpy" / "api.ts").read_text(encoding="utf-8")


def test_sigterm_still_stops_the_frontend_watcher(tmp_path, clean_environ):
    import signal

    if not hasattr(signal, "SIGTERM"):
        return
    project = make_project(tmp_path)
    proc = FakeProcess()
    before = signal.getsignal(signal.SIGTERM)

    def killed(target, **options):
        signal.raise_signal(signal.SIGTERM)

    with pytest.raises(SystemExit):
        run_dev(project, runner=killed, frontend=lambda directory, config: proc, generate=None)
    assert proc.terminated
    assert signal.getsignal(signal.SIGTERM) == before  # handler dikembalikan
