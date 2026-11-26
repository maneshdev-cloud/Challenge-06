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
from schemas import PlanRequest


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


@settings(max_examples=25, deadline=None)
@given(
    city=st.sampled_from(("delhi", "mumbai", "pune", "bengaluru", "kolkata")),
    budget_tier=st.sampled_from(("rs_0", "under_500", "under_2200")),
    hour=st.integers(min_value=0, max_value=23),
    pm25_scale=st.floats(min_value=0.4, max_value=2.5, allow_nan=False),
)
def test_plan_never_increases_household_inhaled_dose(
    city: str,
    budget_tier: Literal["rs_0", "under_500", "under_2200"],
    hour: int,
    pm25_scale: float,
) -> None:
    """Optimal schedule and mitigation never result in higher dose than baseline."""
    raw = build_replay_payload(city, "property-test")
    raw["hourly_raw"]["pm2_5"] = [round(v * pm25_scale, 1) for v in raw["hourly_raw"]["pm2_5"]]
    req = PlanRequest(city=city, budget_tier=budget_tier, skip_llm=True)
    bundle = build_evidence_bundle(req, raw, current_hour=hour)
    assert bundle.breathe_less.optimized_dose_ug <= bundle.breathe_less.baseline_dose_ug
    assert bundle.breathe_less.dose_avoided_ug >= 0.0
    assert bundle.breathe_less.reduction_pct >= 0.0
