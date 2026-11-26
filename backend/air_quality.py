"""CPCB breakpoint NAQI, golden-window detection, meteorology regime, and 5-day outlook."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from geo_india import CONSTANTS, IST_TZ
from schemas import (
    AirSnapshotResponse,
    DailyAirOutlook,
    DataProvenance,
    GoldenWindow,
    HourlyAirPoint,
    LanguageCode,
)

ENGINE_PARAMS: dict[str, Any] = CONSTANTS["engine_params"]


def _interpolate_linear(c_lo: float, c_hi: float, i_lo: float, i_hi: float, val: float) -> int:
    """Linearly interpolate a sub-index within closed breakpoint bounds."""
    if c_hi <= c_lo:
        return int(round(i_hi))
    sub = ((i_hi - i_lo) / (c_hi - c_lo)) * (val - c_lo) + i_lo
    return int(round(sub))


def compute_cpcb_subindex(
    concentration: float, breakpoints: list[dict[str, Any]]
) -> tuple[int, str]:
    """Compute a single-pollutant CPCB sub-index using continuous interval handling."""
    c = max(0.0, float(concentration))
    last_bp = breakpoints[-1]
    if c >= float(last_bp["c_hi"]):
        return 500, str(last_bp["category"])

    prev_c_hi: float | None = None
    prev_i_hi: float | None = None
    for bp in breakpoints:
        c_lo, c_hi = float(bp["c_lo"]), float(bp["c_hi"])
        i_lo, i_hi = float(bp["i_lo"]), float(bp["i_hi"])
        if prev_c_hi is not None and prev_i_hi is not None and prev_c_hi < c < c_lo:
            return _interpolate_linear(prev_c_hi, c_lo, prev_i_hi, i_lo, c), str(bp["category"])
        if c_lo <= c <= c_hi:
            return _interpolate_linear(c_lo, c_hi, i_lo, i_hi, c), str(bp["category"])
        prev_c_hi, prev_i_hi = c_hi, i_hi

    return 500, str(last_bp["category"])


def compute_pm25_naqi(pm25: float) -> tuple[int, str]:
    """Compute CPCB PM2.5 breakpoint sub-index and category."""
    return compute_cpcb_subindex(pm25, CONSTANTS["cpcb_pm25_breakpoints"])


def category_for_naqi(naqi: int) -> str:
    """Return CPCB NAQI band category for an overall NAQI value."""
    for bp in CONSTANTS["cpcb_pm25_breakpoints"]:
        if naqi <= int(bp["i_hi"]):
            return str(bp["category"])
    return "Severe"


def compute_hourly_naqi(pm25: float, pm10: float, no2: float) -> dict[str, Any]:
    """Compute estimated hourly CPCB-breakpoint index across PM2.5, PM10, and NO2."""
    i_pm25, _ = compute_cpcb_subindex(pm25, CONSTANTS["cpcb_pm25_breakpoints"])
    i_pm10, _ = compute_cpcb_subindex(pm10, CONSTANTS["cpcb_pm10_breakpoints"])
    i_no2, _ = compute_cpcb_subindex(no2, CONSTANTS["cpcb_no2_breakpoints"])
    candidates = [("PM2.5", i_pm25), ("PM10", i_pm10), ("NO2", i_no2)]
    dominant_pollutant, cpcb_naqi = max(candidates, key=lambda item: item[1])
    return {
        "cpcb_naqi": cpcb_naqi,
        "cpcb_category": category_for_naqi(cpcb_naqi),
        "dominant_pollutant": dominant_pollutant,
        "pm25_subindex": i_pm25,
        "pm10_subindex": i_pm10,
        "no2_subindex": i_no2,
    }


def _find_best_daytime_pair(pm25_day: list[float]) -> tuple[int, float, float]:
    """Scan daytime pairs 07:00-18:00 and compute reduction vs 06:00-09:00 morning peak."""
    best_h, best_mean = 13, float("inf")
    for h in range(7, 18):
        pair_mean = (pm25_day[h] + pm25_day[h + 1]) / 2.0
        if pair_mean < best_mean:
            best_mean = pair_mean
            best_h = h
    morning_peak = max(pm25_day[6:10])
    reduction_pct = (
        round(((morning_peak - best_mean) / morning_peak) * 100.0, 1) if morning_peak > 0 else 0.0
    )
    return best_h, best_mean, reduction_pct


def _golden_window_advisory(
    window_label: str,
    stats: tuple[float, int, float, float],
    flags: tuple[bool, bool],
) -> str:
    """Build deterministic Golden Window summary copy without calling outdoor smog safe."""
    best_mean, mean_naqi, morning_peak, reduction_pct = stats
    is_clean_air_day, has_meaningful_window = flags
    if is_clean_air_day:
        return (
            "Air quality stays Good/Satisfactory across all 24 hours—normal outdoor routines are "
            "fine; keep kitchen exhaust habits active."
        )
    if has_meaningful_window:
        return (
            f"Lowest-exposure daytime window is {window_label} ({round(best_mean, 1)} ug/m3 PM2.5, "
            f"estimated hourly AQI {mean_naqi}), {reduction_pct:.0f}% lower than morning peak "
            f"({round(morning_peak, 1)} ug/m3) as daytime mixing lifts the boundary layer."
        )
    return (
        f"No strong daytime dip today: best 2h window ({window_label}, {round(best_mean, 1)} "
        f"ug/m3) is only {max(0.0, reduction_pct):.0f}% below morning peak "
        f"({round(morning_peak, 1)} ug/m3). Outdoor air stays uniformly elevated—"
        "shift strenuous exercise indoors."
    )


def find_golden_window(hourly_points: list[HourlyAirPoint]) -> GoldenWindow:
    """Scan daytime hours for lowest 2h PM2.5 window, verifying full 24h clean-air status."""
    min_red_pct = float(ENGINE_PARAMS["golden_window_min_reduction_pct"])
    pm25_series = [pt.pm2_5 for pt in hourly_points]
    best_h, best_mean, reduction_pct = _find_best_daytime_pair(pm25_series)
    morning_peak = max(pm25_series[6:10])
    mean_naqi = int(
        round((hourly_points[best_h].cpcb_naqi + hourly_points[best_h + 1].cpcb_naqi) / 2.0)
    )
    is_clean_air_day = max(pt.cpcb_naqi for pt in hourly_points) <= 100
    has_meaningful_window = is_clean_air_day or (reduction_pct >= min_red_pct)
    window_label = f"{best_h:02d}:00 - {best_h + 2:02d}:00"

    advisory = _golden_window_advisory(
        window_label,
        (best_mean, mean_naqi, morning_peak, reduction_pct),
        (is_clean_air_day, has_meaningful_window),
    )
    return GoldenWindow(
        start_hour=best_h,
        end_hour=best_h + 2,
        hours=[best_h, best_h + 1],
        window_label=window_label,
        mean_pm25=round(best_mean, 1),
        mean_naqi=mean_naqi,
        morning_peak_pm25=round(morning_peak, 1),
        reduction_pct=reduction_pct,
        has_meaningful_window=has_meaningful_window,
        is_clean_air_day=is_clean_air_day,
        advisory=advisory,
    )


def classify_meteorology_regime(hourly_points: list[HourlyAirPoint]) -> tuple[float, str]:
    """Compute morning inversion ceiling (m) and classify today's atmospheric dispersion."""
    morning_pblh = min(hourly_points[h].boundary_layer_height for h in range(5, 9))
    morning_wind = min(hourly_points[h].wind_speed_10m for h in range(5, 9))
    day_wind = max(hourly_points[h].wind_speed_10m for h in range(11, 17))

    if morning_pblh < 120.0 and morning_wind < 3.5:
        regime = "Severe Morning Inversion (Trapped Near Ground)"
    elif morning_pblh < 250.0:
        regime = "Moderate Nocturnal Inversion"
    elif day_wind >= 10.0:
        regime = "Active Daytime / Sea-Breeze Dispersion"
    else:
        regime = "Moderate Boundary-Layer Mixing"
    return round(morning_pblh, 1), regime


def _daily_outlook_tip(peak_naqi: int, has_meaningful: bool, best_label: str) -> str:
    """Select an honest daily guidance tip for one 24h outlook window."""
    if peak_naqi <= 100:
        return "Good day for outdoor errands and walks."
    if not has_meaningful:
        return (
            "Uniformly elevated air all day (<15% midday drop)—keep heavy workouts indoors "
            "and wear a fitted N95 for essential outdoor trips."
        )
    if peak_naqi <= 200:
        return f"Schedule flexible errands around {best_label}."
    if peak_naqi <= 300:
        return f"Poor air expected—limit trips to {best_label} with a fitted N95 mask."
    return "Heavy smog expected—keep strenuous exercise indoors and seal rooms."


def _summarize_single_day_outlook(
    day_idx: int,
    day_date: str,
    day_pm25: list[float],
    day_pm10: list[float],
    day_no2: list[float],
) -> DailyAirOutlook:
    """Compute one day's outlook applying the <15% flat-curve honesty check."""
    min_red_pct = float(ENGINE_PARAMS["golden_window_min_reduction_pct"])
    try:
        dt = datetime.strptime(day_date, "%Y-%m-%d")
        day_label = f"Today ({dt.strftime('%a')})" if day_idx == 0 else dt.strftime("%a, %b %d")
    except ValueError:
        day_label = "Today" if day_idx == 0 else f"Day {day_idx + 1}"

    peak_naqi = max(
        int(compute_hourly_naqi(day_pm25[h], day_pm10[h], day_no2[h])["cpcb_naqi"])
        for h in range(24)
    )
    best_h, best_mean, reduction_pct = _find_best_daytime_pair(day_pm25)
    has_meaningful = (peak_naqi <= 100) or (reduction_pct >= min_red_pct)
    best_label = f"{best_h:02d}:00 - {best_h + 2:02d}:00"

    return DailyAirOutlook(
        date=day_date,
        day_label=day_label,
        peak_pm25=round(max(day_pm25), 1),
        peak_naqi=peak_naqi,
        peak_category=category_for_naqi(peak_naqi),
        best_window_label=best_label,
        best_window_pm25=round(best_mean, 1),
        reduction_pct=reduction_pct,
        has_meaningful_window=has_meaningful,
        tip=_daily_outlook_tip(peak_naqi, has_meaningful, best_label),
    )


def build_daily_outlook(raw_payload: dict[str, Any]) -> list[DailyAirOutlook]:
    """Compute 5-day future air outlook summaries from 120-hour multiday arrays."""
    multi = raw_payload.get("multiday_raw")
    if not multi or len(multi.get("pm2_5", [])) < 24:
        return []

    times = multi["time"]
    pm25_all, pm10_all, no2_all = multi["pm2_5"], multi["pm10"], multi["nitrogen_dioxide"]
    total_days = min(5, len(pm25_all) // 24)
    return [
        _summarize_single_day_outlook(
            d,
            times[d * 24][:10],
            [float(x) for x in pm25_all[d * 24 : (d + 1) * 24]],
            [float(x) for x in pm10_all[d * 24 : (d + 1) * 24]],
            [float(x) for x in no2_all[d * 24 : (d + 1) * 24]],
        )
        for d in range(total_days)
    ]


def _build_hourly_point(h: int, hr: dict[str, Any]) -> HourlyAirPoint:
    """Build one HourlyAirPoint record from hourly atmospheric arrays."""
    pm25 = float(hr["pm2_5"][h])
    pm10 = float(hr["pm10"][h])
    no2 = float(hr["nitrogen_dioxide"][h])
    naqi_info = compute_hourly_naqi(pm25, pm10, no2)
    return HourlyAirPoint(
        hour=h,
        time_label=f"{h:02d}:00",
        pm2_5=round(pm25, 1),
        pm10=round(pm10, 1),
        nitrogen_dioxide=round(no2, 1),
        us_aqi=hr["us_aqi"][h],
        cpcb_naqi=naqi_info["cpcb_naqi"],
        cpcb_category=naqi_info["cpcb_category"],
        dominant_pollutant=naqi_info["dominant_pollutant"],
        pm25_subindex=naqi_info["pm25_subindex"],
        pm10_subindex=naqi_info["pm10_subindex"],
        no2_subindex=naqi_info["no2_subindex"],
        temperature_2m=float(hr["temperature_2m"][h]),
        relative_humidity_2m=float(hr["relative_humidity_2m"][h]),
        wind_speed_10m=float(hr["wind_speed_10m"][h]),
        boundary_layer_height=float(hr["boundary_layer_height"][h]),
    )


def _resolve_snapshot_meta(
    raw_payload: dict[str, Any], city_meta: dict[str, Any]
) -> tuple[LanguageCode, str, str]:
    """Resolve suggested language, display city name, and meteorology note."""
    city_key = str(raw_payload["city"])
    raw_lang = str(raw_payload.get("suggested_language") or city_meta.get("local_language") or "hi")
    supported_langs = {"en", "hinglish", "hi", "mr", "kn", "bn", "ta", "te"}
    sugg_lang: LanguageCode = cast(LanguageCode, raw_lang if raw_lang in supported_langs else "hi")
    city_name = str(raw_payload.get("city_display") or city_meta.get("name") or city_key.title())
    met_note = str(raw_payload.get("meteorology_note") or city_meta.get("meteorology_note", ""))
    return sugg_lang, city_name, met_note


def build_air_snapshot(
    raw_payload: dict[str, Any], current_hour: int | None = None
) -> AirSnapshotResponse:
    """Convert fetched hourly arrays into a CPCB-breakpoint AirSnapshotResponse."""
    city_key = raw_payload["city"]
    city_meta = CONSTANTS["cities"].get(city_key, {})
    hourly_points = [_build_hourly_point(h, raw_payload["hourly_raw"]) for h in range(24)]
    resolved_hour = current_hour if current_hour is not None else datetime.now(IST_TZ).hour
    hour_idx = max(0, min(23, resolved_hour))
    current_pt = hourly_points[hour_idx]
    inversion_m, regime = classify_meteorology_regime(hourly_points)
    sugg_lang, city_name, met_note = _resolve_snapshot_meta(raw_payload, city_meta)

    return AirSnapshotResponse(
        city=city_key,
        city_name=city_name,
        area_name=raw_payload.get("area_name"),
        state=raw_payload.get("state"),
        lat=raw_payload.get("lat"),
        lon=raw_payload.get("lon"),
        is_coastal=bool(raw_payload.get("is_coastal", False)),
        suggested_language=sugg_lang,
        meteorology_note=met_note,
        current_hour=hour_idx,
        current_pm25=current_pt.pm2_5,
        current_naqi=current_pt.cpcb_naqi,
        current_category=current_pt.cpcb_category,
        dominant_pollutant=current_pt.dominant_pollutant,
        morning_inversion_ceiling_m=inversion_m,
        meteorology_regime=regime,
        golden_window=find_golden_window(hourly_points),
        hourly=hourly_points,
        daily_outlook=build_daily_outlook(raw_payload),
        provenance=DataProvenance(**raw_payload["provenance"]),
    )
