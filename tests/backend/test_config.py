import pytest

from simpy import ConfigError, load_settings
from simpy.config import apply_dotenv, parse_dotenv

GOOD = {"SIMPY_SECRET_KEY": "rahasia-dev"}
STRONG = "x" * 40


def test_parse_dotenv():
    text = "# komentar\n\nA=1\nexport B = dua \nC=\"tiga\"\nD='empat'\n"
    assert parse_dotenv(text) == {"A": "1", "B": "dua", "C": "tiga", "D": "empat"}


def test_parse_dotenv_error_does_not_leak_line():
    with pytest.raises(ConfigError) as exc:
        parse_dotenv("rahasia123")
    assert "rahasia123" not in str(exc.value)


def test_missing_secret_fails():
    with pytest.raises(ConfigError) as exc:
        load_settings({}, dotenv_path=None)
    assert "SIMPY_SECRET_KEY" in str(exc.value)


def test_defaults_in_development():
    settings = load_settings(GOOD, dotenv_path=None)
    assert settings.env == "development"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.session_db == "instance/sessions.db"
    assert not settings.is_production


def test_dotenv_file_and_environment_precedence(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("SIMPY_SECRET_KEY=dari-file\nSIMPY_PORT=9000\n", encoding="utf-8")
    assert load_settings({}, dotenv_path=dotenv).secret_key == "dari-file"
    settings = load_settings({"SIMPY_SECRET_KEY": "dari-env"}, dotenv_path=dotenv)
    assert settings.secret_key == "dari-env"
    assert settings.port == 9000


def test_production_requires_strong_secret():
    for weak in ("pendek", "ganti-dengan-string-acak-panjang"):
        with pytest.raises(ConfigError):
            load_settings({"SIMPY_ENV": "production", "SIMPY_SECRET_KEY": weak}, dotenv_path=None)
    ok = load_settings({"SIMPY_ENV": "production", "SIMPY_SECRET_KEY": STRONG}, dotenv_path=None)
    assert ok.is_production


def test_invalid_env_and_port():
    with pytest.raises(ConfigError):
        load_settings({**GOOD, "SIMPY_ENV": "staging"}, dotenv_path=None)
    for bad in ("abc", "0", "70000"):
        with pytest.raises(ConfigError):
            load_settings({**GOOD, "SIMPY_PORT": bad}, dotenv_path=None)


def test_repr_hides_secret():
    settings = load_settings({"SIMPY_SECRET_KEY": "sangat-rahasia"}, dotenv_path=None)
    assert "sangat-rahasia" not in repr(settings)


def test_apply_dotenv_does_not_override(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("A=file\nB=file\n", encoding="utf-8")
    environ = {"A": "env"}
    apply_dotenv(dotenv, environ)
    assert environ == {"A": "env", "B": "file"}


def test_session_db_setting():
    custom = load_settings({**GOOD, "SIMPY_SESSION_DB": "data/s.db"}, dotenv_path=None)
    assert custom.session_db == "data/s.db"
    with pytest.raises(ConfigError):
        load_settings({**GOOD, "SIMPY_SESSION_DB": "  "}, dotenv_path=None)
