"""Founder-directed 2026-08-20: order sizing must scale with available capital.

*"I would rather they be a percentage of the available cash rather than a fixed value.
that way they can scale with the cash available."*

Two flat caps previously pinned every trade regardless of how much capital was in the
account: CRYPTO_MAX_AUTO_TRADE_AMOUNT (the requested notional) and KRAKEN_MAX_ORDER_GBP
(a hard adapter rejection at GBP 5). Adding money changed nothing. These tests pin the
percentage behaviour AND the fallbacks, because a failed balance read must degrade to the
old flat behaviour rather than to a zero-size order that would simply be rejected.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.application.research_service import _crypto_requested_notional


class CryptoRequestedNotionalTests(unittest.TestCase):
    def test_scales_with_the_account(self):
        self.assertAlmostEqual(
            _crypto_requested_notional(account_equity=500.0, pct=0.05, fallback_amount=10.0),
            25.0, places=6,
        )

    def test_the_whole_point_more_capital_means_bigger_trades(self):
        small = _crypto_requested_notional(account_equity=100.0, pct=0.05, fallback_amount=10.0)
        large = _crypto_requested_notional(account_equity=500.0, pct=0.05, fallback_amount=10.0)
        self.assertAlmostEqual(small, 5.0, places=6)
        self.assertAlmostEqual(large, 25.0, places=6)
        self.assertGreater(large, small, "Adding capital must actually change trade size.")

    def test_falls_back_to_the_flat_amount_when_equity_is_unavailable(self):
        for equity in (0.0, -1.0, None):
            self.assertAlmostEqual(
                _crypto_requested_notional(account_equity=equity, pct=0.05, fallback_amount=10.0),
                10.0, places=6, msg=f"equity={equity} must degrade to the flat amount, not zero.",
            )

    def test_falls_back_when_the_percentage_is_disabled(self):
        self.assertAlmostEqual(
            _crypto_requested_notional(account_equity=500.0, pct=0.0, fallback_amount=10.0),
            10.0, places=6,
        )

    def test_never_exceeds_the_configured_share_of_real_equity(self):
        for equity in (1.0, 100.0, 10_000.0):
            got = _crypto_requested_notional(account_equity=equity, pct=0.05, fallback_amount=10.0)
            self.assertLessEqual(got, equity * 0.05 + 1e-9, f"equity={equity}")


if __name__ == "__main__":
    unittest.main()
