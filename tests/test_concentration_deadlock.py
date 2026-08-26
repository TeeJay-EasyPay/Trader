"""2026-08-26: the concentration rule was blocking the trades that would have fixed the
concentration.

Confirmed on the live Alpaca account: two positions, FSLR at 48.7% and NEE at 51.3%, on a
sleeve nowhere near its capacity, with $96k of cash unused. With only two holdings one of
them is over 25% by arithmetic, so NEE tripped the "large position" warning and every new
candidate was demoted to portfolio_manager_manual_review -- including the ones that would
have diluted it.

The closed loop was diagnosed and fixed for Kraken months earlier by comparing position
count against the sleeve's own capacity. _broker_managed_position_cap returned that capacity
for Kraken only and None for everything else, and None makes the guard pass, so Alpaca kept
running the unguarded version the whole time.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.portfolio_intelligence import _broker_managed_position_cap, _exposure_warnings


def _positions(weights):
    return [{"symbol": symbol, "weight": weight} for symbol, weight in weights]


def _concentration_warnings(largest, *, broker):
    return [
        warning for warning in _exposure_warnings(
            {}, largest, [], max_managed_positions=_broker_managed_position_cap(broker)
        )
        if "large position" in warning
    ]


class ConcentrationDeadlockTests(unittest.TestCase):
    def test_a_half_full_alpaca_sleeve_is_not_called_concentrated(self):
        """The live case: two positions out of a possible three, so diversification is still
        genuinely available and must not be blocked."""
        with mock.patch.dict(os.environ, {"MAX_OPEN_POSITIONS": "3"}):
            warnings = _concentration_warnings(_positions([("NEE", 0.513), ("FSLR", 0.487)]), broker="alpaca")

        self.assertEqual(warnings, [], "a 2-of-3 book must not block the trade that would dilute it")

    def test_a_full_alpaca_sleeve_still_warns(self):
        """Once the sleeve has filled and one name still dominates, diversification was
        possible and did not happen -- that is worth saying."""
        with mock.patch.dict(os.environ, {"MAX_OPEN_POSITIONS": "3"}):
            warnings = _concentration_warnings(
                _positions([("NEE", 0.60), ("FSLR", 0.25), ("LLY", 0.15)]), broker="alpaca"
            )

        self.assertTrue(warnings, "a full book dominated by one name is real concentration")
        self.assertIn("NEE", warnings[0])

    def test_kraken_keeps_its_own_capacity(self):
        with mock.patch.dict(os.environ, {"KRAKEN_MAX_OPEN_TRADES": "5"}):
            self.assertEqual(_broker_managed_position_cap("kraken"), 5)

    def test_alpaca_now_has_a_capacity_at_all(self):
        """None was the bug: it makes the guard pass and the warning fire unconditionally."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAX_OPEN_POSITIONS", None)
            self.assertEqual(_broker_managed_position_cap("alpaca"), 3)

    def test_an_unknown_broker_keeps_the_always_on_check(self):
        """Only brokers whose capacity is genuinely known get the guard; anything else keeps
        the conservative behaviour rather than silently losing a safety check."""
        self.assertIsNone(_broker_managed_position_cap("coinbase"))


if __name__ == "__main__":
    unittest.main()
