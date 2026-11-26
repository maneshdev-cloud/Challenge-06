"""Orchestration facade and backward-compatible public API for the PRANA-AI engine."""

from __future__ import annotations

from typing import Any

from air_quality import (
    ENGINE_PARAMS,
    build_air_snapshot,
    build_daily_outlook,
    category_for_naqi,
    classify_meteorology_regime,
    compute_cpcb_subindex,
    compute_hourly_naqi,
    compute_pm25_naqi,
    find_golden_window,
)
from emissions import compute_emit_less
from exposure import (
    PRIMARY_FLEX_LEVELS,
    SENSITIVE_CONDITIONS,
    compute_inhaled_dose_ug,
    compute_interval_dose_ug,
    extract_next_day_series,
    schedule_activities,
)
from geo_india import CONSTANTS
from indoor import DEFAULT_ROOMS, score_sanctuary
from schemas import (
    AirSnapshotResponse,
    BreatheLessLedger,
    EmitLessLedger,
    EvidenceBundle,
    GroundedMetrics,
    PlanRequest,
    ProfileRiskSummary,
    RoutineItemResult,
    SanctuaryPlan,
    UserCategory,
)

__all__ = [
    "DEFAULT_ROOMS",
    "ENGINE_PARAMS",
    "PRIMARY_FLEX_LEVELS",
    "SENSITIVE_CONDITIONS",
    "build_air_snapshot",
    "build_daily_outlook",
    "build_evidence_bundle",
    "build_profile_risk_summary",
    "category_for_naqi",
    "classify_meteorology_regime",
    "compute_cpcb_subindex",
    "compute_emit_less",
    "compute_hourly_naqi",
    "compute_inhaled_dose_ug",
    "compute_interval_dose_ug",
    "compute_pm25_naqi",
    "find_golden_window",
    "score_sanctuary",
]


def _matches_member_tier(
    members: list[Any], cutoff: int, conds: set[str], *, min_age: bool
) -> bool:
    """Return True if any member meets an age bound or shares a respiratory/profile condition."""
    for m in members:
        age_ok = m.age >= cutoff if min_age else m.age <= cutoff
        if age_ok or bool({c.lower() for c in m.conditions} & conds):
            return True
    return False


def _resolve_profile_key(req: PlanRequest) -> UserCategory:
    """Determine primary user category from explicit flag or household profile."""
    if req.user_category is not None:
        return req.user_category
    ages = ENGINE_PARAMS["age_cutoffs"]
    if any(a.is_work_shift for a in req.activities) or _matches_member_tier(
        req.members, 999, {"outdoor_worker"}, min_age=True
    ):
        return "delivery_riders"
    if _matches_member_tier(
        req.members, int(ages["senior_profile_min"]), {"elderly", "copd", "cardiac"}, min_age=True
    ):
        return "seniors"
    if _matches_member_tier(
        req.members, int(ages["student_kid_max"]), {"child", "student"}, min_age=False
    ):
        return "students_kids"
    return "adults_commuters"


_DOMAIN_REFERENCE_VALUES: tuple[float, ...] = (2.0, 2.5, 10.0, 13.0, 95.0)


def _profile_copy_context(
    snapshot: AirSnapshotResponse,
    breathe_less: BreatheLessLedger,
    emit_less: EmitLessLedger,
    spec: tuple[UserCategory, int, float, int],
) -> dict[str, Any]:
    """Build string interpolation context for profile risk templates."""
    _key, threshold, peak_ve, total_outdoor_min = spec
    gw = snapshot.golden_window
    mult = float(ENGINE_PARAMS["roadside_plume_multiplier"])
    co2_str = (
        f"{emit_less.co2_saved_kg} kg"
        if emit_less.co2_saved_g >= 1000
        else f"{emit_less.co2_saved_g} g"
    )
    return {
        "hrs": round(total_outdoor_min / 60.0, 1),
        "peak_ve": peak_ve,
        "mult": mult,
        "pm25": snapshot.current_pm25,
        "road_pm25": round(snapshot.current_pm25 * mult, 1),
        "naqi": snapshot.current_naqi,
        "cat": snapshot.current_category,
        "threshold": threshold,
        "base_dose": breathe_less.baseline_dose_ug,
        "opt_dose": breathe_less.optimized_dose_ug,
        "dose_avoided": breathe_less.dose_avoided_ug,
        "dose_red_pct": breathe_less.reduction_pct,
        "gw_red_pct": round(gw.reduction_pct),
        "morning_peak_pm25": gw.morning_peak_pm25,
        "best_win": f"{gw.start_hour:02d}:00–{gw.end_hour:02d}:00",
        "commute_km": emit_less.commute_km,
        "co2_str": co2_str,
        "target_mode_label": emit_less.target_mode_label,
    }


def build_profile_risk_summary(
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    breathe_less: BreatheLessLedger,
    emit_less: EmitLessLedger,
) -> ProfileRiskSummary:
    """Compute category-specific NAQI thresholds, lung intake, and risk copy from templates."""
    key = _resolve_profile_key(req)
    ve_map = CONSTANTS["usepa_ventilation_m3_hr"]
    peak_ve = round(
        max([float(ve_map.get(a.activity_level, 1.25)) for a in req.activities] or [1.25]), 2
    )
    threshold = int(ENGINE_PARAMS["category_warning_thresholds_naqi"][key])
    warning_active = snapshot.current_naqi > threshold

    tpl = CONSTANTS["profile_copy_templates"][key]
    band_idx = 0 if snapshot.current_naqi > 200 else (1 if warning_active else 2)
    headline_key = (
        "clean"
        if snapshot.golden_window.is_clean_air_day
        else ("window" if snapshot.golden_window.has_meaningful_window else "flat")
    )
    ctx = _profile_copy_context(
        snapshot,
        breathe_less,
        emit_less,
        (key, threshold, peak_ve, sum(a.duration_min for a in req.activities)),
    )
    return ProfileRiskSummary(
        profile_key=key,
        profile_label=str(tpl["label"]),
        sensitivity_tier=str(tpl["tier"]),
        warning_threshold_naqi=threshold,
        warning_active=warning_active,
        risk_level=str(tpl["severity_labels"][band_idx]),
        risk_badge=str(tpl["badges"][band_idx]),
        warning_banner=str(tpl["banners"][("severe", "warning", "ok")[band_idx]]).format(**ctx),
        peak_ventilation_m3_hr=peak_ve,
        total_outdoor_min=sum(a.duration_min for a in req.activities),
        tailored_hero_headline=str(tpl["headlines"][headline_key]).format(**ctx),
        physiology_note=str(tpl["physiology"]).format(**ctx),
    )


def _build_pm25_allowlist(
    snapshot: AirSnapshotResponse,
    routine_plan: list[RoutineItemResult],
    sanctuary_plan: SanctuaryPlan,
) -> set[float]:
    """Collect grounded PM2.5 concentrations across snapshot, windows, and routines."""
    road_pm25 = round(snapshot.current_pm25 * float(ENGINE_PARAMS["roadside_plume_multiplier"]), 1)
    wa = sanctuary_plan.window_advice
    return {
        2.5,
        road_pm25,
        float(ENGINE_PARAMS["window_flush_max_outdoor_pm25"]),
        float(ENGINE_PARAMS["window_moderate_cap_pm25"]),
        float(snapshot.current_pm25),
        float(snapshot.golden_window.mean_pm25),
        float(snapshot.golden_window.morning_peak_pm25),
        float(wa.outdoor_min_pm25),
        float(wa.modeled_indoor_baseline_pm25),
        float(wa.modeled_post_cooking_pm25),
        *(float(pt.pm2_5) for pt in snapshot.hourly),
        *(float(d.peak_pm25) for d in snapshot.daily_outlook),
        *(float(d.best_window_pm25) for d in snapshot.daily_outlook),
        *(v for i in routine_plan for v in (float(i.original_pm25), float(i.recommended_pm25))),
    }


def _build_naqi_allowlist(
    snapshot: AirSnapshotResponse,
    routine_plan: list[RoutineItemResult],
    profile_summary: ProfileRiskSummary,
) -> set[float]:
    """Collect grounded CPCB NAQI thresholds and hourly/daily index values."""
    return {
        *(float(bp["i_hi"]) for bp in CONSTANTS["cpcb_pm25_breakpoints"]),
        *(float(v) for v in ENGINE_PARAMS["category_warning_thresholds_naqi"].values()),
        float(snapshot.current_naqi),
        float(snapshot.golden_window.mean_naqi),
        float(profile_summary.warning_threshold_naqi),
        *(float(pt.cpcb_naqi) for pt in snapshot.hourly),
        *(float(d.peak_naqi) for d in snapshot.daily_outlook),
        *(v for i in routine_plan for v in (float(i.original_naqi), float(i.recommended_naqi))),
    }


def _build_typed_metrics(
    snapshot: AirSnapshotResponse,
    routine_plan: list[RoutineItemResult],
    sanctuary_plan: SanctuaryPlan,
    ledgers: tuple[BreatheLessLedger, EmitLessLedger, ProfileRiskSummary],
) -> GroundedMetrics:
    """Assemble category-scoped grounded allowlists derived from outputs and constants."""
    breathe_less, emit_less, profile_summary = ledgers
    dose_vals: set[float] = {
        float(CONSTANTS["berkeley_earth_cig_ug"]),
        float(breathe_less.baseline_dose_ug),
        float(breathe_less.optimized_dose_ug),
        float(breathe_less.dose_avoided_ug),
        *(
            float(val)
            for item in routine_plan
            for val in (item.baseline_dose_ug, item.optimized_dose_ug, item.dose_avoided_ug)
        ),
    }
    pct_vals = sorted(
        {
            float(ENGINE_PARAMS["golden_window_min_reduction_pct"]),
            float(snapshot.golden_window.reduction_pct),
            float(breathe_less.reduction_pct),
        }
        | {float(day.reduction_pct) for day in snapshot.daily_outlook}
    )
    return GroundedMetrics(
        pm25=sorted(_build_pm25_allowlist(snapshot, routine_plan, sanctuary_plan)),
        naqi=sorted(_build_naqi_allowlist(snapshot, routine_plan, profile_summary)),
        dose_ug=sorted(dose_vals),
        cigarettes=[float(breathe_less.cigarettes_avoided)],
        co2_g=[float(emit_less.co2_saved_g)],
        co2_kg=[float(emit_less.co2_saved_kg)],
        tailpipe_mg=[float(emit_less.tailpipe_pm25_saved_mg)],
        pct=pct_vals,
    )


def _build_flat_allowlist(
    snapshot: AirSnapshotResponse,
    routine_plan: list[RoutineItemResult],
    sanctuary_plan: SanctuaryPlan,
    metrics: GroundedMetrics,
    ledgers: tuple[EmitLessLedger, ProfileRiskSummary],
) -> list[float]:
    """Assemble flattened grounded float allowlist for post-generation validation."""
    emit_less, profile_summary = ledgers
    wa = sanctuary_plan.window_advice
    flat: set[float] = {
        *_DOMAIN_REFERENCE_VALUES,
        *(float(v) for v in CONSTANTS["budget_tier_limits_inr"].values()),
        *(float(v) for v in ENGINE_PARAMS["mask_thresholds_pm25"].values()),
        float(ENGINE_PARAMS["cooking_spike_pm25_ug_m3"]),
        float(snapshot.current_hour),
        float(snapshot.morning_inversion_ceiling_m),
        float(snapshot.golden_window.start_hour),
        float(snapshot.golden_window.end_hour),
        float(wa.duration_minutes),
        float(emit_less.commute_km),
        float(profile_summary.peak_ventilation_m3_hr),
        *metrics.pm25,
        *metrics.naqi,
        *metrics.dose_ug,
        *metrics.pct,
        *metrics.cigarettes,
        *metrics.co2_g,
        *metrics.co2_kg,
        *metrics.tailpipe_mg,
        *(float(v) for pt in snapshot.hourly for v in (pt.hour, pt.pm10, pt.boundary_layer_height)),
        *(float(rm.score) for rm in sanctuary_plan.room_scores),
        *(
            float(v)
            for i in routine_plan
            for v in (i.original_hour, i.recommended_hour, i.duration_min)
        ),
    }
    return sorted(flat)


def _collect_grounded_metrics(
    snapshot: AirSnapshotResponse,
    routine_plan: list[RoutineItemResult],
    sanctuary_plan: SanctuaryPlan,
    ledgers: tuple[BreatheLessLedger, EmitLessLedger, ProfileRiskSummary],
) -> tuple[GroundedMetrics, list[float]]:
    """Build category-scoped and global numeric allowlists before EvidenceBundle creation."""
    metrics = _build_typed_metrics(snapshot, routine_plan, sanctuary_plan, ledgers)
    flat = _build_flat_allowlist(
        snapshot, routine_plan, sanctuary_plan, metrics, (ledgers[1], ledgers[2])
    )
    return metrics, flat


def _build_breathe_less_ledger(
    base_dose: float, opt_dose: float, dose_subs: list[str]
) -> BreatheLessLedger:
    """Construct Ledger 1 (USEPA inhaled dose savings & cigarette equivalent)."""
    cig_ug = float(CONSTANTS["berkeley_earth_cig_ug"])
    dose_avoided = round(base_dose - opt_dose, 2)
    reduction_pct = round((dose_avoided / base_dose) * 100.0, 1) if base_dose > 0 else 0.0
    cigs_avoided = round(dose_avoided / cig_ug, 2)
    return BreatheLessLedger(
        baseline_dose_ug=base_dose,
        optimized_dose_ug=opt_dose,
        dose_avoided_ug=dose_avoided,
        reduction_pct=reduction_pct,
        cigarettes_avoided=cigs_avoided,
        label="Modeled Estimate",
        formula_summary=(
            f"D (ug) = sum_h (C_h * kappa * V_E * dt_h) * (1 - eta); "
            f"Cigarettes = Delta D / {int(cig_ug)} ug"
        ),
        substitutions=dose_subs,
        limitations=(
            "Modeled exposure proxy integrating gridded Open-Meteo outdoor PM2.5, USEPA breathing "
            "rates, and lab filtration/microenvironment factors—not a personal monitor reading."
        ),
    )


def _compute_routine_and_breathe_less(
    req: PlanRequest, snapshot: AirSnapshotResponse, raw_payload: dict[str, Any]
) -> tuple[list[RoutineItemResult], BreatheLessLedger]:
    """Schedule household activities and build the USEPA Breathe Less dose ledger."""
    next_day = extract_next_day_series(raw_payload)
    routine_plan, base_dose, opt_dose, dose_subs = schedule_activities(
        req, snapshot, next_day_pm25=next_day[0], next_day_naqi=next_day[1]
    )
    return routine_plan, _build_breathe_less_ledger(base_dose, opt_dose, dose_subs)


def build_evidence_bundle(
    req: PlanRequest,
    raw_payload: dict[str, Any],
    current_hour: int | None = None,
    emergency_alert: bool = False,
    emergency_message: str | None = None,
) -> EvidenceBundle:
    """Assemble the complete immutable deterministic EvidenceBundle for PRANA-AI."""
    snapshot = build_air_snapshot(raw_payload, current_hour=current_hour)
    routine_plan, breathe_less = _compute_routine_and_breathe_less(req, snapshot, raw_payload)
    sanctuary_plan = score_sanctuary(req, snapshot)
    emit_less = compute_emit_less(req)
    profile_summary = build_profile_risk_summary(req, snapshot, breathe_less, emit_less)
    metrics, grounded_list = _collect_grounded_metrics(
        snapshot, routine_plan, sanctuary_plan, (breathe_less, emit_less, profile_summary)
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
