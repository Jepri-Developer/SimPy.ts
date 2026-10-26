"""Lapisan keamanan: secure headers, rate limiting, CSRF, dan cookie. Hanya pustaka standar."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from collections import deque
from collections.abc import Callable, Hashable
from typing import Any
from urllib.parse import urlsplit

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SESSION_COOKIE = "simpy_session"
CSRF_COOKIE = "simpy_csrf"
CSRF_MAX_AGE = 7 * 24 * 3600
COOKIE_JAR_KEY = "simpy.cookies"

DEFAULT_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)


# --- header & cookie --------------------------------------------------------------------


def security_headers(csp: str, production: bool) -> list[tuple[bytes, bytes]]:
    headers = {
        "content-security-policy": csp,
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "strict-origin-when-cross-origin",
        "permissions-policy": "camera=(), microphone=(), geolocation=()",
        "cross-origin-opener-policy": "same-origin",
        "cross-origin-resource-policy": "same-origin",
    }
    if production:
        headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
    return [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]


def get_header(scope: dict[str, Any], name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


def parse_cookies(header: str) -> dict[str, str]:
    """Parser cookie sederhana. Bila nama dobel, yang pertama dipakai."""
    cookies: dict[str, str] = {}
    for part in header.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name and name not in cookies:
            cookies[name] = value.strip().strip('"')
    return cookies


def cookie_name(base: str, secure: bool) -> str:
    """Di mode secure, pakai awalan __Host- (wajib Secure, Path=/, tanpa Domain)."""
    return f"__Host-{base}" if secure else base


_COOKIE_NAME = re.compile(r"[A-Za-z0-9_-]+")
_COOKIE_VALUE = re.compile(r"[A-Za-z0-9_.-]*")


def build_cookie(
    name: str, value: str, *, max_age: int, http_only: bool, secure: bool, same_site: str = "Lax"
) -> str:
    if not _COOKIE_NAME.fullmatch(name) or not _COOKIE_VALUE.fullmatch(value):
        raise ValueError("nama/nilai cookie mengandung karakter yang tidak diizinkan")
    parts = [f"{name}={value}", "Path=/", f"Max-Age={int(max_age)}", f"SameSite={same_site}"]
    if http_only:
        parts.append("HttpOnly")
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def queue_cookie(scope: dict[str, Any], name: str, header: str) -> None:
    """Antrikan Set-Cookie; ditulis ke respons oleh SecurityMiddleware."""
    scope.setdefault(COOKIE_JAR_KEY, {})[name] = header


# --- IP klien & rate limit ---------------------------------------------------------------


def client_ip(scope: dict[str, Any], trusted_proxy_hops: int = 0) -> str:
    """IP klien. X-Forwarded-For hanya dipercaya bila jumlah proxy tepercaya diatur."""
    peer = scope.get("client")
    host = peer[0] if peer else "unknown"
    if trusted_proxy_hops > 0:
        parts = [p.strip() for p in get_header(scope, b"x-forwarded-for").split(",") if p.strip()]
        if len(parts) >= trusted_proxy_hops:
            return parts[-trusted_proxy_hops]
    return host


_RATE = re.compile(r"(\d{1,6})/(second|minute|hour)s?")
_UNITS = {"second": 1.0, "minute": 60.0, "hour": 3600.0}


def parse_rate(spec: str) -> tuple[int, float]:
    """'5/minute' -> (5, 60.0)."""
    match = _RATE.fullmatch(spec.strip().lower())
    if not match or int(match.group(1)) < 1:
        raise ValueError(f"rate limit '{spec}' tidak valid. Contoh: '5/minute', '100/hour'.")
    return int(match.group(1)), _UNITS[match.group(2)]


class RateLimiter:
    """Jendela geser di memori (per proses). Memori dibatasi oleh `max_keys`."""

    def __init__(
        self,
        limit: int,
        window: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        self.limit, self.window, self._clock, self._max_keys = limit, window, clock, max_keys
        self._events: dict[Hashable, deque[float]] = {}

    @classmethod
    def from_spec(cls, spec: str, **kwargs: Any) -> RateLimiter:
        limit, window = parse_rate(spec)
        return cls(limit, window, **kwargs)

    def hit(self, key: Hashable) -> float | None:
        """Catat satu request. None bila diizinkan; selain itu detik yang harus ditunggu."""
        now = self._clock()
        queue = self._events.get(key)
        if queue is None:
            if len(self._events) >= self._max_keys:
                self._purge(now)
            if len(self._events) >= self._max_keys:
                self._events.pop(next(iter(self._events)))  # buang yang tertua
            queue = self._events[key] = deque()
        cutoff = now - self.window
        while queue and queue[0] <= cutoff:
            queue.popleft()
        if len(queue) >= self.limit:
            return max(queue[0] + self.window - now, 0.0)
        queue.append(now)
        return None

    def _purge(self, now: float) -> None:
        cutoff = now - self.window
        for key in [k for k, q in self._events.items() if not q or q[-1] <= cutoff]:
            del self._events[key]


def retry_after_seconds(wait: float) -> int:
    return max(1, math.ceil(wait))


# --- CSRF ----------------------------------------------------------------------------------


class CsrfService:
    """Token = nonce.HMAC(nonce|binding). `binding` = id sesi (kosong bila belum login)."""

    def __init__(self, secret: bytes) -> None:
        self._key = hmac.new(secret, b"simpy-ts:csrf", hashlib.sha256).digest()

    def _sig(self, nonce: str, binding: str) -> str:
        mac = hmac.new(self._key, f"{nonce}|{binding}".encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()

    def issue(self, binding: str = "") -> str:
        nonce = secrets.token_urlsafe(16)
        return f"{nonce}.{self._sig(nonce, binding)}"

    def valid(self, token: str | None, binding: str = "") -> bool:
        if not token or len(token) > 200:
            return False
        nonce, dot, signature = token.partition(".")
        if not dot or not nonce:
            return False
        return hmac.compare_digest(signature.encode(), self._sig(nonce, binding).encode())


def origin_allowed(origin: str, host: str, allowed: frozenset[str]) -> bool:
    if origin in allowed:
        return True
    if origin == "null":
        return False
    try:
        netloc = urlsplit(origin).netloc.lower()
    except ValueError:
        return False
    return bool(netloc) and netloc == host.lower()


def csrf_problem(
    headers: Any,
    csrf: CsrfService,
    *,
    csrf_cookie: str,
    session_cookie: str,
    allowed_origins: frozenset[str],
) -> str | None:
    """Kembalikan pesan masalah, atau None bila request lolos pemeriksaan CSRF."""
    origin = headers.get("origin")
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site not in ("same-origin", "none"):
        if origin not in allowed_origins:
            return "Permintaan lintas situs ditolak."
    if origin is not None and not origin_allowed(origin, headers.get("host", ""), allowed_origins):
        return "Origin tidak diizinkan."
    cookies = parse_cookies(headers.get("cookie", ""))
    token = headers.get("x-csrf-token")
    cookie_token = cookies.get(csrf_cookie)
    if (
        not token
        or not cookie_token
        or not hmac.compare_digest(token.encode(), cookie_token.encode())
        or not csrf.valid(token, cookies.get(session_cookie, ""))
    ):
        return "Token CSRF tidak valid atau hilang."
    return None


# --- middleware ------------------------------------------------------------------------------


class SecurityMiddleware:
    """ASGI murni: rate limit global, secure headers, dan Set-Cookie (CSRF + antrean cookie)."""

    def __init__(
        self,
        app: Any,
        *,
        csp: str,
        production: bool,
        secure_cookies: bool,
        limiter: RateLimiter | None,
        csrf: CsrfService,
        trusted_proxy_hops: int = 0,
    ) -> None:
        self.app = app
        self._headers = security_headers(csp, production)
        self._secure = secure_cookies
        self._limiter = limiter
        self._csrf = csrf
        self._hops = trusted_proxy_hops
        self._csrf_cookie = cookie_name(CSRF_COOKIE, secure_cookies)
        self._session_cookie = cookie_name(SESSION_COOKIE, secure_cookies)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        request_cookies = parse_cookies(get_header(scope, b"cookie"))

        async def wrapped(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                for name, value in self._headers:
                    if name not in present:
                        headers.append((name, value))
                if path.startswith("/api/") and b"cache-control" not in present:
                    headers.append((b"cache-control", b"no-store"))
                for header in self._cookies_to_set(scope, path, request_cookies):
                    headers.append((b"set-cookie", header.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        if self._limiter is not None:
            wait = self._limiter.hit(client_ip(scope, self._hops))
            if wait is not None:
                body = json.dumps(
                    {"error": "rate_limited", "message": "Terlalu banyak permintaan. Coba lagi nanti."}
                ).encode()
                await wrapped(
                    {
                        "type": "http.response.start",
                        "status": 429,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                            (b"retry-after", str(retry_after_seconds(wait)).encode()),
                        ],
                    }
                )
                await wrapped({"type": "http.response.body", "body": body})
                return

        await self.app(scope, receive, wrapped)

    def _cookies_to_set(
        self, scope: dict[str, Any], path: str, request_cookies: dict[str, str]
    ) -> list[str]:
        jar = dict(scope.get(COOKIE_JAR_KEY, {}))
        if self._csrf_cookie not in jar and not path.startswith("/static/"):
            binding = request_cookies.get(self._session_cookie, "")
            if not self._csrf.valid(request_cookies.get(self._csrf_cookie), binding):
                jar[self._csrf_cookie] = build_cookie(
                    self._csrf_cookie,
                    self._csrf.issue(binding),
                    max_age=CSRF_MAX_AGE,
                    http_only=False,
                    secure=self._secure,
                )
        return list(jar.values())
