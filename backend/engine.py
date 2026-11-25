"""Deterministic CPCB breakpoints, dosimetry, sanctuary, and ARAI engine for PRANA-AI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from data_fetcher import CONSTANTS, IST_TZ
from schemas import (
    AirSnapshotResponse,
    BreatheLessLedger,
    DailyAirOutlook,
    DataProvenance,
    EmitLessLedger,
    EvidenceBundle,
    GoldenWindow,
    GroundedMetrics,
    HourlyAirPoint,
    LanguageCode,
    MaskType,
    PlanRequest,
    ProfileRiskSummary,
    RoomScore,
    RoomSpec,
    RoutineItemResult,
    SanctuaryPlan,
    UserCategory,
    WindowVentilationAdvice,
)

ENGINE_PARAMS: dict[str, Any] = CONSTANTS["engine_params"]

DEFAULT_ROOMS = [
    RoomSpec(
        name="Front Living Room",
        ext_windows=2,
        road_facing=True,
        kitchen_adjacent=True,
        large_volume=True,
    ),
    RoomSpec(
        name="Inner Bedroom",
        ext_windows=1,
        road_facing=False,
        kitchen_adjacent=False,
        large_volume=False,
    ),
]

PRIMARY_FLEX_LEVELS = {"elderly_walk", "child_play", "running_or_outdoor_work", "brisk_walk"}

PROFILE_DESCRIPTORS: dict[UserCategory, dict[str, Any]] = {
    "delivery_riders": {
        "label": "Delivery Riders (Road-Exhaust Shift)",
        "tier": "Road Plume 1.55x + High Intake",
        "severity_labels": (
            "Severe Road Exposure",
            "High Road Exposure",
            "Elevated Route Vigilance",
        ),
        "badges": (
            "High Exposure Alert (NAQI > 100)",
            "Rider Warning (NAQI > 100)",
            "Road Plume Active (1.55x)",
        ),
    },
    "seniors": {
        "label": "Seniors (High Lung Sensitivity)",
        "tier": "Sensitive Airways (Threshold NAQI > 100)",
        "severity_labels": (
            "High Cardiorespiratory Risk",
            "Elevated Senior Risk",
            "Low Senior Risk",
        ),
        "badges": (
            "Senior Health Alert (NAQI > 100)",
            "Senior Warning (NAQI > 100)",
            "Senior-Safe Threshold (<100)",
        ),
    },
    "students_kids": {
        "label": "Students & Kids (Developing Lungs)",
        "tier": "Higher Uptake/kg (Threshold NAQI > 100)",
        "severity_labels": ("High Youth Exposure", "Elevated Kid Risk", "Low Youth Risk"),
        "badges": (
            "School / Sports Alert (NAQI > 100)",
            "Kids / Play Warning (NAQI > 100)",
            "School-Play Friendly (<100)",
        ),
    },
    "adults_commuters": {
        "label": "Adults & Daily Commuters",
        "tier": "Standard CPCB Band (Threshold NAQI > 150)",
        "severity_labels": ("High Commuter Strain", "Elevated Commuter Risk", "Low Adult Risk"),
        "badges": (
            "Outdoor Warning (NAQI > 150)",
            "Advisory Active (NAQI > 150)",
            "Standard Threshold (<=150)",
        ),
    },
}


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
        c_lo = float(bp["c_lo"])
        c_hi = float(bp["c_hi"])
        i_lo = float(bp["i_lo"])
        i_hi = float(bp["i_hi"])

        if prev_c_hi is not None and prev_i_hi is not None and prev_c_hi < c < c_lo:
            sub = _interpolate_linear(prev_c_hi, c_lo, prev_i_hi, i_lo, c)
            return sub, str(bp["category"])

        if c_lo <= c <= c_hi:
            return _interpolate_linear(c_lo, c_hi, i_lo, i_hi, c), str(bp["category"])

        prev_c_hi = c_hi
        prev_i_hi = i_hi

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


def _find_best_daytime_pair(pm25_day: list[float]) -> tuple[int, float]:
    """Scan daytime sliding pairs 07:00-18:00 for minimum 2-hour mean PM2.5."""
    best_h = 13
    best_mean = float("inf")
    for h in range(7, 18):
        pair_mean = (pm25_day[h] + pm25_day[h + 1]) / 2.0
        if pair_mean < best_mean:
            best_mean = pair_mean
            best_h = h
    return best_h, best_mean


def find_golden_window(hourly_points: list[HourlyAirPoint]) -> GoldenWindow:
    """Scan daytime hours (07:00-19:00) for lowest 2h PM2.5 window with <15% honesty rule."""
    min_red_pct = float(ENGINE_PARAMS["golden_window_min_reduction_pct"])
    pm25_series = [pt.pm2_5 for pt in hourly_points]
    best_h, best_mean = _find_best_daytime_pair(pm25_series)

    morning_peak = max(hourly_points[h].pm2_5 for h in range(6, 10))
    morning_peak_naqi = max(hourly_points[h].cpcb_naqi for h in range(6, 10))
    reduction_pct = (
        round(((morning_peak - best_mean) / morning_peak) * 100.0, 1) if morning_peak > 0 else 0.0
    )

    mean_naqi = int(
        round((hourly_points[best_h].cpcb_naqi + hourly_points[best_h + 1].cpcb_naqi) / 2.0)
    )
    is_clean_air_day = mean_naqi <= 100 and morning_peak_naqi <= 100
    has_meaningful_window = is_clean_air_day or (reduction_pct >= min_red_pct)
    window_label = f"{best_h:02d}:00 - {best_h + 2:02d}:00"

    if is_clean_air_day:
        advisory = (
            "Air quality is Good/Satisfactory today—normal outdoor routines are fine; "
            "still follow kitchen exhaust habits."
        )
    elif has_meaningful_window:
        advisory = (
            f"Lowest-exposure daytime window is {window_label} ({round(best_mean, 1)} ug/m3 PM2.5, "
            f"estimated hourly AQI {mean_naqi}), {reduction_pct:.0f}% lower than morning peak "
            f"({round(morning_peak, 1)} ug/m3) as daytime mixing lifts the boundary layer."
        )
    else:
        advisory = (
            f"No strong daytime dip today: best 2h window ({window_label}, {round(best_mean, 1)} "
            f"ug/m3) is only {max(0.0, reduction_pct):.0f}% below morning peak "
            f"({round(morning_peak, 1)} ug/m3). Outdoor air stays uniformly elevated—"
            "shift strenuous exercise indoors."
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

    day_naqis = [
        int(compute_hourly_naqi(day_pm25[h], day_pm10[h], day_no2[h])["cpcb_naqi"])
        for h in range(24)
    ]
    peak_pm25 = round(max(day_pm25), 1)
    peak_naqi = max(day_naqis)
    peak_category = category_for_naqi(peak_naqi)
    morning_peak = max(day_pm25[h] for h in range(6, 10))
    best_h, best_mean = _find_best_daytime_pair(day_pm25)
    reduction_pct = (
        round(((morning_peak - best_mean) / morning_peak) * 100.0, 1) if morning_peak > 0 else 0.0
    )
    has_meaningful = (peak_naqi <= 100) or (reduction_pct >= min_red_pct)
    best_label = f"{best_h:02d}:00 - {best_h + 2:02d}:00"

    if peak_naqi <= 100:
        tip = "Good day for outdoor errands and walks."
    elif not has_meaningful:
        tip = (
            "Uniformly elevated air all day (<15% midday drop)—keep heavy workouts indoors "
            "and wear a fitted N95 for essential outdoor trips."
        )
    elif peak_naqi <= 200:
        tip = f"Schedule flexible errands around {best_h:02d}:00-{best_h + 2:02d}:00."
    elif peak_naqi <= 300:
        tip = (
            f"Poor air expected—limit trips to {best_h:02d}:00-{best_h + 2:02d}:00 "
            "with a fitted N95 mask."
        )
    else:
        tip = "Heavy smog expected—keep strenuous exercise indoors and seal rooms."

    return DailyAirOutlook(
        date=day_date,
        day_label=day_label,
        peak_pm25=peak_pm25,
        peak_naqi=peak_naqi,
        peak_category=peak_category,
        best_window_label=best_label,
        best_window_pm25=round(best_mean, 1),
        reduction_pct=reduction_pct,
        has_meaningful_window=has_meaningful,
        tip=tip,
    )


def build_daily_outlook(raw_payload: dict[str, Any]) -> list[DailyAirOutlook]:
    """Compute 5-day future air outlook summaries from 120-hour multiday arrays."""
    multi = raw_payload.get("multiday_raw")
    if not multi or len(multi.get("pm2_5", [])) < 24:
        return []

    times = multi["time"]
    pm25_all = multi["pm2_5"]
    pm10_all = multi["pm10"]
    no2_all = multi["nitrogen_dioxide"]
    total_days = min(5, len(pm25_all) // 24)

    outlooks: list[DailyAirOutlook] = []
    for d in range(total_days):
        start, end = d * 24, (d + 1) * 24
        outlooks.append(
            _summarize_single_day_outlook(
                d,
                times[start][:10],
                [float(x) for x in pm25_all[start:end]],
                [float(x) for x in pm10_all[start:end]],
                [float(x) for x in no2_all[start:end]],
            )
        )
    return outlooks


def build_air_snapshot(
    raw_payload: dict[str, Any], current_hour: int | None = None
) -> AirSnapshotResponse:
    """Convert fetched hourly arrays into a CPCB-breakpoint AirSnapshotResponse."""
    city_key = raw_payload["city"]
    city_meta = CONSTANTS["cities"].get(city_key, {})
    hr = raw_payload["hourly_raw"]

    hourly_points: list[HourlyAirPoint] = []
    for h in range(24):
        pm25 = float(hr["pm2_5"][h])
        pm10 = float(hr["pm10"][h])
        no2 = float(hr["nitrogen_dioxide"][h])
        naqi_info = compute_hourly_naqi(pm25, pm10, no2)
        hourly_points.append(
            HourlyAirPoint(
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
        )

    default_hr = datetime.now(IST_TZ).hour
    hour_idx = max(0, min(23, current_hour if current_hour is not None else default_hr))
    current_pt = hourly_points[hour_idx]
    golden_window = find_golden_window(hourly_points)
    inversion_m, regime = classify_meteorology_regime(hourly_points)

    city_name = str(raw_payload.get("city_display") or city_meta.get("name") or city_key.title())
    raw_lang = str(raw_payload.get("suggested_language") or city_meta.get("local_language") or "hi")
    supported_langs = {"en", "hinglish", "hi", "mr", "kn", "bn", "ta", "te"}
    sugg_lang: LanguageCode = cast(LanguageCode, raw_lang if raw_lang in supported_langs else "hi")
    met_note = str(raw_payload.get("meteorology_note") or city_meta.get("meteorology_note", ""))

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
        golden_window=golden_window,
        hourly=hourly_points,
        daily_outlook=build_daily_outlook(raw_payload),
        provenance=DataProvenance(**raw_payload["provenance"]),
    )


def compute_inhaled_dose_ug(
    outdoor_pm25: float,
    microenv_key: str,
    activity_level: str,
    duration_min: int,
    mask: MaskType,
) -> float:
    """USEPA modeled PM2.5 inhaled dose proxy for a single concentration interval."""
    kappa = float(CONSTANTS["microenv_multipliers"][microenv_key])
    v_e = float(CONSTANTS["usepa_ventilation_m3_hr"].get(activity_level, 1.25))
    eta = float(CONSTANTS["mask_filtration_efficiency"][mask])
    return round(outdoor_pm25 * kappa * v_e * (duration_min / 60.0) * (1.0 - eta), 2)


def compute_interval_dose_ug(
    hourly_points: list[HourlyAirPoint],
    start_hour: int,
    duration_min: int,
    microenv_key: str,
    activity_level: str,
    mask: MaskType,
) -> tuple[float, float, int]:
    """Integrate PM2.5 dose hour-by-hour across an activity's full duration."""
    if duration_min <= 0:
        pt = hourly_points[start_hour % 24]
        return 0.0, pt.pm2_5, pt.cpcb_naqi

    remaining = duration_min
    idx = start_hour % 24
    total_dose = 0.0
    weighted_pm25 = 0.0
    weighted_naqi = 0.0

    while remaining > 0:
        chunk_min = min(60, remaining)
        pt = hourly_points[idx]
        total_dose += compute_inhaled_dose_ug(
            pt.pm2_5, microenv_key, activity_level, chunk_min, mask
        )
        weighted_pm25 += pt.pm2_5 * chunk_min
        weighted_naqi += pt.cpcb_naqi * chunk_min
        remaining -= chunk_min
        idx = (idx + 1) % 24

    mean_pm25 = round(weighted_pm25 / duration_min, 1)
    mean_naqi = int(round(weighted_naqi / duration_min))
    return round(total_dose, 2), mean_pm25, mean_naqi


def _find_best_start_hour_for_duration(
    hourly_points: list[HourlyAirPoint],
    golden: GoldenWindow,
    duration_min: int,
) -> int:
    """Optimize flexible start hour across the actual duration window (not just 1st hour)."""
    span_hours = max(1, (duration_min + 59) // 60)
    if span_hours <= 2:
        return golden.hours[0]

    best_start = golden.hours[0]
    best_mean = float("inf")
    last_start = max(7, 20 - span_hours)
    for start_h in range(7, last_start + 1):
        window_pm25 = sum(
            hourly_points[(start_h + offset) % 24].pm2_5 for offset in range(span_hours)
        )
        avg_pm25 = window_pm25 / span_hours
        if avg_pm25 < best_mean:
            best_mean = avg_pm25
            best_start = start_h
    return best_start


def _has_sensitive_member(req: PlanRequest, member_name: str) -> bool:
    """Return True if the named member (or household if unmapped) is respiratory-sensitive."""
    ages = ENGINE_PARAMS["age_cutoffs"]
    flags = {"asthma", "copd", "cardiac", "elderly", "child", "hypertension"}
    for m in req.members:
        if m.name == member_name:
            return (
                m.age <= int(ages["sensitive_child_max"])
                or m.age >= int(ages["sensitive_elderly_min"])
                or bool(set(m.conditions) & flags)
            )
    return any(
        m.age <= int(ages["sensitive_child_max"])
        or m.age >= int(ages["sensitive_elderly_min"])
        or bool(set(m.conditions) & {"asthma", "copd"})
        for m in req.members
    )


def _choose_mask(
    pm25: float,
    budget_tier: str,
    current_mask: MaskType,
    sensitive: bool,
    is_work_shift: bool = False,
) -> MaskType:
    """Select cost-feasible mask upgrade using constants.json PM2.5 thresholds."""
    if budget_tier == "rs_0":
        return current_mask
    thresholds = ENGINE_PARAMS["mask_thresholds_pm25"]
    if is_work_shift and pm25 >= float(thresholds["work_shift_n95"]):
        return "n95"
    if pm25 > float(thresholds["general_n95"]) or (
        sensitive and pm25 > float(thresholds["sensitive_n95"])
    ):
        return "n95"
    return current_mask


def _schedule_fixed_activity(
    act: Any,
    req: PlanRequest,
    c_rec: float,
    sensitive: bool,
    base_micro: str,
    target_commute_micro: str,
) -> tuple[str, MaskType, list[str], str]:
    """Generate harm-reduction steps for a fixed work, commute, or school activity."""
    arai_map = CONSTANTS["arai_transport_emissions"]
    mitigation_steps: list[str] = []

    if act.is_work_shift:
        opt_micro = base_micro
        rec_mask = _choose_mask(c_rec, req.budget_tier, act.current_mask, True, is_work_shift=True)
        if rec_mask == "n95":
            mitigation_steps.append("Wear a well-fitted N95/FFP2 respirator across peak corridors.")
        else:
            mitigation_steps.append("Use a snug wrap and take hydration breaks off arterial roads.")
        mitigation_steps.append("Wait for orders 10-15m away from idling diesel/auto queues.")
        mitigation_steps.append(
            "Rinse face/nose with plain water post-shift; recover in Sanctuary Room."
        )
        rationale = (
            f"Fixed work shift stays at {act.planned_hour:02d}:00; focuses on N95 filtration "
            "and off-curb buffers rather than impractical stay-home advice."
        )
        return opt_micro, rec_mask, mitigation_steps, rationale

    if act.is_commute:
        opt_micro = target_commute_micro
        rec_mask = _choose_mask(c_rec, req.budget_tier, act.current_mask, sensitive)
        base_spec = arai_map.get(req.commute_mode, arai_map["car_petrol_solo"])
        target_spec = arai_map.get(req.target_commute_mode, arai_map["electric_metro"])
        if req.target_commute_mode != req.commute_mode:
            mitigation_steps.append(
                f"Switch mode from {base_spec['label']} to {target_spec['label']}."
            )
        elif req.commute_mode in {"car_petrol_solo", "car_diesel_solo", "carpool_3p"}:
            mitigation_steps.append(
                "Keep car AC on Internal Recirculate mode in congested stretches."
            )
        if rec_mask == "n95":
            mitigation_steps.append(
                "Wear a fitted N95 mask on platforms, walkways, and exposed roads."
            )
        elif req.budget_tier == "rs_0":
            mitigation_steps.append(
                "Keep windows closed in congestion and pick quieter side-streets."
            )
        rationale = (
            f"Fixed commute stays at {act.planned_hour:02d}:00; microenvironment and mask "
            "mitigation reduce on-road PM2.5 uptake."
        )
        return opt_micro, rec_mask, mitigation_steps, rationale

    opt_micro = base_micro
    rec_mask = _choose_mask(c_rec, req.budget_tier, act.current_mask, sensitive)
    if rec_mask == "n95":
        mitigation_steps.append("Use a child/adult fitted N95 mask during the roadside wait.")
    elif req.budget_tier == "rs_0":
        mitigation_steps.append("Keep wait time right before pickup under 3 minutes.")
    mitigation_steps.append("Stand 5 meters back from curb/bus exhaust zones while waiting.")
    rationale = f"Fixed commitment remains at {act.planned_hour:02d}:00 with roadside mitigation."
    return opt_micro, rec_mask, mitigation_steps, rationale


def _schedule_flexible_activity(
    act: Any,
    req: PlanRequest,
    hourly: list[HourlyAirPoint],
    golden: GoldenWindow,
    sensitive: bool,
    rec_h: int,
    c_orig: float,
    c_rec: float,
    is_slider_target: bool,
) -> tuple[str, str, MaskType, list[str], str]:
    """Shift flexible outdoor activity to lower-exposure hour or Sanctuary Room."""
    mitigation_steps: list[str] = []
    rec_mask: MaskType = act.current_mask

    if not golden.has_meaningful_window and req.walk_override_hour is None and sensitive:
        opt_micro = "indoor_sealed" if req.budget_tier != "rs_0" else "indoor_shut"
        badge = "FLEXIBLE • INDOOR"
        mitigation_steps.append(
            "Outdoor PM2.5 stays flat (<15% dip); move exercise inside the Sanctuary Room."
        )
        mitigation_steps.append(
            "Do light stretching or indoor walking instead of outdoor exertion."
        )
        rationale = (
            "Honesty rule triggered: no meaningful daytime drop, so vigorous exercise moves inside."
        )
        return badge, opt_micro, rec_mask, mitigation_steps, rationale

    opt_micro = "walk_sidewalk"
    if req.walk_override_hour is not None and is_slider_target:
        badge = "WHAT-IF • TESTED"
    elif rec_h != act.planned_hour:
        badge = "FLEXIBLE • SHIFTED"
    else:
        badge = "FLEXIBLE • KEPT"

    if rec_h != act.planned_hour:
        mitigation_steps.append(
            f"Shift from {act.planned_hour:02d}:00 ({c_orig} ug/m3 avg) "
            f"to {rec_h:02d}:00 ({c_rec} ug/m3 avg)."
        )
    else:
        mitigation_steps.append(f"Timing at {rec_h:02d}:00 already sits in a lower-exposure slot.")

    midday_n95_cutoff = float(ENGINE_PARAMS["mask_thresholds_pm25"]["midday_flexible_n95"])
    if c_rec > midday_n95_cutoff and req.budget_tier != "rs_0":
        rec_mask = "n95"
        mitigation_steps.append("Air remains Poor/Very Poor even midday—add a fitted N95 mask.")
    else:
        mitigation_steps.append("Pick tree-lined lanes away from main arterial intersections.")

    rationale = (
        f"Flexible slot evaluated over {act.duration_min} min from {rec_h:02d}:00 "
        f"(mixing height {hourly[rec_h].boundary_layer_height:.0f} m)."
    )
    return badge, opt_micro, rec_mask, mitigation_steps, rationale


def _schedule_activities(
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
) -> tuple[list[RoutineItemResult], float, float, list[str]]:
    """Run constraint-aware scheduling and hourly-integrated USEPA dosimetry."""
    hourly = snapshot.hourly
    golden = snapshot.golden_window
    arai_map = CONSTANTS["arai_transport_emissions"]
    base_spec = arai_map.get(req.commute_mode, arai_map["car_petrol_solo"])
    target_spec = arai_map.get(req.target_commute_mode, arai_map["electric_metro"])
    base_commute_micro = str(base_spec["microenv"])
    target_commute_micro = str(target_spec["microenv"])

    results: list[RoutineItemResult] = []
    total_base = 0.0
    total_opt = 0.0
    substitutions: list[str] = []
    walk_override_applied = False

    for act in req.activities:
        sensitive = _has_sensitive_member(req, act.member_name)
        base_micro = base_commute_micro if act.is_commute else "walk_sidewalk"
        base_dose, c_orig, naqi_orig = compute_interval_dose_ug(
            hourly,
            act.planned_hour,
            act.duration_min,
            base_micro,
            act.activity_level,
            act.current_mask,
        )

        if act.flexibility == "fixed":
            rec_h = act.planned_hour
            badge = "FIXED • MITIGATED"
            opt_micro, rec_mask, steps, rationale = _schedule_fixed_activity(
                act, req, c_orig, sensitive, base_micro, target_commute_micro
            )
        else:
            is_slider = (
                req.walk_override_hour is not None
                and not walk_override_applied
                and (act.activity_level in PRIMARY_FLEX_LEVELS or act == req.activities[-1])
            )
            if is_slider and req.walk_override_hour is not None:
                rec_h = req.walk_override_hour
                walk_override_applied = True
            else:
                rec_h = _find_best_start_hour_for_duration(hourly, golden, act.duration_min)

            _, c_rec_preview, _ = compute_interval_dose_ug(
                hourly,
                rec_h,
                act.duration_min,
                "walk_sidewalk",
                act.activity_level,
                act.current_mask,
            )
            badge, opt_micro, rec_mask, steps, rationale = _schedule_flexible_activity(
                act, req, hourly, golden, sensitive, rec_h, c_orig, c_rec_preview, is_slider
            )

        opt_dose, c_rec, naqi_rec = compute_interval_dose_ug(
            hourly, rec_h, act.duration_min, opt_micro, act.activity_level, rec_mask
        )
        avoided = round(base_dose - opt_dose, 2)
        total_base += base_dose
        total_opt += opt_dose

        kappa_b = float(CONSTANTS["microenv_multipliers"][base_micro])
        kappa_o = float(CONSTANTS["microenv_multipliers"][opt_micro])
        v_e = float(CONSTANTS["usepa_ventilation_m3_hr"].get(act.activity_level, 1.25))
        eta_b = float(CONSTANTS["mask_filtration_efficiency"][act.current_mask])
        eta_o = float(CONSTANTS["mask_filtration_efficiency"][rec_mask])
        dt_hr = act.duration_min / 60.0

        substitutions.append(
            f"{act.name} ({act.duration_min}m): Base avg {c_orig}*{kappa_b}*{v_e}*{dt_hr:.2f}h"
            f"*(1-{eta_b})={base_dose} ug | Opt avg {c_rec}*{kappa_o}*{v_e}*{dt_hr:.2f}h"
            f"*(1-{eta_o})={opt_dose} ug (Saved {avoided} ug)"
        )
        results.append(
            RoutineItemResult(
                id=act.id,
                name=act.name,
                member_name=act.member_name,
                flexibility=act.flexibility,
                badge=badge,
                original_hour=act.planned_hour,
                recommended_hour=rec_h,
                duration_min=act.duration_min,
                original_pm25=c_orig,
                recommended_pm25=c_rec,
                original_naqi=naqi_orig,
                recommended_naqi=naqi_rec,
                recommended_mask=rec_mask,
                baseline_dose_ug=base_dose,
                optimized_dose_ug=opt_dose,
                dose_avoided_ug=avoided,
                mitigation_steps=steps,
                rationale=rationale,
            )
        )

    return results, round(total_base, 2), round(total_opt, 2), substitutions


def _score_single_room(r: RoomSpec) -> RoomScore:
    """Compute bounded heuristic Clean Air Sanctuary score (0..100) for one room."""
    raw = (
        100
        - 15 * r.ext_windows
        - (25 if r.road_facing else 0)
        - (25 if r.kitchen_adjacent else 0)
        - (10 if r.large_volume else 0)
    )
    score = max(0, min(100, raw))
    reasons = [
        "road-facing infiltration penalty (-25)" if r.road_facing else "away from street exhaust",
        "adjacent to kitchen (-25)" if r.kitchen_adjacent else "isolated from cooking smoke",
    ]
    if r.ext_windows <= 1:
        reasons.append(f"low leak surface ({r.ext_windows} ext window)")
    return RoomScore(
        name=r.name,
        score=score,
        ext_windows=r.ext_windows,
        road_facing=r.road_facing,
        kitchen_adjacent=r.kitchen_adjacent,
        large_volume=r.large_volume,
        is_sanctuary=False,
        reason="; ".join(reasons),
    )


def _build_window_advice(
    snapshot: AirSnapshotResponse,
    budget_tier: str,
) -> WindowVentilationAdvice:
    """Compare outdoor minimum vs modeled sealed indoor proxy without contradictions."""
    day_points = snapshot.hourly[7:19]
    min_pt = min(day_points, key=lambda p: p.pm2_5)
    mean_out_24h = sum(p.pm2_5 for p in snapshot.hourly) / 24.0
    infiltration = float(
        ENGINE_PARAMS["infiltration_rs_0"]
        if budget_tier == "rs_0"
        else ENGINE_PARAMS["infiltration_sealed"]
    )
    cooking_spike = float(ENGINE_PARAMS["cooking_spike_pm25_ug_m3"])
    flush_max = float(ENGINE_PARAMS["window_flush_max_outdoor_pm25"])
    mod_cap = float(ENGINE_PARAMS["window_moderate_cap_pm25"])

    modeled_indoor_base = round(mean_out_24h * infiltration, 1)
    modeled_post_cooking = round(modeled_indoor_base + cooking_spike, 1)
    end_hr = min(23, min_pt.hour + 1)

    if min_pt.pm2_5 <= modeled_indoor_base:
        return WindowVentilationAdvice(
            action="timed_open",
            open_window_start_hour=min_pt.hour,
            open_window_end_hour=end_hr,
            duration_minutes=20,
            outdoor_min_pm25=min_pt.pm2_5,
            modeled_indoor_baseline_pm25=modeled_indoor_base,
            modeled_post_cooking_pm25=modeled_post_cooking,
            guidance=(
                f"Open non-road-facing windows 20 min around {min_pt.hour:02d}:00-"
                f"{end_hr:02d}:00 (outdoor {min_pt.pm2_5} ug/m3 dips at/below modeled indoor "
                f"~{modeled_indoor_base} ug/m3) to refresh air; shut tight by sunset."
            ),
        )

    if min_pt.pm2_5 <= flush_max:
        return WindowVentilationAdvice(
            action="timed_open",
            open_window_start_hour=min_pt.hour,
            open_window_end_hour=end_hr,
            duration_minutes=15,
            outdoor_min_pm25=min_pt.pm2_5,
            modeled_indoor_baseline_pm25=modeled_indoor_base,
            modeled_post_cooking_pm25=modeled_post_cooking,
            guidance=(
                f"Outdoor PM2.5 dips to {min_pt.pm2_5} ug/m3 around {min_pt.hour:02d}:00-"
                f"{end_hr:02d}:00 (above sealed indoor ~{modeled_indoor_base} ug/m3): open "
                "non-road windows 15 min only as a brief CO2/cooking flush, then shut before dusk."
            ),
        )

    extra_flush = (
        " If indoor air feels stuffy during cooking, crack a non-roadside window for only 5-10 min "
        "alongside your exhaust fan."
        if min_pt.pm2_5 <= mod_cap
        else ""
    )
    return WindowVentilationAdvice(
        action="keep_shut_exhaust",
        open_window_start_hour=None,
        open_window_end_hour=None,
        duration_minutes=0,
        outdoor_min_pm25=min_pt.pm2_5,
        modeled_indoor_baseline_pm25=modeled_indoor_base,
        modeled_post_cooking_pm25=modeled_post_cooking,
        guidance=(
            f"Keep exterior windows shut today: lowest outdoor PM2.5 ({min_pt.pm2_5} ug/m3 at "
            f"{min_pt.hour:02d}:00) exceeds modeled indoor air (~{modeled_indoor_base} ug/m3). "
            f"Vent kitchen tadka via closed kitchen door + exhaust fan for 15 min.{extra_flush}"
        ),
    )


def _collect_sanctuary_alerts(req: PlanRequest) -> list[str]:
    """Build indoor source-control and persona-specific Sanctuary alerts."""
    ages = ENGINE_PARAMS["age_cutoffs"]
    alerts: list[str] = []
    if req.uses_agarbatti_or_coils:
        alerts.append(
            "Detected agarbatti/mosquito coil use: pause indoor burning on elevated-AQI days."
        )
    if req.dry_sweeps:
        alerts.append(
            "Switch dry jhadu sweeping to damp wet-mopping (pochha) to curb dust resuspension."
        )
    if any("asthma" in m.conditions or "copd" in m.conditions for m in req.members):
        alerts.append(
            "Keep prescribed rescue inhaler / reliever medication accessible in Sanctuary Room."
        )

    senior_min = int(ages["sensitive_elderly_min"])
    if req.user_category == "delivery_riders" or any(a.is_work_shift for a in req.activities):
        alerts.append(
            "Rider recovery: shake dusty outer jacket outside entry door and rinse nose/face."
        )
    elif req.user_category == "seniors" or any(m.age >= senior_min for m in req.members):
        alerts.append(
            "Senior protection: avoid cold outdoor drafts before 9 AM and keep Sanctuary Room warm."
        )
    elif req.user_category == "students_kids" or any(m.age <= 18 for m in req.members):
        alerts.append(
            "Student/kid routine: keep study desk away from street windows and wipe school shoes."
        )
    else:
        alerts.append(
            "Commuter home setup: seal corridor door leaks and flush interior air only at midday."
        )
    return alerts


def score_sanctuary(req: PlanRequest, snapshot: AirSnapshotResponse) -> SanctuaryPlan:
    """Rank rooms for Clean Air Sanctuary and compute window open/shut protocol + IAQ hacks."""
    rooms = req.rooms if req.rooms else DEFAULT_ROOMS
    scored = [_score_single_room(room) for room in rooms]
    scored.sort(key=lambda item: item.score, reverse=True)
    scored[0].is_sanctuary = True

    limit_inr = int(CONSTANTS["budget_tier_limits_inr"][req.budget_tier])
    hacks = [h for h in CONSTANTS["iaq_hacks"] if int(h["max_cost_inr"]) <= limit_inr]

    return SanctuaryPlan(
        sanctuary_room=scored[0].name,
        room_scores=scored,
        window_advice=_build_window_advice(snapshot, req.budget_tier),
        co2_safety_note="Leave an inner door slightly ajar overnight so CO2 does not build up.",
        no_houseplants_note=(
            "Indoor houseplants do not remove meaningful PM2.5 in real homes; focus on source "
            "control, sealing gaps, and filtration."
        ),
        applicable_hacks=hacks,
        personalized_alerts=_collect_sanctuary_alerts(req),
    )


def compute_emit_less(req: PlanRequest) -> EmitLessLedger:
    """Compute Ledger 2 (ARAI / WRI India transport CO2e and tailpipe PM2.5 savings)."""
    arai_map = CONSTANTS["arai_transport_emissions"]
    base_spec = arai_map.get(req.commute_mode, arai_map["car_petrol_solo"])
    target_spec = arai_map.get(req.target_commute_mode, arai_map["electric_metro"])

    co2_saved_g = round(
        req.commute_km * (float(base_spec["co2_g_pkm"]) - float(target_spec["co2_g_pkm"])), 1
    )
    co2_saved_kg = round(co2_saved_g / 1000.0, 3)
    tailpipe_pm25_mg = round(
        req.commute_km * (float(base_spec["pm25_mg_pkm"]) - float(target_spec["pm25_mg_pkm"])), 1
    )

    substitutions = [
        f"CO2e = {req.commute_km} km * ({base_spec['co2_g_pkm']} - {target_spec['co2_g_pkm']}) "
        f"g/pkm = {co2_saved_g} g ({co2_saved_kg} kg)",
        f"Tailpipe PM2.5 = {req.commute_km} km * ({base_spec['pm25_mg_pkm']} - "
        f"{target_spec['pm25_mg_pkm']}) mg/pkm = {tailpipe_pm25_mg} mg",
    ]
    if req.commute_mode == req.target_commute_mode:
        substitutions.append(
            "Same transport mode kept (e.g., fixed work vehicle); tailpipe counterfactual = 0."
        )

    return EmitLessLedger(
        baseline_mode=req.commute_mode,
        target_mode=req.target_commute_mode,
        baseline_mode_label=str(base_spec["label"]),
        target_mode_label=str(target_spec["label"]),
        commute_km=req.commute_km,
        co2_saved_g=co2_saved_g,
        co2_saved_kg=co2_saved_kg,
        tailpipe_pm25_saved_mg=tailpipe_pm25_mg,
        label="Modeled Estimate",
        formula_summary=(
            "Delta CO2e (g) = km * (EF_CO2_base - EF_CO2_new); "
            "Delta Tailpipe PM2.5 (mg) = km * (EF_PM_base - EF_PM_new)"
        ),
        substitutions=substitutions,
        limitations=(
            "Uses ARAI / WRI India average per-passenger-km emission factors; actual fuel use, "
            "occupancy, and congestion idling vary."
        ),
    )


def _resolve_profile_key(req: PlanRequest) -> UserCategory:
    """Determine primary user category from explicit flag or household profile."""
    if req.user_category is not None:
        return req.user_category
    ages = ENGINE_PARAMS["age_cutoffs"]
    all_conditions = {c for m in req.members for c in m.conditions}
    if any(a.is_work_shift for a in req.activities) or "outdoor_worker" in all_conditions:
        return "delivery_riders"
    senior_tags = {"elderly", "copd", "cardiac"}
    if any(
        m.age >= int(ages["senior_profile_min"]) or bool(set(m.conditions) & senior_tags)
        for m in req.members
    ):
        return "seniors"
    if any(
        m.age <= int(ages["student_kid_max"]) or bool(set(m.conditions) & {"child", "student"})
        for m in req.members
    ):
        return "students_kids"
    return "adults_commuters"


def _build_profile_copy(
    key: UserCategory,
    snapshot: AirSnapshotResponse,
    breathe_less: BreatheLessLedger,
    emit_less: EmitLessLedger,
    peak_ve: float,
    hrs: float,
) -> tuple[str, str, str]:
    """Return (warning_banner, tailored_hero_headline, physiology_note) for profile key."""
    gw = snapshot.golden_window
    pm25 = snapshot.current_pm25
    naqi = snapshot.current_naqi
    best_win = f"{gw.start_hour:02d}:00–{gw.end_hour:02d}:00"
    threshold = int(ENGINE_PARAMS["category_warning_thresholds_naqi"][key])
    co2_str = (
        f"{emit_less.co2_saved_kg} kg"
        if emit_less.co2_saved_g >= 1000
        else f"{emit_less.co2_saved_g} g"
    )

    if key == "delivery_riders":
        mult = float(ENGINE_PARAMS["roadside_plume_multiplier"])
        road_pm25 = round(pm25 * mult, 1)
        physiology = (
            f"Road-facing shifts (~{hrs}h at {peak_ve} m3/hr) hit ~{road_pm25} ug/m3 road dust "
            f"({mult}x ambient {pm25} ug/m3); daily dose: {breathe_less.optimized_dose_ug} ug "
            f"vs {breathe_less.baseline_dose_ug} ug."
        )
        if naqi > 200:
            banner = (
                f"High Roadside Smog Alert (Hourly AQI {naqi}, Road ~{road_pm25} ug/m3): "
                "Wear a snug N95 mask on 2-wheeler runs and take 10-min shaded breaks off roads."
            )
        elif naqi > threshold:
            banner = (
                f"Delivery Rider Warning (Hourly AQI {naqi} > {threshold} limit): Roadside {mult}x "
                f"exhaust lifts baseline intake to {breathe_less.baseline_dose_ug} ug—wear N95."
            )
        else:
            banner = (
                f"Hourly AQI {naqi} is below {threshold}, yet {hrs}h in traffic builds "
                f"{breathe_less.baseline_dose_ug} ug unmasked—keep an N95 handy in congestion."
            )
        headline = (
            f"Ambient air is {snapshot.current_category} (AQI {naqi}), but {hrs}h in traffic puts "
            f"road PM2.5 near {road_pm25} ug/m3 — N95 cuts dose by {breathe_less.reduction_pct}%."
            if gw.is_clean_air_day
            else f"Fixed shifts sit near ~{road_pm25} ug/m3 road dust — N95 + off-curb waits "
            f"avoid {breathe_less.dose_avoided_ug} ug PM2.5 ({breathe_less.reduction_pct}% less)."
        )
        return banner, headline, physiology

    if key == "seniors":
        physiology = (
            f"65+ / COPD airways react earlier at {peak_ve} m3/hr walking pace: cold morning smog "
            f"({gw.morning_peak_pm25} ug/m3 peak) strains airways well before adult alerts fire."
        )
        if naqi > 200:
            banner = (
                f"Senior Health Alert (Hourly AQI {naqi}): Skip pre-9 AM outdoor walks, shut "
                "windows, and keep rescue inhalers / BP meds beside you."
            )
        elif naqi > threshold:
            banner = (
                f"Senior Precaution Active (Hourly AQI {naqi} > {threshold} limit): Skip cold "
                f"inversion walks—shift strolls to {best_win} and wear an N95 in transit."
            )
        else:
            banner = (
                f"Low-strain range for seniors today (Hourly AQI {naqi} <= {threshold}): Enjoy "
                f"daytime walks at {best_win}, skip chilly pre-dawn hours, breathe via nose."
            )
        if gw.is_clean_air_day:
            headline = f"Comfortable air for seniors ({pm25} ug/m3) — walk around {best_win}."
        elif gw.has_meaningful_window:
            headline = (
                f"Move senior walk from cold 6-8 AM smog to warmer {best_win} "
                f"({round(gw.reduction_pct)}% cleaner)."
            )
        else:
            headline = (
                "Elevated stagnant air today — pause senior outdoor walks and stretch inside."
            )
        return banner, headline, physiology

    if key == "students_kids":
        physiology = (
            f"Growing lungs inhale more per kg body weight (up to {peak_ve} m3/hr in sports) near "
            f"exhaust height, driving {breathe_less.baseline_dose_ug} ug baseline peak dose."
        )
        if naqi > 200:
            banner = (
                f"Student & Kid Alert (Hourly AQI {naqi}): Move school assembly & sports indoors; "
                "send a fitted N95 for commutes."
            )
        elif naqi > threshold:
            banner = (
                f"Kids Precaution Triggered (Hourly AQI {naqi} > {threshold}): Limit sprints, step "
                f"back from idling buses, and shift play toward {best_win}."
            )
        else:
            banner = (
                f"Good day for school sports & evening play (Hourly AQI {naqi} <= {threshold}): "
                "Keep pickup queues 5m back from idling buses."
            )
        if gw.is_clean_air_day:
            headline = (
                f"Favorable outdoor day for school & park play ({pm25} ug/m3) — skip bus exhaust."
            )
        elif gw.has_meaningful_window:
            headline = (
                f"Shift playground sports to {best_win} ({round(gw.reduction_pct)}% lower exposure)"
                " instead of evening rush."
            )
        else:
            headline = "Elevated pollution all day — hold school PE indoors and skip sprints."
        return banner, headline, physiology

    physiology = (
        f"Healthy adult lungs ({peak_ve} m3/hr brisk walk) face lower acute risk under NAQI 150—"
        f"biggest gains are workout timing and shifting {emit_less.commute_km} km ({co2_str} CO2)."
    )
    if naqi > 200:
        banner = (
            f"Commuter & Workout Warning (Hourly AQI {naqi} > 150): Move cardio indoors, wear "
            "N95 in transit, and keep car AC on recirculate."
        )
    elif naqi > threshold:
        banner = (
            f"Adult Advisory (Hourly AQI {naqi} > 150): Shift runs to {best_win} and take "
            f"{emit_less.target_mode_label} or AC-recirculate."
        )
    else:
        banner = (
            f"Within standard adult threshold (Hourly AQI {naqi} <= 150): Shifting to "
            f"{emit_less.target_mode_label} avoids {co2_str} CO2 today."
        )
    if gw.is_clean_air_day:
        headline = (
            f"Favorable air for adult workouts (AQI {naqi}); shifting {emit_less.commute_km} km "
            f"saves {co2_str} CO2."
        )
    elif gw.has_meaningful_window:
        headline = (
            f"Best adult workout window: {best_win} ({round(gw.reduction_pct)}% cleaner than AM)."
        )
    else:
        headline = "Elevated smog exceeds adult threshold — move cardio inside and seal cabin air."
    return banner, headline, physiology


def build_profile_risk_summary(
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    breathe_less: BreatheLessLedger,
    emit_less: EmitLessLedger,
) -> ProfileRiskSummary:
    """Compute category-specific NAQI thresholds, lung intake, and risk banner."""
    key = _resolve_profile_key(req)
    ve_map = CONSTANTS["usepa_ventilation_m3_hr"]
    ve_list = [float(ve_map.get(a.activity_level, 1.25)) for a in req.activities] or [1.25]
    peak_ve = round(max(ve_list), 2)
    total_outdoor_min = sum(a.duration_min for a in req.activities)
    hrs = round(total_outdoor_min / 60.0, 1)

    desc = PROFILE_DESCRIPTORS[key]
    threshold = int(ENGINE_PARAMS["category_warning_thresholds_naqi"][key])
    naqi = snapshot.current_naqi
    warning_active = naqi > threshold

    band_idx = 0 if naqi > 200 else (1 if warning_active else 2)
    risk_level = desc["severity_labels"][band_idx]
    risk_badge = desc["badges"][band_idx]
    banner, headline, physiology = _build_profile_copy(
        key, snapshot, breathe_less, emit_less, peak_ve, hrs
    )

    return ProfileRiskSummary(
        profile_key=key,
        profile_label=desc["label"],
        sensitivity_tier=desc["tier"],
        warning_threshold_naqi=threshold,
        warning_active=warning_active,
        risk_level=risk_level,
        risk_badge=risk_badge,
        warning_banner=banner,
        peak_ventilation_m3_hr=peak_ve,
        total_outdoor_min=total_outdoor_min,
        tailored_hero_headline=headline,
        physiology_note=physiology,
    )


def _collect_grounded_metrics(
    snapshot: AirSnapshotResponse,
    routine_plan: list[RoutineItemResult],
    sanctuary_plan: SanctuaryPlan,
    breathe_less: BreatheLessLedger,
    emit_less: EmitLessLedger,
    profile_summary: ProfileRiskSummary,
) -> tuple[GroundedMetrics, list[float]]:
    """Build category-scoped and global numeric allowlists before EvidenceBundle creation."""
    road_pm25 = round(
        snapshot.current_pm25 * float(ENGINE_PARAMS["roadside_plume_multiplier"]), 1
    )
    pm25_vals: set[float] = {
        2.5,
        60.0,
        90.0,
        road_pm25,
        float(snapshot.current_pm25),
        float(snapshot.golden_window.mean_pm25),
        float(snapshot.golden_window.morning_peak_pm25),
        float(sanctuary_plan.window_advice.outdoor_min_pm25),
        float(sanctuary_plan.window_advice.modeled_indoor_baseline_pm25),
        float(sanctuary_plan.window_advice.modeled_post_cooking_pm25),
    }
    naqi_vals: set[float] = {
        100.0, 150.0, 200.0, 300.0, 500.0,
        float(snapshot.current_naqi),
        float(snapshot.golden_window.mean_naqi),
        float(profile_summary.warning_threshold_naqi),
    }
    for pt in snapshot.hourly:
        pm25_vals.add(float(pt.pm2_5))
        naqi_vals.add(float(pt.cpcb_naqi))
    for day in snapshot.daily_outlook:
        pm25_vals.add(float(day.peak_pm25))
        pm25_vals.add(float(day.best_window_pm25))
        naqi_vals.add(float(day.peak_naqi))
    for item in routine_plan:
        pm25_vals.update([float(item.original_pm25), float(item.recommended_pm25)])
        naqi_vals.update([float(item.original_naqi), float(item.recommended_naqi)])

    dose_vals: set[float] = {
        330.0,
        float(breathe_less.baseline_dose_ug),
        float(breathe_less.optimized_dose_ug),
        float(breathe_less.dose_avoided_ug),
    }
    for item in routine_plan:
        dose_vals.update([
            float(item.baseline_dose_ug),
            float(item.optimized_dose_ug),
            float(item.dose_avoided_ug),
        ])

    cigs_vals = sorted({float(breathe_less.cigarettes_avoided)})
    co2_g_vals = sorted({float(emit_less.co2_saved_g)})
    co2_kg_vals = sorted({float(emit_less.co2_saved_kg)})
    tailpipe_vals = sorted({float(emit_less.tailpipe_pm25_saved_mg)})
    pct_vals = sorted(
        {float(snapshot.golden_window.reduction_pct), float(breathe_less.reduction_pct)}
        | {float(day.reduction_pct) for day in snapshot.daily_outlook}
    )

    metrics = GroundedMetrics(
        pm25=sorted(pm25_vals),
        naqi=sorted(naqi_vals),
        dose_ug=sorted(dose_vals),
        cigarettes=cigs_vals,
        co2_g=co2_g_vals,
        co2_kg=co2_kg_vals,
        tailpipe_mg=tailpipe_vals,
        pct=pct_vals,
    )

    flat: set[float] = {
        0.0, 2.0, 2.5, 10.0, 13.0, 15.0, 20.0, 95.0, 330.0, 500.0, 2200.0,
        float(snapshot.current_hour),
        float(snapshot.morning_inversion_ceiling_m),
        float(snapshot.golden_window.start_hour),
        float(snapshot.golden_window.end_hour),
        float(sanctuary_plan.window_advice.duration_minutes),
        float(emit_less.commute_km),
        float(profile_summary.peak_ventilation_m3_hr),
    }
    flat.update(
        pm25_vals,
        naqi_vals,
        dose_vals,
        cigs_vals,
        co2_g_vals,
        co2_kg_vals,
        tailpipe_vals,
        pct_vals,
    )
    flat.update(float(pt.hour) for pt in snapshot.hourly)
    flat.update(float(pt.pm10) for pt in snapshot.hourly)
    flat.update(float(pt.boundary_layer_height) for pt in snapshot.hourly)
    flat.update(float(rm.score) for rm in sanctuary_plan.room_scores)
    for item in routine_plan:
        flat.update([
            float(item.original_hour),
            float(item.recommended_hour),
            float(item.duration_min),
        ])

    return metrics, sorted(flat)


def build_evidence_bundle(
    req: PlanRequest,
    raw_payload: dict[str, Any],
    current_hour: int | None = None,
    emergency_alert: bool = False,
    emergency_message: str | None = None,
) -> EvidenceBundle:
    """Assemble the complete immutable deterministic EvidenceBundle for PRANA-AI."""
    snapshot = build_air_snapshot(raw_payload, current_hour=current_hour)
    routine_plan, base_dose, opt_dose, dose_subs = _schedule_activities(req, snapshot)
    dose_avoided = round(base_dose - opt_dose, 2)
    reduction_pct = round((dose_avoided / base_dose) * 100.0, 1) if base_dose > 0 else 0.0
    cigs_avoided = round(dose_avoided / float(CONSTANTS["berkeley_earth_cig_ug"]), 2)

    breathe_less = BreatheLessLedger(
        baseline_dose_ug=base_dose,
        optimized_dose_ug=opt_dose,
        dose_avoided_ug=dose_avoided,
        reduction_pct=reduction_pct,
        cigarettes_avoided=cigs_avoided,
        label="Modeled Estimate",
        formula_summary=(
            "D (ug) = sum_h (C_h * kappa * V_E * dt_h) * (1 - eta); Cigarettes = Delta D / 330 ug"
        ),
        substitutions=dose_subs,
        limitations=(
            "Modeled exposure proxy integrating gridded Open-Meteo outdoor PM2.5, USEPA breathing "
            "rates, and lab filtration/microenvironment factors—not a personal monitor reading."
        ),
    )

    sanctuary_plan = score_sanctuary(req, snapshot)
    emit_less = compute_emit_less(req)
    profile_summary = build_profile_risk_summary(req, snapshot, breathe_less, emit_less)
    metrics, grounded_list = _collect_grounded_metrics(
        snapshot, routine_plan, sanctuary_plan, breathe_less, emit_less, profile_summary
    )

    return EvidenceBundle(
        app_name="PRANA-AI",
        city=snapshot.city,
        city_name=snapshot.city_name,
        area_name=snapshot.area_name or req.area_name,
        language=req.language,
        budget_tier=req.budget_tier,
        emergency_alert=emergency_alert,
        emergency_message=emergency_message,
        provenance=snapshot.provenance,
        air_snapshot=snapshot,
        routine_plan=routine_plan,
        sanctuary_plan=sanctuary_plan,
        breathe_less=breathe_less,
        emit_less=emit_less,
        profile_summary=profile_summary,
        grounded_metrics=metrics,
        grounded_numbers=grounded_list,
    )
