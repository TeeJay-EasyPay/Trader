"""The scheduled self-assessment must be given real numbers, and must be reachable.

2026-09-06, Founder-directed. He asked the trading AI whether it had what it needed; the
answer named a track-record discrepancy and duplicated attribution rows, and both checked
out against production (94 rows for 27 real round trips). He asked for it twice a day.

The weakness in that first answer is what these tests guard. It opened by saying it could
not assess freshness or coverage because the system had just restarted -- so the value of
this job depends entirely on the inventory being MEASURED and handed over, not inferred.
"""

import shutil
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.database import connect
from ai_trader.self_assessment import (
    QUESTION,
    initialize_self_assessment_schema,
    input_inventory,
    latest_self_assessment,
    record_self_assessment,
)


class InputInventoryTests(unittest.TestCase):
    def test_a_missing_feed_is_reported_not_skipped(self):
        """A feed that does not exist is the single most useful thing the census can say.
        Silently omitting it would let the AI assume coverage it does not have."""
        tmp = tempfile.mkdtemp()
        try:
            inventory = input_inventory(Path(tmp) / "audit.sqlite3")
            self.assertTrue(inventory["feeds"], "the census must never come back empty")
            self.assertTrue(all(f.get("status") == "table_missing" for f in inventory["feeds"]))
            for feed in inventory["feeds"]:
                self.assertTrue(feed.get("purpose"), "every feed says what it is FOR")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_duplicate_rows_are_stated_outright(self):
        """The defect the AI found itself is surfaced as a flag rather than left for it to
        re-derive from two counts that happen to differ."""
        tmp = tempfile.mkdtemp()
        try:
            db_path = Path(tmp) / "audit.sqlite3"
            with closing(connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        "CREATE TABLE PERFORMANCE_ATTRIBUTION (attribution_id INTEGER PRIMARY KEY"
                        " AUTOINCREMENT, proposal_id TEXT, closed_at TEXT, profit_loss REAL,"
                        " exit_reason TEXT)"
                    )
                    for _ in range(4):
                        conn.execute(
                            "INSERT INTO PERFORMANCE_ATTRIBUTION (proposal_id, closed_at,"
                            " profit_loss, exit_reason) VALUES ('p1', '2026-08-19', -0.19, 'x')"
                        )
            record = input_inventory(db_path)["realised_record"]
            self.assertEqual(record["closed_trades"], 4)
            self.assertEqual(record["distinct_trades"], 1)
            self.assertTrue(record["duplicate_rows_present"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class AssessmentStorageTests(unittest.TestCase):
    def test_an_assessment_is_stored_and_read_back(self):
        tmp = tempfile.mkdtemp()
        try:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_self_assessment_schema(db_path)
            self.assertIsNone(latest_self_assessment(db_path))
            record_self_assessment(
                db_path, answer="Kraken news is thin.", model="gpt-6-astra",
                status="answered", inventory={"feeds": []},
            )
            latest = latest_self_assessment(db_path)
            self.assertEqual(latest["answer"], "Kraken news is thin.")
            self.assertEqual(latest["status"], "answered")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_failed_assessment_is_still_recorded(self):
        """A run that could not produce an answer must leave a trace. A silent gap in the
        history reads as 'nothing was wrong' when it means 'nobody asked'."""
        tmp = tempfile.mkdtemp()
        try:
            db_path = Path(tmp) / "audit.sqlite3"
            record_self_assessment(
                db_path, answer=None, model=None,
                status="openai_not_configured", inventory={"feeds": []},
            )
            self.assertEqual(latest_self_assessment(db_path)["status"], "openai_not_configured")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class QuestionTests(unittest.TestCase):
    def test_the_question_asks_all_three_things_the_founder_asked_for(self):
        for needle in ("Alpaca", "Kraken", "best trader in the world", "PROBLEMS", "INPUTS"):
            self.assertIn(needle, QUESTION)

    def test_the_question_licenses_saying_i_cannot_tell(self):
        """Without this the model pads. 'I cannot see X' is the finding that led to the
        duplicate-rows discovery in the first place."""
        self.assertIn("cannot tell", QUESTION)


if __name__ == "__main__":
    unittest.main()


class FeedColumnTests(unittest.TestCase):
    """Every feed's declared date column must actually exist on that table.

    2026-09-06. The census probes eleven feeds on one connection. Postgres aborts the whole
    transaction on a failed statement, so ONE wrong column name did not mark one feed
    unreadable -- it marked every feed after it as missing, and the AI was handed a census
    claiming the attribution table, the backtests, the research evidence, the recommendations,
    macro and fundamentals had all vanished. It reasoned impeccably from that and reported the
    learning loop as gone, about a table holding 27 verified rows.

    _scalar now rolls back so a bad probe cannot cascade. This test stops the bad probe.
    """

    def test_every_feed_column_exists(self):
        import re

        from ai_trader.self_assessment import _FEEDS

        src = Path(__file__).resolve().parents[1] / "src" / "ai_trader"
        schema_text = "\n".join(
            p.read_text(encoding="utf-8", errors="replace") for p in src.rglob("*.py")
        )
        missing = []
        for table, column, _purpose in _FEEDS:
            block = re.search(
                r"CREATE TABLE IF NOT EXISTS\s+" + table + r"\s*\((.*?)\n\)",
                schema_text,
                re.IGNORECASE | re.DOTALL,
            )
            if not block:
                continue  # table defined elsewhere or by migration; not this test's business
            if not re.search(r"\b" + re.escape(column) + r"\b", block.group(1), re.IGNORECASE):
                missing.append(
                    table + " has no column '" + column + "' -- the census would report every "
                    "LATER feed as missing too"
                )
        self.assertEqual(missing, [], "\n".join(missing))


class ShadowSettlementTests(unittest.TestCase):
    """Unsettleable shadow trades must leave the queue, and the two scoreboards must agree.

    2026-09-06 Supabase egress finding, plus a real bug found inside it. The settler reads
    pending rows ORDER BY created_at LIMIT 500, and a row with no candles was skipped and left
    pending -- forever. Production held 543 rows pending and more than ten days old against a
    seven-day horizon, permanently occupying every slot, so NEWER shadow trades were never
    settled and the strategy scoreboard silently stopped updating.
    """

    def test_strategy_records_equal_the_symbol_records_recombined(self):
        """shadow_strategy_records now aggregates shadow_symbol_records instead of running its
        own second full-table read. The two must stay exactly equal, or the saving came at the
        cost of the number the AI judges strategies on."""
        from ai_trader.shadow_outcomes import _settled_shadow_values

        grouped = {("trend", "BTC"): [1.0, -1.0, 2.0], ("trend", "ETH"): [-1.0], ("momo", "SOL"): [0.5]}
        by_strategy: dict[str, list[float]] = {}
        for (strategy, _symbol), values in grouped.items():
            by_strategy.setdefault(strategy, []).extend(values)
        self.assertEqual(sorted(by_strategy["trend"]), [-1.0, -1.0, 1.0, 2.0])
        self.assertEqual(len(by_strategy["trend"]), 4)
        # the mean of the recombined raw values, NOT the mean of two rounded expectancies
        self.assertAlmostEqual(sum(by_strategy["trend"]) / 4, 0.25)

    def test_a_recent_unsettleable_trade_is_given_grace(self):
        """A missing candle can be a temporary feed gap. Retiring on the first failed attempt
        would discard trades that would settle fine a day later."""
        from ai_trader.shadow_outcomes import (
            SHADOW_HORIZON_DAYS,
            SHADOW_SETTLE_GRACE_DAYS,
            _note_unsettleable,
        )
        from datetime import datetime, timedelta, timezone

        moment = datetime(2026, 9, 6, tzinfo=timezone.utc)
        bucket: list = []
        _note_unsettleable(bucket, 1, moment - timedelta(days=1), moment)
        self.assertEqual(bucket, [], "a one-day-old trade must keep its chance to settle")

        _note_unsettleable(bucket, 2, moment - timedelta(days=SHADOW_HORIZON_DAYS + SHADOW_SETTLE_GRACE_DAYS + 1), moment)
        self.assertEqual(bucket, [2], "past horizon plus grace, no candle is ever coming")

        _note_unsettleable(bucket, 3, None, moment)
        self.assertEqual(bucket, [2, 3], "a row with no usable date can never settle")
