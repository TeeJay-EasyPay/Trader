"""2026-08-27, Founder-reported from the live app: four screens, four different numbers.

    Executive Briefing   "13 share trades placed today"
    Executive Briefing   "submitted 5 orders"
    Executive Briefing   "24 orders were actually submitted"
    Portfolio            "Completed today (since midnight)  19"

The true answer was 6. The whole day was four symbols -- SCCO, VMC and NEE bought, MLM, VMC
and NEE sold -- plus six protective legs that never fired.

Three separate causes, all fixed by counting one agreed thing:

  * Brokers store one row per order EVENT. A bracketed buy produces new/held/partial_fill
    (often several)/fill/filled, so counting rows counts paperwork, not decisions.
  * BROKER_TRADE_HISTORY.external_id is unique per event, not per order, so the pre-existing
    "distinct orders" helper counted 22 where the broker had issued 12.
  * A bracket attaches stop-loss and take-profit legs automatically. They are real orders but
    they are not trades the app chose to make, and counting them reports decisions that were
    never taken.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import json

from ai_trader.trade_counting import (
    broker_order_key,
    count_events,
    count_orders_submitted,
    count_trades,
    trade_count_breakdown,
)


def event(order_id, symbol, side, status, **extra):
    """One broker event row, shaped like BROKER_TRADE_HISTORY."""
    return {
        "external_id": f"evt-{order_id}-{status}",  # unique per EVENT, as production is
        "symbol": symbol, "side": side, "status": status,
        "payload_json": json.dumps({"order_id": order_id, "status": status, **extra}),
    }


# The real 27 August day, reduced to its shape: one bracketed buy that filled in stages,
# plus the two protective legs the bracket attached.
BRACKETED_BUY = [
    event("ord-nee-buy", "NEE", "buy", "filled"),
    event("ord-nee-buy", "NEE", "buy", "fill"),
    event("ord-nee-buy", "NEE", "buy", "partial_fill"),
    event("ord-nee-buy", "NEE", "buy", "partial_fill"),
    event("ord-nee-buy", "NEE", "buy", "partial_fill"),
    event("ord-nee-stop", "NEE", "sell", "held"),
    event("ord-nee-target", "NEE", "sell", "new"),
]


class OrderKeyTests(unittest.TestCase):
    def test_the_broker_order_id_beats_the_per_event_external_id(self):
        """The bug in one line: external_id differs on every row of the same order."""
        keys = {broker_order_key(row) for row in BRACKETED_BUY if row["symbol"] == "NEE" and row["side"] == "buy"}
        self.assertEqual(keys, {"ord-nee-buy"})

    def test_falls_back_to_external_id_when_the_payload_has_no_order_id(self):
        self.assertEqual(broker_order_key({"external_id": "abc", "payload_json": "{}"}), "abc")

    def test_a_row_with_no_usable_id_is_counted_alone_not_merged(self):
        """Under-counting real activity is worse than counting one row twice."""
        a, b = {"status": "fill"}, {"status": "fill"}
        self.assertNotEqual(broker_order_key(a), broker_order_key(b))

    def test_unparseable_payload_does_not_crash_the_count(self):
        self.assertEqual(broker_order_key({"external_id": "x", "payload_json": "not json"}), "x")

    def test_a_kraken_style_list_txid_takes_its_first_element(self):
        self.assertEqual(broker_order_key({"payload_json": json.dumps({"txid": ["OABC-1", "OABC-2"]})}), "OABC-1")


class CountingTests(unittest.TestCase):
    def test_one_bracketed_buy_is_one_trade_not_seven_rows(self):
        self.assertEqual(count_events(BRACKETED_BUY), 7)
        self.assertEqual(count_orders_submitted(BRACKETED_BUY), 3)
        self.assertEqual(count_trades(BRACKETED_BUY), 1)

    def test_unfired_protective_legs_are_orders_but_not_trades(self):
        """They are real orders the broker holds, but not decisions the app made to trade."""
        legs = [event("ord-stop", "NEE", "sell", "held"), event("ord-target", "NEE", "sell", "new")]
        self.assertEqual(count_orders_submitted(legs), 2)
        self.assertEqual(count_trades(legs), 0)

    def test_a_protective_leg_that_actually_fires_does_count(self):
        fired = [event("ord-stop", "NEE", "sell", "held"), event("ord-stop", "NEE", "sell", "fill")]
        self.assertEqual(count_trades(fired), 1)

    def test_entries_and_exits_can_be_counted_separately(self):
        rows = BRACKETED_BUY + [event("ord-mlm-exit", "MLM", "sell", "fill")]
        self.assertEqual(count_trades(rows, side="buy"), 1)
        self.assertEqual(count_trades(rows, side="sell"), 1)

    def test_no_rows_is_zero_not_an_error(self):
        for empty in ([], None):
            self.assertEqual(count_trades(empty), 0)
            self.assertEqual(count_orders_submitted(empty), 0)

    def test_non_dict_rows_are_ignored_rather_than_counted(self):
        self.assertEqual(count_trades([None, "junk", 42]), 0)

    def test_the_real_27_august_day_reports_six_trades(self):
        """The end-to-end case the Founder actually saw: 3 entries, 3 exits, 6 resting legs."""
        rows = []
        for symbol in ("SCCO", "VMC", "NEE"):
            rows += [
                event(f"{symbol}-buy", symbol, "buy", "filled"),
                event(f"{symbol}-buy", symbol, "buy", "partial_fill"),
                event(f"{symbol}-stop", symbol, "sell", "held"),
                event(f"{symbol}-target", symbol, "sell", "new"),
            ]
        for symbol in ("MLM", "VMC", "NEE"):
            rows.append(event(f"{symbol}-exit", symbol, "sell", "fill"))

        breakdown = trade_count_breakdown(rows)
        self.assertEqual(breakdown["trades"], 6)
        self.assertEqual(breakdown["entries"], 3)
        self.assertEqual(breakdown["exits"], 3)
        self.assertEqual(breakdown["resting_orders"], 6)
        self.assertEqual(breakdown["orders_submitted"], 12)
        self.assertEqual(breakdown["events"], 15)
        # And the figure that was on screen -- raw rows -- is provably not the trade count.
        self.assertNotEqual(breakdown["events"], breakdown["trades"])

    def test_submitted_and_traded_are_deliberately_different_numbers(self):
        """Keeping them distinct is the point: one number used for both is how four
        contradictory figures appeared on one screen."""
        breakdown = trade_count_breakdown(BRACKETED_BUY)
        self.assertGreater(breakdown["orders_submitted"], breakdown["trades"])


class KrakenShapeTests(unittest.TestCase):
    """Kraken nests side inside descr; the counter must see it or every Kraken order looks
    sideless and side-filtered counts silently return zero."""

    def test_side_is_read_from_krakens_nested_descr(self):
        rows = [{
            "external_id": "e1", "symbol": "XBTGBP", "status": "closed",
            "payload_json": json.dumps({"order_id": "OKRAK-1", "descr": {"pair": "XBTGBP", "type": "buy"}}),
        }]
        self.assertEqual(count_trades(rows, side="buy"), 1)
        self.assertEqual(count_trades(rows, side="sell"), 0)


if __name__ == "__main__":
    unittest.main()
