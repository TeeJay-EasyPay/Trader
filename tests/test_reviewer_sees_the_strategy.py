"""The reviewer must be told which strategy it is being asked to judge.

2026-09-06. The crypto reviewer is asked whether the assigned strategy suits the coin. The
candidate payload it receives never contained the strategy, so it answered honestly:

    strategy_fit: "unproven"
    concerns: ["No confirmed rebound or breakout", "Weekly momentum is zero",
               "Assigned strategy is unspecified"]
    reasoning: "...The assigned strategy is not identified, so its fit cannot be verified."
    proceed: false

One of three stated concerns behind declining XLM was a blank the caller left. And the
ai_strategy_judgement event written moments later, for the same candidate, recorded
assigned_strategy "range_trading" -- the value was one attribute away the whole time.

This matters beyond one field: the Founder asked whether 75% of coins are rejected because the
maths is too strong or because the market is flat. Measured, neither -- the market is rising
(78% of coins up over 7 days) and 8 of 19 tradable coins clear the first gate. The blockage is
at the reviewer, and it was being asked to judge a fit it had no way to assess.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

AGENT = Path(__file__).resolve().parents[1] / "src" / "ai_trader" / "agent.py"


class ReviewerCandidateTests(unittest.TestCase):
    def test_the_candidate_names_the_assigned_strategy(self):
        from ai_trader.agent import _review_candidate

        class _Intel(dict):
            pass

        class _Proposal:
            strategy_id = "range_trading"
            confidence_score = 0.72
            entry_price = 1.0
            stop_loss = 0.9
            take_profit = 1.3
            position_size = 10.0
            intelligence = _Intel()

        row = {
            "technical_trend_score": 0.56, "momentum_score": 0.63, "volatility": 0.2,
            "liquidity": 0.85, "risk_score": 0.86, "overall_due_diligence_score": 0.72,
        }
        candidate = _review_candidate(_Proposal(), row, range_position=0.205, day_range={})
        self.assertEqual(candidate.get("assigned_strategy"), "range_trading")

    def test_the_strategy_is_not_hidden_behind_the_risk_management_block(self):
        """It must be a top-level fact, not buried in the block explicitly labelled
        'fixed_by_risk_management_not_negotiable', which the prompt tells the model is context
        it may not argue with."""
        body = AGENT.read_text(encoding="utf-8")
        start = body.index("def _review_candidate")
        block = body[start:].split("\ndef ", 1)[0]
        self.assertIn('"assigned_strategy": proposal.strategy_id', block)
        fixed_at = block.index("fixed_by_risk_management_not_negotiable")
        strategy_at = block.index('"assigned_strategy"')
        self.assertLess(strategy_at, fixed_at)


if __name__ == "__main__":
    unittest.main()
