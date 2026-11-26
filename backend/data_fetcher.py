"""Live Open-Meteo air, weather, and Pan-India geocoding fetcher with bounded TTL cache."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Any

import httpx

from geo_india import (
    CONSTANTS,
    FALLBACK_REPLAY,
    IST_TZ,
    PRESETS,
    build_meteorology_note,
    is_coastal_location,
    local_geocode_fallback,
    nearest_featured_city,
    suggest_language_for_state,
)

__all__ = [
    "CONSTANTS",
    "FALLBACK_REPLAY",
    "INDIA_LAT_BOUNDS",
    "INDIA_LON_BOUNDS",
    "IST_TZ",
    "PRESETS",
    "build_meteorology_note",
    "build_replay_payload",
    "clear_cache",
    "fetch_city_atmospheric_data",
    "geocode_india",
    "is_coastal_location",
    "nearest_featured_city",
    "reverse_geocode_india",
    "suggest_language_for_state",
    "validate_india_coordinates",
    "weather_cache_key",
]

logger = logging.getLogger("prana_ai.data_fetcher")

CACHE_TTL_SECONDS = 900  # 15 minutes
CACHE_MAX_ENTRIES = 256
INDIA_LAT_BOUNDS = (6.0, 37.5)
INDIA_LON_BOUNDS = (68.0, 97.5)

OPEN_METEO_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_WX_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
BIGDATACLOUD_REVERSE_URL = "https://api.bigdatacloud.net/data/reverse-geocode-client"

SPATIAL_RES_LIVE = "~40 km CAMS Global (3-hourly interpolated) + Weather Forecast"
SPATIAL_RES_REPLAY = "City-level historical replay profile (no live spatial grid)"

_LIVE_AQ_SERIES: tuple[tuple[str, bool], ...] = (
    ("pm2_5", False),
    ("pm10", False),
    ("nitrogen_dioxide", False),
    ("us_aqi", True),
)
_LIVE_WX_SERIES: tuple[str, ...] = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "boundary_layer_height",
)
_MULTIDAY_SERIES: tuple[str, ...] = ("pm2_5", "pm10", "nitrogen_dioxide")
_TTL_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_GEOCODE_CACHE: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()
_REVERSE_GEO_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()


def clear_cache() -> None:
    """Clear in-memory Open-Meteo, geocode, and reverse-geocode caches."""
    _TTL_CACHE.clear()
    _GEOCODE_CACHE.clear()
    _REVERSE_GEO_CACHE.clear()


def validate_india_coordinates(lat: float, lon: float) -> tuple[float, float]:
    """Validate that coordinates lie within Indian geographic bounds."""
    lat_f, lon_f = float(lat), float(lon)
    lat_min, lat_max = INDIA_LAT_BOUNDS
    lon_min, lon_max = INDIA_LON_BOUNDS
    if not (lat_min <= lat_f <= lat_max and lon_min <= lon_f <= lon_max):
        raise ValueError(
            f"Coordinates ({lat_f:.2f}, {lon_f:.2f}) fall outside supported India bounds."
        )
    return lat_f, lon_f


def weather_cache_key(lat: float, lon: float) -> str:
    """Return a ~0.25-degree spatial grid cache key aligned with ~40 km CAMS resolution."""
    return f"{round(float(lat) * 4.0) / 4.0:.2f}:{round(float(lon) * 4.0) / 4.0:.2f}"


def _get_aux_cached(cache: OrderedDict[str, tuple[float, Any]], key: str) -> Any | None:
    """Return a fresh cached geocode/reverse-geocode entry, or None when absent/expired."""
    entry = cache.get(key)
    if not entry:
        return None
    ts, val = entry
    if (time.monotonic() - ts) >= CACHE_TTL_SECONDS:
        cache.pop(key, None)
        return None
    cache.move_to_end(key)
    return val


def _store_aux_cached(cache: OrderedDict[str, tuple[float, Any]], key: str, value: Any) -> None:
    """Store a bounded geocode/reverse-geocode response in an LRU TTL cache."""
    cache[key] = (time.monotonic(), value)
    cache.move_to_end(key)
    while len(cache) > CACHE_MAX_ENTRIES:
        cache.popitem(last=False)


def _current_ist_date() -> str:
    """Return today's YYYY-MM-DD date string in Asia/Kolkata."""
    return datetime.now(IST_TZ).strftime("%Y-%m-%d")


def _payload_day0(payload: dict[str, Any] | None) -> str:
    """Return the day-0 YYYY-MM-DD date embedded in a cached payload, or empty string."""
    if not payload:
        return ""
    times = (payload.get("hourly_raw") or {}).get("time") or []
    return str(times[0])[:10] if times else ""


def _prune_and_store_cache(cache_key: str, payload: dict[str, Any]) -> None:
    """Evict expired entries and enforce bounded LRU cache size."""
    now_mono = time.monotonic()
    today_ist = _current_ist_date()
    expired = [
        k
        for k, (ts, item) in _TTL_CACHE.items()
        if (now_mono - ts) >= CACHE_TTL_SECONDS
        or ((day0 := _payload_day0(item)) and day0 != today_ist)
    ]
    for k in expired:
        _TTL_CACHE.pop(k, None)
    _TTL_CACHE[cache_key] = (now_mono, payload)
    _TTL_CACHE.move_to_end(cache_key)
    while len(_TTL_CACHE) > CACHE_MAX_ENTRIES:
        _TTL_CACHE.popitem(last=False)


def _get_cached_entry(cache_key: str) -> tuple[bool, dict[str, Any] | None]:
    """Return (is_fresh, same_day_payload) from the bounded TTL cache."""
    cached = _TTL_CACHE.get(cache_key)
    if not cached:
        return False, None
    ts, payload = cached
    day0 = _payload_day0(payload)
    if day0 and day0 != _current_ist_date():
        _TTL_CACHE.pop(cache_key, None)
        return False, None
    _TTL_CACHE.move_to_end(cache_key)
    return (time.monotonic() - ts) < CACHE_TTL_SECONDS, payload


async def _fetch_json(
    url: str,
    params: dict[str, Any],
    http_client: httpx.AsyncClient | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Fetch JSON via caller's AsyncClient or a scoped short-lived AsyncClient."""
    if http_client is None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=3.5)) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return dict(resp.json())
    resp = await http_client.get(url, params=params)
    resp.raise_for_status()
    return dict(resp.json())


def _sanitize_series(
    values: list[Any] | None,
    fallback: list[float],
    as_int: bool = False,
) -> tuple[list[Any], int]:
    """Fill missing/None hourly values safely and count how many slots used fallback."""
    if not values or len(values) < 24:
        return list(fallback), 24
    cleaned: list[Any] = []
    fallback_count = 0
    for idx in range(24):
        raw = values[idx]
        if raw is None:
            fallback_count += 1
            raw = cleaned[-1] if cleaned else fallback[idx]
        cleaned.append(int(round(float(raw))) if as_int else round(float(raw), 1))
    return cleaned, fallback_count


def _format_series_value(raw: Any, as_int: bool) -> Any:
    """Round one hourly float/int series sample cleanly."""
    return int(round(float(raw))) if as_int else round(float(raw), 1)


def _sanitize_multiday_series(
    values: list[Any] | None,
    fallback_day: list[float],
    days: int = 5,
    as_int: bool = False,
    day0_series: list[Any] | None = None,
) -> tuple[list[Any], int]:
    """Sanitize a 5x24h series, counting unique future-day (idx >= 24) fallback substitutions."""
    total = days * 24
    if not values or len(values) < 24:
        day0 = day0_series if day0_series and len(day0_series) == 24 else fallback_day
        out = [
            _format_series_value(
                float(v) * (1.0 if d == 0 else (0.94 + (d % 3) * 0.05)),
                as_int,
            )
            for d in range(days)
            for v in (day0 if d == 0 else fallback_day)
        ]
        return out, max(0, total - 24)

    cleaned: list[Any] = []
    future_fallback_count = 0
    for idx in range(total):
        raw = values[idx] if idx < len(values) else None
        if raw is None:
            if idx >= 24:
                future_fallback_count += 1
                raw = cleaned[idx - 24]
            else:
                raw = cleaned[-1] if cleaned else fallback_day[idx % 24]
        cleaned.append(_format_series_value(raw, as_int))
    return cleaned, future_fallback_count


async def geocode_india(
    query: str,
    count: int = 5,
    http_client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Search Indian places via cached Open-Meteo Geocoding API with local fallback."""
    q = query.strip()
    if len(q) < 2:
        return []
    cache_key = f"{q.lower()}:{count}"
    if (cached := _get_aux_cached(_GEOCODE_CACHE, cache_key)) is not None:
        return [dict(row) for row in cached]

    params = {"name": q, "count": count, "countryCode": "IN", "format": "json"}
    try:
        data = await _fetch_json(OPEN_METEO_GEOCODE_URL, params, http_client=http_client)
        formatted = [
            {
                "name": item["name"],
                "state": (state := item.get("admin1") or ""),
                "district": item.get("admin2") or "",
                "lat": (lat := round(float(item["latitude"]), 4)),
                "lon": (lon := round(float(item["longitude"]), 4)),
                "suggested_language": suggest_language_for_state(state, item["name"].lower()),
                "is_coastal": is_coastal_location(
                    lat,
                    lon,
                    state,
                    item["name"].lower() if item["name"].lower() in CONSTANTS["cities"] else None,
                ),
            }
            for item in data.get("results") or []
        ]
        if formatted:
            _store_aux_cached(_GEOCODE_CACHE, cache_key, formatted)
            return formatted
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning(
            "Open-Meteo geocoding failed (%s); using local India fallback.", type(exc).__name__
        )
    return local_geocode_fallback(q, count)


def _extract_locality_from_admins(data: dict[str, Any], city: str, state: str) -> str:
    """Extract sub-city locality name from BigDataCloud administrative hierarchy."""
    admins = data.get("localityInfo", {}).get("administrative") or []
    skip = {city.lower(), state.lower(), "india"}
    sub_names = [
        name_val
        for a in admins
        if (name_val := (a.get("name") or "").strip()) and name_val.lower() not in skip
    ]
    return sub_names[-1] if sub_names else ""


def _reverse_geocode_fallback(lat: float, lon: float, nearest_key: str) -> dict[str, Any]:
    """Build nearest featured-city metadata when reverse geocoding fails."""
    nearest_meta = CONSTANTS["cities"][nearest_key]
    return {
        "area_name": f"Near {nearest_meta['name']}",
        "city": nearest_meta["name"],
        "state": "",
        "lat": round(float(lat), 4),
        "lon": round(float(lon), 4),
        "suggested_language": nearest_meta["local_language"],
        "is_coastal": is_coastal_location(lat, lon, city_key=nearest_key),
    }


def _parse_reverse_geocode_payload(
    data: dict[str, Any], lat: float, lon: float, fallback_city_name: str
) -> dict[str, Any]:
    """Normalize BigDataCloud reverse-geocode payload into unified location dictionary."""
    city = (data.get("city") or "").strip()
    locality = (data.get("locality") or "").strip()
    state = (data.get("principalSubdivision") or "").strip()
    if not locality or locality.lower() == city.lower():
        locality = _extract_locality_from_admins(data, city, state) or locality
    resolved_city = city or locality or fallback_city_name
    city_low = resolved_city.lower()
    known_key = city_low if city_low in CONSTANTS["cities"] else None
    return {
        "area_name": locality or resolved_city,
        "city": resolved_city,
        "state": state,
        "lat": round(float(lat), 4),
        "lon": round(float(lon), 4),
        "suggested_language": suggest_language_for_state(state, city_low),
        "is_coastal": is_coastal_location(lat, lon, state=state, city_key=known_key),
    }


async def reverse_geocode_india(
    lat: float,
    lon: float,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Resolve Indian GPS coordinates to a cached readable Area, City via BigDataCloud."""
    lat_f, lon_f = validate_india_coordinates(lat, lon)
    cache_key = f"{round(lat_f * 50.0) / 50.0:.2f}:{round(lon_f * 50.0) / 50.0:.2f}"
    if (cached := _get_aux_cached(_REVERSE_GEO_CACHE, cache_key)) is not None:
        return {**cached, "lat": round(lat_f, 4), "lon": round(lon_f, 4)}

    nearest_key = nearest_featured_city(lat_f, lon_f)
    nearest_meta = CONSTANTS["cities"][nearest_key]
    try:
        params = {"latitude": lat_f, "longitude": lon_f, "localityLanguage": "en"}
        data = await _fetch_json(BIGDATACLOUD_REVERSE_URL, params, http_client=http_client)
        parsed = _parse_reverse_geocode_payload(data, lat_f, lon_f, str(nearest_meta["name"]))
        _store_aux_cached(_REVERSE_GEO_CACHE, cache_key, parsed)
        return parsed
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning(
            "Reverse geocoding failed (%s); falling back near %s.",
            type(exc).__name__,
            nearest_meta["name"],
        )
        return _reverse_geocode_fallback(lat_f, lon_f, nearest_key)


def _build_replay_series(
    replay_city: dict[str, Any], replay_date: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build 24h and 5-day hourly dictionaries from cached replay profiles."""
    base_dt = datetime.strptime(replay_date, "%Y-%m-%d")
    multi_times = [
        (base_dt + timedelta(days=d)).strftime("%Y-%m-%d") + f"T{h:02d}:00"
        for d in range(5)
        for h in range(24)
    ]
    hourly_raw: dict[str, Any] = {"time": [f"{replay_date}T{h:02d}:00" for h in range(24)]}
    for key, _ in _LIVE_AQ_SERIES:
        hourly_raw[key] = list(replay_city[key])
    for key in _LIVE_WX_SERIES:
        hourly_raw[key] = list(replay_city[key])

    multiday_raw: dict[str, Any] = {"time": multi_times}
    for key in _MULTIDAY_SERIES:
        series, _ = _sanitize_multiday_series(None, replay_city[key])
        multiday_raw[key] = series
    return hourly_raw, multiday_raw


def _build_replay_provenance(
    replay_date: str, feat_name: str, loc_label: str, reason: str
) -> dict[str, Any]:
    """Assemble provenance metadata block for historical winter replay payloads."""
    return {
        "source": f"PRANA-AI Historical Winter Replay ({replay_date})",
        "data_type": "historical_replay",
        "retrieved_at": datetime.now(IST_TZ).isoformat(timespec="seconds"),
        "is_stale": True,
        "is_fallback_replay": True,
        "is_partial_fallback": False,
        "fallback_slots": 24,
        "spatial_resolution": SPATIAL_RES_REPLAY,
        "spatial_note": (
            f"{reason}. Showing nearest regional historical winter replay "
            f"({feat_name} proxy) for {loc_label} instead of live forecast "
            "(3 of 8 CPCB criteria pollutants: PM2.5, PM10, NO2; excludes SO2, CO, O3, NH3, Pb)."
        ),
    }


def _resolve_replay_metadata(
    fallback_city_key: str, meta: dict[str, Any]
) -> tuple[dict[str, Any], float, float, bool, str]:
    """Extract normalized location coordinates, coastal flag, and label for replay synthesis."""
    feat_meta = CONSTANTS["cities"][fallback_city_key]
    resolved_city_key = meta.get("city_key") or fallback_city_key
    resolved_display = meta.get("city_display") or feat_meta["name"]
    area_name, state = meta.get("area_name"), meta.get("state")
    use_lat = float(meta["lat"]) if meta.get("lat") is not None else float(feat_meta["lat"])
    use_lon = float(meta["lon"]) if meta.get("lon") is not None else float(feat_meta["lon"])
    known_key = resolved_city_key if resolved_city_key in CONSTANTS["cities"] else None
    coastal = is_coastal_location(use_lat, use_lon, state=state, city_key=known_key)
    loc_label = (
        f"{resolved_display} ({area_name})"
        if area_name and area_name != resolved_display
        else resolved_display
    )
    return (
        {
            "city": resolved_city_key,
            "city_display": resolved_display,
            "area_name": area_name,
            "state": state,
            "known_key": known_key,
            "feat_name": feat_meta["name"],
        },
        round(use_lat, 4),
        round(use_lon, 4),
        coastal,
        loc_label,
    )


def build_replay_payload(
    fallback_city_key: str,
    reason: str,
    **meta: Any,
) -> dict[str, Any]:
    """Build a clearly labeled historical replay dataset for offline/stale degradation."""
    replay_date = FALLBACK_REPLAY["replay_date"]
    info, use_lat, use_lon, coastal, loc_label = _resolve_replay_metadata(fallback_city_key, meta)
    hourly_raw, multiday_raw = _build_replay_series(
        FALLBACK_REPLAY["cities"][fallback_city_key], replay_date
    )
    return {
        "city": info["city"],
        "city_display": info["city_display"],
        "area_name": info["area_name"],
        "state": info["state"],
        "lat": use_lat,
        "lon": use_lon,
        "is_coastal": coastal,
        "suggested_language": suggest_language_for_state(info["state"], info["known_key"]),
        "meteorology_note": build_meteorology_note(use_lat, coastal, city_key=info["known_key"]),
        "hourly_raw": hourly_raw,
        "multiday_raw": multiday_raw,
        "provenance": _build_replay_provenance(replay_date, info["feat_name"], loc_label, reason),
    }


def _resolve_featured_city_loc(
    city_key: str, coords: tuple[float | None, float | None], area_name: str | None
) -> tuple[float, float, str, str, str | None]:
    """Resolve coordinates and default sub-area label for a featured Indian city."""
    lat, lon = coords
    meta = CONSTANTS["cities"][city_key]
    if lat is not None and lon is not None:
        use_lat, use_lon = validate_india_coordinates(lat, lon)
    else:
        use_lat, use_lon = float(meta["lat"]), float(meta["lon"])
    resolved_area = area_name or (
        f"GPS ({use_lat:.3f}, {use_lon:.3f})" if lat is not None and lon is not None else None
    )
    return use_lat, use_lon, meta["name"], city_key, resolved_area


async def _resolve_custom_city_loc(
    city_clean: str,
    coords: tuple[float | None, float | None],
    hints: tuple[str | None, str | None],
    http_client: httpx.AsyncClient | None,
) -> tuple[float, float, str, str | None, str | None]:
    """Resolve coordinates and state metadata for any non-featured Indian city."""
    lat, lon = coords
    area_name, state = hints
    if lat is not None and lon is not None:
        use_lat, use_lon = validate_india_coordinates(lat, lon)
        return use_lat, use_lon, area_name or city_clean.title(), state, area_name

    geo = await geocode_india(city_clean, count=1, http_client=http_client)
    if not geo:
        raise ValueError(f"Could not find Indian location '{city_clean}'.")
    top = geo[0]
    resolved_state = state or top["state"] or None
    return float(top["lat"]), float(top["lon"]), top["name"], resolved_state, area_name


async def _resolve_location(
    city_clean: str,
    coords: tuple[float | None, float | None],
    hints: tuple[str | None, str | None],
    http_client: httpx.AsyncClient | None,
) -> dict[str, Any]:
    """Resolve city/coordinates/metadata for any Indian location."""
    city_key = city_clean.lower()
    if city_key in CONSTANTS["cities"]:
        use_lat, use_lon, city_display, fallback_key, resolved_area = _resolve_featured_city_loc(
            city_key, coords, hints[0]
        )
        state = hints[1] or CONSTANTS["cities"][city_key].get("state")
        known_key: str | None = city_key
    else:
        use_lat, use_lon, city_display, state, resolved_area = await _resolve_custom_city_loc(
            city_clean, coords, hints, http_client
        )
        fallback_key = nearest_featured_city(use_lat, use_lon)
        known_key = None

    coastal = is_coastal_location(use_lat, use_lon, state=state, city_key=known_key)
    return {
        "city_key": city_key,
        "city_display": city_display,
        "area_name": resolved_area,
        "state": state,
        "lat": use_lat,
        "lon": use_lon,
        "fallback_key": fallback_key,
        "coastal": coastal,
        "suggested_language": suggest_language_for_state(state, known_key),
        "meteorology_note": build_meteorology_note(use_lat, coastal, city_key=known_key),
    }


def _normalize_multiday_times(times: list[str]) -> list[str]:
    """Return 120 ISO hourly timestamps (5 days) aligned with upstream day 0."""
    multi_times = list(times[:120])
    if len(multi_times) < 120 and multi_times:
        start_dt = datetime.strptime(multi_times[0][:10], "%Y-%m-%d")
        return [
            (start_dt + timedelta(days=d)).strftime("%Y-%m-%d") + f"T{h:02d}:00"
            for d in range(5)
            for h in range(24)
        ]
    return multi_times


def _collect_sanitized_series(
    aq_json: dict[str, Any], wx_json: dict[str, Any], replay_city: dict[str, Any]
) -> tuple[dict[str, list[Any]], dict[str, list[Any]], int, int]:
    """Sanitize 24h AQ/weather arrays and 120h multiday AQ arrays with separate counts."""
    hourly_out: dict[str, list[Any]] = {}
    multi_out: dict[str, list[Any]] = {}
    hourly_slots = 0
    multiday_slots = 0

    for key, as_int in _LIVE_AQ_SERIES:
        series, count = _sanitize_series(aq_json.get(key), replay_city[key], as_int=as_int)
        hourly_out[key] = series
        hourly_slots += count
    for key in _LIVE_WX_SERIES:
        series, count = _sanitize_series(wx_json.get(key), replay_city[key])
        hourly_out[key] = series
        hourly_slots += count
    for key in _MULTIDAY_SERIES:
        series, count = _sanitize_multiday_series(
            aq_json.get(key), replay_city[key], day0_series=hourly_out.get(key)
        )
        multi_out[key] = series
        multiday_slots += count

    return hourly_out, multi_out, hourly_slots, multiday_slots


def _build_live_provenance(
    loc: dict[str, Any], hourly_slots: int, multiday_slots: int = 0
) -> dict[str, Any]:
    """Assemble provenance dictionary with separate hourly vs 5-day fallback accounting."""
    total_slots = hourly_slots + multiday_slots
    is_partial = total_slots > 0
    loc_parts = [p for p in (loc["area_name"], loc["city_display"], loc["state"]) if p]
    loc_desc = ", ".join(dict.fromkeys(loc_parts))
    base_note = (
        f"Pan-India Open-Meteo CAMS Global (~40 km, 3-hourly interpolated) + Weather Forecast "
        f"for {loc_desc} ({loc['lat']:.3f}, {loc['lon']:.3f}); not a doorstep CPCB monitor "
        "(3 of 8 CPCB criteria pollutants: PM2.5, PM10, NO2; excludes SO2, CO, O3, NH3, Pb)."
    )
    if is_partial:
        source_lbl = "Open-Meteo (CAMS Global + NWP, partial fallback)"
        data_type = "partial_model_forecast"
        spatial_note = (
            f"{base_note} Note: {hourly_slots} current-day and {multiday_slots} multi-day "
            "outlook slots used fallback fill."
        )
    else:
        source_lbl = "Open-Meteo (CAMS Global ~40 km + Weather Forecast)"
        data_type = "model_forecast"
        spatial_note = base_note
    return {
        "source": source_lbl,
        "data_type": data_type,
        "retrieved_at": datetime.now(IST_TZ).isoformat(timespec="seconds"),
        "is_stale": False,
        "is_fallback_replay": False,
        "is_partial_fallback": is_partial,
        "fallback_slots": total_slots,
        "hourly_fallback_slots": hourly_slots,
        "multiday_fallback_slots": multiday_slots,
        "is_multiday_fallback": multiday_slots > 0,
        "spatial_resolution": SPATIAL_RES_LIVE,
        "spatial_note": spatial_note,
    }


def _assemble_live_payload(
    loc: dict[str, Any],
    aq_json: dict[str, Any],
    wx_json: dict[str, Any],
) -> dict[str, Any]:
    """Assemble and sanitize 24h + 5-day payload while checking AQ/weather hour alignment."""
    aq_times = aq_json.get("time") or []
    wx_times = wx_json.get("time") or []
    if len(aq_times) < 24 or len(wx_times) < 24:
        raise ValueError("Incomplete 24-hour Open-Meteo response")
    if aq_times[:24] != wx_times[:24]:
        raise ValueError("Mismatched Open-Meteo air-quality and weather timestamps")

    replay_city = FALLBACK_REPLAY["cities"][loc["fallback_key"]]
    hourly_series, multi_series, hourly_slots, multiday_slots = _collect_sanitized_series(
        aq_json, wx_json, replay_city
    )
    return {
        "city": loc["city_key"],
        "city_display": loc["city_display"],
        "area_name": loc["area_name"],
        "state": loc["state"],
        "lat": round(loc["lat"], 4),
        "lon": round(loc["lon"], 4),
        "is_coastal": loc["coastal"],
        "suggested_language": loc["suggested_language"],
        "meteorology_note": loc["meteorology_note"],
        "hourly_raw": {"time": aq_times[:24], **hourly_series},
        "multiday_raw": {"time": _normalize_multiday_times(aq_times), **multi_series},
        "provenance": _build_live_provenance(loc, hourly_slots, multiday_slots),
    }


def _apply_loc_metadata(payload: dict[str, Any], loc: dict[str, Any]) -> dict[str, Any]:
    """Attach caller location metadata and caller-specific provenance note onto cache copy."""
    copy_payload = dict(payload)
    orig_prov = dict(payload.get("provenance") or {})
    raw_hourly = orig_prov.get("hourly_fallback_slots")
    if raw_hourly is None:
        raw_hourly = orig_prov.get("fallback_slots")
    rebuilt_prov = _build_live_provenance(
        loc,
        int(raw_hourly) if raw_hourly is not None else 0,
        int(orig_prov.get("multiday_fallback_slots") or 0),
    )
    rebuilt_prov["retrieved_at"] = orig_prov.get("retrieved_at", rebuilt_prov["retrieved_at"])
    rebuilt_prov["is_stale"] = bool(orig_prov.get("is_stale", False))
    rebuilt_prov["is_fallback_replay"] = bool(orig_prov.get("is_fallback_replay", False))

    copy_payload["city"] = loc["city_key"]
    copy_payload["city_display"] = loc["city_display"]
    copy_payload["area_name"] = loc["area_name"]
    copy_payload["state"] = loc["state"]
    copy_payload["is_coastal"] = loc["coastal"]
    copy_payload["suggested_language"] = loc["suggested_language"]
    copy_payload["meteorology_note"] = loc["meteorology_note"]
    copy_payload["provenance"] = rebuilt_prov
    return copy_payload


async def _gather_pair_cancelling(
    aq_params: dict[str, Any],
    wx_params: dict[str, Any],
    client: httpx.AsyncClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run AQ and Weather fetches concurrently, cancelling and awaiting sibling on failure."""
    aq_task = asyncio.create_task(_fetch_json(OPEN_METEO_AQ_URL, aq_params, http_client=client))
    wx_task = asyncio.create_task(_fetch_json(OPEN_METEO_WX_URL, wx_params, http_client=client))
    try:
        aq_res, wx_res = await asyncio.gather(aq_task, wx_task)
        return aq_res, wx_res
    except BaseException:
        for task in (aq_task, wx_task):
            if not task.done():
                task.cancel()
        with suppress(BaseException):
            await asyncio.gather(aq_task, wx_task, return_exceptions=True)
        raise


async def _fetch_om_pair(
    lat: float, lon: float, http_client: httpx.AsyncClient | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch Open-Meteo Air Quality and Weather JSON concurrently over an explicit IST range."""
    start_dt = datetime.now(IST_TZ).date()
    end_dt = start_dt + timedelta(days=4)
    date_bounds = {
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": end_dt.strftime("%Y-%m-%d"),
        "timezone": "Asia/Kolkata",
    }
    aq_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "pm2_5,pm10,nitrogen_dioxide,us_aqi",
        **date_bounds,
    }
    wx_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,boundary_layer_height",
        **date_bounds,
    }
    if http_client is not None:
        return await _gather_pair_cancelling(aq_params, wx_params, http_client)
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.5)) as shared_client:
        return await _gather_pair_cancelling(aq_params, wx_params, shared_client)


def _handle_live_fetch_error(exc: Exception, cache_key: str, loc: dict[str, Any]) -> dict[str, Any]:
    """Re-check cache on error and degrade gracefully to same-day stale cache or replay."""
    logger.warning("Open-Meteo upstream error (%s); serving fallback.", type(exc).__name__)
    _, cached_entry = _get_cached_entry(cache_key)
    if cached_entry:
        stale_payload = _apply_loc_metadata(cached_entry, loc)
        stale_payload["provenance"] = {
            **stale_payload["provenance"],
            "is_stale": True,
            "spatial_note": (
                f"Live API unavailable ({type(exc).__name__}); serving cached forecast."
            ),
        }
        return stale_payload
    return build_replay_payload(
        loc["fallback_key"],
        f"Live Open-Meteo fetch unavailable ({type(exc).__name__})",
        city_key=loc["city_key"],
        city_display=loc["city_display"],
        lat=loc["lat"],
        lon=loc["lon"],
        area_name=loc["area_name"],
        state=loc["state"],
    )


async def fetch_city_atmospheric_data(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    city: str = "delhi",
    simulate_stale: bool = False,
    lat: float | None = None,
    lon: float | None = None,
    area_name: str | None = None,
    state: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Fetch 24h air quality and meteorology from Open-Meteo for any Indian coordinates."""
    loc = await _resolve_location(
        city.strip() or "delhi", (lat, lon), (area_name, state), http_client
    )
    if simulate_stale:
        return build_replay_payload(
            loc["fallback_key"],
            "Stale/Offline simulation enabled",
            city_key=loc["city_key"],
            city_display=loc["city_display"],
            lat=loc["lat"],
            lon=loc["lon"],
            area_name=loc["area_name"],
            state=loc["state"],
        )

    cache_key = weather_cache_key(loc["lat"], loc["lon"])
    is_fresh, cached_entry = _get_cached_entry(cache_key)
    if is_fresh and cached_entry:
        return _apply_loc_metadata(cached_entry, loc)

    try:
        aq_raw, wx_raw = await _fetch_om_pair(loc["lat"], loc["lon"], http_client)
        payload = _assemble_live_payload(loc, aq_raw.get("hourly", {}), wx_raw.get("hourly", {}))
        _prune_and_store_cache(cache_key, payload)
        return payload
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return _handle_live_fetch_error(exc, cache_key, loc)
