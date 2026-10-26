import pytest
from asgi_helper import Client, call

from simpy import SimPy
from simpy.config import Settings
from simpy.security import (
    DEFAULT_CSP,
    CsrfService,
    RateLimiter,
    SecurityMiddleware,
    build_cookie,
    client_ip,
    cookie_name,
    parse_cookies,
    parse_rate,
    retry_after_seconds,
)


def make_app(**kwargs):
    app = SimPy(**kwargs)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/api/x")
    def x():
        return {}

    @app.post("/limited", rate_limit="2/minute")
    def limited():
        return {"ok": True}

    @app.post("/other")
    def other():
        return {"ok": True}

    return app


def production_settings():
    return Settings(env="production", secret_key="k" * 40, session_db=":memory:")


# --- secure headers ------------------------------------------------------------------------


def test_security_headers_on_every_response():
    app = make_app()
    for path in ("/ping", "/tidak-ada", "/api/x"):
        resp = call(app, "GET", path)
        assert resp.headers["content-security-policy"] == DEFAULT_CSP, path
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert resp.headers["cross-origin-opener-policy"] == "same-origin"
        assert "strict-transport-security" not in resp.headers


def test_csp_is_strict():
    assert "script-src 'self'" in DEFAULT_CSP
    assert "unsafe-inline" not in DEFAULT_CSP and "unsafe-eval" not in DEFAULT_CSP
    assert "frame-ancestors 'none'" in DEFAULT_CSP and "object-src 'none'" in DEFAULT_CSP


def test_api_responses_are_not_cached():
    app = make_app()
    assert call(app, "GET", "/api/x").headers["cache-control"] == "no-store"
    assert "cache-control" not in call(app, "GET", "/ping").headers


def test_hsts_only_in_production():
    resp = call(make_app(settings=production_settings()), "GET", "/ping")
    assert "max-age=31536000" in resp.headers["strict-transport-security"]


def test_custom_csp():
    resp = call(make_app(csp="default-src 'none'"), "GET", "/ping")
    assert resp.headers["content-security-policy"] == "default-src 'none'"


def test_existing_headers_are_not_overridden_or_duplicated():
    async def inner(scope, receive, send):
        await send(
            {"type": "http.response.start", "status": 200, "headers": [(b"x-frame-options", b"SAMEORIGIN")]}
        )
        await send({"type": "http.response.body", "body": b""})

    app = SecurityMiddleware(
        inner, csp=DEFAULT_CSP, production=False, secure_cookies=False,
        limiter=None, csrf=CsrfService(b"s"),
    )
    resp = call(app, "GET", "/")
    frame = [v for k, v in resp.raw_headers if k == "x-frame-options"]
    assert frame == ["SAMEORIGIN"]


# --- rate limit ------------------------------------------------------------------------------


def test_parse_rate():
    assert parse_rate("5/minute") == (5, 60.0)
    assert parse_rate("100/Hours") == (100, 3600.0)
    assert parse_rate("1/second") == (1, 1.0)
    for bad in ("", "5", "5/day", "0/minute", "-1/minute", "abc/minute", "5/minute/x"):
        with pytest.raises(ValueError):
            parse_rate(bad)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_rate_limiter_sliding_window():
    clock = Clock()
    limiter = RateLimiter(2, 60, clock=clock)
    assert limiter.hit("a") is None
    clock.now += 10
    assert limiter.hit("a") is None
    wait = limiter.hit("a")
    assert wait == pytest.approx(50.0)
    assert retry_after_seconds(wait) == 50
    clock.now += 50.5  # request pertama keluar dari jendela
    assert limiter.hit("a") is None
    assert limiter.hit("a") is not None


def test_rate_limiter_keys_are_independent():
    limiter = RateLimiter(1, 60, clock=Clock())
    assert limiter.hit("a") is None
    assert limiter.hit("b") is None
    assert limiter.hit("a") is not None


def test_rate_limiter_memory_is_bounded():
    clock = Clock()
    limiter = RateLimiter(5, 60, clock=clock, max_keys=100)
    for i in range(1000):
        limiter.hit(f"ip-{i}")
    assert len(limiter._events) <= 100
    clock.now += 120  # semua kedaluwarsa, purge membersihkan
    limiter.hit("baru")
    assert len(limiter._events) <= 100


def test_retry_after_is_at_least_one_second():
    assert retry_after_seconds(0.0) == 1
    assert retry_after_seconds(0.2) == 1
    assert retry_after_seconds(1.1) == 2


def test_global_rate_limit_returns_429_with_headers():
    app = make_app(rate_limit="3/minute")
    client = Client(app)
    assert [client.get("/ping").status for _ in range(3)] == [200, 200, 200]
    blocked = client.get("/ping")
    assert blocked.status == 429
    assert blocked.json()["error"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.headers["x-content-type-options"] == "nosniff"


def test_global_rate_limit_is_per_ip():
    app = make_app(rate_limit="1/minute")
    assert call(app, "GET", "/ping", ip="1.1.1.1").status == 200
    assert call(app, "GET", "/ping", ip="1.1.1.1").status == 429
    assert call(app, "GET", "/ping", ip="2.2.2.2").status == 200


def test_rate_limit_can_be_disabled():
    app = make_app(rate_limit=None)
    client = Client(app)
    assert all(client.get("/ping").status == 200 for _ in range(400))


def test_route_rate_limit():
    client = Client(make_app())
    assert client.post("/limited", json={}).status == 200
    assert client.post("/limited", json={}).status == 200
    blocked = client.post("/limited", json={})
    assert blocked.status == 429
    assert blocked.json()["error"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) >= 1
    assert client.post("/other", json={}).status == 200  # route lain tidak terpengaruh


def test_invalid_route_rate_limit_fails_at_definition():
    app = SimPy()
    with pytest.raises(ValueError):
        app.get("/x", rate_limit="banyak")


# --- IP klien -----------------------------------------------------------------------------------


def scope_with(peer, forwarded=None):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return {"client": (peer, 1), "headers": headers}


def test_client_ip_ignores_forwarded_header_by_default():
    assert client_ip(scope_with("9.9.9.9", "6.6.6.6")) == "9.9.9.9"


def test_client_ip_trusts_only_configured_proxy_hops():
    scope = scope_with("10.0.0.1", "6.6.6.6, 7.7.7.7")
    assert client_ip(scope, 1) == "7.7.7.7"
    assert client_ip(scope, 2) == "6.6.6.6"
    assert client_ip(scope, 3) == "10.0.0.1"  # header lebih pendek dari hops: pakai peer
    assert client_ip({"headers": []}) == "unknown"


def test_spoofed_forwarded_header_cannot_bypass_limit():
    app = make_app(rate_limit="1/minute")
    assert call(app, "GET", "/ping", headers={"x-forwarded-for": "1.1.1.1"}).status == 200
    assert call(app, "GET", "/ping", headers={"x-forwarded-for": "2.2.2.2"}).status == 429


# --- cookie ----------------------------------------------------------------------------------------


def test_parse_cookies_first_wins_and_strips_quotes():
    assert parse_cookies('a=1; b="dua"; a=3; kosong; =x') == {"a": "1", "b": "dua"}
    assert parse_cookies("") == {}


def test_build_cookie_attributes():
    cookie = build_cookie("simpy_session", "abc-DEF_1.2", max_age=60, http_only=True, secure=True)
    assert cookie == "simpy_session=abc-DEF_1.2; Path=/; Max-Age=60; SameSite=Lax; HttpOnly; Secure"
    plain = build_cookie("simpy_csrf", "t.s", max_age=5, http_only=False, secure=False)
    assert "HttpOnly" not in plain and "Secure" not in plain


@pytest.mark.parametrize("name, value", [("a b", "x"), ("a;", "x"), ("a", "x;y"), ("a", "x\r\nSet-Cookie: z=1")])
def test_build_cookie_rejects_injection(name, value):
    with pytest.raises(ValueError):
        build_cookie(name, value, max_age=1, http_only=True, secure=False)


def test_cookie_name_prefix():
    assert cookie_name("simpy_session", True) == "__Host-simpy_session"
    assert cookie_name("simpy_session", False) == "simpy_session"
