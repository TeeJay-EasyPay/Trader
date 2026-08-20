"""Phase 3 of the CIO-level forecasting build (2026-08-20, Founder-directed).

The most important test in this file is
AntiCircularityTests::test_forecast_evidence_never_contains_trade_performance_data --
the Founder explicitly flagged the circularity risk (a "forecast" derived from the AI's
own past trade results reinforces whatever it already believed on no new information)
and accepted the build on the condition that this could never happen. That test is a
permanent regression guard, not a one-time check.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.ai import _forecast_from_response_text
from ai_trader.forecasting import (
    build_forecast_evidence,
    generate_market_forecast,
    latest_forecast,
    recent_forecasts,
    record_forecast,
    resample_weekly,
)
from ai_trader.market_intelligence_platform import record_market_observations


def _candle(observation_time: str, close: float) -> dict:
    return {"observation_time": observation_time, "open": close - 1, "high": close + 2, "low": close - 2, "close": close, "volume": 100.0}


def _seed_crypto_history(db_path: Path, symbol: str = "BTC", days: int = 40) -> None:
    candles = []
    for i in range(days):
        # A real, mild uptrend so the technical read has something genuine to describe.
        candles.append(_candle(f"2026-06-{(i % 30) + 1:02d}T00:00:00+00:00" if i < 30 else f"2026-07-{(i - 30) + 1:02d}T00:00:00+00:00", 100.0 + i))
    record_market_observations(
        db_path, provider="kraken", original_symbol=f"{symbol}GBP", normalized_symbol=symbol,
        exchange="KRAKEN", asset_type="crypto", timeframe="1d", candles=candles,
    )


class FakeForecastAnalyzer:
    model = "test-model"

    def __init__(self, response: dict | None = None, raises: Exception | None = None):
        self.response = response
        self.raises = raises
        self.received_evidence: dict | None = None

    def forecast(self, *, scope, symbol, asset_type, evidence):
        self.received_evidence = evidence
        if self.raises:
            raise self.raises
        return self.response


def _valid_forecast() -> dict:
    return {
        "direction": "bullish",
        "horizon_days": 14,
        "confidence": 0.62,
        "reasoning": "The 5-period moving average sits above the 20-period, with momentum positive.",
        "supporting_evidence": ["short_ma above long_ma"],
        "contradictory_evidence": ["volume trend is flat"],
        "key_risks": ["A broad risk-off move would invalidate this"],
        "invalidation": "A daily close below the 20-period moving average.",
    }


class AntiCircularityTests(unittest.TestCase):
    def test_forecast_evidence_never_contains_trade_performance_data(self):
        """THE critical guard. See this module's docstring."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_crypto_history(db_path)

            evidence = build_forecast_evidence(db_path, symbol="BTC", asset_type="crypto")

            keys_seen: list[str] = []

            def collect(node, path="evidence"):
                if isinstance(node, dict):
                    for key, value in node.items():
                        keys_seen.append(str(key).lower())
                        collect(value, f"{path}.{key}")
                elif isinstance(node, list):
                    for item in node:
                        collect(item, path)

            collect(evidence)
            for forbidden in ("pnl", "profit", "win_rate", "realized", "realised", "expectancy", "closed_trade", "performance", "attribution"):
                matches = [key for key in keys_seen if forbidden in key]
                self.assertEqual(matches, [], f"Forecast evidence must never carry a trade-performance key; found {matches}")

    def test_wiring_performance_data_into_evidence_fails_loudly(self):
        from ai_trader.forecasting import _assert_no_performance_data

        with self.assertRaises(ValueError):
            _assert_no_performance_data({"daily": {"metrics": {}}, "realized_pnl": 123.45})
        with self.assertRaises(ValueError):
            _assert_no_performance_data({"nested": {"deeper": [{"win_rate": 0.5}]}})

    def test_free_text_mentioning_profit_is_not_falsely_rejected(self):
        # Curated reference material legitimately discusses profit-taking
        # (knowledge/stop_loss_and_take_profit_mechanics.md is entirely about it) and
        # news commentary routinely mentions performance -- the guard checks structural
        # keys only, so this must pass rather than false-positive.
        from ai_trader.forecasting import _assert_no_performance_data

        _assert_no_performance_data(
            {
                "reference_material": [{"title": "Stop loss and take profit mechanics", "excerpt": "Take profit at resistance; realised gains..."}],
                "macro_and_news": ["Company X reported strong performance and profit growth"],
            }
        )


class ResampleWeeklyTests(unittest.TestCase):
    def test_aggregates_daily_candles_into_weekly_ohlc(self):
        daily = [
            {"observation_time": "2026-08-03T00:00:00+00:00", "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 10.0},
            {"observation_time": "2026-08-04T00:00:00+00:00", "open": 104.0, "high": 108.0, "low": 103.0, "close": 107.0, "volume": 12.0},
            {"observation_time": "2026-08-10T00:00:00+00:00", "open": 107.0, "high": 110.0, "low": 106.0, "close": 109.0, "volume": 8.0},
        ]
        weekly = resample_weekly(daily)
        self.assertEqual(len(weekly), 2, "Two distinct ISO weeks must produce two weekly candles.")
        self.assertEqual(weekly[0]["open"], 100.0, "Weekly open is the first day's open.")
        self.assertEqual(weekly[0]["close"], 107.0, "Weekly close is the last day's close.")
        self.assertEqual(weekly[0]["high"], 108.0, "Weekly high is the max across the week.")
        self.assertEqual(weekly[0]["low"], 99.0, "Weekly low is the min across the week.")
        self.assertEqual(weekly[0]["volume"], 22.0, "Weekly volume is the sum across the week.")

    def test_empty_and_unparseable_inputs_degrade_safely(self):
        self.assertEqual(resample_weekly([]), [])
        self.assertEqual(resample_weekly([{"observation_time": "not-a-date", "close": 1.0}]), [])


class ForecastResponseParsingTests(unittest.TestCase):
    def test_parses_a_valid_forecast(self):
        parsed = _forecast_from_response_text(json.dumps(_valid_forecast()))
        self.assertEqual(parsed["direction"], "bullish")
        self.assertEqual(parsed["horizon_days"], 14)
        self.assertAlmostEqual(parsed["confidence"], 0.62)

    def test_rejects_an_out_of_range_or_malformed_response_rather_than_half_trusting_it(self):
        for bad in (
            {**_valid_forecast(), "direction": "moon"},
            {**_valid_forecast(), "confidence": 1.5},
            {**_valid_forecast(), "confidence": "not-a-number"},
            {**_valid_forecast(), "horizon_days": 0},
            {**_valid_forecast(), "reasoning": ""},
        ):
            self.assertIsNone(_forecast_from_response_text(json.dumps(bad)), f"Should reject: {bad}")
        self.assertIsNone(_forecast_from_response_text("not json at all"))
        self.assertIsNone(_forecast_from_response_text("null"))
        self.assertIsNone(_forecast_from_response_text(""))


class GenerateMarketForecastTests(unittest.TestCase):
    def test_generates_and_persists_a_real_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_crypto_history(db_path)
            analyzer = FakeForecastAnalyzer(response=_valid_forecast())

            result = generate_market_forecast(db_path, analyzer=analyzer, symbol="BTC", asset_type="crypto")

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["direction"], "bullish")
            stored = latest_forecast(db_path, symbol="BTC")
            self.assertIsNotNone(stored)
            self.assertEqual(stored["direction"], "bullish")
            self.assertEqual(stored["generated_by"], "test-model")
            self.assertIsNotNone(stored["expires_at"])

    def test_the_analyzer_actually_receives_real_technical_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_crypto_history(db_path)
            analyzer = FakeForecastAnalyzer(response=_valid_forecast())

            generate_market_forecast(db_path, analyzer=analyzer, symbol="BTC", asset_type="crypto")

            evidence = analyzer.received_evidence
            self.assertGreaterEqual(evidence["daily"]["candles_available"], 20)
            self.assertIsNotNone(evidence["daily"]["metrics"].get("short_ma"), "Real moving averages must reach the model, not empty metrics.")
            self.assertGreater(evidence["weekly"]["periods_available"], 0, "A second, slower timeframe must be supplied for a real trend read.")

    def test_insufficient_history_is_reported_honestly_rather_than_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_crypto_history(db_path, days=3)
            analyzer = FakeForecastAnalyzer(response=_valid_forecast())

            result = generate_market_forecast(db_path, analyzer=analyzer, symbol="BTC", asset_type="crypto")

            self.assertEqual(result["status"], "insufficient_evidence")
            self.assertIsNone(analyzer.received_evidence, "The model must not even be called when there is no real basis for a view.")
            self.assertIsNone(latest_forecast(db_path, symbol="BTC"), "Nothing should be persisted when evidence is insufficient.")

    def test_an_analyzer_failure_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_crypto_history(db_path)
            analyzer = FakeForecastAnalyzer(raises=RuntimeError("network timeout"))

            result = generate_market_forecast(db_path, analyzer=analyzer, symbol="BTC", asset_type="crypto")

            self.assertEqual(result["status"], "failed")
            self.assertIn("network timeout", result["reason"])

    def test_an_unusable_model_response_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_crypto_history(db_path)
            analyzer = FakeForecastAnalyzer(response=None)

            result = generate_market_forecast(db_path, analyzer=analyzer, symbol="BTC", asset_type="crypto")

            self.assertEqual(result["status"], "no_usable_forecast")
            self.assertIsNone(latest_forecast(db_path, symbol="BTC"))

    def test_recent_forecasts_returns_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            for direction in ("bullish", "bearish"):
                record_forecast(
                    db_path, scope="symbol", symbol="BTC", asset_type="crypto",
                    forecast={**_valid_forecast(), "direction": direction},
                    evidence={"daily": {"candles_available": 40}}, generated_by="test-model",
                )
            rows = recent_forecasts(db_path, limit=5)
            self.assertEqual(rows[0]["direction"], "bearish")


if __name__ == "__main__":
    unittest.main()
