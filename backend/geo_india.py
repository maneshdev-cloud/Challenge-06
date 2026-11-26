"""Indian city catalog, JSON knowledge-base loaders, coastal flags, and meteorology notes."""

from __future__ import annotations

import json
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
IST_TZ = timezone(timedelta(hours=5, minutes=30))


def load_json_data(filename: str) -> Any:
    """Load a JSON file from backend/data/."""
    with open(DATA_DIR / filename, encoding="utf-8") as fh:
        return json.load(fh)


CONSTANTS: dict[str, Any] = load_json_data("constants.json")
FALLBACK_REPLAY: dict[str, Any] = load_json_data("fallback_replay.json")
PRESETS: list[dict[str, Any]] = load_json_data("presets.json")

STATE_LANGUAGE_MAP = {
    "maharashtra": "mr",
    "goa": "mr",
    "karnataka": "kn",
    "kerala": "en",
    "west bengal": "bn",
    "tripura": "bn",
    "assam": "en",
    "odisha": "en",
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
    "gujarat": "hi",
    "punjab": "hi",
}

COASTAL_STATES = {
    "goa",
    "kerala",
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
    "pondicherry",
    "kozhikode",
    "puri",
    "navi mumbai",
    "thoothukudi",
    "tuticorin",
    "nagapattinam",
    "rameswaram",
    "kanyakumari",
    "kakinada",
    "paradip",
    "udupi",
    "karwar",
    "port blair",
    "kavaratti",
    "kollam",
    "alappuzha",
    "kannur",
    "gopalpur",
}


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
    """Classify coastal vs. inland meteorology from city, island territory, or coastline band."""
    if city_key and city_key.strip().lower() in COASTAL_CITIES:
        return True
    if state and state.strip().lower() in COASTAL_STATES:
        return True
    gujarat_coast = 20.5 < lat <= 22.8 and 68.5 <= lon <= 72.9
    konkan_coast = 14.9 <= lat <= 20.5 and 72.6 <= lon <= 73.4
    karavali_malabar = 8.0 <= lat < 14.9 and 73.8 <= lon <= (74.25 + (14.9 - lat) * 0.48)
    west_coast = gujarat_coast or konkan_coast or karavali_malabar
    bay_south = 8.0 <= lat <= 13.5 and (79.1 + max(0.0, lat - 9.2) * 0.18) <= lon <= 81.0
    bay_north = 13.5 < lat <= 22.0 and (80.0 + (lat - 13.5) * 0.9) <= lon <= 88.8
    return west_coast or bay_south or bay_north


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


def local_geocode_fallback(query: str, count: int) -> list[dict[str, Any]]:
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


__all__ = [
    "COASTAL_CITIES",
    "COASTAL_STATES",
    "CONSTANTS",
    "DATA_DIR",
    "FALLBACK_REPLAY",
    "IST_TZ",
    "PRESETS",
    "STATE_LANGUAGE_MAP",
    "build_meteorology_note",
    "is_coastal_location",
    "load_json_data",
    "local_geocode_fallback",
    "nearest_featured_city",
    "suggest_language_for_state",
]
