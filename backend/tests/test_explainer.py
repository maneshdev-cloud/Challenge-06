"""Tests for Gemini explainer grounding, numeric fallback, and chat triage."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import explainer
from data_fetcher import PRESETS, _build_replay_payload
from engine import build_evidence_bundle
from schemas import PlanRequest


def _sample_bundle(simulate_stale: bool = False):
    delhi_preset = next(p for p in PRESETS if p["id"] == "delhi_family")
    req = PlanRequest(**delhi_preset, simulate_stale=simulate_stale)
    raw = _build_replay_payload("delhi", "test")
    if not simulate_stale:
        raw["provenance"]["is_stale"] = False
        raw["provenance"]["is_fallback_replay"] = False
        raw["provenance"]["data_type"] = "model_forecast"
        raw["provenance"]["source"] = "Open-Meteo (ECMWF CAMS + ERA5)"
    return build_evidence_bundle(req, raw, current_hour=8)


def test_gemini_valid_response_accepted(monkeypatch) -> None:
    """Verify valid grounded Gemini output is returned with source='gemini'."""
    bundle = _sample_bundle(simulate_stale=True)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")

    def fake_gemini(prompt: str, model_name: str, api_key: str) -> str:
        return (
            f"Note: Live data is unavailable (historical replay). "
            f"In Delhi, PM2.5 is {bundle.air_snapshot.current_pm25} ug/m3 and India NAQI is "
            f"{bundle.air_snapshot.current_naqi}. Your lower-exposure window is "
            f"{bundle.air_snapshot.golden_window.window_label}, saving "
            f"{bundle.breathe_less.dose_avoided_ug} ug and {bundle.emit_less.co2_saved_g} g CO2e."
        )

    monkeypatch.setattr(explainer, "_call_gemini_sync", fake_gemini)
    text, source, ok = asyncio.run(explainer.generate_plan_narrative(bundle, skip_llm=False))
    assert source == "gemini"
    assert ok is True
    assert "historical replay" in text.lower()


def test_gemini_hallucination_falls_back_to_template(monkeypatch) -> None:
    """Verify ungrounded Gemini numbers trigger deterministic template fallback."""
    bundle = _sample_bundle(simulate_stale=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")

    def hallucinating_gemini(prompt: str, model_name: str, api_key: str) -> str:
        return "Today PM2.5 is 999 ug/m3 and you save 8,888 g CO2e with a spider plant!"

    monkeypatch.setattr(explainer, "_call_gemini_sync", hallucinating_gemini)
    text, source, ok = asyncio.run(explainer.generate_plan_narrative(bundle, skip_llm=False))
    assert source == "deterministic_template"
    assert ok is True
    assert "999" not in text
    assert str(bundle.air_snapshot.current_pm25) in text


def test_gemini_chat_fallback_and_triage(monkeypatch) -> None:
    """Verify chat uses Gemini when grounded and intercepts emergencies before calling Gemini."""
    bundle = _sample_bundle(simulate_stale=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")

    called = {"count": 0}

    def fake_chat_gemini(prompt: str, model_name: str, api_key: str) -> str:
        called["count"] += 1
        return (
            f"Move the walk to {bundle.air_snapshot.golden_window.window_label} "
            f"({bundle.air_snapshot.golden_window.mean_pm25} ug/m3) instead of morning."
        )

    monkeypatch.setattr(explainer, "_call_gemini_sync", fake_chat_gemini)
    reply, is_er, _, source, ok = asyncio.run(
        explainer.generate_chat_reply("Can dad walk at 7 AM?", bundle, "en")
    )
    assert is_er is False
    assert source == "gemini"
    assert ok is True
    assert called["count"] == 1

    # Emergency must short-circuit BEFORE calling Gemini
    er_reply, er_flag, _, er_source, _ = asyncio.run(
        explainer.generate_chat_reply("He is wheezing and breathless", bundle, "en")
    )
    assert er_flag is True
    assert er_source == "emergency_triage"
    assert "108" in er_reply
    assert called["count"] == 1


def test_all_eight_languages_deterministic_and_validated() -> None:
    """Verify all 8 supported languages generate scannable Do/Avoid narratives passing validation."""
    for lang in ("en", "hinglish", "hi", "mr", "kn", "bn", "ta", "te"):
        bundle = _sample_bundle(simulate_stale=True).model_copy(update={"language": lang})
        text, source, ok = asyncio.run(explainer.generate_plan_narrative(bundle, skip_llm=True))
        assert source == "deterministic_template"
        assert ok is True, f"Validator failed for language={lang}: {text}"
        if lang == "en":
            assert "Today's Air:" in text
            assert "Do This:" in text
            assert "Avoid This:" in text
            assert "EvidenceBundle" not in text
            assert "mixing lid" not in text


def test_gemini_error_falls_back_gracefully_in_chat(monkeypatch) -> None:
    """Verify Ask AI falls back cleanly to grounded deterministic answers if Gemini errors/times out."""
    bundle = _sample_bundle(simulate_stale=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")

    def failing_gemini(prompt: str, model_name: str, api_key: str) -> str:
        raise TimeoutError("Simulated Gemini timeout")

    monkeypatch.setattr(explainer, "_call_gemini_sync", failing_gemini)
    reply, is_er, _, source, ok = asyncio.run(
        explainer.generate_chat_reply("What N95 mask should we wear?", bundle, "en")
    )
    assert is_er is False
    assert source == "deterministic_template"
    assert ok is True
    assert "N95" in reply
    assert "What to Do:" in reply
    assert "What to Avoid:" in reply

    # Casual greeting must return a warm short greeting instead of a full report wall of text
    greet_reply, _, _, greet_source, greet_ok = asyncio.run(
        explainer.generate_chat_reply("HII", bundle, "en")
    )
    assert greet_source == "deterministic_template"
    assert greet_ok is True
    assert "Hi!" in greet_reply
    assert "Clean Air Sanctuary" not in greet_reply


def test_gemini_404_429_503_504_failover_and_key_rotation(monkeypatch) -> None:
    """Verify 404 model fallback, 429 key rotation, and 503/504 seamless template fallback."""
    explainer.reset_failover_cache()
    bundle = _sample_bundle(simulate_stale=False)
    monkeypatch.setenv("GEMINI_API_KEYS", "key_primary,key_backup")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_BACKUP", raising=False)

    class MockApiError(Exception):
        def __init__(self, code: int, msg: str):
            super().__init__(msg)
            self.code = code

    calls: list[tuple[str, str]] = []

    # Case 1: key_primary hits 429 quota -> immediately rotates to key_backup,
    # key_backup gets 404 on gemini-2.5-flash -> falls back to gemini-2.0-flash and succeeds!
    def failover_gemini(prompt: str, model_name: str, api_key: str) -> str:
        calls.append((api_key, model_name))
        if api_key == "key_primary":
            raise MockApiError(429, "429 RESOURCE_EXHAUSTED quota exceeded")
        if model_name == "gemini-2.5-flash":
            raise MockApiError(404, "404 NOT_FOUND")
        return (
            f"Today's Air:\nIn Delhi, PM2.5 is {bundle.air_snapshot.current_pm25} ug/m3 and "
            f"India NAQI is {bundle.air_snapshot.current_naqi}.\n\n"
            f"Do This:\n- Shift walks to {bundle.air_snapshot.golden_window.window_label}."
        )

    monkeypatch.setattr(explainer, "_call_gemini_sync", failover_gemini)
    text, source, ok = asyncio.run(explainer.generate_plan_narrative(bundle, skip_llm=False))
    assert source == "gemini"
    assert ok is True
    assert ("key_primary", "gemini-2.5-flash") in calls
    # Key 1 should have broken out immediately on 429 without wasting calls on key_primary's remaining models
    assert ("key_primary", "gemini-2.0-flash") not in calls
    assert ("key_backup", "gemini-2.5-flash") in calls
    assert ("key_backup", "gemini-2.0-flash") in calls

    # Fast cache check: immediate repeat request must skip key_primary (429 cooldown) and dead 404 model in 0ms!
    calls.clear()
    text_cached, source_cached, _ = asyncio.run(explainer.generate_plan_narrative(bundle, skip_llm=False))
    assert source_cached == "gemini"
    assert calls == [("key_backup", "gemini-2.0-flash")]

    # Case 2: All keys/models hit 503 Unavailable & 504 Gateway Timeout -> seamless deterministic fallback
    explainer.reset_failover_cache()
    def outage_gemini(prompt: str, model_name: str, api_key: str) -> str:
        if api_key == "key_primary":
            raise MockApiError(503, "503 UNAVAILABLE")
        raise MockApiError(504, "504 GATEWAY_TIMEOUT")

    monkeypatch.setattr(explainer, "_call_gemini_sync", outage_gemini)
    plan_txt, plan_src, plan_ok = asyncio.run(explainer.generate_plan_narrative(bundle, skip_llm=False))
    assert plan_src == "deterministic_template"
    assert plan_ok is True
    assert "Do This:" in plan_txt

    chat_txt, _, _, chat_src, chat_ok = asyncio.run(
        explainer.generate_chat_reply("Can we open windows?", bundle, "en")
    )
    assert chat_src == "deterministic_template"
    assert chat_ok is True
    assert "What to Do:" in chat_txt
