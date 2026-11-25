"""Grounded Gemini Flash explainer with shared deterministic Do/Avoid templates."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Callable
from typing import Any, Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types

from data_fetcher import CONSTANTS
from safety import (
    EMERGENCY_DIRECTIVE,
    PARTIAL_DISCLOSURE_TOKENS,
    STALE_DISCLOSURE_TOKENS,
    check_medical_emergency,
    validate_narrative,
)
from schemas import EvidenceBundle, LanguageCode, RoomAuditResponse, RoomAuditTip

load_dotenv()

logger = logging.getLogger("prana_ai.explainer")

GEMINI_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
)
PLACEHOLDER_KEY = "your_google_ai_studio_key_here"
MODEL_404_TTL_SECONDS = 600.0
KEY_429_COOLDOWN_SECONDS = 45.0

_CLIENT_CACHE: dict[str, genai.Client] = {}
_MODEL_UNAVAILABLE_UNTIL: dict[tuple[str, str], float] = {}
_KEY_COOLDOWN_UNTIL: dict[str, float] = {}

SYSTEM_PROMPT = """You are PRANA-AI, a warm, helpful neighbor and family air-quality guide in India.
You receive precomputed air and schedule facts in JSON.

STRICT RULES:
1. NEVER invent, recalculate, round, or alter any number from the provided JSON data.
2. Always keep PM2.5 concentration (ug/m3) and India NAQI separate.
3. Keep personal exposure ("Breathe Less") separate from travel CO2e saved ("Emit Less").
4. NEVER call any polluted outdoor window "safe"—use "lower-exposure window" or "cleaner window".
5. NEVER recommend indoor houseplants for PM2.5 removal.
6. Never use developer jargon such as "EvidenceBundle", "mixing lid", "modeled proxy",
   or "microenvironment multiplier"—write in plain, everyday family words.
7. Respect fixed commitments (school, work, delivery shifts) with practical steps;
   never say "just stay home."
8. If `is_stale` or `is_fallback_replay` is true, disclose that live data is unavailable and
   historical replay is shown; if `is_partial_fallback` is true, note fallback slots were used.
9. Match requested language (`en`, `hinglish`, `hi`, `mr`, `kn`, `bn`, `ta`, `te`) in clear,
   warm 8th-grade reading level.
"""

VISION_SYSTEM_PROMPT = """You are PRANA-AI, an indoor air quality specialist helping families
lower indoor PM2.5 at low cost (Rs 0 to Rs 500).
Inspect the uploaded room or kitchen photo carefully for practical ventilation and dust issues:
- Visible window/door frame gaps, unsealed under-door gaps, or road-facing openings
- Kitchen exhaust placement, open kitchen partition near stove, or stagnant smoke traps
- Soft dust traps (heavy curtains, rugs, open shelves near beds, fan blade/grill buildup)

Return STRICT JSON ONLY matching this exact schema (no markdown fences, no extra prose):
{
  "room_summary": "1-2 short sentences describing what you see and its main priority.",
  "tips": [
    {
      "title": "Short 3-6 word action title",
      "cost_inr": "Rs. 0",
      "action": "Specific step the family can do today",
      "why_it_helps": "Simple reason in everyday words"
    }
  ]
}
Provide EXACTLY 3 tips costing Rs. 0 to Rs. 500 in the requested language (`en`, `hinglish`,
`hi`, `mr`, `kn`, `bn`, `ta`, or `te`). NEVER recommend houseplants or invent sensor numbers."""


def reset_failover_cache() -> None:
    """Clear cached key cooldowns and 404 model skips (primarily for tests)."""
    _MODEL_UNAVAILABLE_UNTIL.clear()
    _KEY_COOLDOWN_UNTIL.clear()


def _get_client(api_key: str) -> genai.Client:
    """Reuse google-genai Client per API key with a bounded >=10s SDK HTTP timeout."""
    client = _CLIENT_CACHE.get(api_key)
    if client is None:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=10_000),
        )
        _CLIENT_CACHE[api_key] = client
    return client


def _get_api_keys() -> list[str]:
    """Collect deduplicated Gemini keys from env vars."""
    raw_candidates: list[str] = []
    comma_keys = os.getenv("GEMINI_API_KEYS", "")
    if comma_keys:
        raw_candidates.extend(k.strip() for k in comma_keys.split(","))
    for single_var in ("GEMINI_API_KEY", "GEMINI_API_KEY_BACKUP"):
        val = os.getenv(single_var, "").strip()
        if val:
            raw_candidates.append(val)

    keys: list[str] = []
    for k in raw_candidates:
        if k and k != PLACEHOLDER_KEY and k not in keys:
            keys.append(k)
    return keys


def _classify_gemini_error(exc: Exception) -> str:
    """Classify HTTP/timeout errors into 429_quota, 404_model, 503_unavailable, or 504_timeout."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    msg = str(exc).lower()
    if code == 429 or "429" in msg or "resource_exhausted" in msg or "quota" in msg:
        return "429_quota"
    if code == 404 or "404" in msg or "not_found" in msg:
        return "404_model"
    if code == 503 or "503" in msg or "unavailable" in msg:
        return "503_unavailable"
    timeout_tokens = ("504", "deadline", "timed out")
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or code == 504 or any(
        tok in msg for tok in timeout_tokens
    ):
        return "504_timeout"
    return "other"


def format_do_avoid_response(
    air_line: str,
    do_items: list[str],
    avoid_items: list[str],
    headings: tuple[str, str, str] = ("Today's Air:", "Do This:", "Avoid This:"),
    stale_prefix: str = "",
) -> str:
    """Render a consistent 3-block scannable guidance message for both plans and chat replies."""
    air_h, do_h, avoid_h = headings
    do_block = "\n".join(f"- {item}" for item in do_items)
    avoid_block = "\n".join(f"- {item}" for item in avoid_items)
    return f"{stale_prefix}{air_h}\n{air_line}\n\n{do_h}\n{do_block}\n\n{avoid_h}\n{avoid_block}"


def _build_english_plan_content(bundle: EvidenceBundle) -> tuple[str, list[str], list[str]]:
    """Build English status line, Do items, and Avoid items directly from EvidenceBundle."""
    air = bundle.air_snapshot
    gw = air.golden_window
    sp = bundle.sanctuary_plan
    el = bundle.emit_less
    bl = bundle.breathe_less
    loc_label = f"{air.city_name} ({air.area_name})" if air.area_name else air.city_name
    prof = bundle.profile_summary

    if prof is not None:
        air_line = (
            f"[{prof.profile_label}] In {loc_label}, PM2.5 is {air.current_pm25} ug/m3 "
            f"(Estimated India NAQI {air.current_naqi}, {air.current_category}). "
            f"{prof.tailored_hero_headline}"
        )
    elif gw.is_clean_air_day:
        air_line = (
            f"In {loc_label}, air is {air.current_category} today (PM2.5 {air.current_pm25} ug/m3, "
            f"Estimated India NAQI {air.current_naqi}); cleanest slot is {gw.window_label}."
        )
    elif gw.has_meaningful_window:
        air_line = (
            f"In {loc_label}, air is {air.current_category} (PM2.5 {air.current_pm25} ug/m3, "
            f"Estimated India NAQI {air.current_naqi}); best lower-exposure window is "
            f"{gw.window_label} ({gw.mean_pm25} ug/m3)."
        )
    else:
        air_line = (
            f"In {loc_label}, air stays {air.current_category} all day (PM2.5 {air.current_pm25} "
            f"ug/m3, Estimated India NAQI {air.current_naqi}), even at {gw.window_label} "
            f"({gw.mean_pm25} ug/m3)."
        )

    do_items: list[str] = []
    if prof and prof.profile_key == "delivery_riders":
        do_items.append(
            f"Wear a snug N95 on traffic shifts and wait 10-15m off curbs to lower daily dose "
            f"from {bl.baseline_dose_ug} ug to {bl.optimized_dose_ug} ug."
        )
    elif prof and prof.profile_key == "seniors":
        do_items.append(
            f"Keep breathing calm (~{prof.peak_ventilation_m3_hr} m3/hr), walk at "
            f"{gw.window_label}, and keep rescue medication inside '{sp.sanctuary_room}'."
        )
    elif prof and prof.profile_key == "students_kids":
        do_items.append(
            f"Shift outdoor play to {gw.window_label} ({gw.mean_pm25} ug/m3) to cut active "
            f"uptake (saves {bl.dose_avoided_ug} ug PM2.5)."
        )
    elif gw.is_clean_air_day:
        do_items.append(
            f"Enjoy regular outdoor walks or play; cleanest daytime slot is {gw.window_label}."
        )
    elif gw.has_meaningful_window:
        do_items.append(
            f"Shift flexible walks to {gw.window_label} ({gw.mean_pm25} ug/m3) to help avoid "
            f"{bl.dose_avoided_ug} ug PM2.5."
        )
    else:
        do_items.append(
            f"Move strenuous exercise indoors into '{sp.sanctuary_room}' and wear N95 outdoors."
        )

    if el.co2_saved_g > 0:
        do_items.append(
            f"Use {el.target_mode_label} over {el.commute_km} km to save {el.co2_saved_g} g CO2e "
            f"and {el.tailpipe_pm25_saved_mg} mg tailpipe PM2.5."
        )
    else:
        do_items.append(
            "Wear a fitted N95 mask on traffic shifts and step back from idling vehicles."
        )

    do_items.append(
        f"Make '{sp.sanctuary_room}' your clean room and shut kitchen door while exhausting 15 min."
    )

    avoid_items: list[str] = []
    if not gw.is_clean_air_day:
        avoid_items.append(
            f"Skip strenuous outdoor cardio at morning peak ({gw.morning_peak_pm25} ug/m3)."
        )
    avoid_items.append(
        "Avoid dry jhadu sweeping, agarbatti/coils, or airtight doors overnight (leave ajar)."
    )
    return air_line, do_items, avoid_items


def build_deterministic_plan_narrative(bundle: EvidenceBundle) -> str:
    """Render a scannable 3-block (Today's Air / Do This / Avoid This) multilingual plan."""
    if bundle.emergency_alert:
        return bundle.emergency_message or EMERGENCY_DIRECTIVE

    air = bundle.air_snapshot
    gw = air.golden_window
    bl = bundle.breathe_less
    el = bundle.emit_less
    sp = bundle.sanctuary_plan
    loc_label = f"{air.city_name} ({air.area_name})" if air.area_name else air.city_name
    is_replay = bundle.provenance.is_stale or bundle.provenance.is_fallback_replay
    is_partial = bundle.provenance.is_partial_fallback and not is_replay

    templates = CONSTANTS.get("deterministic_plan_templates", {})
    tpl = templates.get(bundle.language)
    if tpl:
        stale_prefix = (
            str(tpl["stale_prefix"])
            if is_replay
            else (str(tpl.get("partial_prefix", "")) if is_partial else "")
        )
        ctx = {
            "loc_label": loc_label,
            "current_pm25": air.current_pm25,
            "current_naqi": air.current_naqi,
            "current_category": air.current_category,
            "window_label": gw.window_label,
            "mean_pm25": gw.mean_pm25,
            "dose_avoided_ug": bl.dose_avoided_ug,
            "sanctuary_room": sp.sanctuary_room,
            "target_mode_label": el.target_mode_label,
            "co2_saved_g": el.co2_saved_g,
            "tailpipe_pm25_saved_mg": el.tailpipe_pm25_saved_mg,
            "morning_peak_pm25": gw.morning_peak_pm25,
        }
        use_window = gw.is_clean_air_day or gw.has_meaningful_window
        line_key = "air_line_window" if use_window else "air_line_flat"
        co2_key = "co2_bullet_nonzero" if el.co2_saved_g > 0 else "co2_bullet_same_mode"
        do_items = [
            *[str(b).format(**ctx) for b in tpl["do_bullets_base"]],
            str(tpl[co2_key]).format(**ctx),
        ]
        headings = (
            str(tpl["air_heading"]),
            str(tpl["do_heading"]),
            str(tpl["avoid_heading"]),
        )
        return format_do_avoid_response(
            air_line=str(tpl[line_key]).format(**ctx),
            do_items=do_items,
            avoid_items=[str(b).format(**ctx) for b in tpl["avoid_bullets"]],
            headings=headings,
            stale_prefix=stale_prefix,
        )

    stale_en = (
        f"Note: Live data unavailable; showing historical replay ({bundle.provenance.source}).\n\n"
        if is_replay
        else (
            f"Note: Partial fallback active — some forecast slots use offline baseline "
            f"({bundle.provenance.source}).\n\n"
            if is_partial
            else ""
        )
    )
    air_line, do_items, avoid_items = _build_english_plan_content(bundle)
    return format_do_avoid_response(air_line, do_items, avoid_items, stale_prefix=stale_en)


def _chat_topic_payload(q: str, bundle: EvidenceBundle) -> tuple[str, list[str], list[str]] | None:
    """Resolve deterministic chat topic into (intro, do_items, avoid_items)."""
    air = bundle.air_snapshot
    gw = air.golden_window
    sp = bundle.sanctuary_plan
    bl = bundle.breathe_less
    el = bundle.emit_less

    window_tokens = (
        "window", "open", "shut", "khidki", "ventilat", "kitchen", "tadka", "room", "sanctuary"
    )
    if any(w in q for w in window_tokens):
        return (
            f"Keep '{sp.sanctuary_room}' as cleanest room today. {sp.window_advice.guidance}",
            [
                "Close the kitchen door before tadka and run exhaust fan for 15 minutes afterward.",
                sp.co2_safety_note,
            ],
            ["Do not leave street-facing windows open during morning/evening rush hours."],
        )

    if any(w in q for w in ("walk", "jog", "play", "outside", "bahar", "time", "when", "kab")):
        intro = (
            f"Today in {air.city_name}, air is Good/Satisfactory ({gw.mean_pm25} ug/m3 at "
            f"{gw.window_label}), so normal walks are fine."
            if gw.is_clean_air_day
            else f"Lower-exposure window in {air.city_name} is {gw.window_label} ({gw.mean_pm25} "
            f"ug/m3 PM2.5, Estimated NAQI {gw.mean_naqi}), down from {gw.morning_peak_pm25} ug/m3."
        )
        return (
            intro,
            [
                f"Plan walks around {gw.window_label} on tree-lined lanes away from main roads.",
                "Carry a fitted N95 mask if air is Moderate or worse.",
            ],
            [f"Skip early-morning outdoor runs when smog sits at {gw.morning_peak_pm25} ug/m3."],
        )

    if any(w in q for w in ("mask", "n95", "ffp2", "cloth", "surgical")):
        mask_items = [r.name for r in bundle.routine_plan if r.recommended_mask == "n95"]
        target_note = f" (especially for {', '.join(mask_items[:2])})" if mask_items else ""
        return (
            f"At {air.current_pm25} ug/m3 PM2.5 (Estimated NAQI {air.current_naqi}), a snug N95 "
            f"gives ~80% filtration{target_note}.",
            [
                "Press the nose clip tight so unfiltered traffic air does not leak around cheeks.",
                "Replace disposable N95 masks once straps loosen or breathing resistance rises.",
            ],
            ["Avoid cloth/loose surgical masks in heavy traffic (only 20-35% filter efficiency)."],
        )

    indoor_tokens = ("indoor", "exercise", "yoga", "workout", "cardio", "active", "stretch")
    if any(w in q for w in indoor_tokens):
        return (
            f"Stick to gentle indoor movement inside '{sp.sanctuary_room}' today "
            f"(PM2.5 {air.current_pm25} ug/m3, Estimated NAQI {air.current_naqi}).",
            [
                "Do 15-20 minutes of gentle yoga, stretching, or light hallway walking.",
                "Stay hydrated and rinse your nose/throat with plain water after commuting.",
            ],
            ["Avoid heavy HIIT/cardio above NAQI 200—fast breathing pulls deeper dust."],
        )

    kid_tokens = ("child", "kid", "school", "senior", "dad", "mom", "elderly", "asthma", "copd")
    if any(w in q for w in kid_tokens):
        return (
            f"With PM2.5 at {air.current_pm25} ug/m3 (NAQI {air.current_naqi}) in {air.city_name}, "
            f"keep fixed trips brief and shift walks/play to {gw.window_label}.",
            [
                "Use a well-fitted N95 mask at bus stops and arrive just before pickup.",
                f"Keep prescribed rescue inhalers handy inside '{sp.sanctuary_room}'.",
            ],
            [f"Avoid play at morning peak ({gw.morning_peak_pm25} ug/m3) or idling vehicles."],
        )

    emit_tokens = (
        "co2", "car", "metro", "bus", "commute", "emit", "save", "cigarette", "dose", "math"
    )
    if any(w in q for w in emit_tokens):
        return (
            f"Today's plan avoids {bl.dose_avoided_ug} ug inhaled PM2.5 ({bl.reduction_pct}% less, "
            f"~{bl.cigarettes_avoided} cigarette equivalents) and saves {el.co2_saved_g} g CO2e "
            f"plus {el.tailpipe_pm25_saved_mg} mg tailpipe PM2.5 over {el.commute_km} km.",
            [
                f"Prefer {el.target_mode_label} or keep car AC on internal recirculate in traffic.",
                "Combine cleaner walk timing + N95 choices for the biggest lung-dose drop.",
            ],
            ["Avoid driving solo with windows down or fresh-air intake in congestion."],
        )

    trip_tokens = (
        "trip", "travel", "journey", "outing", "vacation", "tour", "picnic", "highway", "drive"
    )
    if any(w in q for w in trip_tokens):
        outlook = air.daily_outlook or []
        best_day = min(outlook, key=lambda d: d.peak_naqi) if outlook else None
        note = (
            f" Over 5 days, {best_day.day_label} looks cleanest "
            f"(peak NAQI {best_day.peak_naqi}, best slot {best_day.best_window_label})."
            if best_day
            else ""
        )
        return (
            f"For a trip around {air.city_name}, today is {air.current_category} (PM2.5 "
            f"{air.current_pm25} ug/m3, NAQI {air.current_naqi}) with cleanest departure at "
            f"{gw.window_label} ({gw.mean_pm25} ug/m3).{note}",
            [
                f"Time outdoor sightseeing for {gw.window_label} and pick {el.target_mode_label} "
                f"where practical to save {el.co2_saved_g} g CO2e.",
                "Keep cab/car AC on Internal Recirculate in highway traffic and pack N95 masks.",
            ],
            [f"Avoid early-morning (6-9 AM) outdoor stops near {gw.morning_peak_pm25} ug/m3."],
        )

    if any(w in q for w in ("plant", "houseplant", "snake plant", "paudhe")):
        return (
            sp.no_houseplants_note,
            ["Focus on wet mopping (pochha), closing kitchen door for tadka, and sealing leaks."],
            ["Avoid relying on indoor potted plants to clean PM2.5."],
        )
    return None


def build_deterministic_chat_reply(
    message: str, bundle: EvidenceBundle, language: LanguageCode
) -> str:
    """Answer user questions directly first, followed by unified What to Do / Avoid bullets."""
    q = message.lower().strip()
    air = bundle.air_snapshot
    stale_prefix = (
        f"Note: Live data unavailable; using historical replay ({bundle.provenance.source}).\n\n"
        if bundle.provenance.is_stale or bundle.provenance.is_fallback_replay
        else ""
    )

    clean_words = q.strip("!?., ")
    greetings = {"hi", "hii", "hiii", "hello", "hey", "heyy", "namaste", "namaskar", "hola", "yo"}
    if clean_words in greetings or (
        any(clean_words.startswith(g + " ") for g in ("hi", "hii", "hello", "hey", "namaste"))
        and len(clean_words) <= 18
    ):
        return (
            f"{stale_prefix}Hi! I'm PRANA-AI. In {air.city_name} right now, PM2.5 is "
            f"{air.current_pm25} ug/m3 and Estimated India NAQI is {air.current_naqi} "
            f"({air.current_category}).\n\n"
            "Ask me about walk times, masks, windows, indoor exercise, trips, or commute savings!"
        )

    topic = _chat_topic_payload(q, bundle)
    if topic is not None:
        intro, do_items, avoid_items = topic
        return format_do_avoid_response(
            intro,
            do_items,
            avoid_items,
            headings=("Direct Answer:", "What to Do:", "What to Avoid:"),
            stale_prefix=stale_prefix,
        )

    return build_deterministic_plan_narrative(bundle.model_copy(update={"language": language}))


def _serialize_evidence_for_llm(bundle: EvidenceBundle) -> str:
    """Serialize compact air, schedule, and ledger facts without noisy hourly arrays."""
    compact = {
        "app_name": bundle.app_name,
        "city": bundle.city,
        "city_name": bundle.city_name,
        "area_name": bundle.area_name,
        "language": bundle.language,
        "budget_tier": bundle.budget_tier,
        "provenance": bundle.provenance.model_dump(mode="json"),
        "air_snapshot": bundle.air_snapshot.model_dump(
            mode="json",
            exclude={"hourly": True},
        ),
        "routine_plan": [
            item.model_dump(
                mode="json",
                include={
                    "name",
                    "member_name",
                    "flexibility",
                    "badge",
                    "original_hour",
                    "recommended_hour",
                    "duration_min",
                    "original_pm25",
                    "recommended_pm25",
                    "original_naqi",
                    "recommended_naqi",
                    "recommended_mask",
                    "dose_avoided_ug",
                },
            )
            for item in bundle.routine_plan
        ],
        "sanctuary_plan": bundle.sanctuary_plan.model_dump(
            mode="json",
            exclude={"applicable_hacks": True},
        ),
        "breathe_less": bundle.breathe_less.model_dump(
            mode="json",
            exclude={"substitutions": True, "limitations": True},
        ),
        "emit_less": bundle.emit_less.model_dump(
            mode="json",
            exclude={"substitutions": True, "limitations": True},
        ),
        "profile_summary": (
            bundle.profile_summary.model_dump(mode="json") if bundle.profile_summary else None
        ),
    }
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def _call_gemini_sync(prompt: str, model_name: str, api_key: str) -> str:
    """Invoke Google Gemini synchronously via pooled google-genai Client."""
    client = _get_client(api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
            max_output_tokens=500,
        ),
    )
    return (response.text or "").strip()


def _call_gemini_vision_sync(
    prompt: str,
    image_bytes: bytes,
    mime_type: str,
    model_name: str,
    api_key: str,
) -> str:
    """Invoke Google Gemini Vision synchronously via pooled google-genai Client."""
    client = _get_client(api_key)
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    content_msg = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt), image_part],
    )
    response = client.models.generate_content(
        model=model_name,
        contents=content_msg,
        config=types.GenerateContentConfig(
            system_instruction=VISION_SYSTEM_PROMPT,
            temperature=0.2,
            max_output_tokens=700,
            response_mime_type="application/json",
        ),
    )
    return (response.text or "").strip()


async def _run_gemini_with_failover(
    invoke_sync: Callable[[str, str], str],
    postprocess: Callable[[str, str], Any],
) -> tuple[Any, str | None]:
    """Rotate across API keys on 429 and fail over models on 404/503/504/timeout."""
    keys = _get_api_keys()
    if not keys:
        return None, None

    overall_deadline = time.monotonic() + 14.0
    for key_idx, api_key in enumerate(keys):
        if _KEY_COOLDOWN_UNTIL.get(api_key, 0.0) > time.monotonic():
            continue
        for model_name in GEMINI_MODELS:
            if _MODEL_UNAVAILABLE_UNTIL.get((api_key, model_name), 0.0) > time.monotonic():
                continue
            remaining = overall_deadline - time.monotonic()
            if remaining <= 0.5:
                logger.warning("Gemini failover deadline reached before trying %s.", model_name)
                return None, None
            call_timeout = min(8.0, remaining)
            try:
                raw_text = await asyncio.wait_for(
                    asyncio.to_thread(invoke_sync, model_name, api_key),
                    timeout=call_timeout,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                kind = _classify_gemini_error(exc)
                ts_now = time.monotonic()
                logger.warning(
                    "Gemini key#%d model=%s failed (%s: %s).",
                    key_idx + 1,
                    model_name,
                    kind,
                    type(exc).__name__,
                )
                if kind == "429_quota":
                    _KEY_COOLDOWN_UNTIL[api_key] = ts_now + KEY_429_COOLDOWN_SECONDS
                    break
                if kind == "404_model":
                    _MODEL_UNAVAILABLE_UNTIL[(api_key, model_name)] = (
                        ts_now + MODEL_404_TTL_SECONDS
                    )
                continue

            parsed = postprocess(raw_text, model_name)
            if parsed is not None:
                return parsed, model_name
            logger.warning("Gemini output rejected by validator for model %s.", model_name)
    return None, None


async def _try_gemini_with_validation(prompt: str, bundle: EvidenceBundle) -> str | None:
    """Run grounded text prompt with failover and numeric safety validation."""

    def _validate(raw_text: str, _model: str) -> str | None:
        """Accept raw Gemini text only if provenance disclosure and numeric checks pass."""
        text = raw_text
        if (bundle.provenance.is_stale or bundle.provenance.is_fallback_replay) and not any(
            tok in text.lower() for tok in STALE_DISCLOSURE_TOKENS
        ):
            text = f"Historical replay note (live data unavailable): {text}"
        elif bundle.provenance.is_partial_fallback and not any(
            tok in text.lower() for tok in PARTIAL_DISCLOSURE_TOKENS
        ):
            text = f"Partial forecast fallback note (backup slots used): {text}"
        ok, _ = validate_narrative(text, bundle)
        return text if ok else None

    result, _ = await _run_gemini_with_failover(
        lambda model_name, api_key: _call_gemini_sync(prompt, model_name, api_key),
        _validate,
    )
    return result


def build_deterministic_room_audit(
    city: str,
    language: LanguageCode,
    area_name: str | None = None,
    current_naqi: int | None = None,
) -> RoomAuditResponse:
    """Fast Rs 0-500 deterministic IAQ room audit fallback localized to 8 languages."""
    loc = f"{area_name}, {city}" if area_name and area_name.lower() != city.lower() else city
    aqi_note = f" (Estimated India AQI {current_naqi})" if current_naqi is not None else ""

    localized_summaries: dict[str, str] = {
        "hi": (
            f"{loc}{aqi_note} में कम लागत के उपाय: दरवाज़े-खिड़कियों की दरारें सील करें, "
            "तड़का धुआं रोकें और गीला पोछा लगाएं।"
        ),
        "mr": (
            f"{loc}{aqi_note} साठी कमी खर्चातील उपाय: दारं-खिडक्यांच्या फटी सील करा, "
            "फोडणीचा धूर थांबवा आणि ओला पुस घ्या."
        ),
        "kn": (
            f"{loc}{aqi_note} ಮನೆಗಾಗಿ ಕಡಿಮೆ ವೆಚ್ಚದ ಕ್ರಮಗಳು: ಬಾಗಿಲು-ಕಿಟಕಿ ಸಂದಿಗಳನ್ನು ಮುಚ್ಚಿ, "
            "ಒಗ್ಗರಣೆ ಹೊಗೆ ನಿಯಂತ್ರಿಸಿ ಮತ್ತು ಒದ್ದೆ ಒರೆಸಿ."
        ),
        "bn": (
            f"{loc}{aqi_note}-এর ঘরের জন্য কম খরচের উপায়: দরজা-জানালার ফাঁক বন্ধ করুন, "
            "রান্নার ধোঁয়া আটকান ও ভেজা মুছুন।"
        ),
        "ta": (
            f"{loc}{aqi_note} வீட்டுக்கான குறைந்த செலவு தீர்வு: கதவு-ஜன்னல் இடைவெளிகளை "
            "அடைத்து சமையல் புகையை வெளியேற்றுங்கள்."
        ),
        "te": (
            f"{loc}{aqi_note} ఇంటికి తక్కువ ఖర్చు చిట్కాలు: తలుపు-కిటికీ సందులను సీల్ చేసి "
            "వంట పొగను బయటకు పంపండి."
        ),
        "hinglish": (
            f"{loc}{aqi_note} ke room ke liye smart Rs 0-500 sealing aur ventilation steps."
        ),
    }
    summary = localized_summaries.get(
        language,
        f"Low-cost sealing, cooking-smoke isolation, and wet-cleaning audit for {loc}{aqi_note}.",
    )

    tips_table = CONSTANTS.get("room_audit_fallback_tips", {})
    raw_tips = tips_table.get(language) or tips_table.get("en", [])
    tips = [RoomAuditTip(**item) for item in raw_tips[:3]]

    return RoomAuditResponse(
        city=city,
        area_name=area_name,
        language=language,
        room_summary=summary,
        tips=tips,
        source="deterministic_template",
        model_used=None,
    )


def _parse_room_audit_json(
    raw_text: str,
    model_name: str,
    city: str,
    language: LanguageCode,
    area_name: str | None,
) -> RoomAuditResponse | None:
    """Safely parse and sanitize Gemini Vision JSON output into RoomAuditResponse."""
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    try:
        payload = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    room_summary = str(payload.get("room_summary") or "").strip()
    raw_tips = payload.get("tips")
    if not room_summary or not isinstance(raw_tips, list) or len(raw_tips) == 0:
        return None
    if "houseplant" in room_summary.lower() or "snake plant" in room_summary.lower():
        return None

    banned_plants = ("snake plant", "spider plant", "areca palm", "money plant", "houseplant")
    tips: list[RoomAuditTip] = []
    for item in raw_tips[:3]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        cost = str(item.get("cost_inr") or "").strip()
        cost_match = re.search(r"\d+", cost.replace(",", ""))
        if not cost_match or not 0 <= int(cost_match.group(0)) <= 500:
            continue
        action = str(item.get("action") or "").strip()
        why = str(item.get("why_it_helps") or "").strip()
        combined = f"{title} {action} {why}".lower()
        if any(p in combined for p in banned_plants):
            continue
        if title and action and why:
            tips.append(RoomAuditTip(title=title, cost_inr=cost, action=action, why_it_helps=why))

    if len(tips) < 3:
        fallback = build_deterministic_room_audit(city, language, area_name=area_name)
        for fb_tip in fallback.tips:
            if len(tips) >= 3:
                break
            tips.append(fb_tip)

    return RoomAuditResponse(
        city=city,
        area_name=area_name,
        language=language,
        room_summary=room_summary,
        tips=tips[:3],
        source="gemini",
        model_used=model_name,
    )


async def audit_room_photo(
    image_bytes: bytes,
    mime_type: str,
    city: str,
    language: LanguageCode = "en",
    area_name: str | None = None,
    current_naqi: int | None = None,
) -> RoomAuditResponse:
    """Inspect uploaded room/kitchen image via Gemini Vision with key rotation & fallback."""
    loc = f"{area_name}, {city}" if area_name and area_name.lower() != city.lower() else city
    aqi_ctx = (
        f"Current estimated local India NAQI: {current_naqi}."
        if current_naqi is not None
        else ""
    )
    prompt = (
        f"Requested language: {language}\n"
        f"Location: {loc}, India. {aqi_ctx}\n"
        "Examine this household room/kitchen photo for window/door gaps, exhaust placement, "
        "cooking smoke traps, or dust reservoirs. Return 3 practical Rs. 0 to Rs. 500 fixes JSON."
    )

    parsed, _ = await _run_gemini_with_failover(
        lambda model_name, api_key: _call_gemini_vision_sync(
            prompt, image_bytes, mime_type, model_name, api_key
        ),
        lambda raw_text, model_name: _parse_room_audit_json(
            raw_text, model_name, city, language, area_name
        ),
    )
    if parsed is not None:
        return parsed

    return build_deterministic_room_audit(
        city, language, area_name=area_name, current_naqi=current_naqi
    )


async def generate_plan_narrative(
    bundle: EvidenceBundle,
    skip_llm: bool = False,
) -> tuple[str, Literal["gemini", "deterministic_template", "emergency_triage"], bool]:
    """Generate scannable, validated 3-block Daily Brief via Gemini or fallback."""
    if bundle.emergency_alert:
        return bundle.emergency_message or EMERGENCY_DIRECTIVE, "emergency_triage", True

    if not skip_llm:
        prompt = (
            f"Requested language: {bundle.language}\n"
            "Write a super simple, scannable Daily Brief using ONLY exact numbers below.\n"
            "Use this EXACT 3-block structure (translate headings if not English):\n\n"
            "Today's Air:\n"
            "<1 sentence with PM2.5, Estimated India NAQI, and cleanest outdoor window.>\n\n"
            "Do This:\n"
            "- <short practical action 1>\n"
            "- <short practical action 2>\n"
            "- <short practical action 3>\n\n"
            "Avoid This:\n"
            "- <short thing to skip 1>\n"
            "- <short thing to skip 2>\n\n"
            f"JSON data:\n{_serialize_evidence_for_llm(bundle)}"
        )
        gemini_text = await _try_gemini_with_validation(prompt, bundle)
        if gemini_text:
            return gemini_text, "gemini", True

    narrative = build_deterministic_plan_narrative(bundle)
    ok, _ = validate_narrative(narrative, bundle)
    return narrative, "deterministic_template", ok


ChatReplyResult = tuple[
    str,
    bool,
    str | None,
    Literal["gemini", "deterministic_template", "emergency_triage"],
    bool,
]


async def generate_chat_reply(
    message: str,
    bundle: EvidenceBundle,
    language: LanguageCode,
) -> ChatReplyResult:
    """Handle query-adaptive grounded Q&A with immediate medical triage interception."""
    is_emergency, directive = check_medical_emergency(message)
    if is_emergency:
        return directive or EMERGENCY_DIRECTIVE, True, directive, "emergency_triage", True

    prompt = (
        f"Requested language: {language}\n"
        f"User question: {message}\n\n"
        "Instructions:\n"
        "- If greeting (hi/hello/namaste), reply warmly in 1-2 sentences with PM2.5 and NAQI.\n"
        "- Otherwise answer the user's EXACT question FIRST in 1-2 simple sentences.\n"
        "- Follow with short bullets under 'What to Do:' and 'What to Avoid:' using JSON numbers.\n"
        "- Use warm everyday language (no technical jargon).\n\n"
        f"JSON data:\n{_serialize_evidence_for_llm(bundle)}"
    )
    gemini_reply = await _try_gemini_with_validation(prompt, bundle)
    if gemini_reply:
        return gemini_reply, False, None, "gemini", True

    reply = build_deterministic_chat_reply(message, bundle, language)
    ok, _ = validate_narrative(reply, bundle)
    return reply, False, None, "deterministic_template", ok
