"""Shared gates for tests that require external services or local servers."""

from __future__ import annotations

import os
import unittest
from pathlib import Path


_TRUE_VALUES = {"1", "true", "yes", "on"}


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUE_VALUES


def real_service_tests_enabled() -> bool:
    """Return whether tests may call real LLM, AMap, or local services."""
    return _enabled("RUN_REAL_SERVICE_TESTS")


def require_real_service_tests(reason: str) -> None:
    """Skip a test unless the caller explicitly opted into live services."""
    if not real_service_tests_enabled():
        raise unittest.SkipTest(
            f"{reason}; set RUN_REAL_SERVICE_TESTS=1 to run this test"
        )


def test_artifact_dir() -> Path:
    """Return the ignored directory used for live-test output."""
    configured = os.getenv("TEST_ARTIFACT_DIR", "test-artifacts")
    path = Path(configured)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return path
