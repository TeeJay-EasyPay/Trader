"""Founder-requested 2026-08-20: *"AIs decline reasoning should be available but in a
short easy to understand answers."*

The reviewer changes real trading outcomes but its reasoning was readable nowhere. These
tests pin two things: that only genuine JUDGMENT declines appear (mechanical gates are
already explained elsewhere and would just pad the card), and that the text stays short and
free of raw markdown -- the recommendation cards already show literal '###' and '**' to the
Founder, which is the exact failure this avoids.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.decline_reasons import shorten, summarize_decline


def payload(**overrides):
    base = {
        "symbol": "XLM",
        "reason": "ai_review_declined",
        "review": {
            "proceed": False,
            "confidence": 0.42,
            "reasoning": "Price sits near the top of its 24-hour range after a sharp move. Entering here pays up for a rally that has already happened.",
            "concerns": ["Range position 0.86 leaves little room to the next resistance."],
        },
    }
    base.update(overrides)
    return base


class SummarizeDeclineTests(unittest.TestCase):
    def test_produces_a_short_founder_readable_decline(self):
        got = summarize_decline(payload())
        self.assertEqual(got["symbol"], "XLM")
        self.assertEqual(got["outcome"], "Declined")
        self.assertEqual(got["confidence"], 0.42)
        self.assertIn("Range position", got["main_concern"])

    def test_the_headline_is_the_concern_not_the_bullish_preamble(self):
        """Live finding: reviewer reasoning opens with the BULLISH case before pivoting, so
        leading with it answers the opposite of "why not?"."""
        got = summarize_decline(payload(review={
            "proceed": False,
            "reasoning": "Strong momentum and a bullish bias with price above key moving averages.",
            "concerns": ["Weekly trend weakness undermines the daily signal."],
        }))
        self.assertEqual(got["why"], "Weekly trend weakness undermines the daily signal.")
        self.assertNotIn("bullish bias", got["why"])
        self.assertIn("bullish bias", got["assessment"], "The fuller view is kept, just not as the headline.")

    def test_falls_back_to_the_reasoning_when_there_is_no_concern(self):
        got = summarize_decline(payload(review={"proceed": False, "reasoning": "Too extended here."}))
        self.assertEqual(got["why"], "Too extended here.")
        self.assertIsNone(got["assessment"])

    def test_lowered_confidence_is_labelled_differently_from_an_outright_veto(self):
        got = summarize_decline(payload(reason="ai_review_lowered_confidence_below_minimum"))
        self.assertEqual(got["outcome"], "Not confident enough")

    def test_mechanical_gates_are_excluded(self):
        # Already covered by /crypto-rejections-explained; the reviewer never judged these.
        for reason in ("duplicate_open_position", "entry_too_extended", "pair_unavailable", ""):
            self.assertIsNone(summarize_decline(payload(reason=reason)), reason)

    def test_an_event_without_a_review_body_is_skipped(self):
        self.assertIsNone(summarize_decline(payload(review=None)))
        self.assertIsNone(summarize_decline(payload(review={})))

    def test_a_review_with_empty_reasoning_is_skipped_rather_than_shown_blank(self):
        self.assertIsNone(summarize_decline(payload(review={"proceed": False, "reasoning": "   "})))

    def test_a_bad_confidence_becomes_none_not_zero(self):
        got = summarize_decline(payload(review={"proceed": False, "reasoning": "No.", "confidence": "abc"}))
        self.assertIsNone(got["confidence"], "An unparseable confidence must not display as 0.")

    def test_tolerates_junk(self):
        self.assertIsNone(summarize_decline(None))
        self.assertIsNone(summarize_decline("nonsense"))


class ShortenTests(unittest.TestCase):
    def test_keeps_only_the_first_couple_of_sentences(self):
        text = "One. Two. Three. Four."
        self.assertEqual(shorten(text), "One. Two.")

    def test_does_not_split_on_a_decimal_point(self):
        text = "Confidence fell to 0.42 on this setup. That is below the bar."
        self.assertEqual(shorten(text), text, "A decimal must not be treated as a sentence end.")

    def test_strips_raw_markdown_so_it_never_renders_literally(self):
        got = shorten("### Heading **bold** and `code`")
        for marker in ("#", "*", "`"):
            self.assertNotIn(marker, got)

    def test_collapses_whitespace_and_newlines(self):
        self.assertEqual(shorten("a\n\n   b"), "a b")

    def test_truncates_long_text_at_a_word_boundary_with_ascii_dots(self):
        got = shorten("word " * 200, max_chars=60)
        self.assertLessEqual(len(got), 63)
        self.assertTrue(got.endswith("..."))
        self.assertTrue(got.isascii(), "Non-ASCII can arrive mangled through JSON/HTTP/RN Text.")
        self.assertFalse(got[:-3].endswith("wor"), "Must not cut mid-word.")

    def test_empty_input_returns_empty(self):
        self.assertEqual(shorten(""), "")
        self.assertEqual(shorten(None), "")


if __name__ == "__main__":
    unittest.main()
