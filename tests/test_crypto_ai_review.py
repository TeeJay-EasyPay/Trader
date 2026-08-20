"""Phase 5 of the CIO-level forecasting build (2026-08-20, Founder-directed):
crypto trade generation gets a real qualitative AI review, which it has never had --
it was pure scoring arithmetic while equities got genuine LLM judgment.

The safety property these tests exist to protect: the reviewer can veto or LOWER
confidence, but can NEVER raise confidence or touch entry price, position size,
stop-loss or take-profit. Real-money sizing must not depend on model output.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.agent import propose_crypto_trades
from ai_trader.ai import _review_from_response_text
from ai_trader.audit import AuditDatabase
from ai_trader.foundation import initialize_foundation_schema
from ai_trader.models import AccountContext, GuardrailConfig
from ai_trader.multi_broker import record_crypto_research_score


def _seed_score(db_path: Path, symbol: str = "BTC") -> None:
    record_crypto_research_score(
        db_path,
        symbol=symbol,
        category="Top 20 by market cap",
        metrics={
            "technical_trend_score": 0.75,
            "momentum_score": 0.6,
            "volatility": 0.2,
            "liquidity": 0.8,
            "risk_score": 0.8,
            "overall_due_diligence_score": 0.9,
            "confidence_score": 0.9,
        },
        source="test",
    )


def _account() -> AccountContext:
    return AccountContext(equity=1000, daily_realized_pnl=0, open_positions=[], is_paper=False)


class FakeAdapter:
    def current_prices(self, pairs):
        return {pairs[0]: {"c": ["100.0", "1.0"], "h": ["105.0", "108.0"], "l": ["95.0", "92.0"], "o": "98.0"}}


class FakeReviewer:
    def __init__(self, response=None, raises=None):
        self.response = response
        self.raises = raises
        self.received_candidate = None

    def review(self, *, symbol, candidate, context=None):
        self.received_candidate = candidate
        if self.raises:
            raise self.raises
        return self.response


def _run(db_path: Path, reviewer=None, min_confidence: float = 0.85):
    initialize_foundation_schema(db_path)
    audit = AuditDatabase(db_path, None)
    _seed_score(db_path)
    return propose_crypto_trades(
        db_path, FakeAdapter(), ["BTC"], _account(), GuardrailConfig(), audit,
        min_confidence=min_confidence, requested_notional=5.0, default_stop_loss_pct=0.02,
        reviewer=reviewer,
    )


class CryptoReviewParsingTests(unittest.TestCase):
    def test_parses_a_valid_review(self):
        parsed = _review_from_response_text(json.dumps({"proceed": True, "confidence": 0.8, "reasoning": "Setup is clean.", "concerns": ["thin volume"]}))
        self.assertTrue(parsed["proceed"])
        self.assertAlmostEqual(parsed["confidence"], 0.8)
        self.assertEqual(parsed["concerns"], ["thin volume"])

    def test_rejects_unusable_responses_rather_than_half_trusting_them(self):
        self.assertIsNone(_review_from_response_text(""))
        self.assertIsNone(_review_from_response_text("null"))
        self.assertIsNone(_review_from_response_text("not json"))
        self.assertIsNone(_review_from_response_text(json.dumps({"confidence": 0.8, "reasoning": "x"})), "Missing 'proceed' must be rejected.")
        self.assertIsNone(_review_from_response_text(json.dumps({"proceed": True, "reasoning": ""})), "Empty reasoning must be rejected.")

    def test_an_out_of_range_confidence_is_dropped_but_the_review_still_stands(self):
        parsed = _review_from_response_text(json.dumps({"proceed": True, "confidence": 5.0, "reasoning": "Setup is clean."}))
        self.assertIsNotNone(parsed)
        self.assertIsNone(parsed["confidence"], "An out-of-range confidence must be discarded, not clamped or trusted.")


class CryptoReviewBehaviourTests(unittest.TestCase):
    def test_a_review_that_declines_stops_the_trade(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            reviewer = FakeReviewer({"proceed": False, "confidence": 0.4, "reasoning": "The weekly picture contradicts this entry.", "concerns": []})
            self.assertEqual(_run(db_path, reviewer), [], "A declining review must stop the trade.")

    def test_a_review_that_lowers_confidence_below_the_minimum_stops_the_trade(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            reviewer = FakeReviewer({"proceed": True, "confidence": 0.5, "reasoning": "Proceeding but the case is thin.", "concerns": []})
            self.assertEqual(_run(db_path, reviewer), [])

    def test_an_endorsing_review_keeps_the_trade_and_adds_real_reasoning(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            reviewer = FakeReviewer({"proceed": True, "confidence": 0.88, "reasoning": "Trend and momentum agree; entry is not extended.", "concerns": ["thin volume"]})
            proposals = _run(db_path, reviewer)
            self.assertEqual(len(proposals), 1)
            self.assertIn("Trend and momentum agree", proposals[0].plain_english_reasoning)
            self.assertIn("thin volume", proposals[0].plain_english_reasoning)

    def test_a_review_can_never_raise_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            baseline = _run(Path(tmp) / "baseline.sqlite3")
            reviewer = FakeReviewer({"proceed": True, "confidence": 1.0, "reasoning": "Extremely strong setup.", "concerns": []})
            proposals = _run(db_path, reviewer)
            self.assertEqual(len(proposals), 1)
            self.assertLessEqual(
                proposals[0].confidence_score,
                baseline[0].confidence_score,
                "A review must never raise confidence above the deterministic value.",
            )

    def test_a_review_never_changes_price_size_stop_or_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = _run(Path(tmp) / "baseline.sqlite3")[0]
            reviewer = FakeReviewer({"proceed": True, "confidence": 0.87, "reasoning": "Reasonable entry.", "concerns": []})
            reviewed = _run(Path(tmp) / "reviewed.sqlite3", reviewer)[0]

            self.assertEqual(reviewed.entry_price, baseline.entry_price)
            self.assertEqual(reviewed.stop_loss, baseline.stop_loss)
            self.assertEqual(reviewed.take_profit, baseline.take_profit)
            self.assertEqual(reviewed.position_size, baseline.position_size)

    def test_a_reviewer_failure_falls_back_to_the_deterministic_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            reviewer = FakeReviewer(raises=RuntimeError("network timeout"))
            proposals = _run(db_path, reviewer)
            self.assertEqual(len(proposals), 1, "A reviewer failure must never lose a valid deterministic proposal.")

    def test_an_unusable_review_response_falls_back_to_the_deterministic_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            proposals = _run(db_path, FakeReviewer(response=None))
            self.assertEqual(len(proposals), 1)

    def test_no_reviewer_configured_leaves_existing_behaviour_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            proposals = _run(db_path, reviewer=None)
            self.assertEqual(len(proposals), 1)
            self.assertNotIn("AI review:", proposals[0].plain_english_reasoning)

    def test_the_reviewer_receives_real_evidence_and_clearly_fixed_risk_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            reviewer = FakeReviewer({"proceed": True, "confidence": 0.88, "reasoning": "Fine.", "concerns": []})
            _run(db_path, reviewer)

            candidate = reviewer.received_candidate
            self.assertIsNotNone(candidate)
            self.assertIn("scores", candidate)
            self.assertIn("regime", candidate)
            fixed = candidate["fixed_by_risk_management_not_negotiable"]
            self.assertIn("stop_loss", fixed)
            self.assertIn("position_size", fixed)


if __name__ == "__main__":
    unittest.main()
