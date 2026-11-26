"""HTTP security headers, proxy-safe IP resolution, origin checks, and rate limiting."""

from __future__ import annotations

import os
import re
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.requests import Request as StarletteRequest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = [
    "DEFAULT_RATE_LIMITER",
    "JSON_OUTER_RATE_LIMITER",
    "JSON_OUTER_RATE_LIMIT_MAX_REQUESTS",
    "MAX_AUDIT_BODY_BYTES",
    "MAX_JSON_BODY_BYTES",
    "NON_LLM_RATE_LIMITER",
    "NON_LLM_RATE_LIMIT_MAX_REQUESTS",
    "RATE_LIMIT_MAX_REQUESTS",
    "RATE_LIMIT_WINDOW_SECONDS",
    "SecurityAndRequestMiddleware",
    "SlidingWindowRateLimiter",
    "StripApiPrefixMiddleware",
    "enforce_rate_limit",
    "is_allowed_origin",
    "resolve_client_ip",
]

RATE_LIMIT_WINDOW_SECONDS = 60.0
RATE_LIMIT_MAX_REQUESTS = 120
NON_LLM_RATE_LIMIT_MAX_REQUESTS = 90
JSON_OUTER_RATE_LIMIT_MAX_REQUESTS = 240
MAX_AUDIT_BODY_BYTES = 5 * 1024 * 1024 + 512 * 1024  # 5 MB image + multipart headers
MAX_JSON_BODY_BYTES = 512 * 1024  # 512 KB cap for JSON POST routes (/v1/plan, /v1/chat)


class SlidingWindowRateLimiter:
    """Bounded per-key sliding-window rate limiter with stale bucket eviction."""

    def __init__(
        self,
        max_requests: int = RATE_LIMIT_MAX_REQUESTS,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
        max_buckets: int = 50_000,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_buckets = max_buckets
        self.buckets: OrderedDict[str, deque[float]] = OrderedDict()

    def clear(self) -> None:
        """Reset all tracked buckets (used in unit tests)."""
        self.buckets.clear()

    def _evict_expired(self, now: float) -> None:
        stale_ips = [
            ip for ip, q in self.buckets.items() if not q or (now - q[-1]) >= self.window_seconds
        ]
        for ip in stale_ips:
            del self.buckets[ip]
        if len(self.buckets) >= self.max_buckets:
            # Evict only an unblocked oldest key; never reset an actively blocked client bucket.
            victim = next(
                (ip for ip, q in self.buckets.items() if len(q) < self.max_requests),
                None,
            )
            if victim is not None:
                del self.buckets[victim]

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Record a hit for `key`; return (allowed, retry_after_seconds)."""
        current = time.monotonic() if now is None else now
        bucket = self.buckets.get(key)
        if bucket is None:
            if len(self.buckets) >= self.max_buckets:
                self._evict_expired(current)
            if len(self.buckets) >= self.max_buckets:
                earliest = min((q[0] for q in self.buckets.values() if q), default=current)
                wait_s = max(1, int(self.window_seconds - (current - earliest) + 0.999))
                return False, wait_s
            bucket = deque()
            self.buckets[key] = bucket
        elif isinstance(self.buckets, OrderedDict):
            self.buckets.move_to_end(key)

        while bucket and (current - bucket[0]) >= self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            retry_after = max(1, int(self.window_seconds - (current - bucket[0]) + 0.999))
            return False, retry_after
        bucket.append(current)
        return True, 0


DEFAULT_RATE_LIMITER = SlidingWindowRateLimiter()
JSON_OUTER_RATE_LIMITER = SlidingWindowRateLimiter(
    max_requests=JSON_OUTER_RATE_LIMIT_MAX_REQUESTS,
    window_seconds=RATE_LIMIT_WINDOW_SECONDS,
)
NON_LLM_RATE_LIMITER = SlidingWindowRateLimiter(
    max_requests=NON_LLM_RATE_LIMIT_MAX_REQUESTS,
    window_seconds=RATE_LIMIT_WINDOW_SECONDS,
)


_PROXY_TRUSTED_SINGLE_HEADERS: dict[str, tuple[str, ...]] = {
    "vercel": ("x-vercel-forwarded-for", "x-real-ip"),
    "render": ("cf-connecting-ip",),
    "proxy": (),
}


def _trusted_proxy_mode() -> str | None:
    """Identify deployment proxy mode so spoofed forwarding headers are rejected directly."""
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
        return "vercel"
    if os.getenv("RENDER"):
        return "render"
    if os.getenv("TRUST_PROXY_HEADERS", "").strip() == "1":
        return "proxy"
    return None


def _rightmost_forwarded_ip(request: Request) -> str | None:
    """Return the rightmost hop appended by the perimeter reverse proxy."""
    if forwarded := request.headers.get("x-forwarded-for", "").strip():
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[-1]
    if real_ip := request.headers.get("x-real-ip", "").strip():
        return real_ip.split(",")[0].strip()
    return None


def resolve_client_ip(request: Request) -> str:
    """Resolve client IP trusting forwarding headers only behind known proxy environments."""
    proxy_mode = _trusted_proxy_mode()
    if proxy_mode:
        for hdr in _PROXY_TRUSTED_SINGLE_HEADERS[proxy_mode]:
            if val := request.headers.get(hdr, "").strip():
                return val.split(",")[0].strip()
        if ip := _rightmost_forwarded_ip(request):
            return ip
    return request.client.host if request.client else "unknown"


def _check_rate_limit_key(
    client_host: str,
    limiter: SlidingWindowRateLimiter = DEFAULT_RATE_LIMITER,
) -> int | None:
    """Record a hit for client_host and return retry_after seconds when throttled, else None."""
    allowed, retry_after = limiter.allow(client_host)
    return None if allowed else retry_after


def enforce_rate_limit(
    request: Request,
    limiter: SlidingWindowRateLimiter = DEFAULT_RATE_LIMITER,
) -> None:
    """Enforce per-IP rate limiting using dedicated limiter instances."""
    client_host = resolve_client_ip(request)
    retry_after = _check_rate_limit_key(client_host, limiter)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many requests right now; please wait a moment and try again.",
            headers={"Retry-After": str(retry_after)},
        )


def is_allowed_origin(origin: str | None, host: str | None, allowed_origins: list[str]) -> bool:
    """Return True for non-browser callers, same-host requests, or allowlisted origins."""
    if not origin:
        return True
    normalized = origin.strip().rstrip("/")
    if normalized in allowed_origins or "*" in allowed_origins:
        return True
    try:
        parsed_host = urlparse(normalized).netloc
    except ValueError:
        return False
    return bool(parsed_host and host and parsed_host.lower() == host.strip().lower())


_AUDIT_TOO_LARGE_DETAIL = "Image is larger than the 5 MB limit. Please upload a photo under 5 MB."
_JSON_TOO_LARGE_DETAIL = "Request payload exceeds the 512 KB size limit."


@dataclass(frozen=True)
class _BodyGuardPolicy:
    max_bytes: int
    too_large_detail: str
    limiter: SlidingWindowRateLimiter | None


_AUDIT_BODY_POLICY = _BodyGuardPolicy(
    MAX_AUDIT_BODY_BYTES, _AUDIT_TOO_LARGE_DETAIL, DEFAULT_RATE_LIMITER
)
_JSON_BODY_POLICY = _BodyGuardPolicy(
    MAX_JSON_BODY_BYTES, _JSON_TOO_LARGE_DETAIL, JSON_OUTER_RATE_LIMITER
)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _sanitize_request_id(req_headers: dict[bytes, bytes]) -> str:
    """Allowlist incoming request IDs or generate a hex UUID to block header injection."""
    for header_key in (b"x-vercel-id", b"x-request-id"):
        candidate = req_headers.get(header_key, b"").decode("latin-1").strip()
        if candidate and _REQUEST_ID_RE.fullmatch(candidate):
            return candidate
    return uuid.uuid4().hex


async def _prepare_bounded_receive(receive: Receive, max_bytes: int) -> tuple[Receive | None, bool]:
    """Buffer bounded POST body chunks; abort immediately if cumulative bytes > max_bytes."""
    chunks: list[bytes] = []
    total = 0
    disconnected = False
    while True:
        message = await receive()
        msg_type = message.get("type")
        if msg_type == "http.disconnect":
            disconnected = True
            break
        if msg_type != "http.request":
            continue
        chunk = message.get("body", b"")
        if chunk:
            total += len(chunk)
            if total > max_bytes:
                return None, False
            chunks.append(chunk)
        if not message.get("more_body", False):
            break

    body = b"".join(chunks)
    state = {"body_sent": disconnected and not body, "disc_sent": False}

    async def _replay_receive() -> Message:
        if not state["body_sent"]:
            state["body_sent"] = True
            return {"type": "http.request", "body": body, "more_body": disconnected}
        if disconnected and not state["disc_sent"]:
            state["disc_sent"] = True
            return {"type": "http.disconnect"}
        return await receive()

    return _replay_receive, True


def _build_security_send(path: str, request_id: str, send: Send) -> Send:
    """Wrap ASGI send to attach baseline security headers, X-Request-Id, and no-store."""

    async def _send_with_headers(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = list(message.get("headers", []))
            headers.extend(
                [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                    (
                        b"permissions-policy",
                        b"camera=(self), microphone=(self), geolocation=(self), payment=(), usb=()",
                    ),
                    (b"x-request-id", request_id.encode("latin-1")),
                ]
            )
            if path.startswith(("/v1/", "/api/", "/health")):
                headers.append((b"cache-control", b"no-store"))
            message["headers"] = headers
        await send(message)

    return _send_with_headers


class SecurityAndRequestMiddleware:  # pylint: disable=too-few-public-methods
    """Attach security headers, X-Request-Id, and pre-buffer origin/rate/size guards."""

    def __init__(self, app: ASGIApp, allowed_origins: list[str] | None = None) -> None:
        self.app = app
        self.allowed_origins = list(allowed_origins or [])

    async def _guard_post_body(
        self,
        scope: Scope,
        receive: Receive,
        send_with_headers: Send,
        policy: _BodyGuardPolicy,
    ) -> tuple[Receive | None, bool]:
        """Validate Origin, optional IP rate limit, Content-Length, and streamed bytes."""
        req = StarletteRequest(scope)
        origin = req.headers.get("origin")
        host = req.headers.get("host") or req.url.netloc
        if not is_allowed_origin(origin, host, self.allowed_origins):
            resp = JSONResponse(
                status_code=403, content={"detail": "Cross-origin requests are not allowed."}
            )
            await resp(scope, receive, send_with_headers)
            return None, False

        if policy.limiter is not None:
            retry_after = _check_rate_limit_key(resolve_client_ip(req), policy.limiter)
            if retry_after is not None:
                resp = JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Too many requests right now; please wait a moment and try again."
                    },
                    headers={"Retry-After": str(retry_after)},
                )
                await resp(scope, receive, send_with_headers)
                return None, False

        raw_len = req.headers.get("content-length", "").strip()
        if raw_len.isdigit() and int(raw_len) > policy.max_bytes:
            resp = JSONResponse(status_code=413, content={"detail": policy.too_large_detail})
            await resp(scope, receive, send_with_headers)
            return None, False

        bounded_receive, ok = await _prepare_bounded_receive(receive, policy.max_bytes)
        if not ok or bounded_receive is None:
            resp = JSONResponse(status_code=413, content={"detail": policy.too_large_detail})
            await resp(scope, receive, send_with_headers)
            return None, False
        return bounded_receive, True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        req_headers = dict(scope.get("headers", []))
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET")).upper()
        request_id = _sanitize_request_id(req_headers)
        send_with_headers = _build_security_send(path, request_id, send)
        active_receive = receive

        if method == "POST":
            policy = (
                _AUDIT_BODY_POLICY
                if path.endswith("/audit-room")
                else (_JSON_BODY_POLICY if path.endswith(("/chat", "/plan")) else None)
            )
            if policy is not None:
                bounded, ok = await self._guard_post_body(scope, receive, send_with_headers, policy)
                if not ok or bounded is None:
                    return
                active_receive = bounded

        await self.app(scope, active_receive, send_with_headers)


class StripApiPrefixMiddleware:  # pylint: disable=too-few-public-methods
    """Normalize /api/* paths so same-origin Vercel and Vite proxy calls resolve identically."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).startswith("/api/"):
            scope = dict(scope)
            scope["path"] = str(scope["path"])[4:] or "/"
        await self.app(scope, receive, send)
