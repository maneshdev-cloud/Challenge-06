"""End-to-end FastAPI TestClient tests for PRANA-AI REST endpoints and security headers."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

import explainer
import main as main_mod
from main import app

client = TestClient(app)


def test_health_presets_and_api_prefix_stripping() -> None:
    """Verify /health (GET/HEAD), /api/* prefix stripping, security headers, and presets."""
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["app"] == "PRANA-AI"
    assert h.headers.get("x-content-type-options") == "nosniff"
    assert h.headers.get("x-frame-options") == "DENY"

    h_api = client.get("/api/health")
    assert h_api.status_code == 200
    assert h_api.json() == h.json()

    h_head = client.head("/health")
    assert h_head.status_code == 200

    presets_resp = client.get("/api/v1/presets")
    assert presets_resp.status_code == 200
    presets = presets_resp.json()
    assert len(presets) == 4
    assert {p["id"] for p in presets} == {
        "delhi_family",
        "mumbai_student",
        "pune_elderly",
        "delivery_rider",
    }
    assert all(p["language"] == "en" for p in presets)

    cities_resp = client.get("/v1/cities")
    assert cities_resp.status_code == 200
    cities = cities_resp.json()
    assert list(cities.keys())[:4] == ["mumbai", "pune", "delhi", "bengaluru"]
    assert cities["bengaluru"]["name"] == "Bangalore"


def test_air_endpoint_stale_replay_and_invalid_city() -> None:
    """Verify /v1/air returns 24h data, replay metadata, and 400 on unknown places."""
    resp = client.get(
        "/v1/air",
        params={
            "city": "delhi",
            "lat": 28.6469,
            "lon": 77.3164,
            "area_name": "Anand Vihar",
            "simulate_stale": "true",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["city"] == "delhi"
    assert data["area_name"] == "Anand Vihar"
    assert data["lat"] == 28.6469
    assert len(data["hourly"]) == 24
    assert len(data["daily_outlook"]) == 5
    assert data["provenance"]["is_fallback_replay"] is True

    bad_city = client.get("/v1/air", params={"city": "AtlantisNonexistent9999"})
    assert bad_city.status_code == 400


def test_plan_all_presets_what_if_and_edge_validation() -> None:
    """Verify POST /v1/plan succeeds on presets, handles empty activities, and rejects bad enums."""
    presets = client.get("/v1/presets").json()
    for p in presets:
        resp = client.post("/v1/plan", json={**p, "simulate_stale": True, "skip_llm": True})
        assert resp.status_code == 200, f"Failed for preset {p['id']}: {resp.text}"
        body = resp.json()
        assert body["evidence_bundle"]["app_name"] == "PRANA-AI"
        assert body["validator_passed"] is True
        assert body["evidence_bundle"]["provenance"]["is_fallback_replay"] is True

    # What-If walk_override_hour recalculation
    delhi = next(p for p in presets if p["id"] == "delhi_family")
    opt_plan = client.post(
        "/v1/plan", json={**delhi, "simulate_stale": True, "skip_llm": True}
    ).json()
    peak_plan = client.post(
        "/v1/plan",
        json={**delhi, "walk_override_hour": 7, "simulate_stale": True, "skip_llm": True},
    ).json()
    assert peak_plan["narrative_source"] == "deterministic_template"
    assert (
        peak_plan["evidence_bundle"]["breathe_less"]["dose_avoided_ug"]
        < opt_plan["evidence_bundle"]["breathe_less"]["dose_avoided_ug"]
    )

    # Empty activities list returns 200 cleanly
    empty_resp = client.post(
        "/v1/plan",
        json={"city": "delhi", "simulate_stale": True, "skip_llm": True, "activities": []},
    )
    assert empty_resp.status_code == 200

    # Invalid commute_mode must return 422 validation error (never 500 KeyError)
    bad_enum = client.post(
        "/v1/plan",
        json={
            "city": "delhi",
            "commute_mode": "spaceship",
            "simulate_stale": True,
            "skip_llm": True,
        },
    )
    assert bad_enum.status_code == 422


def test_chat_normal_emergency_and_oversized_rejected() -> None:
    """Verify POST /v1/chat answers grounded queries, triggers ER alert, and enforces length."""
    delhi_preset = next(p for p in client.get("/v1/presets").json() if p["id"] == "delhi_family")
    plan_res = client.post(
        "/v1/plan", json={**delhi_preset, "simulate_stale": True, "skip_llm": True}
    ).json()
    bundle = plan_res["evidence_bundle"]
    sig = plan_res["evidence_signature"]

    chat_ok = client.post(
        "/v1/chat",
        json={
            "message": "When should my dad walk?",
            "evidence_bundle": bundle,
            "evidence_signature": sig,
            "language": "en",
        },
    )
    assert chat_ok.status_code == 200
    assert chat_ok.json()["emergency_alert"] is False
    assert chat_ok.json()["validator_passed"] is True

    chat_er = client.post(
        "/v1/chat",
        json={
            "message": "My son is wheezing badly",
            "evidence_bundle": bundle,
            "evidence_signature": sig,
            "language": "en",
        },
    )
    assert chat_er.status_code == 200
    assert chat_er.json()["emergency_alert"] is True
    assert chat_er.json()["source"] == "emergency_triage"
    assert "108" in chat_er.json()["reply"]

    too_long = client.post(
        "/v1/chat",
        json={
            "message": "a" * 1501,
            "evidence_bundle": bundle,
            "evidence_signature": sig,
            "language": "en",
        },
    )
    assert too_long.status_code == 422


def test_pan_india_geocode_and_arbitrary_coords(monkeypatch) -> None:
    """Verify /v1/geocode and generalized Pan-India /v1/air & /v1/plan for arbitrary coords."""

    async def fake_geocode(_q: str, count: int = 5):
        return [
            {
                "name": "Chennai",
                "state": "Tamil Nadu",
                "district": "Chennai",
                "lat": 13.0827,
                "lon": 80.2707,
                "suggested_language": "ta",
                "is_coastal": True,
            }
        ]

    monkeypatch.setattr(main_mod, "geocode_india", fake_geocode)
    geo_resp = client.get("/v1/geocode", params={"q": "Chennai"})
    assert geo_resp.status_code == 200
    assert geo_resp.json()[0]["suggested_language"] == "ta"

    air_resp = client.get(
        "/v1/air",
        params={
            "city": "Jaipur",
            "state": "Rajasthan",
            "lat": 26.9196,
            "lon": 75.7878,
            "simulate_stale": "true",
        },
    )
    assert air_resp.status_code == 200
    assert air_resp.json()["city_name"] == "Jaipur"
    assert air_resp.json()["suggested_language"] == "hi"


def test_reverse_geocode_endpoint_and_fallback(monkeypatch) -> None:
    """Verify /v1/reverse-geocode returns readable Area, City."""

    async def fake_reverse(lat: float, lon: float):
        return {
            "area_name": "Andheri",
            "city": "Mumbai",
            "state": "Maharashtra",
            "lat": lat,
            "lon": lon,
            "suggested_language": "mr",
            "is_coastal": True,
        }

    monkeypatch.setattr(main_mod, "reverse_geocode_india", fake_reverse)
    resp = client.get("/v1/reverse-geocode", params={"lat": 19.1136, "lon": 72.8697})
    assert resp.status_code == 200
    assert resp.json()["area_name"] == "Andheri"
    assert resp.json()["city"] == "Mumbai"


def test_audit_room_endpoint_validation_and_fallback(monkeypatch) -> None:
    """Verify /v1/audit-room handles PNGs, fallback, >5MB (413), and invalid formats (415)."""
    explainer.reset_failover_cache()
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(180, 210, 220)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    def fake_vision(
        _prompt: str, _image_bytes: bytes, mime_type: str, _model: str, _key: str
    ) -> str:
        assert mime_type == "image/png"
        return (
            '{"room_summary": "Sliding balcony door has small frame gaps.", '
            '"tips": ['
            '{"title": "Foam Seal Track", "cost_inr": "Rs. 140", '
            '"action": "Stick EPDM foam strip.", "why_it_helps": "Blocks leaks."}, '
            '{"title": "Shut Kitchen Door", "cost_inr": "Rs. 0", '
            '"action": "Close kitchen partition.", "why_it_helps": "Stops spikes."}, '
            '{"title": "Wet Wipe Sill", "cost_inr": "Rs. 30", '
            '"action": "Damp cloth daily.", "why_it_helps": "Reduces dust."}'
            "]}"
        )

    monkeypatch.setenv("GEMINI_API_KEY", "fake-vision-key")
    monkeypatch.setattr(explainer, "_call_gemini_vision_sync", fake_vision)
    ok_resp = client.post(
        "/v1/audit-room",
        data={"city": "Mumbai", "language": "en", "current_naqi": "85"},
        files={"file": ("room.png", png_bytes, "image/png")},
    )
    assert ok_resp.status_code == 200
    assert ok_resp.json()["source"] == "gemini"
    assert len(ok_resp.json()["tips"]) == 3

    def failing_vision(*_args, **_kwargs):
        raise TimeoutError("Vision timed out")

    monkeypatch.setattr(explainer, "_call_gemini_vision_sync", failing_vision)
    fb_resp = client.post(
        "/v1/audit-room",
        data={"city": "Delhi", "language": "en"},
        files={"file": ("room.png", png_bytes, "image/png")},
    )
    assert fb_resp.status_code == 200
    assert fb_resp.json()["source"] == "deterministic_template"

    bad_type = client.post(
        "/v1/audit-room",
        data={"city": "Delhi", "language": "en"},
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )
    assert bad_type.status_code == 415

    too_big = client.post(
        "/v1/audit-room",
        data={"city": "Delhi", "language": "en"},
        files={"file": ("huge.jpg", b"A" * (5 * 1024 * 1024 + 128), "image/jpeg")},
    )
    assert too_big.status_code == 413


def test_chat_trip_planning_and_simulated_crash_returns_200(monkeypatch) -> None:
    """Verify trip query and simulated uncaught errors always return HTTP 200 cleanly."""
    delhi_preset = next(p for p in client.get("/v1/presets").json() if p["id"] == "delhi_family")
    plan_res = client.post(
        "/v1/plan", json={**delhi_preset, "simulate_stale": True, "skip_llm": True}
    ).json()
    bundle = plan_res["evidence_bundle"]
    sig = plan_res["evidence_signature"]

    monkeypatch.setattr(explainer, "_get_api_keys", lambda: [])
    trip_resp = client.post(
        "/v1/chat",
        json={
            "message": "i want to plan a trip",
            "evidence_bundle": bundle,
            "evidence_signature": sig,
            "language": "en",
        },
    )
    assert trip_resp.status_code == 200
    assert "trip" in trip_resp.json()["reply"].lower()
    assert "What to Do:" in trip_resp.json()["reply"]

    async def crashing_chat(*_args, **_kwargs):
        raise RuntimeError("Simulated uncaught Gemini SDK crash")

    monkeypatch.setattr(main_mod, "generate_chat_reply", crashing_chat)
    crash_resp = client.post(
        "/v1/chat",
        json={
            "message": "i want to plan a trip",
            "evidence_bundle": bundle,
            "evidence_signature": sig,
            "language": "en",
        },
    )
    assert crash_resp.status_code == 200
    assert crash_resp.json()["source"] == "deterministic_template"

    def crashing_deterministic(*_args, **_kwargs):
        raise KeyError("missing_field")

    monkeypatch.setattr(main_mod, "build_deterministic_chat_reply", crashing_deterministic)
    safe_resp = client.post(
        "/v1/chat",
        json={
            "message": "i want to plan a trip",
            "evidence_bundle": bundle,
            "evidence_signature": sig,
            "language": "en",
        },
    )
    assert safe_resp.status_code == 200
    assert "PM2.5" in safe_resp.json()["reply"]


def test_four_user_categories_update_risk_and_dose_on_same_city() -> None:
    """Verify switching across all 4 User Categories updates risk warnings, dose, and tasks."""
    categories = [
        {
            "user_category": "students_kids",
            "budget_tier": "rs_0",
            "commute_mode": "auto_cng",
            "target_commute_mode": "electric_metro",
            "commute_km": 12.0,
            "members": [{"name": "School Child", "age": 9, "conditions": ["child"]}],
            "activities": [
                {
                    "id": "sports_play",
                    "name": "Outdoor Sports",
                    "flexibility": "flexible",
                    "planned_hour": 17,
                    "duration_min": 45,
                    "activity_level": "child_play",
                    "member_name": "School Child",
                    "current_mask": "none",
                }
            ],
        },
        {
            "user_category": "adults_commuters",
            "budget_tier": "under_2200",
            "commute_mode": "car_petrol_solo",
            "target_commute_mode": "electric_metro",
            "commute_km": 16.0,
            "members": [{"name": "Commuter", "age": 34, "conditions": ["adult"]}],
            "activities": [
                {
                    "id": "brisk_walk",
                    "name": "Daily Brisk Walk",
                    "flexibility": "flexible",
                    "planned_hour": 7,
                    "duration_min": 40,
                    "activity_level": "brisk_walk",
                    "member_name": "Commuter",
                    "current_mask": "none",
                }
            ],
        },
        {
            "user_category": "seniors",
            "budget_tier": "under_500",
            "commute_mode": "auto_cng",
            "target_commute_mode": "city_bus",
            "commute_km": 6.0,
            "members": [{"name": "Senior Member", "age": 70, "conditions": ["elderly", "copd"]}],
            "activities": [
                {
                    "id": "senior_walk",
                    "name": "Morning Park Walk",
                    "flexibility": "flexible",
                    "planned_hour": 6,
                    "duration_min": 45,
                    "activity_level": "elderly_walk",
                    "member_name": "Senior Member",
                    "current_mask": "cloth",
                }
            ],
        },
        {
            "user_category": "delivery_riders",
            "budget_tier": "under_500",
            "commute_mode": "two_wheeler_petrol",
            "target_commute_mode": "two_wheeler_petrol",
            "commute_km": 40.0,
            "members": [{"name": "Delivery Rider", "age": 29, "conditions": ["outdoor_worker"]}],
            "activities": [
                {
                    "id": "shift_morning",
                    "name": "Delivery Shift (8h)",
                    "flexibility": "fixed",
                    "planned_hour": 8,
                    "duration_min": 480,
                    "activity_level": "running_or_outdoor_work",
                    "member_name": "Delivery Rider",
                    "current_mask": "cloth",
                    "is_commute": True,
                    "is_work_shift": True,
                }
            ],
        },
    ]

    results = {}
    for cfg in categories:
        resp = client.post(
            "/v1/plan",
            json={**cfg, "city": "pune", "simulate_stale": True, "skip_llm": True},
        )
        assert resp.status_code == 200
        results[cfg["user_category"]] = resp.json()["evidence_bundle"]

    naqis = {b["air_snapshot"]["current_naqi"] for b in results.values()}
    pm25s = {b["air_snapshot"]["current_pm25"] for b in results.values()}
    assert len(naqis) == 1
    assert len(pm25s) == 1

    assert results["students_kids"]["profile_summary"]["warning_threshold_naqi"] == 100
    assert results["seniors"]["profile_summary"]["warning_threshold_naqi"] == 100
    assert results["delivery_riders"]["profile_summary"]["warning_threshold_naqi"] == 100
    assert results["adults_commuters"]["profile_summary"]["warning_threshold_naqi"] == 150

    assert len({b["breathe_less"]["baseline_dose_ug"] for b in results.values()}) == 4
    assert len({b["emit_less"]["co2_saved_g"] for b in results.values()}) == 4
    assert len({b["profile_summary"]["warning_banner"] for b in results.values()}) == 4


def test_chat_rejects_tampered_evidence_bundle() -> None:
    """Verify POST /v1/chat rejects missing, bogus, or tampered HMAC evidence bundles (403)."""
    import copy

    delhi_preset = next(p for p in client.get("/v1/presets").json() if p["id"] == "delhi_family")
    plan_res = client.post(
        "/v1/plan", json={**delhi_preset, "simulate_stale": True, "skip_llm": True}
    ).json()
    bundle = plan_res["evidence_bundle"]
    sig = plan_res["evidence_signature"]
    assert sig and len(sig) == 64

    missing = client.post(
        "/v1/chat",
        json={"message": "Can dad walk?", "evidence_bundle": bundle, "language": "en"},
    )
    assert missing.status_code == 403

    bad_sig = client.post(
        "/v1/chat",
        json={
            "message": "Can dad walk?",
            "evidence_bundle": bundle,
            "evidence_signature": "0" * 64,
            "language": "en",
        },
    )
    assert bad_sig.status_code == 403

    mutations = [
        lambda b: b["air_snapshot"].__setitem__("current_pm25", 999.0),
        lambda b: b["air_snapshot"].__setitem__("current_naqi", 499),
        lambda b: b["breathe_less"].__setitem__("dose_avoided_ug", 1234.5),
        lambda b: b["emit_less"].__setitem__("co2_saved_g", 99999.0),
        lambda b: b["grounded_metrics"]["pm25"].append(777.7),
        lambda b: b["grounded_numbers"].append(888.8),
    ]
    for mutate in mutations:
        tampered = copy.deepcopy(bundle)
        mutate(tampered)
        resp = client.post(
            "/v1/chat",
            json={
                "message": "Can dad walk?",
                "evidence_bundle": tampered,
                "evidence_signature": sig,
                "language": "en",
            },
        )
        assert resp.status_code == 403


def test_emergency_triage_bypasses_rate_limit() -> None:
    """Verify acute distress ER interception succeeds even when caller IP is rate-limited."""
    import time
    from collections import deque

    delhi_preset = next(p for p in client.get("/v1/presets").json() if p["id"] == "delhi_family")
    plan_res = client.post(
        "/v1/plan", json={**delhi_preset, "simulate_stale": True, "skip_llm": True}
    ).json()
    bundle = plan_res["evidence_bundle"]
    sig = plan_res["evidence_signature"]
    test_ip = "203.0.113.99"

    main_mod._RATE_BUCKETS.clear()
    main_mod._RATE_BUCKETS[test_ip] = deque([time.monotonic()] * main_mod.RATE_LIMIT_MAX_REQUESTS)
    try:
        blocked = client.post(
            "/v1/chat",
            headers={"x-forwarded-for": test_ip},
            json={
                "message": "When should my dad walk?",
                "evidence_bundle": bundle,
                "evidence_signature": sig,
                "language": "en",
            },
        )
        assert blocked.status_code == 429

        er_ok = client.post(
            "/v1/chat",
            headers={"x-forwarded-for": test_ip},
            json={
                "message": "My son can’t breathe",
                "evidence_bundle": bundle,
                "evidence_signature": sig,
                "language": "en",
            },
        )
        assert er_ok.status_code == 200
        assert er_ok.json()["emergency_alert"] is True
        assert er_ok.json()["source"] == "emergency_triage"
        assert "108" in er_ok.json()["reply"]
    finally:
        main_mod._RATE_BUCKETS.clear()


def test_audit_room_strips_exif_and_rejects_oversized_pixel_bomb(monkeypatch) -> None:
    """Verify /v1/audit-room strips JPEG EXIF metadata and blocks >25MP pixel bombs."""
    exif = Image.Exif()
    exif[271] = "TestCameraGPSLeak"
    jpg_buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(140, 170, 200)).save(
        jpg_buf, format="JPEG", exif=exif.tobytes()
    )
    raw_jpg = jpg_buf.getvalue()
    assert b"TestCameraGPSLeak" in raw_jpg

    captured: list[bytes] = []

    def capture_vision(
        _prompt: str, image_bytes: bytes, mime_type: str, _model: str, _key: str
    ) -> str:
        assert mime_type == "image/jpeg"
        captured.append(image_bytes)
        return (
            '{"room_summary": "Window track needs foam seal.", '
            '"tips": ['
            '{"title": "Foam Seal", "cost_inr": "Rs. 120", '
            '"action": "Apply foam strip.", "why_it_helps": "Cuts dust."}'
            "]}"
        )

    monkeypatch.setenv("GEMINI_API_KEY", "fake-exif-key")
    monkeypatch.setattr(explainer, "_call_gemini_vision_sync", capture_vision)
    ok_resp = client.post(
        "/v1/audit-room",
        data={"city": "Delhi", "language": "en"},
        files={"file": ("room.jpg", raw_jpg, "image/jpeg")},
    )
    assert ok_resp.status_code == 200
    assert len(captured) == 1
    assert b"TestCameraGPSLeak" not in captured[0]

    bomb_buf = io.BytesIO()
    Image.new("1", (6000, 5000)).save(bomb_buf, format="PNG")
    bomb_resp = client.post(
        "/v1/audit-room",
        data={"city": "Delhi", "language": "en"},
        files={"file": ("bomb.png", bomb_buf.getvalue(), "image/png")},
    )
    assert bomb_resp.status_code == 415
