"""HTTP security headers, proxy-safe IP resolution, origin checks, and rate limiting."""

from __future__ import annotations

import os
import time
import uuid
from collections import OrderedDict, deque
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = [
    "DEFAULT_RATE_LIMITER",
    "MAX_AUDIT_BODY_BYTES",
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
MAX_AUDIT_BODY_BYTES = 5 * 1024 * 1024 + 512 * 1024  # 5 MB image + multipart headers


class SlidingWindowRateLimiter:
    """Bounded per-key sliding-window rate limiter with stale bucket eviction."""

    def __init__(
        self,
        max_requests: int = RATE_LIMIT_MAX_REQUESTS,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
        max_buckets: int = 1000,
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
            # Prefer evicting an unblocked oldest key rather than resetting a rate-limited IP.
            victim = next(
                (ip for ip, q in self.buckets.items() if len(q) < self.max_requests),
                next(iter(self.buckets)),
            )
            del self.buckets[victim]

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Record a hit for `key`; return (allowed, retry_after_seconds)."""
        current = time.monotonic() if now is None else now
        bucket = self.buckets.get(key)
        if bucket is None:
            if len(self.buckets) >= self.max_buckets:
                self._evict_expired(current)
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


def _trusted_proxy_mode() -> str | None:
    """Identify deployment proxy mode so spoofed forwarding headers are rejected directly."""
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
        return "vercel"
    if os.getenv("RENDER") or os.getenv("TRUST_PROXY_HEADERS", "").strip() == "1":
        return "proxy"
    return None


def resolve_client_ip(request: Request) -> str:
    """Resolve client IP trusting forwarding headers only behind known proxy environments."""
    proxy_mode = _trusted_proxy_mode()
    if proxy_mode == "vercel":
        for hdr in ("x-vercel-forwarded-for", "x-real-ip"):
            if val := request.headers.get(hdr, "").strip():
                return val.split(",")[0].strip()
    if proxy_mode in {"vercel", "proxy"}:
        # Behind Render / generic proxies, Cloudflare's overwritten header and rightmost
        # proxy-appended X-Forwarded-For hop take priority over client-spoofable X-Real-IP.
        if cf_ip := request.headers.get("cf-connecting-ip", "").strip():
            return cf_ip.split(",")[0].strip()
        if forwarded := request.headers.get("x-forwarded-for", "").strip():
            hops = [h.strip() for h in forwarded.split(",") if h.strip()]
            if hops:
                return hops[-1]
        if real_ip := request.headers.get("x-real-ip", "").strip():
            return real_ip.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(
    request: Request,
    max_requests: int | None = None,
    limiter: SlidingWindowRateLimiter = DEFAULT_RATE_LIMITER,
) -> None:
    """Enforce per-IP rate limiting on expensive AI endpoints."""
    client_host = resolve_client_ip(request)
    is_test_runner = bool(
        os.getenv("PYTEST_CURRENT_TEST") or os.getenv("PRANA_TESTING", "").strip() == "1"
    )
    if client_host == "testclient" and is_test_runner:
        return
    if max_requests is not None and max_requests != limiter.max_requests:
        temp_limiter = SlidingWindowRateLimiter(
            max_requests=max_requests, window_seconds=limiter.window_seconds
        )
        temp_limiter.buckets = limiter.buckets
        allowed, retry_after = temp_limiter.allow(client_host)
    else:
        allowed, retry_after = limiter.allow(client_host)
    if not allowed:
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


class SecurityAndRequestMiddleware:  # pylint: disable=too-few-public-methods
    """Attach security headers, X-Request-Id, and no-store caching on API responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        req_headers = dict(scope.get("headers", []))
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "GET")).upper()
        if method == "POST" and path.endswith("/audit-room"):
            raw_len = req_headers.get(b"content-length", b"").decode("latin-1").strip()
            if raw_len.isdigit() and int(raw_len) > MAX_AUDIT_BODY_BYTES:
                resp = JSONResponse(
                    status_code=413,
                    content={
                        "detail": "Image is larger than the 5 MB limit. "
                        "Please upload a photo under 5 MB."
                    },
                )
                await resp(scope, receive, send)
                return

        request_id = (
            req_headers.get(b"x-vercel-id", b"").decode("latin-1").strip()
            or req_headers.get(b"x-request-id", b"").decode("latin-1").strip()
            or uuid.uuid4().hex[:16]
        )

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
                            b"camera=(self), microphone=(self), geolocation=(self), "
                            b"payment=(), usb=()",
                        ),
                        (b"x-request-id", request_id.encode("latin-1")),
                    ]
                )
                if path.startswith(("/v1/", "/api/", "/health")):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, _send_with_headers)


class StripApiPrefixMiddleware:  # pylint: disable=too-few-public-methods
    """Normalize /api/* paths so same-origin Vercel and Vite proxy calls resolve identically."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).startswith("/api/"):
            scope = dict(scope)
            scope["path"] = str(scope["path"])[4:] or "/"
        await self.app(scope, receive, send)
