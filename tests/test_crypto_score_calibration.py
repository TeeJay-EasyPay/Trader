"""2026-08-27, Founder-directed: make the crypto score mean something.

Once the fabricated 0.85 bootstrap scores were removed, crypto stopped trading entirely --
0 entries, every candidate rejected on "investment_policy_score_below_minimum". The real
scores topped out at 0.457 against a 0.85 bar, and could not have reached it however good a
coin was, because the composite was broken in three separate places:

  sentiment   No data source existed, so it was a hard 0.0 inside a five-way average -- the
              score asserted that every coin on earth had terrible news when nobody had looked.
  liquidity   Stored as the raw turnover ratio (ETH 0.041), not a 0-1 score. A coin trading 4%
              of its market cap in a day is deeply liquid; the average read it as 4/100.
  momentum    Scaled for +/-100% moves, so a +4% day -- a strong one in crypto -- scored 0.54.

Each is the same mistake: a real signal on a scale that erased it. The Founder's question is
what surfaced it -- "shouldn't liquidity be a part of gauging whether momentum is going to push
and sustain a rally?" It should, and it could not, because 0.041 votes against a coin.

Modelled against the live universe, the composite moves from a meaningless 0.35-0.40 band to a
real 0.48-0.79 ranking that sorts on evidence: SOL 0.788 on a strong trend and deep liquidity,
RAIN 0.536 on turnover of 0.004.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from contextlib import closing

from ai_trader.database import connect
from ai_trader.multi_broker import (
    _MIN_MEASURED_CRYPTO_METRICS,
    initialize_multi_broker_schema,
    record_crypto_research_score,
)
from ai_trader.operational import (
    _MOMENTUM_FULL_SCALE_PCT,
    _TREND_FULL_SCALE_PCT,
    _pct_to_unit_score,
    liquidity_score,
)


class LiquidityScaleTests(unittest.TestCase):
    def test_a_genuinely_liquid_coin_scores_high_not_near_zero(self):
        """ETH turns over ~4% of market cap daily. That is deep liquidity, and the old raw
        ratio scored it 0.041 -- effectively voting that ETH was untradeable."""
        self.assertGreater(liquidity_score(0.0414e9, 1e9), 0.7)

    def test_thin_turnover_still_scores_at_the_floor(self):
        # The end that can actually hurt: you cannot get out of what nobody is trading.
        self.assertEqual(liquidity_score(0.001e9, 1e9), 0.0)

    def test_ranking_follows_real_depth(self):
        thin = liquidity_score(0.004e9, 1e9)     # RAIN
        mid = liquidity_score(0.0414e9, 1e9)     # ETH
        deep = liquidity_score(0.0774e9, 1e9)    # NEAR
        self.assertLess(thin, mid)
        self.assertLess(mid, deep)

    def test_exceptional_turnover_saturates_rather_than_distorting(self):
        self.assertEqual(liquidity_score(0.5e9, 1e9), 1.0)

    def test_missing_inputs_stay_unmeasured_rather_than_scoring_zero(self):
        """The whole disease this audit has been unpicking: unmeasured must never read as bad."""
        self.assertIsNone(liquidity_score(None, 1e9))
        self.assertIsNone(liquidity_score(1e6, None))
        self.assertIsNone(liquidity_score(1e6, 0))


class MomentumScaleTests(unittest.TestCase):
    def test_a_strong_crypto_day_is_no_longer_read_as_neutral(self):
        # SOL's real +4.09% on the day this was found. Old scale: 0.541.
        self.assertGreater(_pct_to_unit_score(4.09, _MOMENTUM_FULL_SCALE_PCT), 0.7)

    def test_a_bad_day_scores_below_neutral_by_the_same_amount(self):
        up = _pct_to_unit_score(4.0, _MOMENTUM_FULL_SCALE_PCT)
        down = _pct_to_unit_score(-4.0, _MOMENTUM_FULL_SCALE_PCT)
        self.assertAlmostEqual(up - 0.5, 0.5 - down, places=4)

    def test_flat_is_still_exactly_neutral(self):
        self.assertEqual(_pct_to_unit_score(0.0, _MOMENTUM_FULL_SCALE_PCT), 0.5)

    def test_the_weekly_trend_uses_a_wider_scale_than_the_daily_one(self):
        """A 4% week is ordinary; a 4% day is not. Same number, different meaning."""
        day = _pct_to_unit_score(4.0, _MOMENTUM_FULL_SCALE_PCT)
        week = _pct_to_unit_score(4.0, _TREND_FULL_SCALE_PCT)
        self.assertGreater(day, week)

    def test_scores_stay_inside_zero_to_one(self):
        for pct in (-500, -8, 0, 8, 500):
            value = _pct_to_unit_score(pct, _MOMENTUM_FULL_SCALE_PCT)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_the_default_scale_is_unchanged_for_existing_callers(self):
        self.assertEqual(_pct_to_unit_score(10.0), 0.55)


class MeasuredOnlyAverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        initialize_multi_broker_schema(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def score(self, **metrics):
        record_crypto_research_score(
            self.db_path, symbol=metrics.pop("symbol", "TEST"), category=None,
            metrics=metrics, source="test",
        )
        with closing(connect(self.db_path)) as conn:
            return conn.execute(
                "SELECT overall_due_diligence_score FROM CRYPTO_RESEARCH_SCORES ORDER BY score_id DESC LIMIT 1"
            ).fetchone()[0]

    def test_an_unmeasured_metric_no_longer_votes_zero_against_the_coin(self):
        """The core fix. A strong coin with no sentiment source used to be dragged from 0.8 to
        0.64 by a metric nobody had measured."""
        strong = dict(technical_trend_score=0.8, momentum_score=0.8, risk_score=0.8, liquidity=0.8)
        self.assertAlmostEqual(self.score(**strong, sentiment=None), 0.8, places=3)

    def test_a_measured_zero_still_counts_against_the_coin(self):
        """Unmeasured and genuinely-terrible must not be treated the same. Awful news is real
        evidence and has to lower the score."""
        strong = dict(technical_trend_score=0.8, momentum_score=0.8, risk_score=0.8, liquidity=0.8)
        with_bad_news = self.score(**strong, sentiment=0.0)
        self.assertLess(with_bad_news, 0.8)
        self.assertAlmostEqual(with_bad_news, 0.64, places=2)

    def test_too_few_measured_metrics_scores_zero_rather_than_looking_strong(self):
        """One lucky number is not a verdict. A coin this thinly evidenced must not trade."""
        self.assertEqual(
            self.score(technical_trend_score=0.95, momentum_score=None, risk_score=None,
                       sentiment=None, liquidity=None),
            0.0,
        )

    def test_the_minimum_is_three_of_five(self):
        self.assertEqual(_MIN_MEASURED_CRYPTO_METRICS, 3)
        exactly_three = self.score(technical_trend_score=0.9, momentum_score=0.9, risk_score=0.9,
                                   sentiment=None, liquidity=None)
        self.assertAlmostEqual(exactly_three, 0.9, places=3)

    def test_an_explicit_overall_score_is_still_respected(self):
        self.assertAlmostEqual(
            self.score(technical_trend_score=0.1, overall_due_diligence_score=0.77), 0.77, places=3
        )

    def test_a_top_coin_can_now_actually_reach_the_bar_to_trade(self):
        """Before this, 0.85 was unreachable by construction -- which is why removing the
        fabricated 0.85 stopped crypto trading outright. An exceptional setup must be able to
        clear it on merit."""
        excellent = self.score(technical_trend_score=0.95, momentum_score=0.9, risk_score=0.85,
                               sentiment=0.85, liquidity=0.95)
        self.assertGreaterEqual(excellent, 0.85)



class StablecoinExclusionTests(unittest.TestCase):
    """2026-08-27, Founder-directed: "stable coins should not be part of the analysis for
    trading."

    They were scoring 0.75 and ranking third in the universe. Not a fault in the maths -- the
    maths was right and the asset is wrong. A stablecoin is engineered to hold one price, so it
    earns a near-perfect risk score (volatility ~0) and a near-perfect liquidity score (it is
    what everything else trades against), with trend and momentum pinned at neutral because it
    never moves. There is no rally to catch; the best outcome of buying one is your money back
    minus 1.6% in round-trip fees.
    """

    def test_the_major_pegged_assets_are_excluded(self):
        from ai_trader.operational import is_stablecoin

        for symbol in ("USDT", "USDC", "DAI", "BUSD", "PYUSD", "FDUSD", "EURC"):
            self.assertTrue(is_stablecoin(symbol), symbol)

    def test_real_tradeable_coins_are_untouched(self):
        from ai_trader.operational import is_stablecoin

        for symbol in ("BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "TAO"):
            self.assertFalse(is_stablecoin(symbol), symbol)

    def test_an_asset_pegged_to_a_volatile_thing_is_still_tradeable(self):
        """WBTC tracks Bitcoin, moves with it, and has a rally to catch. Only
        currency-pegged assets are excluded."""
        from ai_trader.operational import is_stablecoin

        self.assertFalse(is_stablecoin("WBTC"))
        self.assertFalse(is_stablecoin("STETH"))

    def test_pair_and_case_forms_are_recognised(self):
        """The universe uses bare symbols, Kraken uses pairs, and casing varies by source."""
        from ai_trader.operational import is_stablecoin

        for symbol in ("USDTGBP", "usdc", "USDC/USD", "usdt-usd"):
            self.assertTrue(is_stablecoin(symbol), symbol)

    def test_empty_or_missing_input_is_not_treated_as_a_stablecoin(self):
        from ai_trader.operational import is_stablecoin

        for value in (None, "", "   "):
            self.assertFalse(is_stablecoin(value))

    def test_the_kraken_scoring_path_skips_them(self):
        from ai_trader.operational import record_crypto_scores_from_kraken_candles

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            initialize_multi_broker_schema(db_path)
            result = record_crypto_scores_from_kraken_candles(db_path, symbols=["USDT", "USDC"])
            self.assertEqual(result["scored"], 0)
            self.assertEqual(result.get("symbols_scored", []), [])

if __name__ == "__main__":
    unittest.main()


class ConfidenceThresholdTests(unittest.TestCase):
    """2026-08-27, Founder-directed: the bar moved from 0.85 to 0.75.

    0.85 was never calibrated. It matched the FABRICATED bootstrap confidence exactly -- every
    coin was stamped 0.85 -- so the gate passed everything while looking strict, and the
    conviction scaler paid every trade its 50% minimum, which is why Kraken trades came in at
    GBP 25 against a GBP 50 ceiling. Once the fabrication went and the score was calibrated to
    measure real things, the honest range became ~0.69-0.79 and nothing could clear 0.85.
    """

    def test_the_bar_is_reachable_by_the_scores_the_app_now_produces(self):
        from ai_trader.models import AutoTradeConfig

        bar = AutoTradeConfig().min_confidence
        best_observed_today = 0.79  # SOL, modelled against the live universe
        self.assertLessEqual(bar, best_observed_today,
                             "a bar no real coin can reach is not a filter, it is a stop switch")

    def test_the_bar_is_not_so_low_that_anything_qualifies(self):
        from ai_trader.models import AutoTradeConfig

        weakest_observed_today = 0.48
        self.assertGreater(AutoTradeConfig().min_confidence, weakest_observed_today)

    def test_a_marginal_candidate_is_staked_less_than_a_strong_one(self):
        """Lowering the bar must not mean betting the same on a weak case. This is the
        property that makes 0.75 safe rather than reckless."""
        from ai_trader.models import AutoTradeConfig
        from ai_trader.technical_discretion import conviction_scaled_notional

        bar = AutoTradeConfig().min_confidence
        marginal = conviction_scaled_notional(approved_notional=50.0, confidence=bar, min_confidence=bar)
        strong = conviction_scaled_notional(approved_notional=50.0, confidence=0.95, min_confidence=bar)
        self.assertLess(marginal, strong)
        self.assertAlmostEqual(marginal, 25.0, places=2)

    def test_the_environment_can_still_override_the_default(self):
        """The hosting environment must stay authoritative, so the bar can be tightened again
        without a deploy."""
        import os
        from unittest import mock

        from ai_trader.config import load_settings

        with mock.patch.dict(os.environ, {"AUTO_TRADE_MIN_CONFIDENCE": "0.9"}):
            self.assertAlmostEqual(load_settings().auto_trade.min_confidence, 0.9, places=3)


class InvestmentScoreMeasuredOnlyTests(unittest.TestCase):
    """2026-08-27: the same unmeasured-counts-as-zero bug, one layer up.

    calculate_investment_score averaged seven dimensions and scored 0 for any without a data
    source. Measured live, that penalises crypto and nothing else: equities match both a macro
    and a behavioural source, while every crypto symbol matches behavioural but NOT macro,
    because MARKET_THEMES has not been refreshed since 2 July. A crypto proposal was therefore
    scored as though its macro backdrop had been examined and found worthless -- SOL at a real
    0.79 came out at 0.7136 and failed the 0.75 policy gate purely on that absent seventh.
    """

    def proposal(self, confidence=0.79):
        from ai_trader.models import TradeProposal

        return TradeProposal(
            symbol="SOL", side="buy", entry_price=100.0, stop_loss=98.5, take_profit=103.0,
            position_size=1.0, risk_percentage=0.005, confidence_score=confidence,
            news_summary="x", market_sentiment_summary="y", technical_summary="z",
            plain_english_reasoning="w", philosophy_fit=0.85,
        )

    def test_a_missing_dimension_does_not_drag_the_verdict_down(self):
        from unittest import mock

        from ai_trader.foundation import calculate_investment_score, initialize_foundation_schema

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "t.db"
            initialize_foundation_schema(db_path)
            with mock.patch("ai_trader.foundation._macro_context_available", return_value=False), \
                 mock.patch("ai_trader.foundation._behavioural_context_available", return_value=True):
                without_macro = calculate_investment_score(db_path, self.proposal())["overall_confidence"]
            with mock.patch("ai_trader.foundation._macro_context_available", return_value=True), \
                 mock.patch("ai_trader.foundation._behavioural_context_available", return_value=True):
                with_macro = calculate_investment_score(db_path, self.proposal())["overall_confidence"]
        # Missing macro must cost only the certainty of that dimension, not vote zero.
        self.assertGreater(without_macro, 0.75, "an unmeasured dimension must not fail the gate on its own")
        self.assertLess(abs(with_macro - without_macro), 0.05)

    def test_an_all_dimensions_present_score_is_arithmetically_unchanged(self):
        """Equities match every dimension, so this change must not move them at all."""
        from unittest import mock

        from ai_trader.foundation import calculate_investment_score, initialize_foundation_schema

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "t.db"
            initialize_foundation_schema(db_path)
            with mock.patch("ai_trader.foundation._macro_context_available", return_value=True), \
                 mock.patch("ai_trader.foundation._behavioural_context_available", return_value=True):
                score = calculate_investment_score(db_path, self.proposal(0.8))["overall_confidence"]
        conf, policy, risk = 0.8, 0.85, 1 - 0.015
        self.assertAlmostEqual(score, round((conf * 5 + policy + risk) / 7, 4), places=4)
