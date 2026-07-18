import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.always_on import initialize_always_on_schema, record_worker_heartbeat
from ai_trader.api import LocalApiService
from ai_trader.config import Settings
from ai_trader.models import AutoTradeConfig, GuardrailConfig
from ai_trader.production_spine import (
    initialize_production_spine_schema,
    market_data_gateway_validate,
    phase5_status,
    portfolio_manager_decision,
    production_database_spine_status,
    reconcile_logical_trade,
    run_closed_loop_learning,
    strategy_promotion_decision,
    supervise_workers,
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


class Phase5ProductionSpineTests(unittest.TestCase):
    def test_database_spine_reports_partial_runtime_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            status = production_database_spine_status(db_path, database_backend="sqlite")

            self.assertEqual(status["status"], "partial_spine")
            self.assertIn("recommendations", status["unmigrated_families"])
            self.assertIn("plain_english", status)

    def test_worker_supervision_creates_incident_for_stale_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_always_on_schema(db_path)
            old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO WORKER_HEARTBEATS (
                            worker_id, worker_type, started_at, last_heartbeat_at, status
                        ) VALUES ('worker-old', 'background-worker', ?, ?, 'running')
                        """,
                        (old, old),
                    )

            supervision = supervise_workers(db_path, expected_worker_interval_seconds=60)

            self.assertEqual(supervision["status"], "incident")
            self.assertEqual(supervision["stale_workers"], 1)
            self.assertEqual(supervision["incidents_created"], 1)

    def test_canonical_reconciliation_is_idempotent_for_duplicate_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            events = [
                {
                    "logical_trade_id": "kraken-1",
                    "id": "submit-1",
                    "status": "submitted",
                    "pair": "XRPGBP",
                    "type": "buy",
                    "timestamp": "2026-07-18T10:00:00+00:00",
                },
                {
                    "logical_trade_id": "kraken-1",
                    "id": "fill-1",
                    "status": "filled",
                    "pair": "XRPGBP",
                    "type": "buy",
                    "vol_exec": "5",
                    "timestamp": "2026-07-18T10:01:00+00:00",
                },
            ]

            first = reconcile_logical_trade(db_path, broker="kraken", events=events)
            second = reconcile_logical_trade(db_path, broker="kraken", events=events)

            self.assertEqual(first["count"], 1)
            self.assertEqual(first["logical_trades"][0]["status"], "reconciled")
            self.assertEqual(second["logical_trades"][0]["duplicate_events"], 2)

    def test_closed_loop_learning_is_idempotent_and_governed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            decision_context = {
                "proposal_id": "p-1",
                "asset_type": "stock",
                "strategy_id": "breakout",
                "regime_id": "fragile_uptrend",
                "side": "buy",
                "entry_price": 100,
                "intended_entry_price": 100,
                "stop_loss": 95,
                "original_stop": 95,
                "take_profit": 110,
                "expected_r": 2.0,
                "strongest_argument_for": "Breakout with catalyst.",
                "strongest_argument_against": "Market regime is fragile.",
            }
            attribution = {
                "proposal_id": "p-1",
                "side": "buy",
                "quantity": 2,
                "entry_price": 100,
                "exit_price": 108,
                "actual_average_entry_price": 100.5,
                "actual_average_exit_price": 108,
                "broker_fee": 0.1,
                "exchange_fee": 0.0,
                "profit_loss": 15,
            }
            observations = [
                {"time": "2026-07-18T10:00:00+00:00", "low": 98, "high": 106},
                {"time": "2026-07-18T11:00:00+00:00", "low": 101, "high": 109},
            ]

            result = run_closed_loop_learning(
                db_path,
                logical_trade_id="alpaca-p-1",
                broker="alpaca",
                symbol="AAPL",
                attribution=attribution,
                decision_context=decision_context,
                observations=observations,
            )
            duplicate = run_closed_loop_learning(
                db_path,
                logical_trade_id="alpaca-p-1",
                broker="alpaca",
                symbol="AAPL",
                attribution=attribution,
                decision_context=decision_context,
            )

            self.assertEqual(result["status"], "completed")
            self.assertIn("learning_proposal", result)
            self.assertEqual(duplicate["status"], "duplicate")
            self.assertIn("production unchanged", result["learning_proposal"]["current_value"])

    def test_portfolio_manager_can_reject_concentration(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            positions = [
                {"symbol": "BTC", "broker": "kraken", "asset_class": "crypto", "market_value": 800},
                {"symbol": "ETH", "broker": "kraken", "asset_class": "crypto", "market_value": 200},
            ]
            proposal = {
                "proposal_id": "crypto-1",
                "broker": "kraken",
                "symbol": "SOL",
                "asset_type": "crypto",
                "position_size": 400,
                "entry_price": 100,
                "stop_loss": 95,
                "quantity": 4,
            }

            decision = portfolio_manager_decision(db_path, proposal=proposal, positions=positions)

            self.assertIn(decision["decision"], {"reject", "approve_smaller", "manual_review"})
            self.assertIn("Portfolio Manager decision", decision["plain_english"])

    def test_market_data_gateway_blocks_bad_candles(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            result = market_data_gateway_validate(
                db_path,
                provider="test-feed",
                symbol="AAPL",
                asset_type="stock",
                timeframe="1h",
                observations=[
                    {"time": "2026-07-18T10:00:00+00:00", "open": 10, "high": 9, "low": 8, "close": 10, "volume": 100},
                    {"time": "2026-07-18T11:00:00+00:00", "open": 10, "high": 12, "low": 9, "close": 11, "volume": -1},
                ],
            )

            self.assertEqual(result["status"], "blocked")
            self.assertLess(result["quality_score"], 0.80)

    def test_strategy_promotion_respects_evidence_gates_and_demotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            promoted = strategy_promotion_decision(
                db_path,
                strategy_id="breakout",
                current_stage="Backtest",
                evidence={
                    "sample_size": 40,
                    "expectancy": 0.25,
                    "profit_factor": 1.5,
                    "max_drawdown": 0.08,
                    "calibration_error": 0.05,
                },
            )
            demoted = strategy_promotion_decision(
                db_path,
                strategy_id="mean_reversion",
                current_stage="Production",
                evidence={
                    "sample_size": 200,
                    "expectancy": 0.2,
                    "profit_factor": 1.6,
                    "max_drawdown": 0.08,
                    "calibration_error": 0.04,
                    "recent_drawdown": 0.2,
                },
            )

            self.assertEqual(promoted["decision"], "promote")
            self.assertEqual(demoted["decision"], "demote")
            self.assertEqual(demoted["proposed_stage"], "Retired")

    def test_api_exposes_phase5_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            status, payload = service.get("/phase5-status", {})

            self.assertEqual(status, 200)
            self.assertIn("database_spine", payload)
            self.assertIn("worker_supervision", payload)

    def test_phase5_status_reports_attention_until_production_database_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_production_spine_schema(db_path)
            record_worker_heartbeat(db_path, worker_id="worker-1", worker_type="background-worker")

            status = phase5_status(db_path, database_backend="sqlite")

            self.assertEqual(status["overall"], "attention_needed")
            self.assertEqual(status["worker_supervision"]["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
