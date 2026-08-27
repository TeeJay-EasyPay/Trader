"""2026-08-27 audit finding: crypto research had exactly one source.

Every crypto research score came from CoinGecko's free public markets API, and
seed_crypto_universe only reaches _populate_crypto_master_and_scores when that fetch
succeeds. A CoinGecko outage -- or the HTTP 429 rate-limiting this API already returns in
production, see test_crypto_universe_refresh_backoff.py -- did not degrade crypto research,
it stopped it, silently, leaving the universe trading on whatever scores it last had.

Meanwhile refresh_crypto_candle_history was already ingesting real daily OHLC candles from
Kraken into MARKET_DATA_OBSERVATIONS (4,415 candles across 19 symbols at the time of this
audit) and nothing read them for scoring. These tests cover reading them instead.

The load-bearing property is that the two paths use IDENTICAL formulas, so failing over
does not quietly change trading behaviour.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from contextlib import closing

from ai_trader.database import connect
from ai_trader.market_intelligence_platform import initialize_market_intelligence_schema, record_market_observations
from ai_trader.multi_broker import initialize_multi_broker_schema
from ai_trader.operational import (
    KRAKEN_CANDLE_SOURCE,
    _crypto_metrics_from_kraken_candles,
    _crypto_metrics_from_market_row,
    initialize_operational_schema,
    record_crypto_scores_from_kraken_candles,
    seed_crypto_universe,
)


def candle_series(closes: list[float]) -> list[dict]:
    """Daily candles, oldest first -- the order _recent_observations_query returns."""
    return [
        {
            "observation_time": f"2026-07-{(index % 28) + 1:02d}T00:00:00+00:00",
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000.0,
        }
        for index, close in enumerate(closes)
    ]


def store_candles(db_path: Path, symbol: str, closes: list[float]) -> None:
    candles = [
        {**candle, "observation_time": f"2026-07-{index + 1:02d}T00:00:00+00:00"}
        for index, candle in enumerate(candle_series(closes))
    ]
    record_market_observations(
        db_path,
        provider="kraken",
        original_symbol=f"{symbol}GBP",
        normalized_symbol=symbol,
        exchange="KRAKEN",
        asset_type="crypto",
        timeframe="1d",
        candles=candles,
        adjusted_status="unadjusted",
        payload_provenance="kraken_ohlc_api",
    )


class KrakenCandleMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        initialize_operational_schema(self.db_path)
        initialize_market_intelligence_schema(self.db_path)
        initialize_multi_broker_schema(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_thin_history_is_left_unscored_rather_than_guessed(self):
        # 10 candles cannot support a 30-day change. Scoring anyway would mean inventing one.
        self.assertIsNone(
            _crypto_metrics_from_kraken_candles(
                candle_series([100.0] * 10), db_path=self.db_path, symbol="BTC"
            )
        )

    def test_no_candles_at_all_is_unscored(self):
        self.assertIsNone(_crypto_metrics_from_kraken_candles([], db_path=self.db_path, symbol="BTC"))

    def test_metrics_match_the_coingecko_path_for_the_same_price_moves(self):
        """The load-bearing test: same price behaviour in, same scores out.

        If these two ever diverge, failing over to Kraken silently rescales every crypto
        score and changes which trades pass due diligence.
        """
        # A 40-day series where the moves are exact and known: flat, then +10% over the last
        # day, engineered so 24h/7d/30d changes are computable both ways.
        closes = [100.0] * 40
        closes[-1] = 110.0  # +10% on the day, and +10% vs 7 and 30 days back
        from_candles = _crypto_metrics_from_kraken_candles(
            candle_series(closes), db_path=self.db_path, symbol="BTC"
        )
        assert from_candles is not None
        from_coingecko = _crypto_metrics_from_market_row(
            {
                "price_change_percentage_24h_in_currency": 10.0,
                "price_change_percentage_7d_in_currency": 10.0,
                "price_change_percentage_30d_in_currency": 10.0,
            }
        )
        for metric in ("technical_trend_score", "momentum_score", "volatility", "risk_score"):
            self.assertAlmostEqual(
                from_candles[metric], from_coingecko[metric], places=4,
                msg=f"{metric} must be on the same scale in both paths",
            )

    def test_liquidity_is_left_unset_when_coingecko_never_measured_it(self):
        """Liquidity needs market cap, which an OHLC bar does not carry. Inventing a
        substitute would put a fabricated number into a live sizing decision."""
        metrics = _crypto_metrics_from_kraken_candles(
            candle_series([100.0 + index for index in range(40)]), db_path=self.db_path, symbol="KSM"
        )
        assert metrics is not None
        self.assertIsNone(metrics["liquidity"])
        self.assertIsNone(metrics["reasoning"]["liquidity_carried_forward_from"])

    def carry_forward_row(self, reasoning_json, liquidity=0.0191):
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO CRYPTO_RESEARCH_SCORES (created_at, symbol, liquidity, source, reasoning_json)"
                    " VALUES (?, ?, ?, ?, ?)",
                    ("2026-08-20T00:00:00+00:00", "BTC", liquidity, "CoinGecko public markets API", reasoning_json),
                )
        return _crypto_metrics_from_kraken_candles(
            candle_series([100.0 + index for index in range(40)]), db_path=self.db_path, symbol="BTC"
        )

    def test_liquidity_carries_forward_from_the_recorded_turnover(self):
        """Carried forward from the RAW turnover and rescaled here, not from the stored score.
        2026-08-27: the stored column changed meaning when liquidity was rescaled, so turnover
        is what gets recorded and what gets read."""
        metrics = self.carry_forward_row('{"liquidity_turnover": 0.0414}')
        assert metrics is not None
        self.assertGreater(metrics["liquidity"], 0.7)  # ETH-grade turnover is deep liquidity
        # Provenance must be visible, not silently presented as a fresh reading.
        self.assertEqual(metrics["reasoning"]["liquidity_carried_forward_from"], "2026-08-20T00:00:00+00:00")

    def test_a_row_predating_the_rescale_is_refused_rather_than_misread(self):
        """A row with no turnover recorded holds a raw ratio on a scale that no longer means
        anything here. Using it was confirmed harmful live: SOL carried the strongest signals
        in the universe and scored LOWEST, because a stale 0.11 was averaged in as if it were a
        quality score -- so coins with NO liquidity data outranked coins that had some."""
        metrics = self.carry_forward_row("{}", liquidity=0.0642)
        assert metrics is not None
        self.assertIsNone(metrics["liquidity"])
        self.assertIsNone(metrics["reasoning"]["liquidity_carried_forward_from"])

    def test_a_kraken_sourced_score_never_claims_to_be_coingecko(self):
        metrics = _crypto_metrics_from_kraken_candles(
            candle_series([100.0 + index for index in range(40)]), db_path=self.db_path, symbol="BTC"
        )
        assert metrics is not None
        self.assertEqual(metrics["reasoning"]["source"], KRAKEN_CANDLE_SOURCE)


class KrakenFallbackWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        initialize_operational_schema(self.db_path)
        initialize_market_intelligence_schema(self.db_path)
        initialize_multi_broker_schema(self.db_path)
        # Two coins with real, differently-shaped history; one too thin to score.
        store_candles(self.db_path, "BTC", [100.0 + index for index in range(40)])
        store_candles(self.db_path, "ETH", [200.0 - index for index in range(40)])
        store_candles(self.db_path, "THIN", [50.0] * 5)

    def tearDown(self):
        self.tmp.cleanup()

    def recorded_scores(self) -> list[tuple]:
        with closing(connect(self.db_path)) as conn:
            return conn.execute(
                "SELECT symbol, source, technical_trend_score, momentum_score FROM CRYPTO_RESEARCH_SCORES"
                " ORDER BY symbol"
            ).fetchall()

    def test_scores_every_symbol_that_has_enough_candles(self):
        result = record_crypto_scores_from_kraken_candles(self.db_path)
        self.assertEqual(result["scored"], 2)
        self.assertEqual(sorted(result["symbols_scored"]), ["BTC", "ETH"])
        self.assertEqual(result["symbols_skipped_insufficient_history"], ["THIN"])

    def test_rising_and_falling_coins_get_genuinely_different_scores(self):
        """The bug this whole area exists to prevent: 12,239 stored rows that all carried the
        identical fabricated score. Real data must produce real spread."""
        record_crypto_scores_from_kraken_candles(self.db_path)
        scores = {row[0]: row[2] for row in self.recorded_scores()}
        self.assertGreater(scores["BTC"], 0.5, "a rising series must score above neutral")
        self.assertLess(scores["ETH"], 0.5, "a falling series must score below neutral")

    def test_coingecko_failure_falls_back_to_kraken_instead_of_writing_nothing(self):
        """Before this, an exception here returned {'inserted': 0} and no scores at all."""
        with mock.patch("ai_trader.operational.urlopen", side_effect=OSError("HTTP Error 429: Too Many Requests")):
            result = seed_crypto_universe(self.db_path, fetch_live=True)
        self.assertEqual(result["source"], KRAKEN_CANDLE_SOURCE)
        self.assertEqual(result["fallback"]["scored"], 2)
        self.assertTrue(all(row[1] == KRAKEN_CANDLE_SOURCE for row in self.recorded_scores()))

    def test_the_fallback_is_recorded_as_an_operational_event_not_hidden(self):
        with mock.patch("ai_trader.operational.urlopen", side_effect=OSError("boom")):
            seed_crypto_universe(self.db_path, fetch_live=True)
        with closing(connect(self.db_path)) as conn:
            events = conn.execute(
                "SELECT event_type, severity FROM OPERATIONAL_EVENTS WHERE event_type LIKE ?",
                ("%kraken_fallback%",),
            ).fetchall()
        self.assertEqual(len(events), 1, "a degraded data source must be visible, not silent")
        self.assertEqual(events[0][1], "warning")

    def test_no_fallback_when_the_caller_did_not_ask_for_live_data(self):
        # fetch_live=False means "do not go to the network", not "the network failed".
        result = seed_crypto_universe(self.db_path, fetch_live=False)
        self.assertNotIn("fallback", result)
        self.assertEqual(self.recorded_scores(), [])


if __name__ == "__main__":
    unittest.main()
