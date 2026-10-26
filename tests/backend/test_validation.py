import pytest

from simpy import Schema, ValidationError, field


class Address(Schema):
    city: str = field(min_length=1)


class User(Schema):
    name: str = field(min_length=1, max_length=10)
    age: int = field(ge=0, le=150)
    nickname: str | None = None
    tags: list[str] = field(default=[], max_length=2)
    address: Address | None = None


def errors_of(exc_info):
    return {(tuple(e["loc"]), e["msg"]) for e in exc_info.value.errors}


def locs_of(exc_info):
    return {tuple(e["loc"]) for e in exc_info.value.errors}


def test_valid_input():
    user = User.validate({"name": "Ani", "age": 20})
    assert user.name == "Ani"
    assert user.age == 20
    assert user.nickname is None
    assert user.tags == []


def test_mutable_default_is_not_shared():
    a = User.validate({"name": "A", "age": 1})
    a.tags.append("x")
    b = User.validate({"name": "B", "age": 2})
    assert b.tags == []


def test_missing_required_fields():
    with pytest.raises(ValidationError) as exc:
        User.validate({})
    assert locs_of(exc) == {("name",), ("age",)}


def test_types_are_strict():
    with pytest.raises(ValidationError) as exc:
        User.validate({"name": 5, "age": "20"})
    assert locs_of(exc) == {("name",), ("age",)}


def test_bool_is_not_int():
    with pytest.raises(ValidationError):
        User.validate({"name": "A", "age": True})


def test_numeric_range():
    for bad in (-1, 151):
        with pytest.raises(ValidationError) as exc:
            User.validate({"name": "A", "age": bad})
        assert locs_of(exc) == {("age",)}
    assert User.validate({"name": "A", "age": 0}).age == 0
    assert User.validate({"name": "A", "age": 150}).age == 150


def test_string_length():
    for bad in ("", "x" * 11):
        with pytest.raises(ValidationError) as exc:
            User.validate({"name": bad, "age": 1})
        assert locs_of(exc) == {("name",)}


def test_default_max_string_length_applies():
    class Plain(Schema):
        text: str

    assert Plain.validate({"text": "x" * 10_000}).text
    with pytest.raises(ValidationError):
        Plain.validate({"text": "x" * 10_001})


def test_pattern_requires_full_match():
    class Code(Schema):
        code: str = field(pattern=r"[A-Z]{3}")

    assert Code.validate({"code": "ABC"}).code == "ABC"
    for bad in ("abc", "ABCD", "xABC"):
        with pytest.raises(ValidationError):
            Code.validate({"code": bad})


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError) as exc:
        User.validate({"name": "A", "age": 1, "is_admin": True})
    assert errors_of(exc) == {(("is_admin",), "field tidak dikenal")}


def test_optional_field():
    assert User.validate({"name": "A", "age": 1, "nickname": None}).nickname is None
    assert User.validate({"name": "A", "age": 1, "nickname": "Ai"}).nickname == "Ai"
    with pytest.raises(ValidationError):
        User.validate({"name": "A", "age": 1, "nickname": 5})


def test_list_limits_and_item_errors():
    with pytest.raises(ValidationError) as exc:
        User.validate({"name": "A", "age": 1, "tags": ["a", "b", "c"]})
    assert locs_of(exc) == {("tags",)}
    with pytest.raises(ValidationError) as exc:
        User.validate({"name": "A", "age": 1, "tags": ["a", 1]})
    assert locs_of(exc) == {("tags", 1)}
    with pytest.raises(ValidationError):
        User.validate({"name": "A", "age": 1, "tags": "abc"})


def test_nested_schema():
    user = User.validate({"name": "A", "age": 1, "address": {"city": "Bandung"}})
    assert user.address.city == "Bandung"
    with pytest.raises(ValidationError) as exc:
        User.validate({"name": "A", "age": 1, "address": {"city": ""}})
    assert locs_of(exc) == {("address", "city")}
    with pytest.raises(ValidationError) as exc:
        User.validate({"name": "A", "age": 1, "address": "Bandung"})
    assert locs_of(exc) == {("address",)}


def test_non_dict_input():
    with pytest.raises(ValidationError) as exc:
        User.validate([])
    assert locs_of(exc) == {()}


def test_float_field():
    class M(Schema):
        x: float

    value = M.validate({"x": 1}).x
    assert value == 1.0 and isinstance(value, float)
    for bad in ("1", True, float("nan"), float("inf"), 10**400):
        with pytest.raises(ValidationError):
            M.validate({"x": bad})


def test_to_dict_and_equality():
    data = {
        "name": "A",
        "age": 1,
        "nickname": None,
        "tags": ["x"],
        "address": {"city": "Bandung"},
    }
    user = User.validate(data)
    assert user.to_dict() == data
    assert User.validate(data) == user


def test_unsupported_types_fail_at_definition():
    with pytest.raises(TypeError):

        class Bad1(Schema):
            x: dict

    with pytest.raises(TypeError):

        class Bad2(Schema):
            x: int | str


def test_field_name_collision_is_rejected():
    with pytest.raises(TypeError):

        class Bad(Schema):
            validate: str


def test_field_rejects_invalid_arguments():
    with pytest.raises(ValueError):
        field(min_length=-1)
    with pytest.raises(ValueError):
        field(min_length=5, max_length=2)
    with pytest.raises(ValueError):
        field(ge=10, le=1)
