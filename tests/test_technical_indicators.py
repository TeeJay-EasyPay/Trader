"""2026-08-27 audit finding: five indicator columns, 12,474 rows, zero values.

CRYPTO_RESEARCH_SCORES has always carried rsi, macd, moving_average_position, volume_trend
and market_structure. Not one row had ever had a value in any of them, because nothing in
the codebase computed them -- so every reader treated all five as "insufficient data" and
the research scores rested on price change alone.

Most of it did not need writing. trading_intelligence.analyze_price_series already computed
moving-average position, volume trend and price structure from candles for the equity path;
it was simply never pointed at the crypto candles that had been accumulating in
MARKET_DATA_OBSERVATIONS. RSI and MACD were the only genuinely missing pieces.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.operational import (
    _MARKET_STRUCTURE_SCORES,
    _MOVING_AVERAGE_POSITION_SCORES,
    _technical_indicators,
)
from ai_trader.trading_intelligence import _ema, _macd_line_pct, _rsi, analyze_price_series


def candles(closes, volumes=None):
    volumes = volumes or [1000.0] * len(closes)
    return [
        {
            "observation_time": f"2026-07-{(index % 28) + 1:02d}T00:00:00+00:00",
            "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": volume,
        }
        for index, (close, volume) in enumerate(zip(closes, volumes))
    ]


class RsiTests(unittest.TestCase):
    def test_a_series_that_only_rises_is_maximally_overbought(self):
        # avg_loss is zero here; RSI is defined as 100, not a divide-by-zero.
        self.assertEqual(_rsi([100.0 + index for index in range(40)]), 100.0)

    def test_a_series_that_only_falls_is_maximally_oversold(self):
        self.assertEqual(_rsi([200.0 - index for index in range(40)]), 0.0)

    def test_evenly_matched_gains_and_losses_sit_at_the_midpoint(self):
        alternating = [100.0, 101.0] * 20
        value = _rsi(alternating)
        assert value is not None
        self.assertAlmostEqual(value, 50.0, delta=5.0)

    def test_too_little_history_yields_none_rather_than_a_number(self):
        self.assertIsNone(_rsi([100.0] * 10))
        self.assertIsNone(_rsi([]))

    def test_a_flat_series_is_neutral_not_a_crash(self):
        self.assertEqual(_rsi([100.0] * 40), 50.0)

    def test_output_always_sits_inside_the_defined_zero_to_hundred_range(self):
        import random

        random.seed(7)
        for _ in range(25):
            series = [random.uniform(1.0, 500.0) for _ in range(60)]
            value = _rsi(series)
            assert value is not None
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 100.0)


class MacdTests(unittest.TestCase):
    def test_macd_is_price_scale_independent(self):
        """The load-bearing test. A raw MACD line is in price units, so Bitcoin at ~58,000
        would dwarf Stellar at ~0.30 for an identical move and cross-coin ranking would sort
        by coin price rather than by momentum."""
        shape = [100.0 * (1.02 ** index) for index in range(60)]
        cheap = _macd_line_pct(shape)
        expensive = _macd_line_pct([value * 5000.0 for value in shape])
        assert cheap is not None and expensive is not None
        self.assertAlmostEqual(cheap, expensive, places=4)

    def test_rising_and_falling_series_have_opposite_signs(self):
        rising = _macd_line_pct([100.0 * (1.02 ** index) for index in range(60)])
        falling = _macd_line_pct([100.0 * (0.98 ** index) for index in range(60)])
        assert rising is not None and falling is not None
        self.assertGreater(rising, 0)
        self.assertLess(falling, 0)

    def test_too_little_history_yields_none(self):
        self.assertIsNone(_macd_line_pct([100.0] * 20))

    def test_ema_needs_a_full_period_before_it_reports(self):
        self.assertIsNone(_ema([1.0, 2.0], 5))
        self.assertIsNotNone(_ema([1.0] * 5, 5))


class AnalyzePriceSeriesTests(unittest.TestCase):
    def test_the_shared_analyser_now_reports_rsi_and_macd(self):
        metrics = analyze_price_series(candles([100.0 + index for index in range(60)]))
        self.assertIsNotNone(metrics["rsi"])
        self.assertIsNotNone(metrics["macd"])

    def test_the_no_candles_path_still_returns_both_keys_as_none(self):
        # Callers index these keys directly; a missing key would be a KeyError, not a gap.
        metrics = analyze_price_series([])
        self.assertIsNone(metrics["rsi"])
        self.assertIsNone(metrics["macd"])


class IndicatorMappingTests(unittest.TestCase):
    """The columns are numeric, so the analyser's string classifications are mapped onto a
    0-1 scale rather than stored as text."""

    def test_every_classification_the_analyser_can_emit_has_a_mapping(self):
        rising = analyze_price_series(candles([100.0 + index for index in range(60)]))
        falling = analyze_price_series(candles([200.0 - index for index in range(60)]))
        for metrics in (rising, falling):
            self.assertIn(metrics["moving_average_position"], _MOVING_AVERAGE_POSITION_SCORES)
            self.assertIn(metrics["price_structure"], _MARKET_STRUCTURE_SCORES)

    def test_a_rising_market_scores_above_a_falling_one(self):
        rising = _technical_indicators(candles([100.0 + index for index in range(60)]))
        falling = _technical_indicators(candles([200.0 - index for index in range(60)]))
        self.assertEqual(rising["market_structure"], 1.0)
        self.assertEqual(falling["market_structure"], 0.0)
        self.assertGreater(rising["rsi"], falling["rsi"])

    def test_all_five_columns_are_populated_from_real_candles(self):
        """The whole point: none of these may come back None for a symbol with history."""
        indicators = _technical_indicators(
            candles([100.0 + (index % 7) * 3 for index in range(60)],
                    volumes=[900.0 + index * 10 for index in range(60)])
        )
        for field in ("rsi", "macd", "volume_trend", "moving_average_position", "market_structure"):
            self.assertIsNotNone(indicators[field], f"{field} was left empty")

    def test_no_candles_leaves_the_indicators_unset_rather_than_guessed(self):
        indicators = _technical_indicators([])
        self.assertIsNone(indicators["rsi"])
        self.assertIsNone(indicators["macd"])


if __name__ == "__main__":
    unittest.main()
