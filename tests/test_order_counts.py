"""2026-08-25 Founder-reported: the briefing read "42 orders were actually submitted" on
a day the AI had placed two trades, while the Portfolio card on the same refresh read
"Completed Trades Today: 0" beside a scorecard saying "0 worked / 3 didn't".

Numbers that disagree with each other on one screen are worse than no numbers: the
Founder stops reading the app and asks instead, which is exactly the behaviour this
project is trying to remove.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.autonomous_activity import _distinct_orders


def _event(external_id, status):
    return {"external_id": external_id, "status": status}


class DistinctOrderCountTests(unittest.TestCase):
    def test_one_order_reported_several_times_counts_once(self):
        """BROKER_TRADE_HISTORY stores one row per order EVENT. An order that is accepted
        and then filled is two rows describing one order."""
        rows = [
            _event("KR-1", "accepted"),
            _event("KR-1", "new"),
            _event("KR-2", "submitted"),
        ]

        self.assertEqual(_distinct_orders(rows, {"submitted", "accepted", "new"}), 2)

    def test_a_fill_is_matched_back_to_its_own_order(self):
        rows = [_event("KR-1", "filled"), _event("KR-1", "partially_filled"), _event("KR-2", "filled")]

        self.assertEqual(_distinct_orders(rows, contains="filled"), 2)

    def test_rows_without_an_id_are_counted_individually_not_dropped(self):
        """A row with no external_id is still evidence something happened -- undercounting
        is as dishonest as overcounting."""
        rows = [_event("", "accepted"), _event(None, "accepted"), _event("KR-1", "accepted")]

        self.assertEqual(_distinct_orders(rows, {"accepted"}), 3)

    def test_other_statuses_are_ignored(self):
        rows = [_event("KR-1", "accepted"), _event("KR-2", "closed"), _event("KR-3", "rejected")]

        self.assertEqual(_distinct_orders(rows, {"submitted", "accepted", "new"}), 1)


if __name__ == "__main__":
    unittest.main()


class BrokerOrderIdKeyTests(unittest.TestCase):
    """2026-08-25 Founder-reported: the briefing said "7 broker order or fill event(s)" while
    the Trade History table beneath showed 3 FSLR rows. All seven were one purchase of 13 FSLR
    shares, filled in four pieces, plus its two protective bracket legs -- three real orders.

    The identity was there the whole time: BROKER_TRADE_HISTORY calls it external_id,
    PRODUCTION_TRADE_EVIDENCE calls the same thing broker_order_id. Checking only one name
    meant every evidence row looked like its own separate order.
    """

    def test_evidence_rows_are_grouped_by_broker_order_id(self):
        rows = [
            {"broker_order_id": "f3c36ff1", "status": "accepted"},
            {"broker_order_id": "f3c36ff1", "status": "new"},
            {"broker_order_id": "d87e75ca", "status": "accepted"},
        ]

        self.assertEqual(_distinct_orders(rows, {"submitted", "accepted", "new"}), 2)

    def test_either_name_for_the_same_identity_works(self):
        rows = [
            {"external_id": "kr-1", "status": "accepted"},
            {"broker_order_id": "al-1", "status": "accepted"},
            {"broker_order_id": "al-1", "status": "new"},
        ]

        self.assertEqual(_distinct_orders(rows, {"submitted", "accepted", "new"}), 2)
