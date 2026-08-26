"""2026-08-26, Founder-directed: one OPENAI_MODEL setting drove three very different jobs.

  - the hourly scan of 19 coins: mostly arithmetic filtering, runs constantly, so a large
    model there multiplies cost for little gain
  - Ask AI Trader: a handful of questions a day, where reasoning quality IS the product
  - market forecasts: ~25 a day, judgement rather than arithmetic

Sharing one setting meant the valuable low-volume calls could not be upgraded without also
upgrading the high-frequency one. These pin the split so the two cannot quietly re-merge.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.config import Settings, load_settings


class ModelSplitTests(unittest.TestCase):
    def test_the_scan_and_the_reasoning_calls_read_different_settings(self):
        with mock.patch.dict(os.environ, {"OPENAI_MODEL": "scan-model", "OPENAI_REASONING_MODEL": "reasoning-model"}):
            settings = load_settings()

        self.assertEqual(settings.openai_model, "scan-model")
        self.assertEqual(settings.openai_reasoning_model, "reasoning-model")

    def test_setting_only_the_scan_model_leaves_reasoning_on_its_own_default(self):
        """Setting OPENAI_MODEL alone must not drag the reasoning calls down with it -- that
        is exactly the coupling this split removes."""
        with mock.patch.dict(os.environ, {"OPENAI_MODEL": "scan-model"}, clear=False):
            os.environ.pop("OPENAI_REASONING_MODEL", None)
            settings = load_settings()

        self.assertEqual(settings.openai_model, "scan-model")
        self.assertNotEqual(settings.openai_reasoning_model, "scan-model")
        self.assertTrue(settings.openai_reasoning_model)

    def test_the_high_frequency_default_is_unchanged(self):
        """The 19-coin hourly scan keeps the cheap model it already had; this change must not
        quietly raise the cost of the thing that runs most often."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_MODEL", None)
            settings = load_settings()

        self.assertEqual(settings.openai_model, "gpt-4.1-mini")

    def test_settings_can_still_be_built_without_naming_the_reasoning_model(self):
        """Defaulted rather than required, so no existing caller has to know about it."""
        settings = Settings(
            alpaca_api_key=None, alpaca_secret_key=None,
            alpaca_paper_base_url="https://paper-api.alpaca.markets",
            alpaca_data_base_url="https://data.alpaca.markets",
            openai_api_key=None, openai_model="gpt-4.1-mini",
            db_path=Path("x"), output_dir=Path("y"), trading_log_path=Path("z"),
            guardrails=None,
        )

        self.assertTrue(settings.openai_reasoning_model)


if __name__ == "__main__":
    unittest.main()
