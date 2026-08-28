"""2026-08-28, Founder-directed: use Kraken's real order book, not a computed proxy.

The Founder pushed back on deriving liquidity from candle volume -- "we need actual liquidity
data. Doesn't kraken have that?" -- and he was right on every count. Kraken publishes full
order-book depth free, the app was already reading it for a proposal-time penalty, and it beats
the CoinGecko figure it replaces: that was volume / market cap, a global statistic saying
nothing about whether this account can get in and out on Kraken, and it covered only 8 of the
19 pairs actually traded.

Measured live the day this was written:

    XBTGBP  spread 0.03%  support 2.5% down  -> 0.944
    DOTGBP  spread 0.11%  support 2.0% down  -> 0.814
    BCHGBP  spread 0.80%  no support         -> 0.333

Spread is weighted double because it is a certain cost paid on every trade in both directions,
and it is invisible in the fee schedule: BCH's 0.80% spread adds ~1.6% to a round trip that
already costs 1.6% in fees. That is the fee drag the Founder has been chasing all week, and it
was never being scored.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.liquidity_map import LiquidityMap, liquidity_quality_score


def book(spread_pct, support_floor_pct, mid=100.0):
    return LiquidityMap(pair="TESTGBP", mid_price=mid, spread_pct=spread_pct,
                        support_floor_pct=support_floor_pct)


class SpreadTests(unittest.TestCase):
    def test_a_tight_spread_scores_near_the_top(self):
        self.assertGreater(liquidity_quality_score(book(0.03, 2.5)), 0.9)

    def test_a_punitive_spread_scores_low_even_with_good_support(self):
        """BCH: 0.80% each way turns a 1.6% cost into ~3.2%. No amount of resting support
        makes that a good trade on a GBP 25-50 position."""
        self.assertLess(liquidity_quality_score(book(0.80, 5.0)), 0.4)

    def test_spread_dominates_support(self):
        tight_no_support = liquidity_quality_score(book(0.03, 0.0))
        wide_good_support = liquidity_quality_score(book(0.80, 5.0))
        self.assertGreater(tight_no_support, wide_good_support)

    def test_ranking_follows_real_measured_pairs(self):
        btc = liquidity_quality_score(book(0.034, 2.5))
        dot = liquidity_quality_score(book(0.112, 2.0))
        bch = liquidity_quality_score(book(0.803, 5.0))
        self.assertGreater(btc, dot)
        self.assertGreater(dot, bch)


class SupportTests(unittest.TestCase):
    def test_no_support_underneath_costs_the_coin(self):
        with_support = liquidity_quality_score(book(0.10, 3.0))
        without = liquidity_quality_score(book(0.10, 0.0))
        self.assertGreater(with_support, without)

    def test_an_unestablished_floor_counts_as_no_support_not_as_missing(self):
        """A book too thin to establish a floor is real evidence of poor liquidity, unlike a
        feed that simply did not cover the coin."""
        self.assertIsNotNone(liquidity_quality_score(book(0.10, None)))
        self.assertEqual(
            liquidity_quality_score(book(0.10, None)), liquidity_quality_score(book(0.10, 0.0))
        )


class UnmeasuredTests(unittest.TestCase):
    def test_an_unreadable_book_is_unmeasured_rather_than_bad(self):
        """A Kraken outage must not quietly mark every coin illiquid and stop trading."""
        self.assertIsNone(liquidity_quality_score(None))
        self.assertIsNone(liquidity_quality_score(LiquidityMap(pair="X", mid_price=0.0, spread_pct=0.0)))

    def test_scores_stay_inside_zero_and_one(self):
        for spread in (0.0, 0.05, 0.3, 0.6, 5.0):
            for support in (None, 0.0, 1.5, 10.0):
                value = liquidity_quality_score(book(spread, support))
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_a_missing_adapter_yields_no_liquidity_rather_than_zero(self):
        from ai_trader.operational import _order_book_liquidity

        self.assertIsNone(_order_book_liquidity(None, "BTC"))

    def test_an_adapter_that_raises_does_not_stop_research(self):
        from ai_trader.operational import _order_book_liquidity

        class Broken:
            def order_book(self, pair, **kwargs):
                raise RuntimeError("kraken down")

        self.assertIsNone(_order_book_liquidity(Broken(), "BTC"))


class ScoringIntegrationTests(unittest.TestCase):
    def test_live_book_liquidity_is_preferred_over_the_carried_forward_figure(self):
        import tempfile

        from ai_trader.multi_broker import initialize_multi_broker_schema
        from ai_trader.operational import _crypto_metrics_from_kraken_candles

        candles = [
            {"observation_time": f"2026-07-{index + 1:02d}T00:00:00+00:00",
             "open": 100.0 + index, "high": 101.0 + index, "low": 99.0 + index,
             "close": 100.0 + index, "volume": 1000.0}
            for index in range(40)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "t.db"
            initialize_multi_broker_schema(db_path)
            metrics = _crypto_metrics_from_kraken_candles(
                candles, db_path=db_path, symbol="BTC", order_book_liquidity=0.94
            )
        assert metrics is not None
        self.assertAlmostEqual(metrics["liquidity"], 0.94, places=3)
        self.assertEqual(metrics["reasoning"]["liquidity_carried_forward_from"], "live Kraken order book")


if __name__ == "__main__":
    unittest.main()
