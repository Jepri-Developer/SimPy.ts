import pytest

from simpy import Schema, SimPy, field
from simpy.codegen import CodegenError, generate_typescript, to_camel, write_if_changed


class GreetInput(Schema):
    name: str = field(min_length=1)


class Address(Schema):
    city: str
    zip: str | None = None


class UserOut(Schema):
    id: int
    name: str
    tags: list[str]
    notes: list[str | None]
    address: Address | None


class UserIn(Schema):
    name: str
    tags: list[str] = field(default=[])
    address: Address | None = None


def sample_app():
    app = SimPy()

    @app.get("/api/users/{user_id:int}")
    def get_user(user_id: int) -> UserOut:
        return {}

    @app.post("/api/users")
    def create_user(data: UserIn) -> UserOut:
        return {}

    @app.get("/api/users")
    def list_users() -> list[UserOut]:
        return []

    @app.delete("/api/ping")
    def ping() -> None:
        return None

    @app.get("/api/untyped")
    def untyped():
        return {}

    @app.get("/api/meta")
    def meta() -> dict:
        return {}

    @app.get("/api/files/{rest:path}")
    def read_file(rest: str):
        return {}

    @app.post("/api/greet")
    def greet(data: GreetInput) -> GreetInput:
        return data

    return app


def source():
    return generate_typescript(sample_app().routes_info())


def test_header_and_import():
    text = source()
    assert text.startswith("// Dibuat otomatis oleh `simpy generate`")
    assert 'import { request } from "./frontend/api.ts";' in text
    assert text.endswith("} as const;\n")


def test_output_interface_has_all_fields_required():
    assert (
        "export interface UserOut {\n"
        "  id: number;\n"
        "  name: string;\n"
        "  tags: string[];\n"
        "  notes: (string | null)[];\n"
        "  address: Address | null;\n"
        "}"
    ) in source()


def test_input_interface_makes_defaults_optional():
    assert (
        "export interface UserIn {\n"
        "  name: string;\n"
        "  tags?: string[];\n"
        "  address?: AddressInput | null;\n"
        "}"
    ) in source()


def test_schema_used_in_both_roles_gets_two_interfaces():
    text = source()
    assert "export interface Address {\n  city: string;\n  zip: string | null;\n}" in text
    assert "export interface AddressInput {\n  city: string;\n  zip?: string | null;\n}" in text


def test_schema_used_as_both_body_and_response_is_split():
    text = source()
    assert "export interface GreetInput {\n  name: string;\n}" in text
    assert "export interface GreetInputInput {\n  name: string;\n}" in text
    assert (
        'greet: (body: GreetInputInput) => request<GreetInput>("POST", "/api/greet", { body }),'
    ) in text


def test_client_functions():
    text = source()
    assert (
        "getUser: (userId: number) => request<UserOut>(\"GET\", "
        "`/api/users/${encodeURIComponent(String(userId))}`),"
    ) in text
    assert 'createUser: (body: UserIn) => request<UserOut>("POST", "/api/users", { body }),' in text
    assert 'listUsers: () => request<UserOut[]>("GET", "/api/users"),' in text
    assert 'ping: () => request<void>("DELETE", "/api/ping"),' in text
    assert 'untyped: () => request<unknown>("GET", "/api/untyped"),' in text
    assert 'meta: () => request<Record<string, unknown>>("GET", "/api/meta"),' in text
    assert (
        'readFile: (rest: string) => request<unknown>("GET", '
        '`/api/files/${String(rest).split("/").map(encodeURIComponent).join("/")}`),'
    ) in text


def test_generation_is_deterministic():
    assert source() == source()


def test_empty_app():
    text = generate_typescript([])
    assert "export const api = {} as const;" in text


def test_multi_method_routes_get_method_suffix():
    app = SimPy()

    @app.route("/m", methods=["GET", "POST"])
    def thing():
        return {}

    text = generate_typescript(app.routes_info())
    assert "thingGet:" in text and "thingPost:" in text


def test_get_with_body_is_rejected():
    app = SimPy()

    @app.get("/x")
    def x(data: GreetInput):
        return {}

    with pytest.raises(CodegenError) as exc:
        generate_typescript(app.routes_info())
    assert "GET" in str(exc.value)


def test_duplicate_client_names_are_rejected():
    app = SimPy()

    @app.get("/a")
    def get_thing():
        return {}

    @app.get("/b")
    def getThing():  # noqa: N802 - sengaja: bentrok setelah camelCase
        return {}

    with pytest.raises(CodegenError):
        generate_typescript(app.routes_info())


def make_same_named(field_name):
    return type("Same", (Schema,), {"__annotations__": {field_name: int}})


def test_same_class_name_in_different_modules_is_rejected():
    first, second = make_same_named("a"), make_same_named("b")
    app = SimPy()

    @app.get("/one")
    def one() -> first:  # type: ignore[valid-type]
        return {}

    @app.get("/two")
    def two() -> second:  # type: ignore[valid-type]
        return {}

    with pytest.raises(CodegenError) as exc:
        generate_typescript(app.routes_info())
    assert "Same" in str(exc.value)


def test_reserved_word_parameter_names_are_made_safe():
    app = SimPy()

    @app.get("/things/{class_}/{body}")
    def thing(class_: str, body: str):
        return {}

    text = generate_typescript(app.routes_info())
    assert "thing: (class: string, body_: string)" not in text  # 'class' juga dilindungi
    assert "(class_: string, body_: string)" in text


def test_to_camel():
    assert to_camel("get_user") == "getUser"
    assert to_camel("_private_name") == "privateName"
    assert to_camel("Already") == "already"
    with pytest.raises(CodegenError):
        to_camel("___")


def test_write_if_changed(tmp_path):
    target = tmp_path / "sub" / "api.ts"
    assert write_if_changed(target, "a") is True
    assert write_if_changed(target, "a") is False
    assert write_if_changed(target, "b") is True
    assert target.read_text() == "b"
