import pytest
from asgi_helper import call

from simpy import HTTPError, Schema, SimPy, field


class Item(Schema):
    name: str = field(min_length=1, max_length=20)
    qty: int = field(default=1, ge=1)


def make_app(**kwargs):
    app = SimPy(**kwargs)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/async")
    async def async_ping():
        return {"async": True}

    @app.post("/items")
    async def create_item(item: Item):
        return item, 201

    @app.get("/users/{user_id:int}")
    def get_user(user_id: int, request):
        return {"id": user_id, "method": request.method}

    @app.get("/nothing")
    def nothing():
        return None

    @app.get("/forbidden")
    def forbidden():
        raise HTTPError(403, "dilarang")

    @app.get("/boom")
    def boom():
        raise RuntimeError("rahasia internal")

    return app


JSON = {"content-type": "application/json"}


def test_get_sync_and_async_handlers():
    app = make_app()
    assert call(app, "GET", "/ping").json() == {"ok": True}
    assert call(app, "GET", "/async").json() == {"async": True}


def test_post_valid_body_returns_schema_with_status():
    resp = call(make_app(), "POST", "/items", json={"name": "pensil"})
    assert resp.status == 201
    assert resp.json() == {"name": "pensil", "qty": 1}


def test_validation_error_is_422_with_details():
    resp = call(make_app(), "POST", "/items", json={"name": "", "extra": 1})
    assert resp.status == 422
    body = resp.json()
    assert body["error"] == "validation_error"
    locs = {tuple(d["loc"]) for d in body["details"]}
    assert locs == {("name",), ("extra",)}


def test_invalid_json_is_400():
    for raw in (b"{", b"", b'{"name": "a", "qty": NaN}', b"\xff\xfe"):
        resp = call(make_app(), "POST", "/items", body=raw, headers=JSON)
        assert resp.status == 400, raw


def test_deeply_nested_json_is_400():
    raw = b"[" * 100_000 + b"]" * 100_000
    assert call(make_app(), "POST", "/items", body=raw, headers=JSON).status == 400


def test_content_type_must_be_json():
    app = make_app()
    resp = call(app, "POST", "/items", body=b'{"name": "a"}', headers={"content-type": "text/plain"})
    assert resp.status == 415
    assert call(app, "POST", "/items", body=b'{"name": "a"}').status == 415


def test_content_type_with_charset_is_accepted():
    resp = call(
        make_app(),
        "POST",
        "/items",
        body=b'{"name": "a"}',
        headers={"content-type": "application/json; charset=utf-8"},
    )
    assert resp.status == 201


def test_body_size_limit_by_content_length():
    app = make_app(max_body_bytes=50)
    resp = call(app, "POST", "/items", json={"name": "a", "pad": "x" * 100})
    assert resp.status == 413


def test_body_size_limit_when_content_length_lies():
    app = make_app(max_body_bytes=100)
    resp = call(
        app, "POST", "/items", body=b'{"name": "' + b"a" * 200 + b'"}',
        headers={**JSON, "content-length": "5"},
    )
    assert resp.status == 413


def test_path_params_and_request_injection():
    assert call(make_app(), "GET", "/users/7").json() == {"id": 7, "method": "GET"}


def test_none_returns_204():
    resp = call(make_app(), "GET", "/nothing")
    assert resp.status == 204 and resp.body == b""


def test_http_error_from_handler():
    resp = call(make_app(), "GET", "/forbidden")
    assert resp.status == 403
    assert resp.json() == {"error": "forbidden", "message": "dilarang"}


def test_unknown_route_and_method_return_json_errors():
    app = make_app()
    missing = call(app, "GET", "/tidak-ada")
    assert missing.status == 404 and missing.json()["error"] == "not_found"
    wrong = call(app, "POST", "/ping", json={})
    assert wrong.status == 405 and wrong.json()["error"] == "method_not_allowed"


def test_unhandled_exception_does_not_leak_details():
    resp = call(make_app(), "GET", "/boom", raise_app_exceptions=False)
    assert resp.status == 500
    assert resp.json()["error"] == "internal_error"
    assert "rahasia internal" not in resp.text


def test_duplicate_route_is_rejected():
    app = SimPy()

    @app.get("/a")
    def first():
        return {}

    with pytest.raises(ValueError):

        @app.get("/a")
        def second():
            return {}


def test_unresolvable_parameter_fails_at_definition():
    app = SimPy()
    with pytest.raises(TypeError):

        @app.get("/x")
        def handler(unknown):
            return {}


def test_only_one_body_parameter():
    app = SimPy()
    with pytest.raises(TypeError):

        @app.post("/x")
        def handler(a: Item, b: Item):
            return {}


def test_cannot_add_routes_after_serving():
    app = make_app()
    call(app, "GET", "/ping")
    with pytest.raises(RuntimeError):

        @app.get("/late")
        def late():
            return {}


def test_invalid_configuration():
    with pytest.raises(ValueError):
        SimPy(max_body_bytes=0)
    app = SimPy()
    with pytest.raises(ValueError):
        app.route("tanpa-slash", methods=["GET"])
    with pytest.raises(ValueError):
        app.route("/x", methods=["TRACE"])
