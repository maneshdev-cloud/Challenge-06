"""Clean Air Sanctuary scoring, window ventilation protocol, and home IAQ alerts."""

from __future__ import annotations

from air_quality import ENGINE_PARAMS
from geo_india import CONSTANTS
from schemas import (
    AirSnapshotResponse,
    HourlyAirPoint,
    IAQHack,
    PlanRequest,
    RoomScore,
    RoomSpec,
    SanctuaryPlan,
    WindowVentilationAdvice,
)

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


def _score_single_room(r: RoomSpec) -> RoomScore:
    """Compute bounded heuristic Clean Air Sanctuary score (0..100) for one room."""
    raw = (
        100
        - 15 * r.ext_windows
        - (25 if r.road_facing else 0)
        - (25 if r.kitchen_adjacent else 0)
        - (10 if r.large_volume else 0)
    )
    reasons = [
        "road-facing infiltration penalty (-25)" if r.road_facing else "away from street exhaust",
        "adjacent to kitchen (-25)" if r.kitchen_adjacent else "isolated from cooking smoke",
    ]
    if r.ext_windows <= 1:
        reasons.append(f"low leak surface ({r.ext_windows} ext window)")
    return RoomScore(
        name=r.name,
        score=max(0, min(100, raw)),
        ext_windows=r.ext_windows,
        road_facing=r.road_facing,
        kitchen_adjacent=r.kitchen_adjacent,
        large_volume=r.large_volume,
        is_sanctuary=False,
        reason="; ".join(reasons),
    )


def _compute_indoor_baseline(
    snapshot: AirSnapshotResponse, budget_tier: str
) -> tuple[str, float, float]:
    """Model baseline and post-tadka indoor PM2.5 proxies from penetration tier."""
    mean_out_24h = sum(p.pm2_5 for p in snapshot.hourly) / 24.0
    is_unsealed = budget_tier == "rs_0"
    infiltration = float(
        ENGINE_PARAMS["infiltration_rs_0"] if is_unsealed else ENGINE_PARAMS["infiltration_sealed"]
    )
    modeled_label = "unsealed indoor air" if is_unsealed else "sealed indoor air"
    modeled_indoor_base = round(mean_out_24h * infiltration, 1)
    modeled_post_cooking = round(
        modeled_indoor_base + float(ENGINE_PARAMS["cooking_spike_pm25_ug_m3"]), 1
    )
    return modeled_label, modeled_indoor_base, modeled_post_cooking


def _open_window_advice(
    min_pt: HourlyAirPoint, end_hr: int, baseline_spec: tuple[str, float, float]
) -> WindowVentilationAdvice:
    """Build timed 20-minute non-roadside ventilation guidance when outdoor dips below indoor."""
    modeled_label, modeled_indoor_base, modeled_post_cooking = baseline_spec
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
            f"{end_hr:02d}:00 (outdoor {min_pt.pm2_5} ug/m3 dips at/below modeled "
            f"{modeled_label} ~{modeled_indoor_base} ug/m3); shut tight by sunset."
        ),
    )


def _shut_window_advice(
    min_pt: HourlyAirPoint,
    end_hr: int,
    baseline_spec: tuple[str, float, float],
    cap_pm25: float | None = None,
) -> WindowVentilationAdvice:
    """Build sealed-window + kitchen exhaust protocol citing the binding threshold."""
    modeled_label, modeled_indoor_base, modeled_post_cooking = baseline_spec
    flush_note = (
        f" Note: If indoor air feels stuffy during heavy cooking at {min_pt.hour:02d}:00-"
        f"{end_hr:02d}:00 (outdoor {min_pt.pm2_5} ug/m3), run a 10-15 min exhaust-led vent flush."
        if min_pt.pm2_5 <= float(ENGINE_PARAMS["window_flush_max_outdoor_pm25"])
        else ""
    )
    cap_capped = cap_pm25 is not None and cap_pm25 < modeled_indoor_base
    blocker_note = (
        f"stays above the {cap_pm25:.0f} ug/m3 outdoor clean-ventilation cap"
        if cap_capped and min_pt.pm2_5 <= modeled_indoor_base
        else f"stays above modeled {modeled_label} (~{modeled_indoor_base} ug/m3)"
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
            f"{min_pt.hour:02d}:00) {blocker_note}. Isolate kitchen tadka via closed door + "
            f"exhaust fan for 15 min.{flush_note}"
        ),
    )


def _build_window_advice(
    snapshot: AirSnapshotResponse,
    budget_tier: str,
) -> WindowVentilationAdvice:
    """Compare outdoor minimum vs modeled indoor proxy consistently with README protocol."""
    min_pt = min(snapshot.hourly[7:19], key=lambda p: p.pm2_5)
    baseline_spec = _compute_indoor_baseline(snapshot, budget_tier)
    end_hr = min(23, min_pt.hour + 1)
    cap = float(ENGINE_PARAMS["window_moderate_cap_pm25"])
    open_threshold = min(cap, baseline_spec[1])
    if min_pt.pm2_5 <= open_threshold:
        return _open_window_advice(min_pt, end_hr, baseline_spec)
    return _shut_window_advice(min_pt, end_hr, baseline_spec, cap_pm25=cap)


def _persona_alert(req: PlanRequest) -> str:
    """Select the single primary vulnerability-tailored Sanctuary tip."""
    ages = ENGINE_PARAMS["age_cutoffs"]
    if req.user_category == "delivery_riders" or any(a.is_work_shift for a in req.activities):
        return "Rider recovery: shake dusty outer jacket outside and rinse nose/face."
    if req.user_category == "seniors" or any(
        m.age >= int(ages["sensitive_elderly_min"]) for m in req.members
    ):
        return "Senior protection: avoid cold drafts before 9 AM and keep Sanctuary warm."
    if req.user_category == "students_kids" or any(
        m.age <= int(ages["student_kid_max"]) for m in req.members
    ):
        return "Student/kid routine: keep study desk away from road windows and wipe shoes."
    return "Commuter home setup: seal corridor door leaks and run kitchen exhaust."


def _collect_sanctuary_alerts(req: PlanRequest) -> list[str]:
    """Build indoor source-control and persona-specific Sanctuary alerts."""
    alerts: list[str] = []
    if req.uses_agarbatti_or_coils:
        alerts.append(
            "Detected agarbatti/mosquito coil use: pause indoor burning on poor-AQI days."
        )
    if req.dry_sweeps:
        alerts.append("Switch dry jhadu sweeping to damp wet-mopping (pochha) to curb dust.")
    if any({"asthma", "copd"} & {c.lower() for c in m.conditions} for m in req.members):
        alerts.append("Keep prescribed rescue inhaler / reliever handy in Sanctuary Room.")
    alerts.append(_persona_alert(req))
    return alerts


def score_sanctuary(req: PlanRequest, snapshot: AirSnapshotResponse) -> SanctuaryPlan:
    """Rank rooms for Clean Air Sanctuary and compute window open/shut protocol + IAQ hacks."""
    rooms = req.rooms if req.rooms else DEFAULT_ROOMS
    scored = sorted(
        (_score_single_room(r) for r in rooms),
        key=lambda item: item.score,
        reverse=True,
    )
    scored[0].is_sanctuary = True

    limit_inr = int(CONSTANTS["budget_tier_limits_inr"][req.budget_tier])
    hacks = [IAQHack(**h) for h in CONSTANTS["iaq_hacks"] if int(h["max_cost_inr"]) <= limit_inr]

    return SanctuaryPlan(
        sanctuary_room=scored[0].name,
        room_scores=scored,
        window_advice=_build_window_advice(snapshot, req.budget_tier),
        co2_safety_note=(
            "PRANA-AI has no live indoor CO2 sensor; keep an inner door slightly ajar overnight "
            "only if adjoining rooms are free of smoke or incense fumes "
            "(outer windows follow window timing)."
        ),
        no_houseplants_note=(
            "Indoor houseplants do not remove meaningful PM2.5 in real homes; focus on source "
            "control, sealing gaps, and filtration."
        ),
        applicable_hacks=hacks,
        personalized_alerts=_collect_sanctuary_alerts(req),
    )
