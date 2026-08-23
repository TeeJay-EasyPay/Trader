"""2026-08-23, Founder-directed: "relying on one source creates a bottleneck and also risks
getting bad quality news."

Crypto had exactly that, only worse: CryptoPanic was the ONLY crypto news source and needs
an API key that was never set -- so the AI was trading real money on Kraken with no news
input at all. CoinDesk and CoinTelegraph are public RSS: no key, no account, so they work
the moment the job is enabled and keep working if CryptoPanic is down or rate-limited.
"""

import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.database import connect
from ai_trader.external_intelligence import (
    CRYPTO_RSS_FEEDS,
    _detect_crypto_symbols,
    fetch_rss_crypto_news,
    initialize_external_intelligence_schema,
    record_crypto_news,
)

RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Bitcoin Cash surges as Ethereum lags</title><link>https://example.com/a</link>
<description>BCH outperformed.</description><pubDate>Sun, 23 Aug 2026 20:00:00 GMT</pubDate></item>
<item><title>Fed holds rates steady</title><link>https://example.com/b</link>
<description>No coin named here.</description><pubDate>Sun, 23 Aug 2026 21:00:00 GMT</pubDate></item>
</channel></rss>"""


class FakeResponse:
    def __init__(self, body):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class CoinTaggingTests(unittest.TestCase):
    def test_a_longer_coin_name_wins_over_the_shorter_one_inside_it(self):
        """"Bitcoin Cash" once tagged BOTH BCH and BTC. Filing a story under a coin it is
        not about is precisely the bad-quality news these sources exist to avoid."""
        codes = [c["code"] for c in _detect_crypto_symbols("Bitcoin Cash surges as Ethereum lags")]
        self.assertIn("BCH", codes)
        self.assertIn("ETH", codes)
        self.assertNotIn("BTC", codes)

    def test_plain_bitcoin_news_still_tags_bitcoin(self):
        self.assertEqual([c["code"] for c in _detect_crypto_symbols("Bitcoin hits new high")], ["BTC"])

    def test_general_market_news_names_no_coin(self):
        """Untagged is honest -- real news, just not about a specific holding. It is stored
        under MARKET rather than guessed onto a coin."""
        self.assertEqual(_detect_crypto_symbols("Fed holds rates steady"), [])

    def test_only_tradeable_coins_are_recognised(self):
        self.assertEqual(_detect_crypto_symbols("Some unlisted altcoin doubles"), [])


class RssFetchTests(unittest.TestCase):
    def test_a_feed_is_read_into_the_shape_record_crypto_news_expects(self):
        with mock.patch("ai_trader.external_intelligence.urlopen", return_value=FakeResponse(RSS)):
            posts = fetch_rss_crypto_news("https://example.com/rss")
        self.assertEqual(len(posts), 2)
        for post in posts:
            for field in ("title", "url", "published_at", "body", "currencies"):
                self.assertIn(field, post)

    def test_a_dead_feed_returns_nothing_rather_than_raising(self):
        """The whole point of multiple sources: one failing must not stop the others."""
        with mock.patch("ai_trader.external_intelligence.urlopen", side_effect=OSError("feed down")):
            self.assertEqual(fetch_rss_crypto_news("https://example.com/rss"), [])

    def test_malformed_xml_returns_nothing_rather_than_raising(self):
        with mock.patch("ai_trader.external_intelligence.urlopen", return_value=FakeResponse("not xml at all")):
            self.assertEqual(fetch_rss_crypto_news("https://example.com/rss"), [])

    def test_the_same_story_from_two_feeds_is_stored_once(self):
        """Deduped on (symbol, url), so overlapping coverage does not inflate the evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_external_intelligence_schema(db_path)
            with mock.patch("ai_trader.external_intelligence.urlopen", return_value=FakeResponse(RSS)):
                posts = fetch_rss_crypto_news("https://example.com/rss")
            record_crypto_news(db_path, posts=posts, source="CoinDesk")
            record_crypto_news(db_path, posts=posts, source="CoinTelegraph")
            with closing(connect(db_path)) as conn:
                rows = conn.execute("SELECT COUNT(*) FROM CRYPTO_NEWS").fetchone()[0]
            self.assertEqual(rows, 3, "BCH + ETH from story one, MARKET from story two -- each stored once.")

    def test_at_least_two_keyless_feeds_are_configured(self):
        """A single source is the bottleneck the Founder asked to remove."""
        self.assertGreaterEqual(len(CRYPTO_RSS_FEEDS), 2)


if __name__ == "__main__":
    unittest.main()


class ExternalIntelligenceTimeoutTests(unittest.TestCase):
    """2026-08-23 live: the 22:00 external-intelligence-refresh run TIMED OUT on the shared
    180s worker budget, so the news it fetches never got stored.

    The job makes many small sequential HTTP calls in one run -- SEC EDGAR per symbol,
    Alpaca News across the watchlist, a FRED series each, plus the crypto RSS feeds -- which
    is the same shape as forecast-refresh and benchmark-research-refresh, both already moved
    off the shared budget meant for single-query work.
    """

    def test_the_news_job_gets_the_multi_call_budget_not_the_default(self):
        import re

        source = (Path(__file__).resolve().parents[1] / "src" / "ai_trader" / "cli.py").read_text(encoding="utf-8")
        match = re.search(r"if job_name in \{([^}]*)\}", source)
        self.assertIsNotNone(match, "Expected the research-timeout job set in cli.py")
        self.assertIn(
            "external-intelligence-refresh", match.group(1),
            "Without this the job is killed mid-fetch every run and stores nothing.",
        )

    def test_that_budget_is_meaningfully_longer_than_the_shared_default(self):
        from ai_trader.config import Settings

        defaults = Settings.__dataclass_fields__
        shared = defaults["worker_job_timeout_seconds"].default
        research = defaults["research_job_timeout_seconds"].default
        self.assertGreater(
            research, shared,
            f"research budget {research}s must exceed the shared {shared}s or the move achieves nothing.",
        )
