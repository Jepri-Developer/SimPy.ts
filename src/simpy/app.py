"""Aplikasi ASGI SimPy.ts: routing, body JSON aman, kontrak respons, dan penanganan error."""

from __future__ import annotations

import inspect
import json
import mimetypes
import os
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

import types as _types

import anyio.to_thread
from starlette.applications import Starlette
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from simpy.auth import Database, Session, SessionStore, UserStore
from simpy.config import Settings
from simpy.routeinfo import UNSET, RouteInfo, assert_response_type
from simpy.security import (
    CSRF_COOKIE,
    CSRF_MAX_AGE,
    DEFAULT_CSP,
    SAFE_METHODS,
    SESSION_COOKIE,
    CsrfService,
    RateLimiter,
    SecurityMiddleware,
    build_cookie,
    client_ip,
    cookie_name,
    csrf_problem,
    parse_cookies,
    queue_cookie,
    retry_after_seconds,
)
from simpy.validation import Schema, ValidationError

DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 MiB
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_PATH_PARAM_PATTERN = re.compile(r"\{(\w+)(?::(\w+))?\}")
_ERROR_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
    401: "unauthorized",
    403: "forbidden",
    422: "validation_error",
    429: "rate_limited",
}


class HTTPError(Exception):
    """Lempar dari handler untuk membalas error JSON dengan status tertentu."""

    def __init__(
        self,
        status: int,
        message: str = "",
        *,
        code: str | None = None,
        details: list[Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        if not 400 <= status <= 599:
            raise ValueError("status HTTPError harus 400-599")
        self.status = status
        self.message = message or HTTPStatus(status).phrase
        self.code = code or _ERROR_CODES.get(status, "error")
        self.details = details
        self.headers = headers
        super().__init__(self.message)


class ContractError(Exception):
    """Handler mengembalikan data yang tidak sesuai tipe return (bug server, jadi 500)."""


def _error_response(
    status: int,
    code: str,
    message: str,
    details: list[Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    body: dict[str, Any] = {"error": code, "message": message}
    if details:
        body["details"] = details
    return JSONResponse(body, status_code=status, headers=headers)


def _reject_constant(name: str) -> Any:
    raise ValueError(f"konstanta JSON tidak diizinkan: {name}")


async def _parse_body(request: Request, schema: type[Schema], limit: int) -> Any:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        raise HTTPError(415, "Content-Type harus application/json")

    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_size = int(declared)
        except ValueError:
            raise HTTPError(400, "Content-Length tidak valid") from None
        if declared_size < 0:
            raise HTTPError(400, "Content-Length tidak valid")
        if declared_size > limit:
            raise HTTPError(413, f"Body melebihi batas {limit} byte")

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPError(413, f"Body melebihi batas {limit} byte")
        chunks.append(chunk)

    try:
        data = json.loads(b"".join(chunks), parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise HTTPError(400, "Body bukan JSON yang valid") from None

    try:
        return schema.validate(data)
    except ValidationError as exc:
        raise HTTPError(422, "Input tidak valid", details=exc.errors) from None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Schema):
        return value.to_dict()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _split_status(result: Any) -> tuple[Any, int | None]:
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[1], int)
        and not isinstance(result[1], bool)
    ):
        return result[0], result[1]
    return result, None


def _to_response(result: Any) -> Response:
    result, explicit = _split_status(result)
    status = 200 if explicit is None else explicit
    if isinstance(result, Response):
        return result
    if result is None:
        return Response(status_code=204 if status == 200 else status)
    return JSONResponse(_jsonable(result), status_code=status)


# --- kontrak respons: Schema / list[Schema] dipaksakan saat runtime ---------------------


def _contract_target(response: Any) -> Any:
    if isinstance(response, type) and issubclass(response, Schema):
        return response
    if get_origin(response) is list:
        inner = get_args(response)[0]
        if get_origin(inner) is None and isinstance(inner, type) and issubclass(inner, Schema):
            return response
    return None


def _conform(data: Any, target: Any, where: str) -> Any:
    if get_origin(target) is list:
        if not isinstance(data, list):
            raise ContractError(f"{where}: harus mengembalikan list")
        return [_conform(item, get_args(target)[0], where) for item in data]
    if isinstance(data, target):
        return data
    if isinstance(data, dict):
        try:
            return target.validate(data)
        except ValidationError as exc:
            raise ContractError(
                f"{where}: respons tidak sesuai {target.__name__}: {exc.errors}"
            ) from None
    raise ContractError(f"{where}: harus mengembalikan {target.__name__}")


def _enforce(result: Any, target: Any, where: str) -> Any:
    data, status = _split_status(result)
    if isinstance(data, Response):
        return result
    data = _conform(data, target, where)
    return data if status is None else (data, status)


# --- analisis signature handler ----------------------------------------------------------


@dataclass(frozen=True)
class _Param:
    name: str
    kind: str  # "request" | "path" | "body" | "session"
    schema: type[Schema] | None = None


@dataclass(frozen=True)
class _Analysis:
    plan: list[_Param]
    body: type[Schema] | None
    response: Any  # UNSET, None, atau tipe return
    wants_session: bool = False


def _is_session_annotation(annotation: Any) -> bool:
    if annotation is Session:
        return True
    origin = get_origin(annotation)
    return (origin is Union or origin is _types.UnionType) and Session in get_args(annotation)


def _analyze(fn: Callable[..., Any], path: str) -> _Analysis:
    """Tentukan dari mana tiap parameter diisi dan apa tipe return. Salah konfigurasi gagal
    saat definisi, bukan saat request."""
    path_names = {name for name, _ in _PATH_PARAM_PATTERN.findall(path)}
    try:
        hints = get_type_hints(fn)
    except Exception as exc:
        raise TypeError(f"Anotasi tipe pada {fn.__name__} tidak bisa di-resolve: {exc}") from exc

    plan: list[_Param] = []
    body: type[Schema] | None = None
    wants_session = False
    for name, param in inspect.signature(fn).parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            raise TypeError(f"{fn.__name__}: *args/**kwargs tidak didukung")
        annotation = hints.get(name)
        if name == "session" or _is_session_annotation(annotation):
            wants_session = True
            plan.append(_Param(name, "session"))
        elif isinstance(annotation, type) and issubclass(annotation, Schema):
            if body is not None:
                raise TypeError(f"{fn.__name__}: hanya boleh ada satu parameter body (Schema)")
            body = annotation
            plan.append(_Param(name, "body", annotation))
        elif name == "request":
            plan.append(_Param(name, "request"))
        elif name in path_names:
            plan.append(_Param(name, "path"))
        elif param.default is not inspect.Parameter.empty:
            continue
        else:
            raise TypeError(
                f"{fn.__name__}: parameter '{name}' tidak bisa diisi. Gunakan 'request', "
                "parameter path ({nama}), atau anotasi Schema untuk body JSON."
            )

    response: Any = UNSET
    if "return" in hints:
        annotation = hints["return"]
        if annotation is type(None):
            response = None
        elif isinstance(annotation, type) and issubclass(annotation, Response):
            response = UNSET  # respons kustom: tipe klien tidak diketahui
        else:
            assert_response_type(annotation, f"{fn.__name__} (return)", top=True)
            response = annotation
    return _Analysis(plan, body, response, wants_session)


# --- penyajian frontend --------------------------------------------------------------------

_CONTENT_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".txt": "text/plain",
}


def _content_type(path: Path) -> str:
    return (
        _CONTENT_TYPES.get(path.suffix.lower())
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )


def _safe_file(root: Path, relative: str) -> Path | None:
    """File di dalam `root` (sudah resolve) atau None. Menolak traversal dan symlink keluar."""
    if not relative or "\x00" in relative:
        return None
    try:
        candidate = (root / relative).resolve()
    except (OSError, ValueError):
        return None
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


async def _file_response(file: Path) -> Response:
    data = await anyio.to_thread.run_sync(file.read_bytes)
    return Response(
        content=data,
        media_type=_content_type(file),
        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
    )


def _frontend_routes(root: Path) -> list[Route]:
    async def static_files(request: Request) -> Response:
        file = _safe_file(root, request.path_params["path"])
        if file is None:
            return _error_response(404, "not_found", "Not Found")
        return await _file_response(file)

    async def page(request: Request) -> Response:
        path: str = request.path_params["path"]
        if path == "api" or path.startswith("api/") or "." in path.rsplit("/", 1)[-1]:
            return _error_response(404, "not_found", "Not Found")
        index = _safe_file(root, "index.html")
        if index is None:
            return _error_response(
                404, "frontend_not_built", "Frontend belum di-build. Jalankan: simpy build"
            )
        return await _file_response(index)

    return [
        Route("/static/{path:path}", static_files, methods=["GET"]),
        Route("/{path:path}", page, methods=["GET"]),
    ]


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    code = _ERROR_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return _error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))


async def _unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    # Detail error sengaja tidak dikirim ke klien (hindari kebocoran informasi).
    return _error_response(500, "internal_error", "Terjadi kesalahan pada server.")


class SimPy:
    """Aplikasi SimPy.ts. Instance ini adalah aplikasi ASGI: `uvicorn app.routes:app`."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        rate_limit: str | None = "300/minute",
        csp: str = DEFAULT_CSP,
        allowed_origins: tuple[str, ...] | list[str] = (),
        trusted_proxy_hops: int = 0,
        secure_cookies: bool | None = None,
        session_lifetime: float = 7 * 86400,
        session_idle_timeout: float = 86400,
    ) -> None:
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes harus > 0")
        if trusted_proxy_hops < 0:
            raise ValueError("trusted_proxy_hops tidak boleh negatif")
        self.settings = settings
        self._max_body_bytes = max_body_bytes
        self._csp = csp
        self._global_limit = rate_limit
        self._allowed_origins = frozenset(allowed_origins)
        self._hops = trusted_proxy_hops
        production = bool(settings and settings.is_production)
        self._production = production
        self._secure = production if secure_cookies is None else secure_cookies
        self._session_cookie = cookie_name(SESSION_COOKIE, self._secure)
        self._csrf_cookie = cookie_name(CSRF_COOKIE, self._secure)
        secret = settings.secret_key.encode() if settings else secrets.token_bytes(32)
        self._csrf = CsrfService(secret)
        self._session_lifetime = session_lifetime
        self._session_idle = session_idle_timeout
        self._database: Database | None = None
        self._sessions: SessionStore | None = None
        self._users: UserStore | None = None
        self._routes: list[Route] = []
        self._infos: list[RouteInfo] = []
        self._seen: set[tuple[str, str]] = set()
        self._asgi: Any = None
        self._frontend_root: Path | None = None

    def route(
        self,
        path: str,
        *,
        methods: list[str],
        rate_limit: str | None = None,
        auth: bool = False,
        csrf: bool = True,
    ) -> Callable[[Callable], Callable]:
        if self._asgi is not None:
            raise RuntimeError("Route tidak bisa ditambah setelah aplikasi mulai melayani request.")
        if not path.startswith("/"):
            raise ValueError("path harus diawali '/'")
        verbs = [m.upper() for m in methods]
        if not verbs or not set(verbs) <= ALLOWED_METHODS:
            raise ValueError(f"methods harus bagian dari {sorted(ALLOWED_METHODS)}")

        if rate_limit is not None:
            RateLimiter.from_spec(rate_limit)  # validasi lebih awal

        def decorator(fn: Callable) -> Callable:
            analysis = _analyze(fn, path)
            if (auth or analysis.wants_session) and self.settings is None:
                raise ValueError(
                    f"{fn.__name__}: auth/sesi butuh SimPy(settings=load_settings())."
                )
            for verb in verbs:
                if (path, verb) in self._seen:
                    raise ValueError(f"Route {verb} {path} sudah terdaftar")
            self._seen.update((path, verb) for verb in verbs)
            self._routes.append(
                Route(
                    path,
                    self._make_endpoint(fn, analysis, verbs, rate_limit, auth, csrf),
                    methods=verbs,
                    name=fn.__name__,
                )
            )
            params = tuple(
                (name, "number" if conv in ("int", "float") else "string")
                for name, conv in _PATH_PARAM_PATTERN.findall(path)
            )
            self._infos.extend(
                RouteInfo(
                    name=fn.__name__,
                    method=verb,
                    path=path,
                    path_params=params,
                    body=analysis.body,
                    response=analysis.response,
                    multi_method=len(verbs) > 1,
                )
                for verb in verbs
            )
            return fn

        return decorator

    def get(
        self, path: str, *, rate_limit: str | None = None, auth: bool = False, csrf: bool = True
    ) -> Callable[[Callable], Callable]:
        return self.route(path, methods=["GET"], rate_limit=rate_limit, auth=auth, csrf=csrf)

    def post(
        self, path: str, *, rate_limit: str | None = None, auth: bool = False, csrf: bool = True
    ) -> Callable[[Callable], Callable]:
        return self.route(path, methods=["POST"], rate_limit=rate_limit, auth=auth, csrf=csrf)

    def put(
        self, path: str, *, rate_limit: str | None = None, auth: bool = False, csrf: bool = True
    ) -> Callable[[Callable], Callable]:
        return self.route(path, methods=["PUT"], rate_limit=rate_limit, auth=auth, csrf=csrf)

    def patch(
        self, path: str, *, rate_limit: str | None = None, auth: bool = False, csrf: bool = True
    ) -> Callable[[Callable], Callable]:
        return self.route(path, methods=["PATCH"], rate_limit=rate_limit, auth=auth, csrf=csrf)

    def delete(
        self, path: str, *, rate_limit: str | None = None, auth: bool = False, csrf: bool = True
    ) -> Callable[[Callable], Callable]:
        return self.route(path, methods=["DELETE"], rate_limit=rate_limit, auth=auth, csrf=csrf)

    def routes_info(self) -> list[RouteInfo]:
        """Metadata semua route (urutan pendaftaran); dasar generator klien TypeScript."""
        return list(self._infos)

    def serve_frontend(self, directory: str | os.PathLike[str] = "dist") -> None:
        """Sajikan hasil `simpy build`: /static/* dan halaman (index.html) untuk path lain.

        Route API milik aplikasi selalu didahulukan; path /api/* yang tidak dikenal tetap
        membalas JSON 404.
        """
        if self._asgi is not None:
            raise RuntimeError("serve_frontend harus dipanggil sebelum aplikasi melayani request.")
        if self._frontend_root is not None:
            raise RuntimeError("serve_frontend sudah dipanggil.")
        self._frontend_root = Path(directory).resolve()

    # --- auth & sesi (dibuat lazy: aplikasi tanpa auth tidak membuat file database) ---

    @property
    def database(self) -> Database:
        if self._database is None:
            if self.settings is None:
                raise RuntimeError("Auth/sesi butuh SimPy(settings=load_settings()).")
            self._database = Database(self.settings.session_db)
        return self._database

    @property
    def sessions(self) -> SessionStore:
        if self._sessions is None:
            self._sessions = SessionStore(
                self.database, lifetime=self._session_lifetime, idle_timeout=self._session_idle
            )
        return self._sessions

    @property
    def users(self) -> UserStore:
        if self._users is None:
            self._users = UserStore(self.database)
        return self._users

    def _login(self, scope: dict[str, Any], cookie_header: str, user_id: str) -> Session:
        old = parse_cookies(cookie_header).get(self._session_cookie)
        if old:
            self.sessions.delete(old)  # cegah session fixation
        raw_id, session = self.sessions.create(user_id)
        queue_cookie(
            scope,
            self._session_cookie,
            build_cookie(
                self._session_cookie,
                raw_id,
                max_age=int(self._session_lifetime),
                http_only=True,
                secure=self._secure,
            ),
        )
        self._queue_csrf(scope, raw_id)
        scope["simpy.session"] = session
        return session

    def _logout(self, scope: dict[str, Any], cookie_header: str) -> None:
        old = parse_cookies(cookie_header).get(self._session_cookie)
        if old:
            self.sessions.delete(old)
        queue_cookie(
            scope,
            self._session_cookie,
            build_cookie(
                self._session_cookie, "", max_age=0, http_only=True, secure=self._secure
            ),
        )
        self._queue_csrf(scope, "")
        scope["simpy.session"] = None

    def _queue_csrf(self, scope: dict[str, Any], binding: str) -> None:
        queue_cookie(
            scope,
            self._csrf_cookie,
            build_cookie(
                self._csrf_cookie,
                self._csrf.issue(binding),
                max_age=CSRF_MAX_AGE,
                http_only=False,
                secure=self._secure,
            ),
        )

    async def _current_session(self, request: Request) -> Session | None:
        scope = request.scope
        if "simpy.session" in scope:
            return scope["simpy.session"]
        raw = parse_cookies(request.headers.get("cookie", "")).get(self._session_cookie)
        session = await anyio.to_thread.run_sync(self.sessions.get, raw) if raw else None
        scope["simpy.session"] = session
        return session

    # --- endpoint ---

    def _make_endpoint(
        self,
        fn: Callable,
        analysis: _Analysis,
        verbs: list[str],
        rate_limit: str | None,
        auth: bool,
        csrf: bool,
    ) -> Callable:
        is_async = inspect.iscoroutinefunction(fn)
        limit = self._max_body_bytes
        plan = analysis.plan
        contract = _contract_target(analysis.response)
        needs_session = auth or analysis.wants_session
        limiter = RateLimiter.from_spec(rate_limit) if rate_limit else None

        async def endpoint(request: Request) -> Response:
            kwargs: dict[str, Any] = {}
            try:
                if limiter is not None:
                    wait = limiter.hit((request.method, client_ip(request.scope, self._hops)))
                    if wait is not None:
                        raise HTTPError(
                            429,
                            "Terlalu banyak permintaan. Coba lagi nanti.",
                            headers={"Retry-After": str(retry_after_seconds(wait))},
                        )
                if csrf and request.method not in SAFE_METHODS:
                    problem = csrf_problem(
                        request.headers,
                        self._csrf,
                        csrf_cookie=self._csrf_cookie,
                        session_cookie=self._session_cookie,
                        allowed_origins=self._allowed_origins,
                    )
                    if problem:
                        raise HTTPError(403, problem, code="csrf_failed")
                session = None
                if needs_session:
                    session = await self._current_session(request)
                    if auth and session is None:
                        raise HTTPError(401, "Perlu login.")
                for param in plan:
                    if param.kind == "request":
                        kwargs[param.name] = request
                    elif param.kind == "session":
                        kwargs[param.name] = session
                    elif param.kind == "path":
                        kwargs[param.name] = request.path_params[param.name]
                    else:
                        kwargs[param.name] = await _parse_body(request, param.schema, limit)
                if is_async:
                    result = await fn(**kwargs)
                else:
                    result = await anyio.to_thread.run_sync(partial(fn, **kwargs))
            except HTTPError as exc:
                return _error_response(exc.status, exc.code, exc.message, exc.details, exc.headers)
            if contract is not None:
                result = _enforce(result, contract, fn.__name__)
            return _to_response(result)

        endpoint.__name__ = fn.__name__
        return endpoint

    def _build(self) -> Any:
        # debug selalu False: traceback tidak boleh bocor ke klien.
        starlette = Starlette(
            debug=False,
            routes=[
                *self._routes,
                *(_frontend_routes(self._frontend_root) if self._frontend_root else []),
            ],
            exception_handlers={
                StarletteHTTPException: _http_exception_handler,
                Exception: _unhandled_exception_handler,
            },
        )
        return SecurityMiddleware(
            starlette,
            csp=self._csp,
            production=self._production,
            secure_cookies=self._secure,
            limiter=RateLimiter.from_spec(self._global_limit) if self._global_limit else None,
            csrf=self._csrf,
            trusted_proxy_hops=self._hops,
        )

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self._asgi is None:
            self._asgi = self._build()
        if scope["type"] == "http":
            scope["simpy.app"] = self
        await self._asgi(scope, receive, send)
