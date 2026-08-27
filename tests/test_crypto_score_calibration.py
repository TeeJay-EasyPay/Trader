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


if __name__ == "__main__":
    unittest.main()
