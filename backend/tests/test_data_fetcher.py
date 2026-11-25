"""Unit and HTTP resilience tests for PRANA-AI data_fetcher and provenance tracking."""

from __future__ import annotations

import asyncio

import httpx

from data_fetcher import (
    _TTL_CACHE,
    CACHE_MAX_ENTRIES,
    _prune_and_store_cache,
    clear_cache,
    fetch_city_atmospheric_data,
    is_coastal_location,
    reverse_geocode_india,
)


def test_partial_upstream_payload_sets_partial_provenance() -> None:
    """Missing/None Open-Meteo slots must set is_partial_fallback=True rather than fake live."""
    clear_cache()

    def _partial_handler(request: httpx.Request) -> httpx.Response:
        times = [f"2026-11-25T{h:02d}:00" for h in range(24)]
        if "air-quality" in str(request.url):
            pm25 = [80.0 if h % 4 != 0 else None for h in range(24)]
            return httpx.Response(
                200,
                json={
                    "hourly": {
                        "time": times,
                        "pm2_5": pm25,
                        "pm10": [120.0] * 24,
                        "nitrogen_dioxide": [40.0] * 24,
                        "us_aqi": [150] * 24,
                    }
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "hourly": {
                    "time": times,
                    "temperature_2m": [20.0] * 24,
                    "relative_humidity_2m": [60.0] * 24,
                    "wind_speed_10m": [5.0] * 24,
                    "boundary_layer_height": [400.0] * 24,
                }
            },
            request=request,
        )

    async def _run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_partial_handler)) as client:
            return await fetch_city_atmospheric_data("delhi", http_client=client)

    payload = asyncio.run(_run())
    prov = payload["provenance"]
    assert prov["is_partial_fallback"] is True
    assert prov["fallback_slots"] > 0
    assert prov["data_type"] == "partial_model_forecast"
    assert "partial fallback" in prov["source"].lower()
    assert "~40 km" in prov["spatial_resolution"]


def test_ttl_cache_bounded_eviction() -> None:
    """In-memory TTL cache must evict oldest keys cleanly past CACHE_MAX_ENTRIES."""
    clear_cache()
    for idx in range(CACHE_MAX_ENTRIES + 10):
        _prune_and_store_cache(f"key_{idx}", {"idx": idx})
    assert len(_TTL_CACHE) == CACHE_MAX_ENTRIES
    assert "key_0" not in _TTL_CACHE
    assert f"key_{CACHE_MAX_ENTRIES + 9}" in _TTL_CACHE
    clear_cache()


def test_reverse_geocode_offline_fallback_honest_label() -> None:
    """Reverse geocode failure must not fabricate a wrong neighborhood like Dwarka/Andheri."""

    def _fail_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    async def _run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_fail_handler)) as client:
            return await reverse_geocode_india(28.6139, 77.2090, http_client=client)

    res = asyncio.run(_run())
    assert res["city"] == "Delhi"
    assert res["area_name"].startswith("Near ")
    assert is_coastal_location(19.0760, 72.8777, city_key="mumbai") is True
    assert is_coastal_location(28.6139, 77.2090, city_key="delhi") is False


def test_multiday_fallback_slots_not_double_counted() -> None:
    """Day-1 hours must not be counted twice when summing multiday fallback_slots."""
    clear_cache()

    def _multiday_handler(request: httpx.Request) -> httpx.Response:
        times = [
            f"2026-11-{25 + h // 24:02d}T{h % 24:02d}:00"
            for h in range(120)
        ]
        if "air-quality" in str(request.url):
            pm25: list[float | None] = [75.0] * 120
            pm25[30] = None  # Exactly one missing slot on Day 2 (idx >= 24)
            return httpx.Response(
                200,
                json={
                    "hourly": {
                        "time": times,
                        "pm2_5": pm25,
                        "pm10": [110.0] * 120,
                        "nitrogen_dioxide": [35.0] * 120,
                        "us_aqi": [155] * 120,
                    }
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "hourly": {
                    "time": times,
                    "temperature_2m": [21.0] * 120,
                    "relative_humidity_2m": [55.0] * 120,
                    "wind_speed_10m": [5.0] * 120,
                    "boundary_layer_height": [400.0] * 120,
                }
            },
            request=request,
        )

    async def _run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_multiday_handler)) as client:
            return await fetch_city_atmospheric_data("delhi", http_client=client)

    payload = asyncio.run(_run())
    prov = payload["provenance"]
    assert prov["is_partial_fallback"] is True
    assert prov["fallback_slots"] == 1


def test_partial_fallback_disclosure_required_and_templated() -> None:
    """Validator must enforce partial-fallback disclosure and deterministic plan must satisfy it."""
    import explainer
    from data_fetcher import PRESETS, _build_replay_payload
    from engine import build_evidence_bundle
    from safety import validate_narrative
    from schemas import PlanRequest

    raw = _build_replay_payload("delhi", "partial", is_fallback_replay=False)
    raw["provenance"]["is_stale"] = False
    raw["provenance"]["is_fallback_replay"] = False
    raw["provenance"]["is_partial_fallback"] = True
    raw["provenance"]["fallback_slots"] = 3
    raw["provenance"]["data_type"] = "partial_model_forecast"

    preset = next(p for p in PRESETS if p["id"] == "delhi_family")
    bundle = build_evidence_bundle(PlanRequest(**preset), raw, current_hour=9)

    ok_missing, reasons = validate_narrative(
        f"In Delhi, PM2.5 is {bundle.air_snapshot.current_pm25} ug/m3.", bundle
    )
    assert ok_missing is False
    assert any("partial" in r.lower() for r in reasons)

    text, source, ok = asyncio.run(explainer.generate_plan_narrative(bundle, skip_llm=True))
    assert source == "deterministic_template"
    assert ok is True
    assert "partial" in text.lower() or "fallback" in text.lower()
