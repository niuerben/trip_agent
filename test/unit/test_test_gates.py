from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from test._gates import real_service_tests_enabled, test_artifact_dir


class TestGatesTest(unittest.TestCase):
    def test_live_services_are_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(real_service_tests_enabled())

    def test_live_services_accept_explicit_truthy_values(self) -> None:
        for value in ("1", "true", "TRUE", " yes ", "On"):
            with self.subTest(value=value), patch.dict(
                os.environ, {"RUN_REAL_SERVICE_TESTS": value}, clear=True
            ):
                self.assertTrue(real_service_tests_enabled())

    def test_other_values_keep_live_services_disabled(self) -> None:
        for value in ("0", "false", "no", "off", "", "maybe"):
            with self.subTest(value=value), patch.dict(
                os.environ, {"RUN_REAL_SERVICE_TESTS": value}, clear=True
            ):
                self.assertFalse(real_service_tests_enabled())

    def test_artifact_directory_defaults_to_ignored_root_directory(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(test_artifact_dir(), Path(__file__).resolve().parents[2] / "test-artifacts")

    def test_artifact_directory_can_be_configured(self) -> None:
        with patch.dict(os.environ, {"TEST_ARTIFACT_DIR": "custom-artifacts"}, clear=True):
            self.assertEqual(test_artifact_dir(), Path(__file__).resolve().parents[2] / "custom-artifacts")


if __name__ == "__main__":
    unittest.main()
