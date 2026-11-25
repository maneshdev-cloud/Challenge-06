"""Deterministic physics, CPCB NAQI, dosimetry, sanctuary, and ARAI emissions engine for PRANA-AI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from data_fetcher import CONSTANTS
from schemas import (
    ActivityItem,
    AirSnapshotResponse,
    BreatheLessLedger,
    DailyAirOutlook,
    DataProvenance,
    EmitLessLedger,
    EvidenceBundle,
    GoldenWindow,
    HourlyAirPoint,
    MaskType,
    PlanRequest,
    ProfileRiskSummary,
    RoomScore,
    RoomSpec,
    RoutineItemResult,
    SanctuaryPlan,
    WindowVentilationAdvice,
)

IST_TZ = timezone(timedelta(hours=5, minutes=30))

DEFAULT_ROOMS = [
    RoomSpec(name="Front Living Room", ext_windows=2, road_facing=True, kitchen_adjacent=True, large_volume=True),
    RoomSpec(name="Inner Bedroom", ext_windows=1, road_facing=False, kitchen_adjacent=False, large_volume=False),
]

PRIMARY_FLEX_LEVELS = {"elderly_walk", "child_play", "running_or_outdoor_work", "brisk_walk"}


def compute_cpcb_subindex(concentration: float, breakpoints: list[dict[str, Any]]) -> tuple[int, str]:
    """Compute a single-pollutant CPCB NAQI sub-index using continuous interval handling."""
    c = max(0.0, float(concentration))
    last_bp = breakpoints[-1]
    if c >= last_bp["c_hi"]:
        return 500, last_bp["category"]

    prev_bp: dict[str, Any] | None = None
    for bp in breakpoints:
        c_lo = float(bp["c_lo"])
        c_hi = float(bp["c_hi"])
        i_lo = float(bp["i_lo"])
        i_hi = float(bp["i_hi"])

        if prev_bp is not None and float(prev_bp["c_hi"]) < c < c_lo:
            # Smoothly bridge the integer step gap (e.g., 30 < 30.4 < 31) so floats never drop out.
            span = c_lo - float(prev_bp["c_hi"])
            sub = float(prev_bp["i_hi"]) + ((i_lo - float(prev_bp["i_hi"])) / span) * (c - float(prev_bp["c_hi"]))
            return int(round(sub)), bp["category"]

        if c_lo <= c <= c_hi:
            if c_hi == c_lo:
                return int(round(i_hi)), bp["category"]
            sub = ((i_hi - i_lo) / (c_hi - c_lo)) * (c - c_lo) + i_lo
            return int(round(sub)), bp["category"]

        prev_bp = bp

    return 500, last_bp["category"]


def compute_pm25_naqi(pm25: float) -> tuple[int, str]:
    """Compute CPCB PM2.5 sub-index and category."""
    return compute_cpcb_subindex(pm25, CONSTANTS["cpcb_pm25_breakpoints"])


def category_for_naqi(naqi: int) -> str:
    """Return CPCB NAQI band category for an overall NAQI value."""
    for bp in CONSTANTS["cpcb_pm25_breakpoints"]:
        if naqi <= bp["i_hi"]:
            return bp["category"]
    return "Severe"


def compute_hourly_naqi(pm25: float, pm10: float, no2: float) -> dict[str, Any]:
    """Compute CPCB sub-indices for PM2.5, PM10, NO2 and identify dominant pollutant."""
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


def find_golden_window(hourly_points: list[HourlyAirPoint]) -> GoldenWindow:
    """Scan daytime hours (07:00-19:00) for the lowest 2-hour mean PM2.5 window."""
    best_h = 13
    best_mean = float("inf")
    for h in range(7, 18):
        pair_mean = (hourly_points[h].pm2_5 + hourly_points[h + 1].pm2_5) / 2.0
        if pair_mean < best_mean:
            best_mean = pair_mean
            best_h = h

    morning_peak = max(hourly_points[h].pm2_5 for h in range(6, 10))
    morning_peak_naqi = max(hourly_points[h].cpcb_naqi for h in range(6, 10))
    if morning_peak > 0:
        reduction_pct = round(((morning_peak - best_mean) / morning_peak) * 100.0, 1)
    else:
        reduction_pct = 0.0

    mean_naqi = int(round((hourly_points[best_h].cpcb_naqi + hourly_points[best_h + 1].cpcb_naqi) / 2.0))
    is_clean_air_day = mean_naqi <= 100 and morning_peak_naqi <= 100
    has_meaningful_window = is_clean_air_day or ((reduction_pct / 100.0) >= 0.15)
    window_label = f"{best_h:02d}:00 - {best_h + 2:02d}:00"

    if is_clean_air_day:
        advisory = (
            "Air quality is Good/Satisfactory today—normal outdoor routines are fine; "
            "still follow kitchen exhaust habits."
        )
    elif has_meaningful_window:
        advisory = (
            f"Lowest-exposure daytime window is {window_label} ({round(best_mean, 1)} ug/m3 PM2.5, "
            f"NAQI {mean_naqi}), {reduction_pct:.0f}% lower than the morning peak ({round(morning_peak, 1)} ug/m3) "
            "as daytime mixing lifts the boundary layer."
        )
    else:
        advisory = (
            f"No strong daytime dip today: best 2h window ({window_label}, {round(best_mean, 1)} ug/m3) "
            f"is only {max(0.0, reduction_pct):.0f}% below the morning peak ({round(morning_peak, 1)} ug/m3). "
            "Outdoor air stays uniformly elevated—shift strenuous exercise indoors."
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
        start = d * 24
        end = start + 24
        day_date = times[start][:10]
        try:
            dt = datetime.strptime(day_date, "%Y-%m-%d")
            day_label = f"Today ({dt.strftime('%a')})" if d == 0 else dt.strftime("%a, %b %d")
        except ValueError:
            day_label = "Today" if d == 0 else f"Day {d + 1}"

        day_pm25 = [float(x) for x in pm25_all[start:end]]
        day_pm10 = [float(x) for x in pm10_all[start:end]]
        day_no2 = [float(x) for x in no2_all[start:end]]

        day_naqis = [compute_hourly_naqi(day_pm25[h], day_pm10[h], day_no2[h])["cpcb_naqi"] for h in range(24)]
        peak_pm25 = round(max(day_pm25), 1)
        peak_naqi = max(day_naqis)
        peak_category = category_for_naqi(peak_naqi)

        best_h = 13
        best_mean = float("inf")
        for h in range(7, 18):
            m = (day_pm25[h] + day_pm25[h + 1]) / 2.0
            if m < best_mean:
                best_mean = m
                best_h = h

        best_window_label = f"{best_h:02d}:00 - {best_h + 2:02d}:00"
        if peak_naqi <= 100:
            tip = "Good day for outdoor errands and walks."
        elif peak_naqi <= 200:
            tip = f"Schedule outdoor errands around {best_h:02d}:00-{best_h + 2:02d}:00."
        elif peak_naqi <= 300:
            tip = "Poor air expected—keep errands short with an N95 mask."
        else:
            tip = "Heavy smog expected—plan indoor workouts and keep rooms sealed."

        outlooks.append(
            DailyAirOutlook(
                date=day_date,
                day_label=day_label,
                peak_pm25=peak_pm25,
                peak_naqi=peak_naqi,
                peak_category=peak_category,
                best_window_label=best_window_label,
                best_window_pm25=round(best_mean, 1),
                tip=tip,
            )
        )
    return outlooks


def build_air_snapshot(raw_payload: dict[str, Any], current_hour: int | None = None) -> AirSnapshotResponse:
    """Convert fetched hourly arrays into a CPCB-enriched AirSnapshotResponse."""
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

    hour_idx = current_hour if current_hour is not None else datetime.now(IST_TZ).hour
    hour_idx = max(0, min(23, hour_idx))
    current_pt = hourly_points[hour_idx]

    golden_window = find_golden_window(hourly_points)
    inversion_m, regime = classify_meteorology_regime(hourly_points)
    daily_outlook = build_daily_outlook(raw_payload)

    return AirSnapshotResponse(
        city=city_key,
        city_name=raw_payload.get("city_display") or city_meta.get("name") or city_key.title(),
        area_name=raw_payload.get("area_name"),
        state=raw_payload.get("state"),
        lat=raw_payload.get("lat"),
        lon=raw_payload.get("lon"),
        is_coastal=bool(raw_payload.get("is_coastal", False)),
        suggested_language=raw_payload.get("suggested_language") or city_meta.get("local_language") or "hi",
        meteorology_note=raw_payload.get("meteorology_note") or city_meta.get("meteorology_note", ""),
        current_hour=hour_idx,
        current_pm25=current_pt.pm2_5,
        current_naqi=current_pt.cpcb_naqi,
        current_category=current_pt.cpcb_category,
        dominant_pollutant=current_pt.dominant_pollutant,
        morning_inversion_ceiling_m=inversion_m,
        meteorology_regime=regime,
        golden_window=golden_window,
        hourly=hourly_points,
        daily_outlook=daily_outlook,
        provenance=DataProvenance(**raw_payload["provenance"]),
    )


def compute_inhaled_dose_ug(
    outdoor_pm25: float,
    microenv_key: str,
    activity_level: str,
    duration_min: int,
    mask: MaskType,
) -> float:
    """USEPA modeled PM2.5 inhaled dose proxy: C_out * kappa * V_E * dt_hr * (1 - eta)."""
    kappa = float(CONSTANTS["microenv_multipliers"][microenv_key])
    v_e = float(CONSTANTS["usepa_ventilation_m3_hr"].get(activity_level, 1.25))
    eta = float(CONSTANTS["mask_filtration_efficiency"][mask])
    dt_hr = duration_min / 60.0
    return round(outdoor_pm25 * kappa * v_e * dt_hr * (1.0 - eta), 2)


def _has_sensitive_member(req: PlanRequest, member_name: str) -> bool:
    sensitive_flags = {"asthma", "copd", "cardiac", "elderly", "child", "hypertension"}
    for m in req.members:
        if m.name == member_name and (m.age <= 12 or m.age >= 65 or bool(set(m.conditions) & sensitive_flags)):
            return True
    return any(m.age <= 12 or m.age >= 65 or bool(set(m.conditions) & {"asthma", "copd"}) for m in req.members)


def _choose_mask(pm25: float, budget_tier: str, current_mask: MaskType, sensitive: bool, is_work_shift: bool = False) -> MaskType:
    if budget_tier == "rs_0":
        return current_mask
    # Outdoor traffic workers breathe 1.55x roadside plumes over multi-hour shifts, so N95 pays off above 20 ug/m3
    if is_work_shift and pm25 >= 20.0:
        return "n95"
    if pm25 > 60.0 or (sensitive and pm25 > 40.0):
        return "n95"
    return current_mask


def _schedule_activities(
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
) -> tuple[list[RoutineItemResult], float, float, list[str]]:
    """Run constraint-aware scheduling and USEPA dosimetry across all household tasks."""
    hourly = snapshot.hourly
    golden = snapshot.golden_window
    best_h = golden.hours[0]
    arai_map = CONSTANTS["arai_transport_emissions"]
    base_commute_micro = arai_map.get(req.commute_mode, arai_map["car_petrol_solo"])["microenv"]
    target_commute_micro = arai_map.get(req.target_commute_mode, arai_map["electric_metro"])["microenv"]

    results: list[RoutineItemResult] = []
    total_base = 0.0
    total_opt = 0.0
    substitutions: list[str] = []

    walk_override_applied = False

    for act in req.activities:
        orig_h = act.planned_hour
        c_orig = hourly[orig_h].pm2_5
        naqi_orig = hourly[orig_h].cpcb_naqi
        sensitive = _has_sensitive_member(req, act.member_name)

        base_micro = base_commute_micro if act.is_commute else "walk_sidewalk"
        base_dose = compute_inhaled_dose_ug(c_orig, base_micro, act.activity_level, act.duration_min, act.current_mask)
        mitigation_steps: list[str] = []

        if act.flexibility == "fixed":
            rec_h = orig_h
            c_rec = hourly[rec_h].pm2_5
            naqi_rec = hourly[rec_h].cpcb_naqi
            badge = "FIXED • MITIGATED"

            if act.is_work_shift:
                # Non-negotiable outdoor work shift (e.g., delivery rider): never tell them to stay indoors.
                opt_micro = base_micro
                rec_mask = _choose_mask(c_rec, req.budget_tier, act.current_mask, sensitive=True, is_work_shift=True)
                if rec_mask == "n95":
                    mitigation_steps.append("Wear a well-fitted N95/FFP2 respirator across peak traffic corridors.")
                else:
                    mitigation_steps.append("Use a snug double-layer wrap and take hydration breaks off arterial roads.")
                mitigation_steps.append("Wait for orders 10-15m away from idling diesel/auto queues where possible.")
                mitigation_steps.append("Rinse face and nose with plain water after the shift; recover in the Sanctuary Room.")
                rationale = (
                    f"Fixed work shift stays at {rec_h:02d}:00; harm-reduction focuses on fitted N95 filtration "
                    "and off-curb waiting buffers rather than impractical stay-home advice."
                )
            elif act.is_commute:
                opt_micro = target_commute_micro
                rec_mask = _choose_mask(c_rec, req.budget_tier, act.current_mask, sensitive)
                if req.target_commute_mode != req.commute_mode:
                    target_lbl = arai_map.get(req.target_commute_mode, {}).get("label", req.target_commute_mode)
                    mitigation_steps.append(f"Switch mode from {arai_map[req.commute_mode]['label']} to {target_lbl}.")
                elif req.commute_mode in {"car_petrol_solo", "car_diesel_solo", "carpool_3p"}:
                    mitigation_steps.append("Keep car AC on Internal Recirculate mode (do not pull fresh exhaust air).")
                if rec_mask == "n95":
                    mitigation_steps.append("Wear a fitted N95 mask on platforms, walkways, and exposed road stretches.")
                elif req.budget_tier == "rs_0":
                    mitigation_steps.append("Keep windows closed in traffic bottlenecks and pick quieter side-streets.")
                rationale = (
                    f"Fixed commute stays at {rec_h:02d}:00; switching microenvironment and filtration cuts "
                    "on-road PM2.5 uptake."
                )
            else:
                opt_micro = base_micro
                rec_mask = _choose_mask(c_rec, req.budget_tier, act.current_mask, sensitive)
                if rec_mask == "n95":
                    mitigation_steps.append("Use a child/adult fitted N95 mask during the roadside wait.")
                elif req.budget_tier == "rs_0":
                    mitigation_steps.append("Keep wait time right before pickup to under 3 minutes.")
                mitigation_steps.append("Stand 5 meters back from the curb/bus exhaust zone while waiting.")
                rationale = f"Fixed commitment remains at {rec_h:02d}:00 with roadside timing and mask mitigation."
        else:
            # Flexible commitment
            is_primary_slider_target = (
                req.walk_override_hour is not None
                and not walk_override_applied
                and (act.activity_level in PRIMARY_FLEX_LEVELS or act == req.activities[-1])
            )
            if is_primary_slider_target and req.walk_override_hour is not None:
                rec_h = req.walk_override_hour
                walk_override_applied = True
            else:
                rec_h = best_h

            c_rec = hourly[rec_h].pm2_5
            naqi_rec = hourly[rec_h].cpcb_naqi
            rec_mask = act.current_mask

            if not golden.has_meaningful_window and req.walk_override_hour is None and sensitive:
                opt_micro = "indoor_sealed" if req.budget_tier != "rs_0" else "indoor_shut"
                badge = "FLEXIBLE • INDOOR"
                mitigation_steps.append("Outdoor PM2.5 stays flatly elevated today (<15% dip); move exercise inside the Sanctuary Room.")
                mitigation_steps.append("Do light stretching or indoor walking instead of heavy outdoor breathing.")
                rationale = "Honesty rule triggered: no meaningful daytime drop, so vigorous activity moves indoors."
            else:
                opt_micro = "walk_sidewalk"
                if req.walk_override_hour is not None and is_primary_slider_target:
                    badge = "WHAT-IF • TESTED"
                elif rec_h != orig_h:
                    badge = "FLEXIBLE • SHIFTED"
                else:
                    badge = "FLEXIBLE • KEPT"

                if rec_h != orig_h:
                    mitigation_steps.append(
                        f"Shift from {orig_h:02d}:00 ({c_orig} ug/m3) to {rec_h:02d}:00 ({c_rec} ug/m3)."
                    )
                else:
                    mitigation_steps.append(f"Timing at {rec_h:02d}:00 already sits in a lower-exposure slot.")

                if c_rec > 90.0 and req.budget_tier != "rs_0":
                    rec_mask = "n95"
                    mitigation_steps.append("Air remains Poor/Very Poor even midday—add a fitted N95 mask.")
                else:
                    mitigation_steps.append("Pick tree-lined lanes away from main arterial intersections.")

                rationale = (
                    f"Flexible slot evaluated at {rec_h:02d}:00 where boundary layer is "
                    f"{hourly[rec_h].boundary_layer_height:.0f} m."
                )

        opt_dose = compute_inhaled_dose_ug(c_rec, opt_micro, act.activity_level, act.duration_min, rec_mask)
        avoided = round(base_dose - opt_dose, 2)
        total_base += base_dose
        total_opt += opt_dose

        kappa_base = float(CONSTANTS["microenv_multipliers"][base_micro])
        kappa_opt = float(CONSTANTS["microenv_multipliers"][opt_micro])
        v_e = float(CONSTANTS["usepa_ventilation_m3_hr"].get(act.activity_level, 1.25))
        eta_base = float(CONSTANTS["mask_filtration_efficiency"][act.current_mask])
        eta_opt = float(CONSTANTS["mask_filtration_efficiency"][rec_mask])
        dt_hr = act.duration_min / 60.0

        substitutions.append(
            f"{act.name}: Base = {c_orig} * {kappa_base} * {v_e} * {dt_hr:.2f}h * (1-{eta_base}) = {base_dose} ug | "
            f"Opt = {c_rec} * {kappa_opt} * {v_e} * {dt_hr:.2f}h * (1-{eta_opt}) = {opt_dose} ug (Saved {avoided} ug)"
        )

        results.append(
            RoutineItemResult(
                id=act.id,
                name=act.name,
                member_name=act.member_name,
                flexibility=act.flexibility,
                badge=badge,
                original_hour=orig_h,
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
                mitigation_steps=mitigation_steps,
                rationale=rationale,
            )
        )

    return results, round(total_base, 2), round(total_opt, 2), substitutions


def score_sanctuary(req: PlanRequest, snapshot: AirSnapshotResponse) -> SanctuaryPlan:
    """Rank rooms for Clean Air Sanctuary and compute window open/shut protocol + IAQ hacks."""
    rooms = req.rooms if req.rooms else DEFAULT_ROOMS
    scored: list[RoomScore] = []

    for r in rooms:
        score = (
            100
            - 15 * r.ext_windows
            - (25 if r.road_facing else 0)
            - (25 if r.kitchen_adjacent else 0)
            - (10 if r.large_volume else 0)
        )
        reasons = []
        if not r.road_facing:
            reasons.append("away from street exhaust")
        else:
            reasons.append("road-facing infiltration penalty (-25)")
        if not r.kitchen_adjacent:
            reasons.append("isolated from cooking smoke")
        else:
            reasons.append("adjacent to kitchen (-25)")
        if r.ext_windows <= 1:
            reasons.append(f"low leak surface ({r.ext_windows} ext window)")
        scored.append(
            RoomScore(
                name=r.name,
                score=score,
                ext_windows=r.ext_windows,
                road_facing=r.road_facing,
                kitchen_adjacent=r.kitchen_adjacent,
                large_volume=r.large_volume,
                is_sanctuary=False,
                reason="; ".join(reasons),
            )
        )

    scored.sort(key=lambda item: item.score, reverse=True)
    scored[0].is_sanctuary = True
    sanctuary_name = scored[0].name

    # Window ventilation math comparing outdoor daytime minimum against modeled indoor proxy.
    day_points = snapshot.hourly[7:19]
    min_pt = min(day_points, key=lambda p: p.pm2_5)
    mean_out_24h = sum(p.pm2_5 for p in snapshot.hourly) / 24.0
    infiltration = 0.28 if req.budget_tier != "rs_0" else 0.50
    modeled_indoor_base = round(mean_out_24h * infiltration, 1)
    modeled_post_cooking = round(modeled_indoor_base + 220.0, 1)

    if min_pt.pm2_5 <= 90.0:
        end_hr = min(23, min_pt.hour + 1)
        window_advice = WindowVentilationAdvice(
            action="timed_open",
            open_window_start_hour=min_pt.hour,
            open_window_end_hour=end_hr,
            duration_minutes=20,
            outdoor_min_pm25=min_pt.pm2_5,
            modeled_indoor_baseline_pm25=modeled_indoor_base,
            modeled_post_cooking_pm25=modeled_post_cooking,
            guidance=(
                f"Open non-road-facing windows for 20 minutes around {min_pt.hour:02d}:00-{end_hr:02d}:00 "
                f"(outdoor drops to {min_pt.pm2_5} ug/m3) to flush CO2 and cooking fumes; shut tight by sunset."
            ),
        )
    else:
        window_advice = WindowVentilationAdvice(
            action="keep_shut_exhaust",
            open_window_start_hour=None,
            open_window_end_hour=None,
            duration_minutes=0,
            outdoor_min_pm25=min_pt.pm2_5,
            modeled_indoor_baseline_pm25=modeled_indoor_base,
            modeled_post_cooking_pm25=modeled_post_cooking,
            guidance=(
                f"Keep exterior windows shut today: even at the lowest hour ({min_pt.hour:02d}:00), "
                f"outdoor PM2.5 ({min_pt.pm2_5} ug/m3) exceeds modeled sealed indoor air (~{modeled_indoor_base} ug/m3). "
                "Vent kitchen tadka strictly via closed kitchen door + exhaust fan for 15 min."
            ),
        )

    limit_inr = int(CONSTANTS["budget_tier_limits_inr"][req.budget_tier])
    hacks = [h for h in CONSTANTS["iaq_hacks"] if int(h["max_cost_inr"]) <= limit_inr]

    alerts: list[str] = []
    if req.uses_agarbatti_or_coils:
        alerts.append("Detected agarbatti/mosquito coil use: pause indoor burning immediately on elevated-AQI days.")
    if req.dry_sweeps:
        alerts.append("Switch from dry jhadu sweeping to damp wet-mopping (pochha) to prevent dust resuspension.")
    if any("asthma" in m.conditions or "copd" in m.conditions for m in req.members):
        alerts.append("Keep prescribed rescue inhaler / reliever medication accessible in the Sanctuary Room.")

    if req.user_category == "delivery_riders" or any(a.is_work_shift for a in req.activities):
        alerts.append("Rider recovery: shake out helmet & dusty outer jacket outside entry door and rinse nose/face after shift.")
    elif req.user_category == "seniors" or any(m.age >= 65 for m in req.members):
        alerts.append("Senior protection: avoid cold outdoor drafts before 9 AM and keep Sanctuary Room gently insulated.")
    elif req.user_category == "students_kids" or any(m.age <= 18 for m in req.members):
        alerts.append("Student/kid routine: keep study desk away from street-facing windows and wipe dusty school shoes at the door.")
    else:
        alerts.append("Commuter home setup: seal front-door corridor leaks and ventilate interior rooms only during midday dips.")

    return SanctuaryPlan(
        sanctuary_room=sanctuary_name,
        room_scores=scored,
        window_advice=window_advice,
        co2_safety_note="Leave an interior door slightly ajar overnight so indoor CO2 does not build up while sleeping.",
        no_houseplants_note="Indoor houseplants do not remove meaningful PM2.5 in real homes; focus on source control, sealing gaps, and filtration.",
        applicable_hacks=hacks,
        personalized_alerts=alerts,
    )


def compute_emit_less(req: PlanRequest) -> EmitLessLedger:
    """Compute Ledger 2 (ARAI / WRI India transport CO2e and tailpipe PM2.5 savings)."""
    arai_map = CONSTANTS["arai_transport_emissions"]
    base_spec = arai_map.get(req.commute_mode, arai_map["car_petrol_solo"])
    target_spec = arai_map.get(req.target_commute_mode, arai_map["electric_metro"])

    co2_saved_g = round(req.commute_km * (float(base_spec["co2_g_pkm"]) - float(target_spec["co2_g_pkm"])), 1)
    co2_saved_kg = round(co2_saved_g / 1000.0, 3)
    tailpipe_pm25_mg = round(req.commute_km * (float(base_spec["pm25_mg_pkm"]) - float(target_spec["pm25_mg_pkm"])), 1)

    substitutions = [
        f"CO2e Saved = {req.commute_km} km * ({base_spec['co2_g_pkm']} - {target_spec['co2_g_pkm']}) g/pkm = {co2_saved_g} g ({co2_saved_kg} kg)",
        f"Tailpipe PM2.5 Saved = {req.commute_km} km * ({base_spec['pm25_mg_pkm']} - {target_spec['pm25_mg_pkm']}) mg/pkm = {tailpipe_pm25_mg} mg",
    ]
    if req.commute_mode == req.target_commute_mode:
        substitutions.append("Same transport mode kept (e.g., fixed work vehicle); tailpipe counterfactual savings = 0.")

    return EmitLessLedger(
        baseline_mode=req.commute_mode,
        target_mode=req.target_commute_mode,
        baseline_mode_label=base_spec["label"],
        target_mode_label=target_spec["label"],
        commute_km=req.commute_km,
        co2_saved_g=co2_saved_g,
        co2_saved_kg=co2_saved_kg,
        tailpipe_pm25_saved_mg=tailpipe_pm25_mg,
        label="Modeled Estimate",
        formula_summary="Delta CO2e (g) = km * (EF_CO2_base - EF_CO2_new); Delta Tailpipe PM2.5 (mg) = km * (EF_PM_base - EF_PM_new)",
        substitutions=substitutions,
        limitations="Uses ARAI / WRI India average per-passenger-km emission factors; actual fuel efficiency, occupancy, and traffic idling vary.",
    )


def build_profile_risk_summary(
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    breathe_less: BreatheLessLedger,
    emit_less: EmitLessLedger,
) -> ProfileRiskSummary:
    """Compute category-specific NAQI thresholds, lung intake, risk banner, and tailored guidance."""
    all_conditions = {c for m in req.members for c in m.conditions}
    if req.user_category is not None:
        key = req.user_category
    elif any(a.is_work_shift for a in req.activities) or "outdoor_worker" in all_conditions:
        key = "delivery_riders"
    elif any(m.age >= 60 or "elderly" in m.conditions or "copd" in m.conditions or "cardiac" in m.conditions for m in req.members):
        key = "seniors"
    elif any(m.age <= 22 or "child" in m.conditions or "student" in m.conditions for m in req.members):
        key = "students_kids"
    else:
        key = "adults_commuters"

    ve_map = CONSTANTS["usepa_ventilation_m3_hr"]
    peak_ve = round(max([float(ve_map.get(a.activity_level, 1.25)) for a in req.activities] or [1.25]), 2)
    total_outdoor_min = sum(a.duration_min for a in req.activities)
    gw = snapshot.golden_window
    pm25 = snapshot.current_pm25
    naqi = snapshot.current_naqi
    best_win = f"{gw.start_hour:02d}:00–{gw.end_hour:02d}:00"
    hrs = round(total_outdoor_min / 60.0, 1)

    if key == "delivery_riders":
        label = "Delivery Riders (Road-Exhaust Shift)"
        tier = "Road Plume 1.55x + High Intake"
        threshold = 100
        warning_active = naqi > threshold
        road_pm25 = round(pm25 * 1.55, 1)
        physiology = (
            f"Road-facing shifts (~{hrs}h outside at {peak_ve} m3/hr) experience ~{road_pm25} ug/m3 effective road dust "
            f"(1.55x ambient {pm25} ug/m3); daily modeled dose: {breathe_less.optimized_dose_ug} ug vs {breathe_less.baseline_dose_ug} ug."
        )
        if naqi > 200:
            risk_level = "Severe Road Exposure"
            risk_badge = "High Exposure Alert (NAQI > 100)"
            warning_banner = (
                f"High Roadside Smog Alert (Ambient NAQI {naqi}, Road ~{road_pm25} ug/m3): Wear a snug N95 mask on all 2-wheeler "
                f"runs and take 10-minute shaded breaks off main arterial roads."
            )
        elif warning_active:
            risk_level = "High Road Exposure"
            risk_badge = "Rider Warning (NAQI > 100)"
            warning_banner = (
                f"Delivery Rider Warning (NAQI {naqi} exceeds 100 limit): Roadside 1.55x exhaust elevates cumulative intake to "
                f"{breathe_less.baseline_dose_ug} ug—wear a fitted N95 and rest in shaded side-lanes."
            )
        else:
            risk_level = "Elevated Route Vigilance"
            risk_badge = "Road Plume Active (1.55x)"
            warning_banner = (
                f"Ambient NAQI {naqi} is below 100, but {hrs}h in tailpipe traffic still builds {breathe_less.baseline_dose_ug} ug "
                f"without protection—keep a fitted N95 handy in heavy traffic queues."
            )
        if gw.is_clean_air_day:
            headline = (
                f"Ambient air is {snapshot.current_category} (NAQI {naqi}), but {hrs}h in traffic puts effective road PM2.5 near "
                f"{road_pm25} ug/m3 — N95 protection cuts lung dose by {breathe_less.reduction_pct}%."
            )
        else:
            headline = (
                f"Fixed work shifts stay at ~{road_pm25} ug/m3 roadside dust — N95 + off-curb waits avoid "
                f"{breathe_less.dose_avoided_ug} ug PM2.5 ({breathe_less.reduction_pct}% less)."
            )
    elif key == "seniors":
        label = "Seniors (High Lung Sensitivity)"
        tier = "Sensitive Airways (Threshold NAQI > 100)"
        threshold = 100
        warning_active = naqi > threshold
        physiology = (
            f"65+ / COPD airways react earlier at {peak_ve} m3/hr walking pace: cold early-morning smog ({gw.morning_peak_pm25} ug/m3 peak) "
            f"strains breathing & heart rate well before general adult alerts trigger."
        )
        if naqi > 200:
            risk_level = "High Cardiorespiratory Risk"
            risk_badge = "Senior Health Alert (NAQI > 100)"
            warning_banner = (
                f"Senior Health Alert (NAQI {naqi}): Skip all pre-9 AM outdoor walks, keep windows shut indoors, and keep prescribed "
                f"rescue inhalers / BP meds beside you."
            )
        elif warning_active:
            risk_level = "Elevated Senior Risk"
            risk_badge = "Senior Warning (NAQI > 100)"
            warning_banner = (
                f"Senior Precaution Active (NAQI {naqi} > 100 threshold): Avoid early-morning cold inversion walks—shift slow strolls to "
                f"{best_win} and wear an N95 for clinic travel."
            )
        else:
            risk_level = "Low Senior Risk"
            risk_badge = "Senior-Safe Threshold (<100)"
            warning_banner = (
                f"Safe range for seniors today (NAQI {naqi} <= 100): Enjoy gentle daytime walks at {best_win}, avoid chilly pre-dawn rush "
                f"hours, and breathe gently through the nose."
            )
        if gw.is_clean_air_day:
            headline = (
                f"Comfortable air for seniors today ({pm25} ug/m3) — prefer sunny midday strolls around {best_win} and keep inhalers handy."
            )
        elif gw.has_meaningful_window:
            headline = (
                f"Move senior walk out of cold 6–8 AM smog into warmer {best_win} ({round(gw.reduction_pct)}% cleaner) to avoid morning strain."
            )
        else:
            headline = "Elevated stagnant air today — pause outdoor senior walks and practice gentle indoor breathing."
    elif key == "students_kids":
        label = "Students & Kids (Developing Lungs)"
        tier = "Higher Uptake/kg (Threshold NAQI > 100)"
        threshold = 100
        warning_active = naqi > threshold
        physiology = (
            f"Growing lungs breathe faster per kg body weight (up to {peak_ve} m3/hr in sports/play) closer to vehicle exhaust height, "
            f"driving {breathe_less.baseline_dose_ug} ug baseline exposure if timed during traffic peaks."
        )
        if naqi > 200:
            risk_level = "High Youth Exposure"
            risk_badge = "School / Sports Alert (NAQI > 100)"
            warning_banner = (
                f"Student & Kid Alert (NAQI {naqi}): Move school assembly & outdoor sports indoors today; send a fitted mask for school commutes."
            )
        elif warning_active:
            risk_level = "Elevated Kid Risk"
            risk_badge = "Kids / Play Warning (NAQI > 100)"
            warning_banner = (
                f"Kids Precaution Triggered (NAQI {naqi} > 100 limit): Limit strenuous outdoor sprints, wait back from idling school buses, "
                f"and shift evening play toward {best_win}."
            )
        else:
            risk_level = "Low Youth Risk"
            risk_badge = "School-Play Friendly (<100)"
            warning_banner = (
                f"Good day for school sports & evening play (NAQI {naqi} <= 100): Keep pickup queues 5m back from idling buses."
            )
        if gw.is_clean_air_day:
            headline = (
                f"Healthy outdoor day for school commute & playground games ({pm25} ug/m3) — stand clear of bus exhaust queues."
            )
        elif gw.has_meaningful_window:
            headline = (
                f"Shift playground sports to {best_win} ({round(gw.reduction_pct)}% lower exposure) instead of rush-hour evening play."
            )
        else:
            headline = "Elevated pollution all day — hold school PE indoors and avoid intense outdoor sprints."
    else:
        label = "Adults & Daily Commuters"
        tier = "Standard CPCB Band (Threshold NAQI > 150)"
        threshold = 150
        warning_active = naqi > threshold
        co2_str = f"{emit_less.co2_saved_kg} kg" if emit_less.co2_saved_g >= 1000 else f"{emit_less.co2_saved_g} g"
        physiology = (
            f"Healthy adult lungs ({peak_ve} m3/hr brisk walk) face lower acute risk under NAQI 150—biggest gains come from optimizing "
            f"workout hour and shifting {emit_less.commute_km} km car commute ({co2_str} CO2 saved)."
        )
        if naqi > 200:
            risk_level = "High Commuter Strain"
            risk_badge = "Outdoor Warning (NAQI > 150)"
            warning_banner = (
                f"Commuter & Workout Warning (NAQI {naqi} > 150 limit): Shift brisk cardio indoors, wear N95 in transit, and keep car AC on recirculate."
            )
        elif warning_active:
            risk_level = "Elevated Commuter Risk"
            risk_badge = "Advisory Active (NAQI > 150)"
            warning_banner = (
                f"Adult Advisory (NAQI {naqi} crossed 150): Move morning runs to {best_win} and take {emit_less.target_mode_label} or AC-recirculate."
            )
        else:
            risk_level = "Low Adult Risk"
            risk_badge = "Standard Threshold (<=150)"
            warning_banner = (
                f"Within standard adult threshold (NAQI {naqi} <= 150): Normal commutes & outdoor walks are fine; switching to "
                f"{emit_less.target_mode_label} avoids {co2_str} CO2 today."
            )
        if gw.is_clean_air_day:
            headline = (
                f"Clean air for adult workouts today (NAQI {naqi}); shifting {emit_less.commute_km} km commute saves {co2_str} CO2."
            )
        elif gw.has_meaningful_window:
            headline = (
                f"Best workout window for adults: {best_win} ({round(gw.reduction_pct)}% cleaner than morning rush)."
            )
        else:
            headline = "Elevated smog exceeds adult threshold — move cardio indoors and seal traffic cabin air."

    return ProfileRiskSummary(
        profile_key=key,
        profile_label=label,
        sensitivity_tier=tier,
        warning_threshold_naqi=threshold,
        warning_active=warning_active,
        risk_level=risk_level,
        risk_badge=risk_badge,
        warning_banner=warning_banner,
        peak_ventilation_m3_hr=peak_ve,
        total_outdoor_min=total_outdoor_min,
        tailored_hero_headline=headline,
        physiology_note=physiology,
    )


def _collect_grounded_numbers(bundle: EvidenceBundle) -> list[float]:
    """Collect numeric constants and bundle outputs for downstream LLM numeric verification."""
    nums: set[float] = {
        0.0, 2.0, 2.5, 10.0, 13.0, 15.0, 20.0, 95.0, 330.0, 500.0, 2200.0,
        float(bundle.air_snapshot.current_hour),
        float(bundle.air_snapshot.current_pm25),
        float(bundle.air_snapshot.current_naqi),
        float(bundle.air_snapshot.morning_inversion_ceiling_m),
        float(bundle.air_snapshot.golden_window.start_hour),
        float(bundle.air_snapshot.golden_window.end_hour),
        float(bundle.air_snapshot.golden_window.mean_pm25),
        float(bundle.air_snapshot.golden_window.mean_naqi),
        float(bundle.air_snapshot.golden_window.morning_peak_pm25),
        float(bundle.air_snapshot.golden_window.reduction_pct),
        float(bundle.breathe_less.baseline_dose_ug),
        float(bundle.breathe_less.optimized_dose_ug),
        float(bundle.breathe_less.dose_avoided_ug),
        float(bundle.breathe_less.reduction_pct),
        float(bundle.breathe_less.cigarettes_avoided),
        float(bundle.emit_less.commute_km),
        float(bundle.emit_less.co2_saved_g),
        float(bundle.emit_less.co2_saved_kg),
        float(bundle.emit_less.tailpipe_pm25_saved_mg),
        float(bundle.sanctuary_plan.window_advice.outdoor_min_pm25),
        float(bundle.sanctuary_plan.window_advice.modeled_indoor_baseline_pm25),
        float(bundle.sanctuary_plan.window_advice.modeled_post_cooking_pm25),
        float(bundle.sanctuary_plan.window_advice.duration_minutes),
    }
    for pt in bundle.air_snapshot.hourly:
        nums.update([float(pt.hour), float(pt.pm2_5), float(pt.pm10), float(pt.cpcb_naqi), float(pt.boundary_layer_height)])
    for item in bundle.routine_plan:
        nums.update([
            float(item.original_hour), float(item.recommended_hour), float(item.duration_min),
            float(item.original_pm25), float(item.recommended_pm25), float(item.original_naqi),
            float(item.recommended_naqi), float(item.baseline_dose_ug), float(item.optimized_dose_ug),
            float(item.dose_avoided_ug),
        ])
    for rm in bundle.sanctuary_plan.room_scores:
        nums.add(float(rm.score))
    if bundle.profile_summary:
        nums.update([
            float(bundle.profile_summary.peak_ventilation_m3_hr),
            float(bundle.profile_summary.warning_threshold_naqi),
        ])
    return sorted(nums)


def build_evidence_bundle(
    req: PlanRequest,
    raw_payload: dict[str, Any],
    current_hour: int | None = None,
    emergency_alert: bool = False,
    emergency_message: str | None = None,
) -> EvidenceBundle:
    """Assemble the complete deterministic EvidenceBundle for PRANA-AI."""
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
        formula_summary="D (ug) = (C_out * kappa_microenv) * V_E * dt_hr * (1 - eta_mask); Cigarettes = Delta D / 330 ug",
        substitutions=dose_subs,
        limitations="Modeled exposure proxy using gridded Open-Meteo outdoor PM2.5, USEPA breathing rates, and lab mask/microenvironment factors—not a wearable sensor reading.",
    )

    sanctuary_plan = score_sanctuary(req, snapshot)
    emit_less = compute_emit_less(req)
    profile_summary = build_profile_risk_summary(req, snapshot, breathe_less, emit_less)

    bundle = EvidenceBundle(
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
    )
    bundle.grounded_numbers = _collect_grounded_numbers(bundle)
    return bundle
