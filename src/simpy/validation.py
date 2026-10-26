"""Validasi input bawaan SimPy.ts.

Pengganti Pydantic yang ringan: Python murni, tanpa dependensi, dan aman by default
(tipe ketat tanpa konversi diam-diam, field asing ditolak, ada batas panjang bawaan).

Contoh::

    class UserInput(Schema):
        name: str = field(min_length=1, max_length=50)
        age: int = field(ge=0, le=150)
        nickname: str | None = None

    user = UserInput.validate({"name": "Ani", "age": 20})
"""

from __future__ import annotations

import copy
import math
import re
import types
from dataclasses import dataclass
from typing import Any, ClassVar, Union, get_args, get_origin, get_type_hints

DEFAULT_MAX_STR = 10_000
DEFAULT_MAX_LIST = 1_000


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()
_FAIL = object()


class ValidationError(Exception):
    """Dilempar saat input tidak lolos validasi. `errors` berisi daftar {loc, msg}."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} kesalahan validasi")


@dataclass(frozen=True)
class FieldInfo:
    default: Any = MISSING
    min_length: int | None = None
    max_length: int | None = None
    ge: float | None = None
    le: float | None = None
    pattern: re.Pattern[str] | None = None


def field(
    *,
    default: Any = MISSING,
    min_length: int | None = None,
    max_length: int | None = None,
    ge: float | None = None,
    le: float | None = None,
    pattern: str | None = None,
) -> Any:
    """Deklarasikan batasan sebuah field. Tanpa `default`, field wajib diisi."""
    for label, value in (("min_length", min_length), ("max_length", max_length)):
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise ValueError(f"{label} harus bilangan bulat >= 0")
    if min_length is not None and max_length is not None and min_length > max_length:
        raise ValueError("min_length tidak boleh lebih besar dari max_length")
    if ge is not None and le is not None and ge > le:
        raise ValueError("ge tidak boleh lebih besar dari le")
    compiled = re.compile(pattern) if pattern is not None else None
    return FieldInfo(default, min_length, max_length, ge, le, compiled)


def _err(errors: list[dict[str, Any]], loc: tuple[Any, ...], msg: str) -> None:
    errors.append({"loc": list(loc), "msg": msg})


def _is_union(origin: Any) -> bool:
    return origin is Union or origin is types.UnionType


def _assert_supported(tp: Any, where: str) -> None:
    if tp is Any or tp in (str, int, float, bool):
        return
    origin = get_origin(tp)
    args = get_args(tp)
    if _is_union(origin):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and len(args) == 2:
            return _assert_supported(non_none[0], where)
    elif origin is list:
        if len(args) == 1:
            return _assert_supported(args[0], where)
    elif origin is None and isinstance(tp, type) and issubclass(tp, Schema):
        return
    raise TypeError(
        f"Tipe {tp!r} pada '{where}' tidak didukung. "
        "Didukung: str, int, float, bool, list[T], T | None, dan Schema bersarang."
    )


def _check_range(value: Any, loc: tuple[Any, ...], info: FieldInfo | None, errors: list) -> Any:
    if info is not None:
        if info.ge is not None and value < info.ge:
            _err(errors, loc, f"harus >= {info.ge}")
            return _FAIL
        if info.le is not None and value > info.le:
            _err(errors, loc, f"harus <= {info.le}")
            return _FAIL
    return value


def _check(tp: Any, value: Any, loc: tuple[Any, ...], info: FieldInfo | None, errors: list) -> Any:
    """Validasi satu nilai. Mengembalikan nilai bersih, atau _FAIL (error sudah dicatat)."""
    if tp is Any:
        return value

    origin = get_origin(tp)
    args = get_args(tp)

    if _is_union(origin):  # hanya Optional[T] yang didukung
        if value is None:
            return None
        inner = next(a for a in args if a is not type(None))
        return _check(inner, value, loc, info, errors)

    if origin is list:
        if not isinstance(value, list):
            _err(errors, loc, "harus berupa list")
            return _FAIL
        max_len = info.max_length if info and info.max_length is not None else DEFAULT_MAX_LIST
        min_len = info.min_length if info and info.min_length is not None else 0
        if len(value) > max_len:
            _err(errors, loc, f"maksimal {max_len} item")
            return _FAIL
        if len(value) < min_len:
            _err(errors, loc, f"minimal {min_len} item")
            return _FAIL
        out: list[Any] = []
        failed = False
        for i, item in enumerate(value):
            result = _check(args[0], item, (*loc, i), None, errors)
            if result is _FAIL:
                failed = True
            else:
                out.append(result)
        return _FAIL if failed else out

    if origin is None and isinstance(tp, type) and issubclass(tp, Schema):
        if not isinstance(value, dict):
            _err(errors, loc, "harus berupa objek")
            return _FAIL
        return tp._build(value, loc, errors)

    if tp is bool:
        if isinstance(value, bool):
            return value
        _err(errors, loc, "harus berupa boolean")
        return _FAIL

    if tp is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return _check_range(value, loc, info, errors)
        _err(errors, loc, "harus berupa bilangan bulat")
        return _FAIL

    if tp is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                number = float(value)
            except OverflowError:
                number = math.inf
            if not math.isfinite(number):
                _err(errors, loc, "harus berupa bilangan hingga")
                return _FAIL
            return _check_range(number, loc, info, errors)
        _err(errors, loc, "harus berupa angka")
        return _FAIL

    if tp is str:
        if not isinstance(value, str):
            _err(errors, loc, "harus berupa teks")
            return _FAIL
        max_len = info.max_length if info and info.max_length is not None else DEFAULT_MAX_STR
        min_len = info.min_length if info and info.min_length is not None else 0
        if len(value) > max_len:
            _err(errors, loc, f"maksimal {max_len} karakter")
            return _FAIL
        if len(value) < min_len:
            _err(errors, loc, f"minimal {min_len} karakter")
            return _FAIL
        if info and info.pattern is not None and not info.pattern.fullmatch(value):
            _err(errors, loc, "format tidak sesuai")
            return _FAIL
        return value

    raise TypeError(f"Tipe {tp!r} tidak didukung")  # seharusnya sudah ditolak saat definisi


class Schema:
    """Kelas dasar skema input. Turunkan, beri anotasi tipe, lalu panggil `validate`."""

    __fields__: ClassVar[dict] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        try:
            hints = get_type_hints(cls)
        except NameError as exc:
            raise TypeError(
                f"Tipe pada {cls.__name__} tidak bisa di-resolve ({exc}). "
                "Definisikan Schema bersarang sebelum dipakai."
            ) from exc
        fields: dict[str, tuple[Any, FieldInfo]] = {}
        for name, tp in hints.items():
            if name.startswith("_") or get_origin(tp) is ClassVar:
                continue
            if hasattr(Schema, name):
                raise TypeError(f"Nama field '{name}' pada {cls.__name__} bentrok dengan Schema")
            _assert_supported(tp, f"{cls.__name__}.{name}")
            default = getattr(cls, name, MISSING)
            info = default if isinstance(default, FieldInfo) else FieldInfo(default=default)
            fields[name] = (tp, info)
        cls.__fields__ = fields

    @classmethod
    def _build(cls, data: dict, loc: tuple[Any, ...], errors: list) -> Any:
        before = len(errors)
        for key in sorted(str(k) for k in data if k not in cls.__fields__):
            _err(errors, (*loc, key), "field tidak dikenal")
        values: dict[str, Any] = {}
        for name, (tp, info) in cls.__fields__.items():
            if name in data:
                result = _check(tp, data[name], (*loc, name), info, errors)
                if result is not _FAIL:
                    values[name] = result
            elif info.default is not MISSING:
                values[name] = copy.deepcopy(info.default)
            else:
                _err(errors, (*loc, name), "field wajib diisi")
        if len(errors) > before:
            return _FAIL
        obj = cls.__new__(cls)
        obj.__dict__.update(values)
        return obj

    @classmethod
    def validate(cls, data: Any) -> Any:
        """Validasi `data` (dict). Mengembalikan instance, atau melempar ValidationError."""
        errors: list[dict[str, Any]] = []
        if not isinstance(data, dict):
            _err(errors, (), "input harus berupa objek JSON")
            raise ValidationError(errors)
        result = cls._build(data, (), errors)
        if errors:
            raise ValidationError(errors)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {name: _plain(getattr(self, name)) for name in self.__fields__}

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self.to_dict() == other.to_dict()  # type: ignore[attr-defined]

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        pairs = ", ".join(f"{k}={getattr(self, k)!r}" for k in self.__fields__)
        return f"{type(self).__name__}({pairs})"


def _plain(value: Any) -> Any:
    if isinstance(value, Schema):
        return value.to_dict()
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value
