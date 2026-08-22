"""Founder-directed 2026-08-22: Alpaca needs a native trailing stop BEFORE leverage is
enabled on that account.

Until now the whole managed-exit + trailing-stop block was gated to Kraken, so an Alpaca
position had only the fixed bracket stop placed at entry and no trailing protection at all.
A software-side trailing stop can only act while this process is up and the broker is
reachable -- precisely when a leveraged position most needs its exit to already be resting
on the exchange.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.broker_adapters import AlpacaBrokerAdapter
from ai_trader.models import OrderRequest


class FakeAlpacaClient:
    def __init__(self, response=None, raises=None):
        self.requests = []
        self._response = response if response is not None else {"id": "alp-trail-1", "status": "new"}
        self._raises = raises

    def _request(self, method, path, payload=None, data_api=False):
        self.requests.append((method, path, payload))
        if self._raises:
            raise self._raises
        return self._response


def order(qty=10.0, side="sell", client_order_id="trailing-stop-7"):
    return OrderRequest(
        symbol="aapl", side=side, quantity=qty, asset_type="stock", exchange="NASDAQ",
        stop_loss=0, take_profit=0, client_order_id=client_order_id,
    )


class AlpacaTrailingStopTests(unittest.TestCase):
    def test_it_places_a_gtc_native_trailing_stop_with_a_percentage(self):
        client = FakeAlpacaClient()
        result = AlpacaBrokerAdapter(client).place_trailing_stop_order(order(), 0.015)

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["id"], "alp-trail-1")
        method, path, payload = client.requests[0]
        self.assertEqual((method, path), ("POST", "/v2/orders"))
        self.assertEqual(payload["type"], "trailing_stop")
        self.assertEqual(payload["symbol"], "AAPL")
        self.assertEqual(payload["side"], "sell")
        # Alpaca wants a percentage, not the 0.015 fraction the policy stores.
        self.assertEqual(payload["trail_percent"], "1.5")
        self.assertEqual(
            payload["time_in_force"], "gtc",
            "A 'day' exit leg is the 2026-08-12 CSL incident: protective legs expired at the "
            "close and the position sat unprotected for over a month.",
        )

    def test_a_broker_failure_never_raises_into_a_filled_entry(self):
        client = FakeAlpacaClient(raises=RuntimeError("alpaca 503"))
        result = AlpacaBrokerAdapter(client).place_trailing_stop_order(order(), 0.02)

        self.assertEqual(result["status"], "attach_failed")
        self.assertIn("alpaca 503", result["reason"])

    def test_a_response_without_an_order_id_is_not_reported_as_protected(self):
        client = FakeAlpacaClient(response={"status": "new"})
        result = AlpacaBrokerAdapter(client).place_trailing_stop_order(order(), 0.02)

        self.assertEqual(
            result["status"], "attach_failed",
            "Without a real order id nothing can record or cancel this stop later, so it "
            "must never count as attached protection.",
        )

    def test_nonsense_inputs_are_rejected_before_reaching_the_broker(self):
        for trail, qty in ((0.0, 10.0), (-0.01, 10.0), (0.02, 0.0)):
            client = FakeAlpacaClient()
            result = AlpacaBrokerAdapter(client).place_trailing_stop_order(order(qty=qty), trail)
            self.assertEqual(result["status"], "rejected", f"trail={trail} qty={qty}")
            self.assertEqual(client.requests, [], "A rejected order must never hit the broker.")

    def test_the_orchestrator_hook_can_discover_this_adapter(self):
        """The entry hook is capability-based (hasattr), so simply having the method is what
        wires Alpaca into the same path Kraken already uses."""
        self.assertTrue(hasattr(AlpacaBrokerAdapter(FakeAlpacaClient()), "place_trailing_stop_order"))


if __name__ == "__main__":
    unittest.main()
