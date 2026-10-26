"""Klien ASGI mini untuk test: cookie jar dan handshake CSRF otomatis, tanpa httpx."""

from __future__ import annotations

import asyncio
import json as jsonlib
from dataclasses import dataclass, field
from typing import Any

CSRF_NAMES = ("__Host-simpy_csrf", "simpy_csrf")
UNSAFE_EXEMPT = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Resp:
    status: int
    headers: dict[str, str]
    body: bytes
    raw_headers: list[tuple[str, str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")

    @property
    def set_cookies(self) -> list[str]:
        return [v for k, v in self.raw_headers if k == "set-cookie"]

    def cookie(self, name: str) -> str | None:
        for header in self.set_cookies:
            if header.startswith(name + "="):
                return header
        return None

    def json(self) -> Any:
        return jsonlib.loads(self.body)


class Client:
    def __init__(
        self,
        app: Any,
        *,
        auto_csrf: bool = True,
        ip: str = "127.0.0.1",
        raise_app_exceptions: bool = True,
    ) -> None:
        self.app, self.auto_csrf, self.ip = app, auto_csrf, ip
        self.raise_app_exceptions = raise_app_exceptions
        self.cookies: dict[str, str] = {}

    def csrf_token(self) -> str | None:
        for name in CSRF_NAMES:
            if name in self.cookies:
                return self.cookies[name]
        return None

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Resp:
        headers = dict(headers or {})
        lowered = {k.lower() for k in headers}
        if self.auto_csrf and method.upper() not in UNSAFE_EXEMPT:
            if self.csrf_token() is None:
                self._send("GET", "/", None, None, {}, swallow=True)
            token = self.csrf_token()
            if token and "x-csrf-token" not in lowered:
                headers["x-csrf-token"] = token
        return self._send(method, path, json, body, headers)

    def get(self, path: str, **kw: Any) -> Resp:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Resp:
        return self.request("POST", path, **kw)

    def put(self, path: str, **kw: Any) -> Resp:
        return self.request("PUT", path, **kw)

    def delete(self, path: str, **kw: Any) -> Resp:
        return self.request("DELETE", path, **kw)

    def _send(self, method, path, json, body, headers, swallow=False) -> Resp:
        headers = dict(headers)
        if self.cookies and "cookie" not in {k.lower() for k in headers}:
            headers["cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        resp = asyncio.run(
            _call(
                self.app, method, path, json, body, headers, self.ip,
                swallow or not self.raise_app_exceptions,
            )
        )
        for header in resp.set_cookies:
            first, *attrs = [part.strip() for part in header.split(";")]
            name, _, value = first.partition("=")
            if value == "" or "Max-Age=0" in attrs:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value
        return resp


def call(
    app: Any,
    method: str,
    path: str,
    *,
    json: Any = None,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    raise_app_exceptions: bool = True,
    csrf: bool = True,
    ip: str = "127.0.0.1",
) -> Resp:
    client = Client(app, auto_csrf=csrf, ip=ip, raise_app_exceptions=raise_app_exceptions)
    return client.request(method, path, json=json, body=body, headers=headers)


async def _call(app, method, path, json, body, headers, ip, swallow) -> Resp:
    payload = b""
    hdrs = {"host": "testserver"}
    if json is not None:
        payload = jsonlib.dumps(json).encode()
        hdrs["content-type"] = "application/json"
    elif body is not None:
        payload = body
    if payload:
        hdrs["content-length"] = str(len(payload))
    hdrs.update({k.lower(): v for k, v in headers.items()})

    raw_path, _, query = path.partition("?")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": raw_path,
        "raw_path": raw_path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(k.encode(), v.encode()) for k, v in hdrs.items()],
        "client": (ip, 50000),
        "server": ("testserver", 80),
    }

    sent = False

    async def receive() -> dict:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        return {"type": "http.disconnect"}

    status = 500
    out_headers: dict[str, str] = {}
    raw: list[tuple[str, str]] = []
    chunks: list[bytes] = []

    async def send(message: dict) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
            for k, v in message.get("headers", []):
                key, value = k.decode().lower(), v.decode()
                out_headers[key] = value
                raw.append((key, value))
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    try:
        await app(scope, receive, send)
    except Exception:
        if not swallow:
            raise
    return Resp(status, out_headers, b"".join(chunks), raw)
