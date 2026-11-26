"""Tests for proxy-safe client IP resolution, rate limiter, origin CSRF, and response headers."""

from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.requests import Request

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
