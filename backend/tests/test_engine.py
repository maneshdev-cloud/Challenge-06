"""Unit tests for the deterministic PRANA-AI physics, CPCB, dosimetry, and scheduler engine."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_fetcher import PRESETS, _build_replay_payload
from engine import (
    build_air_snapshot,
    build_evidence_bundle,
    compute_emit_less,
    compute_hourly_naqi,
    compute_inhaled_dose_ug,
    compute_pm25_naqi,
    find_golden_window,
    score_sanctuary,
)
from schemas import HourlyAirPoint, PlanRequest


def test_cpcb_naqi_breakpoints() -> None:
    """Verify exact CPCB PM2.5 breakpoint interpolation and continuous float bridging."""
    idx_0, cat_0 = compute_pm25_naqi(0)
    assert (idx_0, cat_0) == (0, "Good")

    idx_30, cat_30 = compute_pm25_naqi(30)
    assert (idx_30, cat_30) == (50, "Good")

    # Float between 30 and 31 must never fail or return None
    idx_gap, cat_gap = compute_pm25_naqi(30.4)
    assert 50 <= idx_gap <= 51
    assert cat_gap == "Satisfactory"

    idx_31, cat_31 = compute_pm25_naqi(31)
    assert (idx_31, cat_31) == (51, "Satisfactory")

    idx_250, cat_250 = compute_pm25_naqi(250)
    assert (idx_250, cat_250) == (400, "Very Poor")

    idx_600, cat_600 = compute_pm25_naqi(600)
    assert (idx_600, cat_600) == (500, "Severe")

    # Multi-pollutant dominant pollutant check (high PM10 vs low PM2.5)
    multi = compute_hourly_naqi(pm25=40.0, pm10=320.0, no2=30.0)
    assert multi["dominant_pollutant"] == "PM10"
    assert multi["cpcb_naqi"] > multi["pm25_subindex"]
    assert multi["cpcb_category"] == "Poor"


def test_golden_window_dynamic_and_flat_honesty() -> None:
    """Verify lowest 2h window detection and <15% flat-curve honesty rule."""
    # Case 1: Clear afternoon dip (morning peak 250, 14:00-15:00 = 100)
    diurnal = [220.0] * 24
    diurnal[7] = 250.0
    diurnal[14] = 100.0
    diurnal[15] = 102.0
    points = [
        HourlyAirPoint(
            hour=h, time_label=f"{h:02d}:00", pm2_5=diurnal[h], pm10=diurnal[h] * 1.4,
            nitrogen_dioxide=40.0, us_aqi=180, cpcb_naqi=compute_pm25_naqi(diurnal[h])[0],
            cpcb_category=compute_pm25_naqi(diurnal[h])[1], dominant_pollutant="PM2.5",
            pm25_subindex=300, pm10_subindex=200, no2_subindex=50,
            temperature_2m=20.0, relative_humidity_2m=60.0, wind_speed_10m=5.0,
            boundary_layer_height=800.0 if 11 <= h <= 16 else 80.0,
        )
        for h in range(24)
    ]
    gw = find_golden_window(points)
    assert gw.hours == [14, 15]
    assert gw.has_meaningful_window is True
    assert gw.reduction_pct >= 15.0

    # Case 2: Uniformly elevated flat curve (200 everywhere, 190 at 14:00 -> 5% dip < 15%)
    flat = [200.0] * 24
    flat[14] = 190.0
    flat[15] = 190.0
    flat_points = [
        points[h].model_copy(update={"pm2_5": flat[h]}) for h in range(24)
    ]
    gw_flat = find_golden_window(flat_points)
    assert gw_flat.has_meaningful_window is False
    assert "uniformly elevated" in gw_flat.advisory.lower()

    # Case 3: Clean / Satisfactory air day (PM2.5 ~ 35 ug/m3 -> NAQI <= 100 everywhere)
    clean = [35.0] * 24
    clean[14] = 33.0
    clean[15] = 33.0
    clean_points = [
        points[h].model_copy(
            update={
                "pm2_5": clean[h],
                "cpcb_naqi": compute_pm25_naqi(clean[h])[0],
                "cpcb_category": compute_pm25_naqi(clean[h])[1],
            }
        )
        for h in range(24)
    ]
    gw_clean = find_golden_window(clean_points)
    assert gw_clean.is_clean_air_day is True
    assert gw_clean.has_meaningful_window is True
    assert "good/satisfactory" in gw_clean.advisory.lower()
    assert "uniformly elevated" not in gw_clean.advisory.lower()


def test_dosimetry_and_cigarettes() -> None:
    """Verify USEPA inhaled dose proxy and Berkeley Earth 330 ug cigarette division."""
    # 200 ug/m3 * 1.15 (walk_sidewalk) * 1.30 (elderly_walk) * 1.0 hr * (1 - 0.0) = 299.0
    dose_no_mask = compute_inhaled_dose_ug(200.0, "walk_sidewalk", "elderly_walk", 60, "none")
    assert dose_no_mask == 299.0

    # With N95 (eta = 0.80) -> 299.0 * 0.2 = 59.8
    dose_n95 = compute_inhaled_dose_ug(200.0, "walk_sidewalk", "elderly_walk", 60, "n95")
    assert dose_n95 == 59.8

    delhi_preset = next(p for p in PRESETS if p["id"] == "delhi_family")
    req = PlanRequest(**delhi_preset)
    raw = _build_replay_payload("delhi", "test")
    bundle = build_evidence_bundle(req, raw, current_hour=8)

    expected_cigs = round(bundle.breathe_less.dose_avoided_ug / 330.0, 2)
    assert bundle.breathe_less.cigarettes_avoided == expected_cigs
    assert bundle.breathe_less.dose_avoided_ug > 0


def test_arai_emissions_separation() -> None:
    """Verify ARAI CO2e and tailpipe PM2.5 are decoupled from inhaled PM2.5."""
    req = PlanRequest(
        city="delhi",
        commute_mode="car_petrol_solo",
        target_commute_mode="electric_metro",
        commute_km=16.0,
    )
    emit = compute_emit_less(req)
    # 16 * (164 - 14) = 2400.0 g CO2e; 16 * (18 - 0) = 288.0 mg PM2.5
    assert emit.co2_saved_g == 2400.0
    assert emit.co2_saved_kg == 2.4
    assert emit.tailpipe_pm25_saved_mg == 288.0


def test_fixed_constraint_respected_for_delivery_rider() -> None:
    """Verify Delivery Rider's fixed 8h shifts are never shifted and never told 'stay home'."""
    rider_preset = next(p for p in PRESETS if p["id"] == "delivery_rider")
    req = PlanRequest(**rider_preset)
    raw = _build_replay_payload("delhi", "test")
    bundle = build_evidence_bundle(req, raw, current_hour=8)

    fixed_shifts = [item for item in bundle.routine_plan if item.flexibility == "fixed"]
    assert len(fixed_shifts) == 2
    for shift in fixed_shifts:
        assert shift.recommended_hour == shift.original_hour
        assert shift.badge == "FIXED • MITIGATED"
        assert shift.recommended_mask == "n95"
        joined = " ".join(shift.mitigation_steps).lower() + " " + shift.rationale.lower()
        assert "just stay home" not in joined


def test_sanctuary_scoring_and_what_if_override() -> None:
    """Verify Sanctuary Room selection, CO2 safety note, and What-If walk hour recalculation."""
    delhi_preset = next(p for p in PRESETS if p["id"] == "delhi_family")
    raw = _build_replay_payload("delhi", "test")
    snapshot = build_air_snapshot(raw, current_hour=8)

    req_opt = PlanRequest(**delhi_preset)
    sanctuary = score_sanctuary(req_opt, snapshot)
    assert sanctuary.sanctuary_room == "Inner Back Bedroom"
    assert "ajar" in sanctuary.co2_safety_note.lower()
    assert any(h["tier"] == "Under Rs 2,200" for h in sanctuary.applicable_hacks)

    bundle_opt = build_evidence_bundle(req_opt, raw, current_hour=8)
    req_whatif = PlanRequest(**{**delhi_preset, "walk_override_hour": 7})
    bundle_whatif = build_evidence_bundle(req_whatif, raw, current_hour=8)

    # Moving the walk back to the 07:00 peak lowers avoided exposure compared to the 13:00/14:00 Golden Window
    assert bundle_whatif.breathe_less.dose_avoided_ug < bundle_opt.breathe_less.dose_avoided_ug


def test_category_threshold_100_vs_150_on_moderate_naqi() -> None:
    """Verify NAQI ~132 warns Kids, Seniors, and Delivery Riders (>100) while Adults (>150) stay non-alert."""
    from schemas import ActivityItem, HouseholdMember

    raw = _build_replay_payload("pune", "test")
    # Force hour 10 to PM2.5 70.0 -> CPCB NAQI ~132 (between 101 and 150)
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

    kids = _run("students_kids", HouseholdMember(name="Child", age=9, conditions=["child"]), ActivityItem(id="p", name="Play", flexibility="flexible", planned_hour=17, duration_min=45, activity_level="child_play", member_name="Child"))
    adults = _run("adults_commuters", HouseholdMember(name="Adult", age=34, conditions=["adult"]), ActivityItem(id="w", name="Walk", flexibility="flexible", planned_hour=7, duration_min=40, activity_level="brisk_walk", member_name="Adult"), "car_petrol_solo", "electric_metro", 16.0)
    seniors = _run("seniors", HouseholdMember(name="Senior", age=70, conditions=["elderly", "copd"]), ActivityItem(id="s", name="Walk", flexibility="flexible", planned_hour=6, duration_min=45, activity_level="elderly_walk", member_name="Senior"))
    riders = _run("delivery_riders", HouseholdMember(name="Rider", age=29, conditions=["outdoor_worker"]), ActivityItem(id="d", name="Shift", flexibility="fixed", planned_hour=8, duration_min=480, activity_level="running_or_outdoor_work", member_name="Rider", is_commute=True, is_work_shift=True), "two_wheeler_petrol", "two_wheeler_petrol", 40.0)

    assert 100 < adults.air_snapshot.current_naqi <= 150
    assert kids.profile_summary.warning_active is True
    assert seniors.profile_summary.warning_active is True
    assert riders.profile_summary.warning_active is True
    assert adults.profile_summary.warning_active is False
    assert len(set(seniors.sanctuary_plan.personalized_alerts) ^ set(riders.sanctuary_plan.personalized_alerts)) >= 1


def test_user_categories_differentiate_lung_capacity_and_advice() -> None:
    """Verify Kids, Commuters, Seniors, and Delivery Riders show distinct lung intake & advice on the same city."""
    from schemas import ActivityItem, HouseholdMember

    raw = _build_replay_payload("pune", "test")

    kids_req = PlanRequest(
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
                current_mask="none",
            )
        ],
    )
    seniors_req = PlanRequest(
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
    )
    rider_req = PlanRequest(
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
    )

    kids_b = build_evidence_bundle(kids_req, raw, current_hour=10)
    seniors_b = build_evidence_bundle(seniors_req, raw, current_hour=10)
    rider_b = build_evidence_bundle(rider_req, raw, current_hour=10)

    assert kids_b.profile_summary.profile_key == "students_kids"
    assert seniors_b.profile_summary.profile_key == "seniors"
    assert rider_b.profile_summary.profile_key == "delivery_riders"

    # Ventilation rate (m3/hr) & daily inhaled lung load must visibly differ across groups
    assert rider_b.profile_summary.peak_ventilation_m3_hr == 2.70
    assert kids_b.profile_summary.peak_ventilation_m3_hr == 1.35
    assert seniors_b.profile_summary.peak_ventilation_m3_hr == 1.30
    assert rider_b.breathe_less.baseline_dose_ug > kids_b.breathe_less.baseline_dose_ug
    assert rider_b.routine_plan[0].recommended_mask == "n95"
    assert len({kids_b.profile_summary.tailored_hero_headline, seniors_b.profile_summary.tailored_hero_headline, rider_b.profile_summary.tailored_hero_headline}) == 3
