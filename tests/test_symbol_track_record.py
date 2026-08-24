import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.multi_broker import initialize_multi_broker_schema
from ai_trader.symbol_track_record import (
    LOOKBACK_DAYS,
    MAX_CONFIDENCE_PENALTY,
    all_symbol_track_records,
    normalize_symbol,
    symbol_track_record,
)

NOW = datetime(2026, 8, 24, 17, 0, tzinfo=timezone.utc)


def _record(db_path: Path, symbol: str, profit_loss: float, *, days_ago: int = 1) -> None:
    closed_at = (NOW - timedelta(days=days_ago)).isoformat()
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO PERFORMANCE_ATTRIBUTION (
                    created_at, proposal_id, broker, symbol, asset_type, side,
                    entry_price, exit_price, quantity, profit_loss, opened_at,
                    closed_at, holding_period_seconds, entry_reason, exit_reason,
                    primary_factors_json
                ) VALUES (?, ?, 'kraken', ?, 'crypto', 'sell', 100, 101, 1, ?, ?, ?, 60, 'test', 'test', '{}')
                """,
                (closed_at, f"p-{symbol}-{profit_loss}-{days_ago}", symbol, profit_loss, closed_at, closed_at),
            )


class SymbolTrackRecordTests(unittest.TestCase):
    def test_the_same_coin_under_different_names_is_one_record(self):
        """Confirmed live in PERFORMANCE_ATTRIBUTION on 2026-08-24: SOL and SOLGBP, BTC
        and XBTGBP, XRP and XRPGBP were all present, splitting each coin's history in
        two. Per-coin logic that skips normalisation reads half a record and quietly
        learns nothing -- the exact failure this module exists to prevent, and the
        reason SOL's true 0-from-5 looked like 0-from-4 and 0-from-1."""
        self.assertEqual(normalize_symbol("SOLGBP"), "SOL")
        self.assertEqual(normalize_symbol("XBTGBP"), "BTC")
        self.assertEqual(normalize_symbol("XXBT"), "BTC")
        self.assertEqual(normalize_symbol("xrpgbp"), "XRP")
        self.assertEqual(normalize_symbol("ETH/USD"), "ETH")
        self.assertEqual(normalize_symbol("ADA"), "ADA")
        # A coin whose whole name is a quote currency must survive being stripped.
        self.assertEqual(normalize_symbol("USD"), "USD")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_multi_broker_schema(db_path)
            for symbol, pnl in [("SOLGBP", -0.30), ("SOLGBP", -0.20), ("SOLGBP", -0.26), ("SOLGBP", -0.10), ("SOL", -0.44)]:
                _record(db_path, symbol, pnl)

            record = symbol_track_record(db_path, "SOL", now=NOW)

            self.assertEqual(record.trades, 5, "both spellings must count as the same coin")
            self.assertEqual(record.wins, 0)
            self.assertAlmostEqual(record.net_profit_loss, -1.30, places=2)

    def test_a_coin_that_has_only_ever_lost_is_stood_aside_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_multi_broker_schema(db_path)
            for _ in range(4):
                _record(db_path, "SOL", -0.25)

            record = symbol_track_record(db_path, "SOL", now=NOW)

            self.assertEqual(record.verdict, "avoid")
            self.assertEqual(record.confidence_penalty, MAX_CONFIDENCE_PENALTY)
            self.assertIn("lost every one", record.summary)

    def test_a_thin_losing_record_lowers_conviction_without_standing_aside(self):
        """Three losses could be one bad week. That is a reason to size down, not a
        reason to declare a coin untradeable on evidence this thin."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_multi_broker_schema(db_path)
            _record(db_path, "LINK", -0.20)
            _record(db_path, "LINK", -0.18)
            _record(db_path, "LINK", 0.05)

            record = symbol_track_record(db_path, "LINK", now=NOW)

            self.assertEqual(record.verdict, "caution")
            self.assertGreater(record.confidence_penalty, 0.0)
            self.assertLessEqual(record.confidence_penalty, MAX_CONFIDENCE_PENALTY)

    def test_too_few_trades_changes_nothing(self):
        """A rule learned from two trades is a rule learned from noise."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_multi_broker_schema(db_path)
            _record(db_path, "ADA", -0.80)
            _record(db_path, "ADA", -0.75)

            record = symbol_track_record(db_path, "ADA", now=NOW)

            self.assertEqual(record.verdict, "insufficient_evidence")
            self.assertEqual(record.confidence_penalty, 0.0)

    def test_a_winning_coin_is_never_given_extra_confidence(self):
        """Rewarding a hot streak is how a small sample becomes a large position at the
        worst possible moment. This input may only ever subtract."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_multi_broker_schema(db_path)
            for _ in range(6):
                _record(db_path, "ETH", 0.40)

            record = symbol_track_record(db_path, "ETH", now=NOW)

            self.assertEqual(record.verdict, "neutral")
            self.assertEqual(record.confidence_penalty, 0.0)

    def test_old_losses_stop_counting(self):
        """A coin that behaved badly in a different market regime should not be held
        against forever -- the evidence expires."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_multi_broker_schema(db_path)
            for _ in range(5):
                _record(db_path, "KSM", -0.50, days_ago=LOOKBACK_DAYS + 10)

            record = symbol_track_record(db_path, "KSM", now=NOW)

            self.assertEqual(record.trades, 0)
            self.assertEqual(record.verdict, "insufficient_evidence")
            self.assertEqual(record.confidence_penalty, 0.0)

    def test_all_records_are_listed_worst_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_multi_broker_schema(db_path)
            for _ in range(4):
                _record(db_path, "SOLGBP", -0.30)
            for _ in range(4):
                _record(db_path, "ETH", 0.50)

            records = all_symbol_track_records(db_path, now=NOW)

            symbols = [row["symbol"] for row in records]
            self.assertEqual(symbols[0], "SOL", "the worst record must be first")
            self.assertIn("ETH", symbols)
            self.assertEqual(len(symbols), len(set(symbols)), "one row per coin, not per spelling")

    def test_a_missing_history_never_blocks_a_proposal(self):
        """This is one input among many. If it cannot be read, trading continues."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "no-such-schema.sqlite3"

            record = symbol_track_record(db_path, "BTC", now=NOW)

            self.assertEqual(record.verdict, "insufficient_evidence")
            self.assertEqual(record.confidence_penalty, 0.0)
            self.assertEqual(all_symbol_track_records(db_path, now=NOW), [])


if __name__ == "__main__":
    unittest.main()
