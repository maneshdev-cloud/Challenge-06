"""Tests for Gemini explainer grounding, Vision JSON filtering, and failover chain."""

from __future__ import annotations

import asyncio

import explainer
from data_fetcher import PRESETS, build_replay_payload
from engine import build_evidence_bundle
from schemas import PlanRequest


def _sample_bundle(simulate_stale: bool = False):
    """Build a reusable EvidenceBundle fixture for explainer tests."""
    delhi_preset = next(p for p in PRESETS if p["id"] == "delhi_family")
    req = PlanRequest(**delhi_preset, simulate_stale=simulate_stale)
    raw = build_replay_payload("delhi", "test")
    if not simulate_stale:
        raw["provenance"]["is_stale"] = False
        raw["provenance"]["is_fallback_replay"] = False
        raw["provenance"]["data_type"] = "model_forecast"
        raw["provenance"]["source"] = "Open-Meteo (CAMS Global ~40 km + Weather Forecast)"
    return build_evidence_bundle(req, raw, current_hour=8)


def test_gemini_models_are_valid_ai_studio_ids() -> None:
    """Verify GEMINI_MODELS lists live 2026 Google AI Studio model identifiers."""
    assert explainer.GEMINI_MODELS == (
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
    )


def test_gemini_valid_response_accepted(monkeypatch) -> None:
    """Verify valid grounded Gemini output is returned with source='gemini'."""
    bundle = _sample_bundle(simulate_stale=True)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")

    def fake_gemini(prompt: str, model_name: str, api_key: str) -> str:
        return (
            f"Note: Live data is unavailable (historical replay). "
            f"In Delhi, PM2.5 is {bundle.air_snapshot.current_pm25} ug/m3 and Estimated NAQI is "
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
    _, is_er, _, source, ok = asyncio.run(
        explainer.generate_chat_reply("Can dad walk at 7 AM?", bundle, "en")
    )
    assert is_er is False
    assert source == "gemini"
    assert ok is True
    assert called["count"] == 1

    er_reply, er_flag, _, er_source, _ = asyncio.run(
        explainer.generate_chat_reply("He is wheezing and breathless", bundle, "en")
    )
    assert er_flag is True
    assert er_source == "emergency_triage"
    assert "108" in er_reply
    assert called["count"] == 1


def test_all_eight_languages_deterministic_and_validated() -> None:
    """Verify all 8 languages generate scannable Do/Avoid plans passing validation."""
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


def test_gemini_error_falls_back_gracefully_in_chat(monkeypatch) -> None:
    """Verify Ask AI falls back cleanly to grounded deterministic answers if Gemini errors."""
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

    greet_reply, _, _, greet_source, greet_ok = asyncio.run(
        explainer.generate_chat_reply("HII", bundle, "en")
    )
    assert greet_source == "deterministic_template"
    assert greet_ok is True
    assert "Hi!" in greet_reply


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

    def failover_gemini(prompt: str, model_name: str, api_key: str) -> str:
        calls.append((api_key, model_name))
        if api_key == "key_primary":
            raise MockApiError(429, "429 RESOURCE_EXHAUSTED")
        if model_name == "gemini-3.5-flash-lite":
            raise MockApiError(404, "404 NOT_FOUND")
        return (
            f"Today's Air:\nIn Delhi, PM2.5 is {bundle.air_snapshot.current_pm25} ug/m3 and "
            f"NAQI is {bundle.air_snapshot.current_naqi}.\n\n"
            f"Do This:\n- Shift walks to {bundle.air_snapshot.golden_window.window_label}."
        )

    monkeypatch.setattr(explainer, "_call_gemini_sync", failover_gemini)
    _, source, ok = asyncio.run(explainer.generate_plan_narrative(bundle, skip_llm=False))
    assert source == "gemini"
    assert ok is True
    assert ("key_primary", "gemini-3.5-flash-lite") in calls
    assert ("key_primary", "gemini-3.8-flash") not in calls
    assert ("key_backup", "gemini-3.8-flash") in calls

    calls.clear()
    _, source_cached, _ = asyncio.run(explainer.generate_plan_narrative(bundle, skip_llm=False))
    assert source_cached == "gemini"
    assert calls == [("key_backup", "gemini-3.8-flash")]

    explainer.reset_failover_cache()

    def outage_gemini(prompt: str, model_name: str, api_key: str) -> str:
        if api_key == "key_primary":
            raise MockApiError(503, "503 UNAVAILABLE")
        raise MockApiError(504, "504 GATEWAY_TIMEOUT")

    monkeypatch.setattr(explainer, "_call_gemini_sync", outage_gemini)
    plan_txt, plan_src, plan_ok = asyncio.run(
        explainer.generate_plan_narrative(bundle, skip_llm=False)
    )
    assert plan_src == "deterministic_template"
    assert plan_ok is True
    assert "Do This:" in plan_txt


def test_parse_room_audit_markdown_fences_and_houseplant_filter() -> None:
    """Verify markdown JSON fences strip cleanly and houseplant tips get replaced."""
    raw = """```json
    {
      "room_summary": "Window track shows minor dust leaks.",
      "tips": [
        {
          "title": "Keep Snake Plant",
          "cost_inr": "Rs. 200",
          "action": "Buy snake plant.",
          "why_it_helps": "Absorbs toxins."
        },
        {
          "title": "Seal Window Gap",
          "cost_inr": "Rs. 120",
          "action": "Apply foam strip.",
          "why_it_helps": "Blocks road dust."
        }
      ]
    }
    ```"""
    parsed = explainer._parse_room_audit_json(raw, "gemini-2.5-flash", "Delhi", "en", None)
    assert parsed is not None
    assert parsed.source == "gemini"
    assert len(parsed.tips) == 3


def test_room_audit_deterministic_tips_localized_and_cost_capped() -> None:
    """Verify deterministic room audit localizes tips in all 8 langs and caps parsed cost."""
    en_audit = explainer.build_deterministic_room_audit("Delhi", "en")
    en_titles = [t.title for t in en_audit.tips]
    for lang in ("hinglish", "hi", "mr", "kn", "bn", "ta", "te"):
        loc_audit = explainer.build_deterministic_room_audit("Delhi", lang, current_naqi=180)
        assert len(loc_audit.tips) == 3
        assert [t.title for t in loc_audit.tips] != en_titles

    over_budget_json = """{
      "room_summary": "Bedroom needs window seal.",
      "tips": [
        {
          "title": "Buy HEPA Purifier",
          "cost_inr": "Rs. 15,000",
          "action": "Purchase flagship purifier.",
          "why_it_helps": "Filters particles."
        },
        {
          "title": "Seal Window Gap",
          "cost_inr": "Rs. 120",
          "action": "Apply EPDM foam tape.",
          "why_it_helps": "Blocks traffic dust."
        }
      ]
    }"""
    parsed = explainer._parse_room_audit_json(
        over_budget_json, "gemini-2.5-flash", "Delhi", "en", None
    )
    assert parsed is not None
    assert all(t.title != "Buy HEPA Purifier" for t in parsed.tips)
    assert any(t.title == "Seal Window Gap" for t in parsed.tips)
    assert len(parsed.tips) == 3
    assert all("snake plant" not in t.title.lower() for t in parsed.tips)


def test_error_classification_blank_skip_room_bounds_and_chat_routing(monkeypatch) -> None:
    """Verify status-code failover, blank skip, range caps, houseplant summary, and routing."""
    from gemini_client import classify_gemini_error

    class _CodeErr(Exception):
        def __init__(self, code: int, msg: str):
            super().__init__(msg)
            self.code = code

    assert classify_gemini_error(_CodeErr(400, "quota message inside 400 error")) == "key_invalid"
    assert classify_gemini_error(_CodeErr(401, "404 string noise")) == "key_invalid"
    assert classify_gemini_error(_CodeErr(502, "bad gateway")) == "503_unavailable"
    assert classify_gemini_error(TimeoutError("network")) == "504_timeout"

    # Empty LLM response on a stale bundle must fall back cleanly instead of bare disclosure note
    stale_bundle = _sample_bundle(simulate_stale=True)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-empty-key")
    monkeypatch.setattr(explainer, "_call_gemini_sync", lambda *_: "   ")
    txt, src, ok = asyncio.run(explainer.generate_plan_narrative(stale_bundle, skip_llm=False))
    assert src == "deterministic_template"
    assert ok is True
    assert "Do This:" in txt or "यह करें:" in txt

    # Rs. 100 to Rs. 2000 range and spider plant summary must be filtered/rejected cleanly
    range_and_summary = (
        '{"room_summary": "Add a spider plant near the bed.", "tips": ['
        '{"title": "Purifier", "cost_inr": "Rs. 100 to Rs. 2000", '
        '"action": "x", "why_it_helps": "y"}]}'
    )
    assert explainer._parse_room_audit_json(range_and_summary, "m", "Delhi", "en", None) is None

    bad_range = (
        '{"room_summary": "Leaky road-facing sill.", "tips": ['
        '{"title": "Expensive range", "cost_inr": "Rs. 100 to Rs. 2000", '
        '"action": "Buy unit.", "why_it_helps": "Costly."}, '
        '{"title": "Seal Gap", "cost_inr": "Rs. 120", '
        '"action": "Add EPDM tape.", "why_it_helps": "Cuts infiltration."}]}'
    )
    parsed = explainer._parse_room_audit_json(bad_range, "m", "Delhi", "en", None)
    assert parsed is not None
    assert all(t.title != "Expensive range" for t in parsed.tips)

    # Chat word boundaries, greeting ordering ("hi mask"), and partial fallback disclosure
    mask_reply = explainer.build_deterministic_chat_reply("hi mask", stale_bundle, "en")
    assert "N95" in mask_reply
    bathroom_reply = explainer.build_deterministic_chat_reply("bathroom odor", stale_bundle, "en")
    assert "window" not in bathroom_reply.lower() or "Today's Air:" in bathroom_reply
    partial_bundle = _sample_bundle(simulate_stale=False).model_copy(
        update={
            "provenance": _sample_bundle(simulate_stale=False).provenance.model_copy(
                update={"is_partial_fallback": True}
            )
        }
    )
    partial_chat = explainer.build_deterministic_chat_reply("Can dad walk?", partial_bundle, "en")
    assert "partial" in partial_chat.lower() or "fallback" in partial_chat.lower()
