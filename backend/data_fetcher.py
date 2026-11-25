"""Live Open-Meteo air, weather, and Pan-India geocoding fetcher with bounded TTL cache."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("prana_ai.data_fetcher")

DATA_DIR = Path(__file__).resolve().parent / "data"
IST_TZ = timezone(timedelta(hours=5, minutes=30))
CACHE_TTL_SECONDS = 900  # 15 minutes
CACHE_MAX_ENTRIES = 256

OPEN_METEO_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_WX_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
BIGDATACLOUD_REVERSE_URL = "https://api.bigdatacloud.net/data/reverse-geocode-client"

SPATIAL_RES_LIVE = "~40 km CAMS Global (3-hourly interpolated) + Weather Forecast"
SPATIAL_RES_REPLAY = "City-level historical replay profile (no live spatial grid)"


def load_json_data(filename: str) -> Any:
    """Load a JSON file from backend/data/."""
    with open(DATA_DIR / filename, encoding="utf-8") as fh:
        return json.load(fh)


CONSTANTS: dict[str, Any] = load_json_data("constants.json")
FALLBACK_REPLAY: dict[str, Any] = load_json_data("fallback_replay.json")
PRESETS: list[dict[str, Any]] = load_json_data("presets.json")

_TTL_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

STATE_LANGUAGE_MAP = {
    "maharashtra": "mr",
    "goa": "mr",
    "karnataka": "kn",
    "west bengal": "bn",
    "tripura": "bn",
    "tamil nadu": "ta",
    "puducherry": "ta",
    "telangana": "te",
    "andhra pradesh": "te",
    "delhi": "hi",
    "national capital territory of delhi": "hi",
    "uttar pradesh": "hi",
    "haryana": "hi",
    "rajasthan": "hi",
    "bihar": "hi",
    "madhya pradesh": "hi",
    "jharkhand": "hi",
    "uttarakhand": "hi",
    "chhattisgarh": "hi",
    "himachal pradesh": "hi",
    "chandigarh": "hi",
}

COASTAL_STATES = {
    "goa",
    "kerala",
    "tamil nadu",
    "puducherry",
    "andaman and nicobar islands",
    "lakshadweep",
    "daman and diu",
    "dadra and nagar haveli and daman and diu",
}

COASTAL_CITIES = {
    "mumbai",
    "chennai",
    "kochi",
    "visakhapatnam",
    "thiruvananthapuram",
    "mangaluru",
    "mangalore",
    "surat",
    "panaji",
    "puducherry",
    "kozhikode",
    "puri",
    "navi mumbai",
}


def clear_cache() -> None:
    """Clear the in-memory Open-Meteo TTL cache (useful in tests)."""
    _TTL_CACHE.clear()


def _prune_and_store_cache(cache_key: str, payload: dict[str, Any]) -> None:
    """Evict expired entries and enforce bounded LRU cache size."""
    now_mono = time.monotonic()
    expired = [k for k, (ts, _) in _TTL_CACHE.items() if (now_mono - ts) >= CACHE_TTL_SECONDS]
    for k in expired:
        _TTL_CACHE.pop(k, None)
    _TTL_CACHE[cache_key] = (now_mono, payload)
    _TTL_CACHE.move_to_end(cache_key)
    while len(_TTL_CACHE) > CACHE_MAX_ENTRIES:
        _TTL_CACHE.popitem(last=False)


def _get_cached_entry(cache_key: str) -> tuple[bool, dict[str, Any] | None]:
    """Return (is_fresh, cached_payload) from the bounded TTL cache."""
    cached = _TTL_CACHE.get(cache_key)
    if not cached:
        return False, None
    ts, payload = cached
    _TTL_CACHE.move_to_end(cache_key)
    is_fresh = (time.monotonic() - ts) < CACHE_TTL_SECONDS
    return is_fresh, payload


async def _fetch_json(
    url: str,
    params: dict[str, Any],
    http_client: httpx.AsyncClient | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Fetch JSON via caller's AsyncClient or a short-lived pooled client."""
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=3.5))
    try:
        resp = await client.get(url, params=params)
    finally:
        if owns_client:
            await client.aclose()
    resp.raise_for_status()
    return dict(resp.json())


def suggest_language_for_state(state: str | None, city_key: str | None = None) -> str:
    """Suggest a local Indian language from state name or featured city key."""
    if city_key and city_key in CONSTANTS["cities"]:
        return str(CONSTANTS["cities"][city_key]["local_language"])
    if state:
        s_low = state.strip().lower()
        for key, lang in STATE_LANGUAGE_MAP.items():
            if key in s_low:
                return lang
    return "hi"


def is_coastal_location(
    lat: float,
    lon: float,
    state: str | None = None,
    city_key: str | None = None,
) -> bool:
    """Classify coastal vs. inland meteorology from city/state or shoreline coordinates."""
    if city_key and city_key.strip().lower() in COASTAL_CITIES:
        return True
    if state and state.strip().lower() in COASTAL_STATES:
        return True
    west_coast = 8.0 <= lat <= 22.8 and 68.5 <= lon <= 73.5
    east_coast = (
        8.0 <= lat <= 21.8 and 79.6 <= lon <= 87.5 and lat <= (13.0 + (lon - 79.8) * 1.4)
    )
    return west_coast or east_coast


def nearest_featured_city(lat: float, lon: float) -> str:
    """Return nearest featured city key for historical replay fallback."""
    best_key = "delhi"
    best_dist = float("inf")
    for key, meta in CONSTANTS["cities"].items():
        d_lat = lat - float(meta["lat"])
        d_lon = lon - float(meta["lon"])
        dist = d_lat * d_lat + d_lon * d_lon
        if dist < best_dist:
            best_dist = dist
            best_key = key
    return best_key


def build_meteorology_note(lat: float, coastal: bool, city_key: str | None = None) -> str:
    """Generate dynamic coastal vs. northern/inland Indian atmospheric dispersion context."""
    if city_key and city_key in CONSTANTS["cities"]:
        return str(CONSTANTS["cities"][city_key]["meteorology_note"])
    if coastal:
        return (
            "Coastal Indian profile: sea-breeze transitions often improve daytime dispersion, "
            "while calm mornings and roadside traffic corridors still create localized peaks."
        )
    if lat >= 23.5:
        return (
            "Northern / Indo-Gangetic inland profile: winter nocturnal thermal inversions and "
            "low winds trap PM2.5 near ground level until daytime warming lifts the boundary layer."
        )
    return (
        "Inland plateau/basin profile: overnight cooling near the surface traps morning emissions "
        "before midday convection widens the boundary layer."
    )


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
        val = int(round(float(raw))) if as_int else round(float(raw), 1)
        cleaned.append(val)
    return cleaned, fallback_count


def _sanitize_multiday_series(
    values: list[Any] | None,
    fallback_day: list[float],
    days: int = 5,
    as_int: bool = False,
) -> tuple[list[Any], int]:
    """Sanitize a 5x24h series, tracking how many slots were padded/synthesized."""
    total = days * 24
    if not values or len(values) < 24:
        out: list[Any] = []
        for d in range(days):
            scale = 1.0 if d == 0 else (0.94 + (d % 3) * 0.05)
            for v in fallback_day:
                val = int(round(float(v) * scale)) if as_int else round(float(v) * scale, 1)
                out.append(val)
        return out, total

    cleaned: list[Any] = []
    fallback_count = 0
    for idx in range(total):
        raw = values[idx] if idx < len(values) else None
        if raw is None:
            fallback_count += 1
            if idx >= 24:
                raw = cleaned[idx - 24]
            elif cleaned:
                raw = cleaned[-1]
            else:
                raw = fallback_day[idx % 24]
        val = int(round(float(raw))) if as_int else round(float(raw), 1)
        cleaned.append(val)
    return cleaned, fallback_count


def _local_geocode_fallback(query: str, count: int) -> list[dict[str, Any]]:
    """Offline matcher across featured cities and preset areas."""
    q_low = query.lower()
    matches: list[dict[str, Any]] = []
    for c_key, meta in CONSTANTS["cities"].items():
        if q_low in meta["name"].lower() or q_low in c_key:
            matches.append(
                {
                    "name": meta["name"],
                    "state": meta["name"],
                    "district": "",
                    "lat": meta["lat"],
                    "lon": meta["lon"],
                    "suggested_language": meta["local_language"],
                    "is_coastal": is_coastal_location(meta["lat"], meta["lon"], city_key=c_key),
                }
            )
        for area in meta.get("areas", []):
            if q_low in area["name"].lower():
                matches.append(
                    {
                        "name": f"{area['name']}, {meta['name']}",
                        "state": meta["name"],
                        "district": meta["name"],
                        "lat": area["lat"],
                        "lon": area["lon"],
                        "suggested_language": meta["local_language"],
                        "is_coastal": is_coastal_location(area["lat"], area["lon"], city_key=c_key),
                    }
                )
    return matches[:count]


async def geocode_india(
    query: str,
    count: int = 5,
    http_client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Search any Indian city, town, or district via Open-Meteo Geocoding API with fallback."""
    q = query.strip()
    if len(q) < 2:
        return []

    params = {"name": q, "count": count, "countryCode": "IN", "format": "json"}
    try:
        data = await _fetch_json(OPEN_METEO_GEOCODE_URL, params, http_client=http_client)
        formatted: list[dict[str, Any]] = []
        for item in data.get("results") or []:
            lat = round(float(item["latitude"]), 4)
            lon = round(float(item["longitude"]), 4)
            state = item.get("admin1") or ""
            name = item["name"]
            formatted.append(
                {
                    "name": name,
                    "state": state,
                    "district": item.get("admin2") or "",
                    "lat": lat,
                    "lon": lon,
                    "suggested_language": suggest_language_for_state(state, name.lower()),
                    "is_coastal": is_coastal_location(lat, lon, state, name.lower()),
                }
            )
        if formatted:
            return formatted
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning(
            "Open-Meteo geocoding failed (%s); using local India fallback.", type(exc).__name__
        )

    return _local_geocode_fallback(q, count)


async def reverse_geocode_india(
    lat: float,
    lon: float,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Resolve GPS coordinates to a readable Area, City in India via BigDataCloud."""
    nearest_key = nearest_featured_city(lat, lon)
    nearest_meta = CONSTANTS["cities"][nearest_key]

    try:
        params = {"latitude": lat, "longitude": lon, "localityLanguage": "en"}
        data = await _fetch_json(BIGDATACLOUD_REVERSE_URL, params, http_client=http_client)
        city = (data.get("city") or "").strip()
        locality = (data.get("locality") or "").strip()
        state = (data.get("principalSubdivision") or "").strip()

        if not locality or locality.lower() == city.lower():
            admins = data.get("localityInfo", {}).get("administrative") or []
            skip = {city.lower(), state.lower(), "india"}
            sub_names = [
                name_val
                for a in admins
                if (name_val := (a.get("name") or "").strip()) and name_val.lower() not in skip
            ]
            if sub_names:
                locality = sub_names[-1]

        resolved_city = city or locality or nearest_meta["name"]
        resolved_area = locality or resolved_city
        return {
            "area_name": resolved_area,
            "city": resolved_city,
            "state": state,
            "lat": round(float(lat), 4),
            "lon": round(float(lon), 4),
            "suggested_language": suggest_language_for_state(state, resolved_city.lower()),
            "is_coastal": is_coastal_location(
                lat, lon, state=state, city_key=resolved_city.lower()
            ),
        }
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning(
            "Reverse geocoding failed (%s); falling back near %s.",
            type(exc).__name__,
            nearest_meta["name"],
        )
        return {
            "area_name": f"Near {nearest_meta['name']}",
            "city": nearest_meta["name"],
            "state": "",
            "lat": round(float(lat), 4),
            "lon": round(float(lon), 4),
            "suggested_language": nearest_meta["local_language"],
            "is_coastal": is_coastal_location(lat, lon, city_key=nearest_key),
        }


def _build_replay_payload(
    fallback_city_key: str,
    reason: str,
    **meta: Any,
) -> dict[str, Any]:
    """Build a clearly labeled historical replay dataset for offline/stale degradation."""
    replay_city = FALLBACK_REPLAY["cities"][fallback_city_key]
    replay_date = FALLBACK_REPLAY["replay_date"]
    feat_meta = CONSTANTS["cities"][fallback_city_key]

    resolved_city_key = meta.get("city_key") or fallback_city_key
    resolved_display = meta.get("city_display") or feat_meta["name"]
    area_name = meta.get("area_name")
    state = meta.get("state")
    use_lat = float(meta["lat"]) if meta.get("lat") is not None else float(feat_meta["lat"])
    use_lon = float(meta["lon"]) if meta.get("lon") is not None else float(feat_meta["lon"])

    coastal = is_coastal_location(use_lat, use_lon, state=state, city_key=resolved_city_key)
    known_key = resolved_city_key if resolved_city_key in CONSTANTS["cities"] else None
    sugg_lang = suggest_language_for_state(state, known_key)
    met_note = build_meteorology_note(use_lat, coastal, city_key=known_key)
    loc_label = (
        f"{resolved_display} ({area_name})"
        if area_name and area_name != resolved_display
        else resolved_display
    )

    base_dt = datetime.strptime(replay_date, "%Y-%m-%d")
    multi_times = [
        (base_dt + timedelta(days=d)).strftime("%Y-%m-%d") + f"T{h:02d}:00"
        for d in range(5)
        for h in range(24)
    ]
    pm25_multi, _ = _sanitize_multiday_series(None, replay_city["pm2_5"])
    pm10_multi, _ = _sanitize_multiday_series(None, replay_city["pm10"])
    no2_multi, _ = _sanitize_multiday_series(None, replay_city["nitrogen_dioxide"])

    return {
        "city": resolved_city_key,
        "city_display": resolved_display,
        "area_name": area_name,
        "state": state,
        "lat": round(use_lat, 4),
        "lon": round(use_lon, 4),
        "is_coastal": coastal,
        "suggested_language": sugg_lang,
        "meteorology_note": met_note,
        "hourly_raw": {
            "time": [f"{replay_date}T{h:02d}:00" for h in range(24)],
            "pm2_5": list(replay_city["pm2_5"]),
            "pm10": list(replay_city["pm10"]),
            "nitrogen_dioxide": list(replay_city["nitrogen_dioxide"]),
            "us_aqi": list(replay_city["us_aqi"]),
            "temperature_2m": list(replay_city["temperature_2m"]),
            "relative_humidity_2m": list(replay_city["relative_humidity_2m"]),
            "wind_speed_10m": list(replay_city["wind_speed_10m"]),
            "boundary_layer_height": list(replay_city["boundary_layer_height"]),
        },
        "multiday_raw": {
            "time": multi_times,
            "pm2_5": pm25_multi,
            "pm10": pm10_multi,
            "nitrogen_dioxide": no2_multi,
        },
        "provenance": {
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
                f"({feat_meta['name']} proxy) for {loc_label} instead of live forecast."
            ),
        },
    }


async def _resolve_location(
    city_clean: str,
    lat: float | None,
    lon: float | None,
    area_name: str | None,
    state: str | None,
    http_client: httpx.AsyncClient | None,
) -> dict[str, Any]:
    """Resolve city/coordinates/metadata for any Indian location."""
    city_key = city_clean.lower()
    if city_key in CONSTANTS["cities"]:
        meta = CONSTANTS["cities"][city_key]
        use_lat = float(lat) if lat is not None else float(meta["lat"])
        use_lon = float(lon) if lon is not None else float(meta["lon"])
        city_display = meta["name"]
        fallback_key = city_key
        resolved_area = area_name or (
            f"GPS ({use_lat:.3f}, {use_lon:.3f})" if lat is not None and lon is not None else None
        )
    else:
        if lat is None or lon is None:
            geo = await geocode_india(city_clean, count=1, http_client=http_client)
            if not geo:
                raise ValueError(f"Could not find Indian location '{city_clean}'.")
            top = geo[0]
            use_lat = float(top["lat"])
            use_lon = float(top["lon"])
            city_display = top["name"]
            state = state or top["state"] or None
        else:
            use_lat = float(lat)
            use_lon = float(lon)
            city_display = area_name or city_clean.title()

        fallback_key = nearest_featured_city(use_lat, use_lon)
        resolved_area = area_name

    coastal = is_coastal_location(use_lat, use_lon, state=state, city_key=city_key)
    known_key = city_key if city_key in CONSTANTS["cities"] else None
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


def _assemble_live_payload(
    loc: dict[str, Any],
    aq_json: dict[str, Any],
    wx_json: dict[str, Any],
) -> dict[str, Any]:
    """Assemble and sanitize 24h + 5-day payload while tracking any fallback substitutions."""
    times = aq_json.get("time") or wx_json.get("time")
    if not times or len(times) < 24:
        raise ValueError("Incomplete 24-hour Open-Meteo response")

    multi_times = list(times[:120])
    if len(multi_times) < 120 and multi_times:
        start_dt = datetime.strptime(multi_times[0][:10], "%Y-%m-%d")
        multi_times = [
            (start_dt + timedelta(days=d)).strftime("%Y-%m-%d") + f"T{h:02d}:00"
            for d in range(5)
            for h in range(24)
        ]

    replay_city = FALLBACK_REPLAY["cities"][loc["fallback_key"]]
    pm25_24, c1 = _sanitize_series(aq_json.get("pm2_5"), replay_city["pm2_5"])
    pm10_24, c2 = _sanitize_series(aq_json.get("pm10"), replay_city["pm10"])
    no2_24, c3 = _sanitize_series(aq_json.get("nitrogen_dioxide"), replay_city["nitrogen_dioxide"])
    us_24, c4 = _sanitize_series(aq_json.get("us_aqi"), replay_city["us_aqi"], as_int=True)
    temp_24, c5 = _sanitize_series(wx_json.get("temperature_2m"), replay_city["temperature_2m"])
    rh_24, c6 = _sanitize_series(
        wx_json.get("relative_humidity_2m"), replay_city["relative_humidity_2m"]
    )
    wind_24, c7 = _sanitize_series(wx_json.get("wind_speed_10m"), replay_city["wind_speed_10m"])
    pblh_24, c8 = _sanitize_series(
        wx_json.get("boundary_layer_height"), replay_city["boundary_layer_height"]
    )

    pm25_120, m1 = _sanitize_multiday_series(aq_json.get("pm2_5"), replay_city["pm2_5"])
    pm10_120, m2 = _sanitize_multiday_series(aq_json.get("pm10"), replay_city["pm10"])
    no2_120, m3 = _sanitize_multiday_series(
        aq_json.get("nitrogen_dioxide"), replay_city["nitrogen_dioxide"]
    )
    fallback_slots = c1 + c2 + c3 + c4 + c5 + c6 + c7 + c8 + m1 + m2 + m3
    is_partial = fallback_slots > 0

    loc_parts = [p for p in (loc["area_name"], loc["city_display"], loc["state"]) if p]
    loc_desc = ", ".join(dict.fromkeys(loc_parts))
    base_note = (
        f"Pan-India Open-Meteo CAMS Global (~40 km, 3-hourly interpolated) + Weather Forecast "
        f"for {loc_desc} ({loc['lat']:.3f}, {loc['lon']:.3f}); not a doorstep CPCB monitor."
    )
    if is_partial:
        source_lbl = "Open-Meteo (CAMS Global + NWP, partial fallback)"
        data_type = "partial_model_forecast"
        spatial_note = (
            f"{base_note} Note: {fallback_slots} missing upstream slots used fallback fill."
        )
    else:
        source_lbl = "Open-Meteo (CAMS Global ~40 km + Weather Forecast)"
        data_type = "model_forecast"
        spatial_note = base_note

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
        "hourly_raw": {
            "time": times[:24],
            "pm2_5": pm25_24,
            "pm10": pm10_24,
            "nitrogen_dioxide": no2_24,
            "us_aqi": us_24,
            "temperature_2m": temp_24,
            "relative_humidity_2m": rh_24,
            "wind_speed_10m": wind_24,
            "boundary_layer_height": pblh_24,
        },
        "multiday_raw": {
            "time": multi_times,
            "pm2_5": pm25_120,
            "pm10": pm10_120,
            "nitrogen_dioxide": no2_120,
        },
        "provenance": {
            "source": source_lbl,
            "data_type": data_type,
            "retrieved_at": datetime.now(IST_TZ).isoformat(timespec="seconds"),
            "is_stale": False,
            "is_fallback_replay": False,
            "is_partial_fallback": is_partial,
            "fallback_slots": fallback_slots,
            "spatial_resolution": SPATIAL_RES_LIVE,
            "spatial_note": spatial_note,
        },
    }


def _apply_loc_metadata(payload: dict[str, Any], loc: dict[str, Any]) -> dict[str, Any]:
    """Attach caller location metadata onto a cached payload copy."""
    copy_payload = dict(payload)
    copy_payload["city"] = loc["city_key"]
    copy_payload["city_display"] = loc["city_display"]
    copy_payload["area_name"] = loc["area_name"]
    copy_payload["state"] = loc["state"]
    copy_payload["is_coastal"] = loc["coastal"]
    copy_payload["suggested_language"] = loc["suggested_language"]
    copy_payload["meteorology_note"] = loc["meteorology_note"]
    return copy_payload


async def fetch_city_atmospheric_data(
    city: str = "delhi",
    simulate_stale: bool = False,
    lat: float | None = None,
    lon: float | None = None,
    area_name: str | None = None,
    state: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Fetch 24h air quality and meteorology from Open-Meteo for any Indian coordinates."""
    city_clean = city.strip() or "delhi"
    loc = await _resolve_location(city_clean, lat, lon, area_name, state, http_client)

    if simulate_stale:
        return _build_replay_payload(
            loc["fallback_key"],
            "Stale/Offline simulation enabled",
            city_key=loc["city_key"],
            city_display=loc["city_display"],
            lat=loc["lat"],
            lon=loc["lon"],
            area_name=loc["area_name"],
            state=loc["state"],
        )

    cache_key = f"{loc['lat']:.3f}:{loc['lon']:.3f}"
    is_fresh, cached_entry = _get_cached_entry(cache_key)
    if is_fresh and cached_entry:
        return _apply_loc_metadata(cached_entry, loc)

    aq_params = {
        "latitude": loc["lat"],
        "longitude": loc["lon"],
        "hourly": "pm2_5,pm10,nitrogen_dioxide,us_aqi",
        "timezone": "Asia/Kolkata",
        "forecast_days": 5,
    }
    wx_params = {
        "latitude": loc["lat"],
        "longitude": loc["lon"],
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,boundary_layer_height",
        "timezone": "Asia/Kolkata",
        "forecast_days": 5,
    }

    try:
        aq_raw, wx_raw = await asyncio.gather(
            _fetch_json(OPEN_METEO_AQ_URL, aq_params, http_client=http_client),
            _fetch_json(OPEN_METEO_WX_URL, wx_params, http_client=http_client),
        )
        payload = _assemble_live_payload(loc, aq_raw.get("hourly", {}), wx_raw.get("hourly", {}))
        _prune_and_store_cache(cache_key, payload)
        return payload
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Open-Meteo upstream error (%s); serving fallback.", type(exc).__name__)
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
        return _build_replay_payload(
            loc["fallback_key"],
            f"Live Open-Meteo fetch unavailable ({type(exc).__name__})",
            city_key=loc["city_key"],
            city_display=loc["city_display"],
            lat=loc["lat"],
            lon=loc["lon"],
            area_name=loc["area_name"],
            state=loc["state"],
        )
