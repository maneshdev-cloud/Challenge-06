"""Hard medical emergency triage and metric-aware post-generation validator."""

from __future__ import annotations

import re

from schemas import EvidenceBundle

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
    "दम घुट",
    "શ્વાસ નથી",
    "শ্বাসকষ্ট",
    "మూச்சுத் திணறல்",
    "శ్వాస అందడం లేదు",
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
    r"\b(?:india\s+)?(?:cpcb\s+)?(?:naqi|aqi)\s*(?:is|of|:|=)?\s*"
    r"(?P<num>\d+(?:,\d{3})*(?:\.\d+)?)\b",
    re.IGNORECASE,
)

SAFE_WINDOW_CLAIM_PATTERN = re.compile(
    r"\b(?<!not\s)(?<!never\s)"
    r"(?:safe\s+window|air\s+is\s+safe|completely\s+safe|safe\s+to\s+breathe\s+outdoors)\b",
    re.IGNORECASE,
)

HOUSEPLANT_CLAIM_PATTERN = re.compile(
    r"\b(?:houseplants?|snake\s+plant|spider\s+plant|areca\s+palm|money\s+plant)\b",
    re.IGNORECASE,
)

NEGATION_WORDS = ("not", "never", "don't", "do not", "no ", "avoid", "cannot", "won't")

STALE_DISCLOSURE_TOKENS = (
    "replay", "stale", "offline", "unavailable", "historical",
    "पुरान", "उपलब्ध नहीं", "ऐतिहासिक", "रीप्ले", "रिप्ले",
    "उपलब्ध नाही", "ಲಭ್ಯವಿಲ್ಲ", "ಹಿಂದಿನ", "উপলব্ধ নয়", "উপলব্ধ নয়", "ঐতিহাসিক",
    "கிடைக்கவில்லை", "வரலாற்று", "అందుబాటులో లేదు", "చారిత్రక",
)


def _normalize_apostrophes(text: str) -> str:
    """Normalize curly/smart quotes and collapse extra whitespace for keyword triage."""
    return text.replace("\u2019", "'").replace("\u2018", "'").replace("\u02bc", "'")


def check_medical_emergency(text: str | None) -> tuple[bool, str | None]:
    """Scan user input for acute respiratory or cardiac distress phrases."""
    if not text:
        return False, None
    lowered = _normalize_apostrophes(text).lower()
    for kw in EMERGENCY_KEYWORDS:
        if kw in lowered:
            return True, EMERGENCY_DIRECTIVE
    return False, None


def _is_number_grounded(val: float, grounded_numbers: list[float]) -> bool:
    """Return True when val matches any number in grounded_numbers within tolerance."""
    for ref in grounded_numbers:
        tol = 0.05 if abs(ref) < 1.0 else max(0.55, abs(ref) * 0.02)
        if abs(val - ref) <= tol:
            return True
    return False


def _allowed_pool_for_unit(unit: str, bundle: EvidenceBundle) -> list[float]:
    """Map a matched unit suffix to the category-specific grounded allowlist."""
    u = re.sub(r"\s+", " ", unit.lower().strip())
    gm = bundle.grounded_metrics
    has_typed = any((gm.pm25, gm.naqi, gm.dose_ug, gm.co2_g, gm.co2_kg, gm.tailpipe_mg, gm.pct))
    if not has_typed:
        return bundle.grounded_numbers

    if u in {"ug/m3", "µg/m3"}:
        return gm.pm25
    if u in {"ug", "µg"}:
        return gm.dose_ug + [float(x) for x in bundle.grounded_numbers if x == 330.0]
    if u in {"naqi", "aqi"}:
        return gm.naqi
    if u.startswith("g "):
        return gm.co2_g
    if u.startswith("kg "):
        return gm.co2_kg
    if u.startswith("mg "):
        return gm.tailpipe_mg
    if u.startswith("cig"):
        return gm.cigarettes
    if u == "%":
        return gm.pct + [15.0, 20.0, 35.0, 44.0, 65.0, 70.0, 80.0]
    return bundle.grounded_numbers


def validate_narrative(text: str, bundle: EvidenceBundle) -> tuple[bool, list[str]]:
    """Validate GenAI narrative for banned claims and category-bound metric numbers."""
    if not text or not text.strip():
        return False, ["Empty narrative output"]

    reasons: list[str] = []

    if SAFE_WINDOW_CLAIM_PATTERN.search(text):
        reasons.append("Narrative incorrectly labeled a polluted window as 'safe'.")

    for sentence in re.split(r"[.!?\n]+", text):
        if HOUSEPLANT_CLAIM_PATTERN.search(sentence):
            s_low = sentence.lower()
            if not any(neg in s_low for neg in NEGATION_WORDS):
                reasons.append("Narrative recommended houseplants for PM2.5 removal.")
                break

    for match in METRIC_NUMBER_PATTERN.finditer(text):
        val = float(match.group("num").replace(",", ""))
        pool = _allowed_pool_for_unit(match.group("unit"), bundle)
        if not _is_number_grounded(val, pool):
            reasons.append(
                f"Ungrounded metric value '{match.group(0)}' did not match category numbers."
            )

    naqi_pool = bundle.grounded_metrics.naqi or bundle.grounded_numbers
    for match in PREFIX_AQI_PATTERN.finditer(text):
        val = float(match.group("num").replace(",", ""))
        if not _is_number_grounded(val, naqi_pool):
            reasons.append(f"Ungrounded AQI value '{match.group(0)}' not found in NAQI pool.")

    if bundle.provenance.is_stale or bundle.provenance.is_fallback_replay:
        low = text.lower()
        if not any(tok in low for tok in STALE_DISCLOSURE_TOKENS):
            reasons.append("Stale/replay provenance was not disclosed in narrative.")

    return len(reasons) == 0, reasons
