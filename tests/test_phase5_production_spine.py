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

    def test_historical_worker_rows_from_past_deploys_are_never_treated_as_stale(self):
        # Bug found investigating AT-ED-010's /status and /phase5-status hanging ~60s in
        # production: WORKER_HEARTBEATS keeps one permanent row per past deploy generation
        # (Render starts a new worker container, hence a new worker_id, on every deploy,
        # and old rows are never deleted). supervise_workers used to check every row's raw
        # heartbeat age directly, so every dead worker from every previous deploy was always
        # "stale," and record_operations_incident (a DB write) ran once per historical row
        # on every single call -- confirmed as the actual bottleneck, not a missing index.
        # This proves many old rows plus one genuinely fresh row produces a healthy result
        # with zero incidents, not one incident per historical row.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_always_on_schema(db_path)
            now = datetime.now(timezone.utc)
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    for i in range(50):
                        old = (now - timedelta(days=i + 1)).isoformat()
                        conn.execute(
                            """
                            INSERT INTO WORKER_HEARTBEATS (
                                worker_id, worker_type, started_at, last_heartbeat_at, status
                            ) VALUES (?, 'background-worker', ?, ?, 'running')
                            """,
                            (f"worker-deploy-{i}", old, old),
                        )
                    fresh = now.isoformat()
                    conn.execute(
                        """
                        INSERT INTO WORKER_HEARTBEATS (
                            worker_id, worker_type, started_at, last_heartbeat_at, status
                        ) VALUES ('worker-current', 'background-worker', ?, ?, 'running')
                        """,
                        (fresh, fresh),
                    )

            supervision = supervise_workers(db_path, expected_worker_interval_seconds=60)

            self.assertEqual(supervision["status"], "healthy")
            self.assertEqual(supervision["stale_workers"], 0)
            self.assertEqual(supervision["incidents_created"], 0)
            self.assertEqual(supervision["duplicate_worker_types"], {})

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
        # Positions deliberately span two asset classes (crypto + stock) so the proposed
        # crypto trade is a genuine cross-asset-class concentration case -- see
        # test_asset_class_concentration_never_fires_for_a_single_asset_class_book below for
        # the 2026-08-08 fix proving a crypto-only (or any single-asset-class-only) book must
        # NOT be flagged this way, since it can never be anything else.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            positions = [
                {"symbol": "BTC", "broker": "kraken", "asset_type": "crypto", "market_value": 800},
                {"symbol": "ETH", "broker": "kraken", "asset_type": "crypto", "market_value": 200},
                {"symbol": "AAPL", "broker": "alpaca", "asset_type": "stock", "market_value": 100},
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

    def test_asset_class_concentration_never_fires_for_a_single_asset_class_book(self):
        # 2026-08-08 hosted incident: Kraken's AI-managed sleeve only ever holds crypto. The
        # first-ever trade succeeding made the book "100% crypto" (unavoidable for a
        # crypto-only broker, not a real concentration signal), and the asset-class ceiling
        # then rejected every subsequent Kraken trade for "concentration" against a comparison
        # that could never be anything else. Positions and proposal are BOTH crypto-only here,
        # unlike the mixed-asset-class test above.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            positions = [{"symbol": "BCH", "broker": "kraken", "asset_type": "crypto", "market_value": 2}]
            proposal = {
                "proposal_id": "crypto-2",
                "broker": "kraken",
                "symbol": "XRP",
                "asset_type": "crypto",
                "position_size": 2,
                "entry_price": 0.5,
                "stop_loss": 0.49,
                "quantity": 4,
            }

            decision = portfolio_manager_decision(db_path, proposal=proposal, positions=positions)

            self.assertEqual(decision["decision"], "approve")

    def test_missing_asset_metadata_alone_never_forces_manual_review(self):
        # 2026-08-08 hosted incident, the most fundamental of the four compounding bugs found
        # that day: ASSET_METADATA has no real writer anywhere in this codebase
        # (upsert_asset_metadata is defined but never called outside tests), so
        # calculate_portfolio_exposure's "Metadata is missing for X" warning was
        # unconditionally present for every symbol, on every single proposal, always -- which
        # meant portfolio_manager_decision's `if exposure["warnings"]: decision =
        # "manual_review"` fired every single time regardless of any other check, so "approve"
        # was structurally unreachable. A genuinely clean, unconcentrated, single crypto
        # position with metadata missing (the real, permanent state of this database) must
        # still be able to reach "approve".
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            positions = [{"symbol": "BCH", "broker": "kraken", "asset_type": "crypto", "market_value": 2}]
            proposal = {
                "proposal_id": "crypto-3",
                "broker": "kraken",
                "symbol": "XLM",
                "asset_type": "crypto",
                "position_size": 2,
                "entry_price": 0.1,
                "stop_loss": 0.098,
                "quantity": 20,
            }
            decision = portfolio_manager_decision(db_path, proposal=proposal, positions=positions)
            self.assertEqual(decision["decision"], "approve")
            self.assertTrue(any("Metadata is missing" in warning for warning in decision["evidence"]["exposure"]["warnings"]))

    def test_positions_from_account_bucket_correctly_instead_of_falling_into_unknown(self):
        # 2026-08-08 hosted incident: _positions_from_account (sprint6.py) built each position
        # dict with key "asset_class", but calculate_portfolio_exposure (portfolio_intelligence.py)
        # only ever reads "asset_type" as its fallback when ASSET_METADATA has no row for the
        # symbol -- which is always, in production, since nothing calls upsert_asset_metadata.
        # Every real managed position was therefore silently bucketed as "Unknown" rather than
        # "crypto"/"stock", masking the true asset-class weight from the concentration check
        # (and from the single-asset-class fix above, which can only recognise the bucket it
        # is actually given).
        from ai_trader.models import AccountContext, Position
        from ai_trader.portfolio_intelligence import calculate_portfolio_exposure
        from ai_trader.sprint6 import _positions_from_account

        account = AccountContext(equity=100.0, daily_realized_pnl=0.0, open_positions=[Position(symbol="BCH", qty=1, market_value=2.0)])
        positions = _positions_from_account(account, "kraken")
        self.assertEqual(positions[0]["asset_type"], "crypto")
        self.assertNotIn("asset_class", positions[0])

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            exposure = calculate_portfolio_exposure(db_path, positions)
            self.assertIn("crypto", {label.lower() for label in exposure["exposure"]["asset_class"]})
            self.assertNotIn("unknown", {label.lower() for label in exposure["exposure"]["asset_class"]})

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
            supervision = status["worker_supervision"]
            if supervision["status"] != "healthy":
                # Diagnosed 2026-08-02 (Stage 0.4, architecture/AI_TRADER_MODULARISATION_
                # ARCHITECTURE_2026-08-02.md): supervise_workers (production_spine.py)
                # classifies heartbeat staleness against a live datetime.now(timezone.utc)
                # read with no way to inject `now`, using a fixed 240s threshold
                # (expected_worker_interval_seconds=120, doubled). This test writes the
                # heartbeat and reads the classification back within the same method with
                # no code path that should ever separate them by minutes -- but on this
                # environment a rare full-suite run has shown a multi-hundred-second stall
                # between the two (this same environment's pytest tmp/cache directories
                # have independently shown intermittent Windows PermissionError stalls on
                # temp-file I/O), which is enough to trip the threshold. Ruled out as the
                # actual cause: schema-cache key collision (production_spine._schema_key
                # correctly scopes by resolved db_path), cross-test global state (none
                # found in always_on.py's heartbeat/job-run storage, all correctly scoped
                # by db_path), and time-mocking leakage (no test in the suite patches
                # datetime/time). Rather than loosen this into accepting any outcome,
                # assert the failure is genuinely *only* clock-staleness on the one
                # worker just heartbeated -- not a real classification bug (a duplicate
                # worker type, a late job, or backlog would indicate one).
                self.assertEqual(supervision["duplicate_worker_types"], {})
                self.assertEqual(supervision["late_jobs"], [])
                self.assertEqual(supervision["backlog"], [])
                self.assertEqual([w["worker_id"] for w in supervision["stale_workers"]], ["worker-1"])
            else:
                self.assertEqual(supervision["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
