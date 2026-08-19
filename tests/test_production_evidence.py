import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.always_on import record_research_funnel, record_worker_heartbeat
from ai_trader.api import LocalApiService
from ai_trader.canonical_trades import link_broker_order
from ai_trader.kraken_reconciliation import register_kraken_order_ownership
from ai_trader.sprint6 import normalize_broker_events
from ai_trader.models import AutoTradeConfig, GuardrailConfig
from ai_trader.config import Settings
import ai_trader.production_evidence as production_evidence
from ai_trader.production_evidence import (
    backfill_realized_pnl,
    founder_evidence_payload,
    list_production_trade_evidence,
    persist_founder_evidence_snapshot,
    prune_production_evidence,
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
    def test_shared_projection_keeps_decision_summary_but_omits_nested_dossier(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_recommendation_evidence(
                db_path,
                {
                    "proposal_id": "proposal-intelligence",
                    "symbol": "AAPL",
                    "side": "buy",
                    "entry_price": 210.0,
                    "stop_loss": 205.0,
                    "take_profit": 220.0,
                    "position_size": 2.0,
                    "confidence_score": 0.64,
                    "intelligence": {
                        "strategy": {"strategy_id": "evidence-trend", "name": "Evidence Trend"},
                        "probability": {
                            "probability_of_success": 0.64,
                            "expected_return_r": 0.92,
                            "confidence_interval_low": 0.54,
                            "confidence_interval_high": 0.72,
                            "calibration_status": "provisional",
                        },
                        "committee": {
                            "committee_result": "approved",
                            "strongest_argument_for": "Trend and catalyst evidence align.",
                            "strongest_argument_against": "An earnings event could invalidate the setup.",
                        },
                        "trade_setup": {
                            "expected_r_multiple": 2.0,
                            "invalidation_conditions": ["Price closes below support."],
                        },
                        "regime": {"regime": "fragile_upward_trend"},
                        "signals": [{"name": "trend", "direction": "bullish"}],
                    },
                },
                broker="alpaca",
            )

            recommendation = founder_evidence_payload(db_path)["recommendations"][0]

            self.assertEqual(recommendation["strategy_name"], "Evidence Trend")
            self.assertEqual(recommendation["strategy_id"], "evidence-trend")
            self.assertEqual(recommendation["probability_of_success"], 0.64)
            self.assertEqual(recommendation["expected_return_r"], 0.92)
            self.assertEqual(recommendation["committee_result"], "approved")
            self.assertIn("earnings event", recommendation["strongest_argument_against"])
            self.assertNotIn("intelligence", recommendation)
            self.assertNotIn("committee", recommendation)
            self.assertNotIn("signals", recommendation)

    def test_shared_projection_size_is_not_driven_by_large_recommendation_dossier(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_recommendation_evidence(
                db_path,
                {
                    "proposal_id": "proposal-large",
                    "symbol": "AAPL",
                    "confidence_score": 0.91,
                    "plain_english_reasoning": "A bounded thesis.",
                    "intelligence": {"committee": {"raw_evidence": "x" * 250_000}},
                },
                broker="alpaca",
            )

            payload = founder_evidence_payload(db_path)

            self.assertLess(len(production_evidence._json(payload["recommendations"])), 10_000)
            self.assertNotIn("intelligence", payload["recommendations"][0])

    def test_retention_prunes_replaceable_evidence_but_preserves_trade_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            now = datetime(2026, 8, 6, tzinfo=timezone.utc)
            old = (now - timedelta(days=120)).isoformat()
            record_recommendation_evidence(
                db_path,
                {"proposal_id": "old-proposal", "symbol": "AAPL", "created_at": old},
                broker="alpaca",
            )
            record_broker_snapshot(
                db_path,
                {"broker": "alpaca", "connection_status": "connected"},
                captured_at=old,
            )
            record_trade_evidence(
                db_path,
                broker="alpaca",
                event={"id": "old-trade", "status": "filled", "updated_at": old},
            )

            result = prune_production_evidence(db_path, now=now, force=True)
            recommendations = production_evidence._query(
                db_path, "SELECT recommendation_id FROM PRODUCTION_RECOMMENDATION_EVIDENCE", limit=10
            )
            snapshots = production_evidence._query(
                db_path, "SELECT snapshot_id FROM PRODUCTION_BROKER_SNAPSHOTS", limit=10
            )
            trades = production_evidence._query(
                db_path, "SELECT trade_evidence_id FROM PRODUCTION_TRADE_EVIDENCE", limit=10
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(recommendations, [])
            self.assertEqual(snapshots, [])
            self.assertEqual(len(trades), 1)
            self.assertEqual(prune_production_evidence(db_path, now=now)["status"], "skipped_recent")

    def test_production_research_merges_rich_recommendation_dossier(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            base = {
                "proposal_id": "proposal-rich",
                "symbol": "AAPL",
                "side": "buy",
                "entry_price": 210.0,
                "stop_loss": 205.0,
                "take_profit": 220.0,
                "position_size": 2.0,
                "strongest_argument_for": "Base proposal argument.",
            }
            rich = {
                "proposal_id": "proposal-rich",
                "symbol": "AAPL",
                "strategy_name": "Evidence Trend",
                "probability_of_success": 0.64,
                "expected_return_r": 2.0,
                "committee": {"committee_result": "approved"},
                "strongest_argument_for": "Committee found trend and catalyst alignment.",
                "strongest_argument_against": "Earnings event risk could invalidate the setup.",
                "invalidation": ["Price closes below support."],
            }

            with (
                patch.object(service, "recommendations", return_value=[rich]),
                # Phase 5 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md)
                # moved _record_production_research into application/research_service.py,
                # which imports record_research_evidence independently -- the call site this
                # patch needs to target moved with it. Same underlying function object,
                # same observable behaviour; only the module-qualified patch target changed.
                patch("ai_trader.application.research_service.record_research_evidence") as record_evidence,
            ):
                service._record_production_research(
                    "2026-07-23T14:00:00+00:00",
                    "alpaca",
                    "stock",
                    "scheduled",
                    ["AAPL"],
                    {"status": "completed", "proposals": [base]},
                )

            stored = record_evidence.call_args.kwargs["result"]["proposals"][0]
            self.assertEqual(stored["entry_price"], 210.0)
            self.assertEqual(stored["strategy_name"], "Evidence Trend")
            self.assertEqual(stored["probability_of_success"], 0.64)
            self.assertEqual(stored["committee"]["committee_result"], "approved")
            self.assertIn("Earnings event risk", stored["strongest_argument_against"])

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

    def test_closed_trade_history_is_not_bounded_by_the_period_window(self):
        # 2026-08-17 hosted finding: Current Position's "Realised this month", the Forecast
        # Centre, and Learning's closed-trade/win-rate figures all read from `trades`, which
        # is bounded by the Founder-evidence `period` window (default 24h). A real ~$639 CSL
        # profit had just been correctly computed (backfill_realized_pnl) but was invisible
        # everywhere in the app anyway, because the exit itself was 6 days old -- confirmed
        # live, /founder-evidence?period=24h returned zero trades outright. closed_trade_history
        # is the fix: the same terminal-trade data, no period bound.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            old = (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()
            record_trade_evidence(
                db_path,
                broker="alpaca",
                event={
                    "id": "sell-old", "status": "filled", "symbol": "CSL", "side": "sell",
                    "qty": 31, "filled_avg_price": 386.958064, "realized_pnl": 639.12,
                    "closed_at": old, "updated_at": old,
                },
            )

            payload = founder_evidence_payload(db_path, period="24h")

            self.assertEqual(payload["trades"], [])
            self.assertEqual(len(payload["closed_trade_history"]), 1)
            self.assertEqual(payload["closed_trade_history"][0]["symbol"], "CSL")
            self.assertAlmostEqual(payload["performance"]["realized_pnl"], 639.12)

    def test_closed_trade_history_flags_ai_decided_trades_separately_from_legacy_ones(self):
        # 2026-08-18 Founder request: separate the AI's real trading judgment from whatever
        # else happened to be in a broker account. orchestrator.py's evaluate_recommendation
        # is the only production order-placement path -- it links a broker_order_id to a real
        # proposal_id (via register_execution_intent + link_broker_order) before the order
        # ever reaches a broker. A trade with no such link (like the 13 confirmed-live legacy
        # Alpaca exits, entry_reason always null) was never AI-decided.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            link_broker_order(
                db_path,
                logical_trade_id="proposal-real-ai-decision",
                broker_order_id="order-ai-decided",
                payload={"status": "filled"},
            )
            record_trade_evidence(db_path, broker="alpaca", event={
                "id": "order-ai-decided", "status": "filled", "symbol": "AAPL", "side": "sell",
                "qty": 1, "filled_avg_price": 200, "realized_pnl": 10,
            })
            record_trade_evidence(db_path, broker="alpaca", event={
                "id": "order-legacy", "status": "filled", "symbol": "CSL", "side": "sell",
                "qty": 31, "filled_avg_price": 386.958064, "realized_pnl": 639.12,
            })

            payload = founder_evidence_payload(db_path)

            by_symbol = {row["symbol"]: row["ai_decided"] for row in payload["closed_trade_history"]}
            self.assertEqual(by_symbol["AAPL"], True)
            self.assertEqual(by_symbol["CSL"], False)

    def test_general_broker_reconciliation_never_marks_a_legacy_trade_as_ai_decided(self):
        # 2026-08-18 hosted incident, caught before this ever reached the Founder as
        # "verified": the first live check of ai_decided showed CSL/ROG/AAL/AZN/AAPL all
        # reading True -- the exact opposite of correct. Root cause: poll_broker_activity's
        # own broker-history reconciliation (normalize_broker_events ->
        # reconcile_canonical_broker_event) writes a LOGICAL_TRADE_EVENTS row for EVERY
        # historical broker order it observes, AI-decided or not -- the original query
        # (`broker_order_id IS NOT NULL`) could never tell that apart from a real
        # link_broker_order() call. Regression coverage: reconciling a legacy order through
        # the exact general path poll_broker_activity actually uses must never mark it
        # ai_decided=true.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            normalize_broker_events(
                db_path,
                broker="alpaca",
                events=[{
                    "id": "order-legacy-csl", "status": "filled", "symbol": "CSL", "side": "sell",
                    "quantity": 31, "average_fill_price": 386.958064,
                }],
                source_endpoint="poll_broker_activity",
            )
            record_trade_evidence(db_path, broker="alpaca", event={
                "id": "order-legacy-csl", "status": "filled", "symbol": "CSL", "side": "sell",
                "qty": 31, "filled_avg_price": 386.958064, "realized_pnl": 639.12,
            })

            payload = founder_evidence_payload(db_path)

            csl_row = next(row for row in payload["closed_trade_history"] if row["symbol"] == "CSL")
            self.assertEqual(csl_row["ai_decided"], False)

    def test_kraken_managed_exit_is_recognised_as_ai_decided(self):
        # 2026-08-19 hosted finding: a real XRP position the AI itself entered (documented
        # due-diligence reasoning on record) and then exited via its own stop/take-profit
        # management showed ai_decided=false on both legs -- confirmed live.
        # monitor_managed_exits (execution_service.py) is a separate production
        # order-placement path from evaluate_recommendation: it places every real Kraken
        # managed exit and never calls link_broker_order, only
        # register_kraken_order_ownership(order_role='exit'). Regression coverage: an exit
        # order registered exactly the way monitor_managed_exits actually registers one must
        # be recognised as AI-decided.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            register_kraken_order_ownership(
                db_path,
                broker_order_id="order-xrp-exit",
                logical_trade_id="proposal-xrp-entry",
                proposal_id="proposal-xrp-entry",
                order_role="exit",
                symbol="XRPGBP",
                side="sell",
                source="managed_exit_monitor",
            )
            record_trade_evidence(db_path, broker="kraken", event={
                "id": "order-xrp-exit", "status": "filled", "symbol": "XRPGBP", "side": "sell",
                "qty": 2.7023, "filled_avg_price": 0.79, "realized_pnl": -0.12,
            })

            payload = founder_evidence_payload(db_path)

            xrp_row = next(row for row in payload["closed_trade_history"] if row["symbol"] == "XRPGBP")
            self.assertEqual(xrp_row["ai_decided"], True)

    def test_worker_refresh_persists_all_requested_periods(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            with patch(
                "ai_trader.production_evidence._load_founder_evidence_rows",
                wraps=production_evidence._load_founder_evidence_rows,
            ) as load_rows:
                result = refresh_founder_evidence_snapshots(db_path, periods=("1h", "24h"))

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["refreshed_periods"], ["1h", "24h"])
            self.assertEqual(load_rows.call_count, 1)
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

    def test_job_health_summary_uses_founder_facing_vocabulary(self):
        # AT-ED-003 Section 2: a job must never be reported "Healthy" merely because a
        # process exists somewhere in history. Each state below must be distinguishable.
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        recent = (now - timedelta(seconds=30)).isoformat()
        stale = (now - timedelta(hours=6)).isoformat()

        jobs = [
            {"job_name": "broker-poll-alpaca", "status": "completed", "completed_at": recent},
            {"job_name": "broker-poll-kraken", "status": "completed", "completed_at": stale},
            {"job_name": "auto-execution-alpaca", "status": "completed", "completed_at": recent, "paper_orders_submitted": 0, "rejection_count": 0},
            {"job_name": "managed-exits", "status": "timed_out", "completed_at": recent, "failure_reason": "exceeded boundary"},
            {"job_name": "evidence-snapshot", "status": "failed", "completed_at": recent, "failure_reason": "broker API error"},
        ]
        broker_payload = [
            {"broker": "alpaca", "auto_trading_enabled": True},
            {"broker": "kraken", "auto_trading_enabled": False},
        ]

        results = {row["job"]: row for row in production_evidence._job_health_summary(jobs, broker_payload)}

        self.assertEqual(results["broker-poll-alpaca"]["status"], "Healthy")
        # Kraken auto trading is Founder-disabled, so its broker-poll job reads
        # "Disabled by Founder" even though a stale completed run exists - disabled
        # takes precedence over a delayed-looking timestamp.
        self.assertEqual(results["broker-poll-kraken"]["status"], "Disabled by Founder")
        self.assertEqual(results["auto-execution-alpaca"]["status"], "No Eligible Action")
        self.assertEqual(results["managed-exits"]["status"], "Timed Out")
        self.assertEqual(results["evidence-snapshot"]["status"], "Blocked")
        # auto-execution-kraken has no matching job rows and kraken is disabled by
        # the Founder - disabled still takes precedence over "no run recorded yet".
        self.assertEqual(results["auto-execution-kraken"]["status"], "Disabled by Founder")
        # daily-report has never run and is not broker-gated.
        self.assertEqual(results["daily-report"]["status"], "Awaiting First Run")

    def test_job_health_summary_distinguishes_blocked_from_no_eligible_action(self):
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        jobs = [
            {"job_name": "auto-execution-alpaca", "status": "completed", "completed_at": now_iso, "paper_orders_submitted": 0, "rejection_count": 3},
            {"job_name": "auto-execution-kraken", "status": "completed", "completed_at": now_iso, "paper_orders_submitted": 1, "rejection_count": 0},
        ]
        broker_payload = [
            {"broker": "alpaca", "auto_trading_enabled": True},
            {"broker": "kraken", "auto_trading_enabled": True},
        ]

        results = {row["job"]: row for row in production_evidence._job_health_summary(jobs, broker_payload)}

        self.assertEqual(results["auto-execution-alpaca"]["status"], "Enabled but Blocked")
        self.assertIn("3", results["auto-execution-alpaca"]["detail"])
        self.assertEqual(results["auto-execution-kraken"]["status"], "Healthy")

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
            self.assertNotIn("brokers", payload["portfolio"])
            self.assertNotIn("payload_json", payload["brokers"][0])
            self.assertNotIn("positions_json", payload["brokers"][0])
            self.assertEqual(payload["recommendations"][0]["symbol"], "AAPL")
            self.assertEqual(len(payload["learning"]), 1)
            self.assertTrue(any(item["category"] == "Execution" for item in payload["timeline"]["items"]))
            self.assertNotIn("payload_json", payload["research"][0])
            self.assertNotIn("payload_json", payload["trades"][0])
            self.assertNotIn("payload_json", payload["learning"][0])

    def test_founder_evidence_exposes_managed_exits_distinct_from_raw_positions(self):
        # The Portfolio screen must never label a manual Kraken holding as AI-managed. The only
        # way to do that correctly is to expose the explicitly AI-owned open positions
        # (MANAGED_TRADE_EXITS) separately from the raw broker position list, which also
        # contains personal/manual holdings the AI never opened.
        from ai_trader.multi_broker import record_managed_trade_exit

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_broker_snapshot(
                db_path,
                {
                    "broker": "kraken",
                    "connection_status": "connected",
                    "account_mode": "live",
                    "portfolio_value": 3700,
                    "cash_available": 50,
                    # Two coins held: one AI-managed (BTC, via record_managed_trade_exit below)
                    # and one manual/personal holding (ETH) with no managed-exit row at all.
                    "open_positions_detail": [
                        {"symbol": "BTC", "qty": 0.01, "market_value": 500},
                        {"symbol": "ETH", "qty": 1.0, "market_value": 3000},
                    ],
                    "reconciliation_status": "verification_required",
                    "auto_trading_enabled": True,
                },
            )
            record_managed_trade_exit(
                db_path,
                broker="kraken",
                symbol="BTC",
                side="buy",
                quantity=0.01,
                entry_order_id="ai-entry-1",
                entry_price=45_000.0,
                stop_loss=43_000.0,
                take_profit=48_000.0,
                payload={"proposal_id": "prop-btc-1", "entry_reason": "Momentum breakout."},
            )

            payload = founder_evidence_payload(db_path)

            kraken = next(row for row in payload["brokers"] if row["broker"] == "kraken")
            self.assertEqual(len(kraken["managed_exits"]), 1)
            managed = kraken["managed_exits"][0]
            self.assertEqual(managed["symbol"], "BTC")
            self.assertEqual(managed["status"], "open")
            self.assertEqual(managed["payload"]["proposal_id"], "prop-btc-1")
            # ETH has no managed-exit row -- it must not appear in managed_exits, even though
            # it is in the broker's raw position list.
            managed_symbols = {row["symbol"] for row in kraken["managed_exits"]}
            self.assertNotIn("ETH", managed_symbols)

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

    def test_backfill_realized_pnl_computes_fifo_matched_exit(self):
        # 2026-08-17 hosted finding: Alpaca's order/fill API never reports realized_pnl, and
        # the LOGICAL_TRADES reconciliation that does compute it can't link an Alpaca entry
        # to its exit (MANAGED_TRADE_EXITS is Kraken-only) -- confirmed live, a real ~$645
        # CSL profit was invisible everywhere in the app. This mirrors that shape with a
        # simpler two-lot case: 10@100 then 5@110 bought, all 15 sold @120.
        # Expected P&L: (120-100)*10 + (120-110)*5 = 200 + 50 = 250.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_trade_evidence(db_path, broker="alpaca", event={
                "id": "buy-1", "status": "filled", "symbol": "AAPL", "side": "buy",
                "qty": 10, "filled_avg_price": 100, "closed_at": "2026-08-01T00:00:00Z",
            })
            record_trade_evidence(db_path, broker="alpaca", event={
                "id": "buy-2", "status": "filled", "symbol": "AAPL", "side": "buy",
                "qty": 5, "filled_avg_price": 110, "closed_at": "2026-08-02T00:00:00Z",
            })
            record_trade_evidence(db_path, broker="alpaca", event={
                "id": "sell-1", "status": "filled", "symbol": "AAPL", "side": "sell",
                "qty": 15, "filled_avg_price": 120, "closed_at": "2026-08-03T00:00:00Z",
            })

            result = backfill_realized_pnl(db_path, broker="alpaca")

            self.assertEqual(result["updated"], 1)
            self.assertAlmostEqual(result["total_realized_pnl"], 250.0)
            trades = list_production_trade_evidence(db_path, broker="alpaca")
            sell_row = next(row for row in trades if row["side"] == "sell")
            self.assertAlmostEqual(sell_row["realized_pnl"], 250.0)

    def test_backfill_realized_pnl_leaves_partially_matched_exit_null(self):
        # A sell larger than all known buy history (a legacy position that existed before
        # trade-evidence tracking began) must never get a fabricated P&L against an unknown
        # cost basis for the unmatched portion -- stays null, honestly.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_trade_evidence(db_path, broker="alpaca", event={
                "id": "buy-1", "status": "filled", "symbol": "MSFT", "side": "buy",
                "qty": 5, "filled_avg_price": 100, "closed_at": "2026-08-01T00:00:00Z",
            })
            record_trade_evidence(db_path, broker="alpaca", event={
                "id": "sell-1", "status": "filled", "symbol": "MSFT", "side": "sell",
                "qty": 10, "filled_avg_price": 120, "closed_at": "2026-08-02T00:00:00Z",
            })

            result = backfill_realized_pnl(db_path, broker="alpaca")

            self.assertEqual(result["updated"], 0)
            trades = list_production_trade_evidence(db_path, broker="alpaca")
            sell_row = next(row for row in trades if row["side"] == "sell")
            self.assertIsNone(sell_row["realized_pnl"])

    def test_backfill_realized_pnl_never_overwrites_an_existing_value(self):
        # Safe to call every broker-poll cycle: a row that already has a real realized_pnl
        # (from Kraken, or any future broker that does report its own) must never be
        # silently recomputed/overwritten by the FIFO fallback.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_trade_evidence(db_path, broker="alpaca", event={
                "id": "buy-1", "status": "filled", "symbol": "GOOG", "side": "buy",
                "qty": 10, "filled_avg_price": 100, "closed_at": "2026-08-01T00:00:00Z",
            })
            record_trade_evidence(db_path, broker="alpaca", event={
                "id": "sell-1", "status": "filled", "symbol": "GOOG", "side": "sell",
                "qty": 10, "filled_avg_price": 120, "closed_at": "2026-08-02T00:00:00Z",
                "realized_pnl": 999,
            })

            result = backfill_realized_pnl(db_path, broker="alpaca")

            self.assertEqual(result["updated"], 0)
            trades = list_production_trade_evidence(db_path, broker="alpaca")
            sell_row = next(row for row in trades if row["side"] == "sell")
            self.assertAlmostEqual(sell_row["realized_pnl"], 999.0)


if __name__ == "__main__":
    unittest.main()
