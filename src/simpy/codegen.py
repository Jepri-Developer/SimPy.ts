"""Generator klien TypeScript bertipe dari route SimPy (`simpy generate`)."""

from __future__ import annotations

import json
import re
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Union, get_args, get_origin

from simpy.routeinfo import UNSET, RouteInfo
from simpy.validation import MISSING, Schema

_PATH_PARAM = re.compile(r"\{(\w+)(?::(\w+))?\}")
_RESERVED = {
    "body", "break", "case", "catch", "class", "const", "continue", "debugger", "default",
    "delete", "do", "else", "enum", "export", "extends", "false", "finally", "for", "function",
    "if", "import", "in", "instanceof", "new", "null", "return", "super", "switch", "this",
    "throw", "true", "try", "typeof", "var", "void", "while", "with", "yield", "let", "static",
    "await", "async", "interface", "package", "private", "protected", "public", "implements",
}
HEADER = "// Dibuat otomatis oleh `simpy generate`. Jangan diedit."


class CodegenError(Exception):
    """Route tidak bisa dijadikan klien TypeScript. Pesannya aman ditampilkan."""


def to_camel(name: str) -> str:
    parts = [p for p in name.split("_") if p]
    if not parts:
        raise CodegenError(f"Nama '{name}' tidak bisa dijadikan nama fungsi klien.")
    first = parts[0][0].lower() + parts[0][1:]
    return first + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def _ident(name: str) -> str:
    result = to_camel(name)
    return result + "_" if result in _RESERVED else result


def _is_union(origin: Any) -> bool:
    return origin is Union or origin is types.UnionType


def _is_schema(tp: Any) -> bool:
    return get_origin(tp) is None and isinstance(tp, type) and issubclass(tp, Schema)


def _discover(tp: Any, role: str, needed: dict[type, set[str]]) -> None:
    """Kumpulkan Schema (dan perannya: 'input' / 'output') yang dipakai, termasuk yang bersarang."""
    origin, args = get_origin(tp), get_args(tp)
    if _is_union(origin):
        for arg in args:
            if arg is not type(None):
                _discover(arg, role, needed)
    elif origin is list and args:
        _discover(args[0], role, needed)
    elif origin is dict and len(args) == 2:
        _discover(args[1], role, needed)
    elif _is_schema(tp):
        roles = needed.setdefault(tp, set())
        if role in roles:
            return
        roles.add(role)
        for field_type, _info in tp.__fields__.values():
            _discover(field_type, role, needed)


def _assign_names(needed: dict[type, set[str]]) -> dict[tuple[type, str], str]:
    names: dict[tuple[type, str], str] = {}
    for cls, roles in needed.items():
        for role in roles:
            both = len(roles) == 2
            names[(cls, role)] = cls.__name__ + ("Input" if both and role == "input" else "")
    owner: dict[str, type] = {}
    for (cls, _role), name in names.items():
        first = owner.setdefault(name, cls)
        if first is not cls:
            raise CodegenError(
                f"Nama TypeScript '{name}' bentrok antara {first.__module__}.{first.__qualname__} "
                f"dan {cls.__module__}.{cls.__qualname__}. Ubah nama salah satu Schema."
            )
    return names


def _ts(tp: Any, role: str, names: dict[tuple[type, str], str]) -> str:
    if tp is Any:
        return "unknown"
    if tp is str:
        return "string"
    if tp is bool:
        return "boolean"
    if tp in (int, float):
        return "number"
    if tp is dict:
        return "Record<string, unknown>"
    origin, args = get_origin(tp), get_args(tp)
    if _is_union(origin):
        inner = next(a for a in args if a is not type(None))
        return f"{_ts(inner, role, names)} | null"
    if origin is list:
        item = _ts(args[0], role, names)
        return f"({item})[]" if " | " in item else f"{item}[]"
    if origin is dict:
        return f"Record<string, {_ts(args[1], role, names)}>"
    if _is_schema(tp):
        return names[(tp, role)]
    raise CodegenError(f"Tipe {tp!r} tidak bisa dijadikan tipe TypeScript.")


def _interface(cls: type[Schema], role: str, names: dict[tuple[type, str], str]) -> str:
    lines = [f"export interface {names[(cls, role)]} {{"]
    for field_name, (field_type, info) in cls.__fields__.items():
        optional = role == "input" and info.default is not MISSING
        lines.append(f"  {field_name}{'?' if optional else ''}: {_ts(field_type, role, names)};")
    lines.append("}")
    return "\n".join(lines)


def _escape_template(text: str) -> str:
    return text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def _client_name(info: RouteInfo) -> str:
    base = f"{info.name}_{info.method.lower()}" if info.multi_method else info.name
    return to_camel(base)


def _path_expression(info: RouteInfo, idents: dict[str, str]) -> str:
    if not info.path_params:
        return json.dumps(info.path)
    out, last = [], 0
    for match in _PATH_PARAM.finditer(info.path):
        out.append(_escape_template(info.path[last : match.start()]))
        ident = idents[match.group(1)]
        if match.group(2) == "path":
            out.append(f'${{String({ident}).split("/").map(encodeURIComponent).join("/")}}')
        else:
            out.append(f"${{encodeURIComponent(String({ident}))}}")
        last = match.end()
    out.append(_escape_template(info.path[last:]))
    return "`" + "".join(out) + "`"


def _client_entry(info: RouteInfo, names: dict[tuple[type, str], str]) -> str:
    if info.body is not None and info.method == "GET":
        raise CodegenError(
            f"GET {info.path} ({info.name}): GET tidak boleh punya body JSON. "
            "Pakai POST, atau hapus parameter Schema."
        )
    idents: dict[str, str] = {}
    args: list[str] = []
    for param_name, kind in info.path_params:
        ident = _ident(param_name)
        if ident in idents.values():
            raise CodegenError(f"{info.name}: parameter path '{param_name}' bentrok setelah camelCase.")
        idents[param_name] = ident
        args.append(f"{ident}: {'number' if kind == 'number' else 'string'}")
    if info.body is not None:
        args.append(f"body: {names[(info.body, 'input')]}")

    if info.response is UNSET:
        returns = "unknown"
    elif info.response is None:
        returns = "void"
    else:
        returns = _ts(info.response, "output", names)

    options = ", { body }" if info.body is not None else ""
    return (
        f"  {_client_name(info)}: ({', '.join(args)}) => "
        f"request<{returns}>({json.dumps(info.method)}, {_path_expression(info, idents)}{options}),"
    )


def generate_typescript(routes: Sequence[RouteInfo]) -> str:
    """Hasilkan isi `.simpy/api.ts`. Deterministik: input sama menghasilkan teks sama."""
    seen: dict[str, RouteInfo] = {}
    for info in routes:
        name = _client_name(info)
        if name in seen:
            other = seen[name]
            raise CodegenError(
                f"Nama klien '{name}' dipakai dua kali ({other.method} {other.path} dan "
                f"{info.method} {info.path}). Ganti nama fungsi handler salah satunya."
            )
        seen[name] = info

    needed: dict[type, set[str]] = {}
    for info in routes:
        if info.body is not None:
            _discover(info.body, "input", needed)
        if info.response is not UNSET and info.response is not None:
            _discover(info.response, "output", needed)
    names = _assign_names(needed)

    interfaces = [
        (name, _interface(cls, role, names)) for (cls, role), name in names.items()
    ]
    interfaces.sort(key=lambda pair: pair[0])

    parts = [HEADER, 'import { request } from "./frontend/api.ts";', ""]
    for _name, text in interfaces:
        parts += [text, ""]
    if routes:
        parts.append("export const api = {")
        parts += [_client_entry(info, names) for info in routes]
        parts.append("} as const;")
    else:
        parts.append("export const api = {} as const;")
    return "\n".join(parts) + "\n"


def write_if_changed(path: Path, text: str) -> bool:
    """Tulis file hanya bila isinya berbeda (menjaga watcher tidak rebuild sia-sia)."""
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True
