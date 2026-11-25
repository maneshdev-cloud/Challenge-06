"""Pydantic v2 request and response schemas for PRANA-AI."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LanguageCode = Literal["en", "hinglish", "hi", "mr", "kn", "bn", "ta", "te"]
FlexibilityType = Literal["fixed", "flexible"]
BudgetTier = Literal["rs_0", "under_500", "under_2200"]
MaskType = Literal["none", "cloth", "surgical", "n95"]
UserCategory = Literal["students_kids", "adults_commuters", "seniors", "delivery_riders"]
ActivityLevel = Literal[
    "sleep",
    "seated",
    "light_walk",
    "brisk_walk",
    "child_play",
    "elderly_walk",
    "running_or_outdoor_work",
]
CommuteMode = Literal[
    "car_petrol_solo",
    "car_diesel_solo",
    "carpool_3p",
    "two_wheeler_petrol",
    "auto_cng",
    "city_bus",
    "electric_metro",
    "walk_or_cycle",
]


class HouseholdMember(BaseModel):
    """Represents a household member and their respiratory vulnerability profile."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=60)
    age: int = Field(..., ge=0, le=110)
    conditions: list[str] = Field(default_factory=list, max_length=10)


class RoomSpec(BaseModel):
    """Physical characteristics of a room used for Clean Air Sanctuary scoring."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=60)
    ext_windows: int = Field(default=1, ge=0, le=10)
    road_facing: bool = False
    kitchen_adjacent: bool = False
    large_volume: bool = False


class ActivityItem(BaseModel):
    """Daily household commitment marked as fixed or flexible."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=60)
    name: str = Field(..., min_length=1, max_length=100)
    flexibility: FlexibilityType
    planned_hour: int = Field(..., ge=0, le=23)
    duration_min: int = Field(..., ge=5, le=720)
    activity_level: ActivityLevel = "light_walk"
    member_name: str = Field(default="Household Member", min_length=1, max_length=60)
    current_mask: MaskType = "none"
    is_commute: bool = False
    is_work_shift: bool = False


class HourlyAirPoint(BaseModel):
    """Single hour of atmospheric pollutant and boundary-layer data."""

    hour: int = Field(..., ge=0, le=23)
    time_label: str
    pm2_5: float
    pm10: float
    nitrogen_dioxide: float
    us_aqi: int | None = None
    cpcb_naqi: int
    cpcb_category: str
    dominant_pollutant: str
    pm25_subindex: int
    pm10_subindex: int
    no2_subindex: int
    temperature_2m: float
    relative_humidity_2m: float
    wind_speed_10m: float
    boundary_layer_height: float


class DataProvenance(BaseModel):
    """Explicit source, freshness, and fallback provenance metadata."""

    source: str
    data_type: Literal["model_forecast", "partial_model_forecast", "historical_replay"]
    retrieved_at: str
    is_stale: bool
    is_fallback_replay: bool
    is_partial_fallback: bool = False
    fallback_slots: int = 0
    spatial_resolution: str = "~40 km CAMS Global (3-hourly interpolated) + NWP Weather"
    spatial_note: str


class GoldenWindow(BaseModel):
    """Lowest-exposure daytime 2-hour window derived from hourly forecast PM2.5."""

    start_hour: int
    end_hour: int
    hours: list[int]
    window_label: str
    mean_pm25: float
    mean_naqi: int
    morning_peak_pm25: float
    reduction_pct: float
    has_meaningful_window: bool
    is_clean_air_day: bool = False
    advisory: str


class GeocodeResult(BaseModel):
    """Single Pan-India city/town match from Open-Meteo Geocoding API."""

    name: str
    state: str = ""
    district: str = ""
    lat: float
    lon: float
    suggested_language: LanguageCode = "hi"
    is_coastal: bool = False


class ReverseGeocodeResult(BaseModel):
    """Readable Indian Area, City resolution from GPS lat/lon."""

    area_name: str
    city: str
    state: str = ""
    lat: float
    lon: float
    suggested_language: LanguageCode = "hi"
    is_coastal: bool = False


class DailyAirOutlook(BaseModel):
    """Single day summary for the 5-day outdoor planning outlook."""

    date: str
    day_label: str
    peak_pm25: float
    peak_naqi: int
    peak_category: str
    best_window_label: str
    best_window_pm25: float
    reduction_pct: float = 0.0
    has_meaningful_window: bool = True
    tip: str


class AirSnapshotResponse(BaseModel):
    """Full 24-hour atmospheric snapshot, estimated hourly AQI summary, and 5-day outlook."""

    city: str
    city_name: str
    area_name: str | None = None
    state: str | None = None
    lat: float | None = None
    lon: float | None = None
    is_coastal: bool = False
    suggested_language: LanguageCode = "hi"
    meteorology_note: str
    current_hour: int
    current_pm25: float
    current_naqi: int
    current_category: str
    dominant_pollutant: str
    morning_inversion_ceiling_m: float
    meteorology_regime: str
    golden_window: GoldenWindow
    hourly: list[HourlyAirPoint]
    daily_outlook: list[DailyAirOutlook] = Field(default_factory=list)
    provenance: DataProvenance


class PlanRequest(BaseModel):
    """Household profile and daily routine input for deterministic planning."""

    model_config = ConfigDict(extra="ignore")

    city: str = Field(default="delhi", min_length=1, max_length=100)
    area_name: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    preset_id: str | None = Field(default=None, max_length=60)
    user_category: UserCategory | None = None
    language: LanguageCode = "en"
    budget_tier: BudgetTier = "under_2200"
    commute_mode: CommuteMode = "car_petrol_solo"
    target_commute_mode: CommuteMode = "electric_metro"
    commute_km: float = Field(default=16.0, ge=0.0, le=200.0)
    uses_agarbatti_or_coils: bool = False
    dry_sweeps: bool = True
    members: list[HouseholdMember] = Field(default_factory=list, max_length=20)
    rooms: list[RoomSpec] = Field(default_factory=list, max_length=20)
    activities: list[ActivityItem] = Field(default_factory=list, max_length=40)
    walk_override_hour: int | None = Field(default=None, ge=0, le=23)
    simulate_stale: bool = False
    skip_llm: bool = False
    symptom_notes: str | None = Field(default=None, max_length=500)


class RoutineItemResult(BaseModel):
    """Scheduled or mitigated outcome for one household activity."""

    id: str
    name: str
    member_name: str
    flexibility: FlexibilityType
    badge: str
    original_hour: int
    recommended_hour: int
    duration_min: int
    original_pm25: float
    recommended_pm25: float
    original_naqi: int
    recommended_naqi: int
    recommended_mask: MaskType
    baseline_dose_ug: float
    optimized_dose_ug: float
    dose_avoided_ug: float
    mitigation_steps: list[str]
    rationale: str


class RoomScore(BaseModel):
    """Clean Air Sanctuary ranking score for a household room."""

    name: str
    score: int
    ext_windows: int
    road_facing: bool
    kitchen_adjacent: bool
    large_volume: bool
    is_sanctuary: bool
    reason: str


class WindowVentilationAdvice(BaseModel):
    """Deterministic window open/shut protocol comparing outdoor vs indoor proxy."""

    action: Literal["timed_open", "keep_shut_exhaust"]
    open_window_start_hour: int | None = None
    open_window_end_hour: int | None = None
    duration_minutes: int
    outdoor_min_pm25: float
    modeled_indoor_baseline_pm25: float
    modeled_post_cooking_pm25: float
    guidance: str


class IAQHack(BaseModel):
    """Budget-tiered indoor air quality action item."""

    id: str
    tier: str
    max_cost_inr: int
    title: str
    action: str
    impact_note: str


class SanctuaryPlan(BaseModel):
    """Complete indoor air quality and sanctuary room recommendation."""

    sanctuary_room: str
    room_scores: list[RoomScore]
    window_advice: WindowVentilationAdvice
    co2_safety_note: str
    no_houseplants_note: str
    applicable_hacks: list[IAQHack]
    personalized_alerts: list[str]


class BreatheLessLedger(BaseModel):
    """Ledger 1: USEPA modeled PM2.5 exposure proxy and Berkeley Earth cig equiv."""

    baseline_dose_ug: float
    optimized_dose_ug: float
    dose_avoided_ug: float
    reduction_pct: float
    cigarettes_avoided: float
    label: str = "Modeled Estimate"
    formula_summary: str
    substitutions: list[str]
    limitations: str


class EmitLessLedger(BaseModel):
    """Ledger 2: ARAI / WRI India transport CO2e and tailpipe PM2.5 savings."""

    baseline_mode: str
    target_mode: str
    baseline_mode_label: str
    target_mode_label: str
    commute_km: float
    co2_saved_g: float
    co2_saved_kg: float
    tailpipe_pm25_saved_mg: float
    phone_charges_saved: int = 0
    label: str = "Modeled Estimate"
    formula_summary: str
    substitutions: list[str]
    limitations: str


class ProfileRiskSummary(BaseModel):
    """Physiology-aware lung capacity, sensitivity tier, and category-specific NAQI warning."""

    profile_key: UserCategory
    profile_label: str
    sensitivity_tier: str
    warning_threshold_naqi: int = 150
    warning_active: bool = False
    risk_level: str = "Low Personal Risk"
    risk_badge: str = "Standard Risk"
    warning_banner: str = ""
    peak_ventilation_m3_hr: float
    total_outdoor_min: int
    tailored_hero_headline: str
    physiology_note: str


class GroundedMetrics(BaseModel):
    """Category-scoped numeric allowlist for strict unit validation in safety.py."""

    model_config = ConfigDict(frozen=True)

    pm25: list[float] = Field(default_factory=list)
    naqi: list[float] = Field(default_factory=list)
    dose_ug: list[float] = Field(default_factory=list)
    cigarettes: list[float] = Field(default_factory=list)
    co2_g: list[float] = Field(default_factory=list)
    co2_kg: list[float] = Field(default_factory=list)
    tailpipe_mg: list[float] = Field(default_factory=list)
    pct: list[float] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    """Immutable deterministic truth object passed to the GenAI explainer."""

    model_config = ConfigDict(frozen=True)

    app_name: str = "PRANA-AI"
    city: str
    city_name: str
    area_name: str | None = None
    language: LanguageCode
    budget_tier: BudgetTier
    emergency_alert: bool = False
    emergency_message: str | None = None
    provenance: DataProvenance
    air_snapshot: AirSnapshotResponse
    routine_plan: list[RoutineItemResult]
    sanctuary_plan: SanctuaryPlan
    breathe_less: BreatheLessLedger
    emit_less: EmitLessLedger
    profile_summary: ProfileRiskSummary | None = None
    grounded_metrics: GroundedMetrics = Field(default_factory=GroundedMetrics)
    grounded_numbers: list[float] = Field(default_factory=list)


class PlanResponse(BaseModel):
    """Top-level response for POST /v1/plan."""

    evidence_bundle: EvidenceBundle
    evidence_signature: str = ""
    narrative: str
    narrative_source: Literal["gemini", "deterministic_template", "emergency_triage"]
    validator_passed: bool


class ChatRequest(BaseModel):
    """Grounded multilingual Q&A request tied to a signed EvidenceBundle."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=1500)
    evidence_bundle: EvidenceBundle
    evidence_signature: str = Field(default="", max_length=128)
    language: LanguageCode = "en"


class ChatResponse(BaseModel):
    """Grounded chat reply with medical triage and validation status."""

    reply: str
    emergency_alert: bool = False
    emergency_message: str | None = None
    source: Literal["gemini", "deterministic_template", "emergency_triage"]
    validator_passed: bool


class RoomAuditTip(BaseModel):
    """Practical Rs 0-500 indoor sealing, ventilation, or dust-control action from room photo."""

    title: str
    cost_inr: str
    action: str
    why_it_helps: str


class RoomAuditResponse(BaseModel):
    """Multimodal indoor air quality room inspection response for POST /v1/audit-room."""

    city: str
    area_name: str | None = None
    language: LanguageCode
    room_summary: str
    tips: list[RoomAuditTip]
    source: Literal["gemini", "deterministic_template"]
    model_used: str | None = None
    disclaimer: str = (
        "Visual household guidance based on your uploaded photo; not a laser PM2.5 measurement."
    )
