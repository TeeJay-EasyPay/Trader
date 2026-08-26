"""2026-08-26 audit finding: BROKER_TRADE_HISTORY held two incompatible timestamp formats
in the same columns.

Measured on the production database:

    kraken: 270 rows, 100% Unix epoch numbers ("1787702509.30039")
    alpaca: 118 rows, 100% ISO dates          ("2026-08-26T16:08:18")

across updated_at, opened_at and closed_at alike -- Kraken reports opentm/closetm as epoch
floats, Alpaca reports ISO strings, and both were simply stringified into a text column.
Because "1787..." sorts before "2026...", every date-filtered query on this table silently
returned Alpaca-only results. Nothing ever errored; Kraken activity just vanished from any
period-scoped view, which is why "Kraken trades since 25 Aug" returned nothing while the
trades plainly existed.
"""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.multi_broker import _iso_timestamp, initialize_multi_broker_schema, record_broker_trade_history


class TimestampFormatTests(unittest.TestCase):
    def test_krakens_epoch_floats_become_iso(self):
        # The exact value found in production.
        self.assertTrue(_iso_timestamp(1787702509.30039).startswith("2026-08-26T"))
        self.assertTrue(_iso_timestamp("1787702509.30039").startswith("2026-08-26T"))

    def test_alpacas_iso_strings_are_left_exactly_alone(self):
        self.assertEqual(_iso_timestamp("2026-08-26T16:08:18"), "2026-08-26T16:08:18")

    def test_milliseconds_are_recognised_too(self):
        self.assertTrue(_iso_timestamp(1787702509300).startswith("2026-08-26T"))

    def test_unrecognisable_values_are_preserved_not_discarded(self):
        """A preserved odd value can be investigated; a dropped one cannot."""
        self.assertEqual(_iso_timestamp("broker-event-without-timestamp"), "broker-event-without-timestamp")
        self.assertEqual(_iso_timestamp(None), "")
        # A small number is a quantity that reached the wrong field, not a date.
        self.assertEqual(_iso_timestamp("42"), "42")

    def test_both_brokers_end_up_filterable_by_the_same_date_range(self):
        """The whole point: one query, both brokers."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_broker_trade_history(db_path, "kraken", [
                {"id": "kr-1", "pair": "XBTGBP", "type": "buy", "status": "closed",
                 "vol": "0.001", "price": "40000", "opentm": 1787702509.30039, "closetm": 1787702600.0},
            ])
            record_broker_trade_history(db_path, "alpaca", [
                {"id": "al-1", "symbol": "FSLR", "side": "buy", "status": "filled",
                 "qty": "13", "price": "207", "updated_at": "2026-08-26T16:08:18"},
            ])

            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    "SELECT broker FROM BROKER_TRADE_HISTORY WHERE updated_at >= '2026-08-26' ORDER BY broker"
                ).fetchall()

            self.assertEqual([r[0] for r in rows], ["alpaca", "kraken"],
                             "a date filter must return both brokers, not silently drop Kraken")

    def test_existing_epoch_rows_are_converted_once_on_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_multi_broker_schema(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        """INSERT INTO BROKER_TRADE_HISTORY
                           (broker, external_id, symbol, side, status, opened_at, closed_at, updated_at, payload_json)
                           VALUES ('kraken','legacy','XBTGBP','buy','closed','1787702509.30039','1787702600.0','1787702509.30039','{}')"""
                    )
            # Force the once-per-process guard to run again for this fresh database.
            import ai_trader.multi_broker as mb
            mb._INITIALIZED_SCHEMA_KEYS.clear()
            initialize_multi_broker_schema(db_path)

            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT updated_at, opened_at, closed_at FROM BROKER_TRADE_HISTORY WHERE external_id='legacy'"
                ).fetchone()

            for value in row:
                self.assertTrue(str(value).startswith("2026-"), f"legacy epoch value not converted: {value}")


if __name__ == "__main__":
    unittest.main()
