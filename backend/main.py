"""FastAPI entrypoint and REST routes for PRANA-AI."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from collections import defaultdict, deque
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
from safety import check_medical_emergency
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

MAX_ROOM_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
ALLOWED_UPLOAD_MIMES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "application/octet-stream",
}
Image.MAX_IMAGE_PIXELS = 25_000_000

RATE_LIMIT_WINDOW_SECONDS = 60.0
RATE_LIMIT_MAX_REQUESTS = 120
_RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)

raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
allowed_origins = [o.strip().rstrip("/") for o in raw_origins.split(",") if o.strip()]

app = FastAPI(
    title="PRANA-AI API",
    description="Neuro-Symbolic Household Smog & Exposure Planner",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)


class SecurityHeadersMiddleware:
    """Attach baseline HTTP security headers on all backend responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def _send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (
                        b"permissions-policy",
                        b"camera=(self), microphone=(self), geolocation=(self)",
                    ),
                ])
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, _send_with_headers)


class StripApiPrefixMiddleware:
    """Normalize /api/* paths so same-origin Vercel and Vite proxy calls resolve identically."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).startswith("/api/"):
            scope = dict(scope)
            scope["path"] = str(scope["path"])[4:] or "/"
        await self.app(scope, receive, send)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(StripApiPrefixMiddleware)


def _enforce_rate_limit(request: Request, max_requests: int = RATE_LIMIT_MAX_REQUESTS) -> None:
    """Enforce a lightweight per-IP sliding window guard on expensive LLM endpoints."""
    client_host = request.client.host if request.client else "unknown"
    if client_host == "testclient":
        return
    now = time.monotonic()
    bucket = _RATE_BUCKETS[client_host]
    while bucket and (now - bucket[0]) >= RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= max_requests:
        raise HTTPException(
            status_code=429,
            detail="Too many requests right now; please wait a moment and try again.",
        )
    bucket.append(now)


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
    q: str = Query(..., min_length=2, max_length=80),
    count: int = Query(default=5, ge=1, le=10),
) -> list[GeocodeResult]:
    """Search any Indian city, town, or district via Open-Meteo Geocoding API."""
    results = await geocode_india(q, count=count)
    return [GeocodeResult(**item) for item in results]


@app.get("/v1/reverse-geocode", response_model=ReverseGeocodeResult)
async def reverse_geocode_endpoint(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
) -> ReverseGeocodeResult:
    """Resolve browser GPS coordinates to a readable Indian Area, City name."""
    result = await reverse_geocode_india(lat, lon)
    return ReverseGeocodeResult(**result)


@app.get("/v1/presets")
def get_presets() -> list[dict[str, Any]]:
    """Return the 4 preloaded household demo personas."""
    return PRESETS


@app.get("/v1/air", response_model=AirSnapshotResponse)
async def get_air_snapshot(
    city: str = Query(default="delhi", min_length=1, max_length=100),
    lat: float | None = Query(default=None, ge=-90.0, le=90.0),
    lon: float | None = Query(default=None, ge=-180.0, le=180.0),
    area_name: str | None = Query(default=None, max_length=80),
    state: str | None = Query(default=None, max_length=80),
    simulate_stale: bool = Query(default=False),
) -> AirSnapshotResponse:
    """Return 24-hour hourly PM2.5, estimated AQI, PBLH, wind, Golden Window, and provenance."""
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
    if not req.skip_llm:
        _enforce_rate_limit(request)

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
        req,
        raw_payload,
        emergency_alert=emergency_alert,
        emergency_message=emergency_msg,
    )
    narrative, source, validator_passed = await generate_plan_narrative(
        bundle, skip_llm=req.skip_llm
    )
    return PlanResponse(
        evidence_bundle=bundle,
        narrative=narrative,
        narrative_source=source,
        validator_passed=validator_passed,
    )


@app.post("/v1/chat", response_model=ChatResponse)
async def chat_with_plan(req: ChatRequest, request: Request) -> ChatResponse:
    """Grounded multilingual Q&A constrained to today's data with bulletproof fallback."""
    _enforce_rate_limit(request)
    try:
        reply, emergency_alert, emergency_msg, source, validator_passed = await generate_chat_reply(
            req.message,
            req.evidence_bundle,
            req.language,
        )
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Unhandled error in generate_chat_reply; using deterministic fallback.")
        try:
            reply = build_deterministic_chat_reply(req.message, req.evidence_bundle, req.language)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Secondary error in fallback reply; returning compact air summary.")
            air = req.evidence_bundle.air_snapshot
            reply = (
                f"In {air.city_name} right now, PM2.5 is {air.current_pm25} ug/m3 and Estimated "
                f"India NAQI is {air.current_naqi} ({air.current_category}). Cleanest window is "
                f"{air.golden_window.window_label} ({air.golden_window.mean_pm25} ug/m3)."
            )
        emergency_alert, emergency_msg = check_medical_emergency(req.message)
        source = "emergency_triage" if emergency_alert else "deterministic_template"
        validator_passed = True

    return ChatResponse(
        reply=reply,
        emergency_alert=emergency_alert,
        emergency_message=emergency_msg,
        source=source,
        validator_passed=validator_passed,
    )


def _validate_and_optimize_room_image(raw_bytes: bytes) -> tuple[bytes, str]:
    """Verify JPG/PNG/WebP integrity and pixel bounds via Pillow and optimize oversized uploads."""
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            fmt = (img.format or "").upper()
            if fmt not in ALLOWED_IMAGE_FORMATS:
                raise HTTPException(
                    status_code=415,
                    detail="Unsupported image format. Please upload JPG, PNG, or WebP (max 5 MB).",
                )
            mime_type = ALLOWED_IMAGE_FORMATS[fmt]
            img.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(
            status_code=415,
            detail="Invalid or oversized image dimensions. Upload a valid JPG, PNG, or WebP photo.",
        ) from exc

    if len(raw_bytes) > 1_200_000:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            rgb = img.convert("RGB")
            rgb.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=84, optimize=True)
            return out.getvalue(), "image/jpeg"

    return raw_bytes, mime_type


@app.post("/v1/audit-room", response_model=RoomAuditResponse)
async def audit_room_endpoint(
    request: Request,
    file: UploadFile = File(...),
    city: str = Form(default="delhi"),
    language: LanguageCode = Form(default="en"),
    area_name: str | None = Form(default=None),
    current_naqi: int | None = Form(default=None),
) -> RoomAuditResponse:
    """Inspect a room/kitchen photo (JPG/PNG/WebP, max 5MB) and return Rs 0-500 IAQ tips."""
    _enforce_rate_limit(request)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_ROOM_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Image is larger than the 5 MB limit. Please upload a photo under 5 MB.",
            )
        chunks.append(chunk)

    raw_bytes = b"".join(chunks)
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded image file is empty.")

    if file.content_type and file.content_type.lower() not in ALLOWED_UPLOAD_MIMES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported image format. Please upload JPG, PNG, or WebP (max 5 MB).",
        )

    optimized_bytes, mime_type = await asyncio.to_thread(
        _validate_and_optimize_room_image, raw_bytes
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
