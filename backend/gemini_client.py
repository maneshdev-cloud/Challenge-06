"""Google Gemini Flash SDK client pool, key rotation, cooldowns, and failover runner."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

__all__ = [
    "GEMINI_MODELS",
    "KEY_429_COOLDOWN_SECONDS",
    "MODEL_404_TTL_SECONDS",
    "PLACEHOLDER_KEY",
    "call_gemini_sync",
    "call_gemini_vision_sync",
    "classify_gemini_error",
    "get_api_keys",
    "get_client",
    "record_gemini_failure",
    "reset_failover_cache",
    "run_gemini_with_failover",
]

load_dotenv()

logger = logging.getLogger("prana_ai.gemini_client")

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


def reset_failover_cache() -> None:
    """Clear cached key cooldowns and 404 model skips (primarily for tests)."""
    _MODEL_UNAVAILABLE_UNTIL.clear()
    _KEY_COOLDOWN_UNTIL.clear()


def get_client(api_key: str) -> genai.Client:
    """Reuse google-genai Client per API key with a bounded >=10s SDK HTTP timeout."""
    client = _CLIENT_CACHE.get(api_key)
    if client is None:
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=10_000))
        _CLIENT_CACHE[api_key] = client
    return client


def get_api_keys() -> list[str]:
    """Collect deduplicated Gemini keys from env vars without exposing secrets."""
    raw_candidates: list[str] = []
    comma_keys = os.getenv("GEMINI_API_KEYS", "")
    if comma_keys:
        raw_candidates.extend(k.strip() for k in comma_keys.split(","))
    for single_var in ("GEMINI_API_KEY", "GEMINI_API_KEY_BACKUP"):
        if val := os.getenv(single_var, "").strip():
            raw_candidates.append(val)
    return list(dict.fromkeys(k for k in raw_candidates if k and k != PLACEHOLDER_KEY))


_RETRYABLE_STATUS_CODES = {500, 502, 503, 529}
_INVALID_KEY_STATUS_CODES = {401, 403}


def _check_finish_reason(response: Any, model_name: str) -> bool:
    """Return False when a Gemini candidate explicitly terminated due to MAX_TOKENS truncation."""
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return True
    reason = str(getattr(candidates[0], "finish_reason", "") or "").upper()
    if "MAX_TOKENS" in reason:
        logger.warning("Gemini output truncated by MAX_TOKENS for model %s.", model_name)
        return False
    return True


def classify_gemini_error(exc: Exception) -> str:
    """Classify HTTP status codes and timeout exception types for key/model failover."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code == 429:
        return "429_quota"
    if code == 404:
        return "404_model"
    if code in _INVALID_KEY_STATUS_CODES:
        return "key_invalid"
    if code in _RETRYABLE_STATUS_CODES:
        return "503_unavailable"
    if code == 504 or isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "504_timeout"
    return "other"


def call_gemini_sync(prompt: str, model_name: str, api_key: str, *, system_instruction: str) -> str:
    """Invoke Google Gemini text generation synchronously via pooled Client."""
    response = get_client(api_key).models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2,
            max_output_tokens=900,
        ),
    )
    if not _check_finish_reason(response, model_name):
        return ""
    return (response.text or "").strip()


def call_gemini_vision_sync(  # pylint: disable=too-many-arguments
    prompt: str,
    image_bytes: bytes,
    mime_type: str,
    model_name: str,
    api_key: str,
    *,
    system_instruction: str,
) -> str:
    """Invoke Google Gemini Vision JSON generation synchronously via pooled Client."""
    content_msg = types.Content(
        role="user",
        parts=[
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        ],
    )
    response = get_client(api_key).models.generate_content(
        model=model_name,
        contents=content_msg,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2,
            max_output_tokens=1100,
            response_mime_type="application/json",
        ),
    )
    if not _check_finish_reason(response, model_name):
        return ""
    return (response.text or "").strip()


def record_gemini_failure(api_key: str, model_name: str, key_idx: int, exc: Exception) -> bool:
    """Log failover error and update caches; return True when the API key must rotate."""
    kind = classify_gemini_error(exc)
    ts_now = time.monotonic()
    logger.warning(
        "Gemini key#%d model=%s failed (%s: %s).",
        key_idx + 1,
        model_name,
        kind,
        type(exc).__name__,
    )
    if kind in {"429_quota", "key_invalid"}:
        _KEY_COOLDOWN_UNTIL[api_key] = ts_now + KEY_429_COOLDOWN_SECONDS
        return True
    if kind == "404_model":
        _MODEL_UNAVAILABLE_UNTIL[(api_key, model_name)] = ts_now + MODEL_404_TTL_SECONDS
    return False


async def _try_models_for_key(
    api_key: str,
    key_idx: int,
    overall_deadline: float,
    invoke_sync: Callable[[str, str], str],
    postprocess: Callable[[str, str], Any],
) -> tuple[Any, str | None, bool]:
    """Iterate active models for one API key; third tuple item signals deadline reached."""
    for model_name in GEMINI_MODELS:
        if _MODEL_UNAVAILABLE_UNTIL.get((api_key, model_name), 0.0) > time.monotonic():
            continue
        remaining = overall_deadline - time.monotonic()
        if remaining <= 0.5:
            logger.warning("Gemini failover deadline reached before trying %s.", model_name)
            return None, None, True
        try:
            raw_text = await asyncio.wait_for(
                asyncio.to_thread(invoke_sync, model_name, api_key),
                timeout=min(8.0, remaining),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if record_gemini_failure(api_key, model_name, key_idx, exc):
                return None, None, False
            continue
        if not raw_text or not raw_text.strip():
            logger.warning("Gemini returned empty text for model %s.", model_name)
            continue
        if (parsed := postprocess(raw_text, model_name)) is not None:
            return parsed, model_name, False
        logger.warning("Gemini output rejected by validator for model %s.", model_name)
    return None, None, False


async def run_gemini_with_failover(
    invoke_sync: Callable[[str, str], str],
    postprocess: Callable[[str, str], Any],
) -> tuple[Any, str | None]:
    """Rotate across API keys on 429 and fail over models on 404/503/504/timeout."""
    keys = get_api_keys()
    if not keys:
        return None, None

    overall_deadline = time.monotonic() + 14.0
    for key_idx, api_key in enumerate(keys):
        if _KEY_COOLDOWN_UNTIL.get(api_key, 0.0) > time.monotonic():
            continue
        parsed, model_name, timed_out = await _try_models_for_key(
            api_key, key_idx, overall_deadline, invoke_sync, postprocess
        )
        if parsed is not None or timed_out:
            return parsed, model_name
    return None, None
