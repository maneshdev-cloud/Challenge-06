"""Grounded Gemini Flash explainer orchestrator with strict evidence serialization."""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from fallbacks import (
    build_deterministic_chat_reply as _build_chat_reply_impl,
)
from fallbacks import (
    build_deterministic_plan_narrative as _build_plan_narrative_impl,
)
from fallbacks import (
    build_deterministic_room_audit,
    format_do_avoid_response,
    parse_room_audit_json,
)
from gemini_client import (
    GEMINI_MODELS,
    reset_failover_cache,
    run_gemini_with_failover,
)
from gemini_client import (
    call_gemini_sync as _sdk_call_gemini,
)
from gemini_client import (
    call_gemini_vision_sync as _sdk_call_gemini_vision,
)
from safety import (
    EMERGENCY_DIRECTIVE,
    PARTIAL_DISCLOSURE_TOKENS,
    STALE_DISCLOSURE_TOKENS,
    check_medical_emergency,
    validate_narrative,
)
from schemas import EvidenceBundle, LanguageCode, RoomAuditResponse

__all__ = [
    "GEMINI_MODELS",
    "audit_room_photo",
    "build_deterministic_chat_reply",
    "build_deterministic_plan_narrative",
    "build_deterministic_room_audit",
    "format_do_avoid_response",
    "generate_chat_reply",
    "generate_plan_narrative",
    "reset_failover_cache",
]

logger = logging.getLogger("prana_ai.explainer")

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
10. NEVER prescribe medication, adjust inhaler or pill dosages, or diagnose medical conditions.
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

_ROUTINE_LLM_FIELDS = {
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
}


def _parse_room_audit_json(
    raw_text: str,
    model_used: str,
    city: str,
    language: LanguageCode,
    area_name: str | None,
) -> RoomAuditResponse | None:
    """Parse and sanitize Vision JSON tips via fallbacks.parse_room_audit_json."""
    return parse_room_audit_json(raw_text, model_used, city, language, area_name)


def build_deterministic_plan_narrative(bundle: EvidenceBundle) -> str:
    """Render deterministic grounded daily plan summary."""
    return _build_plan_narrative_impl(bundle, emergency_fallback=EMERGENCY_DIRECTIVE)


def build_deterministic_chat_reply(
    message: str, bundle: EvidenceBundle, language: LanguageCode
) -> str:
    """Render deterministic grounded chat response for topics, greetings, or plan fallback."""
    return _build_chat_reply_impl(
        bundle=bundle,
        message=message,
        language=language,
        emergency_fallback=EMERGENCY_DIRECTIVE,
    )


def _call_gemini_sync(prompt: str, model_name: str, api_key: str) -> str:
    """Invoke pooled Gemini text client using PRANA-AI system instructions."""
    return _sdk_call_gemini(prompt, model_name, api_key, system_instruction=SYSTEM_PROMPT)


def _call_gemini_vision_sync(
    prompt: str,
    image_bytes: bytes,
    mime_type: str,
    model_name: str,
    api_key: str,
) -> str:
    """Invoke pooled Gemini Vision client using PRANA-AI Vision system instructions."""
    return _sdk_call_gemini_vision(
        prompt,
        image_bytes,
        mime_type,
        model_name,
        api_key,
        system_instruction=VISION_SYSTEM_PROMPT,
    )


def serialize_evidence_for_llm(bundle: EvidenceBundle) -> str:
    """Serialize compact air, schedule, and ledger facts without PII names or raw hourly arrays."""
    member_aliases: dict[str, str] = {}
    routine_items = []
    for item in bundle.routine_plan:
        raw_name = item.member_name.strip() or "Member"
        if raw_name not in member_aliases:
            member_aliases[raw_name] = f"Household Member {len(member_aliases) + 1}"
        dumped = item.model_dump(mode="json", include=_ROUTINE_LLM_FIELDS)
        dumped["member_name"] = member_aliases[raw_name]
        routine_items.append(dumped)

    compact = {
        "app_name": bundle.app_name,
        "city": bundle.city,
        "city_name": bundle.city_name,
        "area_name": bundle.area_name,
        "language": bundle.language,
        "budget_tier": bundle.budget_tier,
        "provenance": bundle.provenance.model_dump(mode="json"),
        "air_snapshot": bundle.air_snapshot.model_dump(mode="json", exclude={"hourly": True}),
        "routine_plan": routine_items,
        "sanctuary_plan": bundle.sanctuary_plan.model_dump(
            mode="json", exclude={"applicable_hacks": True}
        ),
        "breathe_less": bundle.breathe_less.model_dump(
            mode="json", exclude={"substitutions": True, "limitations": True}
        ),
        "emit_less": bundle.emit_less.model_dump(
            mode="json", exclude={"substitutions": True, "limitations": True}
        ),
        "profile_summary": (
            bundle.profile_summary.model_dump(mode="json") if bundle.profile_summary else None
        ),
    }
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


async def _try_gemini_with_validation(prompt: str, bundle: EvidenceBundle) -> str | None:
    """Run grounded text prompt with failover and numeric safety validation."""

    def _validate(raw_text: str, _model: str) -> str | None:
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

    result, _ = await run_gemini_with_failover(
        lambda model_name, api_key: _call_gemini_sync(prompt, model_name, api_key),
        _validate,
    )
    return result


def _sanitize_prompt_field(value: str | None, fallback: str = "") -> str:
    """Strip control characters and prompt-breaking newlines from user-supplied metadata."""
    cleaned = re.sub(r"[^\w\s,.'()/-]+", " ", (value or "").strip())
    return re.sub(r"\s+", " ", cleaned).strip()[:60] or fallback


async def audit_room_photo(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    image_bytes: bytes,
    mime_type: str,
    city: str,
    language: LanguageCode = "en",
    area_name: str | None = None,
    current_naqi: int | None = None,
) -> RoomAuditResponse:
    """Inspect uploaded room/kitchen image via Gemini Vision with key rotation & fallback."""
    safe_city = _sanitize_prompt_field(city, "delhi")
    safe_area = _sanitize_prompt_field(area_name) if area_name else None
    bounded_naqi = current_naqi if current_naqi is not None and 0 <= current_naqi <= 500 else None
    loc = (
        f"{safe_area}, {safe_city}"
        if safe_area and safe_area.lower() != safe_city.lower()
        else safe_city
    )
    aqi_ctx = (
        f"Current estimated local India NAQI: {bounded_naqi}." if bounded_naqi is not None else ""
    )
    prompt = (
        f"Requested language: {language}\nLocation: {loc}, India. {aqi_ctx}\n"
        "Examine this household room/kitchen photo for window/door gaps, exhaust placement, "
        "cooking smoke traps, or dust reservoirs. Return 3 practical Rs. 0 to Rs. 500 fixes JSON."
    )
    parsed, _ = await run_gemini_with_failover(
        lambda model_name, api_key: _call_gemini_vision_sync(
            prompt, image_bytes, mime_type, model_name, api_key
        ),
        lambda raw_text, model_name: _parse_room_audit_json(
            raw_text, model_name, safe_city, language, safe_area
        ),
    )
    return parsed or build_deterministic_room_audit(
        safe_city, language, area_name=safe_area, current_naqi=bounded_naqi
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
            "Today's Air:\n<1 sentence with PM2.5, Estimated India NAQI, and cleanest slot.>\n\n"
            "Do This:\n- <action 1>\n- <action 2>\n- <action 3>\n\n"
            "Avoid This:\n- <skip 1>\n- <skip 2>\n\n"
            f"JSON data:\n{serialize_evidence_for_llm(bundle)}"
        )
        if gemini_text := await _try_gemini_with_validation(prompt, bundle):
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
        f"Requested language: {language}\nUser question: {message}\n\n"
        "Instructions:\n"
        "- If greeting (hi/hello/namaste), reply warmly in 1-2 sentences with PM2.5 and NAQI.\n"
        "- Otherwise answer the user's EXACT question FIRST in 1-2 simple sentences.\n"
        "- Follow with short bullets under 'What to Do:' and 'What to Avoid:' using JSON numbers.\n"
        "- Use warm everyday language (no technical jargon).\n\n"
        f"JSON data:\n{serialize_evidence_for_llm(bundle)}"
    )
    if gemini_reply := await _try_gemini_with_validation(prompt, bundle):
        return gemini_reply, False, None, "gemini", True

    reply = build_deterministic_chat_reply(message, bundle, language)
    ok, _ = validate_narrative(reply, bundle)
    return reply, False, None, "deterministic_template", ok
