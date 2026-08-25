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
