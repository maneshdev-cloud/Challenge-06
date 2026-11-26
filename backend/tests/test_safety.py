"""Tests for medical triage interceptor, stale data fallback, and category-bound validator."""

from __future__ import annotations

import asyncio
import time
import unicodedata

import httpx
import pytest

from data_fetcher import PRESETS, build_replay_payload, clear_cache, fetch_city_atmospheric_data
from engine import build_evidence_bundle
from safety import (
    EMERGENCY_KEYWORDS,
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
    monkeypatch.setenv("PRANA_BUNDLE_SECRET", "unit-test-hmac-secret-key-32bytes!")
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
    monkeypatch.setenv("PRANA_BUNDLE_SECRET", "too-short-secret")
    with pytest.raises(RuntimeError, match="32 bytes"):
        sign_evidence_bundle(bundle)
    monkeypatch.delenv("PRANA_BUNDLE_SECRET", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    # Local ephemeral fallback remains stable in-process while GEMINI_API_KEY changes.
    sig_local_1 = sign_evidence_bundle(bundle)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key-three")
    sig_local_2 = sign_evidence_bundle(bundle)
    assert sig_local_1 == sig_local_2


def test_unicode_numerals_superscripts_and_pm25_prefix_rejected() -> None:
    """Reject fabricated Devanagari/Unicode numerals, ug/m³ leaks, and PM2.5-prefix numbers."""
    delhi_preset = next(p for p in PRESETS if p["id"] == "delhi_family")
    req = PlanRequest(**delhi_preset, simulate_stale=True)
    bundle = build_evidence_bundle(req, build_replay_payload("delhi", "test"), current_hour=8)

    valid_sup = (
        "Live data is unavailable (historical replay). "
        "For your 3-day trip (Day 2, Sat Nov 28), PM2.5 is "
        f"{bundle.air_snapshot.current_pm25} µg/m³."
    )
    assert validate_narrative(valid_sup, bundle)[0] is True

    bad_inputs = (
        "Live data is unavailable (historical replay). आज PM2.5 ३५० µg/m³ है।",
        "Live data is unavailable (historical replay). Exposure dropped ९९ प्रतिशत.",
        "Live data is unavailable (historical replay). PM2.5 is 999 today.",
        "Live data is unavailable (historical replay). एक्यूआई ८८८ है।",
        "Live data is unavailable (historical replay). एक्यूआई 777 है।",
    )
    for bad in bad_inputs:
        ok, reasons = validate_narrative(bad, bundle)
        assert ok is False, f"Expected rejection for fabricated text: {bad}"
        assert reasons


def test_multilingual_single_script_triage_and_english_paraphrases() -> None:
    """Assert single-script Indic keywords and triage triggers across all 8 languages + EN."""
    for kw in EMERGENCY_KEYWORDS:
        scripts = {
            unicodedata.name(ch, "").split()[0] for ch in kw if ord(ch) > 127 and ch.isalpha()
        }
        assert len(scripts) <= 1, f"Mixed script detected in emergency keyword {kw!r}: {scripts}"

    eight_lang_and_en_phrases = (
        "trouble breathing",
        "hard to breathe",
        "I can't catch my breath",
        "short of breath",
        "feels like a heart attack",
        "sharp pain in my chest",
        "lips turning blue",
        "suffocating indoors",
        "unable to breathe",
        "can not breathe",
        "my chest feels tight",
        "can\u200b't breathe right now",
        "saans phool rahi hai",
        "सीने में दर्द हो रहा है",
        "मला श्वास घेता येत नाही",
        "ಉಸಿರಾಡಲು ಆಗುತ್ತಿಲ್ಲ",
        "શ્વાસ નથી લેવાતો",
        "শ্বাসকষ্ট হচ্ছে",
        "மூச்சுத் திணறல்",
        "శ్వాస అందడం లేదు",
    )
    for phrase in eight_lang_and_en_phrases:
        triggered, directive = check_medical_emergency(phrase)
        assert triggered is True, f"Expected triage alert for: {phrase!r}"
        assert directive and "108" in directive


def test_strict_grounding_unanchored_numbers_indic_claims_and_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify strict grounding on standalone numbers, Indic claims, dosing, and bundle TTL."""
    monkeypatch.setenv("PRANA_BUNDLE_SECRET", "strict-ttl-test-secret-32-bytes!")
    delhi_preset = next(p for p in PRESETS if p["id"] == "delhi_family")
    req = PlanRequest(**delhi_preset, simulate_stale=True)
    bundle = build_evidence_bundle(req, build_replay_payload("delhi", "test"), current_hour=8)

    base_ok = (
        "Live data is unavailable (historical replay). "
        f"Current PM2.5 is {bundle.air_snapshot.current_pm25} ug/m3."
    )
    assert validate_narrative(base_ok, bundle)[0] is True

    # Near-miss ungrounded value (e.g. +2.7) must fail tight rounding check
    near_miss = (
        "Live data is unavailable (historical replay). "
        f"PM2.5 is {round(bundle.air_snapshot.current_pm25 + 2.7, 1)} ug/m3."
    )
    assert validate_narrative(near_miss, bundle)[0] is False

    bad_claims = (
        "Live data unavailable (historical replay). PM2.5 reaches 987.",
        "Live data unavailable (historical replay). The AQI will hit 999.",
        "Live data unavailable (historical replay). The PM2.5 level 987.",
        "Live data unavailable (historical replay). 98765 of particulate in air.",
        "Live data unavailable (historical replay). 2 PM is a safe time to jog outside.",
        "Live data unavailable (historical replay). Air is perfectly safe to go outside.",
        "Live data unavailable (historical replay). दोपहर बाहर जाना पूरी तरह सुरक्षित है।",
        "Live data unavailable (historical replay). कमरे में मनी प्लांट रखें।",
        "Live data unavailable (historical replay). வெளியே செல்ல பாதுகாப்பானது.",
        "Live data unavailable (historical replay). Take 2 puffs of your steroid inhaler.",
        "Live data unavailable (historical replay). You might have asthma.",
        "Live data unavailable (historical replay). You could have bronchitis.",
        "Live data unavailable (historical replay). Consider using an inhaler.",
        "Live data unavailable (historical replay). Try taking a steroid tablet.",
        "Live data unavailable (historical replay). It could be bronchitis.",
        "Live data unavailable (historical replay). This could be asthma.",
        "Live data unavailable (historical replay). It might be an asthma attack.",
        "Live data unavailable (historical replay). "
        "Increase the number of puffs you take every day.",
        "Live data unavailable (historical replay). Use your salbutamol inhaler twice daily.",
        "Live data unavailable (historical replay). Start taking cetirizine tablets daily.",
        "Live data unavailable (historical replay). दिन में दो बार इनहेलर की खुराक बढ़ाएँ।",
        "Live data unavailable (historical replay). आपको अस्थमा है।",
        "Live data unavailable (historical replay). तुम्हाला दमा आहे.",
        "Live data unavailable (historical replay). Inhaler dosage double kijiye.",
        "Live data unavailable (historical replay). No rain forecast and air is completely safe.",
        "Live data unavailable (historical replay). "
        "No rain is forecast and air is completely safe.",
        "Live data unavailable (historical replay). No traffic makes 2 PM a safe window.",
        "Live data unavailable (historical replay). Buy a snake plant and avoid dry sweeping.",
    )
    for text in bad_claims:
        ok, reasons = validate_narrative(text, bundle)
        assert ok is False, f"Expected validator rejection for: {text!r}"
        assert reasons

    valid_negations = (
        "Live data unavailable (historical replay). Outdoor air is not completely safe today.",
        "Live data unavailable (historical replay). Houseplants do not remove PM2.5 indoors.",
        "Live data unavailable (historical replay). दोपहर बाहर जाना पूरी तरह सुरक्षित नहीं है।",
        "Live data unavailable (historical replay). कमरे में मनी प्लांट न रखें।",
    )
    for ok_text in valid_negations:
        assert validate_narrative(ok_text, bundle)[0] is True

    expired = bundle.model_copy(update={"issued_at": int(time.time()) - (7 * 3600)})
    expired_sig = sign_evidence_bundle(expired)
    assert verify_evidence_bundle(expired, expired_sig) is False


def test_prefix_patterns_linear_time_no_redos() -> None:
    """Verify PREFIX_AQI_PATTERN and PREFIX_PM25_PATTERN reject ReDoS traps in < 50 ms."""
    from safety import PREFIX_AQI_PATTERN, PREFIX_PM25_PATTERN

    delhi_preset = next(p for p in PRESETS if p["id"] == "delhi_family")
    req = PlanRequest(**delhi_preset, simulate_stale=True)
    bundle = build_evidence_bundle(req, build_replay_payload("delhi", "test"), current_hour=8)

    aqi_trap = "AQI " + "level " * 30 + "high"
    pm25_trap = "PM2.5 " + "level " * 30 + "high"
    t0 = time.perf_counter()
    assert PREFIX_AQI_PATTERN.search(aqi_trap) is None
    assert PREFIX_PM25_PATTERN.search(pm25_trap) is None
    ok, _ = validate_narrative(f"Live data unavailable (historical replay). {aqi_trap}.", bundle)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert ok is True
    assert elapsed_ms < 50.0, f"Regex evaluation took {elapsed_ms:.2f} ms (expected < 50 ms)"
