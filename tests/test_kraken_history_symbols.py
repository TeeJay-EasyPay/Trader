"""2026-08-27, found by reading the Trade History table on the emulator.

149 of 391 BROKER_TRADE_HISTORY rows -- every Kraken order, 38% of the table -- had no symbol
and no buy/sell direction, so the table the Founder relies on most rendered
"Not available - source data has not been recorded yet." where the coin name should be.

The data was never missing. Kraken's OpenOrders/ClosedOrders endpoints do not put `pair` and
`type` at the top level of an order the way its trades endpoint does; they sit one level down
in `descr`, and the whole payload was being stored in payload_json all along:

    {"descr": {"pair": "LTCGBP", "type": "sell", "order": "sell 0.673 LTCGBP @ ..."}}

Same shape of bug as the learning loop's decision_context, found the same day: a reader
looking one level too high at a nested payload.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from contextlib import closing

from ai_trader.database import connect
from ai_trader.multi_broker import (
    _descr,
    backfill_broker_history_symbols,
    initialize_multi_broker_schema,
    record_broker_trade_history,
)

# Shaped exactly like a real Kraken open order.
KRAKEN_ORDER = {
    "id": "OYYKZE-LEELQ-4FLO7V",
    "status": "open",
    "opentm": 1787698356.883816,
    "cost": "0.00000",
    "fee": "0.00000",
    "vol": "0.67324254",
    "descr": {
        "pair": "LTCGBP", "type": "sell", "ordertype": "trailing-stop",
        "order": "sell 0.67324254 LTCGBP @ trailing stop +1.5000%",
    },
}

# Kraken's trades endpoint DOES put them at the top level; that path must keep working.
KRAKEN_TRADE = {"id": "T1", "status": "closed", "pair": "XBTGBP", "type": "buy", "vol": "0.01", "price": "46594.4"}


class DescrTests(unittest.TestCase):
    def test_reads_the_nested_block(self):
        self.assertEqual(_descr(KRAKEN_ORDER)["pair"], "LTCGBP")

    def test_a_missing_or_malformed_descr_is_an_empty_dict_not_a_crash(self):
        for item in ({}, {"descr": None}, {"descr": "sell 0.6 LTCGBP"}, {"descr": []}):
            self.assertEqual(_descr(item), {})


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        initialize_multi_broker_schema(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def stored(self):
        with closing(connect(self.db_path)) as conn:
            return conn.execute(
                "SELECT symbol, side FROM BROKER_TRADE_HISTORY ORDER BY trade_history_id"
            ).fetchall()

    def test_an_order_now_records_its_coin_and_direction(self):
        record_broker_trade_history(self.db_path, "kraken", [KRAKEN_ORDER])
        self.assertEqual(self.stored(), [("LTCGBP", "sell")])

    def test_a_top_level_pair_still_wins(self):
        """Kraken's trades endpoint uses the flat shape; that path must not regress."""
        record_broker_trade_history(self.db_path, "kraken", [KRAKEN_TRADE])
        self.assertEqual(self.stored(), [("XBTGBP", "buy")])

    def test_an_order_with_neither_shape_is_still_stored_rather_than_dropped(self):
        # A row with no symbol is worse than one with, but losing the order entirely would
        # be worse still -- the payload is retained either way.
        record_broker_trade_history(self.db_path, "kraken", [{"id": "X", "status": "open"}])
        self.assertEqual(len(self.stored()), 1)


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        initialize_multi_broker_schema(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def add_legacy_row(self, payload, symbol=None, side=None):
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO BROKER_TRADE_HISTORY (broker, external_id, symbol, side, status,"
                    " updated_at, payload_json) VALUES ('kraken', ?, ?, ?, 'open', '2026-08-25', ?)",
                    (payload.get("id"), symbol, side, json.dumps(payload)),
                )

    def stored(self):
        with closing(connect(self.db_path)) as conn:
            return conn.execute(
                "SELECT symbol, side FROM BROKER_TRADE_HISTORY ORDER BY trade_history_id"
            ).fetchall()

    def test_recovers_symbol_and_side_from_the_stored_payload(self):
        """No broker call needed -- the values were kept in payload_json the whole time."""
        self.add_legacy_row(KRAKEN_ORDER)
        outcome = backfill_broker_history_symbols(self.db_path)
        self.assertEqual(outcome["symbols_set"], 1)
        self.assertEqual(outcome["sides_set"], 1)
        self.assertEqual(self.stored(), [("LTCGBP", "sell")])

    def test_never_overwrites_a_symbol_that_is_already_recorded(self):
        self.add_legacy_row(KRAKEN_ORDER, symbol="ALREADY", side="buy")
        backfill_broker_history_symbols(self.db_path)
        self.assertEqual(self.stored(), [("ALREADY", "buy")])

    def test_running_it_twice_changes_nothing_the_second_time(self):
        self.add_legacy_row(KRAKEN_ORDER)
        backfill_broker_history_symbols(self.db_path)
        second = backfill_broker_history_symbols(self.db_path)
        self.assertEqual(second["symbols_set"], 0)
        self.assertEqual(self.stored(), [("LTCGBP", "sell")])

    def test_a_row_whose_payload_genuinely_lacks_the_fields_is_left_alone(self):
        self.add_legacy_row({"id": "X", "status": "open"})
        backfill_broker_history_symbols(self.db_path)
        self.assertEqual(self.stored(), [(None, None)])

    def test_unparseable_payload_does_not_break_the_run(self):
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO BROKER_TRADE_HISTORY (broker, external_id, status, updated_at,"
                    " payload_json) VALUES ('kraken', 'bad', 'open', '2026-08-25', 'not json')"
                )
        self.assertEqual(backfill_broker_history_symbols(self.db_path)["symbols_set"], 0)



class TradeEvidenceSymbolTests(unittest.TestCase):
    """The same nested-descr bug existed in a SECOND table, PRODUCTION_TRADE_EVIDENCE, which
    is what actually feeds the Founder's Trade History card -- 105 of 297 rows blank. Fixing
    only BROKER_TRADE_HISTORY left the screen unchanged, which is how this one was found."""

    def setUp(self):
        from ai_trader.production_evidence import initialize_production_evidence_schema

        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        initialize_production_evidence_schema(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_kraken_order_records_its_coin_and_direction(self):
        from ai_trader.production_evidence import _trade_evidence_values

        values = _trade_evidence_values("kraken", KRAKEN_ORDER)
        self.assertIn("LTCGBP", values)
        self.assertIn("sell", values)

    def test_a_flat_payload_still_wins(self):
        from ai_trader.production_evidence import _trade_evidence_values

        values = _trade_evidence_values("kraken", KRAKEN_TRADE)
        self.assertIn("XBTGBP", values)
        self.assertIn("buy", values)

    def test_backfill_recovers_existing_rows_and_is_idempotent(self):
        from ai_trader.production_evidence import backfill_trade_evidence_symbols

        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO PRODUCTION_TRADE_EVIDENCE (idempotency_key, observed_at, broker,"
                    " status, payload_json) VALUES ('k1', '2026-08-26', 'kraken', 'open', ?)",
                    (json.dumps(KRAKEN_ORDER),),
                )
        first = backfill_trade_evidence_symbols(self.db_path)
        self.assertEqual(first["symbols_set"], 1)
        with closing(connect(self.db_path)) as conn:
            self.assertEqual(
                conn.execute("SELECT symbol, side FROM PRODUCTION_TRADE_EVIDENCE").fetchall(),
                [("LTCGBP", "sell")],
            )
        self.assertEqual(backfill_trade_evidence_symbols(self.db_path)["symbols_set"], 0)

if __name__ == "__main__":
    unittest.main()
