"""Tests for medical triage interceptor, stale data fallback, and category-bound validator."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from data_fetcher import PRESETS, build_replay_payload, clear_cache, fetch_city_atmospheric_data
from engine import build_evidence_bundle
from safety import (
    check_medical_emergency,
    sign_evidence_bundle,
    validate_narrative,
    verify_evidence_bundle,
)
from schemas import PlanRequest


def test_medical_emergency_triage() -> None:
    """Verify EN/Hinglish/Indic distress and curly-apostrophe phrases trigger emergency alert."""
    phrases = (
        "My son is wheezing badly",
        "I have chest pain",
        "blue lips",
        "saans nahi aa rahi",
        "he can\u2019t breathe cleanly",
        "severe difficulty breathing",
        "बच्चे को सांस नहीं आ रही",
        "শ্বাসকষ্ট হচ্ছে",
    )
    for phrase in phrases:
        triggered, directive = check_medical_emergency(phrase)
        assert triggered is True, f"Expected ER alert for: {phrase}"
        assert directive is not None
        assert "108" in directive

    safe_ok, safe_msg = check_medical_emergency("Can my dad walk at 7 AM?")
    assert safe_ok is False
    assert safe_msg is None


def test_stale_data_fallback() -> None:
    """Verify simulate_stale=True and Open-Meteo errors return historical replay cleanly."""
    clear_cache()
    payload = asyncio.run(fetch_city_atmospheric_data("delhi", simulate_stale=True))
    assert payload["provenance"]["is_stale"] is True
    assert payload["provenance"]["is_fallback_replay"] is True
    assert payload["provenance"]["data_type"] == "historical_replay"
    assert len(payload["hourly_raw"]["pm2_5"]) == 24

    def _timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Simulated Open-Meteo timeout", request=request)

    clear_cache()

    async def _run_timeout() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_timeout_handler)) as client:
            return await fetch_city_atmospheric_data(
                "mumbai", simulate_stale=False, http_client=client
            )

    timeout_payload = asyncio.run(_run_timeout())
    assert timeout_payload["provenance"]["is_fallback_replay"] is True
    assert len(timeout_payload["multiday_raw"]["pm2_5"]) == 120

    for status_code in (404, 503, 504):
        clear_cache()

        def _http_err(request: httpx.Request, code=status_code) -> httpx.Response:
            return httpx.Response(code, request=request)

        async def _run_http_err(_err=_http_err) -> dict:
            async with httpx.AsyncClient(transport=httpx.MockTransport(_err)) as client:
                return await fetch_city_atmospheric_data(
                    "pune", simulate_stale=False, http_client=client
                )

        err_payload = asyncio.run(_run_http_err())
        assert err_payload["provenance"]["is_stale"] is True
        assert len(err_payload["hourly_raw"]["pm2_5"]) == 24


def test_numeric_category_binding_and_policy_validator() -> None:
    """Verify validator rejects cross-metric confusion, hallucinated %, safe claims, and plants."""
    delhi_preset = next(p for p in PRESETS if p["id"] == "delhi_family")
    req = PlanRequest(**delhi_preset, simulate_stale=True)
    raw = build_replay_payload("delhi", "test")
    bundle = build_evidence_bundle(req, raw, current_hour=8)

    valid_text = (
        "Live data is unavailable (historical replay shown). "
        "For your 8-year-old child with a 15 min wait, "
        f"PM2.5 is {bundle.air_snapshot.current_pm25} ug/m3 "
        f"and Estimated NAQI is {bundle.air_snapshot.current_naqi}. "
        f"You save {bundle.breathe_less.dose_avoided_ug} ug and 2,400 g CO2e "
        f"({bundle.breathe_less.reduction_pct}% less). Houseplants do not remove PM2.5."
    )
    ok, reasons = validate_narrative(valid_text, bundle)
    assert ok is True, f"Unexpected validator failure: {reasons}"

    # Cross-metric leakage: 2400 is valid for g CO2e, NEVER valid for ug/m3 PM2.5
    cross_metric_text = (
        "Live data unavailable (historical replay). Today PM2.5 is 2400 ug/m3 indoors."
    )
    ok_cross, reasons_cross = validate_narrative(cross_metric_text, bundle)
    assert ok_cross is False
    assert reasons_cross

    # Hallucinated percentage must fail
    bad_pct = "Live data unavailable (historical replay). You will reduce exposure by 99% today."
    ok_pct, _ = validate_narrative(bad_pct, bundle)
    assert ok_pct is False

    # Banned "safe window" and affirmative houseplant claims (even with later negation clause)
    ok_safe, _ = validate_narrative(
        "Live data unavailable (replay). 2 PM is a safe window.", bundle
    )
    assert ok_safe is False
    ok_plant, _ = validate_narrative(
        "Live data unavailable (replay). Buy a snake plant for PM2.5.", bundle
    )
    assert ok_plant is False
    ok_mixed_clause, _ = validate_narrative(
        "Live data unavailable (replay). Buy a snake plant; avoid dry sweeping.", bundle
    )
    assert ok_mixed_clause is False


def test_hmac_bundle_signing_and_key_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify HMAC signing/tamper detection and zero coupling to GEMINI_API_KEY or deploy IDs."""
    monkeypatch.setenv("PRANA_BUNDLE_SECRET", "unit-test-hmac-secret-key")
    preset = PRESETS[0]
    bundle = build_evidence_bundle(
        PlanRequest(**preset), build_replay_payload(preset["city"], "test"), current_hour=9
    )

    sig = sign_evidence_bundle(bundle)
    assert len(sig) == 64
    assert verify_evidence_bundle(bundle, sig) is True

    # Any tampered field or invalid/missing signature must fail verification
    tampered_city = bundle.model_copy(update={"city": "tampered_city"})
    tampered_air = bundle.model_copy(
        update={
            "air_snapshot": bundle.air_snapshot.model_copy(update={"current_pm25": 1.0}),
        }
    )
    assert verify_evidence_bundle(tampered_city, sig) is False
    assert verify_evidence_bundle(tampered_air, sig) is False
    assert verify_evidence_bundle(bundle, "") is False
    assert verify_evidence_bundle(bundle, "0" * 64) is False

    # Rotating GEMINI_API_KEY must NEVER change HMAC bundle signatures,
    # and deployed envs without PRANA_BUNDLE_SECRET must fail loudly rather than use deploy IDs.
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key-one")
    sig_one = sign_evidence_bundle(bundle)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key-two")
    sig_two = sign_evidence_bundle(bundle)
    assert sig_one == sig_two

    monkeypatch.delenv("PRANA_BUNDLE_SECRET", raising=False)
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VERCEL_PROJECT_ID", "prj_public_123")
    with pytest.raises(RuntimeError, match="PRANA_BUNDLE_SECRET"):
        sign_evidence_bundle(bundle)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    # Local ephemeral fallback remains stable in-process while GEMINI_API_KEY changes.
    sig_local_1 = sign_evidence_bundle(bundle)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key-three")
    sig_local_2 = sign_evidence_bundle(bundle)
    assert sig_local_1 == sig_local_2
