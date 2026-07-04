from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .broker_adapters import BrokerAdapter
from .foundation import (
    calculate_capital_allocation,
    calculate_investment_score,
    create_due_diligence_assessment,
    initialize_foundation_schema,
    load_trading_policy,
    record_broker_decision,
    record_execution_decision,
    validate_investment_universe,
)
from .guardrails import validate_trade_proposal
from .models import AccountContext, AutoTradeConfig, GuardrailConfig, OrderRequest, OrchestratorDecision, TradeProposal, utc_now_iso


ORCHESTRATOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS ORCHESTRATOR_DECISIONS (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    recommendation_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    exchange TEXT NOT NULL,
    requested_action TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    philosophy_fit REAL NOT NULL,
    selected_broker TEXT,
    market_open INTEGER NOT NULL,
    asset_available INTEGER NOT NULL,
    guardrails_passed INTEGER NOT NULL,
    decision TEXT NOT NULL,
    rejection_reason TEXT,
    order_id TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS AUTO_TRADE_EVENTS (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    symbol TEXT NOT NULL,
    broker TEXT,
    action TEXT NOT NULL,
    amount REAL,
    stop_loss_pct REAL,
    take_profit_pct REAL,
    result TEXT NOT NULL,
    order_status TEXT,
    realised_pnl REAL,
    unrealised_pnl REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS DAILY_BRIEFS (
    brief_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    brief_type TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    summary TEXT NOT NULL,
    trades_executed INTEGER NOT NULL,
    trades_rejected INTEGER NOT NULL,
    pnl_summary TEXT,
    risk_summary TEXT,
    intelligence_summary TEXT,
    lessons_learned TEXT
);
"""


@dataclass(frozen=True)
class OrchestratorContext:
    account: AccountContext
    auto_trade: AutoTradeConfig
    guardrails: GuardrailConfig
    now: datetime | None = None


class InvestmentOrchestrator:
    def __init__(self, *, db_path: Path, adapters: list[BrokerAdapter]):
        self.db_path = db_path
        self.adapters = {adapter.name: adapter for adapter in adapters}
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn:
                conn.executescript(ORCHESTRATOR_SCHEMA)
        initialize_foundation_schema(self.db_path)

    def evaluate_recommendation(
        self,
        proposal: TradeProposal,
        context: OrchestratorContext,
        *,
        auto_execute: bool,
    ) -> OrchestratorDecision:
        p = proposal.normalized()
        selected = self._select_adapter(p)
        market_open = selected.is_market_open(p.exchange) if selected else False
        asset_available = selected.is_asset_available(p.symbol, p.exchange, p.asset_type) if selected else False
        validation = validate_trade_proposal(p, context.account, context.guardrails, now=context.now)
        policy = load_trading_policy(self.db_path, auto_trade=context.auto_trade, guardrails=context.guardrails)
        due_diligence = create_due_diligence_assessment(self.db_path, p)
        investment_score = calculate_investment_score(self.db_path, p)
        allocation = calculate_capital_allocation(
            self.db_path,
            p,
            policy,
            account_equity=context.account.equity,
        )
        failures: list[str] = []
        if selected is None:
            failures.append("no_configured_broker_supports_asset")
        if not asset_available:
            failures.append("asset_unavailable")
        if not market_open:
            failures.append("market_closed")
        if not policy.paper_trading_only:
            failures.append("paper_trading_only_failed")
        if selected and selected.name in policy.broker_enabled and not policy.broker_enabled[selected.name]:
            failures.append("broker_disabled_by_policy")
        if p.side == "sell" and not context.guardrails.allow_short_selling:
            failures.append("short_selling_disabled")
        if p.confidence_score < policy.min_ai_confidence:
            failures.append("confidence_below_auto_trade_minimum")
        if p.philosophy_fit < policy.min_investment_policy_fit:
            failures.append("philosophy_fit_below_auto_trade_minimum")
        if investment_score["overall_confidence"] < policy.min_ai_confidence:
            failures.append("investment_score_below_policy_minimum")
        if investment_score["investment_policy_score"] < policy.min_investment_policy_fit:
            failures.append("investment_policy_score_below_minimum")
        if due_diligence["overall_status"] != "completed":
            failures.append("due_diligence_incomplete")
        if p.stop_loss <= 0:
            failures.append("stop_loss_mandatory")
        if policy.take_profit_required and p.take_profit <= 0:
            failures.append("take_profit_mandatory")
        stop_loss_pct = _stop_loss_pct(p)
        if stop_loss_pct > policy.max_stop_loss_pct:
            failures.append("max_stop_loss_pct_exceeded")
        if context.account.equity <= policy.emergency_shutdown_balance:
            failures.append("emergency_shutdown_balance_breached")
        if len(context.account.open_positions) >= policy.max_concurrent_positions:
            failures.append("maximum_concurrent_positions_exceeded")
        if allocation["result"] != "approved":
            failures.append("capital_allocation_rejected")
        failures.extend(validate_investment_universe(self.db_path, p, policy))
        failures.extend(validation.failures)
        failures = list(dict.fromkeys(failures))
        record_broker_decision(
            self.db_path,
            p,
            selected_broker=selected.name if selected else None,
            broker_healthy=selected is not None,
            asset_available=asset_available,
            market_open=market_open,
            result="rejected" if failures else "approved",
            reason=", ".join(failures) if failures else None,
        )

        decision_text = "approved"
        order_id = None
        notes = "Executable recommendation."
        if failures:
            decision_text = "rejected"
            notes = "Rejected by Investment Orchestrator."
        elif not auto_execute or not context.auto_trade.enabled:
            decision_text = "manual_approval_required"
            notes = "Auto Paper Trading is disabled; recommendation requires manual approval."
        else:
            assert selected is not None
            order = selected.place_bracket_order(_order_request(p, allocation["approved_notional"]))
            order_id = str(order.get("id") or order.get("order_id") or "")
            notes = f"Paper bracket order submitted with status {order.get('status', 'submitted')}."
            self.record_auto_trade_event(
                mode="auto_paper",
                symbol=p.symbol,
                broker=selected.name,
                action=p.side,
                amount=allocation["approved_notional"],
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=_take_profit_pct(p),
                result="submitted",
                order_status=str(order.get("status", "submitted")),
                notes=notes,
            )

        decision = OrchestratorDecision(
            recommendation_id=p.proposal_id,
            symbol=p.symbol,
            asset_type=p.asset_type,
            exchange=p.exchange,
            requested_action=p.side,
            confidence_score=p.confidence_score,
            philosophy_fit=p.philosophy_fit,
            selected_broker=selected.name if selected else None,
            market_open=market_open,
            asset_available=asset_available,
            guardrails_passed=validation.passed and not failures,
            decision=decision_text,
            rejection_reason=", ".join(failures) if failures else None,
            order_id=order_id,
            notes=notes,
        )
        self.record_decision(decision)
        record_execution_decision(
            self.db_path,
            p,
            decision=decision_text,
            validation_result=", ".join(failures) if failures else "passed",
            order_id=order_id,
            reason=decision.rejection_reason or notes,
        )
        if failures:
            self.record_auto_trade_event(
                mode="auto_paper" if context.auto_trade.enabled else "manual_required",
                symbol=p.symbol,
                broker=selected.name if selected else None,
                action=p.side,
                amount=allocation["approved_notional"],
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=_take_profit_pct(p),
                result="rejected",
                order_status=None,
                notes=decision.rejection_reason,
            )
        return decision

    def record_decision(self, decision: OrchestratorDecision) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO ORCHESTRATOR_DECISIONS (
                        created_at, recommendation_id, symbol, asset_type, exchange,
                        requested_action, confidence_score, philosophy_fit, selected_broker,
                        market_open, asset_available, guardrails_passed, decision,
                        rejection_reason, order_id, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.created_at,
                        decision.recommendation_id,
                        decision.symbol,
                        decision.asset_type,
                        decision.exchange,
                        decision.requested_action,
                        decision.confidence_score,
                        decision.philosophy_fit,
                        decision.selected_broker,
                        int(decision.market_open),
                        int(decision.asset_available),
                        int(decision.guardrails_passed),
                        decision.decision,
                        decision.rejection_reason,
                        decision.order_id,
                        decision.notes,
                    ),
                )

    def record_auto_trade_event(
        self,
        *,
        mode: str,
        symbol: str,
        broker: str | None,
        action: str,
        amount: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        result: str,
        order_status: str | None,
        notes: str | None,
    ) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO AUTO_TRADE_EVENTS (
                        created_at, mode, symbol, broker, action, amount, stop_loss_pct,
                        take_profit_pct, result, order_status, realised_pnl,
                        unrealised_pnl, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (utc_now_iso(), mode, symbol, broker, action, amount, stop_loss_pct, take_profit_pct, result, order_status, None, None, notes),
                )

    def latest_decision(self) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM ORCHESTRATOR_DECISIONS ORDER BY decision_id DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def _select_adapter(self, proposal: TradeProposal) -> BrokerAdapter | None:
        for adapter in self.adapters.values():
            if proposal.asset_type in adapter.get_supported_assets():
                return adapter
        return None


def _order_request(proposal: TradeProposal, approved_notional: float) -> OrderRequest:
    qty = max(0.000001, approved_notional / proposal.entry_price if proposal.entry_price > 0 else 0)
    return OrderRequest(
        symbol=proposal.symbol,
        side=proposal.side,
        quantity=qty,
        asset_type=proposal.asset_type,
        exchange=proposal.exchange,
        stop_loss=proposal.stop_loss,
        take_profit=proposal.take_profit,
        notional_amount=approved_notional,
        client_order_id=proposal.proposal_id,
    )


def _stop_loss_pct(proposal: TradeProposal) -> float:
    if proposal.entry_price <= 0:
        return 1.0
    return abs(proposal.entry_price - proposal.stop_loss) / proposal.entry_price


def _take_profit_pct(proposal: TradeProposal) -> float:
    if proposal.entry_price <= 0:
        return 0.0
    return abs(proposal.take_profit - proposal.entry_price) / proposal.entry_price


def next_research_run(now: datetime | None = None, interval_minutes: int = 60) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current.astimezone(timezone.utc) + timedelta(minutes=interval_minutes)).isoformat()
