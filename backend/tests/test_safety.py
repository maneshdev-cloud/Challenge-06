"""Tests for medical triage interceptor, stale data fallback, and numeric validator."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_fetcher import PRESETS, _build_replay_payload, clear_cache, fetch_city_atmospheric_data
from engine import build_evidence_bundle
from safety import check_medical_emergency, validate_narrative
from schemas import PlanRequest


def test_medical_emergency_triage() -> None:
    """Verify acute respiratory symptoms immediately trigger emergency alert."""
    for phrase in ("My son is wheezing badly", "I have chest pain", "blue lips", "saans nahi aa rahi"):
        triggered, directive = check_medical_emergency(phrase)
        assert triggered is True
        assert directive is not None
        assert "108" in directive

    safe_ok, safe_msg = check_medical_emergency("Can my dad walk at 7 AM?")
    assert safe_ok is False
    assert safe_msg is None


def test_stale_data_fallback() -> None:
    """Verify simulate_stale=True and live API timeouts return historical replay with zero crashes."""
    clear_cache()
    payload = asyncio.run(fetch_city_atmospheric_data("delhi", simulate_stale=True))
    assert payload["provenance"]["is_stale"] is True
    assert payload["provenance"]["is_fallback_replay"] is True
    assert payload["provenance"]["data_type"] == "historical_replay"
    assert len(payload["hourly_raw"]["pm2_5"]) == 24

    # Also test graceful degradation when Open-Meteo times out
    def _timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Simulated Open-Meteo timeout", request=request)

    clear_cache()
    async def _run_timeout() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_timeout_handler)) as client:
            return await fetch_city_atmospheric_data("mumbai", simulate_stale=False, http_client=client)

    timeout_payload = asyncio.run(_run_timeout())
    assert timeout_payload["provenance"]["is_stale"] is True
    assert timeout_payload["provenance"]["is_fallback_replay"] is True
    assert timeout_payload["city"] == "mumbai"
    assert len(timeout_payload["multiday_raw"]["pm2_5"]) == 120

    # Test HTTP 404 / 503 / 504 errors from Open-Meteo degrade gracefully without crashing
    for status_code in (404, 503, 504):
        clear_cache()

        def _http_err(request: httpx.Request, code=status_code) -> httpx.Response:
            return httpx.Response(code, request=request)

        async def _run_http_err() -> dict:
            async with httpx.AsyncClient(transport=httpx.MockTransport(_http_err)) as client:
                return await fetch_city_atmospheric_data("pune", simulate_stale=False, http_client=client)

        err_payload = asyncio.run(_run_http_err())
        assert err_payload["provenance"]["is_stale"] is True
        assert len(err_payload["hourly_raw"]["pm2_5"]) == 24


def test_numeric_and_policy_validator() -> None:
    """Verify validator rejects hallucinated metrics, safe claims, and houseplant tips while allowing valid text."""
    delhi_preset = next(p for p in PRESETS if p["id"] == "delhi_family")
    req = PlanRequest(**delhi_preset, simulate_stale=True)
    raw = _build_replay_payload("delhi", "test")
    bundle = build_evidence_bundle(req, raw, current_hour=8)

    # Valid narrative with age, PM2.5, comma-formatted CO2e, and stale disclosure must pass
    valid_text = (
        f"Live data is unavailable (historical replay shown). "
        f"For your 8-year-old child, PM2.5 is {bundle.air_snapshot.current_pm25} ug/m3 and "
        f"India NAQI is {bundle.air_snapshot.current_naqi}. "
        f"You save {bundle.breathe_less.dose_avoided_ug} ug and 2,400 g CO2e. "
        "Houseplants do not remove PM2.5."
    )
    ok, reasons = validate_narrative(valid_text, bundle)
    assert ok is True, f"Unexpected validator failure: {reasons}"

    # Hallucinated metric value must fail
    bad_num_text = (
        "Live data is unavailable (historical replay). "
        "Today PM2.5 is 999 ug/m3 and you save 9,500 g CO2e."
    )
    ok_bad, reasons_bad = validate_narrative(bad_num_text, bundle)
    assert ok_bad is False
    assert len(reasons_bad) >= 1

    # Banned "safe window" claim must fail
    ok_safe, _ = validate_narrative("Live data unavailable (replay). 2 PM is a safe window.", bundle)
    assert ok_safe is False

    # Banned houseplant advice must fail
    ok_plant, _ = validate_narrative("Live data unavailable (replay). Buy a snake plant for PM2.5.", bundle)
    assert ok_plant is False
