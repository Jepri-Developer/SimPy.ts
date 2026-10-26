"""Metadata route: dipakai generator klien TypeScript dan pemeriksaan tipe return."""

from __future__ import annotations

import types
from dataclasses import dataclass
from typing import Any, Union, get_args, get_origin

from simpy.validation import Schema


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()  # handler tanpa anotasi return


@dataclass(frozen=True)
class RouteInfo:
    name: str  # nama fungsi handler
    method: str
    path: str
    path_params: tuple[tuple[str, str], ...]  # (nama, "number" | "string")
    body: type[Schema] | None
    response: Any  # UNSET, None (void), atau tipe return
    multi_method: bool = False


def _is_union(origin: Any) -> bool:
    return origin is Union or origin is types.UnionType


def assert_response_type(tp: Any, where: str, *, top: bool = False) -> None:
    """Pastikan tipe return didukung. `top`: tipe return utama (tidak boleh Optional)."""
    if tp is Any or tp in (str, int, float, bool, dict):
        return
    origin = get_origin(tp)
    args = get_args(tp)
    if _is_union(origin):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and len(args) == 2:
            if top:
                raise TypeError(
                    f"{where}: tipe return tidak boleh Optional. "
                    "Pakai '-> None' (204) atau tipe non-Optional."
                )
            return assert_response_type(non_none[0], where)
    elif origin is list and len(args) == 1:
        return assert_response_type(args[0], where)
    elif origin is dict and len(args) == 2 and args[0] is str:
        return assert_response_type(args[1], where)
    elif origin is None and isinstance(tp, type) and issubclass(tp, Schema):
        return
    raise TypeError(
        f"{where}: tipe return {tp!r} tidak didukung. Didukung: Schema, list[T], "
        "dict[str, T], str, int, float, bool, T | None (di dalam), atau None."
    )
