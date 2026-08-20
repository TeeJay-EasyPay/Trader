"""Founder-directed 2026-08-20: patient (limit) buy orders to earn Kraken's maker fee.

Confirmed on pro.kraken.com Tier 1: maker 0.40%, taker 0.80%. Every order this app places
is currently a market order, so entries pay double what they need to.

ENTRIES ONLY, and that asymmetry is the whole design. A resting sell reserves the coins, so
only one sell can rest per position -- and the native trailing stop already occupies it.
Buying is uncontested, so this saving costs no protection at all.

Ships INERT (KRAKEN_LIMIT_ENTRIES_ENABLED off) until the market-order fallback is wired: a
post-only order that cannot rest is cancelled by Kraken rather than filled, so without a
fallback an unfilled entry would silently become a missed trade.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.broker_adapters import _limit_entry_price
from ai_trader.models import OrderRequest


def request(entry_price=100.0, side="buy", quantity=0.1):
    # OrderRequest has no entry_price field; notional/quantity IS the price.
    return OrderRequest(
        symbol="BTC", side=side, quantity=quantity, asset_type="crypto", exchange="KRAKEN",
        stop_loss=98.0, take_profit=104.0, notional_amount=entry_price * quantity,
    )


class LimitEntryPriceTests(unittest.TestCase):
    def test_disabled_by_default_so_this_ships_inert(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            self.assertIsNone(_limit_entry_price(request()))

    def test_prices_at_or_below_the_intended_entry_never_above(self):
        with mock.patch.dict("os.environ", {"KRAKEN_LIMIT_ENTRIES_ENABLED": "true"}):
            price = _limit_entry_price(request(entry_price=100.0))
        self.assertIsNotNone(price)
        self.assertLessEqual(price, 100.0, "Bidding above the proposal price to save 0.40% is self-defeating.")
        self.assertGreater(price, 99.0, "The concession should be small, not a lowball that never fills.")

    def test_a_larger_offset_is_honoured(self):
        with mock.patch.dict("os.environ", {
            "KRAKEN_LIMIT_ENTRIES_ENABLED": "true", "KRAKEN_LIMIT_ENTRY_OFFSET_PCT": "0.01",
        }):
            self.assertAlmostEqual(_limit_entry_price(request(entry_price=100.0)), 99.0, places=6)

    def test_a_missing_or_invalid_entry_price_falls_back_to_a_market_order(self):
        with mock.patch.dict("os.environ", {"KRAKEN_LIMIT_ENTRIES_ENABLED": "true"}):
            self.assertIsNone(_limit_entry_price(request(entry_price=0.0)))
            self.assertIsNone(_limit_entry_price(request(quantity=0.0)))


class LimitEntryPayloadTests(unittest.TestCase):
    """The payload details are what actually earn the fee -- a limit order missing post-only
    that crosses the spread is charged as a taker anyway, saving nothing."""

    def _payload_for(self, env):
        from ai_trader import broker_adapters as ba
        captured = {}

        def fake_request(path, payload=None):
            captured.update(payload or {})
            return {"txid": ["OABC-123"], "descr": {"order": "buy"}}

        adapter = ba.KrakenAdapter()
        with mock.patch.dict("os.environ", env), \
             mock.patch.object(adapter, "_private_request", side_effect=fake_request), \
             mock.patch.object(adapter, "_validate_live_order", return_value={"passed": True, "pair": "XBTGBP", "volume": 0.1, "notional": 10.0, "failures": []}):
            adapter.place_order(request())
        return captured

    def _base_env(self, **extra):
        # KrakenAdapter.configured needs a key AND a secret.
        env = {
            "KRAKEN_API_KEY": "k", "KRAKEN_API_SECRET": "s",
            "KRAKEN_AUTO_TRADING": "true", "KRAKEN_LIVE_TRADING_APPROVED": "true",
        }
        env.update(extra)
        return env

    def test_market_order_when_the_feature_is_off(self):
        payload = self._payload_for(self._base_env())
        self.assertEqual(payload.get("ordertype"), "market")
        self.assertNotIn("price", payload)

    def test_limit_order_carries_post_only_and_an_expiry(self):
        payload = self._payload_for(self._base_env(KRAKEN_LIMIT_ENTRIES_ENABLED="true"))
        self.assertEqual(payload.get("ordertype"), "limit")
        self.assertIn("price", payload)
        self.assertEqual(payload.get("oflags"), "post",
                         "Without post-only a crossing limit order is charged as a taker - saving nothing.")
        self.assertTrue(str(payload.get("expiretm", "")).startswith("+"),
                        "An unfilled patient entry must expire rather than rest indefinitely.")

    def test_sells_are_never_converted_to_limit_orders(self):
        from ai_trader import broker_adapters as ba
        captured = {}

        def fake_request(path, payload=None):
            captured.update(payload or {})
            return {"txid": ["OABC-123"], "descr": {"order": "sell"}}

        adapter = ba.KrakenAdapter()
        env = self._base_env(KRAKEN_LIMIT_ENTRIES_ENABLED="true", KRAKEN_BUY_ONLY_ENTRIES="false")
        with mock.patch.dict("os.environ", env), \
             mock.patch.object(adapter, "_private_request", side_effect=fake_request), \
             mock.patch.object(adapter, "_validate_live_order", return_value={"passed": True, "pair": "XBTGBP", "volume": 0.1, "notional": 10.0, "failures": []}):
            adapter.place_order(request(side="sell"))
        self.assertEqual(captured.get("ordertype"), "market",
                         "The sell side is occupied by the native trailing stop and must not change.")


if __name__ == "__main__":
    unittest.main()
