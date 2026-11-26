"""ARAI / WRI India transport CO2e and tailpipe PM2.5 savings calculations (Ledger 2)."""

from __future__ import annotations

from typing import Any

from air_quality import ENGINE_PARAMS
from geo_india import CONSTANTS
from schemas import CommuteMode, EmitLessLedger, PlanRequest

__all__ = ["compute_emit_less"]


def _emit_less_substitutions(
    req: PlanRequest,
    base_spec: dict[str, Any],
    target_spec: dict[str, Any],
    co2_saved: tuple[float, float],
    metrics: tuple[float, CommuteMode],
) -> list[str]:
    """Build transparent ARAI emission-factor substitution lines for Show Math."""
    tailpipe_pm25_mg, target_mode = metrics
    co2_g, co2_kg = co2_saved
    subs = [
        f"CO2e = {req.commute_km} km * ({base_spec['co2_g_pkm']} - {target_spec['co2_g_pkm']}) "
        f"g/pkm = {co2_g} g ({co2_kg} kg)",
        f"Tailpipe PM2.5 = {req.commute_km} km * ({base_spec['pm25_mg_pkm']} - "
        f"{target_spec['pm25_mg_pkm']}) mg/pkm = {tailpipe_pm25_mg} mg",
    ]
    if req.commute_mode == target_mode:
        subs.append(
            "Same transport mode kept (e.g., fixed work vehicle); tailpipe counterfactual = 0."
        )
    return subs


def compute_emit_less(
    req: PlanRequest,
    effective_target_mode: CommuteMode | None = None,
) -> EmitLessLedger:
    """Compute Ledger 2 (ARAI / WRI India transport CO2e and tailpipe PM2.5 savings)."""
    target_mode: CommuteMode = effective_target_mode or req.target_commute_mode
    arai_map = CONSTANTS["arai_transport_emissions"]
    base_spec = arai_map.get(req.commute_mode, arai_map["car_petrol_solo"])
    target_spec = arai_map.get(target_mode, arai_map["electric_metro"])

    co2_saved_g = round(
        req.commute_km * (float(base_spec["co2_g_pkm"]) - float(target_spec["co2_g_pkm"])), 1
    )
    co2_saved_kg = round(co2_saved_g / 1000.0, 3)
    tailpipe_pm25_mg = round(
        req.commute_km * (float(base_spec["pm25_mg_pkm"]) - float(target_spec["pm25_mg_pkm"])), 1
    )
    phone_charges = round(max(0.0, co2_saved_g) / float(ENGINE_PARAMS["phone_charge_co2_g"]))

    return EmitLessLedger(
        baseline_mode=req.commute_mode,
        target_mode=target_mode,
        baseline_mode_label=str(base_spec["label"]),
        target_mode_label=str(target_spec["label"]),
        commute_km=req.commute_km,
        co2_saved_g=co2_saved_g,
        co2_saved_kg=co2_saved_kg,
        tailpipe_pm25_saved_mg=tailpipe_pm25_mg,
        phone_charges_saved=phone_charges,
        label="Modeled Estimate",
        formula_summary=(
            "Delta CO2e (g) = km * (EF_CO2_base - EF_CO2_new); "
            "Delta Tailpipe PM2.5 (mg) = km * (EF_PM_base - EF_PM_new)"
        ),
        substitutions=_emit_less_substitutions(
            req,
            base_spec,
            target_spec,
            (co2_saved_g, co2_saved_kg),
            (tailpipe_pm25_mg, target_mode),
        ),
        limitations=(
            "Uses ARAI / WRI India average per-passenger-km emission factors; actual fuel use, "
            "occupancy, and congestion idling vary."
        ),
    )
