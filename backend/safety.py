"""Hard medical emergency triage and post-generation output validator for PRANA-AI."""

from __future__ import annotations

import re

from schemas import EvidenceBundle

EMERGENCY_KEYWORDS = (
    "wheezing",
    "can't breathe",
    "cant breathe",
    "cannot breathe",
    "breathless",
    "shortness of breath",
    "chest pain",
    "chest tightness",
    "blue lips",
    "bluish lips",
    "asthma attack",
    "inhaler not working",
    "choking",
    "saans nahi",
    "sans nahi",
    "saans phool",
)

EMERGENCY_DIRECTIVE = (
    "MEDICAL EMERGENCY ALERT: Symptoms like wheezing, severe breathlessness, chest pain, "
    "blue lips, or an asthma attack not responding to an inhaler require immediate emergency medical care. "
    "Call emergency services (108 / 112 in India) or go to the nearest hospital ER right now. "
    "Use prescribed rescue medication immediately if instructed by your doctor, move into clean indoor air, "
    "and do not rely on a daily planner for acute respiratory distress."
)

# Metric-tagged numeric patterns that must strictly match values grounded in EvidenceBundle.
METRIC_NUMBER_PATTERN = re.compile(
    r"(?P<num>-?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<unit>ug/m3|µg/m3|ug|µg|naqi|aqi|g\s*co2e?|kg\s*co2e?|mg\s*pm2\.5|cigarettes?|cigs?)\b",
    re.IGNORECASE,
)

PREFIX_AQI_PATTERN = re.compile(
    r"\b(?:india\s+)?(?:cpcb\s+)?(?:naqi|aqi)\s*(?:is|of|:|=)?\s*(?P<num>\d+(?:,\d{3})*(?:\.\d+)?)\b",
    re.IGNORECASE,
)

SAFE_WINDOW_CLAIM_PATTERN = re.compile(
    r"\b(?<!not\s)(?<!never\s)(?:safe\s+window|air\s+is\s+safe|completely\s+safe|safe\s+to\s+breathe\s+outdoors)\b",
    re.IGNORECASE,
)

HOUSEPLANT_CLAIM_PATTERN = re.compile(
    r"\b(?:houseplants?|snake\s+plant|spider\s+plant|areca\s+palm|money\s+plant)\b",
    re.IGNORECASE,
)

NEGATION_WORDS = ("not", "never", "don't", "do not", "no ", "avoid", "cannot", "won't")


def check_medical_emergency(text: str | None) -> tuple[bool, str | None]:
    """Scan user input for acute respiratory or cardiac distress phrases."""
    if not text:
        return False, None
    lowered = text.lower()
    for kw in EMERGENCY_KEYWORDS:
        if kw in lowered:
            return True, EMERGENCY_DIRECTIVE
    return False, None


def _is_number_grounded(val: float, grounded_numbers: list[float]) -> bool:
    for ref in grounded_numbers:
        tol = 0.05 if abs(ref) < 1.0 else max(0.55, abs(ref) * 0.02)
        if abs(val - ref) <= tol:
            return True
    return False


def validate_narrative(text: str, bundle: EvidenceBundle) -> tuple[bool, list[str]]:
    """Validate GenAI narrative for banned claims and ungrounded metric numbers."""
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
        if not _is_number_grounded(val, bundle.grounded_numbers):
            reasons.append(f"Ungrounded metric value '{match.group(0)}' not found in EvidenceBundle.")

    for match in PREFIX_AQI_PATTERN.finditer(text):
        val = float(match.group("num").replace(",", ""))
        if not _is_number_grounded(val, bundle.grounded_numbers):
            reasons.append(f"Ungrounded AQI value '{match.group(0)}' not found in EvidenceBundle.")

    if bundle.provenance.is_stale or bundle.provenance.is_fallback_replay:
        low = text.lower()
        stale_tokens = (
            "replay", "stale", "offline", "unavailable", "historical",
            "पुरान", "उपलब्ध नहीं", "ऐतिहासिक", "रीप्ले", "रिप्ले",
            "उपलब्ध नाही", "ಲಭ್ಯವಿಲ್ಲ", "ಹಿಂದಿನ", "উপলব্ধ নয়", "উপলব্ধ নয়", "ঐতিহাসিক",
            "கிடைக்கவில்லை", "வரலாற்று", "అందుబాటులో లేదు", "చారిత్రక",
        )
        if not any(tok in low for tok in stale_tokens):
            reasons.append("Stale/replay provenance was not disclosed in narrative.")

    return len(reasons) == 0, reasons
