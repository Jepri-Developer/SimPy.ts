from asgi_helper import Client, call

from simpy import SimPy
from simpy.config import Settings
from simpy.security import CsrfService


def make_app(**kwargs):
    app = SimPy(**kwargs)

    @app.get("/safe")
    def safe():
        return {"ok": True}

    @app.post("/act")
    def act():
        return {"done": True}

    @app.delete("/del")
    def delete():
        return {"done": True}

    @app.post("/hook", csrf=False)
    def hook():
        return {"hook": True}

    return app


def test_csrf_cookie_is_issued_on_safe_requests():
    resp = call(make_app(), "GET", "/safe")
    cookie = resp.cookie("simpy_csrf")
    assert cookie is not None
    assert "SameSite=Lax" in cookie and "Path=/" in cookie
    assert "HttpOnly" not in cookie  # JS harus bisa membaca token
    assert "Secure" not in cookie


def test_valid_cookie_is_not_reissued():
    client = Client(make_app())
    assert client.get("/safe").cookie("simpy_csrf") is not None
    assert client.get("/safe").cookie("simpy_csrf") is None


def test_unsafe_request_without_token_is_rejected_and_gets_fresh_cookie():
    resp = call(make_app(), "POST", "/act", json={}, csrf=False)
    assert resp.status == 403
    assert resp.json()["error"] == "csrf_failed"
    assert resp.cookie("simpy_csrf") is not None


def test_unsafe_requests_pass_with_token():
    client = Client(make_app())
    assert client.post("/act", json={}).json() == {"done": True}
    assert client.delete("/del").status == 200


def test_safe_methods_never_need_a_token():
    assert call(make_app(), "GET", "/safe", csrf=False).status == 200


def test_header_and_cookie_must_both_be_present_and_equal():
    app = make_app()
    client = Client(app)
    client.get("/safe")
    token = client.csrf_token()
    # hanya header
    assert call(app, "POST", "/act", json={}, csrf=False, headers={"x-csrf-token": token}).status == 403
    # hanya cookie
    only_cookie = call(app, "POST", "/act", json={}, csrf=False, headers={"cookie": f"simpy_csrf={token}"})
    assert only_cookie.status == 403
    # header beda dari cookie
    other = CsrfService(b"x").issue("")
    mismatch = call(
        app, "POST", "/act", json={}, csrf=False,
        headers={"cookie": f"simpy_csrf={token}", "x-csrf-token": other},
    )
    assert mismatch.status == 403


def test_tampered_and_foreign_tokens_are_rejected():
    app = make_app(settings=Settings(env="test", secret_key="a" * 40))
    foreign = CsrfService(b"b" * 40).issue("")
    for token in (foreign, "abc.def", "tanpa-titik", "", "x" * 500, ".", "a."):
        resp = call(
            app, "POST", "/act", json={}, csrf=False,
            headers={"cookie": f"simpy_csrf={token}", "x-csrf-token": token},
        )
        assert resp.status == 403, token


def test_csrf_service_binding():
    service = CsrfService(b"secret")
    token = service.issue("sesi-1")
    assert service.valid(token, "sesi-1")
    assert not service.valid(token, "sesi-2")
    assert not service.valid(token, "")
    assert not service.valid(None) and not service.valid("")
    assert service.issue("") != service.issue("")  # nonce acak


def post_with(app, **headers):
    client = Client(app)
    return client.post("/act", json={}, headers=headers)


def test_origin_must_match_host():
    app = make_app()
    assert post_with(app, origin="http://testserver").status == 200
    assert post_with(app).status == 200  # tanpa Origin (klien non-browser)
    assert post_with(app, origin="http://evil.test").status == 403
    assert post_with(app, origin="null").status == 403
    assert post_with(app, origin="http://testserver.evil.test").status == 403


def test_allowed_origins():
    app = make_app(allowed_origins=["https://app.contoh.id"])
    assert post_with(app, origin="https://app.contoh.id").status == 200
    assert post_with(app, origin="https://lain.contoh.id").status == 403


def test_sec_fetch_site():
    app = make_app()
    assert post_with(app, **{"sec-fetch-site": "same-origin"}).status == 200
    for value in ("cross-site", "same-site"):
        assert post_with(app, **{"sec-fetch-site": value}).status == 403, value


def test_route_can_opt_out_of_csrf():
    assert call(make_app(), "POST", "/hook", json={}, csrf=False).json() == {"hook": True}


def test_production_cookie_is_secure_and_prefixed():
    settings = Settings(env="production", secret_key="k" * 40)
    resp = call(make_app(settings=settings), "GET", "/safe")
    cookie = resp.cookie("__Host-simpy_csrf")
    assert cookie is not None and "Secure" in cookie and "Path=/" in cookie
    assert "Domain" not in cookie
