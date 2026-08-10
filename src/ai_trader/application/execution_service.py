from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..broker_adapters import _kraken_last_price, _kraken_pair
from ..config import Settings
from ..models import AccountContext, OrderRequest, TradeProposal, utc_now_iso
from ..multi_broker import (
    acquire_order_intent_lock,
    broker_auto_settings,
    broker_auto_trading_enabled,
    complete_order_intent_lock,
    mark_managed_exit_submitted,
    open_managed_exits,
    record_notification,
    release_order_intent_lock,
    update_broker_runtime,
    update_trailing_water_marks,
)
from ..kraken_reconciliation import register_kraken_order_ownership
from ..operational import safe_float, safe_score
from ..orchestrator import InvestmentOrchestrator, OrchestratorContext, json_safe
from ..persistence.query_executor import QueryExecutor
from .shared_helpers import _int_or_default


# Phase 8 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md): these
# helpers are pure, stateless functions also used by parts of api/__init__.py that are out
# of this phase's scope (recommendations() and friends -- founder-presentation-adjacent,
# still un-extracted), so they cannot be imported without a circular import (api/__init__.py
# imports ExecutionService at module load time, before its own later-defined functions
# exist yet). Duplicated verbatim rather than imported, matching the established convention
# from every prior phase. Behaviourally identical to api/__init__.py's copies.
# (_int_or_default itself was consolidated into shared_helpers.py in Phase 9.)
def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _recommendation_freshness(created_at: str | None, confidence: Any) -> dict[str, Any]:
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
    expires_at = generated_at + lifetime
    now = datetime.now(timezone.utc)
    if now > expires_at:
        status = "Expired"
    elif now > generated_at + (lifetime / 2):
        status = "Stale"
    else:
        status = "Fresh"
    return {
        "status": status,
        "expires_at": expires_at.isoformat(),
        "note": f"{status}. Trade idea lifetime is {int(lifetime.total_seconds() / 3600)} hours.",
    }


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


def _validation_failures(validation_result: Any) -> list[str]:
    data = _validation_payload(validation_result)
    if not data:
        return []
    failures = data.get("failures") or []
    return [str(item) for item in failures]


def _format_guardrail_failures(failures: list[str]) -> str:
    if not failures:
        return "No guardrail details available."
    return ", ".join(item.replace("_", " ") for item in failures)


def _json_loads_safe(payload_json: Any) -> dict[str, Any] | None:
    if not payload_json:
        return None
    try:
        data = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


class ExecutionService:
    """Order execution and managed-exit coordination (architecture/AI_TRADER_
    MODULARISATION_ARCHITECTURE_2026-08-02.md Phase 8): approve_and_execute, autonomous
    recommendation execution, managed-exit monitoring, and forced managed exits, moved out
    of LocalApiService.

    This is a coordinator only, per the plan's explicit requirement. Every authoritative
    safety decision stays in its existing domain module and is called directly, never
    reimplemented here: Strategy/Portfolio/Risk/Sentinel governance and the kill switch
    (orchestrator.evaluate_recommendation, via pre_execution_decision_packet in sprint6.py),
    order-intent locking (acquire_order_intent_lock/complete_order_intent_lock/
    release_order_intent_lock in multi_broker.py -- a lock is only ever released here after a
    definite, synchronous "no order was placed" broker answer; an exception or an ambiguous
    result leaves it locked, matching release_order_intent_lock's own contract), the Kraken
    reconciliation hold (consulted inside orchestrator.evaluate_recommendation itself, not
    duplicated here), broker-adapter order validation (buy-only/allowed-pair/size checks live
    in broker_adapters.KrakenAdapter), and canonical trade lifecycle recording. This class
    only orchestrates calls into that machinery.

    `account_context_lookup`, `control_state_lookup`, `broker_managed_trade_capacity_lookup`,
    and `portfolio_lookup` are narrow, explicit injected dependencies for LocalApiService
    methods that have not been extracted yet -- never a reference to the whole
    LocalApiService object, per the plan's Section 5 dependency rule 6.
    `_account_context_for_broker` specifically carries the Kraken AI capital-sleeve isolation
    logic (`_kraken_trading_allocation_gbp`); this is deliberately injected, not duplicated,
    so that safety-critical logic keeps exactly one implementation anywhere in the codebase --
    the same discipline Phase 5 (research_service.py) and Phase 6a (broker_service.py)
    already established for this exact function.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        orchestrator: InvestmentOrchestrator,
        query_executor: QueryExecutor,
        account_context_lookup: Callable[[str], AccountContext],
        control_state_lookup: Callable[[], dict[str, Any]],
        broker_managed_trade_capacity_lookup: Callable[[str], dict[str, Any]],
        portfolio_lookup: Callable[[str], dict[str, Any]],
    ) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self._query_executor = query_executor
        self._account_context_lookup = account_context_lookup
        self._control_state_lookup = control_state_lookup
        self._broker_managed_trade_capacity_lookup = broker_managed_trade_capacity_lookup
        self._portfolio_lookup = portfolio_lookup

    def approve_and_execute(self, body: dict[str, Any]) -> dict[str, Any]:
        control = self._control_state_lookup()
        if control["trading_state"] != "running":
            return {"status": "blocked", "message": f"Trading state is {control['trading_state']}."}
        proposal_id = body.get("proposal_id")
        if not proposal_id:
            return {"status": "rejected", "message": "proposal_id is required."}
        row = self._query_executor.row(
            "SELECT payload_json, created_at, ai_confidence FROM trade_audit WHERE proposal_id = ? AND event_type = 'agent_proposal' ORDER BY id DESC LIMIT 1",
            (str(proposal_id),),
        )
        if not row:
            symbol = str(body.get("symbol") or "").upper().strip()
            if symbol:
                row = self._query_executor.row(
                    """
                    SELECT payload_json, created_at, ai_confidence, proposal_id
                    FROM trade_audit
                    WHERE UPPER(symbol) = UPPER(?) AND event_type = 'agent_proposal'
                    ORDER BY created_at DESC, id DESC LIMIT 1
                    """,
                    (symbol,),
                )
                if row:
                    proposal_id = row["proposal_id"]
            if not row:
                return {
                    "status": "rejected",
                    "message": "Proposal not found in the production database. Refresh recommendations, then try the latest card again.",
                }
        freshness = _recommendation_freshness(row["created_at"], row["ai_confidence"])
        if freshness["status"] == "Expired":
            return {"status": "blocked", "message": "Recommendation has expired. Run analysis again before execution.", "freshness": freshness}
        payload = json.loads(row["payload_json"])
        proposal = TradeProposal.from_dict(payload["proposal"])
        selected = self.orchestrator._select_adapter(proposal)
        if selected is None:
            return {"status": "rejected", "message": f"No configured broker supports asset type '{proposal.asset_type}'."}
        broker_name = selected.name
        if broker_name == "alpaca" and not self.settings.has_alpaca_credentials:
            return {"status": "not_available", "message": "Alpaca paper credentials are required for execution."}
        managed_capacity = self._broker_managed_trade_capacity_lookup(broker_name)
        if not managed_capacity["can_open"]:
            return {
                "status": "blocked",
                "message": managed_capacity["message"],
                "managed_trade_capacity": managed_capacity,
            }
        context = OrchestratorContext(
            account=self._account_context_lookup(broker_name),
            auto_trade=self._manual_approval_auto_config(broker_name),
            guardrails=self.settings.guardrails,
        )
        proposal = self._proposal_with_manual_amount(proposal, body.get("amount"), account_equity=context.account.equity)
        decision = self.orchestrator.evaluate_recommendation(proposal, context, auto_execute=True)
        if decision.decision == "approved":
            self._portfolio_lookup(broker_name)
        return {
            "status": "submitted" if decision.decision == "approved" else decision.decision,
            "message": decision.notes or decision.rejection_reason or decision.decision,
            "result": decision.to_dict(),
            "amount_requested": body.get("amount"),
        }

    def _proposal_with_manual_amount(self, proposal: TradeProposal, amount: Any, *, account_equity: float) -> TradeProposal:
        requested = safe_float(amount)
        if requested is None or requested <= 0 or proposal.entry_price <= 0:
            return proposal
        quantity = requested / proposal.entry_price
        risk_amount = quantity * abs(proposal.entry_price - proposal.stop_loss)
        risk_percentage = risk_amount / account_equity if account_equity > 0 else proposal.risk_percentage
        return replace(
            proposal,
            position_size=quantity,
            risk_percentage=risk_percentage,
        ).normalized()

    def _manual_approval_auto_config(self, broker: str) -> Any:
        base = self._auto_config_for_broker(broker)
        return type(base)(
            enabled=True,
            broker_enabled=dict(base.broker_enabled),
            min_confidence=base.min_confidence,
            min_philosophy_fit=base.min_philosophy_fit,
            max_trade_amount=base.max_trade_amount,
            default_stop_loss_pct=base.default_stop_loss_pct,
            max_stop_loss_pct=base.max_stop_loss_pct,
            crypto_max_trade_amount=base.crypto_max_trade_amount,
            crypto_default_stop_loss_pct=base.crypto_default_stop_loss_pct,
            crypto_max_stop_loss_pct=base.crypto_max_stop_loss_pct,
        )

    def _auto_config_for_broker(self, broker: str) -> Any:
        enabled = broker_auto_trading_enabled(self.settings.db_path, broker, self.settings.auto_trade.broker_enabled.get(broker, False))
        return type(self.settings.auto_trade)(
            enabled=enabled,
            broker_enabled=dict(self.settings.auto_trade.broker_enabled),
            min_confidence=self.settings.auto_trade.min_confidence,
            min_philosophy_fit=self.settings.auto_trade.min_philosophy_fit,
            max_trade_amount=self.settings.auto_trade.crypto_max_trade_amount if broker == "kraken" else self.settings.auto_trade.max_trade_amount,
            default_stop_loss_pct=self.settings.auto_trade.crypto_default_stop_loss_pct if broker == "kraken" else self.settings.auto_trade.default_stop_loss_pct,
            max_stop_loss_pct=self.settings.auto_trade.crypto_max_stop_loss_pct if broker == "kraken" else self.settings.auto_trade.max_stop_loss_pct,
            crypto_max_trade_amount=self.settings.auto_trade.crypto_max_trade_amount,
            crypto_default_stop_loss_pct=self.settings.auto_trade.crypto_default_stop_loss_pct,
            crypto_max_stop_loss_pct=self.settings.auto_trade.crypto_max_stop_loss_pct,
        )

    def auto_execute_recommendations(self, broker_filter: str | None = None) -> dict[str, Any]:
        _auto_exec_t0 = time.monotonic()
        print(f"[auto-execution] broker={broker_filter} stage=started", flush=True)
        control = self._control_state_lookup()
        if control["trading_state"] != "running":
            return {"status": "blocked", "message": f"Trading state is {control['trading_state']}."}
        broker_settings = broker_auto_settings(self.settings.db_path)
        if broker_filter:
            if not broker_settings.get(broker_filter):
                return {
                    "status": "manual_required",
                    "message": f"Auto trading is disabled for {broker_filter}. Enable auto trading for {broker_filter} to allow new autonomous entries.",
                    "eligible_count": 0,
                    "skipped": [],
                }
        elif not any(broker_settings.values()):
            return {"status": "manual_required", "message": "No broker has auto trading enabled. Enable auto trading for an individual broker to allow new autonomous entries.", "eligible_count": 0, "skipped": []}
        if not self.settings.guardrails.paper_trading_only:
            return {"status": "blocked", "message": "Auto execution is disabled outside Paper Trading mode."}
        # Bounded to the longest recommendation lifetime _recommendation_freshness()
        # grants (24h for confidence < 0.75) and ordered by recency first: a proposal
        # older than that can never be anything but "Expired" below, and ordering by
        # ai_confidence DESC alone let old high-confidence proposals permanently
        # occupy the LIMIT 50 candidate slots, starving every genuinely fresh (but
        # equal-or-lower-confidence) recommendation the research pipeline generated
        # after them -- confirmed in hosted logs 2026-07-31: the same 10 expired
        # proposal_ids recurred unchanged across 40+ minutes and several research
        # cycles because they never aged out of the candidate pool.
        freshness_cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        # 2026-08-10 hosted incident: trade_audit had no broker column, so this shared
        # LIMIT-50 candidate query (used identically by both auto_execute_recommendations_
        # alpaca and _kraken) could not filter by broker in SQL at all. Kraken generates
        # candidates far more frequently than Alpaca (hourly research vs. market-hours-only),
        # and confirmed live evidence showed the 50 most recent trade_audit proposals were
        # 100% Kraken -- Alpaca's auto-execution job was fetching an all-Kraken candidate set,
        # discarding every row as a broker mismatch, and silently evaluating nothing at all,
        # every cycle, for as long as this had been true. broker is now a real column
        # (audit.py backfills existing rows and populates it going forward), so each broker's
        # job gets its own genuinely-scoped top-50 window.
        #
        # 2026-08-10 Supabase egress finding (separate, smaller issue, still fixed here): this
        # used to select payload_json (the full proposal dossier, ~11KB average per row,
        # confirmed via /database-diagnostics) for all 50 candidates up front. Every check
        # below through "already_executed" only ever needed the lightweight columns already in
        # this SELECT -- payload_json is never touched until a candidate survives all of them.
        # Now a lightweight-only first pass; payload_json is fetched in a second, targeted
        # query for just the candidates that survive it.
        broker_clause = "AND ta.broker = ?" if broker_filter else ""
        params: list[Any] = [freshness_cutoff]
        if broker_filter:
            params.append(broker_filter)
        rows = self._query_executor.rows(
            f"""
            SELECT ta.proposal_id, ta.created_at, ta.ai_confidence,
                   execution_guardrails_passed, validation_result, symbol
            FROM trade_audit ta
            WHERE ta.event_type = 'agent_proposal' AND ta.created_at >= ? {broker_clause}
            ORDER BY ta.created_at DESC, ta.ai_confidence DESC, ta.id DESC
            LIMIT 50
            """,
            tuple(params),
        )
        print(
            f"[auto-execution] broker={broker_filter} stage=candidates_loaded count={len(rows)} "
            f"elapsed={time.monotonic() - _auto_exec_t0:.1f}s",
            flush=True,
        )
        decisions: list[dict[str, Any]] = []
        seen: set[str] = set()
        skipped: list[dict[str, Any]] = []
        surviving_rows: list[Any] = []
        for row in rows:
            proposal_id = row["proposal_id"]
            if proposal_id in seen:
                continue
            seen.add(proposal_id)
            freshness = _recommendation_freshness(row["created_at"], row["ai_confidence"])
            confidence = safe_score(row["ai_confidence"]) or 0.0
            if confidence < self.settings.auto_trade.min_confidence:
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "confidence_below_85_percent",
                    "message": "Confidence is below 85%.",
                })
                continue
            if freshness["status"] == "Expired":
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "recommendation_expired",
                    "message": "Recommendation expired. Run new analysis before execution.",
                })
                continue
            if not bool(row["execution_guardrails_passed"]):
                failures = _validation_failures(row["validation_result"])
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "guardrails_not_preapproved",
                    "message": f"Guardrails failed: {_format_guardrail_failures(failures)}.",
                })
                continue
            if self._proposal_already_executed(proposal_id):
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "already_executed",
                    "message": "Already executed.",
                })
                continue
            surviving_rows.append(row)

        payloads_by_proposal_id: dict[str, str] = {}
        if surviving_rows:
            placeholders = ",".join("?" for _ in surviving_rows)
            payload_rows = self._query_executor.rows(
                f"SELECT proposal_id, payload_json FROM trade_audit WHERE event_type = 'agent_proposal' AND proposal_id IN ({placeholders})",
                tuple(row["proposal_id"] for row in surviving_rows),
            )
            payloads_by_proposal_id = {row["proposal_id"]: row["payload_json"] for row in payload_rows}
        print(
            f"[auto-execution] broker={broker_filter} stage=payloads_fetched count={len(payloads_by_proposal_id)} "
            f"elapsed={time.monotonic() - _auto_exec_t0:.1f}s",
            flush=True,
        )

        for _candidate_index, row in enumerate(surviving_rows):
            proposal_id = row["proposal_id"]
            confidence = safe_score(row["ai_confidence"]) or 0.0
            raw_payload_json = payloads_by_proposal_id.get(proposal_id)
            if raw_payload_json is None:
                # Between the first and second pass, extremely unlikely but not impossible
                # (e.g. a concurrent process touched this exact row) -- skip honestly rather
                # than crash the whole batch over one candidate.
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "payload_unavailable",
                    "message": "Proposal payload could not be re-fetched for evaluation.",
                })
                continue
            payload = json.loads(raw_payload_json)
            proposal = TradeProposal.from_dict(payload["proposal"])
            selected_broker = self.orchestrator._select_adapter(proposal)
            broker_name = selected_broker.name if selected_broker else "unknown"
            # Defensive safety net only as of 2026-08-10 -- the candidate query above now
            # filters by trade_audit.broker directly in SQL, so this should never actually
            # trigger for a normally-written row. Kept in case a legacy/edge-case row's stored
            # broker ever disagrees with what _select_adapter resolves from the full proposal
            # (AT-ED-003 Section 1 item 4's original guarantee: no ungoverned cross-broker work
            # happens for a candidate, regardless of why the mismatch occurred).
            if broker_filter and broker_name != broker_filter:
                continue
            print(
                f"[auto-execution] broker={broker_filter} stage=candidate_matched index={_candidate_index} "
                f"proposal_id={proposal_id} candidate_broker={broker_name} "
                f"elapsed={time.monotonic() - _auto_exec_t0:.1f}s",
                flush=True,
            )
            if broker_name == "alpaca" and not self.settings.has_alpaca_credentials:
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "alpaca_credentials_missing",
                    "message": "Alpaca paper credentials are required for Alpaca execution.",
                })
                continue
            if not broker_auto_trading_enabled(self.settings.db_path, broker_name, self.settings.auto_trade.broker_enabled.get(broker_name, False)):
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": f"{broker_name}_auto_trading_disabled",
                    "message": f"Auto trading is disabled for {broker_name}.",
                })
                continue
            managed_capacity = self._broker_managed_trade_capacity_lookup(broker_name)
            print(
                f"[auto-execution] broker={broker_filter} stage=managed_capacity_checked index={_candidate_index} "
                f"elapsed={time.monotonic() - _auto_exec_t0:.1f}s",
                flush=True,
            )
            if not managed_capacity["can_open"]:
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "ai_managed_open_trade_limit_reached",
                    "message": managed_capacity["message"],
                    "managed_trade_capacity": managed_capacity,
                })
                continue
            context = OrchestratorContext(
                account=self._account_context_lookup(broker_name),
                auto_trade=self._auto_config_for_broker(broker_name),
                guardrails=self.settings.guardrails,
            )
            decision = self.orchestrator.evaluate_recommendation(proposal, context, auto_execute=True)
            print(
                f"[auto-execution] broker={broker_filter} stage=recommendation_evaluated index={_candidate_index} "
                f"decision={decision.decision} elapsed={time.monotonic() - _auto_exec_t0:.1f}s",
                flush=True,
            )
            if decision.decision == "approved":
                decisions.append(decision.to_dict())
                update_broker_runtime(self.settings.db_path, broker_name, last_trade_submitted=decision.symbol, current_stage="trade_submitted")
                record_notification(
                    self.settings.db_path,
                    event_type="trade_submitted",
                    broker=broker_name,
                    symbol=decision.symbol,
                    title="Trade submitted",
                    message=f"{broker_name.title()} submitted {decision.symbol}.",
                    payload=decision.to_dict(),
                )
                self._portfolio_lookup(broker_name)
            else:
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": decision.rejection_reason or decision.decision,
                    "message": decision.rejection_reason or decision.notes or decision.decision,
                })

        print(
            f"[auto-execution] broker={broker_filter} stage=loop_completed decisions={len(decisions)} "
            f"skipped={len(skipped)} elapsed={time.monotonic() - _auto_exec_t0:.1f}s",
            flush=True,
        )
        if not decisions:
            return {
                "status": "skipped",
                "message": "No eligible recommendations over the confidence threshold passed all broker permissions and guardrails. See skipped reasons.",
                "eligible_count": 0,
                "skipped_count": len(skipped),
                "skipped": skipped[:10],
            }

        return {
            "status": "submitted",
            "mode": "Paper",
            "threshold": self.settings.auto_trade.min_confidence,
            "eligible_count": len(decisions),
            "result": decisions,
            "skipped": skipped[:10],
        }

    def auto_execute_recommendations_alpaca(self) -> dict[str, Any]:
        return self.auto_execute_recommendations(broker_filter="alpaca")

    def auto_execute_recommendations_kraken(self) -> dict[str, Any]:
        return self.auto_execute_recommendations(broker_filter="kraken")

    def monitor_managed_exits(self) -> dict[str, Any]:
        checked = []
        for item in open_managed_exits(self.settings.db_path):
            broker = item["broker"]
            adapter = self.orchestrator.adapters.get(broker)
            if broker != "kraken" or adapter is None or not hasattr(adapter, "current_prices"):
                checked.append({"managed_exit_id": item["managed_exit_id"], "status": "skipped", "reason": "broker_monitor_not_available"})
                continue
            pair = _kraken_pair(item["symbol"])
            prices = adapter.current_prices([pair])
            price = _kraken_last_price(prices, pair)
            if price is None:
                checked.append({"managed_exit_id": item["managed_exit_id"], "status": "skipped", "reason": "price_not_available"})
                continue
            side = str(item["side"]).lower()
            stop_loss = safe_float(item["stop_loss"]) or 0
            take_profit = safe_float(item["take_profit"]) or 0
            trailing_stop_pct = safe_float(item.get("trailing_stop_pct"))
            if trailing_stop_pct:
                high_water = max(safe_float(item.get("high_water_mark")) or price, price)
                low_water = min(safe_float(item.get("low_water_mark")) or price, price)
                if side == "buy":
                    stop_loss = max(stop_loss, high_water * (1 - trailing_stop_pct))
                else:
                    stop_loss = min(stop_loss, low_water * (1 + trailing_stop_pct))
                update_trailing_water_marks(
                    self.settings.db_path,
                    int(item["managed_exit_id"]),
                    high_water_mark=high_water,
                    low_water_mark=low_water,
                )
            should_exit = False
            reason = None
            if side == "buy" and price <= stop_loss:
                should_exit = True
                reason = "stop_loss_triggered"
            elif side == "buy" and price >= take_profit:
                should_exit = True
                reason = "take_profit_triggered"
            elif side == "sell" and price >= stop_loss:
                should_exit = True
                reason = "stop_loss_triggered"
            elif side == "sell" and price <= take_profit:
                should_exit = True
                reason = "take_profit_triggered"
            if not should_exit:
                checked.append({"managed_exit_id": item["managed_exit_id"], "status": "open", "price": price})
                continue
            exit_side = "sell" if side == "buy" else "buy"
            client_order_id = f"exit-{item['managed_exit_id']}"
            order_request = OrderRequest(
                symbol=item["symbol"],
                side=exit_side,
                quantity=float(item["quantity"]),
                asset_type="crypto",
                exchange="KRAKEN",
                stop_loss=0,
                take_profit=0,
                notional_amount=price * float(item["quantity"]),
                client_order_id=client_order_id,
                quote_currency="GBP",
                broker_pair=pair,
            )
            lock_acquired = acquire_order_intent_lock(
                self.settings.db_path,
                broker=broker,
                client_order_id=client_order_id,
                symbol=item["symbol"],
                side=exit_side,
                notional=order_request.notional_amount,
            )
            if not lock_acquired:
                checked.append(
                    {
                        "managed_exit_id": item["managed_exit_id"],
                        "status": "duplicate_exit_intent",
                        "reason": "An exit order intent for this managed position is already locked; skipping to avoid a duplicate broker submission.",
                        "price": price,
                    }
                )
                continue
            result = adapter.place_exit_order(order_request)
            complete_order_intent_lock(
                self.settings.db_path,
                broker=broker,
                client_order_id=client_order_id,
                status=str(result.get("status", "unknown")),
                result_order_id=str(result.get("id") or result.get("order_id") or "") or None,
                notes=json_safe(result),
            )
            if result.get("status") in {"accepted", "submitted"}:
                entry_payload = _json_loads_safe(item.get("payload_json")) or {}
                proposal_id = entry_payload.get("proposal_id")
                exit_order_id = str(result.get("id") or result.get("order_id") or "")
                mark_managed_exit_submitted(
                    self.settings.db_path,
                    int(item["managed_exit_id"]),
                    exit_order_id=exit_order_id,
                    exit_reason=reason or "exit_triggered",
                    payload={"price": price, "order": result},
                )
                register_kraken_order_ownership(
                    self.settings.db_path,
                    broker_order_id=exit_order_id,
                    logical_trade_id=proposal_id or f"kraken-managed-exit:{item['managed_exit_id']}",
                    proposal_id=proposal_id,
                    managed_exit_id=int(item["managed_exit_id"]),
                    order_role="exit",
                    symbol=item["symbol"],
                    side=exit_side,
                    source="managed_exit_monitor",
                )
                record_notification(
                    self.settings.db_path,
                    event_type=reason or "trade_exited",
                    broker=broker,
                    symbol=item["symbol"],
                    title=(reason or "Trade exited").replace("_", " ").title(),
                    message=f"{broker.title()} {item['symbol']} exit submitted at {price}.",
                    payload={"managed_exit": dict(item), "order": result, "price": price},
                )
                checked.append({"managed_exit_id": item["managed_exit_id"], "status": "exit_submitted", "reason": reason, "price": price})
            else:
                # Broker synchronously and definitively declined the order (no ambiguity
                # about whether it reached the exchange) -- safe to release the intent
                # lock so the next cycle can retry instead of being permanently blocked.
                release_order_intent_lock(self.settings.db_path, broker=broker, client_order_id=client_order_id)
                checked.append({"managed_exit_id": item["managed_exit_id"], "status": "exit_failed", "reason": result.get("reason"), "price": price})
        return {"status": "checked", "managed_exits": checked}

    def force_managed_exit(self, body: dict[str, Any]) -> dict[str, Any]:
        managed_exit_id = _int_or_default(body.get("managed_exit_id"), 0)
        if managed_exit_id <= 0:
            return {"status": "rejected", "message": "managed_exit_id is required."}
        matches = [item for item in open_managed_exits(self.settings.db_path) if int(item["managed_exit_id"]) == managed_exit_id]
        if not matches:
            return {"status": "rejected", "message": "Open AI-managed trade was not found. Personal/manual holdings are not force-exited by this command."}
        item = matches[0]
        broker = item["broker"]
        adapter = self.orchestrator.adapters.get(broker)
        if broker != "kraken" or adapter is None or not hasattr(adapter, "current_prices"):
            return {"status": "rejected", "message": "Force exit is currently available only for AI-managed Kraken trades."}
        pair = _kraken_pair(item["symbol"])
        price = _kraken_last_price(adapter.current_prices([pair]), pair)
        if price is None:
            return {"status": "rejected", "message": "Current Kraken price is not available, so AI Trader cannot calculate a controlled exit order."}
        entry_side = str(item["side"]).lower()
        exit_side = "sell" if entry_side == "buy" else "buy"
        quantity = float(item["quantity"])
        # Shares the same lock key as monitor_managed_exits' automatic trigger for this
        # managed_exit_id, so a founder-forced exit and an automatic stop-loss/take-profit
        # exit can never both submit an order for the same position.
        client_order_id = f"exit-{managed_exit_id}"
        order_request = OrderRequest(
            symbol=item["symbol"],
            side=exit_side,
            quantity=quantity,
            asset_type="crypto",
            exchange="KRAKEN",
            stop_loss=0,
            take_profit=0,
            notional_amount=price * quantity,
            client_order_id=client_order_id,
            quote_currency="GBP",
            broker_pair=pair,
        )
        lock_acquired = acquire_order_intent_lock(
            self.settings.db_path,
            broker=broker,
            client_order_id=client_order_id,
            symbol=item["symbol"],
            side=exit_side,
            notional=order_request.notional_amount,
        )
        if not lock_acquired:
            return {
                "status": "rejected",
                "message": "An exit order intent for this managed position is already locked; a previous forced exit may still be in flight or was already submitted. Refusing to submit a duplicate.",
            }
        result = adapter.place_exit_order(order_request)
        complete_order_intent_lock(
            self.settings.db_path,
            broker=broker,
            client_order_id=client_order_id,
            status=str(result.get("status", "unknown")),
            result_order_id=str(result.get("id") or result.get("order_id") or "") or None,
            notes=json_safe(result),
        )
        if result.get("status") not in {"accepted", "submitted"}:
            release_order_intent_lock(self.settings.db_path, broker=broker, client_order_id=client_order_id)
            return {"status": "rejected", "message": f"Kraken exit order was not accepted: {result.get('reason') or result.get('status')}", "order": result}
        entry_payload = _json_loads_safe(item.get("payload_json")) or {}
        proposal_id = entry_payload.get("proposal_id")
        exit_order_id = str(result.get("id") or result.get("order_id") or "")
        mark_managed_exit_submitted(
            self.settings.db_path,
            managed_exit_id,
            exit_order_id=exit_order_id,
            exit_reason="founder_forced_exit",
            payload={"price": price, "order": result, "forced_by": "founder"},
        )
        register_kraken_order_ownership(
            self.settings.db_path,
            broker_order_id=exit_order_id,
            logical_trade_id=proposal_id or f"kraken-managed-exit:{managed_exit_id}",
            proposal_id=proposal_id,
            managed_exit_id=managed_exit_id,
            order_role="exit",
            symbol=item["symbol"],
            side=exit_side,
            source="founder_forced_exit",
        )
        record_notification(
            self.settings.db_path,
            event_type="founder_forced_exit",
            broker=broker,
            symbol=item["symbol"],
            title="Founder Forced Exit",
            message=f"Kraken {item['symbol']} exit submitted at {price}.",
            payload={"managed_exit": dict(item), "order": result, "price": price},
        )
        return {"status": "submitted", "message": f"Exit submitted for {item['symbol']} at approximately {price}.", "order": result}

    def _proposal_already_executed(self, proposal_id: str) -> bool:
        return bool(
            self._query_executor.scalar(
                """
                SELECT COUNT(*)
                FROM trade_audit
                WHERE proposal_id = ? AND event_type = 'execution_approved'
                """,
                (proposal_id,),
            )
        )
