"""Property-based safety and mathematical invariants enforced via Hypothesis."""

from __future__ import annotations

from typing import Literal

from hypothesis import given, settings
from hypothesis import strategies as st

from data_fetcher import build_replay_payload
from engine import (
    build_evidence_bundle,
    compute_hourly_naqi,
    compute_inhaled_dose_ug,
    compute_pm25_naqi,
)
from request_guards import SlidingWindowRateLimiter
from schemas import (
    ActivityItem,
    ActivityLevel,
    BudgetTier,
    CommuteMode,
    HouseholdMember,
    MaskType,
    PlanRequest,
)


@settings(max_examples=50, deadline=None)
@given(
    pm25_a=st.floats(min_value=0.0, max_value=600.0, allow_nan=False, allow_infinity=False),
    pm25_delta=st.floats(min_value=0.0, max_value=300.0, allow_nan=False, allow_infinity=False),
    pm10=st.floats(min_value=0.0, max_value=800.0, allow_nan=False, allow_infinity=False),
    no2=st.floats(min_value=0.0, max_value=800.0, allow_nan=False, allow_infinity=False),
)
def test_cpcb_naqi_monotonic_and_bounded(
    pm25_a: float, pm25_delta: float, pm10: float, no2: float
) -> None:
    """CPCB sub-indices stay within [0, 500], remain monotonic, and equal pollutant max."""
    pm25_b = pm25_a + pm25_delta
    naqi_a, _ = compute_pm25_naqi(pm25_a)
    naqi_b, _ = compute_pm25_naqi(pm25_b)
    assert 0 <= naqi_a <= naqi_b <= 500

    combined = compute_hourly_naqi(pm25_a, pm10, no2)
    assert combined["cpcb_naqi"] == max(
        combined["pm25_subindex"],
        combined["pm10_subindex"],
        combined["no2_subindex"],
    )
    assert 0 <= combined["cpcb_naqi"] <= 500


@settings(max_examples=50, deadline=None)
@given(
    pm25=st.floats(min_value=0.0, max_value=600.0, allow_nan=False, allow_infinity=False),
    duration_min=st.integers(min_value=0, max_value=480),
    activity_level=st.sampled_from(
        ("sleep", "seated", "light_walk", "brisk_walk", "child_play", "elderly_walk")
    ),
    microenv=st.sampled_from(
        ("walk_sidewalk", "open_road_2w_auto", "car_ac_recirc", "electric_metro", "indoor_shut")
    ),
)
def test_inhaled_dose_monotonic_and_n95_never_worsens(
    pm25: float, duration_min: int, activity_level: str, microenv: str
) -> None:
    """Modeled dose is non-negative and better masks strictly reduce or tie exposure."""
    d_none = compute_inhaled_dose_ug(pm25, microenv, activity_level, duration_min, "none")
    d_cloth = compute_inhaled_dose_ug(pm25, microenv, activity_level, duration_min, "cloth")
    d_surg = compute_inhaled_dose_ug(pm25, microenv, activity_level, duration_min, "surgical")
    d_n95 = compute_inhaled_dose_ug(pm25, microenv, activity_level, duration_min, "n95")
    assert 0.0 <= d_n95 <= d_surg <= d_cloth <= d_none


@settings(max_examples=40, deadline=None)
@given(
    max_requests=st.integers(min_value=1, max_value=12),
    window_seconds=st.floats(min_value=1.0, max_value=60.0, allow_nan=False),
    deltas=st.lists(
        st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=40,
    ),
)
def test_rate_limiter_never_exceeds_window_quota(
    max_requests: int, window_seconds: float, deltas: list[float]
) -> None:
    """SlidingWindowRateLimiter never admits more than max_requests in any active window."""
    limiter = SlidingWindowRateLimiter(
        max_requests=max_requests, window_seconds=window_seconds, max_buckets=32
    )
    now = 0.0
    accepted_times: list[float] = []
    for dt in deltas:
        now += dt
        allowed, retry_after = limiter.allow("client-a", now=now)
        in_window = [t for t in accepted_times if (now - t) < window_seconds]
        if allowed:
            accepted_times.append(now)
            assert len(in_window) < max_requests
        else:
            assert retry_after >= 1
            assert len(in_window) >= max_requests


@st.composite
def _plan_with_activities(draw: st.DrawFn) -> tuple[PlanRequest, list[float], int]:
    """Generate randomized non-empty households across 0..23h and realistic pollution curves."""
    budgets: tuple[BudgetTier, ...] = ("rs_0", "under_500", "under_2200")
    commutes: tuple[CommuteMode, ...] = (
        "car_petrol_solo",
        "car_diesel_solo",
        "two_wheeler_petrol",
        "auto_cng",
        "city_bus",
        "electric_metro",
    )
    target_commutes: tuple[CommuteMode, ...] = (
        "electric_metro",
        "city_bus",
        "walk_or_cycle",
        "carpool_3p",
    )
    levels: tuple[ActivityLevel, ...] = ("seated", "light_walk", "brisk_walk", "elderly_walk")
    masks: tuple[MaskType, ...] = ("none", "cloth", "surgical", "n95")
    flex_opts: tuple[Literal["fixed", "flexible"], ...] = ("fixed", "flexible")

    city = draw(st.sampled_from(("delhi", "mumbai", "pune", "bengaluru", "kolkata")))
    budget_tier: BudgetTier = draw(st.sampled_from(budgets))
    commute_mode: CommuteMode = draw(st.sampled_from(commutes))
    target_commute_mode: CommuteMode = draw(st.sampled_from(target_commutes))
    day_scale = draw(st.floats(min_value=0.4, max_value=2.5, allow_nan=False))
    night_scale = draw(st.floats(min_value=0.2, max_value=2.5, allow_nan=False))
    members = [HouseholdMember(name="Member 1", age=draw(st.integers(5, 78)), conditions=["adult"])]
    n_acts = draw(st.integers(min_value=1, max_value=4))
    activities = []
    for idx in range(n_acts):
        flex: Literal["fixed", "flexible"] = draw(st.sampled_from(flex_opts))
        level: ActivityLevel = draw(st.sampled_from(levels))
        mask: MaskType = draw(st.sampled_from(masks))
        is_commute = flex == "fixed" and draw(st.booleans())
        activities.append(
            ActivityItem(
                id=f"act_{idx}",
                name=f"Task {idx}",
                flexibility=flex,
                planned_hour=draw(st.integers(min_value=0, max_value=23)),
                duration_min=draw(st.integers(min_value=15, max_value=180)),
                activity_level=level,
                member_name="Member 1",
                current_mask=mask,
                is_commute=is_commute,
                is_work_shift=flex == "fixed" and not is_commute and draw(st.booleans()),
            )
        )
    req = PlanRequest(
        city=city,
        budget_tier=budget_tier,
        commute_mode=commute_mode,
        target_commute_mode=target_commute_mode,
        members=members,
        activities=activities,
        skip_llm=True,
    )
    hour = draw(st.integers(min_value=0, max_value=23))
    return req, [day_scale, night_scale], hour


@settings(max_examples=30, deadline=None)
@given(generated=_plan_with_activities())
def test_plan_never_increases_household_inhaled_dose(
    generated: tuple[PlanRequest, list[float], int],
) -> None:
    """Optimal schedule and mitigation never result in higher dose than baseline."""
    req, scales, hour = generated
    day_scale, night_scale = scales
    raw = build_replay_payload(req.city, "property-test")
    raw["hourly_raw"]["pm2_5"] = [
        round(v * (night_scale if (h >= 20 or h <= 5) else day_scale), 1)
        for h, v in enumerate(raw["hourly_raw"]["pm2_5"])
    ]
    bundle = build_evidence_bundle(req, raw, current_hour=hour)
    assert bundle.routine_plan
    assert bundle.breathe_less.optimized_dose_ug <= bundle.breathe_less.baseline_dose_ug
    assert bundle.breathe_less.dose_avoided_ug >= 0.0
    assert bundle.breathe_less.reduction_pct >= 0.0
    for item in bundle.routine_plan:
        assert item.optimized_dose_ug <= item.baseline_dose_ug
