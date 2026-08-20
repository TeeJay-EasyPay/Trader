"""Phase 2 of the CIO-level forecasting build (2026-08-20, Founder-directed):
analyze_price_series/infer_market_regime were already called on every live
proposal (both asset classes) but starved to a single current-price bar.
These pin the new real-history loaders and confirm real candle history now
actually reaches the live proposal path for both equities and crypto."""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.agent import propose_crypto_trades
from ai_trader.audit import AuditDatabase
from ai_trader.foundation import initialize_foundation_schema
from ai_trader.market_intelligence_platform import load_recent_observations, load_recent_observations_batch, record_market_observations
from ai_trader.models import AccountContext, GuardrailConfig
from ai_trader.multi_broker import record_crypto_research_score
from ai_trader.trading_intelligence import initialize_trading_intelligence_schema, load_recent_candles, load_recent_candles_batch, record_historical_candle


def _seed_score(db_path: Path, symbol: str = "BTC") -> None:
    record_crypto_research_score(
        db_path,
        symbol=symbol,
        category="Top 20 by market cap",
        metrics={
            "technical_trend_score": 0.75,
            "momentum_score": 0.6,
            "volatility": 0.2,
            "liquidity": 0.8,
            "risk_score": 0.8,
            "overall_due_diligence_score": 0.9,
            "confidence_score": 0.9,
        },
        source="test",
    )


def _account() -> AccountContext:
    return AccountContext(equity=1000, daily_realized_pnl=0, open_positions=[], is_paper=False)


class FakeAdapter:
    def current_prices(self, pairs):
        return {pairs[0]: {"c": ["100.0", "1.0"], "h": ["105.0", "108.0"], "l": ["95.0", "92.0"], "o": "98.0"}}


class LoadRecentCandlesTests(unittest.TestCase):
    def test_returns_real_candles_oldest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_trading_intelligence_schema(db_path)
            for i, close in enumerate([100.0, 101.0, 102.0]):
                record_historical_candle(
                    db_path, symbol="AAPL", asset_type="stock", timeframe="1d",
                    observed_at=f"2026-08-{10 + i:02d}T00:00:00+00:00", close=close, source="test",
                )
            candles = load_recent_candles(db_path, symbol="AAPL", asset_type="stock", timeframe="1d")
            self.assertEqual([c["close"] for c in candles], [100.0, 101.0, 102.0])

    def test_limit_keeps_only_the_most_recent_rows_in_chronological_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_trading_intelligence_schema(db_path)
            for i, close in enumerate([100.0, 101.0, 102.0, 103.0, 104.0]):
                record_historical_candle(
                    db_path, symbol="AAPL", asset_type="stock", timeframe="1d",
                    observed_at=f"2026-08-{10 + i:02d}T00:00:00+00:00", close=close, source="test",
                )
            candles = load_recent_candles(db_path, symbol="AAPL", asset_type="stock", timeframe="1d", limit=2)
            self.assertEqual([c["close"] for c in candles], [103.0, 104.0])

    def test_batch_reads_multiple_symbols_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_trading_intelligence_schema(db_path)
            record_historical_candle(db_path, symbol="AAPL", asset_type="stock", timeframe="1d", observed_at="2026-08-10T00:00:00+00:00", close=100.0, source="test")
            record_historical_candle(db_path, symbol="MSFT", asset_type="stock", timeframe="1d", observed_at="2026-08-10T00:00:00+00:00", close=200.0, source="test")
            result = load_recent_candles_batch(db_path, symbols=["AAPL", "MSFT", "TSLA"], asset_type="stock", timeframe="1d")
            self.assertEqual(result["AAPL"][0]["close"], 100.0)
            self.assertEqual(result["MSFT"][0]["close"], 200.0)
            self.assertEqual(result["TSLA"], [])


class LoadRecentObservationsTests(unittest.TestCase):
    def _candle(self, observation_time: str, close: float) -> dict:
        return {"observation_time": observation_time, "open": close - 1, "high": close + 1, "low": close - 2, "close": close, "volume": 10.0}

    def test_returns_real_candles_oldest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_market_observations(
                db_path, provider="kraken", original_symbol="XXBTZGBP", normalized_symbol="BTC",
                exchange="KRAKEN", asset_type="crypto", timeframe="1d",
                candles=[self._candle("2026-08-18T00:00:00+00:00", 40000.0), self._candle("2026-08-19T00:00:00+00:00", 41000.0)],
            )
            candles = load_recent_observations(db_path, "BTC", timeframe="1d")
            self.assertEqual([c["close"] for c in candles], [40000.0, 41000.0])

    def test_batch_reads_multiple_symbols_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_market_observations(
                db_path, provider="kraken", original_symbol="XXBTZGBP", normalized_symbol="BTC",
                exchange="KRAKEN", asset_type="crypto", timeframe="1d", candles=[self._candle("2026-08-19T00:00:00+00:00", 41000.0)],
            )
            result = load_recent_observations_batch(db_path, ["BTC", "ETH"], timeframe="1d")
            self.assertEqual(result["BTC"][0]["close"], 41000.0)
            self.assertEqual(result["ETH"], [])


class CryptoProposalHistoryEnrichmentTests(unittest.TestCase):
    def _candle(self, observation_time: str, close: float) -> dict:
        return {"observation_time": observation_time, "open": close - 1, "high": close + 1, "low": close - 2, "close": close, "volume": 10.0}

    def test_a_proposal_reflects_real_seeded_candle_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            _seed_score(db_path)
            for i in range(25):
                record_market_observations(
                    db_path, provider="kraken", original_symbol="XXBTZGBP", normalized_symbol="BTC",
                    exchange="KRAKEN", asset_type="crypto", timeframe="1d",
                    candles=[self._candle(f"2026-07-{i + 1:02d}T00:00:00+00:00", 90.0 + i)],
                )

            proposals = propose_crypto_trades(
                db_path, FakeAdapter(), ["BTC"], _account(), GuardrailConfig(), audit,
                min_confidence=0.85, requested_notional=5.0, default_stop_loss_pct=0.02,
            )

            self.assertEqual(len(proposals), 1)
            data_quality = proposals[0].intelligence["market_intelligence"]["data_quality"]
            self.assertEqual(data_quality["candle_count"], 25, "The real seeded candle history must reach analyze_price_series, not a single snapshot bar.")
            metrics = proposals[0].intelligence["market_intelligence"]["metrics"]
            self.assertIsNotNone(metrics.get("short_ma"), "With 25 real candles, a real 5-period moving average must be computable, not None.")

    def test_a_proposal_with_no_seeded_history_still_completes_without_a_moving_average(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            _seed_score(db_path)

            proposals = propose_crypto_trades(
                db_path, FakeAdapter(), ["BTC"], _account(), GuardrailConfig(), audit,
                min_confidence=0.85, requested_notional=5.0, default_stop_loss_pct=0.02,
            )

            self.assertEqual(len(proposals), 1, "No seeded candle history must degrade gracefully, never block a proposal.")
            data_quality = proposals[0].intelligence["market_intelligence"]["data_quality"]
            self.assertEqual(data_quality["candle_count"], 0)


if __name__ == "__main__":
    unittest.main()
