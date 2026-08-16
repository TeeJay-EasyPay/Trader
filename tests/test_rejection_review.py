"""2026-08-16 (Founder-requested, following the "is BTC/XLM stuck a bug or correct
caution?" question): a nightly job that checks what price actually did after a
Kraken crypto proposal was rejected on a guardrail check, records one compact
verdict per symbol per day, feeds it into the existing experience/analogues
machinery, and a monthly job that rolls up and prunes the raw rows so the table
stays bounded regardless of runtime. See rejection_review.py's module docstring."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.audit import AuditDatabase
from ai_trader.database import connect
from ai_trader.experience_engine import find_historical_analogues
from ai_trader.foundation import initialize_foundation_schema
from ai_trader.models import TradeProposal, ValidationResult
from ai_trader.rejection_review import (
    _price_for_pair,
    deterministic_learned_synthesis,
    initialize_rejection_review_schema,
    recent_crypto_rejection_digest,
    run_crypto_rejection_review,
    run_crypto_rejection_rollup,
)


class _FakeAdapter:
    def __init__(self, prices: dict):
        self._prices = prices

    def current_prices(self, pairs):
        return {pair: self._prices[pair] for pair in pairs if pair in self._prices}


def _record_rejected_proposal(db_path: Path, *, symbol: str, entry_price: float, hours_ago: float, failures=None) -> None:
    audit = AuditDatabase(db_path, None)
    proposal = TradeProposal(
        symbol=symbol,
        side="buy",
        entry_price=entry_price,
        stop_loss=entry_price * 0.98,
        take_profit=entry_price * 1.04,
        position_size=1,
        risk_percentage=0.01,
        confidence_score=0.9,
        asset_type="crypto",
        exchange="KRAKEN",
        news_summary="",
        market_sentiment_summary="",
        technical_summary="",
        plain_english_reasoning="Test crypto proposal.",
        ai_guardrails_passed=False,
    )
    audit.record_trade_event(
        "agent_proposal",
        proposal,
        validation=ValidationResult(passed=False, failures=failures or ["duplicate_open_position"]),
    )
    backdated = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                "UPDATE trade_audit SET created_at = ? WHERE proposal_id = ?",
                (backdated, proposal.proposal_id),
            )


class PriceForPairSafetyTests(unittest.TestCase):
    def test_missing_pair_returns_none_not_a_different_symbols_price(self):
        # The bug this guards against: broker_adapters.py's _kraken_last_price falls
        # back to "any price in the dict" when the exact key is missing, which is
        # fine for its existing single-pair callers but would silently attribute
        # BTC's price to XLM in a multi-symbol batch response missing XLM's pair.
        prices = {"XBTGBP": {"c": ["50000.0", "1.0"]}}
        self.assertIsNone(_price_for_pair(prices, "XLMGBP"))
        self.assertEqual(_price_for_pair(prices, "XBTGBP"), 50000.0)


class RejectionReviewTests(unittest.TestCase):
    def test_price_fell_is_recorded_as_favourable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            _record_rejected_proposal(db_path, symbol="BTC", entry_price=50000.0, hours_ago=30)

            adapter = _FakeAdapter({"XBTGBP": {"c": ["48000.0", "1.0"]}})  # -4%
            result = run_crypto_rejection_review(db_path, adapter)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["symbols_reviewed"], 1)
            with closing(connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM CRYPTO_REJECTION_REVIEWS WHERE symbol = 'BTC'").fetchone()
            self.assertEqual(row["verdict"], "favourable")
            self.assertAlmostEqual(row["pct_change"], -0.04, places=4)
            self.assertEqual(row["dominant_reason"], "duplicate_open_position")

    def test_price_rose_is_recorded_as_unfavourable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            _record_rejected_proposal(db_path, symbol="ETH", entry_price=2000.0, hours_ago=30)

            adapter = _FakeAdapter({"ETHGBP": {"c": ["2100.0", "1.0"]}})  # +5%
            run_crypto_rejection_review(db_path, adapter)

            with closing(connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM CRYPTO_REJECTION_REVIEWS WHERE symbol = 'ETH'").fetchone()
            self.assertEqual(row["verdict"], "unfavourable")

    def test_flat_price_is_recorded_as_neutral(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            _record_rejected_proposal(db_path, symbol="XLM", entry_price=0.30, hours_ago=30)

            adapter = _FakeAdapter({"XLMGBP": {"c": ["0.301", "1.0"]}})  # +0.3%, inside the neutral band
            run_crypto_rejection_review(db_path, adapter)

            with closing(connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM CRYPTO_REJECTION_REVIEWS WHERE symbol = 'XLM'").fetchone()
            self.assertEqual(row["verdict"], "neutral")

    def test_rejection_inside_the_last_24h_is_not_reviewed_yet(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            _record_rejected_proposal(db_path, symbol="SOL", entry_price=150.0, hours_ago=6)  # too recent

            adapter = _FakeAdapter({"SOLGBP": {"c": ["140.0", "1.0"]}})
            result = run_crypto_rejection_review(db_path, adapter)

            self.assertEqual(result["status"], "no_action")
            self.assertEqual(result["symbols_reviewed"], 0)

    def test_rejection_older_than_the_lookback_window_is_not_reviewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            _record_rejected_proposal(db_path, symbol="BCH", entry_price=150.0, hours_ago=72)  # too old

            adapter = _FakeAdapter({"BCHGBP": {"c": ["140.0", "1.0"]}})
            result = run_crypto_rejection_review(db_path, adapter)

            self.assertEqual(result["status"], "no_action")

    def test_running_twice_for_the_same_day_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            _record_rejected_proposal(db_path, symbol="BTC", entry_price=50000.0, hours_ago=30)
            adapter = _FakeAdapter({"XBTGBP": {"c": ["48000.0", "1.0"]}})

            first = run_crypto_rejection_review(db_path, adapter)
            second = run_crypto_rejection_review(db_path, adapter)

            self.assertEqual(first["symbols_reviewed"], 1)
            self.assertEqual(second["status"], "no_action")
            with closing(connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                count = conn.execute("SELECT COUNT(*) AS n FROM CRYPTO_REJECTION_REVIEWS WHERE symbol = 'BTC'").fetchone()["n"]
            self.assertEqual(count, 1)

    def test_missing_price_data_records_unknown_verdict_and_no_analogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            _record_rejected_proposal(db_path, symbol="HBAR", entry_price=0.10, hours_ago=30)

            adapter = _FakeAdapter({})  # Kraken didn't return a price for this pair
            run_crypto_rejection_review(db_path, adapter)

            with closing(connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM CRYPTO_REJECTION_REVIEWS WHERE symbol = 'HBAR'").fetchone()
            self.assertEqual(row["verdict"], "unknown")
            self.assertIsNone(row["pct_change"])

    def test_review_feeds_the_existing_historical_analogues_lookup(self):
        # The point of writing an EXPERIENCE_RECORDS row: a future crypto proposal
        # for the same symbol already calls find_historical_analogues(symbol=...)
        # via build_proposal_context with no strategy_id/regime_id filter, so this
        # record surfaces automatically with zero changes to that existing pathway.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            _record_rejected_proposal(db_path, symbol="BTC", entry_price=50000.0, hours_ago=30)
            adapter = _FakeAdapter({"XBTGBP": {"c": ["48000.0", "1.0"]}})

            run_crypto_rejection_review(db_path, adapter)

            analogues = find_historical_analogues(db_path, {"symbol": "BTC", "strategy_id": None, "regime_id": None})
            self.assertEqual(analogues["comparable_cases"], 1)
            case = analogues["similar_historical_situations"][0]
            self.assertEqual(case["strategy_id"], "crypto_rejection_review")
            self.assertIn("reject_favourable", case["result_context_json"])


class RejectionReviewRollupTests(unittest.TestCase):
    def _seed_old_review(self, db_path: Path, *, symbol: str, verdict: str, pct_change: float, days_ago: int) -> None:
        initialize_rejection_review_schema(db_path)
        review_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).date().isoformat()
        with closing(connect(db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO CRYPTO_REJECTION_REVIEWS (
                        created_at, review_date, broker, symbol, rejection_count,
                        dominant_reason, reference_price, reference_at, price_now,
                        priced_at, pct_change, verdict
                    ) VALUES (datetime('now'), ?, 'kraken', ?, 1, 'duplicate_open_position', 100, datetime('now'), 100, datetime('now'), ?, ?)
                    """,
                    (review_date, symbol, pct_change, verdict),
                )

    def test_old_rows_are_summarized_and_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            self._seed_old_review(db_path, symbol="BTC", verdict="favourable", pct_change=-0.03, days_ago=40)
            self._seed_old_review(db_path, symbol="BTC", verdict="unfavourable", pct_change=0.02, days_ago=38)

            result = run_crypto_rejection_rollup(db_path)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["rows_summarized"], 2)
            with closing(connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                remaining = conn.execute("SELECT COUNT(*) AS n FROM CRYPTO_REJECTION_REVIEWS").fetchone()["n"]
                summary = conn.execute("SELECT * FROM CRYPTO_REJECTION_REVIEW_SUMMARIES WHERE symbol = 'BTC'").fetchone()
            self.assertEqual(remaining, 0)
            self.assertEqual(summary["days_reviewed"], 2)
            self.assertEqual(summary["favourable_count"], 1)
            self.assertEqual(summary["unfavourable_count"], 1)

    def test_recent_rows_are_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            self._seed_old_review(db_path, symbol="ETH", verdict="neutral", pct_change=0.0, days_ago=5)

            result = run_crypto_rejection_rollup(db_path)

            self.assertEqual(result["status"], "no_action")
            with closing(connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                remaining = conn.execute("SELECT COUNT(*) AS n FROM CRYPTO_REJECTION_REVIEWS").fetchone()["n"]
            self.assertEqual(remaining, 1)


class RejectionDigestTests(unittest.TestCase):
    def test_digest_includes_reviewed_and_unreviewed_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            # Old enough to have been reviewed already.
            _record_rejected_proposal(db_path, symbol="BTC", entry_price=50000.0, hours_ago=30)
            run_crypto_rejection_review(db_path, _FakeAdapter({"XBTGBP": {"c": ["48000.0", "1.0"]}}))
            # Too recent to have been reviewed yet.
            _record_rejected_proposal(db_path, symbol="ETH", entry_price=2000.0, hours_ago=6)

            digest = recent_crypto_rejection_digest(db_path, hours=48)

            by_symbol = {item["symbol"]: item for item in digest["rejections"]}
            self.assertTrue(by_symbol["BTC"]["reviewed"])
            self.assertEqual(by_symbol["BTC"]["verdict"], "favourable")
            self.assertFalse(by_symbol["ETH"]["reviewed"])
            self.assertIsNone(by_symbol["ETH"]["verdict"])
            self.assertIn("1 already reviewed", digest["summary"])

    def test_digest_is_empty_summary_when_nothing_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            digest = recent_crypto_rejection_digest(db_path, hours=48)
            self.assertEqual(digest["rejections"], [])
            self.assertIn("No rejected", digest["summary"])


class DeterministicLearnedSynthesisTests(unittest.TestCase):
    def test_no_reviews_yet_says_so_honestly(self):
        text = deterministic_learned_synthesis({"rejections": [{"symbol": "BTC", "reviewed": False, "verdict": None}]})
        self.assertIn("enough evidence yet", text)

    def test_more_unfavourable_than_favourable_flags_it(self):
        digest = {
            "rejections": [
                {"symbol": "BTC", "reviewed": True, "verdict": "unfavourable"},
                {"symbol": "ETH", "reviewed": True, "verdict": "unfavourable"},
                {"symbol": "SOL", "reviewed": True, "verdict": "favourable"},
            ]
        }
        text = deterministic_learned_synthesis(digest)
        self.assertIn("2 were unfavourable", text)
        self.assertIn("worth a closer look", text)

    def test_more_favourable_than_unfavourable_is_reassuring(self):
        digest = {
            "rejections": [
                {"symbol": "BTC", "reviewed": True, "verdict": "favourable"},
                {"symbol": "ETH", "reviewed": True, "verdict": "favourable"},
                {"symbol": "SOL", "reviewed": True, "verdict": "unfavourable"},
            ]
        }
        text = deterministic_learned_synthesis(digest)
        self.assertIn("doing their job", text)


if __name__ == "__main__":
    unittest.main()
