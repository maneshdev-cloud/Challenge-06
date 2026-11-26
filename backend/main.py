"""FastAPI entrypoint and REST routes for PRANA-AI."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from data_fetcher import (
    CONSTANTS,
    PRESETS,
    fetch_city_atmospheric_data,
    geocode_india,
    reverse_geocode_india,
)
from engine import build_air_snapshot, build_evidence_bundle
from explainer import (
    audit_room_photo,
    build_deterministic_chat_reply,
    generate_chat_reply,
    generate_plan_narrative,
)
from image_audit import read_room_upload_bytes, validate_and_optimize_room_image
from request_guards import (
    DEFAULT_RATE_LIMITER,
    NON_LLM_RATE_LIMITER,
    SecurityAndRequestMiddleware,
    StripApiPrefixMiddleware,
    enforce_rate_limit,
    is_allowed_origin,
)
from safety import (
    check_medical_emergency,
    ensure_bundle_hmac_secret,
    sign_evidence_bundle,
    validate_narrative,
    verify_evidence_bundle,
)
from schemas import (
    AirSnapshotResponse,
    ChatRequest,
    ChatResponse,
    GeocodeResult,
    LanguageCode,
    PlanRequest,
    PlanResponse,
    ReverseGeocodeResult,
    RoomAuditResponse,
)

load_dotenv()

logger = logging.getLogger("prana_ai")

raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in raw_origins.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Fail fast on startup if a deployed environment lacks PRANA_BUNDLE_SECRET."""
    if os.getenv("VERCEL_ENV", "").strip() or os.getenv("RENDER", "").strip():
        ensure_bundle_hmac_secret()
    yield


app = FastAPI(
    title="PRANA-AI API",
    description="Neuro-Symbolic Household Smog & Exposure Planner",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)
app.add_middleware(SecurityAndRequestMiddleware, allowed_origins=ALLOWED_ORIGINS)
app.add_middleware(StripApiPrefixMiddleware)


def _enforce_origin(request: Request) -> None:
    """Reject cross-site browser POSTs whose Origin is not same-host or explicitly allowlisted."""
    origin = request.headers.get("origin")
    host = request.headers.get("host") or request.url.netloc
    if not is_allowed_origin(origin, host, ALLOWED_ORIGINS):
        raise HTTPException(status_code=403, detail="Cross-origin requests are not allowed.")


def _fallback_chat_response(req: ChatRequest) -> ChatResponse:
    """Degrade gracefully to deterministic template or compact snapshot if LLM chat crashes."""
    try:
        reply = build_deterministic_chat_reply(req.message, req.evidence_bundle, req.language)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Secondary error in fallback reply; returning compact air summary.")
        air = req.evidence_bundle.air_snapshot
        prov = req.evidence_bundle.provenance
        prefix = (
            "Note: Live data unavailable (historical replay shown). "
            if prov.is_stale or prov.is_fallback_replay
            else (
                "Note: Partial forecast fallback used for backup slots. "
                if prov.is_partial_fallback
                else ""
            )
        )
        reply = (
            f"{prefix}In {air.city_name} right now, PM2.5 is {air.current_pm25} ug/m3 and "
            f"Estimated India NAQI is {air.current_naqi} ({air.current_category}). Cleanest "
            f"window is {air.golden_window.window_label} ({air.golden_window.mean_pm25} ug/m3)."
        )
    emergency_alert, emergency_msg = check_medical_emergency(req.message)
    if emergency_alert:
        source: Literal["emergency_triage", "deterministic_template"] = "emergency_triage"
        valid = True
    else:
        source = "deterministic_template"
        valid, _ = validate_narrative(reply, req.evidence_bundle)
    return ChatResponse(
        reply=reply,
        emergency_alert=emergency_alert,
        emergency_message=emergency_msg,
        source=source,
        validator_passed=valid,
    )


@app.api_route("/health", methods=["GET", "HEAD"])
def health_check() -> dict[str, str]:
    """Health check endpoint (GET & HEAD) for Vercel, Render, and keep-warm pings."""
    return {"status": "ok", "app": "PRANA-AI", "version": "1.0.0"}


@app.get("/v1/cities")
def get_cities() -> dict[str, Any]:
    """Return featured Indian cities, local languages, and neighborhood coordinates."""
    return dict(CONSTANTS["cities"])


@app.get("/v1/geocode", response_model=list[GeocodeResult])
async def geocode_indian_place(
    request: Request,
    q: str = Query(..., min_length=2, max_length=80),
    count: int = Query(default=5, ge=1, le=10),
) -> list[GeocodeResult]:
    """Search any Indian city, town, or district via cached Open-Meteo Geocoding API."""
    _enforce_origin(request)
    enforce_rate_limit(request, limiter=NON_LLM_RATE_LIMITER)
    results = await geocode_india(q, count=count)
    return [GeocodeResult(**item) for item in results]


@app.get("/v1/reverse-geocode", response_model=ReverseGeocodeResult)
async def reverse_geocode_endpoint(
    request: Request,
    lat: float = Query(..., ge=6.0, le=37.5),
    lon: float = Query(..., ge=68.0, le=97.5),
) -> ReverseGeocodeResult:
    """Resolve Indian GPS coordinates to a cached readable Area, City name."""
    _enforce_origin(request)
    enforce_rate_limit(request, limiter=NON_LLM_RATE_LIMITER)
    try:
        result = await reverse_geocode_india(lat, lon)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ReverseGeocodeResult(**result)


@app.get("/v1/presets")
def get_presets() -> list[dict[str, Any]]:
    """Return the 4 preloaded household demo personas."""
    return PRESETS


@app.get("/v1/air", response_model=AirSnapshotResponse)
async def get_air_snapshot(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    request: Request,
    city: str = Query(default="delhi", min_length=1, max_length=100),
    lat: float | None = Query(default=None, ge=6.0, le=37.5),
    lon: float | None = Query(default=None, ge=68.0, le=97.5),
    area_name: str | None = Query(default=None, max_length=80),
    state: str | None = Query(default=None, max_length=80),
    simulate_stale: bool = Query(default=False),
) -> AirSnapshotResponse:
    """Return 24-hour hourly PM2.5, estimated AQI, PBLH, wind, Golden Window, and provenance."""
    _enforce_origin(request)
    enforce_rate_limit(request, limiter=NON_LLM_RATE_LIMITER)
    if (lat is None) != (lon is None):
        raise HTTPException(
            status_code=422, detail="Both 'lat' and 'lon' must be provided together."
        )
    try:
        raw_payload = await fetch_city_atmospheric_data(
            city,
            simulate_stale=simulate_stale,
            lat=lat,
            lon=lon,
            area_name=area_name,
            state=state,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_air_snapshot(raw_payload)


@app.post("/v1/plan", response_model=PlanResponse)
async def create_plan(req: PlanRequest, request: Request) -> PlanResponse:
    """Run deterministic engine + safety triage + grounded narrative explanation."""
    _enforce_origin(request)
    enforce_rate_limit(
        request,
        limiter=NON_LLM_RATE_LIMITER if req.skip_llm else DEFAULT_RATE_LIMITER,
    )

    symptom_text = " ".join(filter(None, [req.symptom_notes] + [a.name for a in req.activities]))
    emergency_alert, emergency_msg = check_medical_emergency(symptom_text)

    try:
        raw_payload = await fetch_city_atmospheric_data(
            req.city,
            simulate_stale=req.simulate_stale,
            lat=req.lat,
            lon=req.lon,
            area_name=req.area_name,
            state=req.state,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    bundle = build_evidence_bundle(
        req, raw_payload, emergency_alert=emergency_alert, emergency_message=emergency_msg
    )
    narrative, source, validator_passed = await generate_plan_narrative(
        bundle, skip_llm=req.skip_llm
    )
    return PlanResponse(
        evidence_bundle=bundle,
        evidence_signature=sign_evidence_bundle(bundle),
        narrative=narrative,
        narrative_source=source,
        validator_passed=validator_passed,
    )


@app.post("/v1/chat", response_model=ChatResponse)
async def chat_with_plan(req: ChatRequest, request: Request) -> ChatResponse:
    """Grounded multilingual Q&A constrained to HMAC-signed server data with safe fallback."""
    _enforce_origin(request)
    if not verify_evidence_bundle(req.evidence_bundle, req.evidence_signature):
        enforce_rate_limit(request)
        raise HTTPException(status_code=403, detail="Invalid or tampered evidence bundle.")

    is_er, er_directive = check_medical_emergency(req.message)
    if is_er and er_directive:
        return ChatResponse(
            reply=er_directive,
            emergency_alert=True,
            emergency_message=er_directive,
            source="emergency_triage",
            validator_passed=True,
        )

    enforce_rate_limit(request)
    try:
        reply, emergency_alert, emergency_msg, source, validator_passed = await generate_chat_reply(
            req.message, req.evidence_bundle, req.language
        )
        return ChatResponse(
            reply=reply,
            emergency_alert=emergency_alert,
            emergency_message=emergency_msg,
            source=source,
            validator_passed=validator_passed,
        )
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Unhandled error in generate_chat_reply; using deterministic fallback.")
        return _fallback_chat_response(req)


@app.post("/v1/audit-room", response_model=RoomAuditResponse)
async def audit_room_endpoint(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    request: Request,
    file: Annotated[UploadFile, File(...)],
    city: Annotated[str, Form()] = "delhi",
    language: Annotated[LanguageCode, Form()] = "en",
    area_name: Annotated[str | None, Form()] = None,
    current_naqi: Annotated[int | None, Form(ge=0, le=500)] = None,
) -> RoomAuditResponse:
    """Inspect a room/kitchen photo (JPG/PNG/WebP, max 5MB) and return Rs 0-500 IAQ tips."""
    _enforce_origin(request)
    raw_bytes = await read_room_upload_bytes(file)
    optimized_bytes, mime_type = await asyncio.to_thread(
        validate_and_optimize_room_image, raw_bytes
    )
    clean_city = city.strip()[:80] or "delhi"
    clean_area = area_name.strip()[:80] if area_name and area_name.strip() else None

    return await audit_room_photo(
        image_bytes=optimized_bytes,
        mime_type=mime_type,
        city=clean_city,
        language=language,
        area_name=clean_area,
        current_naqi=current_naqi,
    )
