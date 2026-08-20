"""Founder-requested trade scorecard (2026-08-20): daily/weekly/monthly wins and losses
plus a short lessons line.

The tests that matter most here are the honesty ones. This project has repeatedly shown
the Founder confident-looking figures derived from absent data, so a closed trade with no
reconciled P&L must be reported as `unknown` and must never be folded into "successful".
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.trade_scorecard import deterministic_lessons_line, summarize_trade_outcomes


NOW = 1_787_200_000.0
HOUR = 3600.0
DAY = 86_400.0


class SummarizeTradeOutcomesTests(unittest.TestCase):
    def test_counts_wins_and_losses_in_each_rolling_window(self):
        trades = [
            {"exit_time": NOW - 2 * HOUR, "net_pnl": 5.0},      # today
            {"exit_time": NOW - 3 * DAY, "net_pnl": -2.0},      # this week
            {"exit_time": NOW - 20 * DAY, "net_pnl": 7.0},      # this month
        ]
        got = summarize_trade_outcomes(trades, now_epoch=NOW)
        self.assertEqual((got["day"]["successful"], got["day"]["unsuccessful"]), (1, 0))
        self.assertEqual((got["week"]["successful"], got["week"]["unsuccessful"]), (1, 1))
        self.assertEqual((got["month"]["successful"], got["month"]["unsuccessful"]), (2, 1))

    def test_a_trade_with_no_reconciled_pnl_is_unknown_not_a_win(self):
        got = summarize_trade_outcomes([{"exit_time": NOW - HOUR, "net_pnl": None}], now_epoch=NOW)
        day = got["day"]
        self.assertEqual(day["unknown"], 1)
        self.assertEqual(day["successful"], 0, "Missing P&L must never be counted as a success.")
        self.assertEqual(day["unsuccessful"], 0)
        self.assertEqual(day["settled"], 0)
        self.assertEqual(day["total"], 1)
        self.assertIsNone(day["win_rate"], "Win rate is undefined with nothing settled, not 0% or 100%.")

    def test_breakeven_is_its_own_category(self):
        got = summarize_trade_outcomes([{"exit_time": NOW - HOUR, "net_pnl": 0.0}], now_epoch=NOW)
        self.assertEqual(got["day"]["breakeven"], 1)
        self.assertEqual(got["day"]["successful"], 0)
        self.assertEqual(got["day"]["unsuccessful"], 0)

    def test_trades_outside_the_window_are_excluded(self):
        got = summarize_trade_outcomes([{"exit_time": NOW - 45 * DAY, "net_pnl": 9.0}], now_epoch=NOW)
        for name in ("day", "week", "month"):
            self.assertEqual(got[name]["total"], 0, f"{name} must exclude a 45-day-old trade.")

    def test_accepts_epoch_seconds_stored_as_a_string(self):
        # KRAKEN_RECONCILED_RESULTS stores exit_time as a string, e.g. '1787173950.17846'.
        got = summarize_trade_outcomes([{"exit_time": str(NOW - HOUR), "net_pnl": 3.0}], now_epoch=NOW)
        self.assertEqual(got["day"]["successful"], 1)

    def test_accepts_iso_timestamps(self):
        got = summarize_trade_outcomes(
            [{"exit_time": "2026-08-20T00:00:00+00:00", "net_pnl": 3.0}], now_epoch=1_787_270_000.0,
        )
        self.assertEqual(got["day"]["successful"], 1)

    def test_an_unparseable_exit_time_is_dropped_not_dated_to_now(self):
        """Dating a bad timestamp to now would silently pull old trades into today."""
        got = summarize_trade_outcomes([{"exit_time": "not-a-date", "net_pnl": 3.0}], now_epoch=NOW)
        self.assertEqual(got["day"]["total"], 0)
        self.assertEqual(got["month"]["total"], 0)

    def test_win_rate_uses_settled_trades_only(self):
        trades = [
            {"exit_time": NOW - HOUR, "net_pnl": 1.0},
            {"exit_time": NOW - HOUR, "net_pnl": -1.0},
            {"exit_time": NOW - HOUR, "net_pnl": None},
        ]
        got = summarize_trade_outcomes(trades, now_epoch=NOW)
        self.assertEqual(got["day"]["win_rate"], 0.5, "The unknown trade must not dilute the win rate.")

    def test_tolerates_junk_rows_without_raising(self):
        got = summarize_trade_outcomes(
            [None, "nonsense", {"exit_time": NOW - HOUR, "net_pnl": "abc"}], now_epoch=NOW,
        )
        self.assertEqual(got["day"]["unknown"], 1)


class LessonsLineTests(unittest.TestCase):
    def test_says_plainly_when_there_is_nothing_to_learn(self):
        line = deterministic_lessons_line(summarize_trade_outcomes([], now_epoch=NOW))
        self.assertIn("nothing to learn", line.lower())

    def test_distinguishes_no_trades_from_unreconciled_trades(self):
        buckets = summarize_trade_outcomes([{"exit_time": NOW - DAY, "net_pnl": None}], now_epoch=NOW)
        line = deterministic_lessons_line(buckets)
        self.assertIn("reconciled", line.lower())

    def test_reports_real_counts_when_trades_have_settled(self):
        trades = [
            {"exit_time": NOW - DAY, "net_pnl": 4.0},
            {"exit_time": NOW - 2 * DAY, "net_pnl": -1.5},
        ]
        line = deterministic_lessons_line(summarize_trade_outcomes(trades, now_epoch=NOW))
        self.assertIn("1 trade(s) made money", line)
        self.assertIn("1 lost money", line)
        self.assertIn("ahead", line)

    def test_stays_to_a_couple_of_sentences(self):
        trades = [{"exit_time": NOW - DAY, "net_pnl": 4.0}]
        line = deterministic_lessons_line(summarize_trade_outcomes(trades, now_epoch=NOW))
        self.assertLessEqual(line.count("."), 2, "The Founder asked for one or two sentences.")


if __name__ == "__main__":
    unittest.main()
