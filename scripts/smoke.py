#!/usr/bin/env python3
"""End-to-end API & security contract smoke verification for PRANA-AI."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from main import app  # noqa: E402


def _check(label: str, passed: bool, detail: str = "") -> bool:
    status = "PASS" if passed else "FAIL"
    suffix = f" ({detail})" if detail else ""
    print(f"{status}  {label}{suffix}")
    return passed


def run_smoke(base_url: str | None = None) -> int:
    """Execute contract and security header smoke checks against ASGI app or live HTTP base."""
    os.environ.setdefault("PRANA_BUNDLE_SECRET", "smoke-test-secret-key")
    checks: list[bool] = []

    if base_url:
        import httpx

        http = httpx.Client(base_url=base_url.rstrip("/"), timeout=10.0)
        get_fn = http.get
        post_fn: Any = http.post
    else:
        tc = TestClient(app)
        get_fn = tc.get
        post_fn = tc.post

    health = get_fn("/health")
    checks.append(_check("GET /health returns 200", health.status_code == 200))
    checks.append(
        _check(
            "Security headers present on API response",
            health.headers.get("x-content-type-options") == "nosniff"
            and health.headers.get("x-frame-options") == "DENY"
            and health.headers.get("cache-control") == "no-store"
            and bool(health.headers.get("x-request-id")),
        )
    )

    plan_res = post_fn("/v1/plan", json={"city": "delhi", "simulate_stale": True, "skip_llm": True})
    plan_json = plan_res.json() if plan_res.status_code == 200 else {}
    has_bundle = isinstance(plan_json.get("evidence_bundle"), dict) and bool(
        plan_json.get("evidence_bundle")
    )
    checks.append(
        _check(
            "POST /v1/plan returns signed EvidenceBundle",
            plan_res.status_code == 200
            and has_bundle
            and len(plan_json.get("evidence_signature", "")) == 64,
        )
    )

    if has_bundle:
        tampered = dict(plan_json["evidence_bundle"])
        tampered["city"] = "tampered_city"
        tamper_res = post_fn(
            "/v1/chat",
            json={
                "message": "When should I walk?",
                "evidence_bundle": tampered,
                "evidence_signature": plan_json["evidence_signature"],
                "language": "en",
            },
        )
        checks.append(
            _check(
                "POST /v1/chat rejects tampered evidence with 403",
                tamper_res.status_code == 403,
                f"status={tamper_res.status_code}",
            )
        )
    else:
        checks.append(
            _check("POST /v1/chat rejects tampered evidence with 403", False, "missing bundle")
        )

    evil_origin = post_fn(
        "/v1/plan",
        headers={"origin": "https://evil.example", "host": "prana-ai.vercel.app"},
        json={"city": "delhi", "simulate_stale": True, "skip_llm": True},
    )
    checks.append(
        _check(
            "Cross-origin POST rejected with 403",
            evil_origin.status_code == 403,
            f"status={evil_origin.status_code}",
        )
    )

    bad_upload = post_fn(
        "/v1/audit-room",
        files={"file": ("evil.txt", b"not-an-image", "text/plain")},
    )
    checks.append(
        _check(
            "Non-image upload rejected with 415",
            bad_upload.status_code == 415,
            f"status={bad_upload.status_code}",
        )
    )

    passed_all = all(checks)
    print("\nAll PRANA-AI smoke checks passed." if passed_all else "\nSmoke checks FAILED.")
    return 0 if passed_all else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PRANA-AI API security & contract smoke test.")
    parser.add_argument("--base-url", help="Optional live server base URL (uses ASGI if omitted).")
    args = parser.parse_args()
    raise SystemExit(run_smoke(args.base_url))
