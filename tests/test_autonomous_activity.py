import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.always_on import (
    claim_scheduled_job,
    complete_scheduled_job,
    initialize_always_on_schema,
    record_research_funnel,
    record_worker_heartbeat,
)
from ai_trader.autonomous_activity import (
    activity_summary,
    activity_timeline,
    autonomous_activity_payload,
    current_autonomous_status,
    founder_attention,
    why_no_trade_funnel,
)
from ai_trader.multi_broker import initialize_multi_broker_schema
from ai_trader.production_spine import initialize_production_spine_schema
from ai_trader.sprint6 import initialize_sprint6_schema, record_operational_event


def _db(tmp: str) -> Path:
    return Path(tmp) / "audit.sqlite3"


class AutonomousActivityTests(unittest.TestCase):
    def setUp(self):
        self._old_backend = os.environ.pop("AI_TRADER_DATABASE_BACKEND", None)
        self._old_database_url = os.environ.pop("DATABASE_URL", None)

    def tearDown(self):
        if self._old_backend is not None:
            os.environ["AI_TRADER_DATABASE_BACKEND"] = self._old_backend
        if self._old_database_url is not None:
            os.environ["DATABASE_URL"] = self._old_database_url

    def _seed_common(self, db_path: Path) -> None:
        initialize_always_on_schema(db_path)
        initialize_sprint6_schema(db_path)
        initialize_production_spine_schema(db_path)
        initialize_multi_broker_schema(db_path)
        record_worker_heartbeat(
            db_path,
            worker_id="worker-activity",
            worker_type="background-worker",
            last_successful_job="broker-poll",
        )

    def test_activity_payload_uses_persisted_evidence_without_mock_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _db(tmp)
            self._seed_common(db_path)
            claim = claim_scheduled_job(db_path, job_name="overnight-crypto", worker_id="worker-activity")
            complete_scheduled_job(
                db_path,
                claim["job_run_id"],
                status="completed_no_action",
                result={"assets_processed": 12, "recommendations_created": 0, "skipped": [{"reason": "no_valid_strategy"}]},
            )
            record_research_funnel(
                db_path,
                broker="kraken",
                asset_type="crypto",
                trigger_type="overnight-crypto",
                symbols_examined=12,
                symbols_with_adequate_data=12,
                interesting_ideas=0,
                valid_strategies=0,
                committee_approved=0,
                portfolio_approved=0,
                guardrail_approved=0,
                eligible_for_paper_execution=0,
                submitted=0,
                filled=0,
                rejected=0,
                primary_reason="no_opportunity_found",
            )

            payload = autonomous_activity_payload(db_path, broker_panels=[], database_backend="sqlite")

            self.assertFalse(payload["truthfulness"]["mock_data_used"])
            self.assertFalse(payload["truthfulness"]["synthetic_activity_used"])
            self.assertGreaterEqual(payload["summary"]["research"]["runs"], 1)
            self.assertGreaterEqual(payload["summary"]["research"]["assets_analysed"], 12)
            self.assertTrue(any(item["source_table"] == "RESEARCH_FUNNELS" for item in payload["timeline"]["items"]))

    def test_no_trade_funnel_distinguishes_no_opportunity_from_blocked_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _db(tmp)
            self._seed_common(db_path)
            record_research_funnel(
                db_path,
                broker="alpaca",
                asset_type="stock",
                trigger_type="market-open-equity",
                symbols_examined=42,
                symbols_with_adequate_data=40,
                interesting_ideas=0,
                valid_strategies=0,
                committee_approved=0,
                portfolio_approved=0,
                guardrail_approved=0,
                eligible_for_paper_execution=0,
                submitted=0,
                filled=0,
                rejected=0,
                primary_reason="no_opportunity_found",
            )

            no_trade = why_no_trade_funnel(db_path)
            self.assertEqual(no_trade["state"], "no_opportunity_found")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = _db(tmp)
            self._seed_common(db_path)
            record_research_funnel(
                db_path,
                broker="alpaca",
                asset_type="stock",
                trigger_type="market-open-equity",
                symbols_examined=42,
                symbols_with_adequate_data=40,
                interesting_ideas=4,
                valid_strategies=2,
                committee_approved=1,
                portfolio_approved=1,
                guardrail_approved=0,
                eligible_for_paper_execution=0,
                submitted=0,
                filled=0,
                rejected=1,
                primary_reason="risk_engine_rejected",
            )

            no_trade = why_no_trade_funnel(db_path)
            self.assertEqual(no_trade["state"], "approved_or_candidate_blocked")
            self.assertEqual(no_trade["top_reasons"][0]["reason"], "risk_engine_rejected")

    def test_no_trade_funnel_reports_order_activity_when_orders_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _db(tmp)
            self._seed_common(db_path)
            claim = claim_scheduled_job(db_path, job_name="auto-execution", worker_id="worker-activity")
            complete_scheduled_job(
                db_path,
                claim["job_run_id"],
                status="completed",
                result={"paper_orders_submitted": 1, "paper_orders_filled": 1},
            )

            no_trade = why_no_trade_funnel(db_path)

            self.assertEqual(no_trade["state"], "order_submitted_or_trade_completed")
            self.assertEqual(no_trade["counts"]["orders_submitted"], 1)
            self.assertEqual(no_trade["counts"]["orders_filled"], 1)

    def test_timeline_filters_and_orders_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _db(tmp)
            self._seed_common(db_path)
            record_operational_event(
                db_path,
                component="Production Risk Sentinel",
                event_type="sentinel_block",
                severity="blocked",
                summary="New entries blocked because broker polling is stale.",
                broker="alpaca",
                success=False,
            )
            record_operational_event(
                db_path,
                component="Reports",
                event_type="report_generated",
                severity="success",
                summary="Daily Founder briefing generated.",
                success=True,
            )

            all_items = activity_timeline(db_path, limit=10)["items"]
            risk_items = activity_timeline(db_path, category="Risk", limit=10)["items"]
            important_items = activity_timeline(db_path, important_only=True, limit=10)["items"]

            timestamps = [item["timestamp"] for item in all_items]
            self.assertEqual(timestamps, sorted(timestamps, reverse=True))
            self.assertTrue(all(item["event_category"] == "Risk" for item in risk_items))
            self.assertTrue(any(item["severity"] == "blocked" for item in important_items))

    def test_current_status_does_not_equate_api_health_with_autonomous_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _db(tmp)
            initialize_always_on_schema(db_path)

            status = current_autonomous_status(db_path, broker_panels=[], database_backend="sqlite")
            attention = founder_attention(db_path, broker_panels=[])

            self.assertEqual(status["state"], "NOT OPERATING")
            self.assertIn("heartbeat", status["plain_english"].lower())
            self.assertTrue(attention["items"])

    def test_stale_worker_generates_founder_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _db(tmp)
            initialize_always_on_schema(db_path)
            old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO WORKER_HEARTBEATS (
                            worker_id, worker_type, started_at, last_heartbeat_at, status
                        ) VALUES ('old-worker', 'background-worker', ?, ?, 'running')
                        """,
                        (old, old),
                    )

            attention = founder_attention(db_path, broker_panels=[])

            self.assertTrue(any("heartbeat" in item["title"].lower() for item in attention["items"]))


if __name__ == "__main__":
    unittest.main()
