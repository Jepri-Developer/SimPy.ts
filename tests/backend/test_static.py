import pytest
from asgi_helper import call

from simpy import SimPy


def make_app(tmp_path):
    dist = tmp_path / "dist"
    (dist / "sub").mkdir(parents=True)
    (dist / "index.html").write_text('<div id="app"></div>', encoding="utf-8")
    (dist / "app.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "sub" / "x.css").write_text("body{}", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("rahasia", encoding="utf-8")
    app = SimPy()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    app.serve_frontend(dist)

    @app.get("/api/later")
    def later():
        return {"later": True}

    return app


def test_root_and_client_routes_serve_index(tmp_path):
    app = make_app(tmp_path)
    for path in ("/", "/about", "/users/42"):
        resp = call(app, "GET", path)
        assert resp.status == 200, path
        assert resp.text == '<div id="app"></div>'
        assert resp.headers["content-type"].startswith("text/html")
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-content-type-options"] == "nosniff"


def test_static_files_and_content_types(tmp_path):
    app = make_app(tmp_path)
    js = call(app, "GET", "/static/app.js")
    assert js.status == 200 and js.text == "console.log(1)"
    assert js.headers["content-type"].startswith("text/javascript")
    css = call(app, "GET", "/static/sub/x.css")
    assert css.headers["content-type"].startswith("text/css")


def test_missing_static_file_is_json_404(tmp_path):
    resp = call(make_app(tmp_path), "GET", "/static/missing.js")
    assert resp.status == 404 and resp.json()["error"] == "not_found"


def test_path_traversal_is_blocked(tmp_path):
    app = make_app(tmp_path)
    for path in ("/static/../secret.txt", "/static/%2e%2e/secret.txt", "/static//etc/passwd"):
        resp = call(app, "GET", path)
        assert resp.status == 404, path
        assert "rahasia" not in resp.text


def test_symlink_escape_is_blocked(tmp_path):
    app = make_app(tmp_path)
    try:
        (tmp_path / "dist" / "link.txt").symlink_to(tmp_path / "secret.txt")
    except OSError:
        return  # platform tanpa symlink
    resp = call(app, "GET", "/static/link.txt")
    assert resp.status == 404 and "rahasia" not in resp.text


def test_api_routes_win_and_unknown_api_is_json(tmp_path):
    app = make_app(tmp_path)
    assert call(app, "GET", "/api/ping").json() == {"ok": True}
    assert call(app, "GET", "/api/later").json() == {"later": True}
    unknown = call(app, "GET", "/api/unknown")
    assert unknown.status == 404 and unknown.json()["error"] == "not_found"
    assert call(app, "GET", "/api").status == 404


def test_paths_with_extension_are_not_spa_routes(tmp_path):
    assert call(make_app(tmp_path), "GET", "/favicon.ico").status == 404


def test_only_get_is_served(tmp_path):
    assert call(make_app(tmp_path), "POST", "/", json={}).status == 405


def test_frontend_not_built(tmp_path):
    app = SimPy()
    app.serve_frontend(tmp_path / "nope")
    resp = call(app, "GET", "/")
    assert resp.status == 404
    assert resp.json()["error"] == "frontend_not_built"


def test_serve_frontend_misuse(tmp_path):
    app = SimPy()
    app.serve_frontend(tmp_path)
    with pytest.raises(RuntimeError):
        app.serve_frontend(tmp_path)
    call(app, "GET", "/")
    with pytest.raises(RuntimeError):
        SimPy.serve_frontend(app, tmp_path)
