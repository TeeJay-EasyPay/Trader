"""2026-08-27 audit finding: PERFORMANCE_ATTRIBUTION recorded no reason for anything.

All 38 production rows carried the constant "Reconciled from Kraken fills." as BOTH the
entry and the exit reason, and holding_period_seconds was NULL on every one of them.
reporting_service.py builds its lessons by grouping winning trades by entry_reason and
losing trades by exit_reason, so it was grouping 38 trades into a single bucket and
learning nothing -- a column that exists, is populated, and means nothing.

The real rationale was already stored (DUE_DILIGENCE_ASSESSMENTS per proposal,
MANAGED_TRADE_EXITS per exit) and simply never joined to the trade.

The rule these tests hold the code to: recover the real reason where it exists, and say
"not recorded" where it does not. A plausible-sounding invented reason would be worse than
the constant it replaced, because it would look like evidence.
"""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import json
from contextlib import closing

from ai_trader.database import connect
from ai_trader.foundation import initialize_foundation_schema
from ai_trader.multi_broker import initialize_multi_broker_schema
from ai_trader.trade_reasons import (
    LEGACY_PLACEHOLDER,
    UNRECORDED_ENTRY,
    UNRECORDED_EXIT,
    backfill_trade_reasons,
    exit_reasons_by_symbol,
    holding_seconds,
    is_placeholder,
    nearest_exit_reason,
    normalise,
    summarise_entry_reason,
)

REAL_DILIGENCE = {
    "behavioural": "Behavioural review matched against today's benchmark trader research.",
    "fundamental": "CoinGecko/public crypto universe data was not available.",
    "investment_policy": "Policy fit score: 0.85",
    "macro": "Macro review matched against tracked market themes / crypto research scores.",
    "market": "7d trend score 0.62.",
    "technical": "Momentum 0.6, volatility None, liquidity 0.75.",
}


class SummaryTests(unittest.TestCase):
    def test_prefers_the_lines_that_carry_real_numbers(self):
        summary = summarise_entry_reason(REAL_DILIGENCE)
        assert summary is not None
        self.assertIn("Momentum 0.6", summary)
        self.assertIn("7d trend score 0.62", summary)
        self.assertIn("0.85", summary)
        # Pure boilerplate appears on every trade and would crowd out the useful lines.
        self.assertNotIn("Behavioural review matched", summary)

    def test_falls_back_to_boilerplate_rather_than_saying_nothing(self):
        summary = summarise_entry_reason({"macro": "Macro review matched against themes."})
        assert summary is not None
        self.assertIn("Macro", summary)

    def test_empty_or_missing_diligence_yields_none_not_an_invented_reason(self):
        for value in (None, {}, {"technical": "   "}, "not a dict", []):
            self.assertIsNone(summarise_entry_reason(value))

    def test_summary_is_length_capped_so_one_trade_cannot_flood_a_report(self):
        summary = summarise_entry_reason({"technical": "9 " * 800})
        assert summary is not None
        self.assertLessEqual(len(summary), 400)

    def test_the_old_constant_counts_as_no_reason_at_all(self):
        self.assertTrue(is_placeholder(LEGACY_PLACEHOLDER))
        self.assertTrue(is_placeholder(""))
        self.assertTrue(is_placeholder(None))
        self.assertFalse(is_placeholder("Technical: Momentum 0.6"))


class SymbolAndTimingTests(unittest.TestCase):
    def test_kraken_pairs_reduce_to_the_bare_coin(self):
        # PERFORMANCE_ATTRIBUTION held both XRP and XRPGBP for the same coin before this.
        self.assertEqual(normalise("XRPGBP"), "XRP")
        self.assertEqual(normalise("SOLGBP"), "SOL")
        self.assertEqual(normalise("BTC"), "BTC")

    def test_holding_period_is_computed_from_the_timestamps_that_are_present(self):
        opened = "2026-08-20T10:00:00+00:00"
        closed = "2026-08-20T14:30:00+00:00"
        self.assertAlmostEqual(holding_seconds(opened, closed), 4.5 * 3600)

    def test_unusable_or_reversed_timestamps_yield_none_not_a_negative_span(self):
        self.assertIsNone(holding_seconds(None, "2026-08-20T10:00:00+00:00"))
        self.assertIsNone(holding_seconds("not-a-date", "2026-08-20T10:00:00+00:00"))
        # A negative span would poison every "how long do winners run" statistic.
        self.assertIsNone(holding_seconds("2026-08-20T14:00:00+00:00", "2026-08-20T10:00:00+00:00"))


class ExitMatchingTests(unittest.TestCase):
    def setUp(self):
        self.closed = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        self.grouped = {
            "XRP": [
                (self.closed - timedelta(minutes=5), "take_profit_triggered"),
                (self.closed - timedelta(days=90), "stop_loss_triggered"),
            ]
        }

    def test_matches_the_trigger_recorded_closest_to_the_close(self):
        self.assertEqual(
            nearest_exit_reason(self.grouped, "XRPGBP", self.closed.isoformat()),
            "take_profit_triggered",
        )

    def test_a_distant_trigger_for_the_same_coin_is_refused(self):
        """Matching on coin alone would attach a 90-day-old stop-loss to today's exit --
        fiction that looks like evidence."""
        far_future = (self.closed + timedelta(days=30)).isoformat()
        self.assertIsNone(nearest_exit_reason(self.grouped, "XRP", far_future))

    def test_unknown_coin_or_unusable_timestamp_yields_none(self):
        self.assertIsNone(nearest_exit_reason(self.grouped, "DOGE", self.closed.isoformat()))
        self.assertIsNone(nearest_exit_reason(self.grouped, "XRP", None))


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        initialize_multi_broker_schema(self.db_path)
        initialize_foundation_schema(self.db_path)
        self.opened = "2026-08-20T10:00:00+00:00"
        self.closed = "2026-08-20T14:00:00+00:00"
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO DUE_DILIGENCE_ASSESSMENTS (created_at, proposal_id, symbol, asset_type,"
                    " fundamental_status, technical_status, market_status, macro_status,"
                    " behavioural_status, investment_policy_status, overall_status, reasoning_json)"
                    " VALUES (?, ?, ?, 'crypto', 'pass','pass','pass','pass','pass','pass','pass', ?)",
                    (self.opened, "prop-1", "XRP", json.dumps(REAL_DILIGENCE)),
                )
                conn.execute(
                    "INSERT INTO MANAGED_TRADE_EXITS (created_at, updated_at, broker, symbol, side,"
                    " quantity, entry_price, stop_loss, take_profit, status, exit_reason, payload_json)"
                    " VALUES (?, ?, 'kraken', 'XRPGBP', 'sell', 1.0, 1.0, 0.9, 1.2, 'closed', ?, '{}')",
                    (self.opened, self.closed, "take_profit_triggered"),
                )

    def tearDown(self):
        self.tmp.cleanup()

    def add_trade(self, proposal_id, symbol="XRP", entry=LEGACY_PLACEHOLDER, exit_reason=LEGACY_PLACEHOLDER):
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO PERFORMANCE_ATTRIBUTION (
                        created_at, proposal_id, broker, symbol, side, entry_price, exit_price,
                        quantity, profit_loss, opened_at, closed_at, holding_period_seconds,
                        entry_reason, exit_reason, primary_factors_json
                    ) VALUES (?, ?, 'kraken', ?, 'buy', 1.0, 1.1, 1.0, 0.1, ?, ?, NULL, ?, ?, '{}')
                    """,
                    (self.closed, proposal_id, symbol, self.opened, self.closed, entry, exit_reason),
                )

    def stored(self):
        with closing(connect(self.db_path)) as conn:
            return conn.execute(
                "SELECT entry_reason, exit_reason, holding_period_seconds FROM PERFORMANCE_ATTRIBUTION"
                " ORDER BY attribution_id"
            ).fetchall()

    def test_recovers_the_real_entry_reason_exit_trigger_and_holding_period(self):
        self.add_trade("prop-1")
        outcome = backfill_trade_reasons(self.db_path)
        self.assertEqual(outcome["entry_reasons_set"], 1)
        self.assertEqual(outcome["exit_reasons_set"], 1)
        self.assertEqual(outcome["holding_periods_set"], 1)
        entry, exit_reason, holding = self.stored()[0]
        self.assertIn("Momentum 0.6", entry)
        self.assertEqual(exit_reason, "take_profit_triggered")
        self.assertAlmostEqual(holding, 4 * 3600)

    def test_an_unrecoverable_trade_says_so_instead_of_inventing_a_reason(self):
        self.add_trade("prop-missing", symbol="DOGE")
        backfill_trade_reasons(self.db_path)
        entry, exit_reason, _ = self.stored()[0]
        self.assertEqual(entry, UNRECORDED_ENTRY)
        self.assertEqual(exit_reason, UNRECORDED_EXIT)

    def test_never_overwrites_a_reason_that_was_already_real(self):
        self.add_trade("prop-1", entry="Founder override: manual entry", exit_reason="founder_forced_exit")
        backfill_trade_reasons(self.db_path)
        entry, exit_reason, _ = self.stored()[0]
        self.assertEqual(entry, "Founder override: manual entry")
        self.assertEqual(exit_reason, "founder_forced_exit")

    def test_running_it_twice_changes_nothing_the_second_time(self):
        self.add_trade("prop-1")
        backfill_trade_reasons(self.db_path)
        first = self.stored()
        second_outcome = backfill_trade_reasons(self.db_path)
        self.assertEqual(self.stored(), first)
        self.assertEqual(second_outcome["entry_reasons_set"], 0)
        self.assertEqual(second_outcome["holding_periods_set"], 0)

    def test_the_learning_loop_can_finally_tell_two_trades_apart(self):
        """The point of the whole exercise: distinct trades must produce distinct reasons,
        so grouping wins by entry_reason yields more than one bucket."""
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO DUE_DILIGENCE_ASSESSMENTS (created_at, proposal_id, symbol, asset_type,"
                    " fundamental_status, technical_status, market_status, macro_status,"
                    " behavioural_status, investment_policy_status, overall_status, reasoning_json)"
                    " VALUES (?, ?, ?, 'crypto', 'pass','pass','pass','pass','pass','pass','pass', ?)",
                    (self.opened, "prop-2", "BTC", json.dumps({"technical": "Momentum 0.91, liquidity 0.02."})),
                )
        self.add_trade("prop-1")
        self.add_trade("prop-2", symbol="BTC")
        backfill_trade_reasons(self.db_path)
        reasons = {row[0] for row in self.stored()}
        self.assertEqual(len(reasons), 2, "two different trades must not collapse into one reason")

    def test_no_attribution_rows_is_handled_without_error(self):
        self.assertEqual(backfill_trade_reasons(self.db_path)["examined"], 0)


if __name__ == "__main__":
    unittest.main()


class ProductionFormatTests(unittest.TestCase):
    """The two formats production actually held, which the first backfill run exposed:
    all 40 rows recovered 0 exit reasons and 0 holding periods until these were handled."""

    def test_epoch_float_timestamps_are_parsed_not_rejected(self):
        # PERFORMANCE_ATTRIBUTION stored Kraken epoch floats as strings, not ISO -- the same
        # split already found and fixed in BROKER_TRADE_HISTORY.
        self.assertAlmostEqual(holding_seconds("1787162315.152785", "1787173950.17846"), 11635.0257, places=3)

    def test_mixed_epoch_and_iso_still_compare(self):
        from ai_trader.trade_reasons import _parse
        parsed = _parse("1787162315.152785")
        assert parsed is not None
        self.assertEqual(parsed.year, 2026)
        self.assertIsNotNone(_parse("2026-08-19T17:58:35+00:00"))

    def test_a_small_stray_number_is_not_read_as_a_1970_date(self):
        from ai_trader.trade_reasons import _parse
        self.assertIsNone(_parse("42"))
        self.assertIsNone(_parse("0"))

    def test_krakens_xbt_maps_to_the_btc_every_other_table_uses(self):
        # Stripping the quote currency off XBTGBP leaves XBT, which matches nothing.
        self.assertEqual(normalise("XBTGBP"), "BTC")
        self.assertEqual(normalise("XBT"), "BTC")

    def test_exit_matching_tolerates_a_naive_stored_timestamp(self):
        """`a is None != b` chains in Python and silently skipped the awareness check."""
        naive = datetime(2026, 8, 20, 12, 0)
        grouped = {"XRP": [(naive, "take_profit_triggered")]}
        aware = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc).isoformat()
        # Mixed awareness must be refused, not raise.
        self.assertIsNone(nearest_exit_reason(grouped, "XRP", aware))
