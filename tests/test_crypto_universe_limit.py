"""2026-08-20: the researched crypto universe was silently capped at 10 coins.

The Founder pasted a 19-coin KRAKEN_ALLOWED_PAIRS list into Render and the research cycle
kept examining the same 9. The environment variable was fine; run_crypto_analysis defaulted
its `limit` to 10 and sliced the de-duplicated symbol list down to that, so no amount of
configuration could widen the universe.

Fourth instance today of the same shape: a default that quietly outlives the configuration
meant to replace it (RISK_POLICIES row, the four MAX_OPEN_POSITIONS values, the GBP 100
capital ledger, and now this).
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.application.research_service import _symbol_from_kraken_pair


FOUNDER_PAIRS = (
    "XBTGBP,BTCGBP,ETHGBP,SOLGBP,XRPGBP,BCHGBP,XLMGBP,ADAGBP,DOTGBP,LINKGBP,"
    "LTCGBP,ATOMGBP,ALGOGBP,FILGBP,GRTGBP,SANDGBP,SUIGBP,MINAGBP,KSMGBP,XDGGBP"
)


def symbols_for(limit: int) -> list[str]:
    """Mirrors _bootstrap_crypto_universe_from_kraken_permissions' selection exactly."""
    symbols = [_symbol_from_kraken_pair(pair) for pair in FOUNDER_PAIRS.split(",")]
    symbols = [s for s in symbols if s]
    return list(dict.fromkeys(symbols))[: max(1, min(limit, 30))]


class UniverseLimitTests(unittest.TestCase):
    def test_the_founder_list_yields_nineteen_distinct_coins(self):
        # XBTGBP and BTCGBP are both Bitcoin, so 20 pairs collapse to 19 coins.
        self.assertEqual(len(symbols_for(30)), 19)

    def test_the_old_default_of_ten_was_the_cap_that_hid_the_new_coins(self):
        capped = symbols_for(10)
        self.assertEqual(len(capped), 10)
        for missing in ("ATOM", "ALGO", "FIL", "GRT", "SAND", "SUI", "MINA", "KSM", "DOGE"):
            self.assertNotIn(missing, capped, f"{missing} was silently dropped by the old limit of 10.")

    def test_the_new_default_admits_the_whole_approved_list(self):
        admitted = symbols_for(25)
        self.assertEqual(len(admitted), 19)
        for expected in ("BTC", "ETH", "SOL", "XRP", "BCH", "XLM", "ADA", "DOT", "LINK", "LTC"):
            self.assertIn(expected, admitted)

    def test_the_hard_ceiling_of_thirty_still_holds(self):
        self.assertLessEqual(len(symbols_for(999)), 30)

    def test_bitcoin_is_not_researched_twice(self):
        admitted = symbols_for(25)
        self.assertEqual(admitted.count("BTC"), 1, "XBTGBP and BTCGBP must collapse to one coin.")


if __name__ == "__main__":
    unittest.main()
