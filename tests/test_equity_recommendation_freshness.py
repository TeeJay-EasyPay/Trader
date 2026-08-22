"""2026-08-22: Alpaca had not filled a trade since 12 August. Every one of the 40 live
equity recommendations read "Expired. Run new analysis before execution."

Root cause: recommendations aged by WALL CLOCK. The highest-confidence band gets the
SHORTEST life (4h) and is also the only band auto-trade accepts (min_confidence 0.85), while
the US market is shut ~73% of the week. So the only recommendations eligible to trade were
the ones most likely to expire before a market was ever open to trade them in.

Equities now age only while their market is open. Crypto is untouched -- it trades 24/7, so
wall clock already is its market time.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.application.execution_service import _recommendation_freshness
from ai_trader.guardrails import us_equity_market_hours_between


def utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


class MarketHoursElapsedTests(unittest.TestCase):
    # US regular hours are 09:30-16:00 New York = 13:30-20:00 UTC outside DST shifts.
    def test_time_inside_one_session_counts_in_full(self):
        elapsed = us_equity_market_hours_between(utc(2026, 8, 20, 14, 0), utc(2026, 8, 20, 17, 0))
        self.assertEqual(elapsed, timedelta(hours=3))

    def test_the_overnight_gap_does_not_age_a_recommendation(self):
        """THE case that was killing every equity recommendation: created near the close,
        judged the next morning. 17 wall-clock hours, but barely any trading time."""
        overnight = us_equity_market_hours_between(utc(2026, 8, 20, 19, 30), utc(2026, 8, 21, 13, 45))
        self.assertLess(overnight, timedelta(hours=1))
        self.assertGreater(overnight, timedelta(0), "The half hour before close plus the first quarter hour after open is real trading time.")

    def test_a_whole_weekend_contributes_nothing(self):
        # Friday 20:00 UTC (after close) to Monday 13:30 UTC (the open).
        self.assertEqual(
            us_equity_market_hours_between(utc(2026, 8, 21, 20, 30), utc(2026, 8, 24, 13, 30)),
            timedelta(0),
        )

    def test_a_full_trading_day_is_six_and_a_half_hours(self):
        elapsed = us_equity_market_hours_between(utc(2026, 8, 20, 0, 0), utc(2026, 8, 21, 0, 0))
        self.assertEqual(elapsed, timedelta(hours=6, minutes=30))

    def test_degenerate_and_runaway_inputs_are_handled(self):
        self.assertEqual(us_equity_market_hours_between(utc(2026, 8, 20, 15), utc(2026, 8, 20, 15)), timedelta(0))
        self.assertEqual(us_equity_market_hours_between(utc(2026, 8, 20, 16), utc(2026, 8, 20, 15)), timedelta(0))
        # A corrupt/far-future timestamp must not spin the day loop.
        self.assertEqual(
            us_equity_market_hours_between(utc(2020, 1, 1, 15), utc(2030, 1, 1, 15)),
            timedelta(days=30),
        )


class RecommendationFreshnessTests(unittest.TestCase):
    HIGH_CONFIDENCE = 0.9  # 4-hour lifetime, and the only band auto-trade accepts.

    def _freshness(self, created, now, broker):
        with mock.patch("ai_trader.application.execution_service.datetime") as fake:
            fake.now.return_value = now
            fake.fromisoformat = datetime.fromisoformat
            return _recommendation_freshness(created.isoformat(), self.HIGH_CONFIDENCE, broker)

    def test_an_equity_idea_survives_the_overnight_close(self):
        """Created 15:30 ET Thursday, judged 09:45 ET Friday. Under wall-clock ageing this
        was Expired and unexecutable -- the exact live failure."""
        result = self._freshness(utc(2026, 8, 20, 19, 30), utc(2026, 8, 21, 13, 45), "alpaca")
        self.assertNotEqual(result["status"], "Expired")

    def test_an_equity_idea_still_expires_after_four_hours_of_real_trading_time(self):
        """The fix must not make recommendations immortal -- four hours of genuine trading
        time still expires one."""
        result = self._freshness(utc(2026, 8, 20, 14, 0), utc(2026, 8, 21, 17, 0), "alpaca")
        self.assertEqual(result["status"], "Expired")

    def test_crypto_still_ages_on_the_wall_clock(self):
        """Kraken trades continuously, so five wall-clock hours really is five hours in
        which the trade could have been placed."""
        result = self._freshness(utc(2026, 8, 20, 2, 0), utc(2026, 8, 20, 7, 0), "kraken")
        self.assertEqual(result["status"], "Expired")

    def test_an_unknown_broker_keeps_the_old_wall_clock_behaviour(self):
        result = self._freshness(utc(2026, 8, 20, 2, 0), utc(2026, 8, 20, 7, 0), None)
        self.assertEqual(result["status"], "Expired")


if __name__ == "__main__":
    unittest.main()
