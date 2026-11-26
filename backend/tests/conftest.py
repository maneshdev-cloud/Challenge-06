"""Pytest path setup and shared fixtures for PRANA-AI backend tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture(autouse=True)
def _reset_rate_limiters() -> None:
    """Isolate per-test request buckets cleanly without test-only production bypasses."""
    from request_guards import (
        DEFAULT_RATE_LIMITER,
        JSON_OUTER_RATE_LIMITER,
        NON_LLM_RATE_LIMITER,
    )

    DEFAULT_RATE_LIMITER.clear()
    JSON_OUTER_RATE_LIMITER.clear()
    NON_LLM_RATE_LIMITER.clear()
