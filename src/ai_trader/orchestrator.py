from __future__ import annotations

import sqlite3
import time
from .database import connect
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .broker_adapters import BrokerAdapter, _float_env, _kraken_pair
from .canonical_trades import link_broker_order, register_execution_intent
from .foundation import (
    position_cap_for,
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
from .kraken_reconciliation import (
    reconciliation_control,
    register_kraken_order_ownership,
)
from .models import AccountContext, AutoTradeConfig, GuardrailConfig, OrderRequest, OrchestratorDecision, TradeProposal, utc_now_iso
from .multi_broker import (
    acquire_order_intent_lock,
    complete_order_intent_lock,
    record_managed_trade_exit,
    record_native_stop_order_id,
    record_notification,
    record_seatbelt_event,
)
from .operational import latest_pnl_snapshot
from .trading_intelligence import latest_intelligence_packet, record_lifecycle_stage


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
    def __init__(self, *, db_path: Path, adapters: list[BrokerAdapter], initialize_schema: bool = True):
        self.db_path = db_path
        self.adapters = {adapter.name: adapter for adapter in adapters}
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if initialize_schema:
            self.initialize()

    def initialize(self) -> None:
        with closing(connect(self.db_path)) as conn:
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
        _eval_t0 = time.monotonic()
        p = proposal.normalized()
        intelligence = latest_intelligence_packet(self.db_path, p.proposal_id) or {}
        strategy_id = (
            (intelligence.get("committee") or {}).get("strategy_id")
            or (intelligence.get("probability") or {}).get("strategy_id")
        )
        print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=intelligence_loaded elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
        selected = self._select_adapter(p)
        market_open = selected.is_market_open(p.exchange) if selected else False
        asset_available = selected.is_asset_available(p.symbol, p.exchange, p.asset_type) if selected else False
        print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=adapter_selected broker={selected.name if selected else None} elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
        validation = validate_trade_proposal(p, context.account, context.guardrails, now=context.now)
        print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=guardrails_validated elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
        policy = load_trading_policy(self.db_path, auto_trade=context.auto_trade, guardrails=context.guardrails)
        print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=policy_loaded elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
        due_diligence = create_due_diligence_assessment(self.db_path, p)
        print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=due_diligence_assessed elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
        investment_score = calculate_investment_score(self.db_path, p)
        print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=investment_score_calculated elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
        allocation = calculate_capital_allocation(
            self.db_path,
            p,
            policy,
            account_equity=context.account.equity,
        )
        print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=capital_allocation_calculated elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
        failures: list[str] = []
        if selected is None:
            failures.append("no_configured_broker_supports_asset")
        if not asset_available:
            failures.append("asset_unavailable")
        if not market_open:
            failures.append("market_closed")
        if not policy.paper_trading_only:
            failures.append("paper_trading_only_failed")
        if selected and selected.name in policy.broker_enabled and not policy.broker_enabled[selected.name] and not context.auto_trade.enabled:
            failures.append("broker_disabled_by_policy")
        if p.side == "sell" and not context.guardrails.allow_short_selling:
            failures.append("short_selling_disabled")
        # 2026-08-29, Founder-directed: four checks collapsed to two.
        #
        # These were two questions asked twice each, and the duplication cost real money in
        # confusion: tuning one threshold took four separate investigations and two wrong
        # attempts, because the raw and averaged numbers differ and the raw one blocks first.
        #
        #   "is this convincing"  was checked on p.confidence_score AND on the investment
        #                         score's overall_confidence -- but that score is largely the
        #                         SAME number averaged with itself: fundamental, technical,
        #                         market, macro and behavioural are each set to `confidence`
        #                         (foundation.py). A smoothed copy is not a second opinion, and
        #                         gating on both is double jeopardy on one measurement.
        #
        #   "is this permitted"   was checked on p.philosophy_fit AND on the investment score's
        #                         investment_policy_score -- which is that identical value
        #                         copied across (`policy = float(p.philosophy_fit or 0.0)`).
        #                         The same number, compared to the same threshold, twice.
        #
        # So: one confidence gate on the research verdict itself, and one permission gate.
        # The seven-dimension investment score is still computed and recorded as evidence --
        # its macro, behavioural and risk terms are real -- it simply no longer acts as a
        # second gate on numbers already tested here.
        if p.confidence_score < policy.min_ai_confidence:
            failures.append("confidence_below_minimum")
        # Permission, not preference. A company absent from the Founder-approved universe has
        # no rating and therefore scores 0.0 (TradeProposal's default), so it can never pass --
        # which is what enforces the Shariah screen. See models.py philosophy_fit.
        if p.philosophy_fit < policy.min_investment_policy_fit:
            failures.append("not_in_permitted_universe")
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
        # 2026-09-01: the cap is per broker now. It was one shared number sized for Kraken,
        # which left Alpaca full at 5 positions on a 101,000 dollar account with 93,000 idle
        # -- and the learning data says that is the most expensive refusal we make (19 of
        # them, price moved +3.24% afterwards). See foundation.position_cap_for.
        position_cap = position_cap_for(policy, selected.name if selected else None)
        if len(context.account.open_positions) >= position_cap:
            failures.append("maximum_concurrent_positions_exceeded")
        if allocation["result"] != "approved":
            failures.append("capital_allocation_rejected")
        pnl_snapshot = latest_pnl_snapshot(self.db_path, selected.name) if selected else {}
        if context.account.equity > 0:
            # PORTFOLIO_SNAPSHOTS.portfolio_value (and the day/week/month_pnl derived from
            # it) reflects the broker's whole account -- for Kraken specifically that
            # includes pre-existing personal holdings alongside the AI's own isolated
            # allocation, so it can be an order of magnitude larger than
            # context.account.equity (deliberately scoped to just the AI's own capital,
            # see _account_context_for_broker/_kraken_trading_allocation_gbp). Comparing
            # a whole-account P&L swing against a tiny isolated equity figure means
            # ordinary price movement on capital the AI never touched could trip a guard
            # meant to protect the AI's own allocation. Hosted evidence (2026-08-01): this
            # produced a standing false-positive maximum_weekly_loss_exceeded on every
            # single Kraken candidate. The drawdown check below already guards against
            # exactly this mismatch via _snapshot_equity_basis_matches_context -- the
            # weekly/monthly checks were simply missing the same guard.
            snapshot_basis_matches = _snapshot_equity_basis_matches_context(
                pnl_snapshot.get("portfolio_value") or 0.0, context.account.equity
            )
            week_pnl = pnl_snapshot.get("week_pnl")
            if snapshot_basis_matches and week_pnl is not None and week_pnl <= -(context.account.equity * policy.max_weekly_loss_pct):
                failures.append("maximum_weekly_loss_exceeded")
            month_pnl = pnl_snapshot.get("month_pnl")
            if snapshot_basis_matches and month_pnl is not None and month_pnl <= -(context.account.equity * policy.max_monthly_loss_pct):
                failures.append("maximum_monthly_loss_exceeded")
            peak_equity = pnl_snapshot.get("peak_equity")
            if peak_equity and peak_equity > 0 and _snapshot_equity_basis_matches_context(peak_equity, context.account.equity):
                drawdown_pct = (peak_equity - context.account.equity) / peak_equity
                if drawdown_pct > policy.max_drawdown_pct:
                    failures.append("maximum_drawdown_exceeded")
            current_exposure = sum(abs(getattr(pos, "market_value", 0.0) or 0.0) for pos in context.account.open_positions)
            prospective_exposure_pct = (current_exposure + allocation["approved_notional"]) / context.account.equity
            if prospective_exposure_pct > policy.max_concurrent_exposure_pct:
                failures.append("maximum_concurrent_exposure_exceeded")
            if prospective_exposure_pct > policy.max_capital_allocation_pct:
                failures.append("maximum_capital_allocation_exceeded")
        failures.extend(validate_investment_universe(self.db_path, p, policy))
        failures.extend(validation.failures)
        print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=pre_governance_checks_done elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)

        production_packet: dict[str, Any] | None = None
        if selected and getattr(selected, "requires_production_governance", True):
            # One production pipeline: every real broker route passes the same
            # Strategy -> Portfolio -> Risk -> Sentinel decision chain here.
            from .sprint6 import pre_execution_decision_packet

            production_packet = pre_execution_decision_packet(
                self.db_path,
                proposal=p,
                broker=selected.name,
                mode="paper" if selected.name == "alpaca" else "micro_live",
                account=context.account,
                guardrails=context.guardrails,
                now=context.now,
                market_data_quality=(
                    (intelligence.get("market_data") or {}).get("quality")
                    or "Unknown - no current market-data quality record was attached."
                ),
            )
            print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=production_governance_done elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
            if not production_packet["approved"]:
                failures.extend(production_packet["reasons"])
            elif production_packet.get("approved_notional") is not None:
                allocation["approved_notional"] = min(
                    float(allocation["approved_notional"]),
                    float(production_packet["approved_notional"]),
                )
        if selected and selected.name == "kraken":
            kraken_control = reconciliation_control(self.db_path)
            if kraken_control.get("hold_new_entries"):
                failures.append("kraken_reconciliation_hold")
            # Founder investigation (2026-08-05/06): every Kraken order attempt was rejected by
            # the exchange itself for "min_order_amount_not_met". Root cause: risk-based sizing
            # (calculate_capital_allocation's max_position_size_pct, default 5%) applied to the
            # small isolated Kraken allocation (context.account.equity, e.g. £38.23) produces a
            # per-trade notional (~£1.91) that is smaller than this deployment's configured
            # KRAKEN_MIN_ORDER_GBP - a real, checkable-in-advance value this code already knows,
            # yet nothing upstream avoided producing an order guaranteed to fail it. Worse, each
            # failed attempt permanently locks that proposal_id (order-intent locks are only
            # released for ambiguous outcomes, not clean rejections like this one - see
            # release_order_intent_lock's docstring), so the same undersized proposal then blocks
            # itself from ever being retried, compounding the problem every research cycle.
            #
            # Fix: when the risk-based size is genuinely positive but falls short of the
            # exchange's own minimum, raise it to that minimum instead of submitting an order
            # already known to fail - never lower a size (that stays the honest risk-based
            # figure), and never raise past what the account can actually afford. This is a
            # sizing correctness fix, not a risk-appetite change: 5% of a small allocation was
            # always intended to be a real, tradeable position, not a guaranteed rejection. Pulled
            # out as its own pure function (below) so it is directly unit-testable without
            # standing up the full governance chain.
            min_notional = _float_env("KRAKEN_MIN_ORDER_GBP", 1.0)
            floored_notional = _kraken_min_order_floor_notional(
                approved_notional=float(allocation.get("approved_notional") or 0.0),
                account_equity=context.account.equity,
                min_notional=min_notional,
            )
            if floored_notional != allocation.get("approved_notional"):
                print(
                    f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=kraken_min_order_floor_applied "
                    f"original_notional={allocation.get('approved_notional')} floored_to={floored_notional} elapsed={time.monotonic() - _eval_t0:.1f}s",
                    flush=True,
                )
                allocation["approved_notional"] = floored_notional
                allocation["approved_quantity"] = floored_notional / p.entry_price if p.entry_price > 0 else 0.0
            # 2026-08-10 hosted incident: KRAKEN_MIN_ORDER_GBP above is one flat guess applied to
            # every pair; Kraken's real minimum order size is set per-pair by the exchange and can
            # be higher. Confirmed live: a proposal correctly floored to GBP 2.00 by the check
            # above still passed every governance check, was submitted, and was rejected by
            # Kraken itself with "EGeneral:Invalid arguments:volume minimum not met". Ask the
            # exchange for the real, authoritative minimum for this specific pair and raise to
            # that if it's higher than what the check above already produced -- same non-lowering,
            # never-exceed-what's-affordable discipline as _kraken_min_order_floor_notional. If
            # even the real minimum can't be afforded or exceeds this deployment's configured
            # ceiling, fail cleanly with an honest reason instead of submitting an order already
            # known to fail at the exchange.
            pair = _kraken_pair(p.symbol)
            exchange_minimum = selected.pair_minimum_notional(pair, p.entry_price) if hasattr(selected, "pair_minimum_notional") else None
            if exchange_minimum is not None and exchange_minimum > allocation.get("approved_notional", 0.0):
                max_notional = _float_env("KRAKEN_MAX_ORDER_GBP", 5.0)
                if exchange_minimum <= context.account.equity and exchange_minimum <= max_notional:
                    print(
                        f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=kraken_exchange_min_order_floor_applied "
                        f"pair={pair} original_notional={allocation.get('approved_notional')} floored_to={exchange_minimum} elapsed={time.monotonic() - _eval_t0:.1f}s",
                        flush=True,
                    )
                    allocation["approved_notional"] = exchange_minimum
                    allocation["approved_quantity"] = exchange_minimum / p.entry_price if p.entry_price > 0 else 0.0
                else:
                    failures.append("kraken_exchange_minimum_not_tradeable_at_current_limits")
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
            print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=order_path_entered broker={selected.name} elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
            logical_trade_id = register_execution_intent(
                self.db_path,
                proposal=p,
                broker=selected.name,
                decision_context={
                    "proposal": p.to_dict(),
                    "intelligence": intelligence,
                    "production_gate": production_packet,
                    "allocation": allocation,
                    "guardrails": validation.to_dict(),
                    "account_equity": context.account.equity,
                },
            )
            print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=execution_intent_registered logical_trade_id={logical_trade_id} elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
            client_order_id = p.proposal_id
            lock_acquired = acquire_order_intent_lock(
                self.db_path,
                broker=selected.name,
                client_order_id=client_order_id,
                symbol=p.symbol,
                side=p.side,
                notional=allocation["approved_notional"],
            )
            print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=order_intent_lock_attempted acquired={lock_acquired} elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
            if not lock_acquired:
                failures.append("duplicate_order_intent")
                decision_text = "rejected"
                notes = "Duplicate order intent blocked before broker submission."
                order = {}
            else:
                record_seatbelt_event(
                    self.db_path,
                    broker=selected.name,
                    symbol=p.symbol,
                    event_type="order_intent_locked",
                    result="passed",
                    message="Duplicate order lock acquired before broker submission.",
                    payload={"proposal_id": p.proposal_id, "notional": allocation["approved_notional"]},
                )
                order_request = _order_request(p, allocation["approved_notional"])
                print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=broker_order_submitting notional={allocation['approved_notional']} elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
                try:
                    order = selected.place_bracket_order(order_request)
                except Exception as exc:  # noqa: BLE001 - must see the failure, not lose it to the outer timeout
                    print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=broker_order_failed error={exc!r} elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
                    raise
                print(f"[evaluate_recommendation] proposal_id={p.proposal_id} stage=broker_order_submitted order={json_safe(order)} elapsed={time.monotonic() - _eval_t0:.1f}s", flush=True)
                broker_order_id = str(order.get("id") or order.get("order_id") or "")
                if broker_order_id:
                    link_broker_order(
                        self.db_path,
                        logical_trade_id=logical_trade_id,
                        broker_order_id=broker_order_id,
                        payload=order,
                    )
                    if selected.name == "kraken":
                        register_kraken_order_ownership(
                            self.db_path,
                            broker_order_id=broker_order_id,
                            logical_trade_id=logical_trade_id,
                            proposal_id=p.proposal_id,
                            order_role="entry",
                            symbol=p.symbol,
                            side=p.side,
                        )
                complete_order_intent_lock(
                    self.db_path,
                    broker=selected.name,
                    client_order_id=client_order_id,
                    status=str(order.get("status", "submitted")),
                    result_order_id=str(order.get("id") or order.get("order_id") or ""),
                    notes=json_safe(order),
                )
            order_id = str(order.get("id") or order.get("order_id") or "")
            if order.get("status") in {"accepted", "submitted"}:
                notes = f"Order submitted with status {order.get('status', 'submitted')}."
                record_seatbelt_event(
                    self.db_path,
                    broker=selected.name,
                    symbol=p.symbol,
                    event_type="broker_order_confirmed",
                    result="passed",
                    message=notes,
                    payload=order,
                )
                # 2026-08-22, Founder-directed: Alpaca joins this block so equities also get
                # a managed exit and a native trailing stop. Previously it was Kraken-only,
                # so Alpaca positions had only the fixed bracket stop from entry and no
                # trailing protection at all -- the risk control that has to exist before
                # leverage is turned on there. register_kraken_order_ownership below stays
                # Kraken-only: it writes KRAKEN_AI_ORDER_OWNERSHIP, which is Kraken's
                # reconciliation ledger and has no meaning for an Alpaca order.
                if selected.name in {"kraken", "alpaca"}:
                    managed = record_managed_trade_exit(
                        self.db_path,
                        broker=selected.name,
                        symbol=p.symbol,
                        side=p.side,
                        quantity=float(order.get("quantity") or order_request.quantity),
                        entry_order_id=order_id,
                        entry_price=p.entry_price,
                        stop_loss=p.stop_loss,
                        take_profit=p.take_profit,
                        payload={**order, "proposal_id": p.proposal_id, "entry_reason": p.plain_english_reasoning},
                        trailing_stop_pct=policy.trailing_stop_pct if policy.trailing_stop_enabled else None,
                    )
                    if selected.name == "kraken":
                        register_kraken_order_ownership(
                            self.db_path,
                            broker_order_id=order_id,
                            logical_trade_id=logical_trade_id,
                            proposal_id=p.proposal_id,
                            managed_exit_id=int(managed["managed_exit_id"]),
                            order_role="entry",
                            symbol=p.symbol,
                            side=p.side,
                        )
                    _attach_native_trailing_stop(
                        self.db_path,
                        adapter=selected,
                        policy=policy,
                        proposal=p,
                        logical_trade_id=logical_trade_id,
                        order=order,
                        order_request=order_request,
                        managed_exit_id=int(managed["managed_exit_id"]),
                    )
                    record_notification(
                        self.db_path,
                        event_type="trade_accepted",
                        broker=selected.name,
                        symbol=p.symbol,
                        title="Trade accepted",
                        message=f"{selected.name.title()} accepted {p.symbol}; managed exit #{managed['managed_exit_id']} is open.",
                        payload={"order": order, "managed_exit": managed},
                    )
                self.record_auto_trade_event(
                    mode="auto_live" if selected.name == "kraken" else "auto_paper",
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
            elif not failures:
                failures.append(str(order.get("reason") or order.get("status") or "broker_order_rejected"))
                decision_text = "rejected"
                notes = str(order.get("reason") or "Broker rejected the order.")

        if failures:
            decision_text = "rejected"
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
        lifecycle_stage = "rejected" if failures else ("submitted" if decision_text == "approved" else "approved")
        record_lifecycle_stage(
            self.db_path,
            p,
            stage=lifecycle_stage,
            reason=decision.rejection_reason or notes or decision_text,
            broker=selected.name if selected else None,
            strategy_id=strategy_id,
            payload=decision.to_dict(),
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
        with closing(connect(self.db_path)) as conn:
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
        with closing(connect(self.db_path)) as conn:
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
        with closing(connect(self.db_path)) as conn:
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


def _attach_native_trailing_stop(
    db_path: Path,
    *,
    adapter: Any,
    policy: Any,
    proposal: TradeProposal,
    logical_trade_id: str,
    order: dict[str, Any],
    order_request: OrderRequest,
    managed_exit_id: int,
) -> dict[str, Any]:
    """Attach a native Kraken trailing-stop order to a just-confirmed entry, so the
    stop-loss leg lives on Kraken's own order book instead of only in AI Trader's polling
    loop. Founder's stated reasoning (2026-08-19): the software-side trailing stop in
    monitor_managed_exits can only act while this process is up and Kraken is reachable --
    a connectivity gap or heavy traffic during a bull run would leave a position with no
    working exit.

    Pulled out of evaluate_recommendation as its own function -- like
    _kraken_min_order_floor_notional above -- specifically so it can be unit-tested in
    isolation without needing a from-scratch test database to clear every other governance
    gate (due diligence, investment score, crypto policy, reconciliation hold) that a
    genuinely 'approved' end-to-end decision would require.

    Never raises: a failure here must not lose or roll back an entry that has already
    filled. On any non-success outcome, record_managed_trade_exit's own trailing_stop_pct
    (already written before this runs) keeps monitor_managed_exits protecting the position
    in software, just not natively -- so this always degrades gracefully, never silently.
    """
    if not policy.trailing_stop_enabled or not hasattr(adapter, "place_trailing_stop_order"):
        return {"status": "skipped"}
    exit_side = "sell" if proposal.side.lower() == "buy" else "buy"
    trailing_order_request = OrderRequest(
        symbol=proposal.symbol,
        side=exit_side,
        quantity=float(order.get("quantity") or order_request.quantity),
        asset_type=proposal.asset_type,
        exchange=proposal.exchange,
        stop_loss=0,
        take_profit=0,
        client_order_id=f"trailing-stop-{managed_exit_id}",
        quote_currency=order_request.quote_currency,
        broker_pair=order.get("pair"),
    )
    try:
        native_stop = adapter.place_trailing_stop_order(trailing_order_request, policy.trailing_stop_pct)
    except Exception as exc:  # noqa: BLE001 - never let stop-attachment failure lose a confirmed entry
        native_stop = {"status": "attach_failed", "reason": str(exc)}
    native_order_id = str(native_stop.get("id") or native_stop.get("order_id") or "")
    if native_stop.get("status") in {"accepted", "submitted"} and native_order_id:
        record_native_stop_order_id(db_path, managed_exit_id, native_order_id)
        # Kraken-only: KRAKEN_AI_ORDER_OWNERSHIP is Kraken's reconciliation ledger and an
        # Alpaca order id in it would be a permanently unmatchable row.
        if getattr(adapter, "name", "") == "kraken":
            register_kraken_order_ownership(
                db_path,
                broker_order_id=native_order_id,
                logical_trade_id=logical_trade_id,
                proposal_id=proposal.proposal_id,
                managed_exit_id=managed_exit_id,
                order_role="exit",
                symbol=proposal.symbol,
                side=exit_side,
                source="native_trailing_stop_entry",
            )
    else:
        record_seatbelt_event(
            db_path,
            broker=adapter.name,
            symbol=proposal.symbol,
            event_type="native_trailing_stop_attach_failed",
            result="degraded",
            message="Native Kraken trailing-stop placement failed; falling back to software-side trailing-stop monitoring.",
            payload={"managed_exit_id": managed_exit_id, "native_stop_result": native_stop},
        )
    return native_stop


def _snapshot_equity_basis_matches_context(peak_equity: float, account_equity: float) -> bool:
    if account_equity <= 0:
        return False
    return peak_equity <= account_equity * 1.5


# Founder investigation (2026-08-05/06): see the call site in evaluate_recommendation for the
# full root-cause account. Pure function so the sizing rule can be proven correct in isolation:
# raises a genuinely positive but sub-minimum notional up to the exchange's own minimum, never
# lowers a size, and never raises past what the account can actually afford.
def _kraken_min_order_floor_notional(*, approved_notional: float, account_equity: float, min_notional: float) -> float:
    if 0 < approved_notional < min_notional <= account_equity:
        return min_notional
    return approved_notional


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


def json_safe(value: Any) -> str:
    try:
        import json

        return json.dumps(value, sort_keys=True, default=str)
    except Exception:
        return str(value)
