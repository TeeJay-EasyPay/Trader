"""2026-08-23 Founder-reported: the Executive Briefing said

    "An opportunity reached execution eligibility, but no broker submission is recorded.
     This requires attention."

on a day with THREE accepted Kraken orders (LINK 11:33, XLM 12:44, LTC 13:40, plus LINK
again at 17:51). _why_no_trade counted submissions only from period-scoped broker trade
rows, which lag and carry broker-specific statuses, while ORDER_INTENT_LOCKS records every
accepted order the moment the broker accepts it.

A false "requires attention" on the main screen is worse than none: it trains the Founder to
ignore the one line that is supposed to mean something.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.production_evidence import _why_no_trade


def funnel(eligible=12, ideas=12, examined=19):
    return {
        "symbols_examined": examined,
        "interesting_ideas": ideas,
        "eligible_for_paper_execution": eligible,
        "primary_reason": "Handled by the independent per-broker auto-execution jobs.",
    }


class ExecutionGapAlertTests(unittest.TestCase):
    def test_accepted_orders_are_recognised_as_submissions(self):
        """The exact live shape: eligible opportunities, no broker trade rows yet, but real
        accepted orders on record."""
        result = _why_no_trade([funnel()], [], [], accepted_orders=3)
        self.assertNotEqual(
            result["state"], "approved_but_not_submitted",
            "Three accepted broker orders is not an execution gap.",
        )
        self.assertNotIn("requires attention", result["conclusion"].lower())
        self.assertEqual(result["counts"]["orders_submitted"], 3)

    def test_a_genuine_execution_gap_is_still_flagged(self):
        """The alert must keep working -- eligible opportunities and genuinely nothing
        placed is exactly what the Founder needs told."""
        result = _why_no_trade([funnel()], [], [], accepted_orders=0)
        self.assertEqual(result["state"], "approved_but_not_submitted")
        self.assertIn("requires attention", result["conclusion"].lower())

    def test_broker_trade_rows_still_count_on_their_own(self):
        """Pre-existing behaviour must not regress: a filled broker row is still a
        submission even with no lock evidence passed in."""
        trades = [{"status": "filled"}, {"status": "accepted"}]
        result = _why_no_trade([funnel()], [], trades)
        self.assertEqual(result["state"], "order_submitted_or_trade_completed")

    def test_no_opportunity_found_is_unaffected(self):
        """A quiet window with no candidates is not an execution gap and must not be
        relabelled as one."""
        result = _why_no_trade([funnel(eligible=0, ideas=0)], [], [], accepted_orders=0)
        self.assertEqual(result["state"], "no_opportunity_found")

    def test_opportunities_rejected_by_governance_is_unaffected(self):
        result = _why_no_trade([funnel(eligible=0, ideas=5)], [], [], accepted_orders=0)
        self.assertEqual(result["state"], "opportunity_found_but_rejected")


if __name__ == "__main__":
    unittest.main()
