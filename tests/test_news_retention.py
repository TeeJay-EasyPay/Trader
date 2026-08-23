"""2026-08-23, Founder-directed: "make sure that with all these feeds and the news coming in
the database doesnt suddenly expand too much and egress is not increased."

The four tables written by external-intelligence-refresh had NO retention at all and would
have grown forever. They are also the highest row-rate tables in the system now: two crypto
RSS feeds at up to 25 stories each, one row per tagged coin, plus Alpaca news across the
watchlist, every hour.

This is the 2026-08-08 Supabase size lesson applied before the fact rather than after: the
only way to shrink a high-volume log table is fewer live rows.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.production_evidence import PRODUCTION_EVIDENCE_RETENTION_DAYS

NEWS_TABLES = ("CRYPTO_NEWS", "NEWS_CATALYST_EVIDENCE", "MACRO_EVENT_EVIDENCE", "FUNDAMENTAL_EVIDENCE")
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "ai_trader"


class NewsRetentionTests(unittest.TestCase):
    def test_every_news_table_is_pruned(self):
        missing = [t for t in NEWS_TABLES if t not in PRODUCTION_EVIDENCE_RETENTION_DAYS]
        self.assertEqual(missing, [], f"These would grow forever: {missing}")

    def test_news_is_kept_for_less_time_than_learning_evidence(self):
        """News is only read to judge a trade being considered NOW -- nothing looks up a
        month-old headline, unlike learning evidence which is genuinely revisited."""
        learning = PRODUCTION_EVIDENCE_RETENTION_DAYS["PRODUCTION_LEARNING_EVIDENCE"][1]
        for table in NEWS_TABLES:
            self.assertLess(
                PRODUCTION_EVIDENCE_RETENTION_DAYS[table][1], learning,
                f"{table} is high-volume and low-reread; it must not be kept as long as learning evidence.",
            )

    def test_the_highest_volume_feeds_have_the_shortest_retention(self):
        """CRYPTO_NEWS and NEWS_CATALYST_EVIDENCE take one row per story per tagged symbol,
        every hour -- by far the fastest-growing of the four."""
        for table in ("CRYPTO_NEWS", "NEWS_CATALYST_EVIDENCE"):
            self.assertLessEqual(PRODUCTION_EVIDENCE_RETENTION_DAYS[table][1], 30)


class NewsEgressTests(unittest.TestCase):
    def test_no_news_table_is_read_without_a_filter(self):
        """Egress guard: a bare SELECT over a high-volume table pulls the whole thing out of
        Supabase on every call. Every read must be narrowed by symbol, date or LIMIT."""
        offenders = []
        for path in SOURCE_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for table in NEWS_TABLES:
                for match in re.finditer(rf"FROM\s+{table}\b(.{{0,120}})", text, re.IGNORECASE | re.DOTALL):
                    tail = match.group(1).upper()
                    if "WHERE" not in tail and "LIMIT" not in tail and "COUNT(" not in text[max(0, match.start() - 60):match.start()].upper():
                        offenders.append(f"{path.name}: FROM {table}")
        self.assertEqual(offenders, [], f"Unfiltered reads of high-volume news tables: {offenders}")

    def test_news_is_not_shipped_to_the_mobile_app(self):
        """The founder-evidence payload is downloaded by the phone on every refresh. News
        belongs server-side, used during research -- putting it in the payload would turn a
        storage question into a bandwidth one."""
        payload_source = (SOURCE_ROOT / "production_evidence.py").read_text(encoding="utf-8")
        for table in ("CRYPTO_NEWS", "NEWS_CATALYST_EVIDENCE"):
            self.assertNotIn(
                f"FROM {table}", payload_source,
                f"{table} must not be read into the evidence payload the app downloads.",
            )


if __name__ == "__main__":
    unittest.main()
