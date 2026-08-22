"""2026-08-22: every Alpaca recommendation was blocked on "Investment philosophy fit is
below 85%", and the reason was a missing dictionary key.

INVESTMENT_WATCHLIST stores philosophy fit as a text label. The labels actually in use are
Strong (19 companies), Good (28) and Moderate (3) -- but "strong" was absent from
QUALITATIVE_SCORES, so safe_score() returned None and the caller fell through to 0.0. The
BEST-rated companies therefore scored ZERO, below even "Moderate", while the second tier
scored 0.75 against a 0.85 threshold. Nothing could ever pass.

Confirmed live before the fix: SCCO/FCX/MLM (Strong) = 0.0, MSFT/LULU/ISRG (Good) = 0.75.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.models import AutoTradeConfig
from ai_trader.operational import QUALITATIVE_SCORES, safe_score


class PhilosophyFitScoringTests(unittest.TestCase):
    THRESHOLD = AutoTradeConfig().min_philosophy_fit  # 0.85

    def test_strong_is_scored_at_all(self):
        self.assertIsNotNone(
            safe_score("Strong"),
            "An unmapped label returns None, which callers turn into 0.0 -- the top rating "
            "scoring zero is exactly the bug this guards.",
        )

    def test_the_labels_actually_used_rank_in_the_right_order(self):
        strong, good, moderate = safe_score("Strong"), safe_score("Good"), safe_score("Moderate")
        self.assertGreater(strong, good)
        self.assertGreater(good, moderate)

    def test_strong_clears_the_auto_trade_threshold_and_good_does_not(self):
        """The whole point: the best-rated companies must become tradeable. "Good" staying
        below the bar is deliberate -- this fix corrects a scoring bug, it does not lower
        the Founder's 85% standard."""
        self.assertGreaterEqual(safe_score("Strong"), self.THRESHOLD)
        self.assertLess(safe_score("Good"), self.THRESHOLD)

    def test_case_and_whitespace_do_not_change_the_score(self):
        for variant in ("strong", "STRONG", "  Strong  ", "Strong"):
            self.assertEqual(safe_score(variant), QUALITATIVE_SCORES["strong"], variant)

    def test_every_label_used_by_the_seeded_watchlist_is_mapped(self):
        """Regression guard for the general fault, not just this one word: any label the
        seed data uses must have a score, or those companies silently score zero."""
        import re

        source = (Path(__file__).resolve().parents[1] / "src" / "ai_trader" / "intelligence_data.py").read_text(encoding="utf-8")
        labels = set(re.findall(r'"investment_philosophy_fit":\s*"([^"]+)"', source))
        self.assertTrue(labels, "Expected the seeded watchlist to carry philosophy-fit labels.")
        unmapped = sorted(label for label in labels if safe_score(label) is None)
        self.assertEqual(
            unmapped, [],
            f"These watchlist labels have no score and so silently become 0.0: {unmapped}",
        )

    def test_unknown_labels_still_return_none_rather_than_a_fabricated_number(self):
        self.assertIsNone(safe_score("Bananas"))
        self.assertIsNone(safe_score("unknown"))


if __name__ == "__main__":
    unittest.main()
