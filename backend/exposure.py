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
    """Per-plan routing, day-2 forecast, and per-member occupied slots."""

    base_commute_micro: str
    target_commute_micro: str
    allow_slider: bool
    next_day_pm25: list[float] | None
    next_day_naqi: list[int] | None = None
    occupied_intervals: tuple[tuple[int, int], ...] = ()


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


@dataclass(frozen=True)
class _ScheduleOutcome:
    """Normalized scheduling decision returned across fixed and flexible branches."""

    rec_hour: int
    badge: str
    opt_micro: str
    rec_mask: MaskType
    steps: list[str]
    rationale: str
    used_slider: bool = False


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
    acc = [0.0, 0.0, 0.0, 0.0]  # dose, weighted_pm25, weighted_naqi, peak_pm25

    while remaining > 0:
        chunk_min = min(60, remaining)
        c_pm25, c_naqi = _concentration_at_step(
            hourly_points, step_idx, next_day_pm25, next_day_naqi
        )
        acc[0] += compute_inhaled_dose_ug(
            c_pm25, query.microenv_key, query.activity_level, chunk_min, query.mask
        )
        acc[1] += c_pm25 * chunk_min
        acc[2] += c_naqi * chunk_min
        acc[3] = max(acc[3], c_pm25)
        remaining -= chunk_min
        step_idx += 1

    return (
        round(acc[0], 2),
        round(acc[1] / query.duration_min, 1),
        int(round(acc[2] / query.duration_min)),
        round(acc[3], 1),
    )


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


def _overlaps_occupied(
    start_min: int, duration_min: int, occupied: tuple[tuple[int, int], ...]
) -> bool:
    """Return True when [start_min, start_min + duration_min) overlaps any occupied window."""
    end_min = start_min + max(1, duration_min)
    return any(start_min < occ_end and occ_start < end_min for occ_start, occ_end in occupied)


def _best_hour_in_range(
    hourly_points: list[HourlyAirPoint],
    query_template: _IntervalQuery,
    hour_range: range,
    *,
    next_day_pm25: list[float] | None,
    occupied: tuple[tuple[int, int], ...],
) -> tuple[int | None, float]:
    """Find lowest-dose start hour in `hour_range` avoiding `occupied` minute intervals."""
    best_h: int | None = None
    best_dose = float("inf")
    for start_h in hour_range:
        if occupied and _overlaps_occupied(start_h * 60, query_template.duration_min, occupied):
            continue
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
            best_dose, best_h = dose, start_h
    return best_h, best_dose


def _find_best_start_hour_for_duration(
    hourly_points: list[HourlyAirPoint],
    query_template: _IntervalQuery,
    *,
    next_day_pm25: list[float] | None = None,
    occupied: tuple[tuple[int, int], ...] = (),
) -> int:
    """Optimize flexible start hour across daytime slots avoiding occupied member intervals."""
    last_start = max(7, 20 - max(1, (query_template.duration_min + 59) // 60))
    free_h, _ = _best_hour_in_range(
        hourly_points,
        query_template,
        range(7, last_start + 1),
        next_day_pm25=next_day_pm25,
        occupied=occupied,
    )
    if free_h is not None:
        return free_h
    if occupied:
        fallback_h, _ = _best_hour_in_range(
            hourly_points,
            query_template,
            range(6, 22),
            next_day_pm25=next_day_pm25,
            occupied=occupied,
        )
        if fallback_h is not None:
            return fallback_h
    any_h, _ = _best_hour_in_range(
        hourly_points,
        query_template,
        range(7, last_start + 1),
        next_day_pm25=next_day_pm25,
        occupied=(),
    )
    return any_h if any_h is not None else 13


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
    """Return True if named member, household, or selected category is respiratory-sensitive."""
    for m in req.members:
        if m.name == member_name:
            return _is_member_sensitive(m)
    if any(_is_member_sensitive(m) for m in req.members):
        return True
    return req.user_category in {"seniors", "students_kids"}


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
) -> _ScheduleOutcome:
    """Shift flexible outdoor activity to cleanest slot or Sanctuary Room."""
    rec_h, c_orig, c_rec, c_rec_peak, is_slider = slot_info
    rec_mask: MaskType = act.current_mask
    if not snapshot.golden_window.has_meaningful_window and not is_slider and sensitive:
        return _ScheduleOutcome(rec_h, *_indoor_override_result(req, rec_mask), is_slider)

    steps = [
        (
            f"Shift from {act.planned_hour:02d}:00 ({c_orig} ug/m3 avg) "
            f"to {rec_h:02d}:00 ({c_rec} ug/m3 avg)."
        )
        if rec_h != act.planned_hour
        else f"Timing at {rec_h:02d}:00 already sits in a lower-exposure slot."
    ]
    if (
        c_rec_peak > float(ENGINE_PARAMS["mask_thresholds_pm25"]["midday_flexible_n95"])
        and req.budget_tier != "rs_0"
    ):
        rec_mask = "n95"
        steps.append("Peak outdoor dust crosses Poor/Very Poor—add a fitted N95 mask.")
    else:
        steps.append("Pick tree-lined lanes away from main arterial intersections.")

    return _ScheduleOutcome(
        rec_hour=rec_h,
        badge=_flexible_badge(req, rec_h, act.planned_hour, is_slider),
        opt_micro="walk_sidewalk",
        rec_mask=rec_mask,
        steps=steps,
        rationale=(
            f"Flexible slot optimized over {act.duration_min} min from {rec_h:02d}:00 "
            f"(mixing height {snapshot.hourly[rec_h].boundary_layer_height:.0f} m)."
        ),
        used_slider=is_slider,
    )


def _format_dose_substitution(
    act: Any,
    base_spec: tuple[str, float, float, MaskType],
    opt_spec: tuple[str, float, float, MaskType],
) -> str:
    """Format formula substitution string for Show Math transparency."""
    v_e = float(CONSTANTS["usepa_ventilation_m3_hr"].get(act.activity_level, 1.25))
    micro_map = CONSTANTS["microenv_multipliers"]
    mask_map = CONSTANTS["mask_filtration_efficiency"]
    dt_hr = act.duration_min / 60.0
    avoided = round(base_spec[2] - opt_spec[2], 2)
    return (
        f"{act.name} ({act.duration_min}m): Base avg {base_spec[1]}*{micro_map[base_spec[0]]}"
        f"*{v_e}*{dt_hr:.2f}h*(1-{mask_map[base_spec[3]]})={base_spec[2]} ug | Opt avg "
        f"{opt_spec[1]}*{micro_map[opt_spec[0]]}*{v_e}*{dt_hr:.2f}h*(1-{mask_map[opt_spec[3]]})"
        f"={opt_spec[2]} ug (Saved {avoided} ug)"
    )


def _choose_flexible_outcome(
    act: Any,
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    ctx: _ScheduleContext,
    base_summary: tuple[bool, float],
) -> _ScheduleOutcome:
    """Select start hour (or what-if slider hour) and build flexible mitigation details."""
    is_slider = ctx.allow_slider and req.walk_override_hour is not None
    rec_h = (
        req.walk_override_hour
        if is_slider and req.walk_override_hour is not None
        else _find_best_start_hour_for_duration(
            snapshot.hourly,
            _IntervalQuery(
                0, act.duration_min, "walk_sidewalk", act.activity_level, act.current_mask
            ),
            next_day_pm25=ctx.next_day_pm25,
            occupied=ctx.occupied_intervals,
        )
    )
    _, c_rec_prev, _, c_rec_peak = _evaluate_interval_exposure(
        snapshot.hourly,
        _IntervalQuery(
            rec_h, act.duration_min, "walk_sidewalk", act.activity_level, act.current_mask
        ),
        next_day_pm25=ctx.next_day_pm25,
        next_day_naqi=ctx.next_day_naqi,
    )
    return _schedule_flexible_activity(
        act,
        req,
        snapshot,
        base_summary[0],
        (rec_h, base_summary[1], c_rec_prev, c_rec_peak, is_slider),
    )


def _assemble_routine_item(
    act: Any,
    base_metrics: tuple[float, int, float],
    opt_metrics: tuple[int, float, int, float, MaskType],
    copy_info: tuple[str, list[str], str],
) -> RoutineItemResult:
    """Construct immutable RoutineItemResult schema from evaluated baseline & optimal runs."""
    return RoutineItemResult(
        id=act.id,
        name=act.name,
        member_name=act.member_name,
        flexibility=act.flexibility,
        badge=copy_info[0],
        original_hour=act.planned_hour,
        recommended_hour=opt_metrics[0],
        duration_min=act.duration_min,
        original_pm25=base_metrics[0],
        recommended_pm25=opt_metrics[1],
        original_naqi=base_metrics[1],
        recommended_naqi=opt_metrics[2],
        recommended_mask=opt_metrics[4],
        baseline_dose_ug=base_metrics[2],
        optimized_dose_ug=opt_metrics[3],
        dose_avoided_ug=round(base_metrics[2] - opt_metrics[3], 2),
        mitigation_steps=copy_info[1],
        rationale=copy_info[2],
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
    base_eval = _evaluate_interval_exposure(
        snapshot.hourly,
        _IntervalQuery(
            act.planned_hour, act.duration_min, base_micro, act.activity_level, act.current_mask
        ),
        next_day_pm25=ctx.next_day_pm25,
        next_day_naqi=ctx.next_day_naqi,
    )
    if act.flexibility == "fixed":
        fixed_plan = _schedule_fixed_activity(
            act, req, base_eval[3], sensitive, (base_micro, ctx.target_commute_micro)
        )
        outcome = _ScheduleOutcome(
            act.planned_hour, "FIXED • MITIGATED", *fixed_plan, used_slider=False
        )
    else:
        outcome = _choose_flexible_outcome(act, req, snapshot, ctx, (sensitive, base_eval[1]))

    opt_eval = _evaluate_interval_exposure(
        snapshot.hourly,
        _IntervalQuery(
            outcome.rec_hour,
            act.duration_min,
            outcome.opt_micro,
            act.activity_level,
            outcome.rec_mask,
        ),
        next_day_pm25=ctx.next_day_pm25,
        next_day_naqi=ctx.next_day_naqi,
    )
    sub_text = _format_dose_substitution(
        act,
        (base_micro, base_eval[1], base_eval[0], act.current_mask),
        (outcome.opt_micro, opt_eval[1], opt_eval[0], outcome.rec_mask),
    )
    item = _assemble_routine_item(
        act,
        (base_eval[1], base_eval[2], base_eval[0]),
        (outcome.rec_hour, opt_eval[1], opt_eval[2], opt_eval[0], outcome.rec_mask),
        (outcome.badge, outcome.steps, outcome.rationale),
    )
    return item, base_eval[0], opt_eval[0], sub_text, outcome.used_slider


def _select_slider_activity_idx(req: PlanRequest) -> int | None:
    """Pick the single flexible activity index controlled by the What-If hour slider."""
    if req.walk_override_hour is None or not req.activities:
        return None
    last_idx = len(req.activities) - 1
    for idx, act in enumerate(req.activities):
        if act.flexibility == "flexible" and (
            act.activity_level in PRIMARY_FLEX_LEVELS or idx == last_idx
        ):
            return idx
    for idx, act in enumerate(req.activities):
        if act.flexibility == "flexible":
            return idx
    return None


def _scheduling_order(req: PlanRequest, slider_idx: int | None) -> list[int]:
    """Order fixed tasks first, then slider task, then remaining flexible tasks."""
    fixed_idxs = [i for i, act in enumerate(req.activities) if act.flexibility == "fixed"]
    slider_list = [slider_idx] if slider_idx is not None and slider_idx not in fixed_idxs else []
    flex_idxs = [
        i for i, act in enumerate(req.activities) if act.flexibility != "fixed" and i != slider_idx
    ]
    return [*fixed_idxs, *slider_list, *flex_idxs]


def _resolve_commute_micros(req: PlanRequest) -> tuple[str, str]:
    """Return baseline and target transport microenvironment keys."""
    arai_map = CONSTANTS["arai_transport_emissions"]
    base_micro = str(arai_map.get(req.commute_mode, arai_map["car_petrol_solo"])["microenv"])
    target_micro = str(
        arai_map.get(req.target_commute_mode, arai_map["electric_metro"])["microenv"]
    )
    return base_micro, target_micro


def _summarize_schedule_runs(
    runs: list[tuple[RoutineItemResult, float, float, str, bool] | None],
) -> tuple[list[RoutineItemResult], float, float, list[str]]:
    """Aggregate per-activity dosimetry runs into routine totals."""
    final_runs = [r for r in runs if r is not None]
    results = [r[0] for r in final_runs]
    substitutions = [r[3] for r in final_runs]
    base_total = sum(r[1] for r in final_runs)
    opt_total = sum(r[2] for r in final_runs)
    return results, round(base_total, 2), round(opt_total, 2), substitutions


def schedule_activities(
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    next_day_pm25: list[float] | None = None,
    next_day_naqi: list[int] | None = None,
) -> tuple[list[RoutineItemResult], float, float, list[str]]:
    """Run non-overlapping per-member scheduling and hourly-integrated USEPA dosimetry."""
    base_micro, target_micro = _resolve_commute_micros(req)
    runs: list[tuple[RoutineItemResult, float, float, str, bool] | None] = [None] * len(
        req.activities
    )
    occupied_by_member: dict[str, list[tuple[int, int]]] = {}
    slider_idx = _select_slider_activity_idx(req)

    for idx in _scheduling_order(req, slider_idx):
        act = req.activities[idx]
        member_key = act.member_name.strip().lower()
        res = _schedule_single_activity(
            act,
            req,
            snapshot,
            _ScheduleContext(
                base_micro,
                target_micro,
                idx == slider_idx,
                next_day_pm25,
                next_day_naqi,
                tuple(occupied_by_member.get(member_key, ())),
            ),
        )
        runs[idx] = res
        start_min = res[0].recommended_hour * 60
        occupied_by_member.setdefault(member_key, []).append(
            (start_min, start_min + max(1, act.duration_min))
        )

    return _summarize_schedule_runs(runs)
