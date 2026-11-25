"""Grounded Gemini Flash explainer with scannable Do/Avoid templates and strict validation."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Callable
from typing import Any, Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types

from safety import EMERGENCY_DIRECTIVE, check_medical_emergency, validate_narrative
from schemas import EvidenceBundle, LanguageCode, RoomAuditResponse, RoomAuditTip

load_dotenv()

GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash")
PLACEHOLDER_KEY = "your_google_ai_studio_key_here"
MODEL_404_TTL_SECONDS = 600.0
KEY_429_COOLDOWN_SECONDS = 45.0

_CLIENT_CACHE: dict[str, genai.Client] = {}
_MODEL_UNAVAILABLE_UNTIL: dict[tuple[str, str], float] = {}
_KEY_COOLDOWN_UNTIL: dict[str, float] = {}


def reset_failover_cache() -> None:
    """Clear cached key cooldowns and 404 model skips (primarily for tests)."""
    _MODEL_UNAVAILABLE_UNTIL.clear()
    _KEY_COOLDOWN_UNTIL.clear()


def _get_client(api_key: str) -> genai.Client:
    """Reuse google-genai Client per API key for connection-pool keep-alive speed."""
    client = _CLIENT_CACHE.get(api_key)
    if client is None:
        client = genai.Client(api_key=api_key)
        _CLIENT_CACHE[api_key] = client
    return client


def _get_api_keys() -> list[str]:
    """Collect deduplicated Gemini API keys from GEMINI_API_KEYS, GEMINI_API_KEY, and GEMINI_API_KEY_BACKUP."""
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
    """Classify HTTP/timeout failures into 429_quota, 404_model, 503_unavailable, 504_timeout, or other."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    msg = str(exc).lower()
    if code == 429 or "429" in msg or "resource_exhausted" in msg or "quota" in msg:
        return "429_quota"
    if code == 404 or "404" in msg or "not_found" in msg:
        return "404_model"
    if code == 503 or "503" in msg or "unavailable" in msg:
        return "503_unavailable"
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or code == 504 or "504" in msg or "deadline" in msg or "timed out" in msg:
        return "504_timeout"
    return "other"

SYSTEM_PROMPT = """You are PRANA-AI, a warm, helpful neighbor and family air-quality guide in India.
You receive precomputed air and schedule facts in JSON.

STRICT RULES:
1. NEVER invent, recalculate, round, or alter any number from the provided JSON data.
2. Always keep PM2.5 concentration (ug/m3) and India NAQI separate.
3. Always keep personal exposure avoided ("Breathe Less") separate from travel CO2e saved ("Emit Less").
4. NEVER call any polluted outdoor window "safe"—use "lower-exposure window" or "cleaner window".
5. NEVER recommend indoor houseplants for PM2.5 removal.
6. Never use technical or developer jargon such as "EvidenceBundle", "mixing lid", "modeled proxy", or "microenvironment multiplier"—write in plain, everyday family words.
7. Respect fixed commitments (school, work, delivery shifts) with practical steps—never shame users or say "just stay home."
8. If `is_stale` or `is_fallback_replay` is true, explicitly state that live data is unavailable and this uses historical replay.
9. Match the user's requested language (`en`, `hinglish`, `hi`, `mr`, `kn`, `bn`, `ta`, or `te`) in a warm, friendly 8th-grade reading level.
"""


def _build_plan_actions(bundle: EvidenceBundle) -> tuple[str, list[str], list[str]]:
    """Derive plain-language status, Do This actions, and Avoid This actions from EvidenceBundle."""
    air = bundle.air_snapshot
    gw = air.golden_window
    sp = bundle.sanctuary_plan
    el = bundle.emit_less
    bl = bundle.breathe_less

    loc_label = f"{air.city_name} ({air.area_name})" if air.area_name else air.city_name
    prof = bundle.profile_summary

    if prof is not None:
        air_line = (
            f"[{prof.profile_label}] In {loc_label}, PM2.5 is {air.current_pm25} ug/m3 (India NAQI {air.current_naqi}, {air.current_category}). "
            f"{prof.tailored_hero_headline}"
        )
    elif gw.is_clean_air_day:
        air_line = (
            f"In {loc_label}, air is {air.current_category} today (PM2.5 {air.current_pm25} ug/m3, India NAQI {air.current_naqi}), "
            f"so normal outdoor routines are fine, with the cleanest slot at {gw.window_label}."
        )
    elif gw.has_meaningful_window:
        air_line = (
            f"In {loc_label}, air is {air.current_category} (PM2.5 {air.current_pm25} ug/m3, India NAQI {air.current_naqi}), "
            f"and the best lower-exposure window outside is {gw.window_label} ({gw.mean_pm25} ug/m3)."
        )
    else:
        air_line = (
            f"In {loc_label}, air stays {air.current_category} all day (PM2.5 {air.current_pm25} ug/m3, India NAQI {air.current_naqi}), "
            f"even during {gw.window_label} ({gw.mean_pm25} ug/m3)."
        )

    do_items: list[str] = []
    if prof and prof.profile_key == "delivery_riders":
        do_items.append(
            f"Wear a snug N95 mask on traffic shifts and wait 10–15m off arterial curbs to cut your daily lung dose from {bl.baseline_dose_ug} ug to {bl.optimized_dose_ug} ug."
        )
    elif prof and prof.profile_key == "seniors":
        do_items.append(
            f"Keep breathing calm (~{prof.peak_ventilation_m3_hr} m3/hr), walk during {gw.window_label}, and keep rescue medication accessible inside '{sp.sanctuary_room}'."
        )
    elif prof and prof.profile_key == "students_kids":
        do_items.append(
            f"Time sports and park play for {gw.window_label} ({gw.mean_pm25} ug/m3) to keep active kids' uptake low (saves {bl.dose_avoided_ug} ug PM2.5)."
        )
    elif gw.is_clean_air_day:
        do_items.append(f"Enjoy regular outdoor walks or play; best daytime window is {gw.window_label}.")
    elif gw.has_meaningful_window:
        do_items.append(
            f"Shift flexible walks or errands to {gw.window_label} ({gw.mean_pm25} ug/m3) to help avoid {bl.dose_avoided_ug} ug PM2.5."
        )
    else:
        do_items.append(
            f"Move strenuous exercise indoors into '{sp.sanctuary_room}' and use an N95 mask for fixed commutes."
        )

    if el.co2_saved_g > 0:
        do_items.append(
            f"Use {el.target_mode_label} for your {el.commute_km} km commute to save {el.co2_saved_g} g CO2e and {el.tailpipe_pm25_saved_mg} mg tailpipe PM2.5."
        )
    else:
        do_items.append("Wear a snug N95 mask during traffic shifts and wait a few steps back from the road curb.")

    do_items.append(
        f"Make '{sp.sanctuary_room}' your clean indoor room and close the kitchen door while running the exhaust fan 15 min after tadka."
    )

    avoid_items: list[str] = []
    if not gw.is_clean_air_day:
        avoid_items.append(
            f"Skip strenuous outdoor workouts during early morning peak ({gw.morning_peak_pm25} ug/m3)."
        )
    avoid_items.append(
        "Avoid dry sweeping (jhadu), burning agarbatti/coils, or sealing bedrooms completely airtight overnight—leave an inner door slightly ajar."
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

    stale_notes = {
        "en": f"Note: Live data is currently unavailable; showing historical replay ({bundle.provenance.source}).\n\n",
        "hinglish": "Note: Abhi live data available nahi hai; yeh historical replay dikhaya ja raha hai.\n\n",
        "hi": "नोट: अभी लाइव डेटा उपलब्ध नहीं है; यह ऐतिहासिक रीप्ले (historical replay) दिखाया जा रहा है।\n\n",
        "mr": "टीप: सध्या लाइव्ह डेटा उपलब्ध नाही; ऐतिहासिक रिप्ले (historical replay) दाखवला जात आहे.\n\n",
        "kn": "ಸೂಚನೆ: ಪ್ರಸ್ತುತ ಲೈವ್ ಡೇಟಾ ಲಭ್ಯವಿಲ್ಲ; ಹಿಂದಿನ ಮಾದರಿ ಡೇಟಾ (historical replay) ತೋರಿಸಲಾಗುತ್ತಿದೆ.\n\n",
        "bn": "নোট: বর্তমানে লাইভ ডেটা উপলব্ধ নয়; ঐতিহাসিক রিপ্লে (historical replay) দেখানো হচ্ছে।\n\n",
        "ta": "குறிப்பு: நேரலை தரவு தற்போது கிடைக்கவில்லை; வரலாற்று மாதிரி தரவு (historical replay) காட்டப்படுகிறது.\n\n",
        "te": "గమనిక: ప్రస్తుతం లైవ్ డేటా అందుబాటులో లేదు; చారిత్రక రీప్లే (historical replay) చూపబడుతోంది.\n\n",
    }
    stale_prefix = stale_notes.get(bundle.language, stale_notes["en"]) if is_replay else ""

    if bundle.language == "hi":
        return (
            f"{stale_prefix}"
            f"आज की हवा:\n"
            f"{loc_label} में आज PM2.5 {air.current_pm25} ug/m3 और India NAQI {air.current_naqi} ({air.current_category}) है; बाहर जाने का सबसे बेहतर समय {gw.window_label} ({gw.mean_pm25} ug/m3) है।\n\n"
            f"यह करें:\n"
            f"- टहलना या बाहरी काम {gw.window_label} में रखें (अनुमानित {bl.dose_avoided_ug} ug कम PM2.5) और सफर में N95 मास्क पहनें।\n"
            f"- घर में '{sp.sanctuary_room}' का उपयोग करें और तड़का लगाते समय रसोई का दरवाज़ा बंद रखकर exhaust 15 मिनट चलाएं।\n"
            f"- {el.target_mode_label} से {el.co2_saved_g} g CO2e और {el.tailpipe_pm25_saved_mg} mg टेलपाइप PM2.5 बचाएं।\n\n"
            f"इससे बचें:\n"
            f"- सुबह के भारी धुंध वाले समय ({gw.morning_peak_pm25} ug/m3) में तेज़ कसरत न करें।\n"
            f"- सूखी झाड़ू (jhadu), अगरबत्ती/कॉइल न जलाएं और रात में कमरा पूरी तरह बंद न करें (अंदरूनी दरवाज़ा थोड़ा खुला रखें)।"
        )

    if bundle.language == "mr":
        return (
            f"{stale_prefix}"
            f"आजची हवा:\n"
            f"{loc_label} मध्ये PM2.5 {air.current_pm25} ug/m3 आणि India NAQI {air.current_naqi} ({air.current_category}) आहे; बाहेर जाण्यासाठी चांगली वेळ {gw.window_label} ({gw.mean_pm25} ug/m3) आहे.\n\n"
            f"हे करा:\n"
            f"- फिरणे किंवा कामे {gw.window_label} दरम्यान करा ({bl.dose_avoided_ug} ug कमी PM2.5) आणि प्रवासात N95 मास्क वापरा.\n"
            f"- घरात '{sp.sanctuary_room}' खोली वापरा आणि फोडणी देताना स्वयंपाकघराचे दार बंद ठेवून exhaust 15 मिनिटे चालवा.\n"
            f"- {el.target_mode_label} वापरून {el.co2_saved_g} g CO2e आणि {el.tailpipe_pm25_saved_mg} mg टेलपाइप PM2.5 वाचवा.\n\n"
            f"हे टाळा:\n"
            f"- सकाळच्या जास्त धुराच्या वेळेत ({gw.morning_peak_pm25} ug/m3) कठीण व्यायाम करू नका.\n"
            f"- कोरडी झाडू, अगरबत्ती/कॉइल टाळा आणि रात्री खोली पूर्ण हवाबंद ठेवू नका (आतील दार किंचित उघडे ठेवा)."
        )

    if bundle.language == "kn":
        return (
            f"{stale_prefix}"
            f"ಇಂದಿನ ಗಾಳಿ:\n"
            f"{loc_label} ನಲ್ಲಿ PM2.5 {air.current_pm25} ug/m3 ಮತ್ತು India NAQI {air.current_naqi} ({air.current_category}) ಇದೆ; ಹೊರಗೆ ಹೋಗಲು ಉತ್ತಮ ಸಮಯ {gw.window_label} ({gw.mean_pm25} ug/m3).\n\n"
            f"ಇದನ್ನು ಮಾಡಿ:\n"
            f"- ನಡಿಗೆ ಅಥವಾ ಹೊರಗಿನ ಕೆಲಸವನ್ನು {gw.window_label} ಗೆ ಬದಲಾಯಿಸಿ ({bl.dose_avoided_ug} ug ಕಡಿಮೆ PM2.5) ಮತ್ತು ಪ್ರಯಾಣದಲ್ಲಿ N95 ಮಾಸ್ಕ್ ಧರಿಸಿ.\n"
            f"- ಮನೆಯಲ್ಲಿ '{sp.sanctuary_room}' ಬಳಸಿ ಹಾಗೂ ಒಗ್ಗರಣೆ ವೇಳೆ ಅಡುಗೆಮನೆ ಬಾಗಿಲು ಮುಚ್ಚಿ exhaust 15 ನಿಮಿಷ ಚಾಲನೆ ಮಾಡಿ.\n"
            f"- {el.target_mode_label} ಬಳಸಿ {el.co2_saved_g} g CO2e ಮತ್ತು {el.tailpipe_pm25_saved_mg} mg ಟೈಲ್‌ಪೈಪ್ PM2.5 ಉಳಿಸಿ.\n\n"
            f"ಇದನ್ನು ತಪ್ಪಿಸಿ:\n"
            f"- ಬೆಳಗಿನ ಹೆಚ್ಚಿನ ಮಾಲಿನ್ಯ ಸಮಯದಲ್ಲಿ ({gw.morning_peak_pm25} ug/m3) ಭಾರೀ ವ್ಯಾಯಾಮ ಬೇಡ.\n"
            f"- ಒಣ ಗುಡಿಸುವಿಕೆ, ಅಗರಬತ್ತಿ/ಕಾಯಿಲ್ ತಪ್ಪಿಸಿ ಹಾಗೂ ರಾತ್ರಿ ಕೋಣೆಯನ್ನು ಸಂಪೂರ್ಣವಾಗಿ ಮುಚ್ಚಬೇಡಿ."
        )

    if bundle.language == "bn":
        return (
            f"{stale_prefix}"
            f"আজকের বাতাস:\n"
            f"{loc_label}-এ PM2.5 {air.current_pm25} ug/m3 এবং India NAQI {air.current_naqi} ({air.current_category}); বাইরে যাওয়ার ভালো সময় {gw.window_label} ({gw.mean_pm25} ug/m3)।\n\n"
            f"যা করবেন:\n"
            f"- হাঁটা বা বাইরের কাজ {gw.window_label}-এ রাখুন ({bl.dose_avoided_ug} ug কম PM2.5) এবং রাস্তায় N95 মাস্ক পরুন।\n"
            f"- ঘরের '{sp.sanctuary_room}' ব্যবহার করুন ও রান্নায় ফোড়নের সময় দরজা বন্ধ রেখে exhaust 15 মিনিট চালান।\n"
            f"- {el.target_mode_label} ব্যবহারে {el.co2_saved_g} g CO2e এবং {el.tailpipe_pm25_saved_mg} mg টেলপাইপ PM2.5 বাঁচান।\n\n"
            f"যা এড়িয়ে চলবেন:\n"
            f"- সকালের বেশি ধোঁয়ার সময় ({gw.morning_peak_pm25} ug/m3) ভারী ব্যায়াম করবেন না।\n"
            f"- শুকনো ঝাড়ু, ধূপ/কয়েল এড়িয়ে চলুন এবং রাতে ঘরের সব দরজা পুরো বন্ধ রাখবেন না।"
        )

    if bundle.language == "ta":
        return (
            f"{stale_prefix}"
            f"இன்றைய காற்று:\n"
            f"{loc_label} பகுதியில் PM2.5 {air.current_pm25} ug/m3 மற்றும் India NAQI {air.current_naqi} ({air.current_category}); வெளியே செல்ல சிறந்த நேரம் {gw.window_label} ({gw.mean_pm25} ug/m3).\n\n"
            f"இதை செய்யுங்கள்:\n"
            f"- நடைப்பயிற்சி மற்றும் வெளி வேலைகளை {gw.window_label}-க்கு மாற்றுங்கள் ({bl.dose_avoided_ug} ug குறைந்த PM2.5) மற்றும் N95 முகக்கவசம் அணியுங்கள்.\n"
            f"- வீட்டில் '{sp.sanctuary_room}' அறையை பயன்படுத்துங்கள்; சமையல் தாளிப்பின் போது கதவை மூடி exhaust fan-ஐ 15 நிமிடம் இயக்குங்கள்.\n"
            f"- {el.target_mode_label} மூலம் {el.co2_saved_g} g CO2e மற்றும் {el.tailpipe_pm25_saved_mg} mg tailpipe PM2.5 சேமியுங்கள்.\n\n"
            f"இதை தவிர்க்கவும்:\n"
            f"- காலை அதிக மாசு நேரத்தில் ({gw.morning_peak_pm25} ug/m3) கடுமையான உடற்பயிற்சி வேண்டாம்.\n"
            f"- உலர்ந்த துடைப்பு, ஊதுபத்தி/கொசுவத்தி தவிர்த்து இரவில் உள் கதவை சிறிது திறந்து வையுங்கள்."
        )

    if bundle.language == "te":
        return (
            f"{stale_prefix}"
            f"నేటి గాలి:\n"
            f"{loc_label} లో PM2.5 {air.current_pm25} ug/m3 మరియు India NAQI {air.current_naqi} ({air.current_category}) ఉంది; బయటకు వెళ్లడానికి మంచి సమయం {gw.window_label} ({gw.mean_pm25} ug/m3).\n\n"
            f"ఇవి చేయండి:\n"
            f"- నడక మరియు బయటి పనులను {gw.window_label} లో చేయండి ({bl.dose_avoided_ug} ug తక్కువ PM2.5) మరియు ప్రయాణంలో N95 మాస్క్ వాడండి.\n"
            f"- ఇంట్లో '{sp.sanctuary_room}' ను వాడండి; పోపు వేసేటప్పుడు వంటగది తలుపు మూసి exhaust fan 15 నిమిషాలు నడపండి.\n"
            f"- {el.target_mode_label} ద్వారా {el.co2_saved_g} g CO2e మరియు {el.tailpipe_pm25_saved_mg} mg tailpipe PM2.5 ఆదా చేయండి.\n\n"
            f"ఇవి మానండి:\n"
            f"- ఉదయం ఎక్కువ కాలుష్య సమయంలో ({gw.morning_peak_pm25} ug/m3) కఠినమైన వ్యాయామం చేయకండి.\n"
            f"- పొడి చీపురు, అగరుబత్తి/కాయిల్స్ వాడకండి మరియు రాత్రి గదిని పూర్తిగా మూసివేయకండి."
        )

    if bundle.language == "hinglish":
        return (
            f"{stale_prefix}"
            f"Today's Air:\n"
            f"{loc_label} mein abhi PM2.5 {air.current_pm25} ug/m3 aur India NAQI {air.current_naqi} ({air.current_category}) hai; bahar jaane ka better slot {gw.window_label} ({gw.mean_pm25} ug/m3) hai.\n\n"
            f"Do This:\n"
            f"- Walk aur errands ko {gw.window_label} mein rakhein ({bl.dose_avoided_ug} ug kam PM2.5) aur commute par fitted N95 pehnein.\n"
            f"- Ghar mein '{sp.sanctuary_room}' use karein aur tadka lagate waqt kitchen door band karke exhaust 15 min chalayein.\n"
            f"- {el.target_mode_label} se {el.co2_saved_g} g CO2e aur {el.tailpipe_pm25_saved_mg} mg tailpipe PM2.5 save karein.\n\n"
            f"Avoid This:\n"
            f"- Subah peak smog ({gw.morning_peak_pm25} ug/m3) mein heavy jog ya outdoor cardio na karein.\n"
            f"- Dry jhadu, agarbatti/mosquito coils avoid karein aur raat ko bedroom bilkul airtight na rakhein."
        )

    air_line, do_items, avoid_items = _build_plan_actions(bundle)
    do_text = "\n".join(f"- {item}" for item in do_items)
    avoid_text = "\n".join(f"- {item}" for item in avoid_items)
    return (
        f"{stale_prefix}"
        f"Today's Air:\n{air_line}\n\n"
        f"Do This:\n{do_text}\n\n"
        f"Avoid This:\n{avoid_text}"
    )


def build_deterministic_chat_reply(message: str, bundle: EvidenceBundle, language: LanguageCode) -> str:
    """Answer user questions directly first, followed by short Do/Avoid bullets."""
    q = message.lower().strip()
    air = bundle.air_snapshot
    gw = air.golden_window
    sp = bundle.sanctuary_plan
    bl = bundle.breathe_less
    el = bundle.emit_less

    stale_prefix = (
        f"Note: Live data is unavailable; using historical replay ({bundle.provenance.source}).\n\n"
        if bundle.provenance.is_stale or bundle.provenance.is_fallback_replay
        else ""
    )

    clean_words = q.strip("!?., ")
    if clean_words in {"hi", "hii", "hiii", "hello", "hey", "heyy", "namaste", "namaskar", "hola", "yo"} or (
        any(clean_words.startswith(g + " ") for g in ("hi", "hii", "hello", "hey", "namaste"))
        and len(clean_words) <= 18
    ):
        return (
            f"{stale_prefix}Hi! I'm PRANA-AI. In {air.city_name} right now, PM2.5 is {air.current_pm25} ug/m3 "
            f"and India NAQI is {air.current_naqi} ({air.current_category}).\n\n"
            "Ask me anything about walk times, masks, windows, indoor exercise, or commute savings!"
        )

    if any(w in q for w in ("window", "open", "shut", "khidki", "ventilat", "kitchen", "tadka", "room", "sanctuary")):
        return (
            f"{stale_prefix}Keep '{sp.sanctuary_room}' as your cleanest indoor spot today. {sp.window_advice.guidance}\n\n"
            f"What to Do:\n"
            f"- Close the kitchen door before tadka and run the exhaust fan for 15 minutes afterward.\n"
            f"- {sp.co2_safety_note}\n\n"
            f"What to Avoid:\n"
            f"- Do not leave street-facing windows open during morning/evening rush hours."
        )

    if any(w in q for w in ("walk", "jog", "play", "outside", "bahar", "time", "when", "kab")):
        first_line = (
            f"Today in {air.city_name}, air is Good/Satisfactory ({gw.mean_pm25} ug/m3 at {gw.window_label}), so normal walks are fine."
            if gw.is_clean_air_day
            else f"Today's lower-exposure window in {air.city_name} is {gw.window_label} ({gw.mean_pm25} ug/m3 PM2.5, India NAQI {gw.mean_naqi}), down from {gw.morning_peak_pm25} ug/m3 in the morning."
        )
        return (
            f"{stale_prefix}{first_line}\n\n"
            f"What to Do:\n"
            f"- Plan walks or errands around {gw.window_label} on tree-lined lanes away from main roads.\n"
            f"- Carry a fitted N95 mask if air is Moderate or worse.\n\n"
            f"What to Avoid:\n"
            f"- Skip early-morning outdoor runs when pollution sits at {gw.morning_peak_pm25} ug/m3."
        )

    if any(w in q for w in ("mask", "n95", "ffp2", "cloth", "surgical")):
        mask_items = [r.name for r in bundle.routine_plan if r.recommended_mask == "n95"]
        target_note = f" (especially for {', '.join(mask_items[:2])})" if mask_items else ""
        return (
            f"{stale_prefix}At {air.current_pm25} ug/m3 PM2.5 (India NAQI {air.current_naqi}), a snug N95/FFP2 mask gives ~80% filtration{target_note}.\n\n"
            f"What to Do:\n"
            f"- Press the nose clip tight so unfiltered traffic air does not leak around the cheeks.\n"
            f"- Replace disposable N95 masks once straps loosen or breathing resistance rises.\n\n"
            f"What to Avoid:\n"
            f"- Avoid relying on cloth or loose surgical masks in heavy traffic—they only filter 20-35% of fine dust."
        )

    if any(w in q for w in ("indoor", "exercise", "yoga", "workout", "cardio", "active", "stretch")):
        return (
            f"{stale_prefix}Stick to gentle indoor movement inside '{sp.sanctuary_room}' today (PM2.5 is {air.current_pm25} ug/m3, NAQI {air.current_naqi}).\n\n"
            f"What to Do:\n"
            f"- Do 15-20 minutes of gentle yoga, stretching, or light hallway walking.\n"
            f"- Stay hydrated and rinse your nose/throat with plain water after commuting.\n\n"
            f"What to Avoid:\n"
            f"- Avoid heavy cardio or HIIT when NAQI crosses 200—fast breathing pulls 3-4x more dust deep into the lungs."
        )

    if any(w in q for w in ("child", "kid", "school", "senior", "dad", "mom", "elderly", "asthma", "copd")):
        return (
            f"{stale_prefix}With PM2.5 at {air.current_pm25} ug/m3 (NAQI {air.current_naqi}) in {air.city_name}, protect sensitive family members by keeping fixed trips brief and shifting play or walks to {gw.window_label}.\n\n"
            f"What to Do:\n"
            f"- Use a well-fitted child/adult N95 mask at bus stops and arrive just before pickup.\n"
            f"- Keep prescribed rescue inhalers handy inside '{sp.sanctuary_room}'.\n\n"
            f"What to Avoid:\n"
            f"- Avoid outdoor park play during the {gw.morning_peak_pm25} ug/m3 morning peak or near idling vehicles."
        )

    if any(w in q for w in ("co2", "car", "metro", "bus", "commute", "emit", "save", "cigarette", "dose", "math")):
        return (
            f"{stale_prefix}Today's shifts avoid {bl.dose_avoided_ug} ug of inhaled PM2.5 ({bl.reduction_pct}% less, ~{bl.cigarettes_avoided} cigarette equivalents) and save {el.co2_saved_g} g CO2e plus {el.tailpipe_pm25_saved_mg} mg tailpipe PM2.5 over {el.commute_km} km.\n\n"
            f"What to Do:\n"
            f"- Prefer {el.target_mode_label} or keep car AC on internal recirculate in traffic.\n"
            f"- Combine outdoor timing + mask choices for the biggest lung-dose drop.\n\n"
            f"What to Avoid:\n"
            f"- Avoid driving solo with windows down or fresh-air AC intake in stop-and-go congestion."
        )

    if any(w in q for w in ("trip", "travel", "journey", "outing", "vacation", "tour", "picnic", "highway", "drive")):
        outlook = air.daily_outlook or []
        best_day = min(outlook, key=lambda d: d.peak_naqi) if outlook else None
        outlook_note = (
            f" Looking ahead over the next 5 days, {best_day.day_label} looks cleanest (peak NAQI {best_day.peak_naqi}, best slot {best_day.best_window_label})."
            if best_day
            else ""
        )
        return (
            f"{stale_prefix}For planning a trip in or from {air.city_name}, today's outdoor air is {air.current_category} "
            f"(PM2.5 {air.current_pm25} ug/m3, India NAQI {air.current_naqi}) with the cleanest departure window at "
            f"{gw.window_label} ({gw.mean_pm25} ug/m3).{outlook_note}\n\n"
            f"What to Do:\n"
            f"- Time your outdoor sightseeing or travel departure for {gw.window_label}, and switch to {el.target_mode_label} where possible to save {el.co2_saved_g} g CO2e.\n"
            f"- Keep car/cab AC on Internal Recirculate in highway congestion and pack fitted N95 masks if any day crosses Moderate NAQI.\n\n"
            f"What to Avoid:\n"
            f"- Avoid early-morning (6–9 AM) outdoor stops when inversion smog sits near {gw.morning_peak_pm25} ug/m3, and don't roll down windows in stop-and-go traffic."
        )

    if any(w in q for w in ("plant", "houseplant", "snake plant", "paudhe")):
        return (
            f"{stale_prefix}{sp.no_houseplants_note}\n\n"
            f"What to Do:\n"
            f"- Focus on wet mopping (pochha), closing the kitchen door for tadka, and sealing leaky windows.\n\n"
            f"What to Avoid:\n"
            f"- Avoid relying on indoor potted plants to clean PM2.5."
        )

    return build_deterministic_plan_narrative(bundle.model_copy(update={"language": language}))


def _serialize_evidence_for_llm(bundle: EvidenceBundle) -> str:
    """Serialize clean air/schedule data without validator lists or noisy hourly arrays."""
    data = bundle.model_dump(exclude={"grounded_numbers": True, "air_snapshot": {"hourly"}})
    return json.dumps(data, ensure_ascii=False, indent=2)


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


VISION_SYSTEM_PROMPT = """You are PRANA-AI, an indoor air quality specialist helping Indian families lower indoor PM2.5 at low cost (Rs 0 to Rs 500).
Inspect the uploaded room or kitchen photo carefully for practical ventilation and dust issues:
- Visible window/door frame gaps, unsealed under-door gaps, or road-facing openings
- Kitchen exhaust fan / chimney placement, open kitchen partition near stove, or stagnant cooking smoke traps
- Soft dust traps (heavy curtains, rugs, open shelves near beds, fan blade/grill buildup)

Return STRICT JSON ONLY matching this exact schema (no markdown fences, no extra prose):
{
  "room_summary": "1-2 short, friendly sentences describing what you see in the photo and its main air/dust priority.",
  "tips": [
    {
      "title": "Short 3-6 word action title",
      "cost_inr": "Rs. 0",
      "action": "Specific step the family can do today",
      "why_it_helps": "Simple reason in everyday words"
    }
  ]
}
Provide EXACTLY 3 tips costing Rs. 0 to Rs. 500 in the requested language (`en`, `hinglish`, `hi`, `mr`, `kn`, `bn`, `ta`, or `te`).
NEVER recommend indoor houseplants for PM2.5 removal and NEVER invent sensor numbers."""


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
    response = client.models.generate_content(
        model=model_name,
        contents=[prompt, image_part],
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
    """Rotate across API keys on 429/quota and fail over models on 404/503/504/8s timeout."""
    keys = _get_api_keys()
    if not keys:
        return None, None

    now = time.monotonic()
    overall_deadline = now + 14.0
    for api_key in keys:
        if _KEY_COOLDOWN_UNTIL.get(api_key, 0.0) > time.monotonic():
            continue
        for model_name in GEMINI_MODELS:
            if _MODEL_UNAVAILABLE_UNTIL.get((api_key, model_name), 0.0) > time.monotonic():
                continue
            remaining = overall_deadline - time.monotonic()
            if remaining <= 0.5:
                return None, None
            call_timeout = min(8.0, remaining)
            try:
                raw_text = await asyncio.wait_for(
                    asyncio.to_thread(invoke_sync, model_name, api_key),
                    timeout=call_timeout,
                )
                parsed = postprocess(raw_text, model_name)
                if parsed is not None:
                    return parsed, model_name
            except Exception as exc:
                kind = _classify_gemini_error(exc)
                ts_now = time.monotonic()
                if kind == "429_quota":
                    _KEY_COOLDOWN_UNTIL[api_key] = ts_now + KEY_429_COOLDOWN_SECONDS
                    break
                if kind == "404_model":
                    _MODEL_UNAVAILABLE_UNTIL[(api_key, model_name)] = ts_now + MODEL_404_TTL_SECONDS
                continue
    return None, None


async def _try_gemini_with_validation(prompt: str, bundle: EvidenceBundle) -> str | None:
    """Run grounded text prompt with failover and numeric safety validation."""
    def _validate(raw_text: str, _model: str) -> str | None:
        text = raw_text
        if (bundle.provenance.is_stale or bundle.provenance.is_fallback_replay) and not any(
            tok in text.lower() for tok in ("replay", "stale", "offline", "unavailable", "historical")
        ):
            text = f"Historical replay note (live data unavailable): {text}"
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
    """Fast Rs 0-500 offline IAQ audit fallback tailored to Indian homes."""
    loc = f"{area_name}, {city}" if area_name and area_name.lower() != city.lower() else city
    aqi_note = f" (India AQI {current_naqi})" if current_naqi is not None else ""

    localized_summaries: dict[str, str] = {
        "hi": f"{loc}{aqi_note} में कम लागत के उपाय: दरवाज़े-खिड़कियों की दरारें सील करें, तड़का धुआं रोकें और गीला पोछा लगाएं।",
        "mr": f"{loc}{aqi_note} साठी कमी खर्चातील उपाय: दारं-खिडक्यांच्या फटी सील करा, फोडणीचा धूर थांबवा आणि ओला पुस घ्या.",
        "kn": f"{loc}{aqi_note} ಮನೆಗಾಗಿ ಕಡಿಮೆ ವೆಚ್ಚದ ಕ್ರಮಗಳು: ಬಾಗಿಲು-ಕಿಟಕಿ ಸಂದಿಗಳನ್ನು ಮುಚ್ಚಿ, ಒಗ್ಗರಣೆ ಹೊಗೆ ನಿಯಂತ್ರಿಸಿ ಮತ್ತು ಒದ್ದೆ ಒರೆಸಿ.",
        "bn": f"{loc}{aqi_note}-এর ঘরের জন্য কম খরচের উপায়: দরজা-জানালার ফাঁক বন্ধ করুন, রান্নার ধোঁয়া আটকান ও ভেজা মুছুন।",
        "ta": f"{loc}{aqi_note} வீட்டுக்கான குறைந்த செலவு தீர்வு: கதவு-ஜன்னல் இடைவெளிகளை அடைத்து சமையல் புகையை வெளியேற்றுங்கள்.",
        "te": f"{loc}{aqi_note} ఇంటికి తక్కువ ఖర్చు చిట్కాలు: తలుపు-కిటికీ సందులను సీల్ చేసి వంట పొగను బయటకు పంపండి.",
        "hinglish": f"{loc}{aqi_note} ke room ke liye smart Rs 0-500 sealing aur ventilation steps niche hain.",
    }
    summary = localized_summaries.get(
        language,
        f"Smart sealing, kitchen smoke isolation, and wet-cleaning audit for your room in {loc}{aqi_note}.",
    )

    tips = [
        RoomAuditTip(
            title="Seal Door & Window Gaps",
            cost_inr="Rs. 150",
            action="Roll a spare damp cotton towel under the main corridor/road-side door tonight, and apply self-adhesive EPDM foam tape (Rs. 120-200) along loose sliding window tracks.",
            why_it_helps="Stops smoky corridor/traffic air from creeping in through unsealed perimeter cracks.",
        ),
        RoomAuditTip(
            title="Isolate Kitchen Tadka Plumes",
            cost_inr="Rs. 0",
            action="Shut the door connecting to the kitchen before frying/tadka, open only the nearest kitchen window or run the exhaust fan for 15 minutes afterward.",
            why_it_helps="Prevents short cooking PM2.5 spikes (>300 ug/m3) from spreading into bedrooms.",
        ),
        RoomAuditTip(
            title="Switch Dust Traps to Wet Cleaning",
            cost_inr="Rs. 50",
            action="Wash heavy road-facing curtains monthly, wipe window sills and fan blades with a damp microfiber cloth, and strictly wet-mop (pochha) instead of dry broom sweeping.",
            why_it_helps="Keeps settled fine particulate dust from resuspending back into breathing height.",
        ),
    ]

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
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    room_summary = str(payload.get("room_summary") or "").strip()
    raw_tips = payload.get("tips")
    if not room_summary or not isinstance(raw_tips, list) or len(raw_tips) == 0:
        return None

    if "houseplant" in room_summary.lower() or "snake plant" in room_summary.lower():
        return None

    tips: list[RoomAuditTip] = []
    for item in raw_tips[:3]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        cost = str(item.get("cost_inr") or "Rs. 0").strip()
        action = str(item.get("action") or "").strip()
        why = str(item.get("why_it_helps") or "").strip()
        combined = f"{title} {action} {why}".lower()
        if any(p in combined for p in ("snake plant", "spider plant", "areca palm", "money plant", "houseplant")):
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
    aqi_context = f"Current local India NAQI: {current_naqi}." if current_naqi is not None else ""
    prompt = (
        f"Requested language: {language}\n"
        f"Location: {loc}, India. {aqi_context}\n"
        "Examine this household room/kitchen photo carefully for window/door gaps, ventilation/exhaust flow, "
        "cooking fume traps, or dust reservoirs. Give 3 practical, specific Rs. 0 to Rs. 500 fixes in strict JSON."
    )

    parsed, _ = await _run_gemini_with_failover(
        lambda model_name, api_key: _call_gemini_vision_sync(prompt, image_bytes, mime_type, model_name, api_key),
        lambda raw_text, model_name: _parse_room_audit_json(raw_text, model_name, city, language, area_name),
    )
    if parsed is not None:
        return parsed

    return build_deterministic_room_audit(city, language, area_name=area_name, current_naqi=current_naqi)


async def generate_plan_narrative(
    bundle: EvidenceBundle,
    skip_llm: bool = False,
) -> tuple[str, Literal["gemini", "deterministic_template", "emergency_triage"], bool]:
    """Generate a scannable, validated 3-block Daily Brief using Gemini or deterministic fallback."""
    if bundle.emergency_alert:
        return bundle.emergency_message or EMERGENCY_DIRECTIVE, "emergency_triage", True

    if not skip_llm:
        prompt = (
            f"Requested language: {bundle.language}\n"
            "Write a super simple, scannable Daily Brief for this family using ONLY exact numbers from the JSON data below.\n"
            "Avoid technical jargon and use this EXACT 3-block structure (translate section titles if requested language is not English):\n\n"
            "Today's Air:\n"
            "<1 simple sentence describing how the air feels today with PM2.5 and India NAQI, plus the best time outside.>\n\n"
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


async def generate_chat_reply(
    message: str,
    bundle: EvidenceBundle,
    language: LanguageCode,
) -> tuple[str, bool, str | None, Literal["gemini", "deterministic_template", "emergency_triage"], bool]:
    """Handle query-adaptive grounded Q&A with immediate medical triage interception."""
    is_emergency, directive = check_medical_emergency(message)
    if is_emergency:
        return directive or EMERGENCY_DIRECTIVE, True, directive, "emergency_triage", True

    prompt = (
        f"Requested language: {language}\n"
        f"User question: {message}\n\n"
        "Instructions:\n"
        "- If the user is just greeting you (e.g., hi, hello, namaste), greet them warmly in 1-2 short sentences with today's PM2.5 and India NAQI, and invite their question.\n"
        "- Otherwise, answer the user's EXACT question FIRST in 1-2 simple sentences. Do NOT repeat the entire daily summary if they asked about one specific topic.\n"
        "- Follow with 2-3 short, topic-relevant bullets under 'What to Do:' and 'What to Avoid:' using ONLY exact figures from the JSON data below.\n"
        "- Use warm everyday language (no technical jargon).\n\n"
        f"JSON data:\n{_serialize_evidence_for_llm(bundle)}"
    )
    gemini_reply = await _try_gemini_with_validation(prompt, bundle)
    if gemini_reply:
        return gemini_reply, False, None, "gemini", True

    reply = build_deterministic_chat_reply(message, bundle, language)
    ok, _ = validate_narrative(reply, bundle)
    return reply, False, None, "deterministic_template", ok
