"""Founder-directed 2026-08-20: patient (limit) buy orders to earn Kraken's maker fee.

Confirmed on pro.kraken.com Tier 1 (at the time): maker 0.40%, taker 0.80%. Every order this
app places is otherwise a market order, so entries pay double what they need to.

ENTRIES ONLY, and that asymmetry is the whole design. A resting sell reserves the coins, so
only one sell can rest per position -- and the native trailing stop already occupies it.
Buying is uncontested, so this saving costs no protection at all.

Shipped INERT (KRAKEN_LIMIT_ENTRIES_ENABLED off) on 2026-08-20 until the market-order
fallback was wired: a post-only order that cannot rest is cancelled by Kraken rather than
filled, so without a fallback an unfilled entry would silently become a missed trade. That
fallback (bounded poll for a fill, then cancel + market order) was built 2026-08-22 and is
what most of this file now tests.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ai_trader.broker_adapters as ba
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


class FakeKraken:
    """Records every private-endpoint call and answers QueryOrders with a scripted status
    sequence, so the fallback's polling loop can be driven deterministically without any
    real waiting. time.sleep is patched to a no-op for the same reason -- these tests must
    stay fast regardless of KRAKEN_LIMIT_ENTRY_POLL_* settings.
    """

    def __init__(self, statuses=("open",)):
        self.calls: list[tuple[str, dict]] = []
        self._statuses = list(statuses)
        self._add_order_seq = 0

    def __call__(self, path, payload=None):
        payload = payload or {}
        self.calls.append((path, dict(payload)))
        if path == "/0/private/AddOrder":
            self._add_order_seq += 1
            txid = f"OLIMIT-{self._add_order_seq}" if self._add_order_seq == 1 else f"OMARKET-{self._add_order_seq}"
            return {"result": {"txid": [txid], "descr": {"order": payload.get("type", "buy")}}}
        if path == "/0/private/QueryOrders":
            txid = payload.get("txid")
            status = self._statuses.pop(0) if self._statuses else "canceled"
            return {"result": {txid: {"status": status}}}
        if path == "/0/private/CancelOrder":
            return {"result": {"count": 1}}
        raise AssertionError(f"Unexpected private call: {path}")

    def add_order_calls(self):
        return [payload for path, payload in self.calls if path == "/0/private/AddOrder"]

    def query_orders_calls(self):
        return [payload for path, payload in self.calls if path == "/0/private/QueryOrders"]

    def cancel_order_calls(self):
        return [payload for path, payload in self.calls if path == "/0/private/CancelOrder"]


def _base_env(**extra):
    # KrakenAdapter.configured needs a key AND a secret. Poll interval kept tiny (still
    # patched to a no-op sleep below, but keeps the loop's own math sane) rather than the
    # 5s production default, which these tests never actually wait out.
    env = {
        "KRAKEN_API_KEY": "k", "KRAKEN_API_SECRET": "s",
        "KRAKEN_AUTO_TRADING": "true", "KRAKEN_LIVE_TRADING_APPROVED": "true",
        "KRAKEN_LIMIT_ENTRY_POLL_INTERVAL_SECONDS": "0.01",
        "KRAKEN_LIMIT_ENTRY_POLL_BUDGET_SECONDS": "0.05",
    }
    env.update(extra)
    return env


def _place(env, fake, *, side="buy"):
    from ai_trader import broker_adapters as ba

    adapter = ba.KrakenAdapter()
    with mock.patch.dict("os.environ", env), \
         mock.patch.object(adapter, "_private_request", side_effect=fake), \
         mock.patch.object(ba.time, "sleep", return_value=None), \
         mock.patch.object(adapter, "_validate_live_order", return_value={"passed": True, "pair": "XBTGBP", "volume": 0.1, "notional": 10.0, "failures": []}):
        return adapter.place_order(request(side=side))


class LimitEntryPayloadTests(unittest.TestCase):
    """The payload details are what actually earn the fee -- a limit order missing post-only
    that crosses the spread is charged as a taker anyway, saving nothing."""

    def test_market_order_when_the_feature_is_off(self):
        fake = FakeKraken()
        result = _place(_base_env(), fake)
        add_orders = fake.add_order_calls()
        self.assertEqual(len(add_orders), 1, "No limit entry, no fallback -- exactly one order placed.")
        self.assertEqual(add_orders[0].get("ordertype"), "market")
        self.assertNotIn("price", add_orders[0])
        self.assertEqual(result["status"], "accepted")

    def test_limit_order_carries_post_only_and_an_expiry(self):
        # "closed" on the first poll simulates an immediate maker fill -- this test's whole
        # purpose is the INITIAL limit order's own payload shape, not the fallback.
        fake = FakeKraken(statuses=["closed"])
        _place(_base_env(KRAKEN_LIMIT_ENTRIES_ENABLED="true"), fake)
        add_orders = fake.add_order_calls()
        self.assertEqual(len(add_orders), 1, "A filled limit order must never trigger a market fallback.")
        limit_payload = add_orders[0]
        self.assertEqual(limit_payload.get("ordertype"), "limit")
        self.assertIn("price", limit_payload)
        self.assertEqual(limit_payload.get("oflags"), "post",
                         "Without post-only a crossing limit order is charged as a taker - saving nothing.")
        self.assertTrue(str(limit_payload.get("expiretm", "")).startswith("+"),
                        "An unfilled patient entry must expire rather than rest indefinitely.")

    def test_sells_are_never_converted_to_limit_orders(self):
        fake = FakeKraken()
        _place(_base_env(KRAKEN_LIMIT_ENTRIES_ENABLED="true", KRAKEN_BUY_ONLY_ENTRIES="false"), fake, side="sell")
        add_orders = fake.add_order_calls()
        self.assertEqual(len(add_orders), 1)
        self.assertEqual(add_orders[0].get("ordertype"), "market",
                         "The sell side is occupied by the native trailing stop and must not change.")
        self.assertEqual(fake.query_orders_calls(), [], "Sells never enter the poll-for-fill path at all.")


class LimitEntryFallbackTests(unittest.TestCase):
    """2026-08-22: the fallback that makes it safe to turn KRAKEN_LIMIT_ENTRIES_ENABLED on."""

    def test_a_fill_within_the_poll_window_never_places_a_second_order(self):
        fake = FakeKraken(statuses=["open", "closed"])
        result = _place(_base_env(KRAKEN_LIMIT_ENTRIES_ENABLED="true"), fake)
        self.assertEqual(len(fake.add_order_calls()), 1)
        self.assertEqual(fake.cancel_order_calls(), [])
        self.assertEqual(result["order_id"], "OLIMIT-1")
        self.assertNotIn("fallback_from_unfilled_limit_order_id", result)

    def test_an_order_that_never_fills_is_cancelled_and_replaced_with_a_market_order(self):
        # "open" for every poll in the (tiny, test-only) budget -- never fills.
        fake = FakeKraken(statuses=["open", "open", "open", "open", "open", "open", "open", "open", "open", "open"])
        result = _place(_base_env(KRAKEN_LIMIT_ENTRIES_ENABLED="true"), fake)
        add_orders = fake.add_order_calls()
        self.assertEqual(len(add_orders), 2, "The unfilled limit entry plus exactly one market fallback.")
        self.assertEqual(add_orders[0].get("ordertype"), "limit")
        self.assertEqual(add_orders[1].get("ordertype"), "market")
        self.assertEqual(len(fake.cancel_order_calls()), 1)
        self.assertEqual(fake.cancel_order_calls()[0].get("txid"), "OLIMIT-1")
        self.assertEqual(result["order_id"], "OMARKET-2")
        self.assertEqual(result["fallback_from_unfilled_limit_order_id"], "OLIMIT-1")

    def test_an_order_kraken_already_cancelled_falls_back_immediately_without_exhausting_the_poll_budget(self):
        fake = FakeKraken(statuses=["canceled"])
        result = _place(_base_env(KRAKEN_LIMIT_ENTRIES_ENABLED="true"), fake)
        # Exactly one status check before giving up and falling back, not the whole budget's
        # worth of polling against an order that is already known to be gone.
        self.assertEqual(len(fake.query_orders_calls()), 1)
        self.assertEqual(len(fake.add_order_calls()), 2)
        self.assertEqual(result["fallback_from_unfilled_limit_order_id"], "OLIMIT-1")

    def test_the_trade_still_happens_even_if_cancelling_the_dead_limit_order_itself_fails(self):
        fake = FakeKraken(statuses=["expired"])

        def flaky_cancel(path, payload=None):
            if path == "/0/private/CancelOrder":
                raise RuntimeError("EOrder:Unknown order (already gone)")
            return fake(path, payload)

        from ai_trader import broker_adapters as ba
        adapter = ba.KrakenAdapter()
        env = _base_env(KRAKEN_LIMIT_ENTRIES_ENABLED="true")
        with mock.patch.dict("os.environ", env), \
             mock.patch.object(adapter, "_private_request", side_effect=flaky_cancel), \
             mock.patch.object(ba.time, "sleep", return_value=None), \
             mock.patch.object(adapter, "_validate_live_order", return_value={"passed": True, "pair": "XBTGBP", "volume": 0.1, "notional": 10.0, "failures": []}):
            result = adapter.place_order(request())
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["fallback_from_unfilled_limit_order_id"], "OLIMIT-1")

    def test_a_status_check_failure_is_treated_as_gone_rather_than_hanging_forever(self):
        from ai_trader import broker_adapters as ba

        def raising_status(path, payload=None):
            if path == "/0/private/QueryOrders":
                raise RuntimeError("network blip")
            return FakeKraken()(path, payload)

        adapter = ba.KrakenAdapter()
        env = _base_env(KRAKEN_LIMIT_ENTRIES_ENABLED="true")
        with mock.patch.dict("os.environ", env), \
             mock.patch.object(adapter, "_private_request", side_effect=raising_status), \
             mock.patch.object(ba.time, "sleep", return_value=None), \
             mock.patch.object(adapter, "_validate_live_order", return_value={"passed": True, "pair": "XBTGBP", "volume": 0.1, "notional": 10.0, "failures": []}):
            result = adapter.place_order(request())
        # A status check that raises must still resolve to a real order, not an exception
        # bubbling out of order placement.
        self.assertIn(result["status"], ("accepted", "submitted"))


if __name__ == "__main__":
    unittest.main()


class MakerPatienceDefaultsTests(unittest.TestCase):
    """2026-08-23, measured against three real trades: the maker strategy was inert.

    LINK 1.606%, XLM 1.600%, LTC 1.592% round trip -- indistinguishable from the ~1.63%
    every pre-maker trade paid, i.e. 2 x 0.80% taker on both legs. A post-only buy priced
    BELOW the market essentially never fills inside a 20-second budget, so every order took
    the market fallback and the 0.40% maker rate was never earned.

    Raising patience alone would have made things worse: at a 5s poll interval a 300s budget
    is 60 QueryOrders calls per order instead of 4, and this account hit
    "EGeneral:Temporary lockout" the same day. The interval has to rise with the budget.
    """

    def _defaults(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in (
                "KRAKEN_LIMIT_ENTRY_POLL_INTERVAL_SECONDS",
                "KRAKEN_LIMIT_ENTRY_POLL_BUDGET_SECONDS",
                "KRAKEN_LIMIT_ENTRY_TIMEOUT_SECONDS",
            ):
                os.environ.pop(name, None)
            return (
                ba._float_env("KRAKEN_LIMIT_ENTRY_POLL_INTERVAL_SECONDS", 30.0),
                ba._float_env("KRAKEN_LIMIT_ENTRY_POLL_BUDGET_SECONDS", 300.0),
                ba._float_env("KRAKEN_LIMIT_ENTRY_TIMEOUT_SECONDS", 420),
            )

    def test_the_budget_is_long_enough_for_a_resting_order_to_realistically_fill(self):
        _, budget, _ = self._defaults()
        self.assertGreaterEqual(
            budget, 300.0,
            "20s was measured to produce zero maker fills across three real trades.",
        )

    def test_patience_does_not_come_at_the_cost_of_more_api_calls(self):
        """The trap: a longer wait at the old 5s interval means 15x the private API calls,
        against an account that hit a temporary lockout the same day."""
        interval, budget, _ = self._defaults()
        calls_per_order = budget / interval
        self.assertLessEqual(
            calls_per_order, 12,
            f"{calls_per_order:.0f} status calls per order is too much API pressure.",
        )
        old_calls_per_minute = 60.0 / 5.0
        self.assertLess(
            60.0 / interval, old_calls_per_minute,
            "Call RATE must not exceed the old 5s-interval behaviour.",
        )

    def test_krakens_own_expiry_outlasts_our_poll_budget(self):
        """If Kraken cancels the order while we are still waiting, we fall back to a market
        order for no reason and pay taker anyway."""
        _, budget, expiry = self._defaults()
        self.assertGreater(
            expiry, budget,
            "expiretm must outlast the poll budget or the wait is self-defeating.",
        )
