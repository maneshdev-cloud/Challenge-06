"""End-to-end FastAPI TestClient tests for PRANA-AI REST endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import app

client = TestClient(app)


def test_health_and_presets() -> None:
    """Verify /health (GET & HEAD) and all 4 demo personas from /v1/presets."""
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["app"] == "PRANA-AI"
    h_head = client.head("/health")
    assert h_head.status_code == 200

    presets_resp = client.get("/v1/presets")
    assert presets_resp.status_code == 200
    presets = presets_resp.json()
    assert len(presets) == 4
    assert {p["id"] for p in presets} == {"delhi_family", "mumbai_student", "pune_elderly", "delivery_rider"}
    assert all(p["language"] == "en" for p in presets)

    cities_resp = client.get("/v1/cities")
    assert cities_resp.status_code == 200
    cities = cities_resp.json()
    assert list(cities.keys())[:4] == ["mumbai", "pune", "delhi", "bengaluru"]
    assert cities["bengaluru"]["name"] == "Bangalore"
    assert cities["delhi"]["local_language"] == "hi"
    assert cities["mumbai"]["local_language"] == "mr"
    assert cities["pune"]["local_language"] == "mr"
    assert cities["bengaluru"]["local_language"] == "kn"
    assert cities["kolkata"]["local_language"] == "bn"
    assert len(cities["delhi"]["areas"]) == 5


def test_air_endpoint_stale_replay() -> None:
    """Verify /v1/air returns 24h data, Golden Window, and replay metadata with area/GPS coords."""
    resp = client.get(
        "/v1/air",
        params={"city": "delhi", "lat": 28.6469, "lon": 77.3164, "area_name": "Anand Vihar", "simulate_stale": "true"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["city"] == "delhi"
    assert data["area_name"] == "Anand Vihar"
    assert data["lat"] == 28.6469
    assert len(data["hourly"]) == 24
    assert len(data["daily_outlook"]) == 5
    assert data["daily_outlook"][0]["best_window_label"]
    assert data["provenance"]["is_fallback_replay"] is True
    assert data["golden_window"]["hours"]


def test_plan_all_presets_and_what_if() -> None:
    """Verify POST /v1/plan succeeds for all 4 presets with skip_llm=True and What-If sliders."""
    presets = client.get("/v1/presets").json()
    for p in presets:
        payload = {**p, "simulate_stale": True, "skip_llm": True}
        resp = client.post("/v1/plan", json=payload)
        assert resp.status_code == 200, f"Failed for preset {p['id']}: {resp.text}"
        body = resp.json()
        assert body["evidence_bundle"]["app_name"] == "PRANA-AI"
        assert body["validator_passed"] is True
        assert body["evidence_bundle"]["provenance"]["is_fallback_replay"] is True

    # Verify What-If walk_override_hour recalculation via POST /v1/plan with skip_llm=True
    delhi = next(p for p in presets if p["id"] == "delhi_family")
    opt_plan = client.post("/v1/plan", json={**delhi, "simulate_stale": True, "skip_llm": True}).json()
    peak_plan = client.post(
        "/v1/plan",
        json={**delhi, "walk_override_hour": 7, "simulate_stale": True, "skip_llm": True},
    ).json()
    assert peak_plan["narrative_source"] == "deterministic_template"
    assert peak_plan["evidence_bundle"]["breathe_less"]["dose_avoided_ug"] < opt_plan["evidence_bundle"]["breathe_less"]["dose_avoided_ug"]


def test_chat_normal_and_emergency_triage() -> None:
    """Verify POST /v1/chat answers grounded queries and triggers ER alert on wheezing."""
    delhi_preset = next(p for p in client.get("/v1/presets").json() if p["id"] == "delhi_family")
    plan = client.post("/v1/plan", json={**delhi_preset, "simulate_stale": True, "skip_llm": True}).json()
    bundle = plan["evidence_bundle"]

    chat_ok = client.post("/v1/chat", json={"message": "When should my dad walk?", "evidence_bundle": bundle, "language": "en"})
    assert chat_ok.status_code == 200
    assert chat_ok.json()["emergency_alert"] is False
    assert chat_ok.json()["validator_passed"] is True

    chat_er = client.post("/v1/chat", json={"message": "My son is wheezing badly", "evidence_bundle": bundle, "language": "en"})
    assert chat_er.status_code == 200
    assert chat_er.json()["emergency_alert"] is True
    assert chat_er.json()["source"] == "emergency_triage"
    assert "108" in chat_er.json()["reply"]


def test_pan_india_geocode_and_arbitrary_coords(monkeypatch) -> None:
    """Verify /v1/geocode and generalized Pan-India /v1/air & /v1/plan for arbitrary cities/states."""
    import main as main_mod

    async def fake_geocode(q: str, count: int = 5):
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
    geo = geo_resp.json()
    assert geo[0]["name"] == "Chennai"
    assert geo[0]["suggested_language"] == "ta"
    assert geo[0]["is_coastal"] is True

    # Arbitrary Indian town coordinates (e.g., Jaipur, Rajasthan) with offline replay fallback
    air_resp = client.get(
        "/v1/air",
        params={"city": "Jaipur", "state": "Rajasthan", "lat": 26.9196, "lon": 75.7878, "simulate_stale": "true"},
    )
    assert air_resp.status_code == 200
    air_data = air_resp.json()
    assert air_data["city_name"] == "Jaipur"
    assert air_data["state"] == "Rajasthan"
    assert air_data["is_coastal"] is False
    assert air_data["suggested_language"] == "hi"

    delhi = next(p for p in client.get("/v1/presets").json() if p["id"] == "delhi_family")
    plan_resp = client.post(
        "/v1/plan",
        json={
            **delhi,
            "city": "Chennai",
            "area_name": "Chennai",
            "state": "Tamil Nadu",
            "lat": 13.0827,
            "lon": 80.2707,
            "simulate_stale": True,
            "skip_llm": True,
        },
    )
    assert plan_resp.status_code == 200
    plan_data = plan_resp.json()
    assert plan_data["evidence_bundle"]["air_snapshot"]["is_coastal"] is True
    assert plan_data["evidence_bundle"]["air_snapshot"]["suggested_language"] == "ta"


def test_reverse_geocode_endpoint_and_fallback(monkeypatch) -> None:
    """Verify /v1/reverse-geocode returns readable Area, City (never raw coordinates)."""
    import main as main_mod

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
    data = resp.json()
    assert data["area_name"] == "Andheri"
    assert data["city"] == "Mumbai"
    assert "19.11" not in data["area_name"]


def test_audit_room_endpoint_validation_and_fallback(monkeypatch) -> None:
    """Verify /v1/audit-room handles valid PNGs, Vision fallback, >5MB rejection (413), and invalid formats (415)."""
    import io
    import explainer
    from PIL import Image

    explainer.reset_failover_cache()

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(180, 210, 220)).save(buf, format="PNG")
    png_bytes = buf.getvalue()

    # Case 1: Mocked Gemini Vision 404/429 failover -> working model returns 3 tips
    def fake_vision(prompt: str, image_bytes: bytes, mime_type: str, model_name: str, api_key: str) -> str:
        assert mime_type == "image/png"
        return (
            '{"room_summary": "Sliding balcony door has small frame gaps near curtains.", '
            '"tips": ['
            '{"title": "Foam Seal Balcony Track", "cost_inr": "Rs. 140", "action": "Stick EPDM foam strip along sliding frame.", "why_it_helps": "Blocks traffic dust leaks."}, '
            '{"title": "Shut Kitchen Door During Tadka", "cost_inr": "Rs. 0", "action": "Close kitchen partition and run exhaust 15 min.", "why_it_helps": "Stops cooking spikes."}, '
            '{"title": "Wet Wipe Window Sill", "cost_inr": "Rs. 30", "action": "Wipe settled dust with damp cloth daily.", "why_it_helps": "Stops settled PM2.5 re-floating."}'
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
    body = ok_resp.json()
    assert body["source"] == "gemini"
    assert len(body["tips"]) == 3

    # Case 2: Gemini fails -> seamless deterministic fallback (never crashes)
    def failing_vision(*args, **kwargs):
        raise TimeoutError("Vision timed out")

    monkeypatch.setattr(explainer, "_call_gemini_vision_sync", failing_vision)
    fb_resp = client.post(
        "/v1/audit-room",
        data={"city": "Delhi", "language": "en"},
        files={"file": ("room.png", png_bytes, "image/png")},
    )
    assert fb_resp.status_code == 200
    assert fb_resp.json()["source"] == "deterministic_template"
    assert len(fb_resp.json()["tips"]) == 3

    # Case 3: Reject non-image / invalid bytes (415)
    bad_type = client.post(
        "/v1/audit-room",
        data={"city": "Delhi", "language": "en"},
        files={"file": ("notes.txt", b"not an image at all", "text/plain")},
    )
    assert bad_type.status_code == 415

    # Case 4: Reject >5 MB payload cleanly (413)
    oversized = b"A" * (5 * 1024 * 1024 + 128)
    too_big = client.post(
        "/v1/audit-room",
        data={"city": "Delhi", "language": "en"},
        files={"file": ("huge.jpg", oversized, "image/jpeg")},
    )
    assert too_big.status_code == 413


def test_chat_trip_planning_and_simulated_crash_returns_200(monkeypatch) -> None:
    """Verify 'i want to plan a trip' and simulated uncaught errors always return HTTP 200 cleanly."""
    import explainer
    import main as main_mod

    delhi_preset = next(p for p in client.get("/v1/presets").json() if p["id"] == "delhi_family")
    bundle = client.post("/v1/plan", json={**delhi_preset, "simulate_stale": True, "skip_llm": True}).json()["evidence_bundle"]

    # Case 1: Normal offline/trip query via deterministic reply (force no API keys to test fast deterministic path)
    monkeypatch.setattr(explainer, "_get_api_keys", lambda: [])
    trip_resp = client.post(
        "/v1/chat",
        json={"message": "i want to plan a trip", "evidence_bundle": bundle, "language": "en"},
    )
    assert trip_resp.status_code == 200
    body = trip_resp.json()
    assert body["emergency_alert"] is False
    assert body["source"] == "deterministic_template"
    assert "trip" in body["reply"].lower()
    assert "What to Do:" in body["reply"]

    # Case 2: Simulated uncaught exception inside generate_chat_reply -> still returns HTTP 200 fallback
    async def crashing_chat(*args, **kwargs):
        raise RuntimeError("Simulated uncaught Gemini SDK / schema crash")

    monkeypatch.setattr(main_mod, "generate_chat_reply", crashing_chat)
    crash_resp = client.post(
        "/v1/chat",
        json={"message": "i want to plan a trip", "evidence_bundle": bundle, "language": "en"},
    )
    assert crash_resp.status_code == 200
    assert crash_resp.json()["source"] == "deterministic_template"
    assert len(crash_resp.json()["reply"].strip()) > 20

    # Case 3: Even a secondary crash inside build_deterministic_chat_reply must still return HTTP 200
    def crashing_deterministic(*args, **kwargs):
        raise KeyError("missing_field")

    monkeypatch.setattr(explainer, "build_deterministic_chat_reply", crashing_deterministic)
    safe_resp = client.post(
        "/v1/chat",
        json={"message": "i want to plan a trip", "evidence_bundle": bundle, "language": "en"},
    )
    assert safe_resp.status_code == 200
    assert "PM2.5" in safe_resp.json()["reply"]


def test_four_user_categories_update_risk_and_dose_on_same_city() -> None:
    """Verify switching across all 4 User Categories on the same city updates risk warnings, dose, and tasks."""
    categories = [
        {
            "user_category": "students_kids",
            "budget_tier": "rs_0",
            "commute_mode": "auto_cng",
            "target_commute_mode": "electric_metro",
            "commute_km": 12.0,
            "members": [{"name": "School Child", "age": 9, "conditions": ["child"]}],
            "activities": [{"id": "sports_play", "name": "Outdoor Sports", "flexibility": "flexible", "planned_hour": 17, "duration_min": 45, "activity_level": "child_play", "member_name": "School Child", "current_mask": "none"}],
        },
        {
            "user_category": "adults_commuters",
            "budget_tier": "under_2200",
            "commute_mode": "car_petrol_solo",
            "target_commute_mode": "electric_metro",
            "commute_km": 16.0,
            "members": [{"name": "Commuter", "age": 34, "conditions": ["adult"]}],
            "activities": [{"id": "brisk_walk", "name": "Daily Brisk Walk", "flexibility": "flexible", "planned_hour": 7, "duration_min": 40, "activity_level": "brisk_walk", "member_name": "Commuter", "current_mask": "none"}],
        },
        {
            "user_category": "seniors",
            "budget_tier": "under_500",
            "commute_mode": "auto_cng",
            "target_commute_mode": "city_bus",
            "commute_km": 6.0,
            "members": [{"name": "Senior Member", "age": 70, "conditions": ["elderly", "copd"]}],
            "activities": [{"id": "senior_walk", "name": "Morning Park Walk", "flexibility": "flexible", "planned_hour": 6, "duration_min": 45, "activity_level": "elderly_walk", "member_name": "Senior Member", "current_mask": "cloth"}],
        },
        {
            "user_category": "delivery_riders",
            "budget_tier": "under_500",
            "commute_mode": "two_wheeler_petrol",
            "target_commute_mode": "two_wheeler_petrol",
            "commute_km": 40.0,
            "members": [{"name": "Delivery Rider", "age": 29, "conditions": ["outdoor_worker"]}],
            "activities": [{"id": "shift_morning", "name": "Delivery Shift (8h)", "flexibility": "fixed", "planned_hour": 8, "duration_min": 480, "activity_level": "running_or_outdoor_work", "member_name": "Delivery Rider", "current_mask": "cloth", "is_commute": True, "is_work_shift": True}],
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

    # Outdoor AQI & PM2.5 stay constant for the city across all 4 categories
    naqis = {b["air_snapshot"]["current_naqi"] for b in results.values()}
    pm25s = {b["air_snapshot"]["current_pm25"] for b in results.values()}
    assert len(naqis) == 1
    assert len(pm25s) == 1

    # Risk thresholds & warnings differ: 100 for kids/seniors/riders vs 150 for adults
    assert results["students_kids"]["profile_summary"]["warning_threshold_naqi"] == 100
    assert results["seniors"]["profile_summary"]["warning_threshold_naqi"] == 100
    assert results["delivery_riders"]["profile_summary"]["warning_threshold_naqi"] == 100
    assert results["adults_commuters"]["profile_summary"]["warning_threshold_naqi"] == 150

    # Personal doses, CO2 counterfactuals, and warning banners are all distinct
    assert len({b["breathe_less"]["baseline_dose_ug"] for b in results.values()}) == 4
    assert len({b["emit_less"]["co2_saved_g"] for b in results.values()}) == 4
    assert len({b["profile_summary"]["warning_banner"] for b in results.values()}) == 4
