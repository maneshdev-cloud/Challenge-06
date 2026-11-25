"""Clean Air Sanctuary scoring, window ventilation protocol, and home IAQ alerts."""

from __future__ import annotations

from air_quality import ENGINE_PARAMS
from data_fetcher import CONSTANTS
from schemas import (
    AirSnapshotResponse,
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


def _build_window_advice(
    snapshot: AirSnapshotResponse,
    budget_tier: str,
) -> WindowVentilationAdvice:
    """Compare outdoor minimum vs modeled indoor proxy consistently with README protocol."""
    day_points = snapshot.hourly[7:19]
    min_pt = min(day_points, key=lambda p: p.pm2_5)
    mean_out_24h = sum(p.pm2_5 for p in snapshot.hourly) / 24.0
    is_unsealed = budget_tier == "rs_0"
    infiltration = float(
        ENGINE_PARAMS["infiltration_rs_0"] if is_unsealed else ENGINE_PARAMS["infiltration_sealed"]
    )
    modeled_label = "unsealed indoor air" if is_unsealed else "sealed indoor air"
    cooking_spike = float(ENGINE_PARAMS["cooking_spike_pm25_ug_m3"])
    flush_max = float(ENGINE_PARAMS["window_flush_max_outdoor_pm25"])
    mod_cap = float(ENGINE_PARAMS["window_moderate_cap_pm25"])

    modeled_indoor_base = round(mean_out_24h * infiltration, 1)
    modeled_post_cooking = round(modeled_indoor_base + cooking_spike, 1)
    end_hr = min(23, min_pt.hour + 1)

    if min_pt.pm2_5 <= min(mod_cap, modeled_indoor_base):
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

    flush_note = (
        f" Note: If indoor air feels stuffy during heavy cooking at {min_pt.hour:02d}:00-"
        f"{end_hr:02d}:00 (outdoor {min_pt.pm2_5} ug/m3), run a 10-15 min exhaust-led vent flush."
        if min_pt.pm2_5 <= flush_max
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
            f"{min_pt.hour:02d}:00) stays above modeled {modeled_label} "
            f"(~{modeled_indoor_base} ug/m3). Isolate kitchen tadka via closed door + exhaust "
            f"fan for 15 min.{flush_note}"
        ),
    )


def _collect_sanctuary_alerts(req: PlanRequest) -> list[str]:
    """Build indoor source-control and persona-specific Sanctuary alerts."""
    ages = ENGINE_PARAMS["age_cutoffs"]
    alerts: list[str] = []
    if req.uses_agarbatti_or_coils:
        alerts.append(
            "Detected agarbatti/mosquito coil use: pause indoor burning on poor-AQI days."
        )
    if req.dry_sweeps:
        alerts.append("Switch dry jhadu sweeping to damp wet-mopping (pochha) to curb dust.")
    if any({"asthma", "copd"} & {c.lower() for c in m.conditions} for m in req.members):
        alerts.append("Keep prescribed rescue inhaler / reliever handy in Sanctuary Room.")

    senior_min = int(ages["sensitive_elderly_min"])
    kid_max = int(ages["student_kid_max"])
    if req.user_category == "delivery_riders" or any(a.is_work_shift for a in req.activities):
        alerts.append("Rider recovery: shake dusty outer jacket outside and rinse nose/face.")
    elif req.user_category == "seniors" or any(m.age >= senior_min for m in req.members):
        alerts.append("Senior protection: avoid cold drafts before 9 AM and keep Sanctuary warm.")
    elif req.user_category == "students_kids" or any(m.age <= kid_max for m in req.members):
        alerts.append("Student/kid routine: keep study desk away from road windows and wipe shoes.")
    else:
        alerts.append("Commuter home setup: seal corridor door leaks and run kitchen exhaust.")
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
        co2_safety_note="Leave an inner door slightly ajar overnight so CO2 does not build up.",
        no_houseplants_note=(
            "Indoor houseplants do not remove meaningful PM2.5 in real homes; focus on source "
            "control, sealing gaps, and filtration."
        ),
        applicable_hacks=hacks,
        personalized_alerts=_collect_sanctuary_alerts(req),
    )
