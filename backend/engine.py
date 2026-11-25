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
from data_fetcher import CONSTANTS
from exposure import (
    PRIMARY_FLEX_LEVELS,
    SENSITIVE_CONDITIONS,
    _extract_next_day_pm25,
    _schedule_activities,
    compute_emit_less,
    compute_inhaled_dose_ug,
    compute_interval_dose_ug,
)
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


def _resolve_profile_key(req: PlanRequest) -> UserCategory:
    """Determine primary user category from explicit flag or household profile."""
    if req.user_category is not None:
        return req.user_category
    ages = ENGINE_PARAMS["age_cutoffs"]
    all_conditions = {c.lower() for m in req.members for c in m.conditions}
    if any(a.is_work_shift for a in req.activities) or "outdoor_worker" in all_conditions:
        return "delivery_riders"
    if any(
        m.age >= int(ages["senior_profile_min"])
        or bool({c.lower() for c in m.conditions} & {"elderly", "copd", "cardiac"})
        for m in req.members
    ):
        return "seniors"
    if any(
        m.age <= int(ages["student_kid_max"])
        or bool({c.lower() for c in m.conditions} & {"child", "student"})
        for m in req.members
    ):
        return "students_kids"
    return "adults_commuters"


def build_profile_risk_summary(
    req: PlanRequest,
    snapshot: AirSnapshotResponse,
    breathe_less: BreatheLessLedger,
    emit_less: EmitLessLedger,
) -> ProfileRiskSummary:
    """Compute category-specific NAQI thresholds, lung intake, and risk copy from templates."""
    key = _resolve_profile_key(req)
    ve_map = CONSTANTS["usepa_ventilation_m3_hr"]
    ve_values = [float(ve_map.get(a.activity_level, 1.25)) for a in req.activities] or [1.25]
    peak_ve = round(max(ve_values), 2)
    total_outdoor_min = sum(a.duration_min for a in req.activities)
    threshold = int(ENGINE_PARAMS["category_warning_thresholds_naqi"][key])
    naqi = snapshot.current_naqi
    warning_active = naqi > threshold

    tpl = CONSTANTS["profile_copy_templates"][key]
    band_idx = 0 if naqi > 200 else (1 if warning_active else 2)
    gw = snapshot.golden_window
    headline_key = (
        "clean" if gw.is_clean_air_day else ("window" if gw.has_meaningful_window else "flat")
    )
    mult = float(ENGINE_PARAMS["roadside_plume_multiplier"])
    co2_str = (
        f"{emit_less.co2_saved_kg} kg"
        if emit_less.co2_saved_g >= 1000
        else f"{emit_less.co2_saved_g} g"
    )
    ctx = {
        "hrs": round(total_outdoor_min / 60.0, 1),
        "peak_ve": peak_ve,
        "mult": mult,
        "pm25": snapshot.current_pm25,
        "road_pm25": round(snapshot.current_pm25 * mult, 1),
        "naqi": naqi,
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
        total_outdoor_min=total_outdoor_min,
        tailored_hero_headline=str(tpl["headlines"][headline_key]).format(**ctx),
        physiology_note=str(tpl["physiology"]).format(**ctx),
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
    road_pm25 = round(snapshot.current_pm25 * float(ENGINE_PARAMS["roadside_plume_multiplier"]), 1)
    wa = sanctuary_plan.window_advice
    pm25_vals: set[float] = {
        2.5, 60.0, 90.0, road_pm25,
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
    naqi_vals: set[float] = {
        100.0, 150.0, 200.0, 300.0, 500.0,
        float(snapshot.current_naqi),
        float(snapshot.golden_window.mean_naqi),
        float(profile_summary.warning_threshold_naqi),
        *(float(pt.cpcb_naqi) for pt in snapshot.hourly),
        *(float(d.peak_naqi) for d in snapshot.daily_outlook),
        *(v for i in routine_plan for v in (float(i.original_naqi), float(i.recommended_naqi))),
    }
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
        {float(snapshot.golden_window.reduction_pct), float(breathe_less.reduction_pct)}
        | {float(day.reduction_pct) for day in snapshot.daily_outlook}
    )

    metrics = GroundedMetrics(
        pm25=sorted(pm25_vals),
        naqi=sorted(naqi_vals),
        dose_ug=sorted(dose_vals),
        cigarettes=[float(breathe_less.cigarettes_avoided)],
        co2_g=[float(emit_less.co2_saved_g)],
        co2_kg=[float(emit_less.co2_saved_kg)],
        tailpipe_mg=[float(emit_less.tailpipe_pm25_saved_mg)],
        pct=pct_vals,
    )
    flat: set[float] = {
        0.0, 2.0, 10.0, 13.0, 15.0, 20.0, 95.0, 500.0, 2200.0,
        float(snapshot.current_hour),
        float(snapshot.morning_inversion_ceiling_m),
        float(snapshot.golden_window.start_hour),
        float(snapshot.golden_window.end_hour),
        float(wa.duration_minutes),
        float(emit_less.commute_km),
        float(profile_summary.peak_ventilation_m3_hr),
        *pm25_vals, *naqi_vals, *dose_vals, *pct_vals,
        *metrics.cigarettes, *metrics.co2_g, *metrics.co2_kg, *metrics.tailpipe_mg,
        *(float(v) for pt in snapshot.hourly for v in (pt.hour, pt.pm10, pt.boundary_layer_height)),
        *(float(rm.score) for rm in sanctuary_plan.room_scores),
        *(
            float(v)
            for i in routine_plan
            for v in (i.original_hour, i.recommended_hour, i.duration_min)
        ),
    }
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
    next_day_pm25 = _extract_next_day_pm25(raw_payload)
    routine_plan, base_dose, opt_dose, dose_subs = _schedule_activities(
        req, snapshot, next_day_pm25=next_day_pm25
    )
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
