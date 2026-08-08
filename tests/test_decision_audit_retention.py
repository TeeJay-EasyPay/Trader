import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.always_on import initialize_always_on_schema
from ai_trader.database import connect
from ai_trader.foundation import initialize_foundation_schema
from ai_trader.multi_broker import initialize_multi_broker_schema
from ai_trader.orchestrator import ORCHESTRATOR_SCHEMA
from ai_trader.portfolio_intelligence import initialize_portfolio_intelligence_schema
from ai_trader.production_evidence import (
    DECISION_AUDIT_TABLES,
    prune_decision_and_audit_history,
)
from ai_trader.production_spine import initialize_production_spine_schema
from ai_trader.sprint6 import initialize_sprint6_schema
from ai_trader.trading_intelligence import initialize_trading_intelligence_schema


def _init_all_schemas(db_path: Path) -> None:
    initialize_foundation_schema(db_path)
    initialize_sprint6_schema(db_path)
    initialize_production_spine_schema(db_path)
    initialize_always_on_schema(db_path)
    initialize_trading_intelligence_schema(db_path)
    initialize_multi_broker_schema(db_path)
    initialize_portfolio_intelligence_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(ORCHESTRATOR_SCHEMA)


class DecisionAuditRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "audit.sqlite3"
        _init_all_schemas(self.db_path)
        self.now = datetime(2026, 8, 8, tzinfo=timezone.utc)
        self.old = (self.now - timedelta(days=120)).isoformat()
        self.recent = (self.now - timedelta(days=5)).isoformat()
        self._env_patch = patch.dict(os.environ, {"DECISION_AUDIT_RETENTION_ENABLED": "true"})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        self.tmp.cleanup()

    def _count(self, table: str, where: str = "1=1") -> int:
        with closing(connect(self.db_path)) as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]

    def _seed_row(self, table: str, columns: dict) -> None:
        cols = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", tuple(columns.values()))

    def _seed_all_tables(self, *, timestamp: str, decision_overrides: dict | None = None) -> None:
        """Seed one representative row per table at `timestamp`, using the routine
        (non-protected) decision/status/severity value for every table, unless overridden."""
        overrides = decision_overrides or {}
        self._seed_row(
            "DECISION_JOURNAL",
            {
                "created_at": timestamp,
                "proposal_id": "p-1",
                "symbol": "AAPL",
                "evidence_for": "[]",
                "evidence_against": "[]",
                "market_data_quality": "ok",
                "portfolio_decision_json": "{}",
                "strategy_entitlement_json": "{}",
                "risk_sentinel_decision_json": "{}",
                "final_decision": overrides.get("DECISION_JOURNAL", "approved"),
                "execution_eligibility": "eligible",
                "payload_json": "{}",
            },
        )
        self._seed_row(
            "EXECUTION_DECISIONS",
            {
                "created_at": timestamp,
                "proposal_id": "p-1",
                "symbol": "AAPL",
                "decision": overrides.get("EXECUTION_DECISIONS", "approved"),
                "payload_json": "{}",
            },
        )
        self._seed_row(
            "ORCHESTRATOR_DECISIONS",
            {
                "created_at": timestamp,
                "recommendation_id": "p-1",
                "symbol": "AAPL",
                "asset_type": "stock",
                "exchange": "NASDAQ",
                "requested_action": "buy",
                "confidence_score": 0.8,
                "philosophy_fit": 0.8,
                "market_open": 1,
                "asset_available": 1,
                "guardrails_passed": 1,
                "decision": overrides.get("ORCHESTRATOR_DECISIONS", "approved"),
            },
        )
        self._seed_row(
            "PORTFOLIO_MANAGER_DECISIONS",
            {
                "created_at": timestamp,
                "proposal_id": "p-1",
                "symbol": "AAPL",
                "decision": overrides.get("PORTFOLIO_MANAGER_DECISIONS", "approve"),
                "reason": "ok",
                "evidence_json": "{}",
            },
        )
        self._seed_row(
            "STRATEGY_ENTITLEMENT_DECISIONS",
            {
                "created_at": timestamp,
                "proposal_id": "p-1",
                "strategy_id": "s-1",
                "mode": "auto",
                "decision": overrides.get("STRATEGY_ENTITLEMENT_DECISIONS", "allowed"),
                "reason": "ok",
                "evidence_json": "{}",
            },
        )
        self._seed_row(
            "PRODUCTION_RISK_SENTINEL_DECISIONS",
            {
                "created_at": timestamp,
                "proposal_id": "p-1",
                "symbol": "AAPL",
                "decision": overrides.get("PRODUCTION_RISK_SENTINEL_DECISIONS", "approved"),
                "reason": "ok",
                "evidence_json": "{}",
            },
        )
        self._seed_row(
            "CAPITAL_ALLOCATION_HISTORY",
            {
                "created_at": timestamp,
                "proposal_id": "p-1",
                "symbol": "AAPL",
                "asset_type": "stock",
                "account_equity": 1000,
                "requested_notional": 100,
                "approved_notional": 100,
                "approved_quantity": 1,
                "risk_amount": 10,
                "policy_snapshot_json": "{}",
                "result": overrides.get("CAPITAL_ALLOCATION_HISTORY", "approved"),
            },
        )
        self._seed_row(
            "OPERATIONAL_EVENTS",
            {
                "created_at": timestamp,
                "component": "test",
                "event_type": "test_event",
                "severity": overrides.get("OPERATIONAL_EVENTS", "info"),
                "summary": "test",
                "details_json": "{}",
                "proposal_id": "p-1",
                "success": 1,
                "correlation_id": "corr-1",
            },
        )
        self._seed_row(
            "SCHEDULED_JOB_RUNS",
            {
                "job_name": "crypto-research",
                "scheduled_for": timestamp,
                "status": overrides.get("SCHEDULED_JOB_RUNS", "completed"),
                "idempotency_key": f"job-{timestamp}",
            },
        )
        self._seed_row(
            "TRADE_SIGNALS",
            {
                "signal_id": f"sig-{timestamp}",
                "created_at": timestamp,
                "proposal_id": "p-1",
                "symbol": "AAPL",
                "asset_type": "stock",
                "strategy_id": "s-1",
                "regime_id": "r-1",
                "signal_name": "trend",
                "score": 0.5,
                "confidence": 0.5,
                "weight": 0.5,
                "evidence_json": "{}",
            },
        )
        self._seed_row(
            "BROKER_TRADE_HISTORY",
            {
                "broker": "alpaca",
                "external_id": f"ext-{timestamp}",
                "symbol": "AAPL",
                "status": "filled",
                "updated_at": timestamp,
                "payload_json": "{}",
            },
        )
        self._seed_row(
            "PORTFOLIO_EXPOSURE_SNAPSHOTS",
            {
                "created_at": timestamp,
                "broker": "alpaca",
                "total_value": 1000,
                "exposure_json": "{}",
                "warnings_json": "{}",
                "plain_english": "ok",
            },
        )

    def test_routine_old_rows_are_deleted_across_every_table(self):
        self._seed_all_tables(timestamp=self.old)
        result = prune_decision_and_audit_history(self.db_path, now=self.now, force=True)
        self.assertEqual(result["status"], "completed")
        for table in DECISION_AUDIT_TABLES:
            self.assertEqual(self._count(table), 0, f"{table} should have deleted its routine old row")
        self.assertEqual(self._count("TRADE_LIFECYCLE"), 0)

    def test_recent_rows_are_never_deleted_regardless_of_decision(self):
        self._seed_all_tables(timestamp=self.recent)
        prune_decision_and_audit_history(self.db_path, now=self.now, force=True)
        for table in DECISION_AUDIT_TABLES:
            self.assertEqual(self._count(table), 1, f"{table} should have kept its recent row")

    def test_old_rejected_blocked_decisions_are_protected_regardless_of_age(self):
        self._seed_all_tables(
            timestamp=self.old,
            decision_overrides={
                "DECISION_JOURNAL": "blocked",
                "EXECUTION_DECISIONS": "rejected",
                "ORCHESTRATOR_DECISIONS": "rejected",
                "PORTFOLIO_MANAGER_DECISIONS": "reject",
                "STRATEGY_ENTITLEMENT_DECISIONS": "blocked",
                "PRODUCTION_RISK_SENTINEL_DECISIONS": "blocked",
                "CAPITAL_ALLOCATION_HISTORY": "rejected",
                "OPERATIONAL_EVENTS": "error",
                "SCHEDULED_JOB_RUNS": "failed",
            },
        )
        result = prune_decision_and_audit_history(self.db_path, now=self.now, force=True)
        for table in (
            "DECISION_JOURNAL",
            "EXECUTION_DECISIONS",
            "ORCHESTRATOR_DECISIONS",
            "PORTFOLIO_MANAGER_DECISIONS",
            "STRATEGY_ENTITLEMENT_DECISIONS",
            "PRODUCTION_RISK_SENTINEL_DECISIONS",
            "CAPITAL_ALLOCATION_HISTORY",
            "OPERATIONAL_EVENTS",
            "SCHEDULED_JOB_RUNS",
        ):
            self.assertEqual(self._count(table), 1, f"{table}'s notable decision should have been protected")
        # Tables with no decision/status field of their own still prune on pure age.
        self.assertEqual(self._count("TRADE_SIGNALS"), 0)
        self.assertEqual(self._count("BROKER_TRADE_HISTORY"), 0)
        self.assertEqual(self._count("PORTFOLIO_EXPOSURE_SNAPSHOTS"), 0)
        self.assertGreater(sum(result["deleted_row_counts"].values()), 0)

    def test_rows_linked_to_a_notably_large_trade_outcome_are_protected(self):
        self._seed_row(
            "TRADE_LIFECYCLE",
            {
                "created_at": self.old,
                "proposal_id": "big-winner",
                "symbol": "AAPL",
                "stage": "closed",
                "stage_reason": "target hit",
                "measurable": 1,
                "r_multiple": 3.5,
                "payload_json": "{}",
            },
        )
        self._seed_row(
            "TRADE_LIFECYCLE",
            {
                "created_at": self.old,
                "proposal_id": "routine-trade",
                "symbol": "MSFT",
                "stage": "closed",
                "stage_reason": "target hit",
                "measurable": 1,
                "r_multiple": 0.4,
                "payload_json": "{}",
            },
        )
        self._seed_row(
            "EXECUTION_DECISIONS",
            {"created_at": self.old, "proposal_id": "big-winner", "symbol": "AAPL", "decision": "approved", "payload_json": "{}"},
        )
        self._seed_row(
            "EXECUTION_DECISIONS",
            {"created_at": self.old, "proposal_id": "routine-trade", "symbol": "MSFT", "decision": "approved", "payload_json": "{}"},
        )

        prune_decision_and_audit_history(self.db_path, now=self.now, force=True)

        self.assertEqual(self._count("TRADE_LIFECYCLE", "proposal_id = 'big-winner'"), 1)
        self.assertEqual(self._count("TRADE_LIFECYCLE", "proposal_id = 'routine-trade'"), 0)
        self.assertEqual(self._count("EXECUTION_DECISIONS", "proposal_id = 'big-winner'"), 1)
        self.assertEqual(self._count("EXECUTION_DECISIONS", "proposal_id = 'routine-trade'"), 0)

    def test_disabled_by_default_is_a_true_no_op_even_when_forced(self):
        self._env_patch.stop()
        try:
            self._seed_all_tables(timestamp=self.old)
            result = prune_decision_and_audit_history(self.db_path, now=self.now, force=True)
            self.assertEqual(result["status"], "disabled")
            for table in DECISION_AUDIT_TABLES:
                self.assertEqual(self._count(table), 1, f"{table} must be untouched while the flag is off")
        finally:
            self._env_patch.start()

    def test_skips_a_second_run_within_24_hours_unless_forced(self):
        self._seed_all_tables(timestamp=self.old)
        prune_decision_and_audit_history(self.db_path, now=self.now, force=True)
        second = prune_decision_and_audit_history(self.db_path, now=self.now + timedelta(hours=1))
        self.assertEqual(second["status"], "skipped_recent")


class ConfirmedAdminTriggerRoutingTests(unittest.TestCase):
    def test_route_refuses_without_confirmation_and_touches_nothing(self):
        from ai_trader.api import LocalApiService
        from ai_trader.config import Settings
        from ai_trader.models import AutoTradeConfig, GuardrailConfig

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
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
            service = LocalApiService(settings)
            status, payload = service.post("/database-diagnostics/prune-decision-audit-history", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "refused")

    def test_explicit_confirmation_runs_even_while_the_automatic_flag_is_off(self):
        from ai_trader.api import LocalApiService
        from ai_trader.config import Settings
        from ai_trader.models import AutoTradeConfig, GuardrailConfig

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "audit.sqlite3"
            _init_all_schemas(db_path)
            settings = Settings(
                alpaca_api_key=None,
                alpaca_secret_key=None,
                alpaca_paper_base_url="https://paper-api.alpaca.markets",
                alpaca_data_base_url="https://data.alpaca.markets",
                openai_api_key=None,
                openai_model="gpt-4.1-mini",
                db_path=db_path,
                output_dir=root,
                trading_log_path=root / "TRADING_LOG.md",
                guardrails=GuardrailConfig(),
                auto_trade=AutoTradeConfig(),
            )
            service = LocalApiService(settings)
            # DECISION_AUDIT_RETENTION_ENABLED is deliberately not set here.
            status, payload = service.post(
                "/database-diagnostics/prune-decision-audit-history", {"confirmed_by_founder": True, "force": True}
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "completed")


if __name__ == "__main__":
    unittest.main()
