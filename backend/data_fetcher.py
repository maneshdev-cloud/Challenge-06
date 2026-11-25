"""Live Open-Meteo air, meteorology, and Pan-India geocoding fetcher with TTL cache and fallback."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

DATA_DIR = Path(__file__).resolve().parent / "data"
IST_TZ = timezone(timedelta(hours=5, minutes=30))
CACHE_TTL_SECONDS = 900  # 15 minutes

OPEN_METEO_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_WX_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
BIGDATACLOUD_REVERSE_URL = "https://api.bigdatacloud.net/data/reverse-geocode-client"


def load_json_data(filename: str) -> Any:
    """Load a JSON file from backend/data/."""
    with open(DATA_DIR / filename, "r", encoding="utf-8") as fh:
        return json.load(fh)


CONSTANTS: dict[str, Any] = load_json_data("constants.json")
FALLBACK_REPLAY: dict[str, Any] = load_json_data("fallback_replay.json")
PRESETS: list[dict[str, Any]] = load_json_data("presets.json")

_TTL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

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


def suggest_language_for_state(state: str | None, city_key: str | None = None) -> str:
    """Suggest a local Indian language from state name or featured city key."""
    if city_key and city_key in CONSTANTS["cities"]:
        return CONSTANTS["cities"][city_key]["local_language"]
    if state:
        s_low = state.strip().lower()
        for key, lang in STATE_LANGUAGE_MAP.items():
            if key in s_low:
                return lang
    return "hi"


def is_coastal_location(lat: float, lon: float, state: str | None = None, city_key: str | None = None) -> bool:
    """Classify coastal vs. inland meteorology from city/state or shoreline coordinates."""
    if city_key:
        c_low = city_key.strip().lower()
        if c_low in COASTAL_CITIES:
            return True
    if state and state.strip().lower() in COASTAL_STATES:
        return True
    # Approximate peninsular coastline band (West coast Konkan/Malabar & East coast Coromandel/Andhra/Odisha)
    west_coast = 8.0 <= lat <= 22.8 and 68.5 <= lon <= 73.5
    east_coast = 8.0 <= lat <= 21.8 and 79.6 <= lon <= 87.5 and lat <= (13.0 + (lon - 79.8) * 1.4)
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


def build_meteorology_note(lat: float, state: str | None, coastal: bool, city_key: str | None = None) -> str:
    """Generate dynamic coastal vs. northern/inland Indian atmospheric dispersion context."""
    if city_key and city_key in CONSTANTS["cities"]:
        return CONSTANTS["cities"][city_key]["meteorology_note"]
    if coastal:
        return (
            "Coastal Indian profile: sea-breeze transitions often improve daytime dispersion, "
            "while calm mornings and roadside traffic corridors still create localized PM2.5/NO2 peaks."
        )
    if lat >= 23.5:
        return (
            "Northern / Indo-Gangetic inland profile: winter nocturnal thermal inversions and low winds "
            "trap PM2.5 near ground level until daytime warming lifts the boundary layer."
        )
    return (
        "Inland plateau/basin profile: overnight cooling near the surface traps morning emissions "
        "before midday convection widens the boundary layer."
    )


def _sanitize_series(values: list[Any] | None, fallback: list[float], as_int: bool = False) -> list[Any]:
    """Fill missing/None hourly values safely without crashing on sparse API slots."""
    if not values or len(values) < 24:
        return list(fallback)
    cleaned: list[Any] = []
    for idx in range(24):
        raw = values[idx]
        if raw is None:
            raw = cleaned[-1] if cleaned else fallback[idx]
        val = int(round(float(raw))) if as_int else round(float(raw), 1)
        cleaned.append(val)
    return cleaned


def _sanitize_multiday_series(
    values: list[Any] | None,
    fallback_day: list[float],
    days: int = 5,
    as_int: bool = False,
) -> list[Any]:
    """Sanitize a multi-day (5x24=120h) hourly series, padding missing trailing days safely."""
    total = days * 24
    if not values or len(values) < 24:
        out: list[Any] = []
        for d in range(days):
            scale = 1.0 if d == 0 else (0.94 + (d % 3) * 0.05)
            for v in fallback_day:
                val = int(round(float(v) * scale)) if as_int else round(float(v) * scale, 1)
                out.append(val)
        return out

    cleaned: list[Any] = []
    for idx in range(total):
        raw = values[idx] if idx < len(values) else None
        if raw is None:
            raw = cleaned[idx - 24] if idx >= 24 else (cleaned[-1] if cleaned else fallback_day[idx % 24])
        val = int(round(float(raw))) if as_int else round(float(raw), 1)
        cleaned.append(val)
    return cleaned


async def geocode_india(
    query: str,
    count: int = 5,
    http_client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Search any Indian city, town, or district via Open-Meteo Geocoding API with local fallback."""
    q = query.strip()
    if len(q) < 2:
        return []

    params = {
        "name": q,
        "count": count,
        "countryCode": "IN",
        "format": "json",
    }
    try:
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=5.0)
        try:
            resp = await client.get(OPEN_METEO_GEOCODE_URL, params=params)
        finally:
            if owns_client:
                await client.aclose()

        resp.raise_for_status()
        raw_results = resp.json().get("results") or []
        formatted: list[dict[str, Any]] = []
        for item in raw_results:
            lat = round(float(item["latitude"]), 4)
            lon = round(float(item["longitude"]), 4)
            state = item.get("admin1") or ""
            district = item.get("admin2") or ""
            name = item["name"]
            formatted.append(
                {
                    "name": name,
                    "state": state,
                    "district": district,
                    "lat": lat,
                    "lon": lon,
                    "suggested_language": suggest_language_for_state(state, name.lower()),
                    "is_coastal": is_coastal_location(lat, lon, state, name.lower()),
                }
            )
        if formatted:
            return formatted
    except Exception:
        pass

    # Local offline fallback matching featured cities & preset neighborhoods
    q_low = q.lower()
    local_matches: list[dict[str, Any]] = []
    for c_key, meta in CONSTANTS["cities"].items():
        if q_low in meta["name"].lower() or q_low in c_key:
            local_matches.append(
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
                local_matches.append(
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
    return local_matches[:count]


async def reverse_geocode_india(
    lat: float,
    lon: float,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Resolve GPS coordinates to a readable Area, City in India via BigDataCloud (with local fallback)."""
    nearest_key = nearest_featured_city(lat, lon)
    nearest_meta = CONSTANTS["cities"][nearest_key]
    fallback_area = nearest_meta.get("areas", [{}])[0].get("name") or nearest_meta["name"]

    try:
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=5.0)
        try:
            resp = await client.get(
                BIGDATACLOUD_REVERSE_URL,
                params={"latitude": lat, "longitude": lon, "localityLanguage": "en"},
            )
        finally:
            if owns_client:
                await client.aclose()

        resp.raise_for_status()
        data = resp.json()
        city = (data.get("city") or "").strip()
        locality = (data.get("locality") or "").strip()
        state = (data.get("principalSubdivision") or "").strip()

        # Prefer deeper administrative neighbourhood when BigDataCloud returns locality == city
        if not locality or locality.lower() == city.lower():
            admins = data.get("localityInfo", {}).get("administrative") or []
            sub_names = [
                (a.get("name") or "").strip()
                for a in admins
                if (a.get("name") or "").strip() and (a.get("name") or "").strip().lower() not in {city.lower(), state.lower(), "india"}
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
            "is_coastal": is_coastal_location(lat, lon, state=state, city_key=resolved_city.lower()),
        }
    except Exception:
        return {
            "area_name": fallback_area,
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
    city_key: str | None = None,
    city_display: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    area_name: str | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    """Build a clearly labeled historical replay dataset for offline/stale degradation."""
    replay_city = FALLBACK_REPLAY["cities"][fallback_city_key]
    replay_date = FALLBACK_REPLAY["replay_date"]
    now_ist = datetime.now(IST_TZ).isoformat(timespec="seconds")
    feat_meta = CONSTANTS["cities"][fallback_city_key]

    resolved_city_key = city_key or fallback_city_key
    resolved_display = city_display or feat_meta["name"]
    use_lat = float(lat) if lat is not None else float(feat_meta["lat"])
    use_lon = float(lon) if lon is not None else float(feat_meta["lon"])
    coastal = is_coastal_location(use_lat, use_lon, state=state, city_key=resolved_city_key)
    sugg_lang = suggest_language_for_state(state, resolved_city_key if resolved_city_key in CONSTANTS["cities"] else None)
    met_note = build_meteorology_note(
        use_lat, state, coastal, city_key=resolved_city_key if resolved_city_key in CONSTANTS["cities"] else None
    )
    loc_label = f"{resolved_display} ({area_name})" if area_name and area_name != resolved_display else resolved_display
    base_dt = datetime.strptime(replay_date, "%Y-%m-%d")
    multi_times = [
        (base_dt + timedelta(days=d)).strftime("%Y-%m-%d") + f"T{h:02d}:00"
        for d in range(5)
        for h in range(24)
    ]

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
            "pm2_5": _sanitize_multiday_series(None, replay_city["pm2_5"]),
            "pm10": _sanitize_multiday_series(None, replay_city["pm10"]),
            "nitrogen_dioxide": _sanitize_multiday_series(None, replay_city["nitrogen_dioxide"]),
        },
        "provenance": {
            "source": f"PRANA-AI Historical Winter Replay ({replay_date})",
            "data_type": "historical_replay",
            "retrieved_at": now_ist,
            "is_stale": True,
            "is_fallback_replay": True,
            "spatial_note": (
                f"{reason}. Showing nearest regional historical winter replay ({feat_meta['name']} proxy) "
                f"for {loc_label} instead of live atmospheric forecast."
            ),
        },
    }


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
    city_key = city_clean.lower()

    if city_key in CONSTANTS["cities"]:
        city_meta = CONSTANTS["cities"][city_key]
        use_lat = float(lat) if lat is not None else float(city_meta["lat"])
        use_lon = float(lon) if lon is not None else float(city_meta["lon"])
        city_display = city_meta["name"]
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
    sugg_lang = suggest_language_for_state(state, city_key if city_key in CONSTANTS["cities"] else None)
    met_note = build_meteorology_note(
        use_lat, state, coastal, city_key=city_key if city_key in CONSTANTS["cities"] else None
    )

    if simulate_stale:
        return _build_replay_payload(
            fallback_key,
            "Stale/Offline simulation enabled",
            city_key=city_key,
            city_display=city_display,
            lat=use_lat,
            lon=use_lon,
            area_name=resolved_area,
            state=state,
        )

    cache_key = f"{use_lat:.3f}:{use_lon:.3f}"
    now_mono = time.monotonic()
    cached = _TTL_CACHE.get(cache_key)
    if cached and (now_mono - cached[0]) < CACHE_TTL_SECONDS:
        cached_payload = dict(cached[1])
        cached_payload["city"] = city_key
        cached_payload["city_display"] = city_display
        cached_payload["area_name"] = resolved_area
        cached_payload["state"] = state
        cached_payload["is_coastal"] = coastal
        cached_payload["suggested_language"] = sugg_lang
        cached_payload["meteorology_note"] = met_note
        return cached_payload

    aq_params = {
        "latitude": use_lat,
        "longitude": use_lon,
        "hourly": "pm2_5,pm10,nitrogen_dioxide,us_aqi",
        "timezone": "Asia/Kolkata",
        "forecast_days": 5,
    }
    wx_params = {
        "latitude": use_lat,
        "longitude": use_lon,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,boundary_layer_height",
        "timezone": "Asia/Kolkata",
        "forecast_days": 5,
    }

    replay_city = FALLBACK_REPLAY["cities"][fallback_key]
    try:
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.5))
        try:
            aq_resp, wx_resp = await asyncio.gather(
                client.get(OPEN_METEO_AQ_URL, params=aq_params),
                client.get(OPEN_METEO_WX_URL, params=wx_params),
            )
        finally:
            if owns_client:
                await client.aclose()

        aq_resp.raise_for_status()
        wx_resp.raise_for_status()
        aq_json = aq_resp.json().get("hourly", {})
        wx_json = wx_resp.json().get("hourly", {})

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

        loc_parts = [p for p in (resolved_area, city_display, state) if p]
        loc_desc = ", ".join(dict.fromkeys(loc_parts))
        payload = {
            "city": city_key,
            "city_display": city_display,
            "area_name": resolved_area,
            "state": state,
            "lat": round(use_lat, 4),
            "lon": round(use_lon, 4),
            "is_coastal": coastal,
            "suggested_language": sugg_lang,
            "meteorology_note": met_note,
            "hourly_raw": {
                "time": times[:24],
                "pm2_5": _sanitize_series(aq_json.get("pm2_5"), replay_city["pm2_5"]),
                "pm10": _sanitize_series(aq_json.get("pm10"), replay_city["pm10"]),
                "nitrogen_dioxide": _sanitize_series(aq_json.get("nitrogen_dioxide"), replay_city["nitrogen_dioxide"]),
                "us_aqi": _sanitize_series(aq_json.get("us_aqi"), replay_city["us_aqi"], as_int=True),
                "temperature_2m": _sanitize_series(wx_json.get("temperature_2m"), replay_city["temperature_2m"]),
                "relative_humidity_2m": _sanitize_series(
                    wx_json.get("relative_humidity_2m"), replay_city["relative_humidity_2m"]
                ),
                "wind_speed_10m": _sanitize_series(wx_json.get("wind_speed_10m"), replay_city["wind_speed_10m"]),
                "boundary_layer_height": _sanitize_series(
                    wx_json.get("boundary_layer_height"), replay_city["boundary_layer_height"]
                ),
            },
            "multiday_raw": {
                "time": multi_times,
                "pm2_5": _sanitize_multiday_series(aq_json.get("pm2_5"), replay_city["pm2_5"]),
                "pm10": _sanitize_multiday_series(aq_json.get("pm10"), replay_city["pm10"]),
                "nitrogen_dioxide": _sanitize_multiday_series(
                    aq_json.get("nitrogen_dioxide"), replay_city["nitrogen_dioxide"]
                ),
            },
            "provenance": {
                "source": "Open-Meteo (ECMWF CAMS + ERA5)",
                "data_type": "model_forecast",
                "retrieved_at": datetime.now(IST_TZ).isoformat(timespec="seconds"),
                "is_stale": False,
                "is_fallback_replay": False,
                "spatial_note": (
                    f"Pan-India Gridded Forecast (~11 km) for {loc_desc} ({use_lat:.3f}, {use_lon:.3f}); "
                    "not a street-level or indoor sensor."
                ),
            },
        }
        _TTL_CACHE[cache_key] = (now_mono, payload)
        return payload
    except Exception as exc:
        if cached:
            stale_payload = dict(cached[1])
            stale_payload["provenance"] = {
                **stale_payload["provenance"],
                "is_stale": True,
                "spatial_note": f"Live API unavailable ({type(exc).__name__}); serving last cached forecast.",
            }
            return stale_payload
        return _build_replay_payload(
            fallback_key,
            f"Live Open-Meteo fetch unavailable ({type(exc).__name__})",
            city_key=city_key,
            city_display=city_display,
            lat=use_lat,
            lon=use_lon,
            area_name=resolved_area,
            state=state,
        )
