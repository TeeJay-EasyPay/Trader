"""Founder-requested trade scorecard (2026-08-20): daily/weekly/monthly wins and losses
plus a short lessons line.

The tests that matter most here are the honesty ones. This project has repeatedly shown
the Founder confident-looking figures derived from absent data, so a closed trade with no
reconciled P&L must be reported as `unknown` and must never be folded into "successful".
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.trade_scorecard import (
    deterministic_lessons_line,
    fee_summary,
    explain_trade_outcomes,
    summarize_trade_outcomes,
)


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



class ExplainTradeOutcomesTests(unittest.TestCase):
    """Founder feedback 2026-08-20: the summary must say WHY, not restate the scoreboard."""

    def test_names_fee_drag_as_the_cause_when_fees_swamp_the_winners(self):
        # Modelled on the real live numbers: fees GBP 0.247 against gross winnings GBP 0.107.
        trades = [
            {"exit_time": NOW - DAY, "symbol": "XRP", "gross_pnl": 0.036, "net_pnl": 0.0044, "exchange_fee": 0.0316},
            {"exit_time": NOW - DAY, "symbol": "BCH", "gross_pnl": 0.071, "net_pnl": 0.0386, "exchange_fee": 0.0324},
            {"exit_time": NOW - DAY, "symbol": "SOL", "gross_pnl": -0.181, "net_pnl": -0.240, "exchange_fee": 0.0591},
        ]
        line = explain_trade_outcomes(trades, now_epoch=NOW)
        self.assertIsNotNone(line)
        self.assertIn("fees", line.lower())
        self.assertIn("too small", line.lower(), "Must name the actionable cause, not just report a fee total.")
        self.assertNotIn("made money and", line, "Must not fall back to restating the win/loss count.")

    def test_names_stop_overrun_when_a_trade_lost_more_than_its_planned_risk(self):
        trades = [
            {"exit_time": NOW - DAY, "symbol": "ETH", "gross_pnl": -0.05, "net_pnl": -0.08,
             "exchange_fee": 0.0, "net_r": -2.04, "planned_r": 2.0},
        ]
        line = explain_trade_outcomes(trades, now_epoch=NOW)
        self.assertIsNotNone(line)
        self.assertIn("past their stop", line.lower())
        self.assertIn("ETH", line)
        self.assertIn("2.0x", line)

    def test_returns_none_when_no_driver_is_strong_enough_to_claim(self):
        # Healthy trades with negligible fees: nothing causal to say, so it must NOT invent one.
        trades = [
            {"exit_time": NOW - DAY, "symbol": "BTC", "gross_pnl": 5.0, "net_pnl": 4.99, "exchange_fee": 0.01},
        ]
        self.assertIsNone(explain_trade_outcomes(trades, now_epoch=NOW))

    def test_returns_none_with_no_trades_in_the_window(self):
        self.assertIsNone(explain_trade_outcomes([], now_epoch=NOW))
        old = [{"exit_time": NOW - 60 * DAY, "gross_pnl": 1.0, "net_pnl": 0.1, "exchange_fee": 0.9}]
        self.assertIsNone(explain_trade_outcomes(old, now_epoch=NOW))

    def test_stays_short(self):
        trades = [
            {"exit_time": NOW - DAY, "symbol": "XRP", "gross_pnl": 0.036, "net_pnl": 0.004, "exchange_fee": 0.0316},
        ]
        line = explain_trade_outcomes(trades, now_epoch=NOW)
        # A period between digits is a decimal, not a sentence end.
        sentences = len(re.findall(r"(?<!\d)\.(?:\s|$)", line))
        self.assertLessEqual(sentences, 2, "The Founder asked for one or two sentences.")

    def test_tolerates_junk_rows(self):
        trades = [None, "x", {"exit_time": NOW - DAY, "gross_pnl": "abc", "net_pnl": None, "exchange_fee": "z"}]
        explain_trade_outcomes(trades, now_epoch=NOW)  # must not raise


class FeeSummaryTests(unittest.TestCase):
    """Founder-requested 2026-08-20: track what commission is actually being paid.

    Built from the real Kraken screenshots: 0.80% per leg on Tier 1, confirmed to three
    decimal places on four separate fills.
    """

    def _round_trip(self):
        # One complete ETH trade, both legs, exactly as Kraken reported it.
        return {"exchange_fee": 0.0161 + 0.0157, "quantity": 0.00119932,
                "actual_entry": 1675.10, "actual_exit": 1633.57}

    def test_reports_the_real_tier_one_taker_rate(self):
        got = fee_summary([self._round_trip()])
        self.assertTrue(got["available"])
        self.assertAlmostEqual(got["fee_pct_per_leg"], 0.80, places=1)
        self.assertAlmostEqual(got["fee_pct_round_trip"], 1.60, places=1)

    def test_break_even_move_equals_the_round_trip_cost(self):
        got = fee_summary([self._round_trip()])
        self.assertEqual(got["break_even_move_pct"], got["fee_pct_round_trip"])

    def test_per_leg_and_round_trip_are_never_confused(self):
        """The exact mistake made earlier today: a round-trip fee quoted against one leg."""
        got = fee_summary([self._round_trip()])
        self.assertAlmostEqual(got["fee_pct_round_trip"], got["fee_pct_per_leg"] * 2, places=6)

    def test_says_so_honestly_when_there_is_nothing_to_measure(self):
        got = fee_summary([])
        self.assertFalse(got["available"])
        self.assertEqual(got["trades_counted"], 0)
        self.assertIn("No settled trade", got["reason"])

    def test_plain_english_avoids_jargon_and_states_both_numbers(self):
        text = fee_summary([self._round_trip()])["plain_english"]
        self.assertIn("break", text.lower())
        for jargon in ("notional", "maker", "taker", "bps"):
            self.assertNotIn(jargon, text.lower())

    def test_tolerates_junk(self):
        fee_summary([None, "x", {"exchange_fee": "a", "quantity": None}])


if __name__ == "__main__":
    unittest.main()
