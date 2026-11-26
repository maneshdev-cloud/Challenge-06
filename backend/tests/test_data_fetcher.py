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
    assert is_coastal_location(9.9252, 78.1198, state="Tamil Nadu", city_key=None) is False
    assert is_coastal_location(13.0827, 80.2707, state="Tamil Nadu", city_key=None) is True


def test_multiday_fallback_slots_not_double_counted() -> None:
    """Day-1 hours must not be counted twice when summing multiday fallback_slots."""
    clear_cache()

    def _multiday_handler(request: httpx.Request) -> httpx.Response:
        times = [f"2026-11-{25 + h // 24:02d}T{h % 24:02d}:00" for h in range(120)]
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
    assert prov["hourly_fallback_slots"] == 0
    assert prov["multiday_fallback_slots"] == 1
    assert prov["is_multiday_fallback"] is True

    # Missing multiday array while 24h hourly series is live must flag multiday fallback cleanly
    clear_cache()

    def _no_multiday_handler(request: httpx.Request) -> httpx.Response:
        times = [f"2026-11-26T{h:02d}:00" for h in range(24)]
        if "air-quality" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "hourly": {
                        "time": times,
                        "pm2_5": [55.0] * 24,
                        "pm10": [85.0] * 24,
                        "nitrogen_dioxide": [30.0] * 24,
                        "us_aqi": [110] * 24,
                    }
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "hourly": {
                    "time": times,
                    "temperature_2m": [22.0] * 24,
                    "relative_humidity_2m": [55.0] * 24,
                    "wind_speed_10m": [6.0] * 24,
                    "boundary_layer_height": [450.0] * 24,
                }
            },
            request=request,
        )

    async def _run_no_multi() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_no_multiday_handler)) as client:
            return await fetch_city_atmospheric_data("delhi", http_client=client)

    no_multi_payload = asyncio.run(_run_no_multi())
    nm_prov = no_multi_payload["provenance"]
    assert nm_prov["hourly_fallback_slots"] == 0
    assert nm_prov["multiday_fallback_slots"] == 288
    assert nm_prov["is_multiday_fallback"] is True
    assert nm_prov["is_partial_fallback"] is True


def test_partial_fallback_disclosure_required_and_templated() -> None:
    """Validator must enforce partial-fallback disclosure and deterministic plan must satisfy it."""
    import explainer
    from data_fetcher import PRESETS, build_replay_payload
    from engine import build_evidence_bundle
    from safety import validate_narrative
    from schemas import PlanRequest

    raw = build_replay_payload("delhi", "partial", is_fallback_replay=False)
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


def test_cache_ist_rollover_recheck_and_caller_spatial_note() -> None:
    """Verify midnight IST expiration, distinct caller spatial_note, and AQ/WX alignment."""
    from datetime import datetime

    from data_fetcher import IST_TZ, _get_cached_entry

    clear_cache()
    today = datetime.now(IST_TZ).strftime("%Y-%m-%d")

    def _live_handler(request: httpx.Request) -> httpx.Response:
        times = [f"{today}T{h:02d}:00" for h in range(24)]
        if "air-quality" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "hourly": {
                        "time": times,
                        "pm2_5": [60.0] * 24,
                        "pm10": [90.0] * 24,
                        "nitrogen_dioxide": [25.0] * 24,
                        "us_aqi": [110] * 24,
                    }
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "hourly": {
                    "time": times,
                    "temperature_2m": [24.0] * 24,
                    "relative_humidity_2m": [50.0] * 24,
                    "wind_speed_10m": [6.0] * 24,
                    "boundary_layer_height": [500.0] * 24,
                }
            },
            request=request,
        )

    async def _run_two_callers() -> tuple[dict, dict]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_live_handler)) as client:
            first = await fetch_city_atmospheric_data(
                "mumbai", lat=19.0760, lon=72.8777, area_name="Andheri", http_client=client
            )
            second = await fetch_city_atmospheric_data(
                "mumbai", lat=19.0760, lon=72.8777, area_name="Colaba", http_client=client
            )
            return first, second

    p1, p2 = asyncio.run(_run_two_callers())
    assert "Andheri" in p1["provenance"]["spatial_note"]
    assert "Colaba" in p2["provenance"]["spatial_note"]
    assert "Andheri" not in p2["provenance"]["spatial_note"]

    # Previous IST day cache entry must expire immediately regardless of monotonic TTL
    _prune_and_store_cache(
        "old_day_key",
        {"hourly_raw": {"time": ["2020-01-01T00:00"]}},
    )
    assert _get_cached_entry("old_day_key") == (False, None)

    # Mismatched AQ and Weather time arrays must reject cleanly into historical replay
    clear_cache()

    def _mismatched_handler(request: httpx.Request) -> httpx.Response:
        if "air-quality" in str(request.url):
            times = [f"2026-11-26T{h:02d}:00" for h in range(24)]
            return httpx.Response(
                200,
                json={"hourly": {"time": times, "pm2_5": [50.0] * 24}},
                request=request,
            )
        wx_times = [f"2026-11-27T{h:02d}:00" for h in range(24)]
        return httpx.Response(
            200,
            json={"hourly": {"time": wx_times, "temperature_2m": [20.0] * 24}},
            request=request,
        )

    async def _run_mismatch() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_mismatched_handler)) as client:
            return await fetch_city_atmospheric_data("pune", http_client=client)

    mismatched = asyncio.run(_run_mismatch())
    assert mismatched["provenance"]["is_fallback_replay"] is True


def test_upstream_failure_cancels_sibling_and_rereads_fresh_cache() -> None:
    """Failing AQ request cancels pending weather task and re-reads fresh concurrent cache."""
    from datetime import datetime

    from data_fetcher import CONSTANTS, IST_TZ, _prune_and_store_cache, weather_cache_key

    clear_cache()
    today = datetime.now(IST_TZ).strftime("%Y-%m-%d")
    wx_cancelled = {"flag": False}

    async def _concurrent_handler(request: httpx.Request) -> httpx.Response:
        if "air-quality" in str(request.url):
            # Another concurrent request populates cache while this fetch is in flight
            lat = float(CONSTANTS["cities"]["delhi"]["lat"])
            lon = float(CONSTANTS["cities"]["delhi"]["lon"])
            _prune_and_store_cache(
                weather_cache_key(lat, lon),
                {
                    "city": "delhi",
                    "city_display": "Delhi",
                    "area_name": None,
                    "state": None,
                    "hourly_raw": {"time": [f"{today}T{h:02d}:00" for h in range(24)]},
                    "provenance": {"is_stale": False, "fallback_slots": 0},
                },
            )
            return httpx.Response(503, request=request)
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            wx_cancelled["flag"] = True
            raise
        return httpx.Response(200, json={}, request=request)

    async def _run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_concurrent_handler)) as client:
            return await fetch_city_atmospheric_data("delhi", http_client=client)

    payload = asyncio.run(_run())
    assert wx_cancelled["flag"] is True
    assert payload["provenance"]["is_stale"] is True
    assert payload["provenance"]["is_fallback_replay"] is False


def test_coarse_weather_cache_geocode_caches_and_india_bounds() -> None:
    """Verify 0.25-deg AQ/WX cache reuse, cached geocode/reverse-geocode, and India bbox."""
    import pytest

    from data_fetcher import geocode_india, validate_india_coordinates

    clear_cache()
    calls = {"aq_wx": 0, "geo": 0, "rev": 0}
    times = [f"2026-11-26T{h:02d}:00" for h in range(24)]

    def _counting_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "geocoding-api" in url:
            calls["geo"] += 1
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "Pune",
                            "admin1": "Maharashtra",
                            "admin2": "Pune",
                            "latitude": 18.5204,
                            "longitude": 73.8567,
                        }
                    ]
                },
                request=request,
            )
        if "bigdatacloud" in url:
            calls["rev"] += 1
            return httpx.Response(
                200,
                json={"city": "Pune", "locality": "Kothrud", "principalSubdivision": "Maharashtra"},
                request=request,
            )
        calls["aq_wx"] += 1
        return httpx.Response(
            200,
            json={
                "hourly": {
                    "time": times,
                    "pm2_5": [55.0] * 24,
                    "pm10": [85.0] * 24,
                    "nitrogen_dioxide": [30.0] * 24,
                    "us_aqi": [110] * 24,
                    "temperature_2m": [24.0] * 24,
                    "relative_humidity_2m": [55.0] * 24,
                    "wind_speed_10m": [8.0] * 24,
                    "boundary_layer_height": [450.0] * 24,
                }
            },
            request=request,
        )

    async def _exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_counting_handler)) as client:
            await fetch_city_atmospheric_data(
                "custom", lat=28.613, lon=77.209, area_name="CP", http_client=client
            )
            await fetch_city_atmospheric_data(
                "custom", lat=28.614, lon=77.210, area_name="Janpath", http_client=client
            )
            await geocode_india("Pune", count=3, http_client=client)
            await geocode_india("pune", count=3, http_client=client)
            await reverse_geocode_india(18.5204, 73.8567, http_client=client)
            await reverse_geocode_india(18.5210, 73.8570, http_client=client)

    asyncio.run(_exercise())
    assert calls["aq_wx"] == 2  # Exactly 1 AQ + 1 WX request across both nearby coords
    assert calls["geo"] == 1
    assert calls["rev"] == 1

    with pytest.raises(ValueError, match="India bounds"):
        validate_india_coordinates(-33.86, 151.20)
    with pytest.raises(ValueError, match="India bounds"):
        validate_india_coordinates(0.0, 0.0)
