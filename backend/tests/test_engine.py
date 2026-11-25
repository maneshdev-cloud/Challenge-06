"""Unit tests for PRANA-AI CPCB breakpoints, hourly dosimetry, sanctuary, and outlook honesty."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from data_fetcher import PRESETS, _build_replay_payload
from engine import (
    build_air_snapshot,
    build_daily_outlook,
    build_evidence_bundle,
    compute_emit_less,
    compute_hourly_naqi,
    compute_inhaled_dose_ug,
    compute_interval_dose_ug,
    compute_pm25_naqi,
    find_golden_window,
    score_sanctuary,
)
from schemas import ActivityItem, HourlyAirPoint, HouseholdMember, PlanRequest, RoomSpec


def test_cpcb_naqi_breakpoints() -> None:
    """Verify exact CPCB PM2.5 breakpoint interpolation and continuous float bridging."""
    assert compute_pm25_naqi(0) == (0, "Good")
    assert compute_pm25_naqi(30) == (50, "Good")

    idx_gap, cat_gap = compute_pm25_naqi(30.4)
    assert 50 <= idx_gap <= 51
    assert cat_gap == "Satisfactory"

    assert compute_pm25_naqi(31) == (51, "Satisfactory")
    assert compute_pm25_naqi(250) == (400, "Very Poor")
    assert compute_pm25_naqi(600) == (500, "Severe")

    multi = compute_hourly_naqi(pm25=40.0, pm10=320.0, no2=30.0)
    assert multi["dominant_pollutant"] == "PM10"
    assert multi["cpcb_naqi"] > multi["pm25_subindex"]
    assert multi["cpcb_category"] == "Poor"


def test_golden_window_and_daily_outlook_flat_honesty() -> None:
    """Verify lowest 2h window detection and <15% flat honesty rule in today and outlook."""
    diurnal = [220.0] * 24
    diurnal[7] = 250.0
    diurnal[14] = 100.0
    diurnal[15] = 102.0
    points = [
        HourlyAirPoint(
            hour=h,
            time_label=f"{h:02d}:00",
            pm2_5=diurnal[h],
            pm10=diurnal[h] * 1.4,
            nitrogen_dioxide=40.0,
            us_aqi=180,
            cpcb_naqi=compute_pm25_naqi(diurnal[h])[0],
            cpcb_category=compute_pm25_naqi(diurnal[h])[1],
            dominant_pollutant="PM2.5",
            pm25_subindex=300,
            pm10_subindex=200,
            no2_subindex=50,
            temperature_2m=20.0,
            relative_humidity_2m=60.0,
            wind_speed_10m=5.0,
            boundary_layer_height=800.0 if 11 <= h <= 16 else 80.0,
        )
        for h in range(24)
    ]
    gw = find_golden_window(points)
    assert gw.hours == [14, 15]
    assert gw.has_meaningful_window is True
    assert gw.reduction_pct >= 15.0

    flat = [200.0] * 24
    flat[14] = 190.0
    flat[15] = 190.0
    flat_points = [points[h].model_copy(update={"pm2_5": flat[h]}) for h in range(24)]
    gw_flat = find_golden_window(flat_points)
    assert gw_flat.has_meaningful_window is False
    assert "uniformly elevated" in gw_flat.advisory.lower()

    # Check 5-day outlook applies the same <15% honesty rule on flat Elevated days
    flat_payload = {
        "multiday_raw": {
            "time": [f"2026-11-{25 + d:02d}T{h:02d}:00" for d in range(2) for h in range(24)],
            "pm2_5": [85.0] * 48,
            "pm10": [110.0] * 48,
            "nitrogen_dioxide": [40.0] * 48,
        }
    }
    outlooks = build_daily_outlook(flat_payload)
    assert len(outlooks) == 2
    assert outlooks[0].has_meaningful_window is False
    assert "uniformly elevated" in outlooks[0].tip.lower()


def test_hourly_integrated_dosimetry_and_immutability() -> None:
    """Verify multi-hour activities integrate hourly PM2.5 and EvidenceBundle is frozen."""
    dose_no_mask = compute_inhaled_dose_ug(200.0, "walk_sidewalk", "elderly_walk", 60, "none")
    assert dose_no_mask == 299.0
    assert compute_inhaled_dose_ug(200.0, "walk_sidewalk", "elderly_walk", 60, "n95") == 59.8

    raw = _build_replay_payload("delhi", "test")
    snap = build_air_snapshot(raw, current_hour=8)
    integrated_4h, _, _ = compute_interval_dose_ug(
        snap.hourly, 8, 240, "open_road_2w_auto", "running_or_outdoor_work", "none"
    )
    naive_single_hour = compute_inhaled_dose_ug(
        snap.hourly[8].pm2_5, "open_road_2w_auto", "running_or_outdoor_work", 240, "none"
    )
    expected_sum = round(
        sum(
            compute_inhaled_dose_ug(
                snap.hourly[h].pm2_5, "open_road_2w_auto", "running_or_outdoor_work", 60, "none"
            )
            for h in range(8, 12)
        ),
        2,
    )
    assert integrated_4h == expected_sum
    assert integrated_4h < naive_single_hour

    delhi_preset = next(p for p in PRESETS if p["id"] == "delhi_family")
    bundle = build_evidence_bundle(PlanRequest(**delhi_preset), raw, current_hour=8)
    with pytest.raises(ValidationError):
        bundle.city = "mumbai"


def test_arai_emissions_separation() -> None:
    """Verify ARAI CO2e and tailpipe PM2.5 are decoupled from inhaled PM2.5."""
    req = PlanRequest(
        city="delhi",
        commute_mode="car_petrol_solo",
        target_commute_mode="electric_metro",
        commute_km=16.0,
    )
    emit = compute_emit_less(req)
    assert emit.co2_saved_g == 2400.0
    assert emit.co2_saved_kg == 2.4
    assert emit.tailpipe_pm25_saved_mg == 288.0


def test_fixed_constraint_respected_for_delivery_rider() -> None:
    """Verify Delivery Rider's fixed 8h shifts are never shifted and never told 'stay home'."""
    rider_preset = next(p for p in PRESETS if p["id"] == "delivery_rider")
    bundle = build_evidence_bundle(
        PlanRequest(**rider_preset), _build_replay_payload("delhi", "test"), current_hour=8
    )

    fixed_shifts = [item for item in bundle.routine_plan if item.flexibility == "fixed"]
    assert len(fixed_shifts) == 2
    for shift in fixed_shifts:
        assert shift.recommended_hour == shift.original_hour
        assert shift.badge == "FIXED • MITIGATED"
        assert shift.recommended_mask == "n95"
        joined = " ".join(shift.mitigation_steps).lower() + " " + shift.rationale.lower()
        assert "just stay home" not in joined


def test_sanctuary_clamping_and_no_contradiction() -> None:
    """Verify Sanctuary score clamps at 0 and keeps shut when outdoor > indoor PM2.5."""
    raw = _build_replay_payload("delhi", "test")
    # Mean 24h ~100 -> sealed indoor ~28, daytime min = 80 (> indoor & > 60)
    raw["hourly_raw"]["pm2_5"] = [100.0] * 24
    raw["hourly_raw"]["pm2_5"][14] = 80.0
    snapshot = build_air_snapshot(raw, current_hour=8)

    extreme_room = RoomSpec(
        name="10-Window Highway Room",
        ext_windows=10,
        road_facing=True,
        kitchen_adjacent=True,
        large_volume=True,
    )
    req = PlanRequest(city="delhi", budget_tier="under_2200", rooms=[extreme_room])
    sanctuary = score_sanctuary(req, snapshot)
    assert sanctuary.room_scores[0].score == 0
    assert sanctuary.window_advice.action == "keep_shut_exhaust"
    assert "ajar" in sanctuary.co2_safety_note.lower()


def test_category_threshold_100_vs_150_on_moderate_naqi() -> None:
    """Verify NAQI ~132 warns Kids, Seniors, Riders (>100) while Adults (>150) stay non-alert."""
    raw = _build_replay_payload("pune", "test")
    raw["hourly_raw"]["pm2_5"][10] = 70.0
    raw["hourly_raw"]["pm10"][10] = 95.0

    def _run(cat, member, act, commute_mode="auto_cng", target="electric_metro", km=12.0):
        req = PlanRequest(
            city="pune",
            user_category=cat,
            budget_tier="under_500",
            commute_mode=commute_mode,
            target_commute_mode=target,
            commute_km=km,
            members=[member],
            activities=[act],
        )
        return build_evidence_bundle(req, raw, current_hour=10)

    kids = _run(
        "students_kids",
        HouseholdMember(name="Child", age=9, conditions=["child"]),
        ActivityItem(
            id="p",
            name="Play",
            flexibility="flexible",
            planned_hour=17,
            duration_min=45,
            activity_level="child_play",
            member_name="Child",
        ),
    )
    adults = _run(
        "adults_commuters",
        HouseholdMember(name="Adult", age=34, conditions=["adult"]),
        ActivityItem(
            id="w",
            name="Walk",
            flexibility="flexible",
            planned_hour=7,
            duration_min=40,
            activity_level="brisk_walk",
            member_name="Adult",
        ),
        "car_petrol_solo",
        "electric_metro",
        16.0,
    )
    seniors = _run(
        "seniors",
        HouseholdMember(name="Senior", age=70, conditions=["elderly", "copd"]),
        ActivityItem(
            id="s",
            name="Walk",
            flexibility="flexible",
            planned_hour=6,
            duration_min=45,
            activity_level="elderly_walk",
            member_name="Senior",
        ),
    )
    riders = _run(
        "delivery_riders",
        HouseholdMember(name="Rider", age=29, conditions=["outdoor_worker"]),
        ActivityItem(
            id="d",
            name="Shift",
            flexibility="fixed",
            planned_hour=8,
            duration_min=480,
            activity_level="running_or_outdoor_work",
            member_name="Rider",
            is_commute=True,
            is_work_shift=True,
        ),
        "two_wheeler_petrol",
        "two_wheeler_petrol",
        40.0,
    )

    assert 100 < adults.air_snapshot.current_naqi <= 150
    assert kids.profile_summary.warning_active is True
    assert seniors.profile_summary.warning_active is True
    assert riders.profile_summary.warning_active is True
    assert adults.profile_summary.warning_active is False


def test_user_categories_differentiate_lung_capacity_and_advice() -> None:
    """Verify Kids, Seniors, and Riders show distinct lung intake & advice on same city."""
    raw = _build_replay_payload("pune", "test")

    kids_b = build_evidence_bundle(
        PlanRequest(
            city="pune",
            budget_tier="rs_0",
            members=[HouseholdMember(name="School Child", age=9, conditions=["child"])],
            activities=[
                ActivityItem(
                    id="play",
                    name="Outdoor Sports",
                    flexibility="flexible",
                    planned_hour=17,
                    duration_min=45,
                    activity_level="child_play",
                    member_name="School Child",
                )
            ],
        ),
        raw,
        current_hour=10,
    )
    seniors_b = build_evidence_bundle(
        PlanRequest(
            city="pune",
            budget_tier="under_500",
            members=[HouseholdMember(name="Senior", age=70, conditions=["elderly", "copd"])],
            activities=[
                ActivityItem(
                    id="walk",
                    name="Morning Walk",
                    flexibility="flexible",
                    planned_hour=6,
                    duration_min=45,
                    activity_level="elderly_walk",
                    member_name="Senior",
                    current_mask="cloth",
                )
            ],
        ),
        raw,
        current_hour=10,
    )
    rider_b = build_evidence_bundle(
        PlanRequest(
            city="pune",
            budget_tier="under_500",
            commute_mode="two_wheeler_petrol",
            target_commute_mode="two_wheeler_petrol",
            commute_km=40.0,
            members=[HouseholdMember(name="Delivery Rider", age=29, conditions=["outdoor_worker"])],
            activities=[
                ActivityItem(
                    id="shift",
                    name="Delivery Shift (8h)",
                    flexibility="fixed",
                    planned_hour=8,
                    duration_min=480,
                    activity_level="running_or_outdoor_work",
                    member_name="Delivery Rider",
                    current_mask="cloth",
                    is_commute=True,
                    is_work_shift=True,
                )
            ],
        ),
        raw,
        current_hour=10,
    )

    assert rider_b.profile_summary is not None
    assert kids_b.profile_summary is not None
    assert seniors_b.profile_summary is not None
    assert rider_b.profile_summary.peak_ventilation_m3_hr == 2.70
    assert kids_b.profile_summary.peak_ventilation_m3_hr == 1.35
    assert seniors_b.profile_summary.peak_ventilation_m3_hr == 1.30
    assert rider_b.breathe_less.baseline_dose_ug > kids_b.breathe_less.baseline_dose_ug
    assert rider_b.routine_plan[0].recommended_mask == "n95"
