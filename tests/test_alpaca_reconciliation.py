"""Reconstructing finished Alpaca trades, and proving the reconstruction is real.

2026-09-08. The Founder asked the trading AI whether it was learning anything from Alpaca. It
said it could not tell. The reason turned out to be that PERFORMANCE_ATTRIBUTION -- the
closed-trade table the learning loop reads -- held 27 rows, every one Kraken, and had never held
a single Alpaca row. Two months of paper trading was being thrown away as it happened.

THE TWO WAYS THIS COULD HAVE PRODUCED CONFIDENT NONSENSE, which is why these tests exist:

  1. Alpaca reports each fill as an INCREMENT ("9 filled, 18 to go"). Reading those as running
     totals, or summing a feed that mixes increments with a cumulative row, silently doubles
     every trade. A table of 666-share trades that were really 333 looks perfectly reasonable.

  2. Pairing sells to buys wrongly produces plausible profits for trades that never happened.
     Nothing downstream would notice; the learning loop would simply start learning fiction.

So the pairing is pure and tested here, and the answer is checked against the broker's own
account value in verify_against_account -- realised profit plus the change in unrealised must
equal what the account actually did. On the real data that comes out at $1.97 unexplained
across a month, which is what "this is not fiction" looks like.
"""

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ai_trader.alpaca_reconciliation import (
    collapse_fills,
    pair_round_trips,
    reconcile_alpaca,
    verify_against_account,
)


def fill(order, symbol, side, quantity, price, at, leaves=0):
    return {"order_id": order, "symbol": symbol, "side": side, "quantity": quantity,
            "price": price, "filled_at": at, "leaves_quantity": leaves}


class CollapsingFillsTests(unittest.TestCase):
    """One order out of the several events Alpaca reports for it."""

    def test_payload_projection_names_both_fields_for_postgres(self):
        from ai_trader.alpaca_reconciliation import _alpaca_fill_rows
        class Capture:
            def execute(inner, sql):
                self.assertIn('AS broker_order_id', sql)
                self.assertIn('AS leaves_quantity', sql)
                self.assertNotIn('h.opened_at, h.payload_json,', sql)
                return inner
            def fetchall(inner):
                return []
        self.assertEqual(_alpaca_fill_rows(Capture()), [])

    def test_full_order_profit_replaces_final_increment_estimate_once(self):
        from ai_trader.alpaca_reconciliation import _publish_order_result
        from ai_trader.production_evidence import record_trade_evidence
        orders = collapse_fills([
            fill("entry", "NEE", "buy", 30, 84.04, "t1"),
            fill("exit", "NEE", "sell", 28, 82.72, "t2", leaves=2),
            fill("exit", "NEE", "sell", 1, 82.72, "t3", leaves=1),
            fill("exit", "NEE", "sell", 1, 82.72, "t4", leaves=0),
        ])
        trips, unmatched = pair_round_trips(orders)
        self.assertFalse(unmatched)
        self.assertEqual(trips[0].exit_order_id, "exit")
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            for trade_id in ("first", "duplicate"):
                record_trade_evidence(db, broker="alpaca", event={
                    "order_id": "exit", "trade_id": trade_id, "status": "filled",
                    "symbol": "NEE", "side": "sell", "qty": 1,
                    "filled_avg_price": 82.72, "realized_pnl": -1.04,
                })
            with closing(sqlite3.connect(db)) as conn:
                _publish_order_result(conn, trips[0])
                first_changes = conn.total_changes
                _publish_order_result(conn, trips[0])
                self.assertEqual(conn.total_changes, first_changes)
                rows = conn.execute("SELECT quantity, realized_pnl FROM PRODUCTION_TRADE_EVIDENCE ORDER BY trade_evidence_id").fetchall()
                self.assertEqual(rows[0][0], 30)
                self.assertAlmostEqual(rows[0][1], -39.6)
                self.assertIsNone(rows[1][1])

    def test_the_real_aapl_order_comes_out_as_333_not_666(self):
        """The exact shape from production, 2 July. Alpaca reported this order in eight pieces;
        it is one purchase of 333 shares at 299.328, and reading it as 666 would double a real
        trade and every number computed from it."""
        rows = [
            fill("A", "AAPL", "buy", q, p, f"2026-07-02T13:37:5{i}Z", leaves=1)
            for i, (q, p) in enumerate([(4, 299.35), (152, 299.35), (107, 299.31), (53, 299.30),
                                        (9, 299.30), (6, 299.35), (1, 299.35)])
        ]
        rows.append(fill("A", "AAPL", "buy", 1, 299.35, "2026-07-02T13:37:59Z", leaves=0))
        orders = collapse_fills(rows)
        self.assertEqual(len(orders), 1)
        self.assertAlmostEqual(orders[0].quantity, 333.0)
        self.assertAlmostEqual(orders[0].price, 299.3278, places=3)

    def test_the_price_is_weighted_by_size_not_averaged(self):
        """A plain average of the prices would let a one-share fill count as much as a
        three-hundred-share one."""
        orders = collapse_fills([
            fill("A", "X", "buy", 99, 10.0, "t1", leaves=1),
            fill("A", "X", "buy", 1, 110.0, "t2", leaves=0),
        ])
        self.assertAlmostEqual(orders[0].price, 11.0)

    def test_separate_orders_stay_separate(self):
        orders = collapse_fills([
            fill("A", "X", "buy", 5, 10.0, "t1"),
            fill("B", "X", "buy", 5, 20.0, "t2"),
        ])
        self.assertEqual(len(orders), 2)

    def test_an_order_still_working_is_marked_rather_than_trusted(self):
        """Its quantity is real but not final. Treating a half-filled order as a finished one
        would pair a position that is still being built."""
        orders = collapse_fills([fill("A", "X", "buy", 5, 10.0, "t1", leaves=15)])
        self.assertTrue(orders[0].incomplete)

    def test_a_fill_with_no_order_id_is_dropped_not_guessed_at(self):
        self.assertEqual(collapse_fills([fill("", "X", "buy", 5, 10.0, "t1")]), [])

    def test_orders_come_back_in_the_order_they_happened(self):
        """FIFO pairing depends on it, and the database returns rows in whatever order it
        likes."""
        orders = collapse_fills([
            fill("B", "X", "buy", 1, 10.0, "2026-09-02T00:00:00Z"),
            fill("A", "X", "buy", 1, 10.0, "2026-09-01T00:00:00Z"),
        ])
        self.assertEqual([o.order_id for o in orders], ["A", "B"])


class PairingTests(unittest.TestCase):
    """Matching sells back to the buys they closed."""

    def _orders(self, *rows):
        return collapse_fills([fill(*row) for row in rows])

    def test_a_simple_round_trip(self):
        trips, unmatched = pair_round_trips(self._orders(
            ("A", "MDT", "buy", 27, 91.367, "2026-09-01T15:06:11Z"),
            ("B", "MDT", "sell", 27, 93.010, "2026-09-02T13:38:13Z"),
        ))
        self.assertEqual(len(trips), 1)
        self.assertEqual(unmatched, [])
        self.assertAlmostEqual(trips[0].profit_loss, 44.37, places=1)
        self.assertEqual(trips[0].opened_at, "2026-09-01T15:06:11Z")
        self.assertEqual(trips[0].closed_at, "2026-09-02T13:38:13Z")

    def test_oldest_shares_are_sold_first(self):
        """FIFO, the ordinary convention and the only one checkable against a broker that
        reports positions rather than lots."""
        trips, _ = pair_round_trips(self._orders(
            ("A", "X", "buy", 10, 100.0, "t1"),
            ("B", "X", "buy", 10, 200.0, "t2"),
            ("C", "X", "sell", 10, 150.0, "t3"),
        ))
        self.assertAlmostEqual(trips[0].entry_price, 100.0)
        self.assertAlmostEqual(trips[0].profit_loss, 500.0)

    def test_a_sell_spanning_two_purchases_is_one_finished_trade(self):
        """"I bought this and later sold it" is one trade in the Founder's terms. Splitting it
        per lot would inflate every count of how often the system trades."""
        trips, _ = pair_round_trips(self._orders(
            ("A", "X", "buy", 10, 100.0, "t1"),
            ("B", "X", "buy", 10, 120.0, "t2"),
            ("C", "X", "sell", 20, 130.0, "t3"),
        ))
        self.assertEqual(len(trips), 1)
        self.assertEqual(trips[0].lots, 2)
        self.assertAlmostEqual(trips[0].entry_price, 110.0)
        self.assertAlmostEqual(trips[0].profit_loss, 400.0)
        self.assertEqual(trips[0].opened_at, "t1", "the holding period starts at the first lot")

    def test_selling_half_leaves_the_rest_open(self):
        trips, unmatched = pair_round_trips(self._orders(
            ("A", "X", "buy", 10, 100.0, "t1"),
            ("B", "X", "sell", 4, 110.0, "t2"),
        ))
        self.assertAlmostEqual(trips[0].quantity, 4.0)
        self.assertAlmostEqual(trips[0].profit_loss, 40.0)
        self.assertEqual(unmatched, [], "six shares still held is not a fault")

    def test_shares_still_held_produce_no_trade_at_all(self):
        """An open position has no result yet, and inventing one is how a learning loop gets
        taught that unfinished trades were wins."""
        trips, unmatched = pair_round_trips(self._orders(("A", "X", "buy", 10, 100.0, "t1")))
        self.assertEqual(trips, [])
        self.assertEqual(unmatched, [])

    def test_a_sell_with_no_purchase_behind_it_is_reported_not_priced(self):
        """This is the fault that ended the first attempt: pairing our own ledger produced
        twelve of these, and the account check then missed by $493."""
        trips, unmatched = pair_round_trips(self._orders(("A", "X", "sell", 10, 100.0, "t1")))
        self.assertEqual(trips, [])
        self.assertEqual(len(unmatched), 1)
        self.assertIn("no recorded purchase", unmatched[0]["reason"])

    def test_selling_more_than_was_bought_keeps_the_real_half_and_reports_the_rest(self):
        trips, unmatched = pair_round_trips(self._orders(
            ("A", "X", "buy", 4, 100.0, "t1"),
            ("B", "X", "sell", 10, 110.0, "t2"),
        ))
        self.assertAlmostEqual(trips[0].quantity, 4.0)
        self.assertAlmostEqual(unmatched[0]["quantity"], 6.0)
        self.assertTrue(trips[0].incomplete)

    def test_one_share_cannot_pay_for_another(self):
        """Lots are per symbol. Without that, a profitable AAPL sale could be matched against a
        cheap NKE purchase and produce a wonderful, entirely imaginary result."""
        trips, unmatched = pair_round_trips(self._orders(
            ("A", "AAPL", "buy", 10, 300.0, "t1"),
            ("B", "NKE", "sell", 10, 40.0, "t2"),
        ))
        self.assertEqual(trips, [])
        self.assertEqual(len(unmatched), 1)

    def test_a_position_rebuilt_after_being_sold_starts_a_new_trade(self):
        """SCCO and DAL both did this in production -- sold out, bought back in, sold again."""
        trips, _ = pair_round_trips(self._orders(
            ("A", "X", "buy", 10, 100.0, "t1"),
            ("B", "X", "sell", 10, 110.0, "t2"),
            ("C", "X", "buy", 10, 105.0, "t3"),
            ("D", "X", "sell", 10, 115.0, "t4"),
        ))
        self.assertEqual(len(trips), 2)
        self.assertAlmostEqual(trips[1].entry_price, 105.0)


class WritingTests(unittest.TestCase):
    """The database half: what gets written, and what happens when it runs twice."""

    def _seed(self, db_path):
        with closing(sqlite3.connect(db_path)) as conn:
            with conn:
                conn.execute("""CREATE TABLE BROKER_TRADE_HISTORY (
                    trade_history_id INTEGER PRIMARY KEY, broker TEXT, external_id TEXT,
                    symbol TEXT, side TEXT, quantity REAL, price REAL, status TEXT,
                    opened_at TEXT, payload_json TEXT)""")
                conn.execute("""CREATE TABLE LOGICAL_TRADE_FILLS (
                    fill_id INTEGER PRIMARY KEY, broker_fill_id TEXT, logical_trade_id TEXT, broker TEXT)""")
                conn.execute("""CREATE TABLE LOGICAL_TRADES (
                    logical_trade_id TEXT, proposal_id TEXT, broker TEXT)""")
                conn.execute('CREATE TABLE LOGICAL_TRADE_EVENTS (logical_trade_id TEXT, broker_order_id TEXT)')
                conn.execute("""CREATE TABLE PERFORMANCE_ATTRIBUTION (
                    attribution_id INTEGER PRIMARY KEY, created_at TEXT, proposal_id TEXT,
                    broker TEXT, symbol TEXT, asset_type TEXT, side TEXT, entry_price REAL,
                    exit_price REAL, quantity REAL, profit_loss REAL, opened_at TEXT,
                    closed_at TEXT, holding_period_seconds REAL, entry_reason TEXT,
                    exit_reason TEXT, primary_factors_json TEXT)""")
                conn.execute("""CREATE TABLE TRADE_AUDIT (
                    proposal_id TEXT, event_type TEXT, payload_json TEXT)""")
                conn.execute("""CREATE TABLE PRODUCTION_BROKER_SNAPSHOTS (
                    captured_at TEXT, broker TEXT, portfolio_value REAL, cash REAL,
                    positions_json TEXT)""")
                for i, (ext, sym, side, qty, price, at, leaves) in enumerate([
                    ("f1", "MDT", "buy", 9, 91.38, "2026-09-01T15:06:10Z", 18),
                    ("f2", "MDT", "buy", 18, 91.36, "2026-09-01T15:06:11Z", 0),
                    ("f3", "MDT", "sell", 27, 93.01, "2026-09-02T13:38:13Z", 0),
                ]):
                    conn.execute(
                        "INSERT INTO BROKER_TRADE_HISTORY (broker, external_id, symbol, side, "
                        "quantity, price, status, opened_at, payload_json) "
                        "VALUES ('alpaca', ?, ?, ?, ?, ?, 'fill', ?, ?)",
                        (ext, sym, side, qty, price, at,
                         json.dumps({"order_id": f"order-{side}", "leaves_qty": str(leaves)})),
                    )

    def test_a_finished_trade_is_written_with_its_profit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            self._seed(db)
            result = reconcile_alpaca(db)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["written"], 1)
            with closing(sqlite3.connect(db)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM PERFORMANCE_ATTRIBUTION").fetchone()
            self.assertEqual(row["broker"], "alpaca")
            self.assertEqual(row["symbol"], "MDT")
            self.assertEqual(row["asset_type"], "stock")
            self.assertAlmostEqual(row["quantity"], 27.0)
            self.assertAlmostEqual(row["profit_loss"], 44.37, places=1)

    def test_running_it_again_writes_nothing_new(self):
        """It runs every cycle. Without this the table fills with copies and every average
        computed from it drifts."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            self._seed(db)
            reconcile_alpaca(db)
            second = reconcile_alpaca(db)
            self.assertEqual(second["written"], 0)
            self.assertEqual(second["already_recorded"], 1)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM PERFORMANCE_ATTRIBUTION").fetchone()[0], 1)

    def test_a_missing_rationale_is_said_plainly_rather_than_invented(self):
        """A constant string here is what taught the Kraken learning loop nothing for weeks --
        every trade grouped into one bucket. Better to record that it is unknown."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            self._seed(db)
            reconcile_alpaca(db)
            with closing(sqlite3.connect(db)) as conn:
                row = conn.execute(
                    "SELECT entry_reason, exit_reason FROM PERFORMANCE_ATTRIBUTION").fetchone()
            self.assertIn("not recorded", row[0].lower())
            self.assertIn("not recorded", row[1].lower())

    def test_a_broken_database_reports_rather_than_raising(self):
        """This runs inside a trading cycle. It must never be able to stop one."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(reconcile_alpaca(Path(tmp))["status"], "failed")

    def test_existing_outcome_recovers_exact_entry_order_link_and_stop_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'audit.sqlite3'
            self._seed(db)
            self.assertEqual(reconcile_alpaca(db)['status'], 'completed')
            with closing(sqlite3.connect(db)) as c:
                with c:
                    c.execute("INSERT INTO LOGICAL_TRADES VALUES ('logical', 'proposal', 'alpaca')")
                    c.execute("INSERT INTO LOGICAL_TRADE_EVENTS VALUES ('logical', 'order-buy')")
                    c.execute("INSERT INTO BROKER_TRADE_HISTORY (broker,external_id,status,payload_json) VALUES ('alpaca','order-sell','filled','{\"type\":\"stop\"}')")
            self.assertEqual(reconcile_alpaca(db)['status'], 'completed')
            with closing(sqlite3.connect(db)) as c:
                row = c.execute('SELECT proposal_id,exit_reason,primary_factors_json FROM PERFORMANCE_ATTRIBUTION').fetchone()
            self.assertEqual(row[0], 'proposal')
            self.assertEqual(row[1], 'Broker stop order filled.')
            self.assertEqual(json.loads(row[2])['exit_evidence']['order_id'], 'order-sell')


class AccountCheckTests(unittest.TestCase):
    """The check the trading AI insisted on, and it was right to."""

    def _seed(self, db_path, *, realised, first_unrealised, last_unrealised, first_value,
              last_value):
        with closing(sqlite3.connect(db_path)) as conn:
            with conn:
                conn.execute("""CREATE TABLE PERFORMANCE_ATTRIBUTION (
                    broker TEXT, profit_loss REAL, closed_at TEXT)""")
                conn.execute("""CREATE TABLE PRODUCTION_BROKER_SNAPSHOTS (
                    captured_at TEXT, broker TEXT, portfolio_value REAL, cash REAL,
                    positions_json TEXT)""")
                conn.execute(
                    "INSERT INTO PERFORMANCE_ATTRIBUTION VALUES ('alpaca', ?, '2026-08-20')",
                    (realised,))
                for at, value, unrealised in (("2026-08-09", first_value, first_unrealised),
                                              ("2026-09-08", last_value, last_unrealised)):
                    conn.execute(
                        "INSERT INTO PRODUCTION_BROKER_SNAPSHOTS VALUES (?, 'alpaca', ?, 0, ?)",
                        (at, value, json.dumps([{"symbol": "X", "unrealized_pl": unrealised}])))

    def test_open_positions_are_part_of_the_answer_not_noise(self):
        """The whole point of the trader's objection. Realised alone would call this a $600
        error; with the open positions it balances exactly."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            self._seed(db, realised=569.35, first_unrealised=0.0, last_unrealised=-619.14,
                       first_value=101881.0, last_value=101831.21)
            result = verify_against_account(db)
            self.assertEqual(result["status"], "measured")
            self.assertAlmostEqual(result["realised_profit_loss"], 569.35, places=2)
            self.assertAlmostEqual(result["unrealised_change"], -619.14, places=2)
            self.assertAlmostEqual(result["unexplained"], 0.0, places=1)

    def test_a_pairing_that_invents_profit_shows_up_as_unexplained(self):
        """The failure this exists to catch: numbers that look fine in the table and do not
        add up against the broker."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            self._seed(db, realised=5000.0, first_unrealised=0.0, last_unrealised=0.0,
                       first_value=101881.0, last_value=101831.21)
            self.assertLess(verify_against_account(db)["unexplained"], -4000)

    def test_it_says_so_rather_than_guessing_when_there_is_nothing_to_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            self._seed(db, realised=0.0, first_unrealised=0.0, last_unrealised=0.0,
                       first_value=1.0, last_value=1.0)
            with closing(sqlite3.connect(db)) as conn:
                with conn:
                    conn.execute("DELETE FROM PRODUCTION_BROKER_SNAPSHOTS WHERE captured_at='2026-09-08'")
            self.assertEqual(verify_against_account(db)["status"], "insufficient_snapshots")


if __name__ == "__main__":
    unittest.main()
