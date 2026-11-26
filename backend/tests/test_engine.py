"""Unit tests for PRANA-AI CPCB breakpoints, hourly dosimetry, sanctuary, and outlook honesty."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from air_quality import classify_meteorology_regime
from data_fetcher import PRESETS, build_replay_payload
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

    raw = build_replay_payload("delhi", "test")
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
        PlanRequest(**rider_preset), build_replay_payload("delhi", "test"), current_hour=8
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
    raw = build_replay_payload("delhi", "test")
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
    raw = build_replay_payload("pune", "test")
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
    raw = build_replay_payload("pune", "test")

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


def test_evening_spike_clears_clean_air_day_flag() -> None:
    """An evening pollution spike (NAQI > 100) must mark is_clean_air_day=False."""
    points = [
        HourlyAirPoint(
            hour=h,
            time_label=f"{h:02d}:00",
            pm2_5=115.0 if 19 <= h <= 22 else 18.0,
            pm10=140.0 if 19 <= h <= 22 else 28.0,
            nitrogen_dioxide=30.0,
            cpcb_naqi=283 if 19 <= h <= 22 else 30,
            cpcb_category="Poor" if 19 <= h <= 22 else "Good",
            dominant_pollutant="PM2.5",
            pm25_subindex=283 if 19 <= h <= 22 else 30,
            pm10_subindex=127 if 19 <= h <= 22 else 28,
            no2_subindex=38,
            temperature_2m=25.0,
            relative_humidity_2m=55.0,
            wind_speed_10m=8.0,
            boundary_layer_height=450.0,
        )
        for h in range(24)
    ]
    gw = find_golden_window(points)
    assert gw.is_clean_air_day is False


def test_duration_integrated_optimizer_and_midnight_nowrap() -> None:
    """Late-night 4h exposure must not wrap onto polluted hour 0, and optimizer respects length."""
    hourly_vals = [220.0 if h < 3 or 10 <= h <= 14 else 35.0 for h in range(24)]
    points = [
        HourlyAirPoint(
            hour=h,
            time_label=f"{h:02d}:00",
            pm2_5=hourly_vals[h],
            pm10=hourly_vals[h] * 1.4,
            nitrogen_dioxide=25.0,
            cpcb_naqi=380 if hourly_vals[h] > 200 else 58,
            cpcb_category="Very Poor" if hourly_vals[h] > 200 else "Satisfactory",
            dominant_pollutant="PM2.5",
            pm25_subindex=380 if hourly_vals[h] > 200 else 58,
            pm10_subindex=250 if hourly_vals[h] > 200 else 49,
            no2_subindex=31,
            temperature_2m=20.0,
            relative_humidity_2m=55.0,
            wind_speed_10m=6.0,
            boundary_layer_height=350.0,
        )
        for h in range(24)
    ]

    dose_no_day2, mean_no_day2, _ = compute_interval_dose_ug(
        points, 22, 240, "walk_sidewalk", "light_walk", "none"
    )
    dose_with_clean_day2, mean_with_day2, _ = compute_interval_dose_ug(
        points, 22, 240, "walk_sidewalk", "light_walk", "none", next_day_pm25=[20.0] * 24
    )
    assert mean_no_day2 == 35.0
    assert mean_with_day2 < mean_no_day2
    assert dose_with_clean_day2 < dose_no_day2

    # Build a 24h series where 13:00 is clean (25) but 14:00-15:00 spikes (260),
    # while 16:00-18:00 stays steadily moderate (60).
    spike_vals = [180.0] * 24
    spike_vals[13] = 25.0
    spike_vals[14] = 260.0
    spike_vals[15] = 260.0
    spike_vals[16] = 60.0
    spike_vals[17] = 60.0
    spike_vals[18] = 60.0
    req_long = PlanRequest(
        city="delhi",
        budget_tier="rs_0",
        members=[HouseholdMember(name="Adult", age=32, conditions=["adult"])],
        activities=[
            ActivityItem(
                id="long_walk",
                name="2.5h Outdoor Task",
                flexibility="flexible",
                planned_hour=9,
                duration_min=150,
                activity_level="brisk_walk",
                member_name="Adult",
            )
        ],
    )
    raw = build_replay_payload("delhi", "test")
    raw["hourly_raw"]["pm2_5"] = spike_vals
    bundle = build_evidence_bundle(req_long, raw, current_hour=9)
    assert bundle.routine_plan[0].recommended_hour == 16


def test_peak_interval_mask_and_emit_less_phone_charges() -> None:
    """Multi-hour fixed task enters poor-PM2.5 peak hour -> triggers N95, plus phone charges."""
    raw = build_replay_payload("pune", "test")
    raw["hourly_raw"]["pm2_5"] = [30.0 if h != 10 else 110.0 for h in range(24)]
    req = PlanRequest(
        city="pune",
        budget_tier="under_500",
        commute_mode="car_petrol_solo",
        target_commute_mode="electric_metro",
        commute_km=10.0,
        members=[HouseholdMember(name="Adult", age=35, conditions=["adult"])],
        activities=[
            ActivityItem(
                id="commute",
                name="Fixed Wait + Walk",
                flexibility="fixed",
                planned_hour=9,
                duration_min=180,
                activity_level="light_walk",
                member_name="Adult",
                current_mask="none",
            )
        ],
    )
    bundle = build_evidence_bundle(req, raw, current_hour=8)
    assert bundle.routine_plan[0].recommended_mask == "n95"
    assert bundle.emit_less.phone_charges_saved == round(bundle.emit_less.co2_saved_g / 8.2)
    assert bundle.emit_less.phone_charges_saved > 0


def test_window_advice_unsealed_vs_sealed_alignment() -> None:
    """Window opening threshold compares outdoor minimum strictly against modeled indoor proxy."""
    raw = build_replay_payload("pune", "test")
    raw["hourly_raw"]["pm2_5"] = [55.0 if h == 13 else 180.0 for h in range(24)]
    snapshot = build_air_snapshot(raw, current_hour=9)

    rs0_plan = score_sanctuary(PlanRequest(city="pune", budget_tier="rs_0"), snapshot)
    sealed_plan = score_sanctuary(PlanRequest(city="pune", budget_tier="under_2200"), snapshot)
    assert rs0_plan.window_advice.action == "timed_open"
    assert rs0_plan.window_advice.duration_minutes == 20
    assert sealed_plan.window_advice.action == "keep_shut_exhaust"
    assert sealed_plan.window_advice.duration_minutes == 0


def test_engine_facade_exports_and_constants_parity() -> None:
    """Verify engine facade identity aliases and backend/frontend city & language parity."""
    import json
    from pathlib import Path

    import air_quality
    import engine
    import exposure
    import indoor

    assert engine.find_golden_window is air_quality.find_golden_window
    assert engine.build_air_snapshot is air_quality.build_air_snapshot
    assert engine.compute_interval_dose_ug is exposure.compute_interval_dose_ug
    assert engine.compute_emit_less is exposure.compute_emit_less
    assert engine.score_sanctuary is indoor.score_sanctuary

    root = Path(__file__).resolve().parents[2]
    constants = json.loads((root / "backend" / "data" / "constants.json").read_text("utf-8"))
    js_text = (root / "frontend" / "src" / "data" / "constants.js").read_text("utf-8")

    for city_key, meta in constants["cities"].items():
        assert f"  {city_key}: {{" in js_text
        assert str(round(float(meta["lat"]), 4)).rstrip("0") in js_text
        assert str(round(float(meta["lon"]), 4)).rstrip("0") in js_text

    for lang_key in constants["room_audit_fallback_tips"]:
        assert f'key: "{lang_key}"' in js_text


def test_post_midnight_naqi_slider_indoor_isolation_and_window_cap() -> None:
    """Verify post-midnight PM10 NAQI, 2nd sensitive walk indoor rule, and cap explanation."""
    from schemas import ActivityItem, HouseholdMember

    # 1. Post-midnight 23:00 2h walk sees next-day midnight PM10=450 spike even if PM2.5 is low
    raw = build_replay_payload("delhi", "test")
    raw["hourly_raw"]["pm2_5"] = [25.0] * 24
    raw["hourly_raw"]["pm10"] = [40.0] * 24
    raw["hourly_raw"]["nitrogen_dioxide"] = [20.0] * 24
    raw["multiday_raw"]["pm2_5"] = [25.0] * 120
    raw["multiday_raw"]["pm10"] = [40.0] * 24 + [450.0] + [40.0] * 95
    raw["multiday_raw"]["nitrogen_dioxide"] = [20.0] * 120
    req_mid = PlanRequest(
        city="delhi",
        budget_tier="rs_0",
        members=[HouseholdMember(name="Adult", age=32, conditions=["adult"])],
        activities=[
            ActivityItem(
                id="late_walk",
                name="Late Errand",
                flexibility="fixed",
                planned_hour=23,
                duration_min=120,
                activity_level="light_walk",
                member_name="Adult",
            )
        ],
    )
    bundle_mid = build_evidence_bundle(req_mid, raw, current_hour=22)
    assert bundle_mid.routine_plan[0].original_naqi > 150

    # 2. On flat elevated day, walk #1 uses slider while sensitive walk #2 stays indoor
    flat_raw = build_replay_payload("delhi", "test")
    flat_raw["hourly_raw"]["pm2_5"] = [150.0] * 24
    req_two = PlanRequest(
        city="delhi",
        budget_tier="under_500",
        walk_override_hour=14,
        members=[HouseholdMember(name="Dadi", age=70, conditions=["elderly"])],
        activities=[
            ActivityItem(
                id="walk_1",
                name="Morning Walk",
                flexibility="flexible",
                planned_hour=7,
                duration_min=30,
                activity_level="elderly_walk",
                member_name="Dadi",
            ),
            ActivityItem(
                id="walk_2",
                name="Evening Walk",
                flexibility="flexible",
                planned_hour=18,
                duration_min=30,
                activity_level="elderly_walk",
                member_name="Dadi",
            ),
        ],
    )
    bundle_two = build_evidence_bundle(req_two, flat_raw, current_hour=8)
    assert bundle_two.routine_plan[0].badge == "WHAT-IF • TESTED"
    assert bundle_two.routine_plan[1].badge == "FLEXIBLE • INDOOR"

    # 3. When 90 cap blocks windows while indoor baseline > 90, guidance cites the 90 cap
    cap_raw = build_replay_payload("delhi", "test")
    cap_raw["hourly_raw"]["pm2_5"] = [400.0 if h < 7 or h > 18 else 95.0 for h in range(24)]
    snap_cap = build_air_snapshot(cap_raw, current_hour=12)
    wa_cap = score_sanctuary(PlanRequest(city="delhi", budget_tier="rs_0"), snap_cap).window_advice
    assert wa_cap.modeled_indoor_baseline_pm25 > 90.0
    assert wa_cap.action == "keep_shut_exhaust"
    assert "90" in wa_cap.guidance


def test_user_category_mask_sensitivity_coastal_regime_and_co2_note() -> None:
    """Verify user_category sensitivity with empty members, coastal wind labels, and CO2 note."""
    raw = build_replay_payload("delhi", "test")
    raw["hourly_raw"]["pm2_5"] = [50.0] * 24
    raw["hourly_raw"]["wind_speed_10m"] = [12.0] * 24
    raw["hourly_raw"]["boundary_layer_height"] = [450.0] * 24

    act = ActivityItem(
        id="bus_wait",
        name="Morning Wait",
        flexibility="fixed",
        planned_hour=8,
        duration_min=30,
        activity_level="light_walk",
    )
    senior_req = PlanRequest(
        city="delhi",
        user_category="seniors",
        budget_tier="under_500",
        members=[],
        activities=[act],
    )
    adult_req = PlanRequest(
        city="delhi",
        user_category="adults_commuters",
        budget_tier="under_500",
        members=[],
        activities=[act],
    )
    senior_bundle = build_evidence_bundle(senior_req, raw, current_hour=7)
    adult_bundle = build_evidence_bundle(adult_req, raw, current_hour=7)
    assert senior_bundle.routine_plan[0].recommended_mask == "n95"
    assert adult_bundle.routine_plan[0].recommended_mask == "none"

    assert "no live indoor co2 sensor" in senior_bundle.sanctuary_plan.co2_safety_note.lower()
    assert "ajar" in senior_bundle.sanctuary_plan.co2_safety_note.lower()

    inland_snap = build_air_snapshot(raw, current_hour=12)
    assert inland_snap.meteorology_regime == "Strong Daytime Wind Dispersion"

    coastal_points = inland_snap.hourly
    _, coastal_regime = classify_meteorology_regime(coastal_points, is_coastal=True)
    assert coastal_regime == "Active Daytime / Sea-Breeze Dispersion"


def test_non_overlapping_per_member_scheduling_preserves_other_members() -> None:
    """Same member must not overlap fixed or flexible slots; another member may reuse best hour."""
    raw = build_replay_payload("delhi", "test")
    # Make hour 14 strictly cleanest, hour 13 second cleanest
    raw["hourly_raw"]["pm2_5"] = [120.0] * 24
    raw["hourly_raw"]["pm2_5"][14] = 35.0
    raw["hourly_raw"]["pm2_5"][13] = 45.0
    raw["hourly_raw"]["pm2_5"][15] = 55.0

    req = PlanRequest(
        city="delhi",
        budget_tier="under_500",
        members=[
            HouseholdMember(name="Rohan", age=28, conditions=["adult"]),
            HouseholdMember(name="Meera", age=30, conditions=["adult"]),
        ],
        activities=[
            ActivityItem(
                id="rohan_fixed",
                name="Fixed Noon Errand",
                flexibility="fixed",
                planned_hour=14,
                duration_min=60,
                member_name="Rohan",
            ),
            ActivityItem(
                id="rohan_walk_1",
                name="Walk 1",
                flexibility="flexible",
                planned_hour=7,
                duration_min=60,
                member_name="Rohan",
            ),
            ActivityItem(
                id="rohan_walk_2",
                name="Walk 2",
                flexibility="flexible",
                planned_hour=18,
                duration_min=60,
                member_name="Rohan",
            ),
            ActivityItem(
                id="meera_walk",
                name="Meera Walk",
                flexibility="flexible",
                planned_hour=8,
                duration_min=45,
                member_name="Meera",
            ),
        ],
    )
    bundle = build_evidence_bundle(req, raw, current_hour=6)
    by_id = {item.id: item for item in bundle.routine_plan}
    assert [item.id for item in bundle.routine_plan] == [
        "rohan_fixed",
        "rohan_walk_1",
        "rohan_walk_2",
        "meera_walk",
    ]
    assert by_id["rohan_fixed"].recommended_hour == 14
    rohan_hours = {
        by_id["rohan_fixed"].recommended_hour,
        by_id["rohan_walk_1"].recommended_hour,
        by_id["rohan_walk_2"].recommended_hour,
    }
    assert len(rohan_hours) == 3
    assert rohan_hours == {13, 14, 15}
    assert by_id["meera_walk"].recommended_hour == 14
