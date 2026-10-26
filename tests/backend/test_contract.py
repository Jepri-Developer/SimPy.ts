import pytest
from asgi_helper import call
from starlette.responses import JSONResponse, Response

from simpy import HTTPError, Schema, SimPy


class Msg(Schema):
    message: str


class Item(Schema):
    name: str
    qty: int = 1


def make_app():
    app = SimPy()

    @app.get("/ok")
    def ok() -> Msg:
        return {"message": "hi"}

    @app.get("/instance")
    def instance() -> Msg:
        return Msg.validate({"message": "x"})

    @app.get("/extra")
    def extra() -> Msg:
        return {"message": "hi", "secret": "bocor"}

    @app.get("/none")
    def none() -> Msg:
        return None

    @app.get("/wrong")
    def wrong() -> Msg:
        return "teks"

    @app.get("/list")
    def listing() -> list[Msg]:
        return [{"message": "a"}, Msg.validate({"message": "b"})]

    @app.get("/badlist")
    def badlist() -> list[Msg]:
        return [{"nope": 1}]

    @app.get("/notlist")
    def notlist() -> list[Msg]:
        return {"message": "a"}

    @app.post("/created")
    async def created() -> Msg:
        return {"message": "c"}, 201

    @app.get("/void")
    def void() -> None:
        return None

    @app.get("/custom")
    def custom() -> Response:
        return JSONResponse({"x": 1}, status_code=202)

    @app.get("/untyped")
    def untyped():
        return {"apa": "saja"}

    @app.get("/plaindict")
    def plaindict() -> dict:
        return {"a": 1}

    @app.get("/err")
    def err() -> Msg:
        raise HTTPError(409, "bentrok")

    @app.get("/items/{item_id:int}")
    def get_item(item_id: int) -> Item:
        return {"name": f"item-{item_id}", "qty": 2}

    return app


def test_dict_is_validated_against_return_type():
    resp = call(make_app(), "GET", "/ok")
    assert resp.status == 200 and resp.json() == {"message": "hi"}


def test_defaults_are_filled_by_validation():
    assert call(make_app(), "GET", "/items/5").json() == {"name": "item-5", "qty": 2}


def test_schema_instance_is_accepted():
    assert call(make_app(), "GET", "/instance").json() == {"message": "x"}


@pytest.mark.parametrize("path", ["/extra", "/none", "/wrong", "/badlist", "/notlist"])
def test_contract_violation_is_500_without_leaking(path):
    resp = call(make_app(), "GET", path, raise_app_exceptions=False)
    assert resp.status == 500
    assert resp.json()["error"] == "internal_error"
    assert "bocor" not in resp.text and "secret" not in resp.text


def test_list_of_schemas():
    assert call(make_app(), "GET", "/list").json() == [{"message": "a"}, {"message": "b"}]


def test_status_tuple_keeps_contract():
    resp = call(make_app(), "GET", "/void")
    assert resp.status == 204
    created = call(make_app(), "POST", "/created", json={})
    assert created.status == 201 and created.json() == {"message": "c"}


def test_custom_response_and_untyped_and_plain_dict_are_not_enforced():
    app = make_app()
    assert call(app, "GET", "/custom").status == 202
    assert call(app, "GET", "/untyped").json() == {"apa": "saja"}
    assert call(app, "GET", "/plaindict").json() == {"a": 1}


def test_http_error_passes_through_typed_route():
    resp = call(make_app(), "GET", "/err")
    assert resp.status == 409 and resp.json()["message"] == "bentrok"


def test_unsupported_return_types_fail_at_definition():
    app = SimPy()
    with pytest.raises(TypeError):

        @app.get("/a")
        def a() -> set:
            return set()

    with pytest.raises(TypeError):

        @app.get("/b")
        def b() -> int | str:
            return 1

    with pytest.raises(TypeError) as exc:

        @app.get("/c")
        def c() -> Msg | None:
            return None

    assert "Optional" in str(exc.value)


def test_routes_info():
    app = SimPy()

    @app.post("/api/items")
    def create(item: Item) -> Item:
        return item

    @app.get("/users/{user_id:int}/files/{rest:path}")
    def files(user_id: int, rest: str) -> list[Msg]:
        return []

    @app.route("/multi", methods=["GET", "POST"])
    def multi():
        return {}

    infos = {(i.name, i.method): i for i in app.routes_info()}
    create_info = infos[("create", "POST")]
    assert create_info.path == "/api/items"
    assert create_info.body is Item and create_info.response is Item
    assert not create_info.multi_method
    files_info = infos[("files", "GET")]
    assert files_info.path_params == (("user_id", "number"), ("rest", "string"))
    assert files_info.body is None
    assert infos[("multi", "GET")].multi_method and infos[("multi", "POST")].multi_method
    assert repr(infos[("multi", "GET")].response) == "UNSET"
