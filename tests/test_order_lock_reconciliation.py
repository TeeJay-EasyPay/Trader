"""2026-08-26 audit finding: 16 order-intent locks sat unsettled, the oldest from 10 August.

A lock is taken immediately before submission and only cleared on a definite synchronous
rejection -- deliberately, because an unknown outcome might mean the order WAS placed, and
clearing it blind risks resubmitting a live position with real money. Any run that dies
mid-submission therefore strands a lock forever, and that proposal can never be retried.

Checking the brokers showed the 16 were three different situations: five Alpaca orders that
had actually FILLED (NUE, MLM, VMC, FSLR, NEE) and were simply never advanced past
pending_new, three Kraken locks from 13 August with no order at the broker at all, and the
rest still genuinely working. Blanket-clearing would have been wrong for the first group.
"""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.broker_adapters import _userref
from ai_trader.multi_broker import initialize_multi_broker_schema
from ai_trader.order_lock_reconciliation import reconcile_order_intent_locks, unsettled_locks


def _lock(db_path, broker, client_order_id, symbol, status="locked"):
    initialize_multi_broker_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """INSERT INTO ORDER_INTENT_LOCKS
                   (created_at, broker, client_order_id, symbol, side, notional, status, result_order_id, notes)
                   VALUES ('2026-08-13T13:40:08+00:00', ?, ?, ?, 'buy', 25.0, ?, NULL, 'test')""",
                (broker, client_order_id, symbol, status),
            )


class _Adapter:
    def __init__(self, orders):
        self._orders = orders

    def get_orders(self):
        return self._orders


class _UnreachableAdapter:
    def get_orders(self):
        raise RuntimeError("broker unreachable")


class OrderLockReconciliationTests(unittest.TestCase):
    def test_a_filled_order_settles_its_lock_rather_than_releasing_it(self):
        """The Alpaca case: the order succeeded, the lock just never caught up. Releasing it
        would invite a duplicate of a position that already exists."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _lock(db_path, "alpaca", "ord-nue-1", "NUE", status="pending_new")
            adapters = {"alpaca": _Adapter([
                {"client_order_id": "ord-nue-1", "status": "filled", "id": "broker-123"},
            ])}

            result = reconcile_order_intent_locks(db_path, adapters)

            self.assertEqual(result["settled"], 1)
            self.assertEqual(result["released"], 0)
            self.assertEqual(unsettled_locks(db_path), [])

    def test_no_order_at_the_broker_releases_the_lock(self):
        """The Kraken case: locked before submission, process died, nothing was ever sent --
        so the proposal can safely be retried."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _lock(db_path, "kraken", "ord-sol-1", "SOL")
            adapters = {"kraken": _Adapter([])}

            result = reconcile_order_intent_locks(db_path, adapters)

            self.assertEqual(result["released"], 1)
            self.assertEqual(unsettled_locks(db_path), [])

    def test_a_live_order_is_left_strictly_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _lock(db_path, "alpaca", "ord-live-1", "AAPL", status="pending_new")
            adapters = {"alpaca": _Adapter([
                {"client_order_id": "ord-live-1", "status": "new", "id": "broker-999"},
            ])}

            result = reconcile_order_intent_locks(db_path, adapters)

            self.assertEqual(result["still_working"], 1)
            self.assertEqual(result["released"], 0)
            self.assertEqual(len(unsettled_locks(db_path)), 1, "a working order must keep its lock")

    def test_an_unreachable_broker_releases_nothing(self):
        """Silence is not evidence of absence. This is the rule that keeps the whole thing
        safe: a lock that cannot be checked stays exactly where it is."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _lock(db_path, "kraken", "ord-unknown-1", "XLM")
            adapters = {"kraken": _UnreachableAdapter()}

            result = reconcile_order_intent_locks(db_path, adapters)

            self.assertEqual(result["unreachable"], 1)
            self.assertEqual(result["released"], 0)
            self.assertEqual(len(unsettled_locks(db_path)), 1)

    def test_a_missing_adapter_releases_nothing_either(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _lock(db_path, "kraken", "ord-noadapter-1", "XLM")

            result = reconcile_order_intent_locks(db_path, {})

            self.assertEqual(result["released"], 0)
            self.assertEqual(len(unsettled_locks(db_path)), 1)

    def test_kraken_orders_are_matched_by_userref_since_they_carry_no_client_order_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            client_order_id = "ord-kraken-42"
            _lock(db_path, "kraken", client_order_id, "XBT")
            adapters = {"kraken": _Adapter([
                {"userref": _userref(client_order_id), "status": "closed", "txid": "OABC-123"},
            ])}

            result = reconcile_order_intent_locks(db_path, adapters)

            self.assertEqual(result["settled"], 1, "a Kraken order must be matched by its userref")
            self.assertEqual(result["released"], 0)


if __name__ == "__main__":
    unittest.main()
