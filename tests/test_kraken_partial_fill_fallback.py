"""2026-09-05 incident, real money: the market fallback re-bought the whole position.

The first live Kraken trade in eleven days placed a post-only limit order for 24.14 XRP.
Over the next five minutes it filled roughly 17.99 XRP in small pieces -- which is simply how
a thin GBP book fills. Kraken reports a partially filled order that is still resting as
"open", the same string as one that has not filled at all, and the poll loop only returned
early on "closed". So when the patience budget expired the order looked untouched: it was
cancelled and a market order was placed for the ORIGINAL 24.14, not the ~6 remaining.

Result: about 42.1 XRP acquired against an authorised 24.14 -- roughly 1.75x the size, with
a stop loss sized for the smaller one, and about GBP 19 more spent than approved.

These tests pin the arithmetic. The one that matters most is
`test_the_fallback_buys_only_the_remainder`.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.broker_adapters import KrakenAdapter
from ai_trader.models import OrderRequest


def _request(quantity: float = 24.1436256, notional: float = 25.0) -> OrderRequest:
    return OrderRequest(
        symbol="XRP", side="buy", quantity=quantity, notional_amount=notional,
        asset_type="crypto", exchange="KRAKEN",
        stop_loss=0.98848969, take_profit=1.24565, client_order_id="test-partial-fill",
    )


class PartialFillFallbackTests(unittest.TestCase):
    REQUESTED = 24.1436256
    NOTIONAL = 25.0
    CHECK = {"volume": REQUESTED, "notional": NOTIONAL}
    LIMIT_RESPONSE = {"status": "accepted", "broker": "kraken", "id": "OFL7X7-37RD4-2LARC6",
                      "order_id": "OFL7X7-37RD4-2LARC6", "pair": "XRPGBP", "side": "buy",
                      "quantity": REQUESTED, "notional": NOTIONAL}

    def _adapter(self, *, fill_states, minimum_notional=1.71):
        """fill_states: the (status, vol_exec) pairs _order_fill_state returns in order."""
        adapter = KrakenAdapter()
        adapter._order_fill_state = mock.Mock(side_effect=fill_states)
        adapter.pair_minimum_notional = mock.Mock(return_value=minimum_notional)
        adapter.current_prices = mock.Mock(return_value={"XRPGBP": {"c": ["1.0371", "1"]}})
        adapter.submitted = []

        def _private(path, payload=None):
            if "AddOrder" in path:
                adapter.submitted.append(payload)
                return {"result": {"txid": ["OBJ3IU-4AUJR-QVTI3Y"], "descr": {}}}
            return {"result": {}}

        adapter._private_request = mock.Mock(side_effect=_private)
        return adapter

    def _run(self, adapter):
        with mock.patch("ai_trader.broker_adapters.time.sleep"), \
             mock.patch("ai_trader.broker_adapters._float_env", side_effect=lambda k, d: 0.0 if "BUDGET" in k else d), \
             mock.patch("ai_trader.broker_adapters._bool_env", return_value=True):
            return adapter._await_fill_or_fallback_to_market(
                "OFL7X7-37RD4-2LARC6", _request(), dict(self.CHECK), "XRPGBP", dict(self.LIMIT_RESPONSE),
            )

    def test_the_fallback_buys_only_the_remainder(self):
        """THE INCIDENT. 17.99 of 24.14 already filled -> the fallback must buy 6.15, not 24.14."""
        adapter = self._adapter(fill_states=[("open", 17.9899)])
        result = self._run(adapter)

        self.assertEqual(len(adapter.submitted), 1, "exactly one market fallback")
        submitted_volume = float(adapter.submitted[0]["volume"])
        self.assertAlmostEqual(submitted_volume, self.REQUESTED - 17.9899, places=4)
        self.assertLess(submitted_volume, 7.0,
                        "buying the original 24.14 on top of a 17.99 fill is the bug this test exists for")

    def test_the_reported_position_is_the_partial_plus_the_fallback(self):
        """Downstream sizes the stop and the ledger off this number, so it must be the whole
        holding -- not just the fallback leg."""
        adapter = self._adapter(fill_states=[("open", 17.9899)])
        result = self._run(adapter)
        self.assertAlmostEqual(result["quantity"], self.REQUESTED, places=4)
        self.assertAlmostEqual(result["patient_limit_filled_quantity"], 17.9899, places=4)
        self.assertAlmostEqual(result["market_fallback_quantity"], self.REQUESTED - 17.9899, places=4)

    def test_nothing_filled_still_buys_the_full_size(self):
        """The ordinary case must be untouched: a patient order that never rested falls back
        to a market order for the whole amount, exactly as before."""
        adapter = self._adapter(fill_states=[("open", 0.0)])
        self._run(adapter)
        self.assertAlmostEqual(float(adapter.submitted[0]["volume"]), self.REQUESTED, places=6)

    def test_a_remainder_below_the_exchange_minimum_places_no_order_at_all(self):
        """24.10 of 24.14 filled leaves about GBP 0.04 -- below Kraken's own minimum. Submitting
        it would be an order known to fail, so the partial fill is simply reported as the
        position."""
        adapter = self._adapter(fill_states=[("open", 24.10)], minimum_notional=1.71)
        result = self._run(adapter)
        self.assertEqual(adapter.submitted, [], "no order should be sent for an untradeable remainder")
        self.assertTrue(result["patient_limit_partially_filled"])
        self.assertAlmostEqual(result["quantity"], 24.10, places=4)

    def test_a_fill_completing_between_the_last_poll_and_the_cancel_places_no_order(self):
        """The order stays live through the cancel round trip. If it completed in that gap the
        fallback must not fire -- re-reading after cancelling is what catches this.

        The clock is driven so the poll loop runs exactly once: it sees 20.0 filled, then the
        post-cancel read sees the order complete.
        """
        adapter = self._adapter(fill_states=[("open", 20.0), ("open", self.REQUESTED)])
        with mock.patch("ai_trader.broker_adapters.time.sleep"), \
             mock.patch("ai_trader.broker_adapters.time.monotonic", side_effect=[0.0, 0.0, 999.0]), \
             mock.patch("ai_trader.broker_adapters._float_env", side_effect=lambda k, d: 60.0 if "BUDGET" in k else d), \
             mock.patch("ai_trader.broker_adapters._bool_env", return_value=True):
            result = adapter._await_fill_or_fallback_to_market(
                "OFL7X7-37RD4-2LARC6", _request(), dict(self.CHECK), "XRPGBP", dict(self.LIMIT_RESPONSE),
            )
        self.assertEqual(adapter.submitted, [], "the position is already complete")
        self.assertTrue(result["patient_limit_fully_filled_before_fallback"])

    def test_a_fully_filled_limit_order_returns_without_a_fallback(self):
        adapter = self._adapter(fill_states=[("closed", self.REQUESTED)])
        with mock.patch("ai_trader.broker_adapters.time.sleep"), \
             mock.patch("ai_trader.broker_adapters._float_env", side_effect=lambda k, d: 60.0 if "BUDGET" in k else 0.0), \
             mock.patch("ai_trader.broker_adapters._bool_env", return_value=True):
            result = adapter._await_fill_or_fallback_to_market(
                "OFL7X7-37RD4-2LARC6", _request(), dict(self.CHECK), "XRPGBP", dict(self.LIMIT_RESPONSE),
            )
        self.assertEqual(adapter.submitted, [])
        self.assertEqual(result["order_id"], "OFL7X7-37RD4-2LARC6")


class OrderFillStateTests(unittest.TestCase):
    def test_vol_exec_is_read_alongside_the_status(self):
        """The field that was never read. Without it a partial fill is indistinguishable from
        no fill, which is precisely how the over-buy happened."""
        adapter = KrakenAdapter()
        adapter._private_request = mock.Mock(return_value={
            "result": {"OFL7X7-37RD4-2LARC6": {"status": "open", "vol_exec": "17.9899"}}
        })
        status, filled = adapter._order_fill_state("OFL7X7-37RD4-2LARC6")
        self.assertEqual(status, "open")
        self.assertAlmostEqual(filled, 17.9899, places=4)

    def test_an_unknown_order_reports_no_fill_rather_than_crashing(self):
        adapter = KrakenAdapter()
        adapter._private_request = mock.Mock(return_value={"result": {}})
        self.assertEqual(adapter._order_fill_state("nope"), (None, 0.0))


if __name__ == "__main__":
    unittest.main()
