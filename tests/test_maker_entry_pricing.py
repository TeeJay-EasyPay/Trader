"""2026-08-24: patient limit entries almost never filled, so nearly every buy took the market
fallback and paid the 0.80% taker rate anyway. Confirmed against real Kraken responses --
only 1 of 4 overnight entries stayed a limit:

    KSM 07:43  "buy 8.22439636 KSMGBP @ limit 2.74"          <- rested, maker
    XRP 07:41  fallback_from_unfilled_limit_order_id -> @ market
    LTC 02:37  fallback_from_unfilled_limit_order_id -> @ market

Cause: _limit_entry_price works from the PROPOSAL's entry price, i.e. whatever the market
was doing when research ran, potentially an hour before the order is placed. By order time
the market has moved and the bid sits somewhere irrelevant, so it never fills.

Fix: rest at the LIVE best bid, capped by the proposal price so we never bid more than the
trade was sized against.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ai_trader.broker_adapters as ba
from ai_trader.broker_adapters import KrakenAdapter
from ai_trader.models import OrderRequest

LIVE_ENV = {
    "KRAKEN_API_KEY": "key", "KRAKEN_PRIVATE_KEY": "c2VjcmV0",
    "KRAKEN_AUTO_TRADING": "true", "KRAKEN_LIVE_TRADING_APPROVED": "true",
    "KRAKEN_LIMIT_ENTRIES_ENABLED": "true", "KRAKEN_SUBMIT_REAL_ORDERS": "true",
    "KRAKEN_LIMIT_ENTRY_POLL_INTERVAL_SECONDS": "0.01",
    "KRAKEN_LIMIT_ENTRY_POLL_BUDGET_SECONDS": "0.02",
}


class _Adapter(KrakenAdapter):
    def __init__(self, best_bid_price):
        super().__init__()
        self.calls = []
        self._bid = best_bid_price

    def _public_request(self, path):
        if "Ticker" in path:
            pair = path.split("pair=")[-1]
            return {"result": {pair: {"b": [str(self._bid), "1", "1.0"]}}} if self._bid else {"result": {}}
        pair = path.split("pair=")[-1]
        return {"result": {pair: {"pair_decimals": 3}}}

    def _private_request(self, path, payload=None):
        self.calls.append((path, payload))
        if path == "/0/private/AddOrder":
            return {"result": {"txid": ["OTEST-1"], "descr": {}}}
        return {"result": {"OTEST-1": {"status": "closed"}}}


def order(quantity=3.0, notional=25.0):
    return OrderRequest(
        symbol="LINK", side="buy", quantity=quantity, asset_type="crypto", exchange="KRAKEN",
        stop_loss=7.0, take_profit=10.0, notional_amount=notional, client_order_id="maker-test",
    )


def place(adapter, req):
    with mock.patch.dict(os.environ, LIVE_ENV), \
         mock.patch.object(adapter, "_validate_live_order",
                           return_value={"passed": True, "failures": [], "pair": ba._kraken_pair(req.symbol),
                                         "volume": req.quantity, "notional": req.notional_amount}), \
         mock.patch.object(ba.time, "sleep", return_value=None):
        adapter.place_order(req)
    return adapter.calls[0][1]


class MakerEntryPricingTests(unittest.TestCase):
    # order() implies a proposal price of 25/3 = 8.3333
    PROPOSAL_PRICE = 25.0 / 3.0

    def test_it_rests_at_the_live_bid_when_the_market_has_fallen(self):
        """The case that was failing: market moved since research, so the stale proposal
        price was nowhere near the book and the order never filled."""
        payload = place(_Adapter(best_bid_price=8.0), order())
        self.assertEqual(payload["ordertype"], "limit")
        self.assertLessEqual(float(payload["price"]), 8.0)
        self.assertGreater(
            float(payload["price"]), 7.9,
            "Should rest AT the bid, not far below it -- resting below the book is what "
            "stopped these filling in the first place.",
        )

    def test_it_never_bids_above_the_price_the_trade_was_sized_against(self):
        """Market has run up. Paying more than the proposal price to save 0.40% is
        self-defeating, so the cap binds and the fallback handles it."""
        payload = place(_Adapter(best_bid_price=50.0), order())
        self.assertLessEqual(float(payload["price"]), self.PROPOSAL_PRICE)

    def test_an_unreadable_bid_falls_back_to_the_proposal_price(self):
        """A pricing read must never block the trade; it just loses the improvement."""
        payload = place(_Adapter(best_bid_price=None), order())
        self.assertEqual(payload["ordertype"], "limit")
        self.assertLessEqual(float(payload["price"]), self.PROPOSAL_PRICE)

    def test_the_order_is_still_post_only(self):
        """post-only is what guarantees maker: without it a limit priced at the touch can
        cross and be charged as taker anyway."""
        payload = place(_Adapter(best_bid_price=8.0), order())
        self.assertEqual(payload.get("oflags"), "post")

    def test_the_price_still_respects_the_pairs_decimal_limit(self):
        payload = place(_Adapter(best_bid_price=8.123456789), order())
        decimals = payload["price"].split(".")[1] if "." in payload["price"] else ""
        self.assertLessEqual(len(decimals), 3)


if __name__ == "__main__":
    unittest.main()
