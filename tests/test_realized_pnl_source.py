"""2026-08-24 Founder-reported: Trade History showed +GBP 0.48 profit on a trade that actually
made GBP 0.057 -- an 8x overstatement.

Reconstructed from the real numbers: the AI sold 0.00119506 ETH at 1741.54 having bought at
1666.50, a real net of GBP 0.057 after fees. The FIFO matcher instead priced that sell
against a buy at ~GBP 1,340 -- one of the Founder's OWN older ETH purchases sitting in the
same Kraken wallet.

That is unfixable in FIFO terms: on Kraken the AI trades inside a personal account, so "the
oldest buy of this symbol" is very often not the entry this exit closes. Reconciliation
already links each exit to its own entry and computes net_pnl from real fills on both legs.

Overstating profit is the worst direction for this number to be wrong in -- it is what the
Founder reads when deciding how much capital to commit.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.production_evidence import _fifo_matched_realized_pnl


class FifoMisattributionTests(unittest.TestCase):
    """Documents WHY FIFO cannot be used on a personal Kraken account."""

    def test_fifo_prices_an_ai_exit_against_a_personal_holding(self):
        # The exact live shape: an old personal buy, then the AI's own round trip.
        fills = [
            {"trade_evidence_id": 1, "side": "buy", "quantity": 0.05, "price": 1339.54, "fee": 0.0},
            {"trade_evidence_id": 2, "side": "buy", "quantity": 0.00119506, "price": 1666.50, "fee": 0.016},
            {"trade_evidence_id": 3, "side": "sell", "quantity": 0.00119506, "price": 1741.54, "fee": 0.0167},
        ]
        fifo = _fifo_matched_realized_pnl(fills)[3]
        real = (1741.54 - 1666.50) * 0.00119506 - 0.0167

        self.assertGreater(
            fifo, real * 5,
            "FIFO matches the personal lot first and massively overstates the profit -- this "
            "is the bug, asserted so nobody reinstates FIFO for Kraken.",
        )
        self.assertAlmostEqual(real, 0.0730, places=3)

    def test_fifo_stays_correct_when_every_buy_really_is_the_ai_s(self):
        """It is not broken in general -- only when someone else's holdings share the wallet.
        Alpaca has no personal holdings, which is why FIFO remains the fallback there."""
        fills = [
            {"trade_evidence_id": 1, "side": "buy", "quantity": 2.0, "price": 100.0, "fee": 0.0},
            {"trade_evidence_id": 2, "side": "sell", "quantity": 2.0, "price": 110.0, "fee": 1.0},
        ]
        self.assertAlmostEqual(_fifo_matched_realized_pnl(fills)[2], 19.0, places=6)

    def test_an_exit_with_no_known_entry_is_omitted_not_guessed(self):
        """Pre-existing positions must never be priced against an invented cost basis."""
        fills = [{"trade_evidence_id": 9, "side": "sell", "quantity": 1.0, "price": 50.0, "fee": 0.1}]
        self.assertEqual(_fifo_matched_realized_pnl(fills), {})


class ReconciledSourceTests(unittest.TestCase):
    def test_kraken_prefers_reconciliation_over_fifo(self):
        """Guards the fix itself: the Kraken branch must not fall through to FIFO."""
        source = (Path(__file__).resolve().parents[1] / "src" / "ai_trader" / "production_evidence.py").read_text(encoding="utf-8")
        marker = source.index("def backfill_realized_pnl")
        body = source[marker:marker + 4000]
        self.assertIn("_reconciled_pnl_by_exit_order", body)
        self.assertIn('broker.lower() == "kraken"', body)
        self.assertLess(
            body.index("_reconciled_pnl_by_exit_order"),
            body.index("_fifo_matched_realized_pnl"),
            "Reconciliation must be consulted BEFORE any FIFO fallback.",
        )


if __name__ == "__main__":
    unittest.main()
