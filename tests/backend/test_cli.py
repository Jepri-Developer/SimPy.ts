import json

import pytest

from simpy import __version__
from simpy_cli.main import main
from simpy_cli.scaffold import ScaffoldError, create_project, validate_name


def test_create_project_makes_expected_files(tmp_path):
    target = create_project("myapp", tmp_path)
    for rel in [
        "app/__init__.py",
        "app/routes.py",
        "pages/index.ts",
        "pages/about.ts",
        "pages/404.ts",
        "tsconfig.json",
        ".env.example",
        ".gitignore",
        "simpy.config.json",
        "package.json",
        "README.md",
    ]:
        assert (target / rel).is_file(), rel


def test_name_is_substituted_everywhere(tmp_path):
    target = create_project("myapp", tmp_path)
    config = json.loads((target / "simpy.config.json").read_text(encoding="utf-8"))
    assert config["name"] == "myapp"
    assert json.loads((target / "package.json").read_text(encoding="utf-8"))["name"] == "myapp"
    for f in target.rglob("*"):
        if f.is_file():
            assert "{{name}}" not in f.read_text(encoding="utf-8"), f


def test_refuses_non_empty_directory(tmp_path):
    (tmp_path / "myapp").mkdir()
    (tmp_path / "myapp" / "x.txt").write_text("x")
    with pytest.raises(ScaffoldError):
        create_project("myapp", tmp_path)


def test_allows_existing_empty_directory(tmp_path):
    (tmp_path / "myapp").mkdir()
    assert create_project("myapp", tmp_path).is_dir()


@pytest.mark.parametrize("bad", ["", "App", "1app", "../evil", "a b", "a/b", "x" * 65])
def test_invalid_names_rejected(bad):
    with pytest.raises(ScaffoldError):
        validate_name(bad)


def test_cli_create_success(tmp_path, capsys):
    assert main(["create", "demo", "--dir", str(tmp_path)]) == 0
    assert (tmp_path / "demo" / "app" / "routes.py").exists()
    assert "demo" in capsys.readouterr().out


def test_cli_create_invalid_name_returns_error(tmp_path, capsys):
    assert main(["create", "Bad Name", "--dir", str(tmp_path)]) == 1
    assert "tidak valid" in capsys.readouterr().err


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_unwritable_target_gives_friendly_error(tmp_path, monkeypatch, capsys):
    from pathlib import Path

    def deny(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "mkdir", deny)
    assert main(["create", "demo", "--dir", str(tmp_path)]) == 1
    assert "Permission denied" in capsys.readouterr().err
