"""Hard medical emergency triage, bundle HMAC integrity, and category-bound validator."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
import unicodedata

from geo_india import CONSTANTS
from schemas import EvidenceBundle

logger = logging.getLogger("prana_ai.safety")

PLACEHOLDER_KEY = "your_google_ai_studio_key_here"
_EPHEMERAL_SECRET = secrets.token_bytes(32)
CIG_EQUIV_UG = float(CONSTANTS["berkeley_earth_cig_ug"])
BUNDLE_TTL_SECONDS = 6 * 3600

BANNED_HOUSEPLANT_NAMES = (
    "snake plant",
    "spider plant",
    "areca palm",
    "money plant",
    "houseplant",
)

EMERGENCY_KEYWORDS = (
    "wheezing",
    "severe wheeze",
    "can't breathe",
    "cant breathe",
    "cannot breathe",
    "difficulty breathing",
    "struggling to breathe",
    "breathless",
    "shortness of breath",
    "gasping",
    "chest pain",
    "chest tightness",
    "tight chest",
    "blue lips",
    "bluish lips",
    "asthma attack",
    "inhaler not working",
    "choking",
    "saans nahi",
    "sans nahi",
    "saans phool",
    "सांस नहीं",
    "साँस नहीं",
    "सांस फूल",
    "सीने में दर्द",
    "दम घुट",
    "मला श्वास घेता येत नाही",
    "श्वास घ्यायला त्रास",
    "छातीत दुखत",
    "ಉಸಿರಾಡಲು ಆಗುತ್ತಿಲ್ಲ",
    "ಉಸಿರಾಟದ ತೊಂದರೆ",
    "ಎದೆ ನೋವು",
    "શ્વાસ નથી",
    "শ্বাসকষ্ট",
    "மூச்சுத் திணறல்",
    "மூச்சு விட முடியவில்லை",
    "శ్వాస అందడం లేదు",
)

EMERGENCY_REGEX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:trouble|hard|difficult(?:y)?|struggling|unable|cannot|can\s*not|can't|cant)"
        r"\s+(?:to\s+)?breath(?:e|ing)\b"
    ),
    re.compile(r"\bcan'?t\s+catch\s+(?:my|their|his|her)?\s*breath\b"),
    re.compile(r"\b(?:short(?:ness)?\s+of\s+breath|breathless|gasping|choking|suffocating)\b"),
    re.compile(
        r"\b(?:heart\s+attack|chest\s+(?:pain|tight(?:ness)?)|"
        r"pain\s+in\s+(?:my|the)?\s*chest|chest\s+feels?\s+tight)\b"
    ),
    re.compile(
        r"\b(?:lips?\s+(?:are\s+|turning\s+)?blu(?:e|ish)|blu(?:e|ish)\s+lips?|"
        r"inhaler\s+(?:is\s+)?not\s+working|asthma\s+attack)\b"
    ),
)

EMERGENCY_DIRECTIVE = (
    "MEDICAL EMERGENCY ALERT: Symptoms like wheezing, severe breathlessness, chest pain, "
    "blue lips, or an asthma attack not responding to an inhaler require immediate emergency care. "
    "Call emergency services (108 / 112 in India) or go to the nearest hospital ER right now. "
    "Use prescribed rescue medication immediately if instructed by your doctor, move into clean "
    "indoor air, and do not rely on a daily planner for acute respiratory distress."
)

METRIC_NUMBER_PATTERN = re.compile(
    r"(?P<num>(?<!\d)-?\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(?P<unit>ug/m3|µg/m3|ug|µg|naqi|aqi|g\s*co2e?|kg\s*co2e?|mg\s*pm2\.5|cigarettes?|cigs?|%)",
    re.IGNORECASE,
)

PREFIX_AQI_PATTERN = re.compile(
    r"\b(?:india\s+)?(?:cpcb\s+)?(?:naqi|aqi)\s+"
    r"(?:(?:will|may|might|could)\s+)?"
    r"(?:(?:is|are|of|at|reaches?|hits?|around|near|about|level|levels?|peaks?|"
    r"drops?\s+to|:|=)\s+)*"
    r"(?P<num>\d+(?:,\d{3})*(?:\.\d+)?)\b",
    re.IGNORECASE,
)

PREFIX_PM25_PATTERN = re.compile(
    r"\bpm\s*2\.5\s+"
    r"(?:(?:will|may|might|could)\s+)?"
    r"(?:(?:is|are|of|at|reaches?|hits?|around|near|about|level|levels?|peaks?|"
    r"drops?\s+to|:|=)\s+)+"
    r"(?P<num>-?\d+(?:,\d{3})*(?:\.\d+)?)\b",
    re.IGNORECASE,
)

PCT_RANGE_PATTERN = re.compile(r"\b(?P<a>\d+(?:\.\d+)?)\s*[-–]\s*(?P<b>\d+(?:\.\d+)?)\s*%")

_EXEMPT_CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:pm\s*2\.5|pm\s*10|no\s*2|co\s*2e?|n\s*95|ffp\s*2|ug/m3|µg/m3|m3/hr)\b",
        re.I,
    ),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}:\d{2}\b"),
    re.compile(r"\b\d{1,2}(?:\s*[-–]\s*\d{1,2})?\s*(?:am|pm)\b", re.I),
    re.compile(r"\b(?:108|112)\b"),
    re.compile(r"(?:rs\.?|inr|₹)\s*[\d,]+(?:\s*[-–]\s*[\d,]+)?", re.I),
    re.compile(r"\b\d+\s*(?:-|\s)?(?:year|yr)s?(?:-old)?\b", re.I),
    re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.I),
    re.compile(r"(?m)^\s*\d+[.)]\s+"),
    re.compile(
        r"\b\d+(?:\s*[-–]\s*\d+)?\s*"
        r"(?:mins?|minutes?|hrs?|hours?|days?|m(?=\s+off\b)|"
        r"मिनट|मिनिटे|ನಿಮಿಷ|মিনিট|நிமிடம்|నిమిషాలు)(?:\b|(?=\s))",
        re.I,
    ),
)

_SUPERSCRIPT_AND_UNIT_MAP = str.maketrans(
    {
        "\u00b2": "2",
        "\u00b3": "3",
        "\u03bc": "\u00b5",
    }
)


def _normalize_for_metric_scan(text: str) -> str:
    """Normalize Unicode numerals, superscripts, and Indic unit labels for numeric grounding."""
    mapped = unicodedata.normalize("NFC", text).translate(_SUPERSCRIPT_AND_UNIT_MAP)
    chars = [
        str(unicodedata.digit(ch)) if ch.isdecimal() and not ch.isascii() else ch for ch in mapped
    ]
    normalized = "".join(chars)
    normalized = re.sub(r"प्रतिशत", " % ", normalized)
    normalized = re.sub(r"माइक्रोग्राम", " ug ", normalized)
    return re.sub(r"एनएक्यूआई|एक्यूआई", " NAQI ", normalized)


SAFE_WINDOW_CLAIM_PATTERN = re.compile(
    r"(?:"
    r"\b(?:safe\s+window|air\s+is\s+(?:completely\s+|perfectly\s+)?safe|"
    r"(?:completely|perfectly)\s+safe(?:\s+to\s+\w+)?|"
    r"safe\s+time\s+to\s+(?:walk|jog|run|exercise|play|go\s+out(?:side|doors)?)|"
    r"safe\s+to\s+(?:breathe\s+outdoors|go\s+out(?:side|doors)?))\b"
    r"|पूरी\s+तरह\s+सुरक्षित|सुरक्षित\s+समय|बाहर\s+जाना\s+सुरक्षित|"
    r"पूर्णपणे\s+सुरक्षित|ಸಂಪೂರ್ಣ\s+ಸುರಕ್ಷಿತ|ಸುರಕ್ಷಿತ\s+ಸಮಯ|"
    r"সম্পূর্ণ\s+নিরাপদ|பாதுகாப்பானது|పూర్తిగా\s+సురక్షితం"
    r")",
    re.IGNORECASE,
)

HOUSEPLANT_CLAIM_PATTERN = re.compile(
    r"(?:"
    r"\b(?:houseplants?|snake\s+plant|spider\s+plant|areca\s+palm|money\s+plant|"
    r"indoor\s+plants?|paudhe)\b"
    r"|मनी\s*प्लांट|स्नेक\s*प्लांट|स्पाइडर\s*प्लांट|एरेका\s*पाम|"
    r"घरेलू\s+पौधे|मनी\s*प्लँट|মনি\s*প্ল্যান্ট|মணி\s*ப்ளாண்ட்|"
    r"மணி\s*பிளாண்ட்|ஸ்நேக்\s*பிளாண்ட்|మనీ\s*ప్లాంట్|ಮನಿ\s*ಪ್ಲಾಂಟ್"
    r")",
    re.IGNORECASE,
)

MEDICAL_ADVICE_CLAIM_PATTERN = re.compile(
    r"\b(?:(?:increase|double|stop|skip|take)\s+(?:\d+\s+)?"
    r"(?:puffs?|inhaler|steroid|tablets?|dosage)"
    r"|you\s+(?:have|don'?t\s+have)\s+(?:asthma|pneumonia|bronchitis|copd))\b",
    re.IGNORECASE,
)

STALE_DISCLOSURE_TOKENS = (
    "replay",
    "stale",
    "offline",
    "unavailable",
    "historical",
    "पुरान",
    "उपलब्ध नहीं",
    "ऐतिहासिक",
    "रीप्ले",
    "रिप्ले",
    "उपलब्ध नाही",
    "ಲಭ್ಯವಿಲ್ಲ",
    "ಹಿಂದಿನ",
    "উপলব্ধ নয়",
    "উপলব্ধ নয়",
    "ঐতিহাসিক",
    "கிடைக்கவில்லை",
    "வரலாற்று",
    "అందుబాటులో లేదు",
    "చారిత్రక",
)

PARTIAL_DISCLOSURE_TOKENS = (
    "partial",
    "fallback",
    "backup",
    "missing",
    "बैकअप",
    "आंशिक",
    "बॅकअप",
    "ಬ್ಯಾಕಪ್",
    "ব্যাকআপ",
    "மாற்று",
    "బ్యాకప్",
) + STALE_DISCLOSURE_TOKENS

_DOCUMENTED_PCT_ALLOWLIST: list[float] = sorted(
    {
        float(CONSTANTS["engine_params"]["golden_window_min_reduction_pct"]),
        *[
            round(float(v) * 100.0, 1)
            for v in CONSTANTS["mask_filtration_efficiency"].values()
            if v > 0
        ],
        44.0,
        65.0,
        70.0,
        95.0,
    }
)


def _get_bundle_hmac_key() -> bytes:
    """Resolve dedicated >=32-byte HMAC key from PRANA_BUNDLE_SECRET or ephemeral fallback."""
    explicit = os.getenv("PRANA_BUNDLE_SECRET", "").strip()
    is_deployed = bool(os.getenv("VERCEL_ENV", "").strip() or os.getenv("RENDER", "").strip())
    if explicit:
        raw = explicit.encode("utf-8")
        if len(raw) < 32:
            if is_deployed:
                raise RuntimeError(
                    "PRANA_BUNDLE_SECRET must be at least 32 bytes in deployed environments."
                )
            logger.warning("PRANA_BUNDLE_SECRET is shorter than 32 bytes; rotate to >= 32 bytes.")
        return raw
    if is_deployed:
        raise RuntimeError("PRANA_BUNDLE_SECRET must be set in deployed environments.")
    logger.warning("PRANA_BUNDLE_SECRET unset; using per-process ephemeral HMAC key.")
    return _EPHEMERAL_SECRET


def ensure_bundle_hmac_secret() -> bytes:
    """Validate and return the dedicated HMAC secret key at startup or signing time."""
    return _get_bundle_hmac_key()


def _canonical_bundle_bytes(bundle: EvidenceBundle) -> bytes:
    """Serialize an EvidenceBundle canonically for deterministic HMAC verification."""
    payload = json.dumps(
        bundle.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return payload.encode("utf-8")


def sign_evidence_bundle(bundle: EvidenceBundle) -> str:
    """Create an HMAC-SHA256 signature authenticating server-computed EvidenceBundle fields."""
    return hmac.new(
        _get_bundle_hmac_key(), _canonical_bundle_bytes(bundle), hashlib.sha256
    ).hexdigest()


def verify_evidence_bundle(
    bundle: EvidenceBundle,
    signature: str | None,
    max_age_seconds: int = BUNDLE_TTL_SECONDS,
) -> bool:
    """Verify EvidenceBundle HMAC-SHA256 signature and issued_at freshness window."""
    if not signature or not isinstance(signature, str):
        return False
    age = int(time.time()) - int(getattr(bundle, "issued_at", 0))
    if age > max_age_seconds or age < -300:
        return False
    expected = sign_evidence_bundle(bundle)
    return hmac.compare_digest(expected, signature.strip().lower())


def _normalize_triage_text(text: str) -> str:
    """Normalize Unicode NFC, zero-width characters, smart quotes, and spaces for triage."""
    cleaned = unicodedata.normalize("NFC", text)
    cleaned = re.sub(r"[\u200b\u2060\ufeff\u00ad]", "", cleaned)
    cleaned = cleaned.replace("\u2019", "'").replace("\u02bc", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def check_medical_emergency(text: str | None) -> tuple[bool, str | None]:
    """Scan user input for acute respiratory or cardiac distress phrases across languages."""
    if not text:
        return False, None
    lowered = _normalize_triage_text(text)
    if any(kw in lowered for kw in EMERGENCY_KEYWORDS) or any(
        pat.search(lowered) for pat in EMERGENCY_REGEX_PATTERNS
    ):
        return True, EMERGENCY_DIRECTIVE
    return False, None


def _is_number_grounded(val: float, grounded_numbers: list[float]) -> bool:
    """Return True when val matches any number in grounded_numbers up to exact rounding."""
    val_is_int = val == float(int(round(val)))
    for ref in grounded_numbers:
        if abs(val - ref) <= 0.06:
            return True
        if val_is_int and int(round(ref)) == int(round(val)):
            return True
    return False


def _allowed_pool_for_unit(unit: str, bundle: EvidenceBundle) -> list[float]:
    """Map a matched unit suffix to the category-specific grounded allowlist."""
    u = re.sub(r"\s+", " ", unit.lower().strip())
    gm = bundle.grounded_metrics
    has_typed = any((gm.pm25, gm.naqi, gm.dose_ug, gm.co2_g, gm.co2_kg, gm.tailpipe_mg, gm.pct))
    if not has_typed:
        return bundle.grounded_numbers

    dose_pool = gm.dose_ug + [float(x) for x in bundle.grounded_numbers if x == CIG_EQUIV_UG]
    unit_map: dict[str, list[float]] = {
        "ug/m3": gm.pm25,
        "µg/m3": gm.pm25,
        "ug": dose_pool,
        "µg": dose_pool,
        "naqi": gm.naqi,
        "aqi": gm.naqi,
        "%": gm.pct + _DOCUMENTED_PCT_ALLOWLIST,
    }
    pool = unit_map.get(u)
    if pool is None:
        prefix_map = (
            ("g ", gm.co2_g),
            ("kg ", gm.co2_kg),
            ("mg ", gm.tailpipe_mg),
            ("cig", gm.cigarettes),
        )
        pool = next((vals for prefix, vals in prefix_map if u.startswith(prefix)), None)
    return pool if pool is not None else bundle.grounded_numbers


def contains_banned_houseplant(text: str) -> bool:
    """Return True when text promotes or names banned air-purifying houseplants."""
    norm = _normalize_for_metric_scan(text).lower()
    return bool(HOUSEPLANT_CLAIM_PATTERN.search(norm)) or any(
        plant in norm for plant in BANNED_HOUSEPLANT_NAMES
    )


_SUBCLAUSE_SPLIT_RE = re.compile(
    r"[.!?;,\n।]+|\b(?:and|but|however|while|because|since|means)\b", re.I
)
_DIRECT_NEG_PREFIX_RE = re.compile(
    r"(?:\b(?:not|never|avoid|cannot|can't|won't|isn't|aren't|do\s+not|don't|stop|skip)\b"
    r"(?:\s+\w+){0,3})\s*$",
    re.I,
)
_NO_TARGET_RE = re.compile(
    r"\bno\s+(?:safe|completely|perfectly|clean|houseplants?|indoor\s+plants?|"
    r"snake|spider|areca|money|paudhe)\b",
    re.I,
)
_INDIC_NEG_RE = re.compile(
    r"(?:(?<!\S)न(?!\S)|नहीं|नाही|नको|मत|बचें|टाळा|ಬೇಡ|ಅಲ್ಲ|வேண்டாம்|அல்ல|"
    r"వద్దు|కాదు|নয়|নয়|এড়িয়ে)"
)
_POST_NEG_SUFFIX_RE = re.compile(
    r"^\s*(?:is|are|can|do|did|will|to)?\s*\b(?:not|never|don't|do\s+not|won't|cannot|can't)\b",
    re.I,
)


def _claim_is_negated(subclause: str, match: re.Match[str]) -> bool:
    """Return True only when explicit English or Indic negation targets this claim match."""
    prefix = subclause[max(0, match.start() - 32) : match.start()]
    head_window = subclause[max(0, match.start() - 12) : min(len(subclause), match.start() + 20)]
    suffix = subclause[match.end() : min(len(subclause), match.end() + 28)]
    return bool(
        _DIRECT_NEG_PREFIX_RE.search(prefix)
        or _NO_TARGET_RE.search(head_window)
        or _POST_NEG_SUFFIX_RE.search(suffix)
        or _INDIC_NEG_RE.search(prefix)
        or _INDIC_NEG_RE.search(suffix)
    )


def _has_unnegated_claim(norm_text: str, pattern: re.Pattern[str]) -> bool:
    """Return True if any subclause contains a matching claim not directly negated."""
    for subclause in _SUBCLAUSE_SPLIT_RE.split(norm_text):
        stripped = subclause.strip()
        if not stripped:
            continue
        for match in pattern.finditer(stripped):
            if not _claim_is_negated(stripped, match):
                return True
    return False


def check_safety_claims(text: str) -> list[str]:
    """Verify output neither labels polluted air 'safe', gives medical dosing, nor pushes plants."""
    norm = unicodedata.normalize("NFC", text)
    reasons: list[str] = []
    if MEDICAL_ADVICE_CLAIM_PATTERN.search(norm):
        reasons.append("Narrative attempted medical dosing or diagnostic advice.")
    if _has_unnegated_claim(norm, SAFE_WINDOW_CLAIM_PATTERN):
        reasons.append("Narrative incorrectly labeled a polluted window as 'safe'.")
    if _has_unnegated_claim(norm, HOUSEPLANT_CLAIM_PATTERN):
        reasons.append("Narrative recommended houseplants for PM2.5 removal.")
    return reasons


def _scan_unit_and_prefix_metrics(scan_text: str, bundle: EvidenceBundle) -> list[str]:
    """Validate unit-bound numbers, hyphenated % ranges, and explicit AQI/PM2.5 mentions."""
    reasons: list[str] = []
    pct_pool = _allowed_pool_for_unit("%", bundle)
    for match in PCT_RANGE_PATTERN.finditer(scan_text):
        for grp in ("a", "b"):
            if not _is_number_grounded(float(match.group(grp)), pct_pool):
                reasons.append(f"Ungrounded percentage range '{match.group(0)}'.")
                break
    for match in METRIC_NUMBER_PATTERN.finditer(scan_text):
        val = float(match.group("num").replace(",", ""))
        if not _is_number_grounded(val, _allowed_pool_for_unit(match.group("unit"), bundle)):
            reasons.append(
                f"Ungrounded metric value '{match.group(0)}' did not match category numbers."
            )
    for pat, pool, label in (
        (PREFIX_AQI_PATTERN, bundle.grounded_metrics.naqi or bundle.grounded_numbers, "NAQI"),
        (PREFIX_PM25_PATTERN, bundle.grounded_metrics.pm25 or bundle.grounded_numbers, "PM2.5"),
    ):
        for match in pat.finditer(scan_text):
            val = float(match.group("num").replace(",", ""))
            if not _is_number_grounded(val, pool):
                reasons.append(f"Ungrounded {label} value '{match.group(0)}' not found in pool.")
    return reasons


def _check_standalone_numbers(scan_text: str, bundle: EvidenceBundle) -> list[str]:
    """Verify any unanchored prose numbers match grounded_numbers after safe masking."""
    masked = scan_text
    for pat in (PCT_RANGE_PATTERN, METRIC_NUMBER_PATTERN, PREFIX_AQI_PATTERN, PREFIX_PM25_PATTERN):
        masked = pat.sub(" ", masked)
    for pat in _EXEMPT_CONTEXT_PATTERNS:
        masked = pat.sub(" ", masked)

    reasons: list[str] = []
    for match in re.finditer(r"(?<![A-Za-z0-9.])\d+(?:,\d{3})*(?:\.\d+)?\b", masked):
        val = float(match.group(0).replace(",", ""))
        if not _is_number_grounded(val, bundle.grounded_numbers):
            reasons.append(f"Ungrounded standalone number '{match.group(0)}' not in evidence.")
    return reasons


def _check_metric_grounding(text: str, bundle: EvidenceBundle) -> list[str]:
    """Verify category-bound metrics and standalone prose numbers against grounded allowlists."""
    scan_text = _normalize_for_metric_scan(text)
    return [
        *_scan_unit_and_prefix_metrics(scan_text, bundle),
        *_check_standalone_numbers(scan_text, bundle),
    ]


def _check_provenance_disclosure(text: str, bundle: EvidenceBundle) -> list[str]:
    """Ensure stale replay and partial-fallback conditions are disclosed honestly in output."""
    low = text.lower()
    if bundle.provenance.is_stale or bundle.provenance.is_fallback_replay:
        if not any(tok in low for tok in STALE_DISCLOSURE_TOKENS):
            return ["Stale/replay provenance was not disclosed in narrative."]
    elif bundle.provenance.is_partial_fallback and not any(
        tok in low for tok in PARTIAL_DISCLOSURE_TOKENS
    ):
        return ["Partial forecast fallback was not disclosed in narrative."]
    return []


def validate_narrative(text: str, bundle: EvidenceBundle) -> tuple[bool, list[str]]:
    """Validate GenAI narrative for banned claims, provenance honesty, and metric numbers."""
    if not text or not text.strip():
        return False, ["Empty narrative output"]
    reasons = [
        *check_safety_claims(text),
        *_check_metric_grounding(text, bundle),
        *_check_provenance_disclosure(text, bundle),
    ]
    return len(reasons) == 0, reasons
