"""2026-08-27, Founder-directed: measure news sentiment instead of assuming it is zero.

CRYPTO_RESEARCH_SCORES has always had a `sentiment` column and nothing ever wrote to it, so it
sat at 0.0 in a five-way average -- telling the scoring engine that every coin had terrible
coverage when nothing had ever looked. The Founder's question was the right one: "why is
sentiment not an important indicator?" It is. So it is now measured, from the crypto news the
app was already collecting.

The rule these tests exist to hold: a coin with no coverage stays UNSCORED. Not 0.5, not 0.0.
"No news" is not "neutral news", and inventing either repeats the exact fault being fixed.
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from contextlib import closing

from ai_trader.crypto_sentiment import (
    MIN_ARTICLES_FOR_SENTIMENT,
    initialize_crypto_sentiment_schema,
    latest_sentiment,
    recent_headlines,
    score_crypto_sentiment,
)
from ai_trader.database import connect
from ai_trader.foundation import initialize_foundation_schema


def fake_openai(judgements):
    """A stand-in for the /v1/responses call, shaped like the real payload."""
    body = json.dumps({"output": [{"content": [{"text": json.dumps(judgements)}]}]}).encode()

    class Response:
        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return mock.Mock(return_value=Response())


class SentimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        initialize_foundation_schema(self.db_path)
        initialize_crypto_sentiment_schema(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def add_news(self, symbol, count=3, hours_ago=2):
        when = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
        with closing(connect(self.db_path)) as conn:
            with conn:
                for index in range(count):
                    conn.execute(
                        "INSERT INTO CRYPTO_NEWS (symbol, published_at, title, summary, source, url,"
                        " payload_json, created_at) VALUES (?, ?, ?, ?, 'TestWire', 'http://x', '{}', ?)",
                        (symbol, when, f"{symbol} headline {index}", "summary text", when),
                    )

    def test_reads_the_news_already_being_collected(self):
        self.add_news("BTC", count=2)
        self.add_news("ETH", count=1)
        coverage = recent_headlines(self.db_path)
        self.assertEqual(len(coverage["BTC"]), 2)
        self.assertEqual(len(coverage["ETH"]), 1)

    def test_stale_coverage_is_ignored(self):
        """Week-old headlines say nothing about whether a move can be sustained today."""
        self.add_news("BTC", count=3, hours_ago=200)
        self.assertEqual(recent_headlines(self.db_path, window_hours=48), {})

    def test_a_coin_with_too_little_coverage_is_never_judged(self):
        self.add_news("BTC", count=MIN_ARTICLES_FOR_SENTIMENT - 1)
        with mock.patch("ai_trader.crypto_sentiment.urlopen") as opener:
            result = score_crypto_sentiment(self.db_path, api_key="k", model="m")
        self.assertEqual(result["status"], "no_coverage")
        opener.assert_not_called()
        self.assertEqual(latest_sentiment(self.db_path), {})

    def test_no_api_key_records_nothing_rather_than_a_neutral_guess(self):
        self.add_news("BTC", count=3)
        result = score_crypto_sentiment(self.db_path, api_key=None, model="m")
        self.assertEqual(result["status"], "not_available")
        self.assertEqual(latest_sentiment(self.db_path), {})

    def test_a_real_judgement_is_stored_and_readable(self):
        self.add_news("BTC", count=3)
        with mock.patch("ai_trader.crypto_sentiment.urlopen",
                        fake_openai({"BTC": {"sentiment": 0.82, "reason": "Major exchange listing."}})):
            result = score_crypto_sentiment(self.db_path, api_key="k", model="m")
        self.assertEqual(result["scored"], 1)
        self.assertAlmostEqual(latest_sentiment(self.db_path)["BTC"], 0.82, places=3)

    def test_a_symbol_the_model_declines_to_judge_stays_unscored(self):
        """The prompt tells it to omit anything too thin to call. Omission must mean unscored,
        never a default."""
        self.add_news("BTC", count=3)
        self.add_news("DOGE", count=3)
        with mock.patch("ai_trader.crypto_sentiment.urlopen",
                        fake_openai({"BTC": {"sentiment": 0.7, "reason": "Positive."}})):
            score_crypto_sentiment(self.db_path, api_key="k", model="m")
        stored = latest_sentiment(self.db_path)
        self.assertIn("BTC", stored)
        self.assertNotIn("DOGE", stored)

    def test_scores_are_clamped_to_zero_and_one(self):
        self.add_news("BTC", count=3)
        with mock.patch("ai_trader.crypto_sentiment.urlopen",
                        fake_openai({"BTC": {"sentiment": 4.2, "reason": "Model went out of range."}})):
            score_crypto_sentiment(self.db_path, api_key="k", model="m")
        self.assertEqual(latest_sentiment(self.db_path)["BTC"], 1.0)

    def test_an_unusable_score_is_skipped_rather_than_coerced(self):
        self.add_news("BTC", count=3)
        with mock.patch("ai_trader.crypto_sentiment.urlopen",
                        fake_openai({"BTC": {"sentiment": "very good", "reason": "Not a number."}})):
            result = score_crypto_sentiment(self.db_path, api_key="k", model="m")
        self.assertEqual(result["scored"], 0)
        self.assertEqual(latest_sentiment(self.db_path), {})

    def test_a_failed_call_never_stops_research(self):
        self.add_news("BTC", count=3)
        with mock.patch("ai_trader.crypto_sentiment.urlopen", side_effect=OSError("network down")):
            result = score_crypto_sentiment(self.db_path, api_key="k", model="m")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(latest_sentiment(self.db_path), {})

    def test_stale_sentiment_is_not_reported_as_todays_mood(self):
        self.add_news("BTC", count=3)
        with mock.patch("ai_trader.crypto_sentiment.urlopen",
                        fake_openai({"BTC": {"sentiment": 0.9, "reason": "Old good news."}})):
            score_crypto_sentiment(self.db_path, api_key="k", model="m")
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "UPDATE CRYPTO_SENTIMENT_SCORES SET created_at = ?",
                    ((datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),),
                )
        self.assertEqual(latest_sentiment(self.db_path, max_age_hours=12), {})

    def test_the_newest_reading_wins_when_a_coin_is_scored_twice(self):
        self.add_news("BTC", count=3)
        for value in (0.2, 0.9):
            with mock.patch("ai_trader.crypto_sentiment.urlopen",
                            fake_openai({"BTC": {"sentiment": value, "reason": "r"}})):
                score_crypto_sentiment(self.db_path, api_key="k", model="m")
        self.assertAlmostEqual(latest_sentiment(self.db_path)["BTC"], 0.9, places=3)


if __name__ == "__main__":
    unittest.main()
