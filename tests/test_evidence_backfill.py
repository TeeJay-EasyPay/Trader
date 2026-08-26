"""2026-08-26 audit finding: broker fills that never became evidence rows.

Measured on production: Kraken 270 history rows against 68 evidence rows, Alpaca 118
against 80 -- 240 fills missing, including the LTCGBP maker buy that is the only proof the
maker-fee fix works (fee 0.09957 on cost 24.89 = 0.400%, with Kraken's own maker flag True).
The fee data sat in BROKER_TRADE_HISTORY the whole time; the table every cost analysis reads
never received it, so the round trip still showed 1.56% when the buy leg had already halved.

Cause is structural: evidence was written only for rows the change detector called "new", so
anything it missed was missed forever. A detector that must be perfect for all time is the
wrong shape; reconciling the two tables directly is not.
"""

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.multi_broker import initialize_multi_broker_schema
from ai_trader.production_evidence import backfill_missing_trade_evidence

# The real payload shape Kraken returned for the maker buy.
MAKER_BUY = {
    "id": "TKR-MAKER-1", "trade_id": "TKR-MAKER-1", "ordertxid": "OKR-1", "pair": "LTCGBP",
    "type": "buy", "status": "filled", "vol": "0.67324254", "price": "36.97502",
    "cost": "24.89316", "fee": "0.09957", "maker": True, "time": 1787702509.30039,
    "updated_at": "2026-08-25T22:52:12+00:00", "kraken_record_type": "trade_fill",
}


def _history_row(db_path, broker, payload):
    initialize_multi_broker_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """INSERT INTO BROKER_TRADE_HISTORY
                   (broker, external_id, symbol, side, status, opened_at, closed_at, updated_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (broker, payload["id"], payload.get("pair"), payload.get("type"), payload.get("status"),
                 payload.get("updated_at"), None, payload.get("updated_at"), json.dumps(payload)),
            )


def _evidence_rows(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute(
            "SELECT symbol, side, fee, quantity, price FROM PRODUCTION_TRADE_EVIDENCE"
        ).fetchall()


class EvidenceBackfillTests(unittest.TestCase):
    def test_a_fill_with_no_evidence_row_gets_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _history_row(db_path, "kraken", MAKER_BUY)

            written = backfill_missing_trade_evidence(db_path, broker="kraken")

            self.assertEqual(written, 1)
            rows = _evidence_rows(db_path)
            self.assertEqual(len(rows), 1)
            symbol, side, fee, qty, price = rows[0]
            self.assertEqual(symbol, "LTCGBP")
            self.assertEqual(side, "buy")
            self.assertAlmostEqual(float(fee), 0.09957, places=5)

    def test_the_recovered_fee_shows_the_maker_rate(self):
        """The point of the whole exercise: with the fee present, cost analysis can finally
        see that the buy leg is 0.400% rather than 0.800%."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _history_row(db_path, "kraken", MAKER_BUY)
            backfill_missing_trade_evidence(db_path, broker="kraken")

            _, _, fee, qty, price = _evidence_rows(db_path)[0]
            rate = float(fee) / (float(qty) * float(price)) * 100

            self.assertLess(rate, 0.6, f"expected the maker rate, measured {rate:.3f}%")
            self.assertAlmostEqual(rate, 0.4, places=1)

    def test_running_it_twice_writes_nothing_the_second_time(self):
        """It runs every poll cycle, so it has to be safe to repeat."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _history_row(db_path, "kraken", MAKER_BUY)

            first = backfill_missing_trade_evidence(db_path, broker="kraken")
            second = backfill_missing_trade_evidence(db_path, broker="kraken")

            self.assertEqual(first, 1)
            self.assertEqual(second, 0)
            self.assertEqual(len(_evidence_rows(db_path)), 1)

    def test_it_only_touches_the_broker_it_was_asked_about(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _history_row(db_path, "kraken", MAKER_BUY)
            _history_row(db_path, "alpaca", {**MAKER_BUY, "id": "AL-1", "pair": "FSLR", "type": "buy"})

            backfill_missing_trade_evidence(db_path, broker="kraken")

            rows = _evidence_rows(db_path)
            self.assertEqual([r[0] for r in rows], ["LTCGBP"])

    def test_an_empty_history_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_multi_broker_schema(db_path)

            self.assertEqual(backfill_missing_trade_evidence(db_path, broker="kraken"), 0)


if __name__ == "__main__":
    unittest.main()
