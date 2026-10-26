import importlib.util
import sys

import pytest
from asgi_helper import Client

from simpy import ConfigError
from simpy_cli.scaffold import create_project


def load_routes(project, monkeypatch):
    name = "generated_routes"
    spec = importlib.util.spec_from_file_location(name, project / "app" / "routes.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def make_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SIMPY_SECRET_KEY", "rahasia-dev")
    monkeypatch.setenv("SIMPY_SESSION_DB", ":memory:")
    return Client(load_routes(create_project("demo", tmp_path), monkeypatch).app)


def test_generated_app_works_end_to_end(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    assert client.get("/api/hello").json() == {"message": "Hello from demo"}
    ok = client.post("/api/greet", json={"name": "Ani"})
    assert ok.json() == {"message": "Halo, Ani!"}
    assert client.post("/api/greet", json={"name": ""}).status == 422


def test_generated_app_has_security_features_on(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    resp = client.get("/api/hello")
    assert "script-src 'self'" in resp.headers["content-security-policy"]
    assert resp.headers["cache-control"] == "no-store"
    no_token = Client(client.app, auto_csrf=False).post("/api/greet", json={"name": "x"})
    assert no_token.status == 403


def test_generated_app_account_flow(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    creds = {"username": "ani", "password": "sandi-panjang-1"}
    assert client.get("/api/me").status == 401

    created = client.post("/api/register", json=creds)
    assert created.status == 201 and created.json()["username"] == "ani"
    assert client.get("/api/me").json()["username"] == "ani"
    assert client.post("/api/register", json=creds).status == 409

    assert client.post("/api/logout").status == 204
    assert client.get("/api/me").status == 401

    wrong = client.post("/api/login", json={**creds, "password": "sandi-salah-1"})
    assert wrong.status == 401 and wrong.json()["error"] == "invalid_credentials"
    unknown = client.post("/api/login", json={"username": "tidak-ada", "password": "sandi-panjang-1"})
    assert unknown.status == 401 and unknown.json() == wrong.json()
    assert client.post("/api/login", json=creds).status == 200
    assert client.get("/api/me").json()["username"] == "ani"


def test_generated_app_validates_credentials(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    for bad in (
        {"username": "a", "password": "sandi-panjang-1"},
        {"username": "ani baru", "password": "sandi-panjang-1"},
        {"username": "ani", "password": "pendek"},
        {"username": "ani", "password": "x" * 129},
    ):
        assert client.post("/api/register", json=bad).status == 422, bad


def test_generated_app_rate_limits_registration(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    statuses = [
        client.post("/api/register", json={"username": f"user{i}", "password": "sandi-panjang-1"}).status
        for i in range(6)
    ]
    assert statuses[:5] == [201] * 5 and statuses[5] == 429


def test_generated_app_refuses_to_start_without_secret(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SIMPY_SECRET_KEY", raising=False)
    project = create_project("demo", tmp_path)
    with pytest.raises(ConfigError):
        load_routes(project, monkeypatch)
