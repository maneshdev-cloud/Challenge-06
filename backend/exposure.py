"""USEPA duration-integrated PM2.5 dosimetry and constraint-aware activity scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from air_quality import ENGINE_PARAMS, compute_hourly_naqi, compute_pm25_naqi
from emissions import compute_emit_less
from geo_india import CONSTANTS
from schemas import (
    AirSnapshotResponse,
    HourlyAirPoint,
    MaskType,
    PlanRequest,
    RoutineItemResult,
)

__all__ = [
    "PRIMARY_FLEX_LEVELS",
    "SENSITIVE_CONDITIONS",
    "compute_emit_less",
    "compute_inhaled_dose_ug",
    "compute_interval_dose_ug",
    "extract_next_day_pm25",
    "extract_next_day_series",
    "schedule_activities",
]

PRIMARY_FLEX_LEVELS = {"elderly_walk", "child_play", "running_or_outdoor_work", "brisk_walk"}
SENSITIVE_CONDITIONS = {"asthma", "copd", "cardiac", "elderly", "child", "hypertension"}


@dataclass(frozen=True)
class _IntervalQuery:
    """Internal immutable exposure-window parameters."""

    start_hour: int
    duration_min: int
    microenv_key: str
    activity_level: str
    mask: MaskType


@dataclass(frozen=True)
class _ScheduleContext:
    """Per-plan routing and day-2 forecast context for activity scheduling."""

    base_commute_micro: str
    target_commute_micro: str
    allow_slider: bool
    next_day_pm25: list[float] | None
    next_day_naqi: list[int] | None = None


def compute_inhaled_dose_ug(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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


def extract_next_day_pm25(raw_payload: dict[str, Any] | None) -> list[float] | None:
    """Extract day-2 hourly PM2.5 concentrations if multiday_raw spans >= 48 hours."""
    if not raw_payload:
        return None
    multi = raw_payload.get("multiday_raw")
    if not multi or len(multi.get("pm2_5", [])) < 48:
        return None
    return [float(x) for x in multi["pm2_5"][24:48]]


def extract_next_day_series(
    raw_payload: dict[str, Any] | None,
) -> tuple[list[float] | None, list[int] | None]:
    """Extract day-2 PM2.5 and 3-pollutant NAQI arrays when multiday_raw spans >= 48h."""
    pm25 = extract_next_day_pm25(raw_payload)
    if not pm25 or not raw_payload:
        return pm25, None
    multi = raw_payload["multiday_raw"]
    pm10 = [float(x) for x in multi.get("pm10", [])[24:48]]
    no2 = [float(x) for x in multi.get("nitrogen_dioxide", [])[24:48]]
    if len(pm10) < 24 or len(no2) < 24:
        return pm25, [compute_pm25_naqi(c)[0] for c in pm25]
    naqi = [
        int(compute_hourly_naqi(pm25[i], pm10[i], no2[i])["cpcb_naqi"]) for i in range(len(pm25))
    ]
    return pm25, naqi


def _concentration_at_step(
    hourly_points: list[HourlyAirPoint],
    step_idx: int,
    next_day_pm25: list[float] | None,
    next_day_naqi: list[int] | None = None,
) -> tuple[float, int]:
    """Return (pm25, cpcb_naqi) without wrapping past midnight onto hour 0 of today."""
    if step_idx < 24:
        pt = hourly_points[step_idx]
        return pt.pm2_5, pt.cpcb_naqi
    offset = step_idx - 24
    if next_day_pm25 and offset < len(next_day_pm25):
        c_pm25 = next_day_pm25[offset]
        c_naqi = (
            next_day_naqi[offset]
            if next_day_naqi and offset < len(next_day_naqi)
            else compute_pm25_naqi(c_pm25)[0]
        )
        return c_pm25, c_naqi
    pt = hourly_points[23]
    return pt.pm2_5, pt.cpcb_naqi


def _evaluate_interval_exposure(
    hourly_points: list[HourlyAirPoint],
    query: _IntervalQuery,
    *,
    next_day_pm25: list[float] | None = None,
    next_day_naqi: list[int] | None = None,
) -> tuple[float, float, int, float]:
    """Integrate exposure hour-by-hour over a contiguous activity duration."""
    if query.duration_min <= 0:
        pt = hourly_points[max(0, min(23, query.start_hour))]
        return 0.0, pt.pm2_5, pt.cpcb_naqi, pt.pm2_5

    remaining = query.duration_min
    step_idx = max(0, min(23, query.start_hour))
    total_dose, weighted_pm25, weighted_naqi, peak_pm25 = 0.0, 0.0, 0.0, 0.0

    while remaining > 0:
        chunk_min = min(60, remaining)
        c_pm25, c_naqi = _concentration_at_step(
            hourly_points, step_idx, next_day_pm25, next_day_naqi
        )
        total_dose += compute_inhaled_dose_ug(
            c_pm25, query.microenv_key, query.activity_level, chunk_min, query.mask
        )
        weighted_pm25 += c_pm25 * chunk_min
        weighted_naqi += c_naqi * chunk_min
        peak_pm25 = max(peak_pm25, c_pm25)
        remaining -= chunk_min
        step_idx += 1

    mean_pm25 = round(weighted_pm25 / query.duration_min, 1)
    mean_naqi = int(round(weighted_naqi / query.duration_min))
    return round(total_dose, 2), mean_pm25, mean_naqi, round(peak_pm25, 1)


def compute_interval_dose_ug(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
        _IntervalQuery(start_hour, duration_min, microenv_key, activity_level, mask),
        next_day_pm25=next_day_pm25,
    )
    return dose, mean_pm25, mean_naqi


def _find_best_start_hour_for_duration(
    hourly_points: list[HourlyAirPoint],
    query_template: _IntervalQuery,
    *,
    next_day_pm25: list[float] | None = None,
) -> int:
    """Optimize flexible start hour across daytime slots via exact duration-integrated dose."""
    last_start = max(7, 20 - max(1, (query_template.duration_min + 59) // 60))
    best_start, best_dose = 13, float("inf")
    for start_h in range(7, last_start + 1):
        candidate = _IntervalQuery(
            start_h,
            query_template.duration_min,
            query_template.microenv_key,
            query_template.activity_level,
            query_template.mask,
        )
        dose, _, _, _ = _evaluate_interval_exposure(
            hourly_points, candidate, next_day_pm25=next_day_pm25
        )
        if dose < best_dose:
            best_dose, best_start = dose, start_h
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


def _schedule_work_shift(
    act: Any, req: PlanRequest, peak_pm25: float, base_micro: str
) -> tuple[str, MaskType, list[str], str]:
    """Build harm-reduction plan for a fixed outdoor work shift."""
    rec_mask = _choose_mask(peak_pm25, req.budget_tier, act.current_mask, True, is_work_shift=True)
    primary_step = (
        "Wear a well-fitted N95/FFP2 respirator across peak corridors."
        if rec_mask == "n95"
        else "Use a snug wrap and take hydration breaks off arterial roads."
    )
    steps = [
        primary_step,
        "Wait for orders 10-15m away from idling diesel/auto queues.",
        "Rinse face/nose with plain water post-shift; recover in Sanctuary Room.",
    ]
    rationale = (
        f"Fixed work shift stays at {act.planned_hour:02d}:00; focuses on N95 filtration "
        "and off-curb buffers rather than impractical stay-home advice."
    )
    return base_micro, rec_mask, steps, rationale


def _schedule_commute_activity(
    act: Any,
    req: PlanRequest,
    peak_pm25: float,
    sensitive: bool,
    target_commute_micro: str,
) -> tuple[str, MaskType, list[str], str]:
    """Build harm-reduction plan for a fixed daily commute."""
    arai_map = CONSTANTS["arai_transport_emissions"]
    rec_mask = _choose_mask(peak_pm25, req.budget_tier, act.current_mask, sensitive)
    base_spec = arai_map.get(req.commute_mode, arai_map["car_petrol_solo"])
    target_spec = arai_map.get(req.target_commute_mode, arai_map["electric_metro"])

    steps: list[str] = []
    if req.target_commute_mode != req.commute_mode:
        steps.append(f"Switch mode from {base_spec['label']} to {target_spec['label']}.")
    elif req.commute_mode in {"car_petrol_solo", "car_diesel_solo", "carpool_3p"}:
        steps.append("Keep car AC on Internal Recirculate mode in congested stretches.")
    if rec_mask == "n95":
        steps.append("Wear a fitted N95 mask on platforms, walkways, and exposed roads.")
    elif req.budget_tier == "rs_0":
        steps.append("Keep windows closed in congestion and pick quieter side-streets.")

    rationale = (
        f"Fixed commute stays at {act.planned_hour:02d}:00; microenvironment and mask "
        "mitigation reduce on-road PM2.5 uptake."
    )
    return target_commute_micro, rec_mask, steps, rationale


def _schedule_fixed_default(
    act: Any, req: PlanRequest, peak_pm25: float, sensitive: bool, base_micro: str
) -> tuple[str, MaskType, list[str], str]:
    """Build harm-reduction plan for school pickup/drop or general fixed waits."""
    rec_mask = _choose_mask(peak_pm25, req.budget_tier, act.current_mask, sensitive)
    steps: list[str] = []
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


def _schedule_fixed_activity(
    act: Any,
    req: PlanRequest,
    peak_pm25: float,
    sensitive: bool,
    commute_micros: tuple[str, str],
) -> tuple[str, MaskType, list[str], str]:
    """Dispatch a fixed activity to work-shift, commute, or roadside-wait planning."""
    base_micro, target_commute_micro = commute_micros
    if act.is_work_shift:
        return _schedule_work_shift(act, req, peak_pm25, base_micro)
    if act.is_commute:
        return _schedule_commute_activity(act, req, peak_pm25, sensitive, target_commute_micro)
    return _schedule_fixed_default(act, req, peak_pm25, sensitive, base_micro)


def _flexible_badge(req: PlanRequest, rec_h: int, planned_h: int, is_slider: bool) -> str:
    """Select UI status badge label for a scheduled flexible outdoor activity."""
    if req.walk_override_hour is not None and is_slider:
        return "WHAT-IF • TESTED"
    return "FLEXIBLE • SHIFTED" if rec_h != planned_h else "FLEXIBLE • KEPT"


def _indoor_override_result(
    req: PlanRequest, rec_mask: MaskType
) -> tuple[str, str, MaskType, list[str], str]:
    """Move vigorous sensitive-member workouts indoors on flat (<15% dip) pollution curves."""
    opt_micro = "indoor_sealed" if req.budget_tier != "rs_0" else "indoor_shut"
    return (
        "FLEXIBLE • INDOOR",
        opt_micro,
        rec_mask,
        [
            "Outdoor PM2.5 stays flat (<15% dip); move exercise inside the Sanctuary Room.",
            "Do light stretching or indoor walking instead of outdoor exertion.",
        ],
        "Honesty rule triggered: no meaningful daytime drop, so vigorous exercise moves inside.",
    )


def _schedule_flexible_activity(
    act: Any,
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    sensitive: bool,
    slot_info: tuple[int, float, float, float, bool],
) -> tuple[str, str, MaskType, list[str], str]:
    """Shift flexible outdoor activity to cleanest slot or Sanctuary Room."""
    rec_h, c_orig, c_rec, c_rec_peak, is_slider = slot_info
    rec_mask: MaskType = act.current_mask
    no_win = not snapshot.golden_window.has_meaningful_window
    if no_win and not is_slider and sensitive:
        return _indoor_override_result(req, rec_mask)

    steps = [
        (
            f"Shift from {act.planned_hour:02d}:00 ({c_orig} ug/m3 avg) "
            f"to {rec_h:02d}:00 ({c_rec} ug/m3 avg)."
        )
        if rec_h != act.planned_hour
        else f"Timing at {rec_h:02d}:00 already sits in a lower-exposure slot."
    ]
    midday_cutoff = float(ENGINE_PARAMS["mask_thresholds_pm25"]["midday_flexible_n95"])
    if c_rec_peak > midday_cutoff and req.budget_tier != "rs_0":
        rec_mask = "n95"
        steps.append("Peak outdoor dust crosses Poor/Very Poor—add a fitted N95 mask.")
    else:
        steps.append("Pick tree-lined lanes away from main arterial intersections.")

    rationale = (
        f"Flexible slot optimized over {act.duration_min} min from {rec_h:02d}:00 "
        f"(mixing height {snapshot.hourly[rec_h].boundary_layer_height:.0f} m)."
    )
    badge = _flexible_badge(req, rec_h, act.planned_hour, is_slider)
    return badge, "walk_sidewalk", rec_mask, steps, rationale


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


def _choose_flexible_outcome(
    act: Any,
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    ctx: _ScheduleContext,
    base_summary: tuple[bool, float],
) -> tuple[int, str, str, MaskType, list[str], str, bool]:
    """Select start hour (or what-if slider hour) and build flexible mitigation details."""
    sensitive, c_orig = base_summary
    is_slider = ctx.allow_slider and req.walk_override_hour is not None
    if is_slider and req.walk_override_hour is not None:
        rec_h = req.walk_override_hour
    else:
        template = _IntervalQuery(
            0, act.duration_min, "walk_sidewalk", act.activity_level, act.current_mask
        )
        rec_h = _find_best_start_hour_for_duration(
            snapshot.hourly, template, next_day_pm25=ctx.next_day_pm25
        )
    walk_query = _IntervalQuery(
        rec_h, act.duration_min, "walk_sidewalk", act.activity_level, act.current_mask
    )
    _, c_rec_prev, _, c_rec_peak = _evaluate_interval_exposure(
        snapshot.hourly,
        walk_query,
        next_day_pm25=ctx.next_day_pm25,
        next_day_naqi=ctx.next_day_naqi,
    )
    badge, opt_micro, rec_mask, steps, rationale = _schedule_flexible_activity(
        act, req, snapshot, sensitive, (rec_h, c_orig, c_rec_prev, c_rec_peak, is_slider)
    )
    return rec_h, badge, opt_micro, rec_mask, steps, rationale, is_slider


def _assemble_routine_item(
    act: Any,
    base_metrics: tuple[float, int, float],
    opt_metrics: tuple[int, float, int, float, MaskType],
    copy_info: tuple[str, list[str], str],
) -> RoutineItemResult:
    """Construct immutable RoutineItemResult schema from evaluated baseline & optimal runs."""
    c_orig, naqi_orig, base_dose = base_metrics
    rec_h, c_rec, naqi_rec, opt_dose, rec_mask = opt_metrics
    badge, steps, rationale = copy_info
    return RoutineItemResult(
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


def _schedule_single_activity(
    act: Any,
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    ctx: _ScheduleContext,
) -> tuple[RoutineItemResult, float, float, str, bool]:
    """Optimize and evaluate one activity item, returning result and dose totals."""
    sensitive = _has_sensitive_member(req, act.member_name)
    base_micro = ctx.base_commute_micro if act.is_commute else "walk_sidewalk"
    base_q = _IntervalQuery(
        act.planned_hour, act.duration_min, base_micro, act.activity_level, act.current_mask
    )
    base_dose, c_orig, naqi_orig, c_orig_peak = _evaluate_interval_exposure(
        snapshot.hourly, base_q, next_day_pm25=ctx.next_day_pm25, next_day_naqi=ctx.next_day_naqi
    )
    if act.flexibility == "fixed":
        rec_h, badge, used_slider = act.planned_hour, "FIXED • MITIGATED", False
        opt_micro, rec_mask, steps, rationale = _schedule_fixed_activity(
            act, req, c_orig_peak, sensitive, (base_micro, ctx.target_commute_micro)
        )
    else:
        rec_h, badge, opt_micro, rec_mask, steps, rationale, used_slider = _choose_flexible_outcome(
            act, req, snapshot, ctx, (sensitive, c_orig)
        )
    opt_q = _IntervalQuery(rec_h, act.duration_min, opt_micro, act.activity_level, rec_mask)
    opt_dose, c_rec, naqi_rec, _ = _evaluate_interval_exposure(
        snapshot.hourly, opt_q, next_day_pm25=ctx.next_day_pm25, next_day_naqi=ctx.next_day_naqi
    )
    base_spec = (base_micro, c_orig, base_dose, act.current_mask)
    opt_spec = (opt_micro, c_rec, opt_dose, rec_mask)
    sub_text = _format_dose_substitution(act, base_spec, opt_spec)
    item = _assemble_routine_item(
        act,
        (c_orig, naqi_orig, base_dose),
        (rec_h, c_rec, naqi_rec, opt_dose, rec_mask),
        (badge, steps, rationale),
    )
    return item, base_dose, opt_dose, sub_text, used_slider


def schedule_activities(
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    next_day_pm25: list[float] | None = None,
    next_day_naqi: list[int] | None = None,
) -> tuple[list[RoutineItemResult], float, float, list[str]]:
    """Run constraint-aware scheduling and hourly-integrated USEPA dosimetry."""
    arai_map = CONSTANTS["arai_transport_emissions"]
    base_micro = str(arai_map.get(req.commute_mode, arai_map["car_petrol_solo"])["microenv"])
    target_spec = arai_map.get(req.target_commute_mode, arai_map["electric_metro"])
    target_micro = str(target_spec["microenv"])

    results: list[RoutineItemResult] = []
    substitutions: list[str] = []
    total_base, total_opt = 0.0, 0.0
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
            _ScheduleContext(base_micro, target_micro, allow_slider, next_day_pm25, next_day_naqi),
        )
        walk_override_applied = walk_override_applied or used_slider
        total_base += base_dose
        total_opt += opt_dose
        substitutions.append(sub_text)
        results.append(item)

    return results, round(total_base, 2), round(total_opt, 2), substitutions
