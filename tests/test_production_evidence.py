import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.always_on import record_research_funnel, record_worker_heartbeat
from ai_trader.api import LocalApiService
from ai_trader.models import AutoTradeConfig, GuardrailConfig
from ai_trader.config import Settings
from ai_trader.production_evidence import (
    founder_evidence_payload,
    persist_founder_evidence_snapshot,
    refresh_founder_evidence_snapshots,
    record_broker_snapshot,
    record_learning_evidence,
    record_recommendation_evidence,
    record_research_evidence,
    record_trade_evidence,
)


def settings_for(tmp: str) -> Settings:
    root = Path(tmp)
    return Settings(
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
    )


class ProductionEvidenceTests(unittest.TestCase):
    def test_founder_snapshot_is_served_without_rebuilding_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            payload = {
                "generated_at": "2026-07-22T12:00:00+00:00",
                "period": "24h",
                "status": {"state": "OPERATING NORMALLY", "plain_english": "Worker evidence is current."},
                "summary": {"research": {"runs": 4}},
            }
            persist_founder_evidence_snapshot(db_path, payload, period="24h")

            with patch("ai_trader.production_evidence._build_founder_evidence_payload", side_effect=AssertionError("live rebuild")):
                result = founder_evidence_payload(db_path, period="24h")

            self.assertEqual(result["summary"]["research"]["runs"], 4)
            self.assertEqual(result["snapshot"]["served_from"], "worker_projection")

    def test_stale_founder_snapshot_is_labelled_without_hiding_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            persist_founder_evidence_snapshot(
                db_path,
                {
                    "generated_at": "2020-01-01T00:00:00+00:00",
                    "period": "24h",
                    "status": {"state": "OPERATING NORMALLY", "plain_english": "Old state."},
                    "trades": [{"symbol": "AAPL"}],
                },
                period="24h",
            )

            result = founder_evidence_payload(db_path, period="24h")

            self.assertTrue(result["snapshot"]["stale"])
            self.assertEqual(result["status"]["state"], "OPERATING WITH WARNINGS")
            self.assertEqual(result["trades"][0]["symbol"], "AAPL")

    def test_worker_refresh_persists_all_requested_periods(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            result = refresh_founder_evidence_snapshots(db_path, periods=("1h", "24h"))

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["refreshed_periods"], ["1h", "24h"])
            self.assertEqual(founder_evidence_payload(db_path, period="1h")["snapshot"]["served_from"], "worker_projection")

    def test_hosted_read_returns_warmup_state_instead_of_slow_live_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            with (
                patch("ai_trader.production_evidence.uses_postgres", return_value=True),
                patch("ai_trader.production_evidence.postgres_connection", side_effect=TimeoutError("database unavailable")),
                patch("ai_trader.production_evidence._build_founder_evidence_payload", side_effect=AssertionError("live rebuild")),
            ):
                result = founder_evidence_payload(db_path, period="24h")

            self.assertEqual(result["status"]["state"], "STATUS UNKNOWN")
            self.assertEqual(result["snapshot"]["served_from"], "warmup_state")

    def test_founder_payload_reconstructs_worker_activity_and_financial_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_worker_heartbeat(db_path, worker_id="worker-1", worker_type="background-worker")
            record_research_funnel(
                db_path,
                broker="alpaca",
                asset_type="stock",
                trigger_type="market-open-equity",
                symbols_examined=12,
                symbols_with_adequate_data=10,
                interesting_ideas=1,
                valid_strategies=1,
                committee_approved=1,
                portfolio_approved=1,
                guardrail_approved=1,
                eligible_for_paper_execution=1,
                submitted=1,
                filled=1,
                rejected=0,
                primary_reason="submitted",
            )
            record_research_evidence(
                db_path,
                idempotency_key="research-1",
                started_at="2026-07-19T09:30:00+00:00",
                broker="alpaca",
                asset_type="stock",
                trigger_type="market-open-equity",
                symbols=["AAPL", "MSFT"],
                result={
                    "status": "completed",
                    "proposals": [{"proposal_id": "proposal-1", "symbol": "AAPL"}],
                    "summary": "Two fresh equity assets were reviewed and one candidate qualified.",
                },
                provider="alpaca",
            )
            record_recommendation_evidence(
                db_path,
                {
                    "proposal_id": "proposal-1",
                    "symbol": "AAPL",
                    "side": "buy",
                    "confidence_score": 0.91,
                    "entry_price": 100,
                    "stop_loss": 97,
                    "take_profit": 106,
                    "position_size": 2,
                    "strongest_argument_for": "Trend and catalyst align.",
                    "strongest_argument_against": "The broader market is volatile.",
                },
                broker="alpaca",
            )
            record_broker_snapshot(
                db_path,
                {
                    "broker": "alpaca",
                    "connection_status": "connected",
                    "account_mode": "paper",
                    "portfolio_value": 101_250,
                    "cash_available": 91_000,
                    "buying_power": 180_000,
                    "todays_pnl": 250,
                    "open_positions_detail": [{"symbol": "AAPL", "qty": 2, "market_value": 250}],
                    "reconciliation_status": "fully reconciled",
                    "auto_trading_enabled": True,
                },
            )
            record_trade_evidence(
                db_path,
                broker="alpaca",
                event={
                    "id": "order-1",
                    "symbol": "AAPL",
                    "side": "buy",
                    "status": "filled",
                    "qty": 2,
                    "filled_avg_price": 100.25,
                    "fee": 0.25,
                },
            )
            record_learning_evidence(
                db_path,
                {"status": "completed", "processed": 1, "summary": "One terminal trade review completed."},
                worker_id="worker-1",
            )

            payload = founder_evidence_payload(db_path)

            self.assertEqual(payload["status"]["state"], "OPERATING NORMALLY")
            self.assertEqual(payload["summary"]["research"]["runs"], 1)
            self.assertEqual(payload["summary"]["execution"]["orders_filled"], 1)
            self.assertEqual(payload["portfolio"]["portfolio_value"], 101_250)
            self.assertEqual(payload["portfolio"]["todays_pnl"], 250)
            self.assertEqual(payload["brokers"][0]["broker"], "alpaca")
            self.assertEqual(payload["recommendations"][0]["symbol"], "AAPL")
            self.assertEqual(len(payload["learning"]), 1)
            self.assertTrue(any(item["category"] == "Execution" for item in payload["timeline"]["items"]))
            self.assertNotIn("payload_json", payload["research"][0])
            self.assertNotIn("payload_json", payload["trades"][0])
            self.assertNotIn("payload_json", payload["learning"][0])

    def test_repeated_broker_event_does_not_create_duplicate_trade_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            event = {"id": "same-order", "symbol": "SOLGBP", "side": "buy", "status": "filled", "qty": 1, "price": 10}

            record_trade_evidence(db_path, broker="kraken", event=event)
            record_trade_evidence(db_path, broker="kraken", event=event)

            payload = founder_evidence_payload(db_path)
            self.assertEqual(len(payload["trades"]), 1)

    def test_api_exposes_compact_founder_evidence_and_trade_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            status, payload = service.get("/founder-evidence", {"period": ["24h"], "trade_limit": ["20"]})
            trades_status, trades_payload = service.get("/founder/trades", {"broker": ["all"], "limit": ["20"]})

            self.assertEqual(status, 200)
            self.assertIn("status", payload)
            self.assertIn("portfolio", payload)
            self.assertIn("why_no_trade", payload)
            self.assertEqual(trades_status, 200)
            self.assertIn("trades", trades_payload)

    def test_worker_owned_api_service_skips_startup_schema_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            LocalApiService(settings)

            with (
                patch("ai_trader.api.AuditDatabase.initialize", side_effect=AssertionError("audit schema write")),
                patch(
                    "ai_trader.api.InvestmentIntelligenceDatabase.initialize",
                    side_effect=AssertionError("intelligence schema write"),
                ),
                patch(
                    "ai_trader.api.BenchmarkIntelligenceDatabase.initialize",
                    side_effect=AssertionError("benchmark schema write"),
                ),
                patch(
                    "ai_trader.api.InvestmentOrchestrator.initialize",
                    side_effect=AssertionError("orchestrator schema write"),
                ),
                patch(
                    "ai_trader.api.initialize_foundation_schema",
                    side_effect=AssertionError("foundation schema write"),
                ),
            ):
                service = LocalApiService(settings, initialize_runtime=False)

            status, payload = service.get("/founder-evidence", {"period": ["24h"]})
            self.assertEqual(status, 200)
            self.assertIn("status", payload)


if __name__ == "__main__":
    unittest.main()
