"""Deterministic multilingual fallback builders and Vision JSON room-audit sanitizer."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from geo_india import CONSTANTS
from safety import check_safety_claims, contains_banned_houseplant
from schemas import EvidenceBundle, LanguageCode, RoomAuditResponse, RoomAuditTip

TopicPayload = tuple[str, list[str], list[str]]

LOCALIZED_ROOM_SUMMARIES: dict[str, str] = {
    "hi": (
        "{loc}{aqi_note} में कम लागत के उपाय: दरवाज़े-खिड़कियों की दरारें सील करें, "
        "तड़का धुआं रोकें और गीला पोछा लगाएं।"
    ),
    "mr": (
        "{loc}{aqi_note} साठी कमी खर्चातील उपाय: दारं-खिडक्यांच्या फटी सील करा, "
        "फोडणीचा धूर थांबवा आणि ओला पुस घ्या."
    ),
    "kn": (
        "{loc}{aqi_note} ಮನೆಗಾಗಿ ಕಡಿಮೆ ವೆಚ್ಚದ ಕ್ರಮಗಳು: ಬಾಗಿಲು-ಕಿಟಕಿ ಸಂದಿಗಳನ್ನು ಮುಚ್ಚಿ, "
        "ಒಗ್ಗರಣೆ ಹೊಗೆ ನಿಯಂತ್ರಿಸಿ ಮತ್ತು ಒದ್ದೆ ಒರೆಸಿ."
    ),
    "bn": "".join(
        [
            "{loc}{aqi_note}-এর ঘরের জন্য কম খরচের উপায়: ",
            "দরজা-জানালার ফাঁক বন্ধ করুন, রান্নার ধোঁয়া আটকান ও ভেজা মুছুন।",
        ]
    ),
    "ta": "".join(
        [
            "{loc}{aqi_note} வீட்டுக்கான குறைந்த செலவு தீர்வு: ",
            "கதவு-ஜன்னல் இடைவெளிகளை அடைத்து சமையல் புகையை வெளியேற்றுங்கள்.",
        ]
    ),
    "te": "".join(
        [
            "{loc}{aqi_note} ఇంటికి తక్కువ ఖర్చు చిట్కాలు: ",
            "తలుపు-కిటికీ సందులను సీల్ చేసి వంట పొగను బయటకు పంపండి.",
        ]
    ),
    "hinglish": "{loc}{aqi_note} ke room ke liye smart Rs 0-500 sealing aur ventilation steps.",
}


def format_do_avoid_response(
    air_line: str,
    do_items: list[str],
    avoid_items: list[str],
    headings: tuple[str, str, str] = ("Today's Air:", "Do This:", "Avoid This:"),
    stale_prefix: str = "",
) -> str:
    """Render a consistent 3-block scannable guidance message for plans and chat replies."""
    air_h, do_h, avoid_h = headings
    do_block = "\n".join(f"- {item}" for item in do_items)
    avoid_block = "\n".join(f"- {item}" for item in avoid_items)
    return f"{stale_prefix}{air_h}\n{air_line}\n\n{do_h}\n{do_block}\n\n{avoid_h}\n{avoid_block}"


def _english_air_line(bundle: EvidenceBundle, loc_label: str) -> str:
    """Format the English opening status line based on profile and Clean/Window status."""
    air = bundle.air_snapshot
    gw = air.golden_window
    if bundle.profile_summary is not None:
        prof = bundle.profile_summary
        return (
            f"[{prof.profile_label}] In {loc_label}, PM2.5 is {air.current_pm25} ug/m3 "
            f"(Estimated India NAQI {air.current_naqi}, {air.current_category}). "
            f"{prof.tailored_hero_headline}"
        )
    if gw.is_clean_air_day:
        return (
            f"In {loc_label}, air is {air.current_category} today (PM2.5 {air.current_pm25} ug/m3, "
            f"Estimated India NAQI {air.current_naqi}); cleanest slot is {gw.window_label}."
        )
    if gw.has_meaningful_window:
        return (
            f"In {loc_label}, air is {air.current_category} (PM2.5 {air.current_pm25} ug/m3, "
            f"Estimated India NAQI {air.current_naqi}); best lower-exposure window is "
            f"{gw.window_label} ({gw.mean_pm25} ug/m3)."
        )
    return (
        f"In {loc_label}, air stays {air.current_category} all day (PM2.5 {air.current_pm25} "
        f"ug/m3, Estimated India NAQI {air.current_naqi}), even at {gw.window_label} "
        f"({gw.mean_pm25} ug/m3)."
    )


def _english_primary_do_bullet(bundle: EvidenceBundle) -> str:
    """Build the profile-specific primary action bullet for English plans."""
    gw = bundle.air_snapshot.golden_window
    sp = bundle.sanctuary_plan
    bl = bundle.breathe_less
    prof = bundle.profile_summary

    profile_actions = {
        "delivery_riders": (
            f"Wear a snug N95 on traffic shifts and wait 10-15m off curbs to lower daily dose "
            f"from {bl.baseline_dose_ug} ug to {bl.optimized_dose_ug} ug."
        ),
        "seniors": (
            f"Keep breathing calm (~{prof.peak_ventilation_m3_hr} m3/hr), walk at "
            f"{gw.window_label}, and keep rescue medication inside '{sp.sanctuary_room}'."
        )
        if prof
        else "",
        "students_kids": (
            f"Shift outdoor play to {gw.window_label} ({gw.mean_pm25} ug/m3) to cut active "
            f"uptake (saves {bl.dose_avoided_ug} ug PM2.5)."
        ),
    }
    if prof and prof.profile_key in profile_actions:
        return profile_actions[prof.profile_key]
    if gw.is_clean_air_day:
        return f"Enjoy regular outdoor walks or play; cleanest daytime slot is {gw.window_label}."
    if gw.has_meaningful_window:
        return (
            f"Shift flexible walks to {gw.window_label} ({gw.mean_pm25} ug/m3) to help avoid "
            f"{bl.dose_avoided_ug} ug PM2.5."
        )
    return f"Move strenuous exercise indoors into '{sp.sanctuary_room}' and wear N95 outdoors."


def _build_english_plan_content(bundle: EvidenceBundle) -> TopicPayload:
    """Build English status line, Do items, and Avoid items directly from EvidenceBundle."""
    air = bundle.air_snapshot
    gw = air.golden_window
    el = bundle.emit_less
    loc_label = f"{air.city_name} ({air.area_name})" if air.area_name else air.city_name

    commute_bullet = (
        f"Use {el.target_mode_label} over {el.commute_km} km to save {el.co2_saved_g} g CO2e "
        f"and {el.tailpipe_pm25_saved_mg} mg tailpipe PM2.5."
        if el.co2_saved_g > 0
        else "Wear a fitted N95 mask on traffic shifts and step back from idling vehicles."
    )
    do_items = [
        _english_primary_do_bullet(bundle),
        commute_bullet,
        (
            f"Make '{bundle.sanctuary_plan.sanctuary_room}' your clean room and shut kitchen door "
            "while exhausting 15 min."
        ),
    ]
    avoid_items: list[str] = []
    if not gw.is_clean_air_day:
        avoid_items.append(
            f"Skip strenuous outdoor cardio at morning peak ({gw.morning_peak_pm25} ug/m3)."
        )
    avoid_items.append(
        "Avoid dry jhadu sweeping, agarbatti/coils, or airtight doors overnight (leave ajar)."
    )
    return _english_air_line(bundle, loc_label), do_items, avoid_items


def _localized_plan_ctx(bundle: EvidenceBundle) -> dict[str, Any]:
    """Assemble template interpolation values for non-English deterministic plan rendering."""
    air = bundle.air_snapshot
    gw = air.golden_window
    loc_label = f"{air.city_name} ({air.area_name})" if air.area_name else air.city_name
    return {
        "loc_label": loc_label,
        "current_pm25": air.current_pm25,
        "current_naqi": air.current_naqi,
        "current_category": air.current_category,
        "window_label": gw.window_label,
        "mean_pm25": gw.mean_pm25,
        "dose_avoided_ug": bundle.breathe_less.dose_avoided_ug,
        "sanctuary_room": bundle.sanctuary_plan.sanctuary_room,
        "target_mode_label": bundle.emit_less.target_mode_label,
        "co2_saved_g": bundle.emit_less.co2_saved_g,
        "tailpipe_pm25_saved_mg": bundle.emit_less.tailpipe_pm25_saved_mg,
        "morning_peak_pm25": gw.morning_peak_pm25,
    }


def _build_localized_plan(
    bundle: EvidenceBundle, tpl: dict[str, Any], flags: tuple[bool, bool]
) -> str:
    """Render localized non-English plan from constants.json templates."""
    is_replay, is_partial = flags
    prefix = (
        str(tpl["stale_prefix"])
        if is_replay
        else (str(tpl.get("partial_prefix", "")) if is_partial else "")
    )
    ctx = _localized_plan_ctx(bundle)
    gw = bundle.air_snapshot.golden_window
    has_win = gw.is_clean_air_day or gw.has_meaningful_window
    line_key = "air_line_window" if has_win else "air_line_flat"
    co2_key = "co2_bullet_nonzero" if bundle.emit_less.co2_saved_g > 0 else "co2_bullet_same_mode"
    do_items = [
        *[str(b).format(**ctx) for b in tpl["do_bullets_base"]],
        str(tpl[co2_key]).format(**ctx),
    ]
    headings = (str(tpl["air_heading"]), str(tpl["do_heading"]), str(tpl["avoid_heading"]))
    return format_do_avoid_response(
        air_line=str(tpl[line_key]).format(**ctx),
        do_items=do_items,
        avoid_items=[str(b).format(**ctx) for b in tpl["avoid_bullets"]],
        headings=headings,
        stale_prefix=prefix,
    )


def build_deterministic_plan_narrative(bundle: EvidenceBundle, emergency_fallback: str) -> str:
    """Render a scannable 3-block (Today's Air / Do This / Avoid This) multilingual plan."""
    if bundle.emergency_alert:
        return bundle.emergency_message or emergency_fallback

    is_replay = bundle.provenance.is_stale or bundle.provenance.is_fallback_replay
    is_partial = bundle.provenance.is_partial_fallback and not is_replay
    tpl = CONSTANTS.get("deterministic_plan_templates", {}).get(bundle.language)
    if tpl:
        return _build_localized_plan(bundle, tpl, (is_replay, is_partial))

    prefix_en = (
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
    return format_do_avoid_response(air_line, do_items, avoid_items, stale_prefix=prefix_en)


def _topic_window(bundle: EvidenceBundle) -> TopicPayload:
    sp = bundle.sanctuary_plan
    return (
        f"Keep '{sp.sanctuary_room}' as cleanest room today. {sp.window_advice.guidance}",
        [
            "Close the kitchen door before tadka and run exhaust fan for 15 minutes afterward.",
            sp.co2_safety_note,
        ],
        ["Do not leave street-facing windows open during morning/evening rush hours."],
    )


def _topic_walk(bundle: EvidenceBundle) -> TopicPayload:
    air = bundle.air_snapshot
    gw = air.golden_window
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


def _topic_mask(bundle: EvidenceBundle) -> TopicPayload:
    air = bundle.air_snapshot
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


def _topic_indoor(bundle: EvidenceBundle) -> TopicPayload:
    air = bundle.air_snapshot
    sp = bundle.sanctuary_plan
    return (
        f"Stick to gentle indoor movement inside '{sp.sanctuary_room}' today "
        f"(PM2.5 {air.current_pm25} ug/m3, Estimated NAQI {air.current_naqi}).",
        [
            "Do 15-20 minutes of gentle yoga, stretching, or light hallway walking.",
            "Stay hydrated and rinse your nose/throat with plain water after commuting.",
        ],
        [
            "Avoid heavy HIIT/cardio when outdoor air hits Poor or Very Poor—"
            "fast breathing pulls deeper dust."
        ],
    )


def _topic_sensitive_member(bundle: EvidenceBundle) -> TopicPayload:
    air = bundle.air_snapshot
    gw = air.golden_window
    return (
        f"With PM2.5 at {air.current_pm25} ug/m3 (NAQI {air.current_naqi}) in {air.city_name}, "
        f"keep fixed trips brief and shift walks/play to {gw.window_label}.",
        [
            "Use a well-fitted N95 mask at bus stops and arrive just before pickup.",
            (
                "Keep prescribed rescue inhalers handy inside "
                f"'{bundle.sanctuary_plan.sanctuary_room}'."
            ),
        ],
        [f"Avoid play at morning peak ({gw.morning_peak_pm25} ug/m3) or idling vehicles."],
    )


def _topic_emissions(bundle: EvidenceBundle) -> TopicPayload:
    bl, el = bundle.breathe_less, bundle.emit_less
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


def _topic_trip(bundle: EvidenceBundle) -> TopicPayload:
    air, el = bundle.air_snapshot, bundle.emit_less
    gw = air.golden_window
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


def _topic_plants(bundle: EvidenceBundle) -> TopicPayload:
    return (
        bundle.sanctuary_plan.no_houseplants_note,
        ["Focus on wet mopping (pochha), closing kitchen door for tadka, and sealing leaks."],
        ["Avoid relying on indoor potted plants to clean PM2.5."],
    )


TopicRule = tuple[tuple[str, ...], Callable[[EvidenceBundle], TopicPayload]]

CHAT_TOPIC_RULES: tuple[TopicRule, ...] = (
    (
        ("window", "open", "shut", "khidki", "ventilat", "kitchen", "tadka", "room", "sanctuary"),
        _topic_window,
    ),
    (("walk", "jog", "play", "outside", "bahar", "time", "when", "kab"), _topic_walk),
    (("mask", "n95", "ffp2", "cloth", "surgical"), _topic_mask),
    (("indoor", "exercise", "yoga", "workout", "cardio", "active", "stretch"), _topic_indoor),
    (
        ("child", "kid", "school", "senior", "dad", "mom", "elderly", "asthma", "copd"),
        _topic_sensitive_member,
    ),
    (
        ("co2", "car", "metro", "bus", "commute", "emit", "save", "cigarette", "dose", "math"),
        _topic_emissions,
    ),
    (
        ("trip", "travel", "journey", "outing", "vacation", "tour", "picnic", "highway", "drive"),
        _topic_trip,
    ),
    (("plant", "houseplant", "snake plant", "paudhe"), _topic_plants),
)


def _kw_pattern(tok: str) -> str:
    """Match keyword at word start (requiring word end + optional plural on short tokens)."""
    escaped = re.escape(tok)
    if len(tok) > 5 or " " in tok:
        return rf"\b{escaped}"
    return rf"\b{escaped}(?:s|es)?\b"


def _chat_topic_payload(q: str, bundle: EvidenceBundle) -> TopicPayload | None:
    """Resolve deterministic chat topic into (intro, do_items, avoid_items)."""
    for keywords, builder in CHAT_TOPIC_RULES:
        if any(re.search(_kw_pattern(tok), q) for tok in keywords):
            return builder(bundle)
    return None


def _is_short_greeting(q: str) -> bool:
    """Return True when the user sent a brief greeting without specific questions."""
    clean = q.strip("!?., ")
    greetings = {"hi", "hii", "hiii", "hello", "hey", "heyy", "namaste", "namaskar", "hola", "yo"}
    return clean in greetings or (
        any(clean.startswith(g + " ") for g in ("hi", "hii", "hello", "hey", "namaste"))
        and len(clean) <= 18
    )


def _chat_disclosure_prefix(bundle: EvidenceBundle) -> str:
    """Return mandatory stale/replay or partial-fallback prefix for deterministic chat replies."""
    prov = bundle.provenance
    if prov.is_stale or prov.is_fallback_replay:
        return f"Note: Live data unavailable; using historical replay ({prov.source}).\n\n"
    if prov.is_partial_fallback:
        return "Note: Partial forecast fallback used for some missing slots.\n\n"
    return ""


def build_deterministic_chat_reply(
    message: str,
    bundle: EvidenceBundle,
    language: LanguageCode,
    emergency_fallback: str,
) -> str:
    """Answer user questions directly first, followed by unified What to Do / Avoid bullets."""
    q = message.lower().strip()
    air = bundle.air_snapshot
    disclosure_prefix = _chat_disclosure_prefix(bundle)
    topic = _chat_topic_payload(q, bundle)
    if topic is None and _is_short_greeting(q):
        return (
            f"{disclosure_prefix}Hi! I'm PRANA-AI. In {air.city_name} right now, PM2.5 is "
            f"{air.current_pm25} ug/m3 and Estimated India NAQI is {air.current_naqi} "
            f"({air.current_category}).\n\n"
            "Ask me about walk times, masks, windows, indoor exercise, trips, or commute savings!"
        )
    if topic is not None:
        return format_do_avoid_response(
            topic[0],
            topic[1],
            topic[2],
            headings=("Direct Answer:", "What to Do:", "What to Avoid:"),
            stale_prefix=disclosure_prefix,
        )
    return build_deterministic_plan_narrative(
        bundle.model_copy(update={"language": language}),
        emergency_fallback=emergency_fallback,
    )


def build_deterministic_room_audit(
    city: str,
    language: LanguageCode,
    area_name: str | None = None,
    current_naqi: int | None = None,
) -> RoomAuditResponse:
    """Fast Rs 0-500 deterministic IAQ room audit fallback localized to 8 languages."""
    loc = f"{area_name}, {city}" if area_name and area_name.lower() != city.lower() else city
    aqi_note = f" (Estimated India AQI {current_naqi})" if current_naqi is not None else ""
    summary_tpl = LOCALIZED_ROOM_SUMMARIES.get(
        language,
        "Low-cost sealing, cooking-smoke isolation, and wet-cleaning audit for {loc}{aqi_note}.",
    )
    tips_table = CONSTANTS.get("room_audit_fallback_tips", {})
    raw_tips = tips_table.get(language) or tips_table.get("en", [])
    return RoomAuditResponse(
        city=city,
        area_name=area_name,
        language=language,
        room_summary=summary_tpl.format(loc=loc, aqi_note=aqi_note),
        tips=[RoomAuditTip(**item) for item in raw_tips[:3]],
        source="deterministic_template",
        model_used=None,
    )


def _parse_json_payload(raw_text: str) -> dict[str, Any] | None:
    """Strip optional markdown fences and parse a JSON object dictionary."""
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    try:
        payload = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _cost_within_budget(cost: str) -> bool:
    """Return True when every numeric cost in `cost` sits cleanly within 0..500 INR."""
    normalized = cost.replace(",", "")
    if re.search(r"(?:^|\s)-\s*\d+", normalized):
        return False
    amounts = [int(n) for n in re.findall(r"\d+", normalized)]
    return bool(amounts) and max(amounts) <= 500


def _sanitize_audit_tip(item: Any) -> RoomAuditTip | None:
    """Validate budget bounds (Rs 0-500) and reject prohibited claims/plants via shared rules."""
    if not isinstance(item, dict):
        return None
    title = str(item.get("title") or "").strip()
    cost = str(item.get("cost_inr") or "").strip()
    action = str(item.get("action") or "").strip()
    why = str(item.get("why_it_helps") or "").strip()
    if not (title and action and why and _cost_within_budget(cost)):
        return None
    combined = f"{title}. {action}. {why}"
    if contains_banned_houseplant(combined) or check_safety_claims(combined):
        return None
    try:
        return RoomAuditTip(title=title, cost_inr=cost, action=action, why_it_helps=why)
    except ValidationError:
        return None


def parse_room_audit_json(
    raw_text: str,
    model_name: str,
    city: str,
    language: LanguageCode,
    area_name: str | None,
) -> RoomAuditResponse | None:
    """Safely parse and sanitize Gemini Vision JSON output into RoomAuditResponse."""
    payload = _parse_json_payload(raw_text)
    if payload is None:
        return None
    room_summary = str(payload.get("room_summary") or "").strip()
    raw_tips = payload.get("tips")
    if not room_summary or not isinstance(raw_tips, list) or not raw_tips:
        return None
    if contains_banned_houseplant(room_summary) or check_safety_claims(room_summary):
        return None

    tips = [tip for item in raw_tips[:3] if (tip := _sanitize_audit_tip(item)) is not None]
    if len(tips) < 3:
        fallback = build_deterministic_room_audit(city, language, area_name=area_name)
        tips.extend(fallback.tips[: 3 - len(tips)])

    try:
        return RoomAuditResponse(
            city=city,
            area_name=area_name,
            language=language,
            room_summary=room_summary,
            tips=tips[:3],
            source="gemini",
            model_used=model_name,
        )
    except ValidationError:
        return None
