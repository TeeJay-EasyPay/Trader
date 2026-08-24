from __future__ import annotations

import json
import logging
import os
import sqlite3
from ..application.administration_service import AdministrationService
from ..guardrails import us_equity_market_hours_between
from ..application.broker_service import BrokerService
from ..application.execution_service import ExecutionService
from ..application.founder_experience_service import FounderExperienceService
from ..application.operations_service import OperationsService
from ..application.reporting_service import ReportingService
from ..application.research_service import ResearchService
from ..database import connect
from ..db_diagnostics import database_size_report, vacuum_table
from ..persistence.query_executor import QueryExecutor
from .http_server import ApiHandler
import time
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from ..agent import AITradingAgent, propose_crypto_trades
from ..always_on import (
    alpaca_inactivity_diagnosis,
    initialize_always_on_schema,
    list_job_runs,
    list_research_funnels,
    list_shadow_trades,
    record_research_funnel,
    record_shadow_trade,
    scheduler_status,
    shadow_performance,
)
from ..autonomous_activity import (
    activity_summary,
    activity_timeline,
    broker_activity,
    current_autonomous_status,
    founder_attention,
    why_no_trade_funnel,
)
from ..ai import OpenAIProposalAnalyzer, OpenAIReadOnlyExplainer
from ..alpaca import AlpacaCredentials, AlpacaPaperClient
from ..audit import AuditDatabase
from ..benchmark import BenchmarkIntelligenceDatabase
from ..briefing import generate_daily_briefing
from ..broker_adapters import AlpacaBrokerAdapter, CoinbaseAdapter, InteractiveBrokersAdapter, KrakenAdapter, SaxoAdapter, _kraken_last_price, _kraken_pair
from ..config import Settings, load_settings
from ..foundation import (
    initialize_foundation_schema,
    latest_due_diligence_batch,
    list_capital_allocations,
    latest_investment_score_batch,
    load_trading_policy,
    set_risk_policy_value,
)
from ..experience_engine import initialize_experience_engine_schema
from ..forecasting import latest_forecast, recent_forecasts
from ..market_intelligence_platform import initialize_market_intelligence_schema
from ..trade_scorecard import trade_scorecard
from ..decline_reasons import recent_decline_reasons
from ..intelligence import InvestmentIntelligenceDatabase
from ..models import AccountContext, Position, TradeProposal, utc_now_iso
from ..multi_broker import (
    all_broker_runtime,
    broker_auto_settings,
    broker_auto_trading_enabled,
    initialize_multi_broker_schema,
    latest_recommendation_set,
    list_performance_attribution,
    open_managed_exits,
    record_broker_trade_history,
    record_crypto_research_score,
    record_notification,
    record_recommendation_set,
    set_broker_auto_trading,
)
from ..orchestrator import InvestmentOrchestrator, OrchestratorContext, json_safe, next_research_run, _snapshot_equity_basis_matches_context
from ..canonical_trades import initialize_canonical_trade_schema
from ..daily_plan import daily_trading_plan_status
from ..kraken_reconciliation import (
    founder_override_kraken_hold,
    initialize_kraken_reconciliation_schema,
    kraken_reconciliation_status,
    record_founder_allocation,
    replay_persisted_kraken_evidence,
    resume_kraken_entries_after_verification,
    verify_kraken_reconciliation,
)
from ..operational import display_value, initialize_operational_schema, latest_pnl_snapshot, record_portfolio_snapshot, record_research_run, safe_float, safe_score, seed_crypto_universe
from ..operational_truth import initialize_operational_truth_schema, reconcile_broker_trade_rows, reconciliation_health
from ..rejection_review import deterministic_learned_synthesis, recent_crypto_rejection_digest
from ..portfolio_intelligence import initialize_portfolio_intelligence_schema, upsert_asset_metadata
from ..production_spine import initialize_production_spine_schema
from ..production_evidence import (
    founder_evidence_payload,
    initialize_production_evidence_schema,
    list_production_trade_evidence,
    prune_decision_and_audit_history,
    record_research_evidence,
)
from ..sprint6 import (
    apply_founder_strategy_authorization,
    generate_founder_operational_report,
    initialize_sprint6_schema,
    record_operational_event,
    refresh_strategy_maturity,
    seed_default_strategy_registry,
)
from ..scheduler import IntervalWorker, ResearchScheduler
from ..trading_intelligence import (
    STRATEGIES,
    calculate_calibration_metrics,
    initialize_trading_intelligence_schema,
    latest_intelligence_packets_batch,
    record_historical_candle,
    run_strategy_backtest,
    run_walk_forward_validation,
    update_calibration_from_attribution,
)


logger = logging.getLogger("ai_trader.api")

# Ask AI Trader time budget. Render's proxy hangs up at a hard 60s, and a request the
# proxy kills returns nothing at all -- the Founder sees "the request timed out" rather
# than a slightly-late answer. So Ask keeps its own budget well inside that ceiling and
# always returns *something*: a real OpenAI answer when there's time, the deterministic
# evidence summary when there isn't.
_ASK_TOTAL_BUDGET_SECONDS = 50.0
# Below this there isn't enough runway for an OpenAI round trip to be worth starting.
_ASK_MIN_OPENAI_SECONDS = 12.0
# The daily-learning section costs ~25s on its own; only gather it with room to spare.
_ASK_LEARNING_SECTION_MIN_SECONDS = 38.0

# Kept from each recommendation for Ask. The full row is ~118KB, nearly all of it
# trade_lifecycle/signals/committee internals that answer no founder question.
_ASK_RECOMMENDATION_FIELDS = (
    "proposal_id", "symbol", "company", "sector", "country", "confidence",
    "suggested_broker", "exchange", "asset_type", "market_open", "asset_available",
    "strategy_name", "market_regime", "created_at", "expires_at",
    "freshness_status", "freshness_note", "already_executed", "guardrails_passed",
    "guardrail_summary", "guardrail_failures", "auto_trade_eligible", "auto_trade_reason",
    "orchestrator_decision", "orchestrator_rejection_reason", "due_diligence_status",
    "investment_philosophy_fit", "probability_of_success", "expected_return_r",
    "recommended_position_size", "suggested_stop_loss", "suggested_take_profit",
    "reason_for_recommendation", "key_risks", "strongest_argument_for",
    "strongest_argument_against", "invalidation",
)
_ASK_RECOMMENDATION_TEXT_LIMIT = 600


def _seconds_left(deadline: float | None) -> float:
    """Remaining wall clock, or effectively unlimited when no deadline was set."""
    if deadline is None:
        return float("inf")
    return deadline - time.monotonic()


def _slim_recommendation(row: dict[str, Any]) -> dict[str, Any]:
    slim: dict[str, Any] = {}
    for key in _ASK_RECOMMENDATION_FIELDS:
        if key not in row:
            continue
        value = row[key]
        # The narrative fields are the useful ones, but an unbounded essay in any of
        # them puts the whole prompt back where it started.
        if isinstance(value, str) and len(value) > _ASK_RECOMMENDATION_TEXT_LIMIT:
            value = value[:_ASK_RECOMMENDATION_TEXT_LIMIT] + "..."
        slim[key] = value
    return slim


def configure_logging(output_dir: Path) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(output_dir / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        logger.warning("Could not open log file under %s; continuing with console logging only.", output_dir)


CONTROL_SCHEMA = """
CREATE TABLE IF NOT EXISTS engine_control (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    trading_state TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_command TEXT
);
"""

AUTO_TRADE_CONFIDENCE_THRESHOLD = 0.85

GUARDRAIL_CHECKS: list[tuple[str, str, str]] = [
    ("paper_trading_only_failed", "Paper trading account confirmed", "all"),
    ("invalid_side", "Trade side is valid", "all"),
    ("position_size_must_be_positive", "Position size is positive", "all"),
    ("entry_price_must_be_positive", "Entry price is positive", "all"),
    ("stop_loss_mandatory", "Stop loss is present", "all"),
    ("take_profit_mandatory", "Take profit is present", "all"),
    ("confidence_below_minimum", "Confidence meets the minimum threshold", "all"),
    ("account_equity_must_be_positive", "Account equity is positive", "all"),
    ("risk_must_be_positive", "Trade risk is measurable", "all"),
    ("max_account_risk_per_trade_exceeded", "Trade risk stays within account limit", "all"),
    ("declared_risk_percentage_exceeded", "Declared risk percentage is within limit", "all"),
    ("maximum_daily_loss_exceeded", "Daily loss limit has not been breached", "all"),
    ("maximum_open_positions_exceeded", "Open position limit has room", "all"),
    ("duplicate_open_position", "No duplicate long position", "buy"),
    ("short_selling_disabled", "Short selling rule is satisfied", "sell"),
    ("buy_stop_loss_must_be_below_entry", "Buy stop loss is below entry", "buy"),
    ("buy_take_profit_must_be_above_entry", "Buy take profit is above entry", "buy"),
    ("sell_stop_loss_must_be_above_entry", "Sell stop loss is above entry", "sell"),
    ("sell_take_profit_must_be_below_entry", "Sell take profit is below entry", "sell"),
    ("outside_regular_trading_hours", "Inside regular US market hours", "all"),
]


class LocalApiService:
    def __init__(self, settings: Settings, *, initialize_runtime: bool = True):
        self.settings = settings
        self._query_executor = QueryExecutor(settings.db_path)
        self.hosted_read_only = False
        self.api_token_configured = bool(os.getenv("AI_TRADER_API_TOKEN"))
        self.audit = AuditDatabase(
            settings.db_path,
            settings.trading_log_path,
            initialize_schema=initialize_runtime,
        )
        self._reporting_service = ReportingService(
            settings=settings,
            audit=self.audit,
            query_executor=self._query_executor,
            portfolio_lookup=self.portfolio,
            daily_learning_lookup=self.daily_learning_update,
        )
        self._founder_experience_service = FounderExperienceService(
            settings=settings,
            query_executor=self._query_executor,
            broker_panels_lookup=self.broker_panels,
            recommendations_lookup=self.recommendations,
            daily_learning_lookup=self.daily_learning_update,
            operational_truth_status_lookup=self.operational_truth_status,
            themes_lookup=self.themes,
            companies_lookup=self.companies,
            hosted_read_only_lookup=lambda: self.hosted_read_only,
            api_token_configured_lookup=lambda: self.api_token_configured,
        )
        if initialize_runtime:
            initialize_trading_intelligence_schema(settings.db_path)
        self.intelligence = InvestmentIntelligenceDatabase(
            settings.db_path,
            initialize_schema=initialize_runtime,
        )
        self.benchmark = BenchmarkIntelligenceDatabase(
            settings.db_path,
            initialize_schema=initialize_runtime,
        )
        self.orchestrator = InvestmentOrchestrator(
            db_path=settings.db_path,
            adapters=self._adapters(),
            initialize_schema=initialize_runtime,
        )
        self._research_service = ResearchService(
            settings=settings,
            audit=self.audit,
            orchestrator=self.orchestrator,
            query_executor=self._query_executor,
            # Lazy lambdas, not direct bound-method captures: tests/test_strategy_lab.py and
            # tests/test_production_evidence.py monkeypatch service._broker/.recommendations
            # as instance attributes *after* construction, which a captured bound method
            # would not see. Matches the live-reading pattern Phase 4 established for
            # hosted_read_only/api_token_configured for the same reason.
            account_context_lookup=lambda broker: self._account_context_for_broker(broker),
            recommendations_lookup=lambda limit: self.recommendations(limit),
            broker_factory=lambda: self._broker(),
        )
        self._broker_service = BrokerService(
            settings=settings,
            orchestrator=self.orchestrator,
            query_executor=self._query_executor,
            # Lazy lambdas, matching the live-reading pattern above/Phase 4/5: not
            # captured bound methods, since tests may monkeypatch service._broker
            # post-construction.
            broker_factory=lambda: self._broker(),
            kraken_balance_summary_lookup=lambda balances, adapter: _kraken_balance_summary(balances, adapter),
        )
        self._administration_service = AdministrationService(
            settings=settings,
            audit=self.audit,
            query_executor=self._query_executor,
        )
        self._operations_service = OperationsService(
            settings=settings,
            orchestrator=self.orchestrator,
            query_executor=self._query_executor,
            # Lazy lambdas, matching every prior phase's pattern: status() alone touches
            # nearly every other application service, and several of these (recommendations,
            # broker_panels, hosted-state) are monkeypatched or reassigned on the
            # LocalApiService instance after construction in various tests/run_server().
            recommendations_lookup=lambda limit: self.recommendations(limit),
            broker_panels_lookup=lambda: self.broker_panels(),
            executive_summary_lookup=lambda brokers: self.executive_summary(brokers),
            founder_executive_summary_lookup=lambda brokers, executive_summary: self.founder_executive_summary(brokers, executive_summary),
            connection_readiness_lookup=lambda brokers: self.connection_readiness(brokers),
            founder_experience_payload_lookup=lambda brokers, recommendations, policy, research_run: self.founder_experience_payload(brokers, recommendations, policy, research_run),
            world_class_evidence_lookup=lambda **kwargs: self.world_class_evidence(**kwargs),
            active_broker_names_lookup=lambda: self._active_broker_names(),
            continuous_research_status_lookup=lambda brokers: self._continuous_research_status(brokers),
            due_diligence_status_lookup=lambda: self._due_diligence_status(),
            control_state_lookup=lambda: self._control_state(),
            latest_daily_brief_lookup=lambda brief_type: self._latest_daily_brief(brief_type),
        )
        self._execution_service = ExecutionService(
            settings=settings,
            orchestrator=self.orchestrator,
            query_executor=self._query_executor,
            # Lazy lambdas, matching every prior phase's pattern (Phases 4/5 established
            # this is required wherever tests monkeypatch LocalApiService instance
            # attributes post-construction). _account_context_for_broker specifically
            # carries the Kraken AI capital-sleeve isolation logic and is deliberately
            # injected rather than duplicated, so it keeps exactly one implementation
            # anywhere in the codebase -- the same discipline Phases 5 and 6a established
            # for this exact function.
            account_context_lookup=lambda broker: self._account_context_for_broker(broker),
            control_state_lookup=lambda: self._control_state(),
            broker_managed_trade_capacity_lookup=lambda broker: self._broker_managed_trade_capacity(broker),
            portfolio_lookup=lambda broker: self.portfolio(broker),
        )
        if not initialize_runtime:
            return
        initialize_foundation_schema(settings.db_path)
        initialize_operational_schema(settings.db_path)
        initialize_multi_broker_schema(settings.db_path)
        initialize_operational_truth_schema(settings.db_path)
        initialize_market_intelligence_schema(settings.db_path)
        initialize_portfolio_intelligence_schema(settings.db_path)
        initialize_experience_engine_schema(settings.db_path)
        initialize_always_on_schema(settings.db_path)
        initialize_production_evidence_schema(settings.db_path)
        initialize_production_spine_schema(settings.db_path)
        initialize_sprint6_schema(settings.db_path)
        initialize_canonical_trade_schema(settings.db_path)
        initialize_kraken_reconciliation_schema(
            settings.db_path,
            allocation_gbp=_float_env("KRAKEN_TRADING_ALLOCATION_GBP", 100.0),
        )
        seed_default_strategy_registry(settings.db_path)
        self._reporting_service.initialize_schema()
        self._apply_env_broker_auto_defaults()
        self._apply_founder_kraken_live_authorization()
        self._initialize_control()

    def reconcile_on_startup(self) -> dict[str, Any]:
        stuck_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        stuck_locks = self._rows(
            "SELECT * FROM ORDER_INTENT_LOCKS WHERE status = 'locked' AND created_at < ?",
            (stuck_cutoff,),
        )
        open_exits = self._rows("SELECT * FROM MANAGED_TRADE_EXITS WHERE status = 'open'")
        reconciliation = {}
        for broker in ["alpaca", "kraken"]:
            rows = [
                dict(row)
                for row in self._rows(
                    """
                    SELECT *
                    FROM BROKER_TRADE_HISTORY
                    WHERE broker = ?
                    ORDER BY trade_history_id DESC
                    LIMIT 250
                    """,
                    (broker,),
                )
            ]
            reconciliation[broker] = reconcile_broker_trade_rows(self.settings.db_path, broker, rows)
        summary = {
            "stuck_order_intents": len(stuck_locks),
            "open_managed_exits": len(open_exits),
            "broker_reconciliation": reconciliation,
        }
        logger.info("Startup reconciliation: %s", summary)
        if stuck_locks:
            record_notification(
                self.settings.db_path,
                event_type="broker_failure",
                broker=None,
                symbol=None,
                title="Stuck order submissions detected at startup",
                message=(
                    f"{len(stuck_locks)} order intent lock(s) never completed before the last restart. "
                    "Review ORDER_INTENT_LOCKS for the affected broker/symbol."
                ),
                payload={"stuck_locks": [dict(row) for row in stuck_locks]},
            )
        return summary

    def notifications(self, *, unread_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        # Delegates to OperationsService (Phase 6b, architecture/AI_TRADER_MODULARISATION_
        # ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper -- "delegation before
        # deletion" -- so the GET/POST route dispatch table needed zero changes.
        return self._operations_service.notifications(unread_only=unread_only, limit=limit)

    def ack_notifications(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._operations_service.ack_notifications(body)

    def register_push_token_endpoint(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._operations_service.register_push_token_endpoint(body)

    def dispatch_pending_push_notifications(self) -> dict[str, Any]:
        # cli.py and run_server()'s scheduled job wiring call this externally.
        return self._operations_service.dispatch_pending_push_notifications()

    def refresh_crypto_universe(self) -> dict[str, Any]:
        # Delegates to ResearchService (Phase 5, architecture/AI_TRADER_MODULARISATION_
        # ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper -- "delegation before
        # deletion" -- since run_server() calls this externally on a scheduled interval.
        return self._research_service.refresh_crypto_universe()

    def refresh_strategy_lab(self) -> dict[str, Any]:
        # Delegates to ResearchService (Phase 5). Kept as a thin wrapper since cli.py
        # calls this externally (`service.refresh_strategy_lab()`).
        return self._research_service.refresh_strategy_lab()

    def refresh_crypto_candle_history(self) -> dict[str, Any]:
        # Delegates to ResearchService. Kept as a thin wrapper since cli.py calls this
        # externally (`service.refresh_crypto_candle_history()`), same convention as
        # refresh_strategy_lab above.
        return self._research_service.refresh_crypto_candle_history()

    def refresh_market_forecasts(self) -> dict[str, Any]:
        # Delegates to ResearchService, same thin-wrapper convention as above (cli.py
        # calls this externally for the forecast-refresh worker job).
        return self._research_service.refresh_market_forecasts()

    def forecast_one_symbol(self, symbol: str, *, asset_type: str = "crypto") -> dict[str, Any]:
        return self._research_service.forecast_one_symbol(symbol, asset_type=asset_type)

    def refresh_benchmark_research(self) -> dict[str, Any]:
        # Delegates to ResearchService, same thin-wrapper convention as above (cli.py
        # calls this externally for the benchmark-research-refresh worker job).
        return self._research_service.refresh_benchmark_research()

    def research_one_benchmark_trader(self, trader_name: str) -> dict[str, Any]:
        return self._research_service.research_one_benchmark_trader(trader_name)

    def run_crypto_analysis(self, symbols: list[str] | None = None, *, limit: int = 10) -> dict[str, Any]:
        # Delegates to ResearchService (Phase 5). Kept as a thin wrapper so callers
        # (POST /run-crypto-analysis, refresh_crypto_universe, run_analysis) needed no changes.
        return self._research_service.run_crypto_analysis(symbols, limit=limit)

    def review_crypto_rejections(self) -> dict[str, Any]:
        # Delegates to ResearchService. Kept as a thin wrapper since cli.py calls this
        # externally (`service.review_crypto_rejections()`).
        return self._research_service.review_crypto_rejections()

    def rollup_crypto_rejections(self) -> dict[str, Any]:
        # Delegates to ResearchService. Kept as a thin wrapper since cli.py calls this
        # externally (`service.rollup_crypto_rejections()`).
        return self._research_service.rollup_crypto_rejections()

    def get(self, path: str, query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
        if path == "/healthz":
            return 200, {"status": "ok", "generated_at": utc_now_iso()}
        if path == "/status":
            return 200, self.status()
        if path == "/founder-evidence":
            return 200, founder_evidence_payload(
                self.settings.db_path,
                period=_first(query, "period") or "24h",
                trade_limit=_int_or_default(_first(query, "trade_limit"), 100),
            )
        if path == "/market-forecast":
            # Phase 3/6 of the CIO-level forecasting build (2026-08-20). Returns the real
            # stored forecasts; an empty list is an honest "none generated yet", never a
            # placeholder or fabricated view.
            symbol = _first(query, "symbol")
            if symbol:
                forecast = latest_forecast(self.settings.db_path, symbol=symbol)
                return 200, {"symbol": symbol.upper(), "forecast": forecast, "generated_at": utc_now_iso()}
            return 200, {
                "forecasts": recent_forecasts(self.settings.db_path, limit=_int_or_default(_first(query, "limit"), 25)),
                "generated_at": utc_now_iso(),
            }
        if path == "/founder/trades":
            return 200, {
                "trades": list_production_trade_evidence(
                    self.settings.db_path,
                    broker=_first(query, "broker"),
                    limit=_int_or_default(_first(query, "limit"), 100),
                )
            }
        if path == "/decline-reasons":
            limit = max(1, min(_int_or_default(_first(query, "limit"), 8), 25))
            return 200, recent_decline_reasons(self.settings.db_path, limit=limit)
        if path == "/trade-scorecard":
            return 200, trade_scorecard(self.settings.db_path)
        if path == "/admin/trading-policy":
            # 2026-08-20: RISK_POLICIES had a writer (/admin/set-risk-policy) but no reader,
            # so the only way to learn a live policy value was to overwrite it and read the
            # returned previous_value. That is a poor tool for a project whose standing rule
            # is to verify against live production -- and it is how trailing_stop_enabled sat
            # at false, unnoticed, while the feature that depends on it was believed active.
            return 200, load_trading_policy(
                self.settings.db_path,
                auto_trade=self.settings.auto_trade,
                guardrails=self.settings.guardrails,
            ).to_dict()
        if path == "/portfolio":
            return 200, self.portfolio(_first(query, "broker") or "all")
        if path == "/founder-brief":
            return 200, self.founder_brief()
        if path == "/recommendations":
            # Full dossiers are intentionally on-demand. The two-minute Founder snapshot uses
            # compact summaries; only the Recommendations screen pays for this richer payload.
            limit = max(1, min(_int_or_default(_first(query, "limit"), 15), 50))
            return 200, {"recommendations": self.recommendations(limit=limit)}
        if path == "/intelligence/companies":
            return 200, {"companies": self.companies()}
        if path == "/intelligence/themes":
            return 200, {"themes": self.themes()}
        if path == "/benchmark-traders":
            return 200, {"benchmark_traders": self.benchmark_traders()}
        if path == "/benchmark-daily-brief":
            brief_date = _first(query, "date") or date.today().isoformat()
            return 200, self.benchmark_daily_brief(brief_date)
        if path == "/developer-status":
            return 200, self.developer_status()
        if path == "/developer-dashboard":
            return 200, {"html": DEVELOPER_DASHBOARD_HTML}
        if path == "/brokers":
            return 200, {"brokers": self.broker_panels()}
        if path == "/performance-attribution":
            return 200, {"performance_attribution": list_performance_attribution(self.settings.db_path)}
        if path == "/daily-learning-update":
            return 200, self.daily_learning_update(_first(query, "date"))
        if path == "/operational-truth":
            return 200, self.operational_truth_status()
        if path == "/world-class-evidence":
            return 200, self.world_class_evidence()
        if path == "/operations-health":
            return 200, self.operations_health()
        if path == "/scheduler-status":
            return 200, scheduler_status(self.settings.db_path)
        if path == "/job-runs":
            return 200, {"job_runs": list_job_runs(self.settings.db_path, limit=_int_or_default(_first(query, "limit"), 50), job_name=_first(query, "job_name"))}
        if path == "/shadow-trades":
            return 200, {"shadow_trades": list_shadow_trades(self.settings.db_path, broker=_first(query, "broker"), limit=_int_or_default(_first(query, "limit"), 100))}
        if path == "/shadow-performance":
            return 200, shadow_performance(self.settings.db_path)
        if path == "/research-funnel":
            return 200, {"research_funnels": list_research_funnels(self.settings.db_path, broker=_first(query, "broker"), limit=_int_or_default(_first(query, "limit"), 50))}
        if path == "/alpaca-inactivity-diagnosis":
            return 200, alpaca_inactivity_diagnosis(self.settings.db_path)
        if path == "/phase5-status":
            return 200, self.phase5_status()
        if path == "/sprint6-status":
            return 200, self.sprint6_status()
        if path == "/timing-diagnostics":
            return 200, self.timing_diagnostics(_first(query, "target") or "alpaca")
        if path == "/capital-allocations":
            # 2026-08-23: exposes the per-trade sizing record (account_equity,
            # requested_notional, approved_notional and the policy ceilings in force) so an
            # unexpected trade size can be read rather than reverse-engineered from
            # qty x entry_price. Three Kraken trades in two hours landed at GBP 6.03,
            # GBP 25.00 and GBP 3.86 with no way to see which limit produced each.
            return 200, {
                "capital_allocations": list_capital_allocations(
                    self.settings.db_path,
                    symbol=_first(query, "symbol"),
                    limit=_int_or_default(_first(query, "limit"), 25),
                )
            }
        if path == "/kraken-reconciliation":
            return 200, kraken_reconciliation_status(self.settings.db_path)
        if path == "/broker-decisions":
            return 200, {
                "broker_decisions": self.broker_decisions(
                    broker=_first(query, "broker"),
                    limit=_int_or_default(_first(query, "limit"), 20),
                )
            }
        if path == "/order-intent-locks":
            return 200, {
                "order_intent_locks": self.order_intent_locks(
                    broker=_first(query, "broker"),
                    status=_first(query, "status"),
                    limit=_int_or_default(_first(query, "limit"), 20),
                )
            }
        if path == "/kraken-reconciliation/verify":
            return 200, verify_kraken_reconciliation(self.settings.db_path)
        if path == "/autonomous-activity":
            return 200, self.production_activity(query)
        if path == "/activity/status":
            return 200, founder_evidence_payload(self.settings.db_path, period=_first(query, "period") or "24h")["status"]
        if path == "/activity/summary":
            return 200, founder_evidence_payload(self.settings.db_path, period=_first(query, "period") or "24h")["summary"]
        if path == "/activity/timeline":
            return 200, self._filtered_production_timeline(query)
        if path == "/activity/why-no-trade":
            return 200, founder_evidence_payload(self.settings.db_path, period=_first(query, "period") or "24h")["why_no_trade"]
        if path == "/daily-plan":
            return 200, daily_trading_plan_status(self.settings.db_path, broker=_first(query, "broker") or "alpaca")
        if path == "/crypto-rejections-explained":
            return 200, self.ask_about_crypto_rejections(hours=_int_or_default(_first(query, "hours"), 48))
        if path == "/activity/brokers":
            return 200, {"brokers": founder_evidence_payload(self.settings.db_path, period=_first(query, "period") or "24h")["brokers"]}
        if path == "/activity/founder-attention":
            payload = founder_evidence_payload(self.settings.db_path, period=_first(query, "period") or "24h")
            items = [] if payload["status"]["state"] == "OPERATING NORMALLY" else [{
                "title": payload["status"]["state"],
                "explanation": payload["status"]["plain_english"],
                "recommended_action": "Review worker, research, and broker evidence on this screen.",
                "started_at": payload["generated_at"],
            }]
            return 200, {"items": items, "count": len(items)}
        if path == "/operational-events":
            return 200, {"operational_events": self.operational_events(limit=_int_or_default(_first(query, "limit"), 50))}
        if path == "/decision-journal":
            return 200, {"decision_journal": self.decision_journal(limit=_int_or_default(_first(query, "limit"), 50))}
        if path == "/trading-report":
            return 200, self.trading_report(
                report_date=_first(query, "date"),
                broker=_first(query, "broker") or "all",
                report_type=_first(query, "type") or "daily",
                persist=True,
            )
        if path.startswith("/reports/"):
            return self.report_page(path)
        if path == "/notifications":
            return 200, {"notifications": self.notifications(unread_only=_first(query, "unread_only") == "true")}
        if path == "/database-diagnostics":
            return 200, database_size_report(self.settings.db_path)
        return 404, {"error": "not_found", "path": path}

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if path == "/run-analysis":
            return 200, self.run_analysis(body)
        if path == "/run-crypto-analysis":
            symbols = body.get("symbols")
            if isinstance(symbols, str):
                symbols = [item.strip().upper() for item in symbols.split(",") if item.strip()]
            return 200, self.run_crypto_analysis(symbols, limit=_int_or_default(body.get("limit"), 10))
        if path == "/forecast-symbol":
            # Single-symbol on-demand forecast (Phase 3 verification path). The full
            # forecast-refresh job is one real OpenAI call per symbol and far exceeds a
            # synchronous web request's budget; this one fits.
            symbol = str(body.get("symbol") or "").strip()
            if not symbol:
                return 400, {"error": "missing_symbol", "message": "Body must include a 'symbol'."}
            return 200, self.forecast_one_symbol(symbol, asset_type=str(body.get("asset_type") or "crypto"))
        if path == "/research-benchmark-trader":
            # Single-trader on-demand benchmark research (2026-08-21 verification path,
            # same reasoning as /forecast-symbol above). The full benchmark-research-refresh
            # job calls this once per tracked trader (currently 4) with real web search,
            # which comfortably exceeds a synchronous web request's budget; this one call
            # fits inside Render's ~60s proxy timeout.
            trader_name = str(body.get("trader_name") or "").strip()
            if not trader_name:
                return 400, {"error": "missing_trader_name", "message": "Body must include a 'trader_name' matching a BENCHMARK_TRADERS entry."}
            return 200, self.research_one_benchmark_trader(trader_name)
        if path == "/refresh-crypto-candle-history":
            # Manual trigger for the Phase 1 CIO-forecasting work (2026-08-20) -- lets the
            # hourly worker job be verified on demand against production instead of
            # waiting for its own schedule.
            return 200, self.refresh_crypto_candle_history()
        if path == "/start-trading":
            return 200, self.set_trading_state("running", "start-trading")
        if path == "/pause-trading":
            return 200, self.set_trading_state("paused", "pause-trading")
        if path == "/resume-trading":
            return 200, self.set_trading_state("running", "resume-trading")
        if path == "/stop-trading":
            return 200, self.set_trading_state("stopped", "stop-trading")
        if path == "/auto-execute-recommendations":
            return 200, self.auto_execute_recommendations()
        if path == "/approve-and-execute":
            return 200, self.approve_and_execute(body)
        if path == "/broker-auto-trading":
            return 200, self.set_broker_auto_trading(body)
        if path == "/monitor-managed-exits":
            return 200, self.monitor_managed_exits()
        if path == "/force-managed-exit":
            return 200, self.force_managed_exit(body)
        if path == "/close-position":
            return 200, self.close_position(body)
        if path == "/kraken-reconciliation/replay":
            return 200, replay_persisted_kraken_evidence(
                self.settings.db_path,
                limit=_int_or_default(body.get("limit"), 1000),
            )
        if path == "/kraken-reconciliation/verify":
            return 200, verify_kraken_reconciliation(self.settings.db_path)
        if path == "/kraken-reconciliation/resume":
            return 200, resume_kraken_entries_after_verification(self.settings.db_path)
        if path == "/kraken-reconciliation/founder-override":
            return 200, founder_override_kraken_hold(
                self.settings.db_path,
                reason=str(
                    body.get("reason")
                    or "Founder-authorized override (2026-08-01): unmatched Kraken history "
                    "confirmed as pre-existing personal/manual activity, not an AI Trader "
                    "accounting gap. explicit_order_ownership_exists can never pass for "
                    "evidence predating the 2026-07-27 reconciliation bootstrap."
                ),
            )
        if path == "/order-intent-locks/release":
            return 200, self.release_order_intent_lock_for(
                broker=str(body.get("broker") or ""),
                client_order_id=str(body.get("client_order_id") or ""),
                confirmed_no_order_placed=bool(body.get("confirmed_no_order_placed")),
            )
        if path == "/database-diagnostics/vacuum":
            table_name = str(body.get("table_name") or "")
            if not bool(body.get("confirmed_by_founder")):
                return 200, {
                    "status": "refused",
                    "message": "Set confirmed_by_founder=true only after the Founder has explicitly approved running "
                    "VACUUM on this specific table, since VACUUM (FULL) locks it for the duration of the operation.",
                }
            return 200, vacuum_table(self.settings.db_path, table_name, full=bool(body.get("full")))
        if path == "/database-diagnostics/prune-decision-audit-history":
            if not bool(body.get("confirmed_by_founder")):
                return 200, {
                    "status": "refused",
                    "message": "Set confirmed_by_founder=true only after the Founder has explicitly approved running "
                    "this DELETE against real governance/decision history. See DECISION_AUDIT_TABLES in "
                    "production_evidence.py for exactly which tables and protections apply.",
                }
            kwargs: dict[str, Any] = {"force": bool(body.get("force")), "explicitly_confirmed": True}
            if body.get("retention_days") is not None:
                kwargs["retention_days"] = int(body["retention_days"])
            return 200, prune_decision_and_audit_history(self.settings.db_path, **kwargs)
        if path == "/generate-report":
            return 200, self.generate_report(body)
        if path == "/generate-operational-report":
            return 200, generate_founder_operational_report(
                self.settings.db_path,
                output_dir=self.settings.output_dir,
                report_type=str(body.get("type") or "daily"),
                period_start=body.get("period_start"),
                period_end=body.get("period_end"),
            )
        if path == "/ask-ai-trader":
            return 200, self.ask_ai_trader(body)
        if path == "/admin/set-risk-policy":
            key = str(body.get("key") or "").strip()
            if not key:
                return 400, {"error": "missing_key", "message": "Body must include a 'key' naming an existing RISK_POLICIES row."}
            return 200, set_risk_policy_value(self.settings.db_path, key, body.get("value"), updated_by=str(body.get("updated_by") or "founder"))
        if path == "/admin/kraken-allocation":
            # Founder capital top-up for the Kraken AI ledger. Needs an explicit
            # `reference` so a retried call cannot double-credit the allocation.
            try:
                amount = float(body.get("amount_gbp"))
            except (TypeError, ValueError):
                return 400, {"error": "invalid_amount", "message": "Body must include a numeric 'amount_gbp'."}
            reference = str(body.get("reference") or "").strip()
            if not reference:
                return 400, {"error": "missing_reference", "message": "Body must include a unique 'reference' for idempotency."}
            return 200, record_founder_allocation(
                self.settings.db_path,
                amount_gbp=amount,
                reference=reference,
                note=body.get("note"),
            )
        if path == "/notifications/ack":
            return 200, self.ack_notifications(body)
        if path == "/register-push-token":
            return 200, self.register_push_token_endpoint(body)
        return 404, {"error": "not_found", "path": path}

    def status(self) -> dict[str, Any]:
        # Delegates to OperationsService (Phase 6b). Kept as a thin wrapper -- callers
        # (GET /status, tests) needed zero changes.
        return self._operations_service.status()

    def operations_health(self) -> dict[str, Any]:
        return self._operations_service.operations_health()

    def phase5_status(self) -> dict[str, Any]:
        return self._operations_service.phase5_status()

    def sprint6_status(self) -> dict[str, Any]:
        return self._operations_service.sprint6_status()

    def production_activity(self, query: dict[str, list[str]]) -> dict[str, Any]:
        return self._operations_service.production_activity(query)

    def _filtered_production_timeline(
        self,
        query: dict[str, list[str]],
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._operations_service._filtered_production_timeline(query, payload=payload)

    def operational_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._operations_service.operational_events(limit=limit)

    def decision_journal(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._operations_service.decision_journal(limit=limit)

    def founder_experience_payload(
        self,
        brokers: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        policy: Any,
        research_run: dict[str, Any] | None,
    ) -> dict[str, Any]:
        # Delegates to FounderExperienceService (Phase 4, architecture/AI_TRADER_
        # MODULARISATION_ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper --
        # "delegation before deletion" -- so callers needed zero changes.
        return self._founder_experience_service.founder_experience_payload(brokers, recommendations, policy, research_run)

    def portfolio(self, broker_filter: str = "all") -> dict[str, Any]:
        broker_filter = broker_filter.lower()
        if broker_filter in {"kraken", "coinbase"}:
            return self._exchange_portfolio(broker_filter)
        if not self.settings.has_alpaca_credentials:
            return {
                "portfolio_value": "Not available - Alpaca paper credentials are not configured",
                "cash_available": "Not available - Alpaca paper credentials are not configured",
                "todays_pnl": "Not available - Alpaca paper credentials are not configured",
                "open_positions": [],
                "source": "Not available: Alpaca paper credentials are not configured.",
                "executive_summary": self.executive_summary(),
            }
        try:
            portfolio = self._live_alpaca_portfolio()
            return {**portfolio, "executive_summary": self.executive_summary()}
        except Exception as exc:
            # AT-ED-011.7: this previously interpolated the raw exception straight into
            # Founder-facing fields (f"Not available - {exc}") - for a Postgres-layer failure
            # that could include a psycopg/sqlite3-compatibility exception's low-level wording
            # (table/column names, driver internals). The real exception is logged here, in
            # full, for engineering; the Founder only ever sees a safe, generic reason.
            logger.exception("Live Alpaca portfolio fetch failed")
            reason = "Not available - the live Alpaca portfolio could not be loaded right now."
            return {
                "portfolio_value": reason,
                "cash_available": reason,
                "todays_pnl": reason,
                "open_positions": [],
                "source": reason,
                "executive_summary": self.executive_summary(),
            }

    def founder_brief(self) -> dict[str, Any]:
        row = self._row("SELECT * FROM daily_briefings ORDER BY id DESC LIMIT 1")
        if row:
            return {"briefing_date": row["briefing_date"], "report_markdown": row["report_markdown"], "created_at": row["created_at"]}
        markdown = generate_daily_briefing(self.audit, date.today(), self.settings.output_dir)
        return {"briefing_date": date.today().isoformat(), "report_markdown": markdown, "created_at": utc_now_iso()}

    def operational_truth_status(self) -> dict[str, Any]:
        health = reconciliation_health(self.settings.db_path)
        lifecycle_count = self._scalar("SELECT COUNT(*) FROM CANONICAL_TRADE_LIFECYCLE") or 0
        rejected_count = self._scalar("SELECT COUNT(*) FROM LIFECYCLE_TRANSITION_REJECTIONS") or 0
        latest_events = [
            dict(row)
            for row in self._rows(
                """
                SELECT created_at, broker, symbol, stage, event_source, event_reason
                FROM CANONICAL_TRADE_LIFECYCLE
                ORDER BY lifecycle_id DESC
                LIMIT 20
                """
            )
        ]
        return {
            "status": "active",
            "canonical_lifecycle_events": lifecycle_count,
            "illegal_transition_rejections": rejected_count,
            "reconciliation_health": health,
            "latest_events": latest_events,
            "plain_english": (
                "Alpaca and Kraken broker events now feed a single canonical lifecycle. "
                "Duplicate polling is ignored by idempotency keys; illegal lifecycle jumps are logged for review."
            ),
        }

    def world_class_evidence(
        self,
        *,
        brokers: list[dict[str, Any]] | None = None,
        recommendations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # Delegates to FounderExperienceService (Phase 4, architecture/AI_TRADER_
        # MODULARISATION_ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper --
        # "delegation before deletion" -- so callers needed zero changes.
        return self._founder_experience_service.world_class_evidence(brokers=brokers, recommendations=recommendations)

    def generate_report(self, body: dict[str, Any]) -> dict[str, Any]:
        # Delegates to ReportingService (Phase 3, architecture/AI_TRADER_MODULARISATION_
        # ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper -- "delegation before
        # deletion" -- so the GET/POST route dispatch table needed zero changes.
        return self._reporting_service.generate_report(body)

    def ask_ai_trader(self, body: dict[str, Any]) -> dict[str, Any]:
        question = str(body.get("question") or "").strip()
        if not question:
            return {
                "status": "rejected",
                "answer": "Ask me a question about AI Trader's balances, trades, reports, recommendations, or learning.",
                "read_only": True,
            }
        deadline = time.monotonic() + _ASK_TOTAL_BUDGET_SECONDS
        context = self._ask_ai_context(deadline=deadline)
        if not self.settings.openai_api_key:
            return {
                "status": "openai_not_configured",
                "answer": _deterministic_ai_trader_answer(question, context),
                "read_only": True,
                "model": None,
                "note": "OPENAI_API_KEY is not configured for this AI Trader deployment, so this answer used the local evidence summary only.",
                "evidence": context,
            }
        remaining = _seconds_left(deadline)
        if remaining < _ASK_MIN_OPENAI_SECONDS:
            logger.warning("Ask AI Trader context build left only %.1fs; answering from evidence instead.", remaining)
            return {
                "status": "evidence_only",
                "answer": _deterministic_ai_trader_answer(question, context),
                "read_only": True,
                "model": None,
                "note": "Gathering the evidence used up the time available for this question, so this answer came from the stored evidence directly. Ask again for a fuller answer.",
                "evidence": context,
            }
        explainer = OpenAIReadOnlyExplainer(
            self.settings.openai_api_key, self.settings.openai_model, timeout_seconds=remaining
        )
        try:
            answer = explainer.answer(question, context)
        except Exception as exc:
            logger.exception("Ask AI Trader OpenAI explanation failed; returning deterministic fallback.")
            return {
                "status": "openai_failed",
                "answer": _deterministic_ai_trader_answer(question, context),
                "read_only": True,
                "model": self.settings.openai_model,
                "note": f"OpenAI explanation failed, so this answer used the local evidence summary only. Reason: {exc}",
                "evidence": context,
            }
        return {
            "status": "answered",
            "answer": answer or _deterministic_ai_trader_answer(question, context),
            "read_only": True,
            "model": self.settings.openai_model,
            "note": "Ask AI Trader is read-only. It cannot place trades, approve trades, change guardrails, or change broker settings.",
            "evidence": context,
        }

    def crypto_rejection_digest(self, *, hours: int = 48) -> dict[str, Any]:
        # Deterministic, no OpenAI call -- see recent_crypto_rejection_digest's own
        # docstring for why the "what and why" half doesn't need one.
        return recent_crypto_rejection_digest(self.settings.db_path, hours=hours)

    def ask_about_crypto_rejections(self, *, hours: int = 48) -> dict[str, Any]:
        """The Founder's pre-built Ask-AI-Trader question (2026-08-16): what crypto
        was rejected recently, why, and has the system learned from it. Mirrors
        ask_ai_trader's structure/fallback behavior exactly, but only the "has it
        learned" synthesis is worth a real OpenAI call -- the "what and why" half
        (the digest) is answered directly from stored data, for free, instantly."""
        digest = self.crypto_rejection_digest(hours=hours)
        question = (
            "Based only on the crypto rejection digest supplied as context (which Kraken coins were rejected "
            "recently, why, and -- for anything already reviewed -- what price did afterward), has the trading "
            "system's judgment on these rejections been vindicated or found wanting, and is there any sign it "
            "should adjust course? Be honest about a small sample size."
        )
        if not self.settings.openai_api_key:
            return {
                "status": "openai_not_configured",
                "digest": digest,
                "learned_synthesis": deterministic_learned_synthesis(digest),
                "read_only": True,
                "model": None,
                "note": "OPENAI_API_KEY is not configured for this AI Trader deployment, so this used the local digest summary only.",
            }
        explainer = OpenAIReadOnlyExplainer(self.settings.openai_api_key, self.settings.openai_model)
        try:
            synthesis = explainer.answer(question, {"crypto_rejection_digest": digest})
        except Exception as exc:
            logger.exception("Crypto rejection 'has it learned' synthesis failed; returning deterministic fallback.")
            return {
                "status": "openai_failed",
                "digest": digest,
                "learned_synthesis": deterministic_learned_synthesis(digest),
                "read_only": True,
                "model": self.settings.openai_model,
                "note": f"OpenAI synthesis failed, so this used the local digest summary only. Reason: {exc}",
            }
        return {
            "status": "answered",
            "digest": digest,
            "learned_synthesis": synthesis or deterministic_learned_synthesis(digest),
            "read_only": True,
            "model": self.settings.openai_model,
            "note": "Read-only. Cannot place trades, approve trades, change guardrails, or change broker settings.",
        }

    def _ask_ai_context(self, *, deadline: float | None = None) -> dict[str, Any]:
        """Evidence for one Ask question, built to a wall-clock deadline.

        2026-08-24: this used to embed world_class_evidence and two separate
        recommendations(limit=20) calls. Measured against production that was
        unanswerable, not merely slow: /world-class-evidence on its own exceeds
        Render's hard 60s proxy timeout, and each recommendation row carries ~118KB
        of trade_lifecycle/signals/committee detail, so the two calls alone built
        ~3.4MB of context that then had to be JSON-encoded into an OpenAI prompt.
        Every Ask request died at the proxy before OpenAI ever replied.

        None of that bulk was answering questions -- world_class_evidence is the
        self-audit panel the briefing screen already renders, and a founder asking
        "what did you buy and why" needs a recommendation's symbol and reason, not
        its full lifecycle. Slim context, one query, and heavy optional sections
        only while the clock allows."""
        broker_panels = self.broker_panels()
        context = {
            "generated_at": utc_now_iso(),
            "safety_boundary": "Read-only explanation. No trading, approvals, broker controls, or guardrail changes are available to this endpoint.",
            "openai_configured": bool(self.settings.openai_api_key),
            "trading_state": self._control_state(),
            "broker_auto_trading": broker_auto_settings(self.settings.db_path),
            "broker_panels": broker_panels,
            "latest_portfolio_snapshots": [
                dict(row) for row in self._rows(
                    """
                    SELECT broker, exchange, created_at, portfolio_value, cash, buying_power,
                           day_pnl, week_pnl, month_pnl, open_positions_count
                    FROM PORTFOLIO_SNAPSHOTS
                    ORDER BY created_at DESC
                    LIMIT 12
                    """
                )
            ],
            "latest_broker_trades": [
                dict(row) for row in self._rows(
                    """
                    SELECT broker, symbol, side, quantity, price, notional, status,
                           opened_at, closed_at, updated_at
                    FROM BROKER_TRADE_HISTORY
                    ORDER BY COALESCE(closed_at, opened_at, updated_at) DESC, trade_history_id DESC
                    LIMIT 30
                    """
                )
            ],
            "latest_closed_trade_attribution": [
                dict(row) for row in self._rows(
                    """
                    SELECT broker, symbol, asset_type, side, entry_price, exit_price, quantity,
                           profit_loss, opened_at, closed_at, entry_reason, exit_reason
                    FROM PERFORMANCE_ATTRIBUTION
                    ORDER BY COALESCE(closed_at, created_at) DESC, attribution_id DESC
                    LIMIT 20
                    """
                )
            ],
            "latest_reports": [
                dict(row) for row in self._rows(
                    """
                    SELECT report_date, broker, report_type, summary, created_at
                    FROM TRADING_REPORTS
                    ORDER BY report_id DESC
                    LIMIT 8
                    """
                )
            ],
            "latest_recommendations": [
                _slim_recommendation(row) for row in self.recommendations(limit=20)
            ],
            "latest_orchestrator_decisions": [
                dict(row) for row in self._rows(
                    """
                    SELECT created_at, selected_broker, symbol, requested_action, decision, rejection_reason, confidence_score
                    FROM ORCHESTRATOR_DECISIONS
                    ORDER BY decision_id DESC
                    LIMIT 20
                    """
                )
            ],
        }
        # Measured at ~25s in production. Worth having when there's room for it -- it is
        # what answers "is AI Trader getting better?" -- but never worth spending the
        # budget that the actual answer needs.
        if _seconds_left(deadline) > _ASK_LEARNING_SECTION_MIN_SECONDS:
            context["daily_learning"] = self.daily_learning_update(date.today().isoformat())
        else:
            context["daily_learning"] = {
                "skipped": "Omitted to keep this answer inside the request time budget."
            }
        return context

    def trading_report(self, *, report_date: str | None, broker: str = "all", report_type: str = "daily", persist: bool = False) -> dict[str, Any]:
        return self._reporting_service.trading_report(report_date=report_date, broker=broker, report_type=report_type, persist=persist)

    def report_page(self, path: str) -> tuple[int, dict[str, Any]]:
        return self._reporting_service.report_page(path)

    def recommendations(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._rows(
            """
            SELECT ta.*, cm.company_name, cm.country, cm.sector, cm.investment_thesis,
                   cm.reasons_for_caution, iw.current_investment_philosophy_fit
            FROM trade_audit ta
            LEFT JOIN COMPANY_MASTER cm ON UPPER(cm.ticker) = UPPER(ta.symbol)
            LEFT JOIN INVESTMENT_WATCHLIST iw ON iw.company_id = cm.id
            WHERE ta.event_type = 'agent_proposal'
            ORDER BY ta.ai_confidence DESC, ta.created_at DESC, ta.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        # 2026-08-15: batch every per-row lookup up front instead of inside the loop below.
        # Each of these used to run once per row (already_executed, orchestrator decision,
        # due diligence, investment score, intelligence packet) and every one of them opens
        # its own fresh Postgres connection (database.py's connect() has no pooling) -- for
        # the mobile app's real limit=15 request that was ~75 fresh connections for one API
        # call, which is exactly the kind of thing that times out or trips Supabase
        # connection limits. Five batched IN-clause lookups replace all of it.
        proposal_ids = [row["proposal_id"] for row in rows]
        already_executed_ids = self._already_executed_batch(proposal_ids)
        decisions_by_id = self._latest_orchestrator_decisions_batch(proposal_ids)
        due_diligence_by_id = latest_due_diligence_batch(self.settings.db_path, proposal_ids)
        investment_score_by_id = latest_investment_score_batch(self.settings.db_path, proposal_ids)
        intelligence_packets_by_id = latest_intelligence_packets_batch(self.settings.db_path, proposal_ids)

        recommendations: list[dict[str, Any]] = []
        seen: set[str] = set()
        # proposal_broker is almost always just "alpaca"/"kraken" across the whole result
        # set, but broker_auto_trading_enabled() also opens its own fresh connection (plus a
        # schema-init) per call -- memoize per distinct broker string rather than per row.
        broker_auto_enabled_cache: dict[str, bool] = {}
        for row in rows:
            if row["proposal_id"] in seen:
                continue
            seen.add(row["proposal_id"])
            freshness = _recommendation_freshness(row["created_at"], row["ai_confidence"], row["broker"])
            already_executed = row["proposal_id"] in already_executed_ids
            guardrails_passed = bool(row["execution_guardrails_passed"])
            guardrail_failures = _validation_failures(row["validation_result"])
            guardrail_checks = _guardrail_checks(row["validation_result"], row["payload_json"])
            confidence = safe_score(row["ai_confidence"]) or 0.0
            philosophy_fit = safe_score(row["current_investment_philosophy_fit"]) or _proposal_philosophy_fit(row["payload_json"]) or 0.0
            decision = decisions_by_id.get(row["proposal_id"])
            proposal_broker = self._proposal_broker(row["payload_json"])
            if proposal_broker is None:
                broker_auto_enabled = self.settings.auto_trade.enabled
            elif proposal_broker in broker_auto_enabled_cache:
                broker_auto_enabled = broker_auto_enabled_cache[proposal_broker]
            else:
                broker_auto_enabled = broker_auto_trading_enabled(
                    self.settings.db_path,
                    proposal_broker,
                    self.settings.auto_trade.broker_enabled.get(proposal_broker, False),
                )
                broker_auto_enabled_cache[proposal_broker] = broker_auto_enabled
            due_diligence = due_diligence_by_id.get(row["proposal_id"])
            investment_score = investment_score_by_id.get(row["proposal_id"])
            payload_intelligence = _payload_intelligence(row["payload_json"]) or {}
            stored_intelligence = intelligence_packets_by_id.get(row["proposal_id"]) or {}
            intelligence = {**payload_intelligence, **stored_intelligence} if (payload_intelligence or stored_intelligence) else None
            committee = (intelligence or {}).get("committee") or {}
            probability = (intelligence or {}).get("probability") or {}
            explainability = (intelligence or {}).get("explainability") or {}
            trade_setup = (intelligence or {}).get("trade_setup") or {}
            strategy = _payload_strategy(row["payload_json"], intelligence)
            regime = _payload_regime(row["payload_json"], intelligence)
            strongest_for = committee.get("strongest_argument_for") or row["ai_reasoning"]
            strongest_against = committee.get("strongest_argument_against") or row["reasons_for_caution"] or _format_guardrail_failures(guardrail_failures)
            has_dossier_arguments = bool(str(strongest_for or "").strip()) and bool(str(strongest_against or "").strip())
            auto_trade_eligible = (
                guardrails_passed
                and freshness["status"] != "Expired"
                and confidence >= self.settings.auto_trade.min_confidence
                and philosophy_fit >= self.settings.auto_trade.min_philosophy_fit
                and not already_executed
                and broker_auto_enabled
                and has_dossier_arguments
            )
            recommendations.append(
                {
                    "proposal_id": row["proposal_id"],
                    "symbol": row["symbol"],
                    "company": row["company_name"],
                    "ticker": row["symbol"],
                    "sector": row["sector"],
                    "country": row["country"],
                    "confidence": confidence if confidence else None,
                    "investment_score": _score_payload(investment_score, confidence, philosophy_fit),
                    "strategy": strategy,
                    "strategy_id": (strategy or {}).get("strategy_id") or committee.get("strategy_id") or probability.get("strategy_id"),
                    "strategy_name": (strategy or {}).get("name"),
                    "market_regime": regime,
                    "probability": probability,
                    "committee": committee,
                    "signals": (intelligence or {}).get("signals") or [],
                    "trade_lifecycle": (intelligence or {}).get("lifecycle") or [],
                    "strongest_argument_for": strongest_for,
                    "strongest_argument_against": strongest_against,
                    "invalidation": (explainability.get("invalidation_conditions") or trade_setup.get("invalidation_conditions") or []),
                    "why_no_action_may_be_better": _why_no_action_may_be_better(committee, probability, guardrail_failures, freshness["status"]),
                    "probability_of_success": probability.get("probability_of_success"),
                    "expected_return_r": probability.get("expected_return_r"),
                    "calibration_status": probability.get("calibration_status"),
                    "asset_available": None if decision is None else bool(decision["asset_available"]),
                    "suggested_broker": decision["selected_broker"] if decision is not None else proposal_broker,
                    "exchange": _proposal_exchange(row["payload_json"]),
                    "asset_type": _proposal_asset_type(row["payload_json"]),
                    "market_open": None if decision is None else bool(decision["market_open"]),
                    "orchestrator_decision": None if decision is None else decision["decision"],
                    "orchestrator_rejection_reason": None if decision is None else decision["rejection_reason"],
                    "investment_philosophy_fit": philosophy_fit,
                    "investment_thesis": row["investment_thesis"],
                    "reason_for_recommendation": row["ai_reasoning"],
                    "key_risks": row["reasons_for_caution"] or row["validation_result"],
                    "suggested_stop_loss": row["stop_loss"],
                    "suggested_take_profit": row["take_profit"],
                    "suggested_position_size": row["position_size"],
                    "recommended_position_size": row["position_size"],
                    "created_at": row["created_at"],
                    "due_diligence_status": (due_diligence or {}).get("overall_status") or "Not available - not assessed by orchestrator yet",
                    "due_diligence": due_diligence,
                    "expires_at": freshness["expires_at"],
                    "freshness_status": freshness["status"],
                    "freshness_note": freshness["note"],
                    "auto_trade_eligible": auto_trade_eligible,
                    "auto_trade_reason": _auto_trade_reason(
                        confidence=confidence,
                        philosophy_fit=philosophy_fit,
                        auto_enabled=broker_auto_enabled,
                        auto_label=f"{proposal_broker} auto trading" if proposal_broker else "AUTO_PAPER_TRADING",
                        min_confidence=self.settings.auto_trade.min_confidence,
                        min_philosophy_fit=self.settings.auto_trade.min_philosophy_fit,
                        freshness_status=freshness["status"],
                        guardrails_passed=guardrails_passed,
                        already_executed=already_executed,
                        guardrail_failures=guardrail_failures,
                        has_dossier_arguments=has_dossier_arguments,
                    ),
                    "guardrail_failures": guardrail_failures,
                    "guardrail_summary": "Passed" if guardrails_passed else _format_guardrail_failures(guardrail_failures),
                    "guardrail_checks": guardrail_checks,
                    "guardrail_passes": [
                        check["label"]
                        for check in guardrail_checks
                        if check["status"] == "passed"
                    ],
                    "already_executed": already_executed,
                    "guardrails_passed": guardrails_passed,
                }
            )
        return sorted(
            recommendations,
            key=lambda item: (
                safe_score(item["confidence"]) or 0,
                _parse_datetime(item["created_at"]) or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )

    def companies(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self._rows(
                """
                SELECT cm.*, iw.current_watchlist_priority, iw.current_investment_philosophy_fit, iw.active
                FROM COMPANY_MASTER cm
                LEFT JOIN INVESTMENT_WATCHLIST iw ON iw.company_id = cm.id
                ORDER BY cm.company_name ASC
                """
            )
        ]

    def themes(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows("SELECT * FROM MARKET_THEMES ORDER BY theme ASC")]

    def benchmark_traders(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows("SELECT * FROM BENCHMARK_TRADERS WHERE active = 1 ORDER BY trader_name ASC")]

    def benchmark_daily_brief(self, brief_date: str) -> dict[str, Any]:
        rows = [
            dict(row)
            for row in self._rows(
                """
                SELECT bt.trader_name, bt.platform, bt.strategy_style, bt.risk_rating,
                       bdr.research_date, bdr.source, bdr.observed_trade_or_portfolio_change,
                       bdr.ai_interpretation, bdr.risk_lesson, bdr.market_lesson,
                       bdr.related_company, bdr.related_sector, bdr.related_theme,
                       bdr.confidence, bdr.impact_on_our_view
                FROM BENCHMARK_DAILY_RESEARCH bdr
                JOIN BENCHMARK_TRADERS bt ON bt.trader_id = bdr.trader_id
                WHERE bdr.research_date = ?
                ORDER BY bt.trader_name ASC
                """,
                (brief_date,),
            )
        ]
        reason = None
        source_date = brief_date
        if not rows:
            latest = self._scalar("SELECT MAX(research_date) FROM BENCHMARK_DAILY_RESEARCH")
            if latest:
                source_date = latest
                rows = [
                    dict(row)
                    for row in self._rows(
                        """
                        SELECT bt.trader_name, bt.platform, bt.strategy_style, bt.risk_rating,
                               bdr.research_date, bdr.source, bdr.observed_trade_or_portfolio_change,
                               bdr.ai_interpretation, bdr.risk_lesson, bdr.market_lesson,
                               bdr.related_company, bdr.related_sector, bdr.related_theme,
                               bdr.confidence, bdr.impact_on_our_view
                        FROM BENCHMARK_DAILY_RESEARCH bdr
                        JOIN BENCHMARK_TRADERS bt ON bt.trader_id = bdr.trader_id
                        WHERE bdr.research_date = ?
                        ORDER BY bt.trader_name ASC
                        """,
                        (latest,),
                    )
                ]
                reason = f"No benchmark rows for {brief_date}; showing latest seeded research from {latest}."
            else:
                reason = "Benchmark seed data has not been loaded yet."
        summary = reason if reason and not rows else "Benchmark intelligence is for learning only. Do not copy trades automatically."
        return {"date": brief_date, "source_date": source_date, "summary": summary, "items": rows, "unavailable_reason": reason}

    def developer_status(self) -> dict[str, Any]:
        # Delegates to OperationsService (Phase 6b). Kept as a thin wrapper -- callers
        # (GET /developer-status, tests/test_developer_experience.py) needed zero changes.
        return self._operations_service.developer_status()

    def run_analysis(self, body: dict[str, Any]) -> dict[str, Any]:
        # Delegates to ResearchService (Phase 5). Kept as a thin wrapper so callers
        # (POST /run-analysis) needed no changes.
        return self._research_service.run_analysis(body)

    def _refresh_asset_metadata_from_company_master(self, symbols: list[str]) -> int:
        # Delegates to ResearchService (Phase 5). Kept as a thin wrapper: this "private"
        # method has no internal caller left in this file (its only caller, run_analysis,
        # moved with it), but tests/test_asset_metadata_refresh.py calls it directly on the
        # LocalApiService instance, so it is a real external caller, not a dead method.
        return self._research_service._refresh_asset_metadata_from_company_master(symbols)

    def _record_production_research(
        self,
        started_at: str,
        broker: str,
        asset_type: str,
        trigger_type: str,
        symbols: list[str],
        result: dict[str, Any],
    ) -> None:
        # Delegates to ResearchService (Phase 5). Kept as a thin wrapper: tests/
        # test_production_evidence.py calls this directly on the LocalApiService instance.
        return self._research_service._record_production_research(started_at, broker, asset_type, trigger_type, symbols, result)

    def set_trading_state(self, state: str, command: str) -> dict[str, Any]:
        # Delegates to AdministrationService (Phase 7, architecture/AI_TRADER_
        # MODULARISATION_ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper --
        # "delegation before deletion" -- so callers needed zero changes.
        return self._administration_service.set_trading_state(state, command)

    def approve_and_execute(self, body: dict[str, Any]) -> dict[str, Any]:
        # Delegates to ExecutionService (Phase 8, architecture/AI_TRADER_MODULARISATION_
        # ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper -- "delegation before
        # deletion" -- so the GET/POST route dispatch table and tests needed no changes.
        return self._execution_service.approve_and_execute(body)

    def close_position(self, body: dict[str, Any]) -> dict[str, Any]:
        # 2026-08-12: Founder-requested capability. Unlike force_managed_exit (Kraken-only,
        # keyed off the local managed_exits table), Alpaca positions never get a local
        # managed_exit row -- they rely on Alpaca's own native bracket-order legs for
        # protection (see alpaca.py's time_in_force fix, same incident) and have no existing
        # "force exit" path at all. Delegates to ExecutionService, matching every other
        # broker-action route.
        return self._execution_service.close_broker_position(body)

    def _account_context_for_broker(self, broker_name: str) -> AccountContext:
        snapshot = latest_pnl_snapshot(self.settings.db_path, broker_name)
        daily_pnl = safe_float(snapshot.get("day_pnl")) or 0.0
        if broker_name == "alpaca":
            return self._broker().account_context(daily_realized_pnl=daily_pnl)
        adapter = self.orchestrator.adapters.get(broker_name)
        equity = 0.0
        if adapter is not None:
            account = adapter.get_account()
            balances = account.get("balances") if isinstance(account, dict) else None
            if broker_name == "kraken":
                equity = _kraken_trading_allocation_gbp(balances)
            else:
                equity = _sum_balances(balances) or 0.0
        # PORTFOLIO_SNAPSHOTS.day_pnl (and the whole-account portfolio_value it is derived
        # from) reflects the broker's WHOLE account - for Kraken specifically that includes
        # the Founder's pre-existing personal holdings alongside the AI's own isolated
        # allocation (`equity` above, deliberately scoped via _kraken_trading_allocation_gbp),
        # so it can be an order of magnitude larger. Comparing that whole-account day_pnl
        # against the tiny scoped equity in guardrails.py's maximum_daily_loss_exceeded check
        # meant ordinary price movement on capital the AI never touched could permanently
        # block every Kraken trade - confirmed in hosted evidence (2026-08-05/06): a 100%
        # rejection rate, every eligible candidate, every auto-execution cycle, always citing
        # maximum_daily_loss_exceeded. orchestrator.py's weekly/monthly/drawdown checks
        # already guard against this exact mismatch via
        # _snapshot_equity_basis_matches_context - applying the same guard here, at the
        # source, so every consumer of this AccountContext gets a same-basis daily P&L or an
        # honest 0.0 (never a mismatched comparison), not only the checks that happened to
        # already have their own guard.
        if not _snapshot_equity_basis_matches_context(snapshot.get("portfolio_value") or 0.0, equity):
            daily_pnl = 0.0
        positions = [
            Position(
                symbol=str(item["symbol"]).upper(),
                qty=float(item["quantity"]),
                market_value=float(item["entry_price"]) * float(item["quantity"]),
            )
            for item in open_managed_exits(self.settings.db_path, broker_name)
        ]
        return AccountContext(equity=equity, daily_realized_pnl=daily_pnl, open_positions=positions, is_paper=False)

    def daily_learning_update(self, learning_date: str | None = None) -> dict[str, Any]:
        if not learning_date:
            learning_date = (date.today() - timedelta(days=1)).isoformat()
        start = f"{learning_date}T00:00:00"
        end = f"{learning_date}T23:59:59"
        attribution = [
            dict(row)
            for row in self._rows(
                """
                SELECT * FROM PERFORMANCE_ATTRIBUTION
                WHERE created_at >= ? AND created_at <= ?
                ORDER BY attribution_id DESC
                """,
                (start, end),
            )
        ]
        decisions = [
            dict(row)
            for row in self._rows(
                """
                SELECT * FROM ORCHESTRATOR_DECISIONS
                WHERE created_at >= ? AND created_at <= ?
                ORDER BY decision_id DESC
                LIMIT 50
                """,
                (start, end),
            )
        ]
        snapshots = [
            dict(row)
            for row in self._rows(
                """
                SELECT broker, exchange, created_at, portfolio_value, day_pnl, week_pnl, month_pnl
                FROM PORTFOLIO_SNAPSHOTS
                WHERE created_at >= ? AND created_at <= ?
                ORDER BY created_at DESC
                """,
                (start, end),
            )
        ]
        benchmark = self.benchmark_daily_brief(learning_date)
        total_pnl = sum(safe_float(row.get("profit_loss")) or 0.0 for row in attribution)
        wins = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) > 0]
        losses = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
        rejected = [row for row in decisions if row.get("decision") == "rejected"]
        approved = [row for row in decisions if row.get("decision") == "approved"]
        trade_lessons = _trade_learning_lessons(attribution, rejected, snapshots)
        benchmark_lessons = _benchmark_learning_lessons(benchmark.get("items") or [])
        recommendations = _learning_recommendations(attribution, rejected, benchmark.get("items") or [])
        calibration = update_calibration_from_attribution(self.settings.db_path)
        return {
            "date": learning_date,
            "summary": (
                f"Reviewed {len(attribution)} closed trade outcome(s), {len(approved)} approved decision(s), "
                f"{len(rejected)} rejected decision(s), and {len(benchmark.get('items') or [])} benchmark learning note(s)."
            ),
            "trade_outcomes": {
                "closed_trades": len(attribution),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": (len(wins) / len(attribution)) if attribution else None,
                "total_profit_loss": round(total_pnl, 4),
                "largest_gain": max((safe_float(row.get("profit_loss")) or 0.0 for row in attribution), default=None),
                "largest_loss": min((safe_float(row.get("profit_loss")) or 0.0 for row in attribution), default=None),
            },
            "trade_lessons": trade_lessons,
            "benchmark_learning": benchmark_lessons,
            "confidence_calibration": calibration,
            "recommendations_for_founder": recommendations,
            "closed_trades": attribution,
            "recent_rejections": rejected[:10],
            "benchmark_items": benchmark.get("items") or [],
            "note": "Learning updates propose improvements only. They do not change strategy, guardrails, or execution logic automatically.",
        }

    def auto_execute_recommendations(self, broker_filter: str | None = None) -> dict[str, Any]:
        # Delegates to ExecutionService (Phase 8). Kept as a thin wrapper: the GET/POST
        # route dispatch table, ResearchService's injected auto_execute_recommendations_
        # lookup, and tests all call this externally.
        return self._execution_service.auto_execute_recommendations(broker_filter)

    def auto_execute_recommendations_alpaca(self) -> dict[str, Any]:
        # Delegates to ExecutionService (Phase 8). Kept as a thin wrapper: cli.py calls
        # this externally.
        return self._execution_service.auto_execute_recommendations_alpaca()

    def auto_execute_recommendations_kraken(self) -> dict[str, Any]:
        # Delegates to ExecutionService (Phase 8). Kept as a thin wrapper: cli.py calls
        # this externally.
        return self._execution_service.auto_execute_recommendations_kraken()

    def set_broker_auto_trading(self, body: dict[str, Any]) -> dict[str, Any]:
        # Delegates to AdministrationService (Phase 7, architecture/AI_TRADER_
        # MODULARISATION_ARCHITECTURE_2026-08-02.md; corrected from a Phase 6a scoping
        # mistake that put this mutating method in the presentation-only BrokerService).
        # Kept as a thin wrapper -- "delegation before deletion" -- so callers
        # (POST /broker-auto-trading, tests) needed no changes.
        return self._administration_service.set_broker_auto_trading(body)

    def monitor_managed_exits(self) -> dict[str, Any]:
        # Delegates to ExecutionService (Phase 8, architecture/AI_TRADER_MODULARISATION_
        # ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper -- run_server() passes
        # service.monitor_managed_exits as a bound-method reference to a scheduled
        # IntervalWorker, and tests call it directly -- both needed no changes.
        return self._execution_service.monitor_managed_exits()

    def force_managed_exit(self, body: dict[str, Any]) -> dict[str, Any]:
        # Delegates to ExecutionService (Phase 8). Kept as a thin wrapper -- "delegation
        # before deletion" -- so the GET/POST route dispatch table needed zero changes.
        return self._execution_service.force_managed_exit(body)

    def poll_broker_activity(self, broker_filter: str | None = None) -> dict[str, Any]:
        # Delegates to BrokerService (Phase 6a, architecture/AI_TRADER_MODULARISATION_
        # ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper -- run_server() passes
        # service.poll_broker_activity as a bound-method reference to a scheduled
        # IntervalWorker, and cli.py calls it directly -- both needed no changes.
        return self._broker_service.poll_broker_activity(broker_filter)

    def poll_broker_activity_alpaca(self) -> dict[str, Any]:
        return self._broker_service.poll_broker_activity_alpaca()

    def poll_broker_activity_kraken(self) -> dict[str, Any]:
        return self._broker_service.poll_broker_activity_kraken()

    def capture_production_broker_snapshots(self) -> dict[str, Any]:
        # Delegates to BrokerService (Phase 6a). Kept as a thin wrapper since cli.py
        # calls this externally (`capture_production_broker_snapshots()`).
        return self._broker_service.capture_production_broker_snapshots()

    def broker_panels(self, *, max_age_seconds: float | None = None) -> list[dict[str, Any]]:
        # Delegates to BrokerService (Phase 6a, architecture/AI_TRADER_MODULARISATION_
        # ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper -- get(), status(),
        # _ask_ai_context() all call this externally, and the GET/POST route dispatch
        # table needed zero changes.
        return self._broker_service.broker_panels(max_age_seconds=max_age_seconds)

    def _kraken_ai_capital_ledger(
        self,
        *,
        price_hints: dict[str, float] | None = None,
        allow_live_pricing: bool = True,
    ) -> dict[str, Any]:
        # Delegates to BrokerService (Phase 6a). Kept as a thin wrapper: tests/
        # test_multi_broker_platform.py calls this directly on the LocalApiService
        # instance.
        return self._broker_service._kraken_ai_capital_ledger(price_hints=price_hints, allow_live_pricing=allow_live_pricing)

    def _broker_managed_trade_capacity(self, broker: str) -> dict[str, Any]:
        # Delegates to BrokerService (Phase 6a). Kept as a thin wrapper: approve_and_execute
        # and auto_execute_recommendations (execution territory, Phase 8) call this
        # externally, and tests/test_multi_broker_platform.py calls it directly too.
        return self._broker_service._broker_managed_trade_capacity(broker)

    def _adapters(self):
        adapters = []
        if self.settings.has_alpaca_credentials:
            adapters.append(AlpacaBrokerAdapter(self._broker()))
        adapters.extend([InteractiveBrokersAdapter(), SaxoAdapter(), KrakenAdapter(), CoinbaseAdapter()])
        return adapters

    def _active_broker_names(self) -> list[str]:
        # Delegates to BrokerService (Phase 6a). Kept as a thin wrapper: status() calls
        # this externally.
        return self._broker_service._active_broker_names()

    def timing_diagnostics(self, target: str = "alpaca") -> dict[str, Any]:
        """Stage-by-stage wall clock for the expensive account paths.

        2026-08-24: /portfolio, /status and Ask were all dying at Render's 60s proxy,
        and from outside the box every guess about *which* stage was to blame cost a
        full redeploy to test. Alpaca's own API measured 0.3-0.6s directly, so the
        cost was somewhere in our own pipeline -- this says where, in one request.
        Runs to a budget and reports what it skipped rather than timing out itself.
        """
        broker_service = self._broker_service
        stages: list[dict[str, Any]] = []
        deadline = time.monotonic() + 40.0

        pool = ThreadPoolExecutor(max_workers=1)

        def stage(name: str, fn: Callable[[], Any]) -> Any:
            """Time one stage, bounded, so a stage slower than the whole request
            budget still reports a number instead of taking the diagnostic down with
            it -- which is exactly what the Alpaca path did on 2026-08-24."""
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stages.append({"stage": name, "seconds": None, "skipped": "time budget exhausted"})
                return None
            started = time.monotonic()
            future = pool.submit(fn)
            try:
                value = future.result(timeout=remaining)
            except FuturesTimeoutError:
                stages.append({"stage": name, "seconds": round(time.monotonic() - started, 2), "ok": False, "detail": f"still running after {remaining:.1f}s"})
                return None
            except Exception as exc:  # noqa: BLE001 - a failing stage is a result, not a crash
                stages.append({"stage": name, "seconds": round(time.monotonic() - started, 2), "ok": False, "detail": str(exc)[:200]})
                return None
            stages.append({
                "stage": name,
                "seconds": round(time.monotonic() - started, 2),
                "ok": True,
                "size": len(value) if isinstance(value, (list, dict)) else None,
            })
            return value

        target = (target or "alpaca").lower()
        if target == "alpaca":
            broker = stage("alpaca._broker_factory", broker_service._broker_factory)
            account = stage("alpaca.get_account", broker.get_account)
            positions = stage("alpaca.get_positions", broker.get_positions)
            orders = stage("alpaca.get_orders", lambda: broker.get_orders(status="all", limit=10))
            activities = stage("alpaca.get_activities", lambda: broker.get_activities("FILL"))
            stage(
                "alpaca.record_broker_trade_history",
                lambda: record_broker_trade_history(self.settings.db_path, "alpaca", list(orders or []) + list(activities or [])),
            )
            stage(
                "alpaca.record_portfolio_snapshot",
                lambda: record_portfolio_snapshot(
                    self.settings.db_path, broker="alpaca", exchange="Alpaca",
                    account=account or {}, positions=positions or [], notes="Timing diagnostic.",
                ),
            )
            stage("executive_summary", self.executive_summary)
        elif target == "kraken":
            # Step-for-step mirror of _exchange_portfolio("kraken"): batching the price
            # lookups only took it 51.66s -> 45.6s, so the bulk of the cost is one of
            # the calls below and guessing which has already been wrong once.
            adapter = broker_service.orchestrator.adapters.get("kraken")
            if adapter is None:
                return {"error": "No Kraken adapter configured."}
            account = stage("kraken.get_account", adapter.get_account)
            stage("kraken.get_positions", lambda: adapter.get_positions(account))
            orders = stage("kraken.get_orders", adapter.get_orders) or []
            history = stage("kraken.get_trade_history", adapter.get_trade_history) or []
            stage(
                "kraken.record_broker_trade_history",
                lambda: record_broker_trade_history(self.settings.db_path, "kraken", list(orders) + list(history)),
            )
            stage(
                "kraken.balance_summary(prices)",
                lambda: _kraken_balance_summary(account.get("balances") if isinstance(account, dict) else None, adapter),
            )
            stage("kraken._kraken_ai_capital_ledger", self._kraken_ai_capital_ledger)
        else:
            return {"error": f"Unknown target '{target}'. Use alpaca or kraken."}

        pool.shutdown(wait=False, cancel_futures=True)
        return {
            "target": target,
            "total_seconds": round(sum(row["seconds"] or 0.0 for row in stages), 2),
            "stages": stages,
            "note": "Wall-clock timings for one pass. Render's proxy kills any request at 60s.",
        }

    def executive_summary(self, panels: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        # Delegates to FounderExperienceService (Phase 4, architecture/AI_TRADER_
        # MODULARISATION_ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper --
        # "delegation before deletion" -- so callers needed zero changes.
        return self._founder_experience_service.executive_summary(panels)

    def founder_executive_summary(self, panels: list[dict[str, Any]], executive_summary: list[dict[str, Any]]) -> dict[str, Any]:
        return self._founder_experience_service.founder_executive_summary(panels, executive_summary)

    def connection_readiness(self, panels: list[dict[str, Any]]) -> dict[str, Any]:
        return self._founder_experience_service.connection_readiness(panels)

    def _exchange_portfolio(self, broker: str) -> dict[str, Any]:
        # Delegates to BrokerService (Phase 6a, architecture/AI_TRADER_MODULARISATION_
        # ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper: portfolio() calls this
        # externally, and tests/test_multi_broker_platform.py and
        # tests/test_production_completion.py call it directly too.
        return self._broker_service._exchange_portfolio(broker)

    def _live_alpaca_portfolio(self) -> dict[str, Any]:
        # Delegates to BrokerService (Phase 6a). Kept as a thin wrapper: portfolio()
        # calls this externally, and tests/test_multi_broker_platform.py and
        # tests/test_production_completion.py call it directly too.
        return self._broker_service._live_alpaca_portfolio()

    def _apply_env_broker_auto_defaults(self) -> None:
        if self.settings.auto_trade.enabled:
            set_broker_auto_trading(self.settings.db_path, "alpaca", True, updated_by="legacy_auto_paper_trading")
        for broker, enabled in self.settings.auto_trade.broker_enabled.items():
            if enabled:
                set_broker_auto_trading(self.settings.db_path, broker, True, updated_by="environment")

    def _apply_founder_kraken_live_authorization(self) -> None:
        """Applies the Founder's explicit authorization for autonomous Kraken execution.

        Only when KRAKEN_AUTO_TRADING is actually on: the orchestrator's production governance
        chain calls pre_execution_decision_packet() with mode="micro_live" for every non-Alpaca
        broker, but every strategy's registry entitlement is capped at paper/shadow/manual by
        design (see refresh_strategy_maturity's _MAX_AUTOMATIC_STAGE) - crossing into a real-money
        mode is never done automatically. Without this, KRAKEN_AUTO_TRADING=true alone would not
        submit any real order: every autonomous Kraken proposal would be rejected at Strategy
        Entitlement with "not permitted for micro_live execution", regardless of the enablement
        flags. This applies exactly one narrow, explicit authorization: crypto_trend_following_2r
        is the only strategy trading_intelligence.STRATEGIES itself already labels
        production_status="founder_controlled_live_kraken" (every other crypto-eligible strategy
        is explicitly "research_only" and is deliberately left untouched - a research-only
        strategy winning the scoring for a given proposal will still be correctly blocked from
        real-money execution). The size/count/allocation guardrails
        (KRAKEN_MAX_ORDER_GBP/KRAKEN_MAX_OPEN_TRADES/KRAKEN_TRADING_ALLOCATION_GBP/
        KRAKEN_ALLOWED_PAIRS) are enforced independently in broker_adapters.KrakenAdapter and are
        not affected by this.
        """
        if not self.settings.auto_trade.broker_enabled.get("kraken"):
            return
        apply_founder_strategy_authorization(
            self.settings.db_path,
            strategy_id="crypto_trend_following_2r",
            target_stage="Micro Live",
            additional_modes=["micro_live"],
            reason=(
                "Founder explicitly authorized autonomous Kraken execution (AT-ED-002 v2.0 "
                "implementation session), bounded by the existing KRAKEN_MAX_ORDER_GBP/"
                "KRAKEN_MAX_OPEN_TRADES/KRAKEN_TRADING_ALLOCATION_GBP/KRAKEN_ALLOWED_PAIRS "
                "guardrails, which this authorization does not change."
            ),
            authorized_by="founder_via_ai_trader_engineering_session",
        )

    def _continuous_research_status(self, brokers: list[dict[str, Any]]) -> dict[str, Any]:
        active = [broker for broker in brokers if broker.get("research_status") == "running"]
        latest = latest_recommendation_set(self.settings.db_path)
        return {
            "research_running": bool(active) or self.settings.research_scheduler_enabled,
            "current_broker": active[0]["broker"] if active else None,
            "current_asset": active[0].get("current_asset") if active else None,
            "current_stage": active[0].get("current_stage") if active else "waiting_for_next_scan",
            "research_queue": active[0].get("research_queue") if active else [],
            "assets_reviewed_today": sum(int(item.get("assets_reviewed_today") or 0) for item in brokers),
            "research_cycles_today": sum(int(item.get("research_cycles_today") or 0) for item in brokers),
            "last_scan": max([item.get("last_scan") for item in brokers if item.get("last_scan")] or [None]),
            "next_scan": next_research_run(interval_minutes=self.settings.research_scheduler_interval_minutes),
            "research_freshness": "Fresh" if self.settings.research_scheduler_enabled else "Idle - scheduler disabled",
            "last_recommendation": latest,
            "last_trade_submitted": max([item.get("last_trade_submitted") for item in brokers if item.get("last_trade_submitted")] or [None]),
        }

    def _latest_orchestrator_decision(self, recommendation_id: str) -> dict[str, Any] | None:
        row = self._row(
            "SELECT * FROM ORCHESTRATOR_DECISIONS WHERE recommendation_id = ? ORDER BY decision_id DESC LIMIT 1",
            (recommendation_id,),
        )
        return dict(row) if row else None

    def _latest_orchestrator_decisions_batch(self, recommendation_ids: list[str]) -> dict[str, dict[str, Any]]:
        # Batched form of _latest_orchestrator_decision(), used by recommendations() -- see
        # the comment above that call site for why batching these lookups matters.
        ids = [rid for rid in dict.fromkeys(recommendation_ids) if rid]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self._rows(
            f"SELECT * FROM ORCHESTRATOR_DECISIONS WHERE recommendation_id IN ({placeholders}) ORDER BY recommendation_id, decision_id DESC",
            tuple(ids),
        )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            rid = row["recommendation_id"]
            if rid not in result:
                result[rid] = dict(row)
        return result

    def _already_executed_batch(self, proposal_ids: list[str]) -> set[str]:
        # Batched form of _proposal_already_executed(), used by recommendations().
        ids = [pid for pid in dict.fromkeys(proposal_ids) if pid]
        if not ids:
            return set()
        placeholders = ",".join("?" for _ in ids)
        rows = self._rows(
            f"""
            SELECT DISTINCT proposal_id FROM trade_audit
            WHERE proposal_id IN ({placeholders}) AND event_type = 'execution_approved'
            """,
            tuple(ids),
        )
        return {row["proposal_id"] for row in rows}

    def _latest_daily_brief(self, brief_type: str) -> dict[str, Any] | None:
        row = self._row(
            "SELECT * FROM DAILY_BRIEFS WHERE brief_type = ? ORDER BY brief_id DESC LIMIT 1",
            (brief_type,),
        )
        return dict(row) if row else None

    def _broker(self) -> AlpacaPaperClient:
        return AlpacaPaperClient(
            AlpacaCredentials(
                api_key=self.settings.alpaca_api_key or "",
                secret_key=self.settings.alpaca_secret_key or "",
                base_url=self.settings.alpaca_paper_base_url,
                data_base_url=self.settings.alpaca_data_base_url,
            )
        )

    def _initialize_control(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.executescript(CONTROL_SCHEMA)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO engine_control (id, trading_state, updated_at, last_command)
                    VALUES (1, 'running', ?, 'api-start')
                    """,
                    (utc_now_iso(),),
                )

    def _initialize_report_schema(self) -> None:
        self._reporting_service.initialize_schema()

    def _control_state(self) -> dict[str, Any]:
        row = self._row("SELECT * FROM engine_control WHERE id = 1")
        return dict(row) if row else {"trading_state": "unknown", "updated_at": None, "last_command": None}

    def _proposal_already_executed(self, proposal_id: str) -> bool:
        # Delegates to ExecutionService (Phase 8, architecture/AI_TRADER_MODULARISATION_
        # ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper: recommendations() (still
        # un-extracted presentation code) calls this externally too.
        return self._execution_service._proposal_already_executed(proposal_id)

    def _proposal_broker(self, payload_json: Any) -> str | None:
        proposal_payload = _proposal_payload(payload_json)
        if not proposal_payload:
            return None
        try:
            proposal = TradeProposal.from_dict(proposal_payload)
        except Exception:
            return None
        selected = self.orchestrator._select_adapter(proposal)
        if selected:
            return selected.name
        if proposal.asset_type.lower() == "crypto" and proposal.exchange.upper() == "KRAKEN":
            return "kraken"
        if proposal.exchange.upper() in {"NYSE", "NASDAQ", "AMEX"}:
            return "alpaca"
        return None

    def broker_decisions(self, *, broker: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        # Delegates to BrokerService (Phase 6a, architecture/AI_TRADER_MODULARISATION_
        # ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper -- get() calls this
        # externally, and the GET/POST route dispatch table needed zero changes.
        return self._broker_service.broker_decisions(broker=broker, limit=limit)

    def order_intent_locks(self, *, broker: str | None = None, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return self._broker_service.order_intent_locks(broker=broker, status=status, limit=limit)

    def release_order_intent_lock_for(self, *, broker: str, client_order_id: str, confirmed_no_order_placed: bool) -> dict[str, Any]:
        # Delegates to AdministrationService (Phase 7; corrected from a Phase 6a scoping
        # mistake that put this guarded mutating action in the presentation-only
        # BrokerService).
        return self._administration_service.release_order_intent_lock_for(
            broker=broker, client_order_id=client_order_id, confirmed_no_order_placed=confirmed_no_order_placed
        )

    def _connect(self) -> sqlite3.Connection:
        # Delegates to QueryExecutor (Phase 2, architecture/AI_TRADER_MODULARISATION_
        # ARCHITECTURE_2026-08-02.md). Kept as a thin wrapper rather than rewriting all
        # 73 existing self._row/_rows/_scalar/_count/_connect call sites in this file --
        # "delegation before deletion" per the plan's Section 11 delivery controls.
        return self._query_executor.connect()

    def _row(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        return self._query_executor.row(sql, params)

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return self._query_executor.rows(sql, params)

    def _scalar(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        return self._query_executor.scalar(sql, params)

    def _count(self, table: str, where: str | None = None) -> int:
        return self._query_executor.count(table, where)

    def _due_diligence_status(self) -> str:
        latest = self._row("SELECT overall_status, created_at FROM DUE_DILIGENCE_ASSESSMENTS ORDER BY assessment_id DESC LIMIT 1")
        if not latest:
            return "idle - no due diligence assessment recorded yet"
        return f"{latest['overall_status']} at {latest['created_at']}"


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def run_server(host: str = "127.0.0.1", port: int = 8765, api_token: str | None = None) -> None:
    settings = load_settings()
    configure_logging(settings.output_dir)
    startup_errors = settings.production_startup_errors(host=host)
    if startup_errors:
        for message in startup_errors:
            logger.error("Hosted startup validation failed: %s", message)
        raise RuntimeError("; ".join(startup_errors))
    hosted_read_only = False
    if not api_token and host not in _LOOPBACK_HOSTS:
        hosted_read_only = True
        logger.warning(
            "Starting hosted API on %s without AI_TRADER_API_TOKEN in read-only mode. "
            "All POST trading/control commands will be rejected until the token is configured.",
            host,
        )
    # Bind before database-backed initialization. Render detects readiness by
    # scanning for an open port, so schema work must never prevent the web
    # process from proving that it started.
    server = ThreadingHTTPServer((host, port), ApiHandler)
    logger.info("AI Trader API socket bound on http://%s:%s; initializing runtime.", host, port)

    # The production worker owns schema/bootstrap writes. Repeating every migration,
    # seed and reconciliation operation before binding the HTTP socket made a sleeping
    # Render API take minutes to wake. Local and combined-process deployments retain
    # the self-initializing behavior.
    worker_owns_runtime = settings.is_hosted_runtime and settings.disable_api_background_workers
    service = LocalApiService(settings, initialize_runtime=not worker_owns_runtime)
    service.hosted_read_only = hosted_read_only
    service.api_token_configured = bool(api_token)
    if not worker_owns_runtime:
        service.intelligence.seed_initial_data()
        service.benchmark.seed_initial_data()
        seed_crypto_universe(service.settings.db_path, fetch_live=False)
        service.benchmark.write_schema_doc(Path("governance/BENCHMARK_INTELLIGENCE_SCHEMA.md"))
        service.benchmark.write_initial_brief(service.settings.output_dir)
        service.reconcile_on_startup()
    else:
        logger.info(
            "Hosted API startup skipped schema/bootstrap writes; the production worker owns durable initialization."
        )

    def _on_research_error(exc: Exception) -> None:
        record_notification(
            service.settings.db_path,
            event_type="research_failure",
            broker=None,
            symbol=None,
            title="Research cycle failed",
            message=f"A scheduled research cycle raised an exception and was skipped: {exc}",
            payload={"error": str(exc)},
        )

    def _on_exit_monitor_error(exc: Exception) -> None:
        record_notification(
            service.settings.db_path,
            event_type="broker_failure",
            broker=None,
            symbol=None,
            title="Position monitoring cycle failed",
            message=f"A managed-exit monitoring cycle raised an exception and was skipped: {exc}",
            payload={"error": str(exc)},
        )

    def _on_activity_poll_error(exc: Exception) -> None:
        record_notification(
            service.settings.db_path,
            event_type="broker_failure",
            broker=None,
            symbol=None,
            title="Order/trade activity poll failed",
            message=f"A broker order/trade activity poll raised an exception and was skipped: {exc}",
            payload={"error": str(exc)},
        )

    def _on_auto_execution_error(exc: Exception) -> None:
        record_notification(
            service.settings.db_path,
            event_type="broker_failure",
            broker=None,
            symbol=None,
            title="Auto execution cycle failed",
            message=f"An autonomous execution cycle raised an exception and was skipped: {exc}",
            payload={"error": str(exc)},
        )

    def _on_crypto_refresh_error(exc: Exception) -> None:
        record_notification(
            service.settings.db_path,
            event_type="research_failure",
            broker="kraken",
            symbol=None,
            title="Crypto universe refresh failed",
            message=f"A crypto knowledge engine refresh raised an exception and was skipped: {exc}",
            payload={"error": str(exc)},
        )

    if service.settings.disable_api_background_workers:
        # This is the branch that actually runs in hosted production --
        # AI_TRADER_DISABLE_API_BACKGROUND_WORKERS=true on every Render service
        # (render.yaml). Everything in the `else` below, including the push-dispatch
        # IntervalWorker, is dead code there; the always-on worker's own job loop
        # (cli.py run-worker) is what must own autonomous operations, including push
        # dispatch (see the "push-dispatch" job, CRITICAL_REMEDIATION_PLAN.md P0-5).
        # The `else` branch below only executes for a local/dev API process run with
        # this flag unset.
        logger.info(
            "API background workers are disabled by AI_TRADER_DISABLE_API_BACKGROUND_WORKERS; "
            "Render worker/cron services own autonomous operations."
        )
    else:
        if service.settings.research_scheduler_enabled:
            ResearchScheduler(
                service,
                interval_minutes=service.settings.research_scheduler_interval_minutes,
                on_error=_on_research_error,
            ).start_background(limit=service.settings.research_scheduler_limit)
        else:
            logger.warning("RESEARCH_SCHEDULER_ENABLED is false - continuous research will not run automatically.")

        # Position/exit monitoring is a safety function, independent of whether research is
        # scheduled, and always runs so stop-loss/take-profit protection is never dependent on
        # a manual call to /monitor-managed-exits.
        IntervalWorker(
            service.monitor_managed_exits,
            interval_seconds=60,
            name="ai-trader-exit-monitor",
            on_error=_on_exit_monitor_error,
        ).start_background()

        IntervalWorker(
            service.poll_broker_activity,
            interval_seconds=60,
            name="ai-trader-order-monitor",
            on_error=_on_activity_poll_error,
        ).start_background()

        # Auto execution is intentionally separate from research. Research creates fresh
        # proposals; this worker repeatedly asks the deterministic execution engine whether
        # any proposal is currently eligible under broker permissions and guardrails.
        IntervalWorker(
            service.auto_execute_recommendations,
            interval_seconds=max(30, service.settings.auto_execution_interval_seconds),
            name="ai-trader-auto-executor",
            on_error=_on_auto_execution_error,
        ).start_background()

        # Crypto knowledge engine refresh - independent of research_scheduler_enabled since it's
        # foundational data (market cap / AI / privacy category universes and scoring), not a
        # decision-making cycle. Runs on the same cadence as equities research by default.
        IntervalWorker(
            service.refresh_crypto_universe,
            interval_seconds=max(300, service.settings.research_scheduler_interval_minutes * 60),
            name="ai-trader-crypto-refresh",
            on_error=_on_crypto_refresh_error,
        ).start_background()

        # Push dispatch runs on a short cadence since it's just an outbound HTTP call for
        # already-recorded high-priority notifications, not a broker/API poll.
        IntervalWorker(
            service.dispatch_pending_push_notifications,
            interval_seconds=30,
            name="ai-trader-push-dispatch",
        ).start_background()

    ApiHandler.service = service
    ApiHandler.api_token = api_token
    ApiHandler.hosted_read_only = hosted_read_only
    logger.info("AI Trader API runtime initialized; accepting requests on http://%s:%s", host, port)
    server.serve_forever()


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values else None


def _float_or_none(value: Any) -> float | None:
    return safe_float(value)


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _list_or_none(items: list[str]) -> str:
    if not items:
        return "- None recorded"
    return "\n".join(item if str(item).startswith("- ") else f"- {item}" for item in items)


def _money_text(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "Not available"
    return f"{number:,.2f}"


def _estimated_in_positions(portfolio_value: Any, cash: Any) -> float | None:
    portfolio_number = safe_float(portfolio_value)
    cash_number = safe_float(cash)
    if portfolio_number is None or cash_number is None:
        return None
    return portfolio_number - cash_number


def _human_time(value: Any) -> str:
    if not value:
        return "Not available"
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%d %b %Y, %H:%M UTC")


def _deterministic_ai_trader_answer(question: str, context: dict[str, Any]) -> str:
    snapshots = context.get("latest_portfolio_snapshots") or []
    trades = context.get("latest_broker_trades") or []
    attribution = context.get("latest_closed_trade_attribution") or []
    learning = context.get("daily_learning") or {}
    lines = [
        "I can answer from stored AI Trader evidence, but I am read-only and cannot place or approve trades.",
    ]
    if snapshots:
        latest = snapshots[0]
        invested = _estimated_in_positions(latest.get("portfolio_value"), latest.get("cash"))
        lines.append(
            f"Latest {latest.get('broker', 'broker')} snapshot: account {_money_text(latest.get('portfolio_value'))}, "
            f"cash {_money_text(latest.get('cash'))}, estimated in positions {_money_text(invested)}, "
            f"open positions {latest.get('open_positions_count') or 'not available'}."
        )
        day_pnl = safe_float(latest.get("day_pnl"))
        if day_pnl is not None:
            moved = "up" if day_pnl > 0 else "down" if day_pnl < 0 else "flat"
            lines.append(f"Latest day P&L evidence says the account is {moved} by {_money_text(day_pnl)}.")
    else:
        lines.append("No portfolio snapshots are stored yet, so I cannot prove current performance.")
    if attribution:
        total = sum(safe_float(row.get("profit_loss")) or 0.0 for row in attribution)
        winners = sum(1 for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) > 0)
        losers = sum(1 for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0)
        lines.append(f"Closed-trade attribution shows {_money_text(total)} across {len(attribution)} recent closed trade(s): {winners} winner(s), {losers} loser(s).")
    elif trades:
        latest_trade = trades[0]
        lines.append(
            f"I can see broker activity, but no recent closed-trade attribution. Latest broker row: "
            f"{latest_trade.get('side') or 'activity'} {latest_trade.get('symbol') or 'unknown'} "
            f"for {latest_trade.get('quantity') or 'unknown'} at {_money_text(latest_trade.get('price'))}."
        )
    else:
        lines.append("No recent broker trades are stored in the evidence bundle.")
    if learning.get("summary"):
        lines.append(f"Learning summary: {learning.get('summary')}")
    if "kraken" in question.lower() and "trade" in question.lower():
        lines.extend(_kraken_trade_status_lines(context))
    if context.get("openai_configured"):
        lines.append("OpenAI is configured, but this response used the local evidence summary because the OpenAI explanation was unavailable or timed out.")
    else:
        lines.append("For a fuller answer, configure OPENAI_API_KEY on the AI Trader deployment so the Ask screen can explain this evidence conversationally.")
    return "\n\n".join(lines)


def _kraken_trade_status_lines(context: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    panels = context.get("broker_panels") or []
    kraken = next((item for item in panels if str(item.get("broker") or "").lower() == "kraken"), None)
    if kraken:
        permissions = kraken.get("trading_permissions") or {}
        lines.append(
            "Kraken trading status: "
            f"auto trading {'enabled' if permissions.get('auto_trading_enabled') else 'disabled'}, "
            f"broker trading {'enabled' if permissions.get('trading_enabled') else 'disabled'}, "
            f"live approval {'yes' if permissions.get('live_trading_approved') else 'no'}, "
            f"real-order submission {'yes' if permissions.get('submit_real_orders') else 'no'}, "
            f"can submit real orders now {'yes' if permissions.get('can_submit_real_orders') else 'no'}."
        )
        lines.append(
            f"Kraken seatbelts: allocation {_money_text(permissions.get('trading_allocation_gbp'))}, "
            f"max order {_money_text(permissions.get('max_order_gbp'))}, "
            f"max open trades {permissions.get('max_open_trades')}, "
            f"allowed pairs {', '.join(permissions.get('allowed_pairs') or []) or 'not listed'}."
        )
    recommendations = [
        item for item in (context.get("latest_recommendations") or [])
        if str(item.get("broker") or item.get("suggested_broker") or "").lower() == "kraken"
        or str(item.get("asset_type") or "").lower() == "crypto"
    ]
    active = [item for item in recommendations if str(item.get("freshness_status") or "").lower() != "expired"]
    eligible = [item for item in active if item.get("auto_trade_eligible")]
    if eligible:
        symbols = ", ".join(str(item.get("symbol") or "unknown") for item in eligible[:5])
        lines.append(f"I can see {len(eligible)} active crypto/Kraken recommendation(s) marked auto-trade eligible: {symbols}.")
    elif active:
        reasons = Counter(str(item.get("auto_trade_reason") or item.get("status") or "not eligible") for item in active)
        lines.append(f"I can see active crypto/Kraken recommendations, but none are marked auto-trade eligible yet. Reasons seen: {dict(reasons)}.")
    else:
        lines.append("I cannot see an active fresh Kraken recommendation in the latest evidence. Auto trading will wait until research produces one that passes confidence, freshness, and guardrails.")
    lines.append("So zero Kraken trades today can be normal if no fresh eligible recommendation has passed the orchestrator yet, even though Kraken auto trading is enabled.")
    return lines


def _recommendation_freshness(created_at: str | None, confidence: Any, broker: str | None = None) -> dict[str, Any]:
    if not created_at:
        return {"status": "Not available", "expires_at": None, "note": "Generated time is not available."}
    generated_at = _parse_datetime(created_at)
    if generated_at is None:
        return {"status": "Not available", "expires_at": None, "note": "Generated time could not be parsed."}
    confidence_value = safe_score(confidence) or 0
    if confidence_value >= 0.85:
        lifetime = timedelta(hours=4)
    elif confidence_value >= 0.75:
        lifetime = timedelta(hours=12)
    else:
        lifetime = timedelta(hours=24)
    now = datetime.now(timezone.utc)
    # 2026-08-22: equities age only while their market is OPEN. Wall-clock ageing meant a
    # high-confidence idea (4h life -- the shortest, and the only band auto-trade accepts at
    # min_confidence 0.85) generated late in a session or overnight was expired before the
    # next open and could never be acted on. Confirmed live: all 40 equity recommendations
    # read "Expired", with no Alpaca fill since 12 Aug. Crypto is unchanged: it trades
    # continuously, so wall clock already IS its market time.
    ages_only_when_market_open = str(broker or "").strip().lower() not in {"", "kraken"}
    if ages_only_when_market_open:
        elapsed = us_equity_market_hours_between(generated_at, now)
        expires_at = generated_at + lifetime
    else:
        elapsed = now - generated_at
        expires_at = generated_at + lifetime
    if elapsed > lifetime:
        status = "Expired"
    elif elapsed > (lifetime / 2):
        status = "Stale"
    else:
        status = "Fresh"
    return {
        "status": status,
        "expires_at": expires_at.isoformat(),
        "note": f"{status}. Trade idea lifetime is {int(lifetime.total_seconds() / 3600)} hours.",
    }


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _auto_trade_reason(
    *,
    confidence: float,
    philosophy_fit: float,
    auto_enabled: bool,
    auto_label: str,
    min_confidence: float,
    min_philosophy_fit: float,
    freshness_status: str,
    guardrails_passed: bool,
    already_executed: bool,
    guardrail_failures: list[str] | None = None,
    has_dossier_arguments: bool = True,
) -> str:
    if not auto_enabled:
        return f"{auto_label} is disabled; manual approval is required."
    if already_executed:
        return "Already executed."
    if freshness_status == "Expired":
        return "Expired. Run new analysis before execution."
    if confidence < min_confidence:
        return f"Confidence is below {int(min_confidence * 100)}%."
    if philosophy_fit < min_philosophy_fit:
        return f"Investment philosophy fit is below {int(min_philosophy_fit * 100)}%."
    if not guardrails_passed:
        if guardrail_failures:
            return f"Execution guardrails failed: {_format_guardrail_failures(guardrail_failures)}."
        return "Execution guardrails did not pass, so auto-trade is blocked."
    if not has_dossier_arguments:
        return "Not actionable yet: AI Trader cannot state both the strongest argument for and against the trade."
    return "Eligible for broker auto-trade."


def _why_no_action_may_be_better(
    committee: dict[str, Any],
    probability: dict[str, Any],
    guardrail_failures: list[str],
    freshness_status: str,
) -> str:
    if freshness_status == "Expired":
        return "Waiting may be better because the evidence is stale and market conditions may have changed."
    if guardrail_failures:
        return "Taking no action is better while guardrails are failing."
    calibration = str(probability.get("calibration_status") or "").lower()
    if "insufficient" in calibration or "weak" in calibration:
        return "Waiting may be better because AI Trader does not yet have enough similar outcomes to trust this confidence level."
    opposing = committee.get("strongest_argument_against")
    if opposing:
        return f"Waiting may be better if this concern matters more than the thesis: {opposing}"
    return "Doing nothing remains acceptable if evidence quality, portfolio fit, or market conditions are not strong enough."


def _proposal_payload(payload_json: Any) -> dict[str, Any]:
    if not payload_json:
        return {}
    try:
        data = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    proposal = data.get("proposal") if isinstance(data, dict) else None
    return proposal if isinstance(proposal, dict) else {}


def _proposal_exchange(payload_json: Any) -> str:
    return str(_proposal_payload(payload_json).get("exchange") or "NYSE")


def _proposal_asset_type(payload_json: Any) -> str:
    return str(_proposal_payload(payload_json).get("asset_type") or "stock")


def _proposal_philosophy_fit(payload_json: Any) -> float:
    value = _proposal_payload(payload_json).get("philosophy_fit")
    return safe_score(value) or 0.0


def _score_payload(score: dict[str, Any] | None, confidence: float, philosophy_fit: float) -> dict[str, Any]:
    if score:
        return {
            "fundamental_score": score.get("fundamental_score"),
            "technical_score": score.get("technical_score"),
            "market_score": score.get("market_score"),
            "macro_score": score.get("macro_score"),
            "behavioural_score": score.get("behavioural_score"),
            "investment_policy_score": score.get("investment_policy_score"),
            "risk_score": score.get("risk_score"),
            "overall_confidence": score.get("overall_confidence"),
            "reasoning": score.get("reasoning"),
        }
    return {
        "fundamental_score": confidence or None,
        "technical_score": confidence or None,
        "market_score": confidence or None,
        "macro_score": None,
        "behavioural_score": None,
        "investment_policy_score": philosophy_fit or None,
        "risk_score": None,
        "overall_confidence": confidence or None,
        "reasoning": {"status": "Not available - not assessed by orchestrator yet"},
    }


def _payload_intelligence(payload_json: Any) -> dict[str, Any] | None:
    if not payload_json:
        return None
    try:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    intelligence = payload.get("intelligence")
    return intelligence if isinstance(intelligence, dict) else None


def _payload_strategy(payload_json: Any, intelligence: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if intelligence and isinstance(intelligence.get("strategy"), dict):
        return intelligence["strategy"]
    fallback = _payload_intelligence(payload_json)
    if fallback and isinstance(fallback.get("strategy"), dict):
        return fallback["strategy"]
    return None


def _payload_regime(payload_json: Any, intelligence: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if intelligence and isinstance(intelligence.get("regime"), dict):
        return intelligence["regime"]
    fallback = _payload_intelligence(payload_json)
    if fallback and isinstance(fallback.get("regime"), dict):
        return fallback["regime"]
    return None


def _broker_label(broker: str) -> str:
    labels = {
        "alpaca": "Alpaca",
        "kraken": "Kraken",
        "coinbase": "Coinbase",
        "binance": "Binance",
        "interactive_brokers": "Interactive Brokers",
    }
    return labels.get(broker.lower(), broker.replace("_", " ").title())


def _sum_balances(balances: Any) -> float | None:
    if not isinstance(balances, dict):
        return None
    total = 0.0
    found = False
    for value in balances.values():
        amount = safe_float(value)
        if amount is None:
            continue
        total += amount
        found = True
    return total if found else None


def _kraken_trading_allocation_gbp(balances: Any) -> float:
    allocation = _float_env("KRAKEN_TRADING_ALLOCATION_GBP", 100.0)
    summary_cash = _kraken_gbp_cash(balances)
    if summary_cash is None:
        return allocation
    return max(0.0, min(allocation, summary_cash))


def _kraken_balance_summary(balances: Any, adapter: Any) -> dict[str, Any]:
    raw = balances if isinstance(balances, dict) else {}
    book = _KrakenPriceBook(adapter)
    book.prefetch(_kraken_candidate_pairs([
        _kraken_asset_symbol(asset)
        for asset, value in raw.items()
        if (safe_float(value) or 0) != 0 and _kraken_asset_symbol(asset) != "GBP"
    ]))
    gbp_cash = _kraken_gbp_cash(raw)
    total = gbp_cash or 0.0
    raw_balance_rows: list[dict[str, Any]] = []
    converted_assets: list[dict[str, Any]] = []
    unpriced_assets: list[dict[str, Any]] = []
    for asset, value in raw.items():
        qty = safe_float(value)
        if qty is None or qty == 0:
            continue
        normalized = _kraken_asset_symbol(asset)
        raw_balance_rows.append({"asset": asset, "normalized_asset": normalized, "quantity": qty})
        if normalized == "GBP":
            continue
        price_result = _kraken_asset_gbp_price(adapter, normalized, book)
        price = price_result.get("price_gbp")
        if price is None:
            unpriced_assets.append({
                "asset": asset,
                "normalized_asset": normalized,
                "quantity": qty,
                "reason": price_result.get("reason") or "gbp_price_unavailable",
                "pairs_tried": price_result.get("pairs_tried") or [],
            })
            continue
        value_gbp = qty * price
        total += value_gbp
        converted_assets.append({
            "asset": asset,
            "normalized_asset": normalized,
            "quantity": qty,
            "pair": price_result.get("pair"),
            "pricing_route": price_result.get("pricing_route"),
            "price_gbp": price,
            "value_gbp": value_gbp,
        })
    trading_allocation = _kraken_trading_allocation_gbp(raw)
    return {
        "total_estimated_gbp": round(total, 2),
        "gbp_cash": round(gbp_cash, 2) if gbp_cash is not None else None,
        "trading_allocation_gbp": round(trading_allocation, 2),
        "raw_balances": raw,
        "raw_balance_rows": raw_balance_rows,
        "converted_assets": converted_assets,
        "unpriced_assets": unpriced_assets,
        "valuation_note": (
            "Portfolio value is GBP cash plus supported crypto balances converted to GBP using Kraken ticker prices. "
            "Fiat/stablecoin balances and assets without a GBP price are shown below but excluded from the estimated total. "
            "Kraken Pro may also show assets outside this API balance view, such as earn/staked/funding balances. "
            "Trading allocation is capped separately by KRAKEN_TRADING_ALLOCATION_GBP."
        ),
    }


def _kraken_gbp_cash(balances: Any) -> float | None:
    if not isinstance(balances, dict):
        return None
    total = 0.0
    found = False
    for key in ("GBP", "ZGBP"):
        amount = safe_float(balances.get(key))
        if amount is not None:
            total += amount
            found = True
    return total if found else None


def _kraken_asset_gbp_price(adapter: Any, normalized: str, book: "_KrakenPriceBook | None" = None) -> dict[str, Any]:
    book = book if book is not None else _KrakenPriceBook(adapter)
    normalized = str(normalized or "").upper()
    if normalized == "GBP":
        return {"price_gbp": 1.0, "pair": "GBP", "pricing_route": "cash"}
    pairs_tried: list[str] = []
    direct_pair = _kraken_pair(normalized, "GBP")
    direct = book.price(direct_pair)
    pairs_tried.append(direct_pair)
    if direct is not None:
        return {"price_gbp": direct, "pair": direct_pair, "pricing_route": "direct_gbp", "pairs_tried": pairs_tried}
    if normalized in {"USD", "USDT", "USDC"}:
        usd_to_gbp = _kraken_usd_to_gbp(adapter, pairs_tried, book)
        if usd_to_gbp is not None:
            return {"price_gbp": usd_to_gbp, "pair": "USDGBP", "pricing_route": "usd_to_gbp", "pairs_tried": pairs_tried}
    if normalized == "EUR":
        eur_pair = _kraken_pair("EUR", "GBP")
        eur_to_gbp = book.price(eur_pair)
        pairs_tried.append(eur_pair)
        if eur_to_gbp is not None:
            return {"price_gbp": eur_to_gbp, "pair": eur_pair, "pricing_route": "eur_to_gbp", "pairs_tried": pairs_tried}
    for quote in ["USD", "USDT", "USDC"]:
        asset_pair = _kraken_pair(normalized, quote)
        asset_to_quote = book.price(asset_pair)
        pairs_tried.append(asset_pair)
        if asset_to_quote is None:
            continue
        quote_to_gbp = _kraken_usd_to_gbp(adapter, pairs_tried, book)
        if quote_to_gbp is None:
            continue
        return {
            "price_gbp": asset_to_quote * quote_to_gbp,
            "pair": asset_pair,
            "pricing_route": f"{quote.lower()}_bridge_to_gbp",
            "pairs_tried": pairs_tried,
        }
    return {"price_gbp": None, "reason": "no_direct_or_bridge_gbp_price", "pairs_tried": pairs_tried}


def _kraken_usd_to_gbp(adapter: Any, pairs_tried: list[str], book: "_KrakenPriceBook | None" = None) -> float | None:
    book = book if book is not None else _KrakenPriceBook(adapter)
    for pair in ["USDGBP", "USDTGBP", "USDCGBP"]:
        price = book.price(pair)
        pairs_tried.append(pair)
        if price is not None:
            return price
    inverse = book.price("GBPUSD")
    pairs_tried.append("GBPUSD")
    if inverse:
        return 1 / inverse
    return None


class _KrakenPriceBook:
    """One batched Kraken Ticker call for a whole wallet valuation, memoized.

    2026-08-24: measured at 51.66s for a single _exchange_portfolio("kraken") in
    production, which put /portfolio, /brokers, /status and Ask AI Trader over
    Render's hard 60s proxy limit. The cause was request count, not Kraken being
    slow: pricing ran one asset at a time, and an asset with no direct GBP pair
    cost up to seven sequential calls (three bridge quotes, each re-fetching the
    USD->GBP rate that every other asset had already looked up).

    adapter.current_prices() has always taken a *list* of pairs and comma-joined
    them into a single /0/public/Ticker request -- it was simply never called with
    more than one. This asks for every candidate pair at once, then answers from
    that result. Fewer requests is also gentler on Kraken's rate limits than
    firing the same lookups concurrently would have been, which matters on a live
    account that has been rate-locked before.

    Correctness is unchanged: a pair the batch didn't return still falls back to
    its own live lookup, so pricing routes resolve exactly as they did before.
    """

    def __init__(self, adapter: Any):
        self._adapter = adapter
        self._prices: dict[str, float | None] = {}

    def _canonical_keys(self, wanted: list[str]) -> dict[str, str]:
        """Requested name -> the key Kraken returns it under, dropping unlisted pairs.

        Verified against the live API: XBTGBP comes back as XXBTZGBP, and USDGBP is
        not a pair at all -- one unlisted name fails the whole batch.
        """
        lookup = getattr(self._adapter, "known_pair_map", None)
        known = lookup() if callable(lookup) else None
        if not known:
            # No pair map (fake adapters in tests, or the lookup failed): ask for the
            # names as given and read them back as given.
            return {pair: pair for pair in wanted}
        return {pair: known[pair.upper()] for pair in wanted if pair.upper() in known}

    def prefetch(self, pairs: list[str]) -> None:
        wanted = [pair for pair in dict.fromkeys(pairs) if pair and pair not in self._prices]
        if not wanted:
            return
        keys = self._canonical_keys(wanted)
        # A pair the map doesn't list has been asked about and answered: it does not
        # exist. Recording that stops price() spending a live call to rediscover it.
        for pair in wanted:
            if pair not in keys:
                self._prices[pair] = None
        if not keys:
            return
        try:
            result = self._adapter.current_prices(list(keys.values()))
        except Exception:
            # Belt and braces: the pair map should have removed anything unlisted, but
            # a batch can still be rejected (a pair delisted since the map was cached).
            # Halve and retry so one bad name costs its own branch, not the whole
            # wallet -- price() still resolves anything left unpriced.
            if len(wanted) > 1:
                middle = len(wanted) // 2
                self.prefetch(wanted[:middle])
                self.prefetch(wanted[middle:])
            return
        if not isinstance(result, dict):
            return
        for pair, key in keys.items():
            payload = result.get(key)
            price = _kraken_last_price({key: payload}, key) if isinstance(payload, dict) else None
            # None is recorded too: the batch asked and Kraken did not price it, so a
            # follow-up single call would only buy the same answer more slowly.
            self._prices[pair] = price

    def price(self, pair: str) -> float | None:
        if pair in self._prices:
            return self._prices[pair]
        try:
            price = _kraken_last_price(self._adapter.current_prices([pair]), pair)
        except Exception:
            price = None
        self._prices[pair] = price
        return price


def _kraken_candidate_pairs(assets: list[str]) -> list[str]:
    """Every pair the GBP-pricing routes below might ask for, for a whole wallet."""
    pairs: list[str] = ["USDGBP", "USDTGBP", "USDCGBP", "GBPUSD", _kraken_pair("EUR", "GBP")]
    for asset in assets:
        pairs.append(_kraken_pair(asset, "GBP"))
        for quote in ("USD", "USDT", "USDC"):
            pairs.append(_kraken_pair(asset, quote))
    return [pair for pair in dict.fromkeys(pairs) if pair]


def _kraken_pair_price(adapter: Any, pair: str) -> float | None:
    try:
        return _kraken_last_price(adapter.current_prices([pair]), pair)
    except Exception:
        return None


def _kraken_asset_symbol(asset: str) -> str:
    normalized = str(asset or "").upper()
    aliases = {
        "XXBT": "BTC",
        "XBT": "BTC",
        "XETH": "ETH",
        "ZGBP": "GBP",
        "ZUSD": "USD",
        "ZEUR": "EUR",
    }
    if normalized in aliases:
        return aliases[normalized]
    if normalized.startswith("X") and len(normalized) > 3:
        return normalized[1:]
    if normalized.startswith("Z") and len(normalized) > 3:
        return normalized[1:]
    return normalized


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _trade_learning_lessons(attribution: list[dict[str, Any]], rejected: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> list[str]:
    lessons: list[str] = []
    if attribution:
        wins = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) > 0]
        losses = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
        if wins:
            lessons.append(f"{len(wins)} closed trade(s) were profitable; compare their entry reasons against future recommendations before increasing size.")
        if losses:
            exit_reasons = Counter(str(row.get("exit_reason") or "unknown") for row in losses)
            lessons.append(f"{len(losses)} closed trade(s) lost money; loss reasons observed: {dict(exit_reasons)}.")
    else:
        lessons.append("No closed trade outcomes were recorded for this date, so technique learning is limited to decisions, rejections, portfolio movement, and benchmark observations.")
    if rejected:
        reasons = Counter(str(row.get("rejection_reason") or "unknown") for row in rejected)
        lessons.append(f"Guardrail/orchestrator rejections clustered around: {dict(reasons)}.")
    if snapshots:
        latest_by_broker: dict[str, dict[str, Any]] = {}
        for row in snapshots:
            latest_by_broker.setdefault(str(row.get("broker") or "unknown"), row)
        for broker, row in latest_by_broker.items():
            day_pnl = safe_float(row.get("day_pnl"))
            week_pnl = safe_float(row.get("week_pnl"))
            if day_pnl is not None or week_pnl is not None:
                lessons.append(f"{broker.title()} snapshot showed day P&L {day_pnl if day_pnl is not None else 'N/A'} and week P&L {week_pnl if week_pnl is not None else 'N/A'}.")
    return lessons


def _benchmark_learning_lessons(items: list[dict[str, Any]]) -> list[str]:
    lessons = []
    for item in items[:6]:
        trader = item.get("trader_name") or "Benchmark trader"
        interpretation = item.get("ai_interpretation")
        risk = item.get("risk_lesson")
        market = item.get("market_lesson")
        summary = "; ".join(part for part in [interpretation, risk, market] if part)
        if summary:
            lessons.append(f"{trader}: {summary}")
    if not lessons:
        lessons.append("No benchmark trader learning rows were available for this date.")
    return lessons


def _learning_recommendations(attribution: list[dict[str, Any]], rejected: list[dict[str, Any]], benchmark_items: list[dict[str, Any]]) -> list[str]:
    recommendations = [
        "Do not change strategy or guardrails automatically; Founder approval is required.",
    ]
    if rejected:
        recommendations.append("Review repeated rejection reasons before lowering confidence, risk, or freshness thresholds.")
    losses = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
    if losses:
        recommendations.append("Compare losing trades against stop distance, trend score, and entry timing before allowing larger position sizes.")
    if benchmark_items:
        recommendations.append("Use benchmark trader observations as discipline checks, not as automatic copy-trade signals.")
    return recommendations






def _validation_failures(validation_result: Any) -> list[str]:
    data = _validation_payload(validation_result)
    if not data:
        return []
    failures = data.get("failures") or []
    return [str(item) for item in failures]


def _validation_payload(validation_result: Any) -> dict[str, Any] | None:
    if not validation_result:
        return None
    try:
        data = json.loads(validation_result)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _guardrail_checks(validation_result: Any, payload_json: Any = None) -> list[dict[str, str]]:
    data = _validation_payload(validation_result)
    if not data:
        return []
    side = _proposal_side(payload_json)
    failures = set(_validation_failures(validation_result))
    known = {key for key, _, _ in GUARDRAIL_CHECKS}
    checks = [
        {
            "key": key,
            "label": label,
            "status": "failed" if key in failures else "passed",
        }
        for key, label, applies_to in GUARDRAIL_CHECKS
        if applies_to == "all" or applies_to == side or key in failures
    ]
    checks.extend(
        {
            "key": key,
            "label": key.replace("_", " "),
            "status": "failed",
        }
        for key in sorted(failures - known)
    )
    return checks


def _json_loads_safe(payload_json: Any) -> dict[str, Any] | None:
    if not payload_json:
        return None
    try:
        data = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _proposal_side(payload_json: Any) -> str | None:
    if not payload_json:
        return None
    try:
        data = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    proposal = data.get("proposal")
    if not isinstance(proposal, dict):
        return None
    side = proposal.get("side")
    return str(side).lower() if side else None


def _format_guardrail_failures(failures: list[str]) -> str:
    if not failures:
        return "No guardrail details available."
    return ", ".join(item.replace("_", " ") for item in failures)


DEVELOPER_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Trader Developer Dashboard</title>
  <style>
    body { margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f6f7f9; color: #17202a; }
    header { background: #ffffff; border-bottom: 1px solid #dde1e7; padding: 20px 28px; }
    main { padding: 24px; max-width: 1100px; margin: 0 auto; }
    h1 { margin: 0; font-size: 26px; }
    .sub { margin-top: 6px; color: #667085; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
    .card { background: #ffffff; border: 1px solid #dde1e7; border-radius: 8px; padding: 14px; }
    .label { font-weight: 800; margin-bottom: 8px; }
    .healthy { color: #137333; font-weight: 800; }
    .problem { color: #b42318; font-weight: 800; }
    .detail { margin-top: 8px; color: #475467; font-size: 13px; overflow-wrap: anywhere; }
    .counts { margin-top: 18px; }
    button { border: 0; border-radius: 8px; background: #1f6feb; color: #fff; font-weight: 800; padding: 10px 14px; cursor: pointer; }
  </style>
</head>
<body>
  <header>
    <h1>AI Trader Developer Dashboard</h1>
    <div class="sub" id="generated">Loading local status...</div>
  </header>
  <main>
    <p><button onclick="loadStatus()">Refresh</button></p>
    <section class="grid" id="components"></section>
    <section class="card counts">
      <div class="label">Counts</div>
      <div id="counts">Not available</div>
    </section>
    <section class="card counts">
      <div class="label">Last Founder Brief</div>
      <div id="brief">Not available</div>
    </section>
  </main>
  <script>
    const names = {
      python: 'Python Version',
      sqlite: 'SQLite Status',
      openai: 'OpenAI Status',
      alpaca: 'Alpaca Status',
      knowledge_engine: 'Knowledge Engine Status',
      benchmark_engine: 'Benchmark Engine Status',
      trading_engine: 'Trading Engine Status',
      api: 'API Status',
      mobile_app: 'Mobile App Status'
    };
    function icon(ok) { return ok ? '🟢 Healthy' : '🔴 Problem'; }
    async function loadStatus() {
      const response = await fetch('/developer-status');
      const data = await response.json();
      document.getElementById('generated').textContent = `Generated ${data.generated_at}`;
      document.getElementById('components').innerHTML = Object.entries(data.components).map(([key, item]) => `
        <div class="card">
          <div class="label">${names[key] || key}</div>
          <div class="${item.healthy ? 'healthy' : 'problem'}">${icon(item.healthy)}</div>
          <div class="detail">${item.detail || 'Not available'}</div>
        </div>
      `).join('');
      document.getElementById('counts').innerHTML = `
        Watchlist Count: ${data.counts.watchlist}<br>
        Market Theme Count: ${data.counts.market_themes}<br>
        Benchmark Trader Count: ${data.counts.benchmark_traders}<br>
        Trading Journal Count: ${data.counts.trading_journal}
      `;
      document.getElementById('brief').textContent = data.last_founder_brief
        ? `${data.last_founder_brief.briefing_date} (${data.last_founder_brief.created_at})`
        : 'Not available';
    }
    loadStatus().catch(error => {
      document.getElementById('generated').textContent = `Problem loading status: ${error}`;
    });
  </script>
</body>
</html>"""
