"""Founder-directed 2026-08-21: real, web-grounded daily benchmark-trader research,
replacing the static one-time-seeded content that was silently blocking every Alpaca
due-diligence assessment (foundation.py's _behavioural_context_available only reports
"completed" for a BENCHMARK_DAILY_RESEARCH row dated exactly today, and nothing before
this wrote one).

The most important tests in this file are the honesty ones: BenchmarkResearchAnalyzer
must be allowed to say "nothing found" without that being treated as a failure (an
honest empty result is still a real, today-dated row and is exactly what the due-diligence
check needs), and it must never be coaxed into fabricating a finding.
"""

import json
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.ai import _benchmark_research_from_response_text, _lenient_json_object
from ai_trader.api import LocalApiService
from ai_trader.benchmark import BenchmarkIntelligenceDatabase
from ai_trader.benchmark_data import BENCHMARK_TRADERS
from ai_trader.cli import _due_worker_jobs, _run_named_job
from ai_trader.config import Settings
from ai_trader.models import AutoTradeConfig, GuardrailConfig


def settings_for(tmp: str, **overrides) -> Settings:
    root = Path(tmp)
    base = Settings(
        alpaca_api_key=None,
        alpaca_secret_key=None,
        alpaca_paper_base_url="https://paper-api.alpaca.markets",
        alpaca_data_base_url="https://data.alpaca.markets",
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
        db_path=root / "audit.sqlite3",
        output_dir=root,
        trading_log_path=root / "TRADING_LOG.md",
        guardrails=GuardrailConfig(),
        auto_trade=AutoTradeConfig(),
        database_backend="sqlite",
    )
    return replace(base, **overrides)


def _found_activity_result(**overrides) -> dict:
    result = {
        "found_activity": True,
        "observed_trade_or_portfolio_change": "13F filing shows a new position initiated last quarter.",
        "ai_interpretation": "Consistent with the stated long-term value strategy.",
        "risk_lesson": "Concentration risk stays real even for disciplined investors.",
        "market_lesson": "Patience through a filing-lag information gap is itself a discipline.",
        "related_sector": "Financials",
        "related_theme": "Quality value investing",
        "confidence": "Medium",
        "source_urls": ["https://example.com/13f-filing"],
    }
    result.update(overrides)
    return result


def _no_activity_result(**overrides) -> dict:
    result = {
        "found_activity": False,
        "observed_trade_or_portfolio_change": "No notable public activity found in the last 30 days.",
        "ai_interpretation": "No fresh lesson without new activity.",
        "risk_lesson": None,
        "market_lesson": None,
        "related_sector": None,
        "related_theme": None,
        "confidence": "Low",
        "source_urls": [],
    }
    result.update(overrides)
    return result


class FakeBenchmarkAnalyzer:
    model = "test-model"

    def __init__(self, response=None, raises: Exception | None = None, by_trader: dict | None = None):
        self.response = response
        self.raises = raises
        self.by_trader = by_trader or {}
        self.requested: list[str] = []

    def research(self, *, trader_name, platform, strategy_style):
        self.requested.append(trader_name)
        if self.raises:
            raise self.raises
        if trader_name in self.by_trader:
            return self.by_trader[trader_name]
        return self.response


class BenchmarkResearchResponseParsingTests(unittest.TestCase):
    def test_accepts_a_well_formed_response_that_found_real_activity(self):
        parsed = _benchmark_research_from_response_text(json.dumps(_found_activity_result()))
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["found_activity"])
        self.assertEqual(parsed["confidence"], "Medium")

    def test_accepts_an_honest_nothing_found_response(self):
        # This is the single most important case: an honest empty result must be usable,
        # not rejected as if it were a failure -- that is the entire reason this analyzer
        # is instructed to say "nothing found" instead of inventing something.
        parsed = _benchmark_research_from_response_text(json.dumps(_no_activity_result()))
        self.assertIsNotNone(parsed)
        self.assertFalse(parsed["found_activity"])
        self.assertIn("No notable public activity", parsed["observed_trade_or_portfolio_change"])

    def test_rejects_a_confidence_label_outside_the_allowed_vocabulary(self):
        # Guards against a numeric fraction or free-text confidence slipping through --
        # the BENCHMARK_DAILY_RESEARCH.confidence column is TEXT and every other reader
        # (seed data, mobile) expects High/Medium/Low, not "0.62".
        bad = _found_activity_result(confidence="0.62")
        self.assertIsNone(_benchmark_research_from_response_text(json.dumps(bad)))

    def test_confidence_label_is_normalised_regardless_of_case(self):
        parsed = _benchmark_research_from_response_text(json.dumps(_found_activity_result(confidence="high")))
        self.assertEqual(parsed["confidence"], "High")

    def test_rejects_a_response_with_no_observed_text_at_all(self):
        bad = _found_activity_result(observed_trade_or_portfolio_change="")
        self.assertIsNone(_benchmark_research_from_response_text(json.dumps(bad)))

    def test_rejects_malformed_or_missing_responses(self):
        self.assertIsNone(_benchmark_research_from_response_text("not json at all"))
        self.assertIsNone(_benchmark_research_from_response_text("null"))
        self.assertIsNone(_benchmark_research_from_response_text(""))
        self.assertIsNone(_benchmark_research_from_response_text(json.dumps(["not", "a", "dict"])))

    # 2026-08-21 live-verification finding: web_search_preview and structured JSON mode
    # (text.format) are mutually exclusive on this API ("Web Search cannot be used with
    # JSON mode", HTTP 400) -- this analyzer had to drop text.format and now relies on the
    # instruction plus this tolerant parsing to still get a usable JSON object out.

    def test_accepts_a_response_wrapped_in_a_markdown_code_fence(self):
        wrapped = "```json\n" + json.dumps(_found_activity_result()) + "\n```"
        parsed = _benchmark_research_from_response_text(wrapped)
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["found_activity"])

    def test_accepts_a_response_with_a_stray_sentence_before_and_after_the_json(self):
        wrapped = "Here is my finding:\n" + json.dumps(_found_activity_result()) + "\nLet me know if you need more."
        parsed = _benchmark_research_from_response_text(wrapped)
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["found_activity"])


class LenientJsonObjectTests(unittest.TestCase):
    def test_parses_plain_json_unchanged(self):
        self.assertEqual(_lenient_json_object('{"a": 1}'), {"a": 1})

    def test_strips_a_json_code_fence(self):
        self.assertEqual(_lenient_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_strips_a_bare_code_fence_with_no_language_tag(self):
        self.assertEqual(_lenient_json_object('```\n{"a": 1}\n```'), {"a": 1})

    def test_extracts_the_outermost_object_from_surrounding_prose(self):
        self.assertEqual(_lenient_json_object('Sure, here it is: {"a": 1} - hope that helps!'), {"a": 1})

    def test_returns_none_for_text_with_no_recoverable_json_object(self):
        self.assertIsNone(_lenient_json_object("no json here at all"))
        self.assertIsNone(_lenient_json_object(""))

    def test_returns_none_for_a_json_array_not_an_object(self):
        self.assertIsNone(_lenient_json_object("[1, 2, 3]"))


class RecordDailyResearchTests(unittest.TestCase):
    def test_writes_a_row_dated_exactly_today_for_a_known_trader(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            db = BenchmarkIntelligenceDatabase(db_path)
            db.seed_initial_data()
            trader_name = BENCHMARK_TRADERS[0]["trader_name"]
            today = date(2026, 8, 21)

            written = db.record_daily_research(today, trader_name, _found_activity_result())

            self.assertTrue(written)
            rows = db.monitored_today(today)
            self.assertTrue(any(row["trader_name"] == trader_name for row in rows))

    def test_writes_an_honest_nothing_found_row_too_not_just_positive_findings(self):
        # The whole point: due diligence only needs a row to EXIST for today, not for it
        # to contain a positive finding. An honest "nothing found" must still count.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            db = BenchmarkIntelligenceDatabase(db_path)
            db.seed_initial_data()
            trader_name = BENCHMARK_TRADERS[0]["trader_name"]
            today = date(2026, 8, 21)

            written = db.record_daily_research(today, trader_name, _no_activity_result())

            self.assertTrue(written)
            rows = db.monitored_today(today)
            matching = [row for row in rows if row["trader_name"] == trader_name]
            self.assertEqual(len(matching), 1)

    def test_returns_false_for_a_trader_not_in_benchmark_traders(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            db = BenchmarkIntelligenceDatabase(db_path)
            db.seed_initial_data()
            written = db.record_daily_research(date(2026, 8, 21), "Not A Real Trader", _found_activity_result())
            self.assertFalse(written)

    def test_never_nulls_out_the_traders_own_seeded_metadata(self):
        # record_daily_research must look the trader up, not re-upsert it -- reusing
        # _upsert_trader with a partial dict would ON CONFLICT its way into nulling out
        # region/risk_rating/etc. that seed_initial_data already correctly populated.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            db = BenchmarkIntelligenceDatabase(db_path)
            db.seed_initial_data()
            trader_name = BENCHMARK_TRADERS[0]["trader_name"]
            with closing(db.connect()) as conn:
                before = dict(conn.execute("SELECT * FROM BENCHMARK_TRADERS WHERE trader_name = ?", (trader_name,)).fetchone())

            db.record_daily_research(date(2026, 8, 21), trader_name, _found_activity_result())

            with closing(db.connect()) as conn:
                after = dict(conn.execute("SELECT * FROM BENCHMARK_TRADERS WHERE trader_name = ?", (trader_name,)).fetchone())
            for field in ("region", "risk_rating", "performance_notes", "why_monitored"):
                self.assertEqual(before[field], after[field], f"{field} must be untouched by record_daily_research")


class RefreshBenchmarkResearchServiceTests(unittest.TestCase):
    def test_not_available_without_an_openai_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp, openai_api_key=None))
            result = service.refresh_benchmark_research()
            self.assertEqual(result["status"], "not_available")

    def test_writes_real_research_for_every_tracked_trader_on_a_full_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp, openai_api_key="test-key")
            BenchmarkIntelligenceDatabase(settings.db_path).seed_initial_data()
            service = LocalApiService(settings)
            fake = FakeBenchmarkAnalyzer(response=_found_activity_result())
            with patch("ai_trader.application.research_service.BenchmarkResearchAnalyzer", return_value=fake):
                result = service.refresh_benchmark_research()

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["research_written"], len(BENCHMARK_TRADERS))
            self.assertEqual(set(fake.requested), {trader["trader_name"] for trader in BENCHMARK_TRADERS})

    def test_one_traders_model_failure_does_not_block_the_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp, openai_api_key="test-key")
            BenchmarkIntelligenceDatabase(settings.db_path).seed_initial_data()
            service = LocalApiService(settings)
            failing_trader = BENCHMARK_TRADERS[0]["trader_name"]
            fake = FakeBenchmarkAnalyzer(
                response=_found_activity_result(),
                by_trader={failing_trader: None},  # simulates a no-usable-response outcome for just this one
            )
            with patch("ai_trader.application.research_service.BenchmarkResearchAnalyzer", return_value=fake):
                result = service.refresh_benchmark_research()

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["research_written"], len(BENCHMARK_TRADERS) - 1)
            failed = [item for item in result["outcomes"] if item["trader_name"] == failing_trader]
            self.assertEqual(failed[0]["status"], "no_usable_research")

    def test_an_honest_nothing_found_result_still_counts_as_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp, openai_api_key="test-key")
            BenchmarkIntelligenceDatabase(settings.db_path).seed_initial_data()
            service = LocalApiService(settings)
            fake = FakeBenchmarkAnalyzer(response=_no_activity_result())
            with patch("ai_trader.application.research_service.BenchmarkResearchAnalyzer", return_value=fake):
                result = service.refresh_benchmark_research()

            self.assertEqual(result["research_written"], len(BENCHMARK_TRADERS))
            self.assertFalse(result["outcomes"][0]["found_activity"])

    def test_research_one_benchmark_trader_rejects_an_unknown_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp, openai_api_key="test-key"))
            result = service.research_one_benchmark_trader("Not A Real Trader")
            self.assertEqual(result["status"], "not_available")

    def test_research_one_benchmark_trader_writes_a_todays_row_for_a_known_trader(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp, openai_api_key="test-key")
            BenchmarkIntelligenceDatabase(settings.db_path).seed_initial_data()
            service = LocalApiService(settings)
            trader_name = BENCHMARK_TRADERS[0]["trader_name"]
            fake = FakeBenchmarkAnalyzer(response=_found_activity_result())
            with patch("ai_trader.application.research_service.BenchmarkResearchAnalyzer", return_value=fake):
                result = service.research_one_benchmark_trader(trader_name)

            self.assertEqual(result["status"], "completed")
            db = BenchmarkIntelligenceDatabase(settings.db_path)
            rows = db.monitored_today(date.today())
            self.assertTrue(any(row["trader_name"] == trader_name for row in rows))


class SchedulingTests(unittest.TestCase):
    def test_due_worker_jobs_includes_benchmark_research_refresh_at_10_utc(self):
        settings = settings_for(tempfile.mkdtemp(), worker_research_enabled=True, research_scheduler_interval_minutes=60, external_intelligence_enabled=False)
        due = _due_worker_jobs(settings, datetime(2026, 8, 21, 10, 30, tzinfo=timezone.utc))
        self.assertIn("benchmark-research-refresh", [name for name, _ in due])

    def test_due_worker_jobs_omits_benchmark_research_refresh_outside_its_window(self):
        settings = settings_for(tempfile.mkdtemp(), worker_research_enabled=True, research_scheduler_interval_minutes=60, external_intelligence_enabled=False)
        due = _due_worker_jobs(settings, datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc))
        self.assertNotIn("benchmark-research-refresh", [name for name, _ in due])

    def test_fires_on_weekends_too(self):
        # 2026-08-16 is a Sunday.
        settings = settings_for(tempfile.mkdtemp(), worker_research_enabled=True, research_scheduler_interval_minutes=60, external_intelligence_enabled=False)
        due = _due_worker_jobs(settings, datetime(2026, 8, 16, 10, 30, tzinfo=timezone.utc))
        self.assertIn("benchmark-research-refresh", [name for name, _ in due])

    def test_run_named_job_dispatches_benchmark_research_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp, openai_api_key=None))
            # No API key configured -- proves dispatch reaches the real method (which then
            # honestly reports not_available) rather than raising KeyError/AttributeError
            # for an unregistered job name.
            result = _run_named_job(service, "benchmark-research-refresh", limit=0)
            self.assertEqual(result["status"], "not_available")


if __name__ == "__main__":
    unittest.main()
