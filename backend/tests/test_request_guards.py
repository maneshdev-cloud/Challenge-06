"""Tests for proxy-safe client IP resolution, rate limiter, origin CSRF, and response headers."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.types import Message

from main import app
from request_guards import SlidingWindowRateLimiter, is_allowed_origin, resolve_client_ip

client = TestClient(app)


def _fake_request(
    *,
    headers: dict[str, str] | None = None,
    client_host: str = "198.51.100.7",
) -> Request:
    """Construct a minimal Starlette Request with deterministic socket peer and headers."""
    items = (headers or {}).items()
    raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in items]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/plan",
        "headers": raw_headers,
        "client": (client_host, 54321),
    }
    return Request(scope)


def test_resolve_client_ip_ignores_spoofed_forwarded_for_without_proxy(monkeypatch) -> None:
    """Direct clients must not bypass IP limits by forging X-Forwarded-For headers."""
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)

    req = _fake_request(
        headers={"x-forwarded-for": "1.2.3.4, 5.6.7.8", "x-real-ip": "9.9.9.9"},
        client_host="198.51.100.7",
    )
    assert resolve_client_ip(req) == "198.51.100.7"


def test_resolve_client_ip_respects_trusted_vercel_and_proxy_hops(monkeypatch) -> None:
    """Trusted proxy environments use platform headers or rightmost proxy-appended hop."""
    monkeypatch.setenv("VERCEL", "1")
    vercel_req = _fake_request(
        headers={
            "x-forwarded-for": "1.2.3.4, 203.0.113.55",
            "x-vercel-forwarded-for": "203.0.113.10",
        }
    )
    assert resolve_client_ip(vercel_req) == "203.0.113.10"

    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("RENDER", "1")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    render_req = _fake_request(
        headers={
            "x-vercel-forwarded-for": "198.51.100.200",
            "x-real-ip": "1.2.3.4",
            "x-forwarded-for": "spoofed.1.2.3, 203.0.113.77",
        }
    )
    assert resolve_client_ip(render_req) == "203.0.113.77"
    cf_req = _fake_request(headers={"cf-connecting-ip": "203.0.113.88", "x-real-ip": "1.2.3.4"})
    assert resolve_client_ip(cf_req) == "203.0.113.88"


def test_resolve_client_ip_custom_proxy_ignores_cf_connecting_ip(monkeypatch) -> None:
    """Generic TRUST_PROXY_HEADERS=1 proxies must ignore spoofable CF-Connecting-IP headers."""
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")

    req = _fake_request(
        headers={
            "cf-connecting-ip": "1.1.1.1",
            "x-forwarded-for": "spoofed.1.2.3, 203.0.113.99",
            "x-real-ip": "9.9.9.9",
        },
        client_host="10.0.0.5",
    )
    assert resolve_client_ip(req) == "203.0.113.99"

    only_cf_req = _fake_request(
        headers={"cf-connecting-ip": "1.1.1.1"},
        client_host="10.0.0.5",
    )
    assert resolve_client_ip(only_cf_req) == "10.0.0.5"


def test_sliding_window_rate_limiter_bounds_and_evicts() -> None:
    """Verify active blocked buckets are preserved when new keys trigger eviction."""
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=10.0, max_buckets=2)
    assert limiter.allow("ip_a", now=0.0) == (True, 0)
    assert limiter.allow("ip_a", now=0.0) == (True, 0)
    assert limiter.allow("ip_b", now=0.0) == (True, 0)
    assert limiter.allow("ip_c", now=0.0) == (True, 0)
    # ip_a must still remain rate-limited after ip_c admits a new bucket
    allowed, retry_after = limiter.allow("ip_a", now=1.0)
    assert allowed is False
    assert retry_after == 9

    assert limiter.allow("ip_a", now=10.5) == (True, 0)
    assert limiter.allow("ip_d", now=25.0) == (True, 0)
    assert len(limiter.buckets) <= 2

    # Saturation check: when all buckets are actively blocked, new keys must fail closed
    # without evicting or resetting an existing blocked IP's quota.
    sat = SlidingWindowRateLimiter(max_requests=1, window_seconds=10.0, max_buckets=2)
    assert sat.allow("blk_a", now=0.0) == (True, 0)
    assert sat.allow("blk_b", now=0.0) == (True, 0)
    allowed_c, retry_c = sat.allow("blk_c", now=1.0)
    assert allowed_c is False
    assert retry_c == 9
    assert sat.allow("blk_a", now=2.0) == (False, 8)
    assert len(sat.buckets) == 2


def test_chunked_json_post_exceeding_limit_aborts_before_parse() -> None:
    """Chunked >512 KB JSON POST to /v1/chat must abort early with 413 in middleware."""
    chunk = b"a" * (256 * 1024)
    chunks_delivered = 0
    sent_messages: list[Message] = []

    async def fake_receive() -> Message:
        nonlocal chunks_delivered
        chunks_delivered += 1
        return {"type": "http.request", "body": chunk, "more_body": chunks_delivered < 4}

    async def fake_send(msg: Message) -> None:
        sent_messages.append(msg)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/chat",
        "raw_path": b"/v1/chat",
        "query_string": b"",
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, fake_receive, fake_send))
    assert sent_messages[0]["status"] == 413
    assert chunks_delivered < 4


def test_cross_origin_post_rejected_and_api_headers_present() -> None:
    """Verify cross-site Origin POST gets 403 while /health sets security headers."""
    assert is_allowed_origin(None, "example.com", []) is True
    assert is_allowed_origin("https://example.com", "example.com", []) is True
    assert (
        is_allowed_origin("https://evil.example", "example.com", ["http://localhost:5173"]) is False
    )

    health = client.get("/health")
    assert health.status_code == 200
    assert health.headers.get("cache-control") == "no-store"
    assert health.headers.get("x-request-id")
    assert health.headers.get("cross-origin-opener-policy") == "same-origin"
    assert "payment=()" in (health.headers.get("permissions-policy") or "")

    evil_post = client.post(
        "/v1/plan",
        headers={"origin": "https://evil.example", "host": "prana-ai.vercel.app"},
        json={"city": "delhi"},
    )
    assert evil_post.status_code == 403

    spoofed_fwd_host = client.post(
        "/v1/plan",
        headers={
            "origin": "https://evil.example",
            "host": "prana-ai.vercel.app",
            "x-forwarded-host": "evil.example",
        },
        json={"city": "delhi"},
    )
    assert spoofed_fwd_host.status_code == 403


def test_request_id_sanitized_and_json_outer_limiter_enforced() -> None:
    """Allowlist valid X-Request-Id values and rate-limit /v1/chat before buffering body."""
    import re
    import time
    from collections import deque

    from request_guards import JSON_OUTER_RATE_LIMITER

    clean = client.get("/health", headers={"x-request-id": "req-123_abc:45.6"})
    assert clean.headers.get("x-request-id") == "req-123_abc:45.6"

    injected = client.get("/health", headers={"x-vercel-id": "bad\x00value spaces " + ("x" * 200)})
    sanitized_id = injected.headers.get("x-request-id") or ""
    assert re.fullmatch(r"[0-9a-f]{32}", sanitized_id) is not None

    JSON_OUTER_RATE_LIMITER.buckets["testclient"] = deque(
        [time.monotonic()] * JSON_OUTER_RATE_LIMITER.max_requests
    )
    try:
        flood_res = client.post("/v1/chat", json={"message": "wheezing badly"})
        assert flood_res.status_code == 429
        assert int(flood_res.headers.get("Retry-After", "0")) >= 1
    finally:
        JSON_OUTER_RATE_LIMITER.clear()
