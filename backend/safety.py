"""Hard medical emergency triage, bundle HMAC integrity, and category-bound validator."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets

from geo_india import CONSTANTS
from schemas import EvidenceBundle

logger = logging.getLogger("prana_ai.safety")

PLACEHOLDER_KEY = "your_google_ai_studio_key_here"
_EPHEMERAL_SECRET = secrets.token_bytes(32)
CIG_EQUIV_UG = float(CONSTANTS["berkeley_earth_cig_ug"])

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
    """Resolve dedicated HMAC key from PRANA_BUNDLE_SECRET or local ephemeral fallback."""
    explicit = os.getenv("PRANA_BUNDLE_SECRET", "").strip()
    if explicit:
        return explicit.encode("utf-8")
    if os.getenv("VERCEL_ENV", "").strip() or os.getenv("RENDER", "").strip():
        raise RuntimeError("PRANA_BUNDLE_SECRET must be set in deployed environments.")
    logger.warning("PRANA_BUNDLE_SECRET unset; using per-process ephemeral HMAC key.")
    return _EPHEMERAL_SECRET


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


def verify_evidence_bundle(bundle: EvidenceBundle, signature: str | None) -> bool:
    """Verify submitted EvidenceBundle HMAC-SHA256 signature in constant time."""
    if not signature or not isinstance(signature, str):
        return False
    expected = sign_evidence_bundle(bundle)
    return hmac.compare_digest(expected, signature.strip().lower())


def _normalize_apostrophes(text: str) -> str:
    """Normalize curly/smart quotes for reliable emergency keyword matching."""
    return text.replace("\u2019", "'").replace("\u02bc", "'").replace("\u2018", "'")


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


def _check_safety_claims(text: str) -> list[str]:
    """Verify output neither labels polluted outdoor windows 'safe' nor recommends houseplants."""
    reasons: list[str] = []
    if SAFE_WINDOW_CLAIM_PATTERN.search(text):
        reasons.append("Narrative incorrectly labeled a polluted window as 'safe'.")
    for clause in re.split(r"[.!?;,\n]+", text):
        if HOUSEPLANT_CLAIM_PATTERN.search(clause) and not any(
            neg in clause.lower() for neg in NEGATION_WORDS
        ):
            reasons.append("Narrative recommended houseplants for PM2.5 removal.")
            break
    return reasons


def _check_metric_grounding(text: str, bundle: EvidenceBundle) -> list[str]:
    """Verify all metric-bound numbers and AQI citations match grounded category allowlists."""
    reasons: list[str] = []
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
    return reasons


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
        *_check_safety_claims(text),
        *_check_metric_grounding(text, bundle),
        *_check_provenance_disclosure(text, bundle),
    ]
    return len(reasons) == 0, reasons
