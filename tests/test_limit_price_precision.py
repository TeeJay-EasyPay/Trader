"""2026-08-23 live incident: every Kraken buy was rejected with

    EOrder:Invalid price:ETH/GBP price can only be specified up to 2 decimals.

from the moment maker/limit entries were switched on. A market order carries no price, so
this could not appear until limit orders went live: last accepted order 2026-08-21 23:43,
first rejection 2026-08-22 18:41. The limit price is notional/quantity with an offset
applied, which routinely yields 7+ decimals.

Two defects, both fixed here:
  1. The price was never rounded to the pair's own allowed precision, which varies widely
     (ETHGBP 2, LINKGBP 3, XBTGBP 1, ADAGBP 5) so one fixed rounding cannot work.
  2. A synchronous rejection killed the trade outright. The pre-existing fallback only
     covered a limit order that RESTED and failed to fill. So a fee optimisation was able
     to cost the trade entirely -- the exact thing it is documented as never doing.
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

PAIR_DECIMALS = {"ETHGBP": 2, "LINKGBP": 3, "XBTGBP": 1, "ADAGBP": 5}

LIVE_ENV = {
    "KRAKEN_API_KEY": "key", "KRAKEN_PRIVATE_KEY": "c2VjcmV0",
    "KRAKEN_AUTO_TRADING": "true", "KRAKEN_LIVE_TRADING_APPROVED": "true",
    "KRAKEN_LIMIT_ENTRIES_ENABLED": "true", "KRAKEN_SUBMIT_REAL_ORDERS": "true",
    # Keep the post-fill poll loop from dominating the test run.
    "KRAKEN_LIMIT_ENTRY_POLL_INTERVAL_SECONDS": "0.01",
    "KRAKEN_LIMIT_ENTRY_POLL_BUDGET_SECONDS": "0.02",
}


def order(pair_symbol="ETH", quantity=0.0300123, notional=50.0):
    return OrderRequest(
        symbol=pair_symbol, side="buy", quantity=quantity, asset_type="crypto",
        exchange="KRAKEN", stop_loss=1500.0, take_profit=1800.0,
        notional_amount=notional, client_order_id="precision-test",
    )


class _Adapter(KrakenAdapter):
    """Real place_order logic; only the network boundary is replaced."""

    def __init__(self, reject_limit_with=None):
        super().__init__()
        self.calls = []
        self._reject_limit_with = reject_limit_with

    def _public_request(self, path):
        pair = path.split("pair=")[-1]
        decimals = PAIR_DECIMALS.get(pair)
        return {"result": {pair: {"pair_decimals": decimals}}} if decimals is not None else {"result": {}}

    def _private_request(self, path, payload=None):
        self.calls.append((path, payload))
        if path == "/0/private/AddOrder":
            if self._reject_limit_with and payload.get("ordertype") == "limit":
                raise RuntimeError(self._reject_limit_with)
            return {"result": {"txid": ["OTEST-1"], "descr": {}}}
        return {"result": {}}


def place(adapter, req):
    with mock.patch.dict(os.environ, LIVE_ENV), \
         mock.patch.object(adapter, "_validate_live_order",
                           return_value={"passed": True, "failures": [], "pair": ba._kraken_pair(req.symbol),
                                         "volume": req.quantity, "notional": req.notional_amount}), \
         mock.patch.object(ba.time, "sleep", return_value=None):
        return adapter.place_order(req)


class LimitPricePrecisionTests(unittest.TestCase):
    def test_the_exact_live_failure_no_longer_sends_too_many_decimals(self):
        adapter = _Adapter()
        place(adapter, order())
        payload = adapter.calls[0][1]
        self.assertEqual(payload["ordertype"], "limit")
        decimals = payload["price"].split(".")[1] if "." in payload["price"] else ""
        self.assertLessEqual(
            len(decimals), 2,
            f"ETHGBP allows 2 decimals; sent {payload['price']} -- this is the exact string "
            "Kraken rejected for a day.",
        )

    def test_each_pair_uses_its_own_precision(self):
        for symbol, pair, allowed in (("ETH", "ETHGBP", 2), ("LINK", "LINKGBP", 3), ("BTC", "XBTGBP", 1)):
            adapter = _Adapter()
            place(adapter, order(symbol, quantity=0.0300123, notional=50.0))
            price = adapter.calls[0][1].get("price", "")
            decimals = price.split(".")[1] if "." in price else ""
            self.assertLessEqual(len(decimals), allowed, f"{pair} allows {allowed}, sent {price}")

    def test_the_price_is_rounded_down_never_up(self):
        """Rounding up could bid ABOVE the price the proposal was sized against, and paying
        more to save a fee defeats the purpose."""
        adapter = _Adapter()
        req = order()
        with mock.patch.dict(os.environ, LIVE_ENV):
            raw = ba._limit_entry_price(req)  # must be read INSIDE the env patch
        place(adapter, req)
        sent = float(adapter.calls[0][1]["price"])
        self.assertIsNotNone(raw)
        self.assertLessEqual(sent, raw)

    def test_unknown_precision_falls_back_to_a_market_order_rather_than_guessing(self):
        adapter = _Adapter()
        place(adapter, order("DOGE"))  # not in PAIR_DECIMALS -> unknown
        payload = adapter.calls[0][1]
        self.assertEqual(payload["ordertype"], "market")
        self.assertNotIn("price", payload)


class RejectedLimitFallsBackToMarketTests(unittest.TestCase):
    REJECTION = "EOrder:Invalid price:ETH/GBP price can only be specified up to 2 decimals."

    def test_a_rejected_limit_order_still_places_the_trade_as_market(self):
        adapter = _Adapter(reject_limit_with=self.REJECTION)
        result = place(adapter, order())

        self.assertEqual(
            result["status"], "accepted",
            "A fee optimisation must never be able to cost the trade -- this is precisely "
            "what blocked every Kraken buy for a day.",
        )
        kinds = [payload.get("ordertype") for path, payload in adapter.calls if path == "/0/private/AddOrder"]
        self.assertEqual(kinds, ["limit", "market"], "Try the maker price once, then fall back.")
        self.assertIn("fallback_from_rejected_limit_order", result)

    def test_the_market_fallback_drops_every_limit_only_field(self):
        adapter = _Adapter(reject_limit_with=self.REJECTION)
        place(adapter, order())
        market_payload = [p for path, p in adapter.calls if path == "/0/private/AddOrder"][1]
        for field in ("price", "oflags", "expiretm"):
            self.assertNotIn(field, market_payload, f"{field} is meaningless on a market order")

    def test_if_the_market_fallback_also_fails_both_reasons_are_reported(self):
        class BothFail(_Adapter):
            def _private_request(self, path, payload=None):
                self.calls.append((path, payload))
                raise RuntimeError("EGeneral:Temporary lockout")

        adapter = BothFail(reject_limit_with=self.REJECTION)
        result = place(adapter, order())
        self.assertEqual(result["status"], "rejected")
        self.assertIn("market fallback also rejected", result["reason"])


if __name__ == "__main__":
    unittest.main()
