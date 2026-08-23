"""2026-08-23 live incident: portfolio_manager_decision read `position_size` as a NOTIONAL,
but on a TradeProposal position_size is the QUANTITY IN UNITS.

The caller already supplies a correct "notional" (sprint6.pre_execution_decision_packet sets
entry_price * position_size) -- it was simply never reached, because position_size was
checked first.

The effect was silent and size-dependent, because a quantity only looks like a small number
for HIGH-priced assets. Confirmed against live trades, all with the same GBP 500 allocation
approving ~GBP 25:

    XLM   25 / 0.144  = 173.6 units -> min(25, 173.6) = GBP 25.00  (right by accident)
    LTC   25 / 38.57  =   0.643     -> min(25, 0.643) -> floored to 0.1 LTC  = GBP 3.86
    SOL   25 / ~70    =   0.417     -> floored to 0.06 SOL = GBP 4.20

So cheap coins traded at full size and expensive ones collapsed to the exchange minimum,
which read as erratic sizing rather than a unit confusion.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.production_spine import portfolio_manager_decision


def payload(symbol, entry_price, quantity, **extra):
    """Mirrors what sprint6.pre_execution_decision_packet actually passes."""
    base = {
        "symbol": symbol,
        "broker": "kraken",
        "asset_type": "crypto",
        "entry_price": entry_price,
        "stop_loss": entry_price * 0.985,
        "position_size": quantity,                    # QUANTITY, not currency
        "notional": entry_price * quantity,           # the real notional
        "quantity": quantity,
    }
    base.update(extra)
    return base


class ProposedNotionalUnitsTests(unittest.TestCase):
    EQUITY = 500.0

    def _approved(self, prop):
        with tempfile.TemporaryDirectory() as tmp:
            return portfolio_manager_decision(
                Path(tmp) / "audit.sqlite3", proposal=prop, positions=[],
                return_series={}, account_equity=self.EQUITY,
            )

    def test_a_high_priced_coin_is_not_collapsed_to_its_quantity(self):
        """The LTC case: GBP 25 at GBP 38.57 is 0.643 units. Reading that as GBP 0.64 is what
        drove the order down to the exchange minimum."""
        result = self._approved(payload("LTC", 38.5686, 25.0 / 38.5686))
        self.assertAlmostEqual(
            result["approved_notional"], 25.0, places=2,
            msg="A GBP 25 trade must stay GBP 25, not become its unit count.",
        )

    def test_a_low_priced_coin_is_unchanged(self):
        """XLM was the one that looked correct -- it must still be correct afterwards."""
        result = self._approved(payload("XLM", 0.144, 25.0 / 0.144))
        self.assertAlmostEqual(result["approved_notional"], 25.0, places=2)

    def test_price_no_longer_changes_the_approved_size(self):
        """THE property. Same GBP 25 trade across wildly different unit prices must approve
        the same notional -- that is what makes this a unit bug and not a risk judgement."""
        approved = [
            self._approved(payload(sym, price, 25.0 / price))["approved_notional"]
            for sym, price in (("XLM", 0.144), ("LINK", 8.297), ("LTC", 38.5686), ("BTC", 50000.0))
        ]
        for value in approved:
            self.assertAlmostEqual(value, 25.0, places=2, msg=f"approved sizes: {approved}")

    def test_a_caller_passing_only_position_size_still_works(self):
        """position_size is kept as the LAST fallback: some callers and existing tests pass a
        notional under that name, and dropping it would size those at zero."""
        legacy = {
            "symbol": "AAA", "broker": "kraken", "asset_type": "crypto",
            "entry_price": 10.0, "stop_loss": 9.85, "position_size": 25.0,
        }
        self.assertAlmostEqual(self._approved(legacy)["approved_notional"], 25.0, places=2)


if __name__ == "__main__":
    unittest.main()
