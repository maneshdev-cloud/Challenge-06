"""USEPA duration-integrated PM2.5 dosimetry, activity scheduling, and ARAI emissions."""

from __future__ import annotations

from typing import Any

from air_quality import ENGINE_PARAMS, compute_pm25_naqi
from data_fetcher import CONSTANTS
from schemas import (
    AirSnapshotResponse,
    EmitLessLedger,
    HourlyAirPoint,
    MaskType,
    PlanRequest,
    RoutineItemResult,
)

PRIMARY_FLEX_LEVELS = {"elderly_walk", "child_play", "running_or_outdoor_work", "brisk_walk"}
SENSITIVE_CONDITIONS = {"asthma", "copd", "cardiac", "elderly", "child", "hypertension"}


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


def _extract_next_day_pm25(raw_payload: dict[str, Any] | None) -> list[float] | None:
    """Extract day-2 hourly PM2.5 concentrations if multiday_raw spans >= 48 hours."""
    if not raw_payload:
        return None
    multi = raw_payload.get("multiday_raw")
    if not multi or len(multi.get("pm2_5", [])) < 48:
        return None
    return [float(x) for x in multi["pm2_5"][24:48]]


def _evaluate_interval_exposure(
    hourly_points: list[HourlyAirPoint],
    start_hour: int,
    duration_min: int,
    microenv_key: str,
    activity_level: str,
    mask: MaskType,
    *,
    next_day_pm25: list[float] | None = None,
) -> tuple[float, float, int, float]:
    """Integrate exposure hour-by-hour without wrapping late-night tasks onto hour 0 of today."""
    if duration_min <= 0:
        pt = hourly_points[max(0, min(23, start_hour))]
        return 0.0, pt.pm2_5, pt.cpcb_naqi, pt.pm2_5

    remaining = duration_min
    step_idx = max(0, min(23, start_hour))
    total_dose = 0.0
    weighted_pm25 = 0.0
    weighted_naqi = 0.0
    peak_pm25 = 0.0

    while remaining > 0:
        chunk_min = min(60, remaining)
        if step_idx < 24:
            pt = hourly_points[step_idx]
            c_pm25, c_naqi = pt.pm2_5, pt.cpcb_naqi
        elif next_day_pm25 and (step_idx - 24) < len(next_day_pm25):
            c_pm25 = next_day_pm25[step_idx - 24]
            c_naqi, _ = compute_pm25_naqi(c_pm25)
        else:
            # Never wrap late-night hours backward onto today's stale 00:00 data.
            pt = hourly_points[23]
            c_pm25, c_naqi = pt.pm2_5, pt.cpcb_naqi

        total_dose += compute_inhaled_dose_ug(
            c_pm25, microenv_key, activity_level, chunk_min, mask
        )
        weighted_pm25 += c_pm25 * chunk_min
        weighted_naqi += c_naqi * chunk_min
        peak_pm25 = max(peak_pm25, c_pm25)
        remaining -= chunk_min
        step_idx += 1

    mean_pm25 = round(weighted_pm25 / duration_min, 1)
    mean_naqi = int(round(weighted_naqi / duration_min))
    return round(total_dose, 2), mean_pm25, mean_naqi, round(peak_pm25, 1)


def compute_interval_dose_ug(
    hourly_points: list[HourlyAirPoint],
    start_hour: int,
    duration_min: int,
    microenv_key: str,
    activity_level: str,
    mask: MaskType,
    *,
    next_day_pm25: list[float] | None = None,
) -> tuple[float, float, int]:
    """Return duration-integrated (total_dose_ug, mean_pm25, mean_naqi)."""
    dose, mean_pm25, mean_naqi, _ = _evaluate_interval_exposure(
        hourly_points,
        start_hour,
        duration_min,
        microenv_key,
        activity_level,
        mask,
        next_day_pm25=next_day_pm25,
    )
    return dose, mean_pm25, mean_naqi


def _find_best_start_hour_for_duration(
    hourly_points: list[HourlyAirPoint],
    duration_min: int,
    microenv_key: str,
    activity_level: str,
    mask: MaskType,
    *,
    next_day_pm25: list[float] | None = None,
) -> int:
    """Optimize flexible start hour across daytime slots via exact duration-integrated dose."""
    last_start = max(7, 20 - max(1, (duration_min + 59) // 60))
    best_start = 13
    best_dose = float("inf")
    for start_h in range(7, last_start + 1):
        dose, _, _, _ = _evaluate_interval_exposure(
            hourly_points,
            start_h,
            duration_min,
            microenv_key,
            activity_level,
            mask,
            next_day_pm25=next_day_pm25,
        )
        if dose < best_dose:
            best_dose = dose
            best_start = start_h
    return best_start


def _is_member_sensitive(member: Any) -> bool:
    """Check one HouseholdMember for pediatric/elderly age or sensitive condition tags."""
    ages = ENGINE_PARAMS["age_cutoffs"]
    conds = {c.strip().lower() for c in member.conditions}
    return (
        member.age <= int(ages["sensitive_child_max"])
        or member.age >= int(ages["sensitive_elderly_min"])
        or bool(conds & SENSITIVE_CONDITIONS)
    )


def _has_sensitive_member(req: PlanRequest, member_name: str) -> bool:
    """Return True if the named member (or household fallback) is respiratory-sensitive."""
    for m in req.members:
        if m.name == member_name:
            return _is_member_sensitive(m)
    return any(_is_member_sensitive(m) for m in req.members)


def _choose_mask(
    peak_pm25: float,
    budget_tier: str,
    current_mask: MaskType,
    sensitive: bool,
    *,
    is_work_shift: bool = False,
) -> MaskType:
    """Select cost-feasible mask upgrade based on interval peak PM2.5 thresholds."""
    if budget_tier == "rs_0":
        return current_mask
    thresholds = ENGINE_PARAMS["mask_thresholds_pm25"]
    if is_work_shift and peak_pm25 >= float(thresholds["work_shift_n95"]):
        return "n95"
    if peak_pm25 > float(thresholds["general_n95"]) or (
        sensitive and peak_pm25 > float(thresholds["sensitive_n95"])
    ):
        return "n95"
    return current_mask


def _schedule_fixed_activity(
    act: Any,
    req: PlanRequest,
    peak_pm25: float,
    sensitive: bool,
    commute_micros: tuple[str, str],
) -> tuple[str, MaskType, list[str], str]:
    """Generate harm-reduction steps for a fixed work, commute, or school activity."""
    base_micro, target_commute_micro = commute_micros
    arai_map = CONSTANTS["arai_transport_emissions"]
    steps: list[str] = []

    if act.is_work_shift:
        rec_mask = _choose_mask(
            peak_pm25, req.budget_tier, act.current_mask, True, is_work_shift=True
        )
        steps.append(
            "Wear a well-fitted N95/FFP2 respirator across peak corridors."
            if rec_mask == "n95"
            else "Use a snug wrap and take hydration breaks off arterial roads."
        )
        steps.append("Wait for orders 10-15m away from idling diesel/auto queues.")
        steps.append("Rinse face/nose with plain water post-shift; recover in Sanctuary Room.")
        return (
            base_micro,
            rec_mask,
            steps,
            (
                f"Fixed work shift stays at {act.planned_hour:02d}:00; focuses on N95 filtration "
                "and off-curb buffers rather than impractical stay-home advice."
            ),
        )

    if act.is_commute:
        rec_mask = _choose_mask(peak_pm25, req.budget_tier, act.current_mask, sensitive)
        base_spec = arai_map.get(req.commute_mode, arai_map["car_petrol_solo"])
        target_spec = arai_map.get(req.target_commute_mode, arai_map["electric_metro"])
        if req.target_commute_mode != req.commute_mode:
            steps.append(f"Switch mode from {base_spec['label']} to {target_spec['label']}.")
        elif req.commute_mode in {"car_petrol_solo", "car_diesel_solo", "carpool_3p"}:
            steps.append("Keep car AC on Internal Recirculate mode in congested stretches.")
        if rec_mask == "n95":
            steps.append("Wear a fitted N95 mask on platforms, walkways, and exposed roads.")
        elif req.budget_tier == "rs_0":
            steps.append("Keep windows closed in congestion and pick quieter side-streets.")
        return (
            target_commute_micro,
            rec_mask,
            steps,
            (
                f"Fixed commute stays at {act.planned_hour:02d}:00; microenvironment and mask "
                "mitigation reduce on-road PM2.5 uptake."
            ),
        )

    rec_mask = _choose_mask(peak_pm25, req.budget_tier, act.current_mask, sensitive)
    if rec_mask == "n95":
        steps.append("Use a child/adult fitted N95 mask during the roadside wait.")
    elif req.budget_tier == "rs_0":
        steps.append("Keep wait time right before pickup under 3 minutes.")
    steps.append("Stand 5 meters back from curb/bus exhaust zones while waiting.")
    return (
        base_micro,
        rec_mask,
        steps,
        f"Fixed commitment remains at {act.planned_hour:02d}:00 with roadside mitigation.",
    )


def _schedule_flexible_activity(
    act: Any,
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    sensitive: bool,
    slot_info: tuple[int, float, float, float, bool],
) -> tuple[str, str, MaskType, list[str], str]:
    """Shift flexible outdoor activity to cleanest slot or Sanctuary Room."""
    rec_h, c_orig, c_rec, c_rec_peak, is_slider_target = slot_info
    golden = snapshot.golden_window
    steps: list[str] = []
    rec_mask: MaskType = act.current_mask

    if not golden.has_meaningful_window and req.walk_override_hour is None and sensitive:
        opt_micro = "indoor_sealed" if req.budget_tier != "rs_0" else "indoor_shut"
        return (
            "FLEXIBLE • INDOOR",
            opt_micro,
            rec_mask,
            [
                "Outdoor PM2.5 stays flat (<15% dip); move exercise inside the Sanctuary Room.",
                "Do light stretching or indoor walking instead of outdoor exertion.",
            ],
            (
                "Honesty rule triggered: no meaningful daytime drop, "
                "so vigorous exercise moves inside."
            ),
        )

    if req.walk_override_hour is not None and is_slider_target:
        badge = "WHAT-IF • TESTED"
    elif rec_h != act.planned_hour:
        badge = "FLEXIBLE • SHIFTED"
    else:
        badge = "FLEXIBLE • KEPT"

    if rec_h != act.planned_hour:
        steps.append(
            f"Shift from {act.planned_hour:02d}:00 ({c_orig} ug/m3 avg) "
            f"to {rec_h:02d}:00 ({c_rec} ug/m3 avg)."
        )
    else:
        steps.append(f"Timing at {rec_h:02d}:00 already sits in a lower-exposure slot.")

    midday_cutoff = float(ENGINE_PARAMS["mask_thresholds_pm25"]["midday_flexible_n95"])
    if c_rec_peak > midday_cutoff and req.budget_tier != "rs_0":
        rec_mask = "n95"
        steps.append("Peak outdoor dust crosses Poor/Very Poor—add a fitted N95 mask.")
    else:
        steps.append("Pick tree-lined lanes away from main arterial intersections.")

    return (
        badge,
        "walk_sidewalk",
        rec_mask,
        steps,
        (
            f"Flexible slot optimized over {act.duration_min} min from {rec_h:02d}:00 "
            f"(mixing height {snapshot.hourly[rec_h].boundary_layer_height:.0f} m)."
        ),
    )


def _format_dose_substitution(
    act: Any,
    base_spec: tuple[str, float, float, MaskType],
    opt_spec: tuple[str, float, float, MaskType],
) -> str:
    """Format formula substitution string for Show Math transparency."""
    base_micro, c_orig, base_dose, orig_mask = base_spec
    opt_micro, c_rec, opt_dose, rec_mask = opt_spec
    v_e = float(CONSTANTS["usepa_ventilation_m3_hr"].get(act.activity_level, 1.25))
    k_b = float(CONSTANTS["microenv_multipliers"][base_micro])
    k_o = float(CONSTANTS["microenv_multipliers"][opt_micro])
    eta_b = float(CONSTANTS["mask_filtration_efficiency"][orig_mask])
    eta_o = float(CONSTANTS["mask_filtration_efficiency"][rec_mask])
    dt_hr = act.duration_min / 60.0
    avoided = round(base_dose - opt_dose, 2)
    return (
        f"{act.name} ({act.duration_min}m): Base avg {c_orig}*{k_b}*{v_e}*{dt_hr:.2f}h"
        f"*(1-{eta_b})={base_dose} ug | Opt avg {c_rec}*{k_o}*{v_e}*{dt_hr:.2f}h"
        f"*(1-{eta_o})={opt_dose} ug (Saved {avoided} ug)"
    )


def _schedule_single_activity(
    act: Any,
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    ctx: tuple[str, str, bool, list[float] | None],
) -> tuple[RoutineItemResult, float, float, str, bool]:
    """Optimize and evaluate one activity item, returning result and dose totals."""
    base_commute_micro, target_commute_micro, allow_slider, next_day_pm25 = ctx
    hourly = snapshot.hourly
    sensitive = _has_sensitive_member(req, act.member_name)
    base_micro = base_commute_micro if act.is_commute else "walk_sidewalk"
    base_dose, c_orig, naqi_orig, c_orig_peak = _evaluate_interval_exposure(
        hourly,
        act.planned_hour,
        act.duration_min,
        base_micro,
        act.activity_level,
        act.current_mask,
        next_day_pm25=next_day_pm25,
    )

    used_slider = False
    if act.flexibility == "fixed":
        rec_h = act.planned_hour
        badge = "FIXED • MITIGATED"
        opt_micro, rec_mask, steps, rationale = _schedule_fixed_activity(
            act, req, c_orig_peak, sensitive, (base_micro, target_commute_micro)
        )
    else:
        is_slider = allow_slider and req.walk_override_hour is not None
        if is_slider and req.walk_override_hour is not None:
            rec_h = req.walk_override_hour
            used_slider = True
        else:
            rec_h = _find_best_start_hour_for_duration(
                hourly,
                act.duration_min,
                "walk_sidewalk",
                act.activity_level,
                act.current_mask,
                next_day_pm25=next_day_pm25,
            )

        _, c_rec_prev, _, c_rec_peak = _evaluate_interval_exposure(
            hourly,
            rec_h,
            act.duration_min,
            "walk_sidewalk",
            act.activity_level,
            act.current_mask,
            next_day_pm25=next_day_pm25,
        )
        badge, opt_micro, rec_mask, steps, rationale = _schedule_flexible_activity(
            act, req, snapshot, sensitive, (rec_h, c_orig, c_rec_prev, c_rec_peak, is_slider)
        )

    opt_dose, c_rec, naqi_rec, _ = _evaluate_interval_exposure(
        hourly,
        rec_h,
        act.duration_min,
        opt_micro,
        act.activity_level,
        rec_mask,
        next_day_pm25=next_day_pm25,
    )
    sub_text = _format_dose_substitution(
        act,
        (base_micro, c_orig, base_dose, act.current_mask),
        (opt_micro, c_rec, opt_dose, rec_mask),
    )
    item = RoutineItemResult(
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
        dose_avoided_ug=round(base_dose - opt_dose, 2),
        mitigation_steps=steps,
        rationale=rationale,
    )
    return item, base_dose, opt_dose, sub_text, used_slider


def _schedule_activities(
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    next_day_pm25: list[float] | None = None,
) -> tuple[list[RoutineItemResult], float, float, list[str]]:
    """Run constraint-aware scheduling and hourly-integrated USEPA dosimetry."""
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
        allow_slider = (
            req.walk_override_hour is not None
            and not walk_override_applied
            and (act.activity_level in PRIMARY_FLEX_LEVELS or act == req.activities[-1])
        )
        item, base_dose, opt_dose, sub_text, used_slider = _schedule_single_activity(
            act,
            req,
            snapshot,
            (base_commute_micro, target_commute_micro, allow_slider, next_day_pm25),
        )
        walk_override_applied = walk_override_applied or used_slider
        total_base += base_dose
        total_opt += opt_dose
        substitutions.append(sub_text)
        results.append(item)

    return results, round(total_base, 2), round(total_opt, 2), substitutions


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
    phone_charges = round(max(0.0, co2_saved_g) / float(ENGINE_PARAMS["phone_charge_co2_g"]))

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
        phone_charges_saved=phone_charges,
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
