from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote

from ..alpaca import AlpacaPaperClient
from ..broker_adapters import _kraken_last_price, _kraken_pair
from ..config import Settings
from ..database import selected_backend
from ..multi_broker import (
    broker_auto_settings,
    latest_broker_trades,
    open_managed_exits,
    record_broker_trade_history,
    record_notification,
    release_order_intent_lock,
    set_broker_auto_trading,
    today_runtime_counts,
    update_broker_runtime,
)
from ..kraken_reconciliation import kraken_capital_ledger_summary, reconciliation_control, replay_kraken_evidence
from ..operational import display_value, safe_float, record_portfolio_snapshot
from ..orchestrator import InvestmentOrchestrator
from ..persistence.query_executor import QueryExecutor
from ..production_evidence import record_broker_snapshot, record_trade_evidence_batch, refresh_founder_evidence_snapshots
from ..sprint6 import normalize_broker_events, upsert_incident

logger = logging.getLogger("ai_trader.api")

BROKER_AUTO_TRADING_ENV_VARS = {
    "alpaca": "ALPACA_AUTO_TRADING",
    "kraken": "KRAKEN_AUTO_TRADING",
    "coinbase": "COINBASE_AUTO_TRADING",
    "binance": "BINANCE_AUTO_TRADING",
    "interactive_brokers": "IBKR_AUTO_TRADING",
}


def _recent_unique_broker_events(
    orders: list[dict[str, Any]],
    history: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Keep current orders first, then bounded recent history, without replays."""
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for event in [*orders, *history]:
        if not isinstance(event, dict):
            continue
        identity = (
            str(event.get("id") or event.get("order_id") or event.get("ordertxid") or event.get("txid") or event.get("trade_id") or ""),
            str(event.get("status") or event.get("type") or ""),
            str(
                event.get("updated_at")
                or event.get("transaction_time")
                or event.get("filled_at")
                or event.get("closed_at")
                or event.get("closetm")
                or event.get("created_at")
                or event.get("opentm")
                or event.get("time")
                or ""
            ),
            str(event.get("filled_qty") or event.get("cum_qty") or event.get("qty") or event.get("vol") or ""),
        )
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(event)
        if len(selected) >= max(1, int(limit)):
            break
    return selected


# Phase 6a (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md): these four
# small pure helpers are also used by parts of api/__init__.py that are out of this phase's
# scope (_account_context_for_broker -- the Kraken capital-isolation logic itself -- and the
# Ask AI Trader feature), so they cannot be imported without a circular import. Already
# duplicated in reporting_service.py/founder_experience_service.py/research_service.py for the
# same reason. Duplicated verbatim again here per the established convention.
def _broker_label(broker: str) -> str:
    labels = {
        "alpaca": "Alpaca",
        "kraken": "Kraken",
        "coinbase": "Coinbase",
        "binance": "Binance",
        "interactive_brokers": "Interactive Brokers",
    }
    return labels.get(broker.lower(), broker.replace("_", " ").title())


def _estimated_in_positions(portfolio_value: Any, cash: Any) -> float | None:
    portfolio_number = safe_float(portfolio_value)
    cash_number = safe_float(cash)
    if portfolio_number is None or cash_number is None:
        return None
    return portfolio_number - cash_number


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


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


# Phase 6a: exclusive to this cluster -- moved fully rather than duplicated, since nothing
# else in api/__init__.py used them after broker_panels/_broker_trade_rows/etc. moved (verified
# by grep before removing their originals).
def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _bool_env(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(key: str, default: str) -> list[str]:
    value = os.getenv(key, default)
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _broker_block_reason(broker: str, auto_enabled: bool, permissions: dict[str, Any] | None) -> str | None:
    """Plain-language reason new entries are blocked, or None when nothing blocks them.

    Mirrors the exact gates _broker_trading_permissions() already evaluates so the
    Command screen and broker panels never show "Disabled" for a broker that is
    actually enabled but blocked further down the governance chain (AT-ED-003
    Section 3).
    """
    if permissions is None:
        return "Trading permission data unavailable."
    if not auto_enabled:
        return "Auto trading is disabled by the Founder for this broker."
    key = broker.lower()
    if key == "alpaca":
        if not permissions.get("trading_enabled"):
            return "Alpaca paper credentials are not configured."
        return None
    if not permissions.get("trading_enabled"):
        return f"{_broker_label(broker)} trading is disabled by environment configuration."
    if permissions.get("reconciliation_hold_active"):
        return permissions.get("reconciliation_hold_reason") or "New entries are paused pending reconciliation verification."
    if not permissions.get("live_trading_approved"):
        return "Live trading has not been approved for this broker."
    if not permissions.get("submit_real_orders"):
        return "Real order submission is not yet enabled for this broker."
    remaining = permissions.get("remaining_ai_trade_slots")
    if isinstance(remaining, int) and remaining <= 0:
        return "AI-managed open-trade limit reached for this broker."
    if permissions.get("can_submit_real_orders"):
        return None
    return "Blocked by broker trading permissions."


def _kraken_price_hints_from_panel(panel: dict[str, Any]) -> dict[str, float]:
    """Extract a symbol->GBP-price map from a Kraken portfolio panel's wallet balance
    conversion, already computed during this same broker-snapshot cycle by
    _kraken_balance_summary(). Reusing these prices lets the AI capital ledger value
    open positions without a second live Kraken pricing call for the same market data
    (AT-ED-003 corrective session, Part 1).
    """
    balance_summary = panel.get("balance_summary") if isinstance(panel, dict) else None
    if not isinstance(balance_summary, dict):
        return {}
    hints: dict[str, float] = {}
    for row in balance_summary.get("converted_assets") or []:
        if not isinstance(row, dict):
            continue
        symbol = row.get("normalized_asset")
        price = row.get("price_gbp")
        if symbol and price is not None:
            hints[str(symbol).upper()] = float(price)
    return hints


def _broker_trade_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload_json")
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _broker_trade_symbol(row: dict[str, Any]) -> str | None:
    payload = _broker_trade_payload(row)
    value = row.get("symbol") or payload.get("symbol") or payload.get("pair")
    return str(value).upper() if value else None


def _latest_trade(orders: list[dict[str, Any]], activities: list[dict[str, Any]]) -> dict[str, Any] | None:
    combined = []
    for item in activities:
        combined.append({"type": "fill", **item, "sort_time": item.get("transaction_time") or item.get("date")})
    for item in orders:
        combined.append({"type": "order", **item, "sort_time": item.get("submitted_at") or item.get("updated_at") or item.get("created_at")})
    combined.sort(key=lambda item: item.get("sort_time") or "", reverse=True)
    return combined[0] if combined else None


def _amount_traded_today(activities: list[dict[str, Any]]) -> float:
    today = date.today().isoformat()
    amount = 0.0
    for item in activities:
        timestamp = str(item.get("transaction_time") or item.get("date") or "")
        if not timestamp.startswith(today):
            continue
        qty = safe_float(item.get("qty")) or 0.0
        price = safe_float(item.get("price")) or 0.0
        amount += abs(qty * price)
    return amount


class BrokerService:
    """Broker panels, activity polling, production snapshots, and reconciliation
    presentation (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md Phase 6a),
    moved out of LocalApiService.

    Two narrow injected dependencies, not a reference to LocalApiService:
    - `broker_factory` constructs an AlpacaPaperClient; still needed elsewhere in
      api/__init__.py too (same pattern research_service.py already established).
    - `kraken_balance_summary_lookup` is `_kraken_balance_summary` -- the Kraken wallet
      valuation/pricing pipeline (`_kraken_gbp_cash`/`_kraken_asset_gbp_price`/
      `_kraken_usd_to_gbp`/`_kraken_pair_price`/`_kraken_asset_symbol`/
      `_kraken_trading_allocation_gbp`). This entire pricing subsystem was deliberately
      NOT moved or duplicated: `_kraken_trading_allocation_gbp` is the same safety-critical
      Kraken AI capital-sleeve isolation function Phase 5 already established must keep
      exactly one implementation anywhere in the codebase (it is also called directly by
      `_account_context_for_broker`, which stays in api/__init__.py). Injecting the whole
      `_kraken_balance_summary` pipeline as a single Callable, rather than partially
      extracting it, keeps that safety-critical pricing/allocation code completely
      untouched by this phase.

    Both are wired as call-time lambdas in LocalApiService.__init__, not captured bound
    methods, matching the live-reading pattern Phase 4/5 established for dependencies that
    tests may monkeypatch on the instance after construction.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        orchestrator: InvestmentOrchestrator,
        query_executor: QueryExecutor,
        broker_factory: Callable[[], AlpacaPaperClient],
        kraken_balance_summary_lookup: Callable[[Any, Any], dict[str, Any]],
    ) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self._query_executor = query_executor
        self._broker_factory = broker_factory
        self._kraken_balance_summary_lookup = kraken_balance_summary_lookup

    def _render_api_json(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.settings.render_api_key or not self.settings.render_service_id:
            return {
                "status": "skipped",
                "configured": False,
                "message": "RENDER_API_KEY and RENDER_SERVICE_ID are required to persist this setting in Render.",
            }
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib_request.Request(
            f"https://api.render.com/v1{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.settings.render_api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
                return {"status": "ok", "configured": True, "http_status": response.status, "payload": payload}
        except urllib_error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"raw": raw}
            return {"status": "failed", "configured": True, "http_status": exc.code, "message": str(exc), "payload": payload}
        except Exception as exc:  # noqa: BLE001 - Render sync failure should not block the local broker toggle
            return {"status": "failed", "configured": True, "message": str(exc)}

    def _sync_broker_auto_trading_to_render(self, broker: str, enabled: bool) -> dict[str, Any]:
        env_var = BROKER_AUTO_TRADING_ENV_VARS.get(broker)
        if not env_var:
            return {"status": "skipped", "configured": False, "message": f"No Render env var mapping exists for broker {broker}."}
        service_id = self.settings.render_service_id
        if not self.settings.render_api_key or not service_id:
            return {
                "status": "skipped",
                "configured": False,
                "env_var": env_var,
                "message": "Render sync skipped. Set RENDER_API_KEY and RENDER_SERVICE_ID in Render to persist broker auto-trading toggles across deploys.",
            }

        encoded_service_id = quote(service_id, safe="")
        encoded_env_var = quote(env_var, safe="")
        update = self._render_api_json(
            "PUT",
            f"/services/{encoded_service_id}/env-vars/{encoded_env_var}",
            {"value": "true" if enabled else "false"},
        )
        if update.get("status") != "ok":
            return {"status": "failed", "configured": True, "env_var": env_var, "update": update, "message": f"Render env var {env_var} was not updated."}

        deploy = self._render_api_json(
            "POST",
            f"/services/{encoded_service_id}/deploys",
            {"deployMode": "deploy_only"},
        )
        if deploy.get("status") != "ok":
            return {
                "status": "env_updated_deploy_failed",
                "configured": True,
                "env_var": env_var,
                "value": enabled,
                "update": update,
                "deploy": deploy,
                "message": f"Render env var {env_var} was updated, but deployment was not triggered.",
            }

        return {
            "status": "synced",
            "configured": True,
            "env_var": env_var,
            "value": enabled,
            "deploy_http_status": deploy.get("http_status"),
            "message": f"Render env var {env_var} was updated and a deploy was triggered.",
        }

    def set_broker_auto_trading(self, body: dict[str, Any]) -> dict[str, Any]:
        broker = str(body.get("broker") or "").lower()
        if not broker:
            return {"status": "rejected", "message": "broker is required."}
        enabled = bool(body.get("enabled"))
        result = set_broker_auto_trading(self.settings.db_path, broker, enabled)
        render_sync = self._sync_broker_auto_trading_to_render(broker, enabled)
        update_broker_runtime(
            self.settings.db_path,
            broker,
            research_status="running" if enabled else "idle",
            current_stage="auto_trading_enabled" if enabled else "auto_trading_disabled",
            research_freshness="Fresh" if enabled else None,
        )
        record_notification(
            self.settings.db_path,
            event_type="render_env_sync",
            broker=broker,
            symbol=None,
            title=f"{broker.title()} Render auto-trading sync",
            message=render_sync.get("message") or render_sync.get("status") or "Render sync checked.",
            payload={"broker": broker, "enabled": enabled, "render_sync": render_sync},
        )
        return {"status": "updated", **result, "render_sync": render_sync}

    def poll_broker_activity(self, broker_filter: str | None = None) -> dict[str, Any]:
        """Continuously reconciles broker-reported order/trade status into SQLite and
        fires trade_filled/trade_closed notifications - this is what gives Alpaca (which
        has no other fill-confirmation loop) and Kraken order-level monitoring, distinct
        from the price-driven managed-exit check in monitor_managed_exits.

        broker_filter restricts this cycle to one broker so Alpaca and Kraken can be
        scheduled, timed out, and retried independently (AT-ED-003 Section 1)."""
        results: dict[str, Any] = {}
        for broker_name, adapter in self.orchestrator.adapters.items():
            if broker_filter and broker_name != broker_filter:
                continue
            if not getattr(adapter, "configured", True):
                continue
            try:
                orders = adapter.get_orders()
                history = adapter.get_trade_history()
            except Exception:
                logger.exception("Failed to poll %s order/trade activity.", broker_name)
                upsert_incident(
                    self.settings.db_path,
                    incident_key=f"broker-poll:{broker_name}",
                    severity="warning",
                    component="broker",
                    affected_entity=broker_name,
                    explanation=f"{broker_name.title()} broker polling failed.",
                    recommended_action="Check broker credentials, network availability, and adapter logs.",
                    payload={"broker": broker_name},
                )
                continue
            events = _recent_unique_broker_events(list(orders), list(history), limit=100)
            new_rows = record_broker_trade_history(self.settings.db_path, broker_name, events)
            # Broker history is the change detector. Persist production evidence
            # only for new or changed rows; rewriting the broker's full recent
            # history on every poll caused hundreds of Postgres transactions and
            # allowed one broker cycle to exceed the worker timeout. All new rows
            # for this broker share one connection/transaction instead of one per
            # event (AT-ED-003 Section 1 item 5).
            evidence_written = record_trade_evidence_batch(self.settings.db_path, broker=broker_name, events=new_rows)
            if broker_name == "kraken":
                reconciliation = replay_kraken_evidence(
                    self.settings.db_path,
                    events=new_rows,
                    source="poll_broker_activity",
                )
            else:
                reconciliation = normalize_broker_events(
                    self.settings.db_path,
                    broker=broker_name,
                    # Stable history rows are already persisted. Canonical work is
                    # only required for new or changed broker evidence.
                    events=new_rows,
                    source_endpoint="poll_broker_activity",
                )
            terminal_statuses = {"filled", "closed", "cancelled", "canceled", "rejected"}
            for row in new_rows:
                status = str(row.get("status") or "").lower()
                if status not in terminal_statuses:
                    continue
                record_type = str(row.get("kraken_record_type") or "")
                if broker_name == "kraken" and record_type == "closed_order":
                    event_type = "broker_order_completed"
                    title = "Broker Order Completed"
                    message = (
                        f"Kraken order for {row.get('symbol') or row.get('pair') or 'unknown'} "
                        f"is no longer open ({status}). This does not by itself mean the investment was sold."
                    )
                else:
                    event_type = "trade_filled" if status == "filled" else "trade_closed"
                    title = event_type.replace("_", " ").title()
                    message = f"{broker_name.title()} order for {row.get('symbol') or row.get('pair') or 'unknown'} is now {status}."
                symbol = row.get("symbol") or row.get("pair") or "unknown"
                record_notification(
                    self.settings.db_path,
                    event_type=event_type,
                    broker=broker_name,
                    symbol=symbol,
                    title=title,
                    message=message,
                    payload=row,
                )
            results[broker_name] = {
                "orders": len(orders),
                "history": len(history),
                "events_processed": len(events),
                "new_records": len(new_rows),
                "evidence_rows_written": evidence_written,
                "reconciliation": reconciliation,
            }
            print(
                f"[broker-poll:{broker_name}] orders={len(orders)} history={len(history)} "
                f"new_records={len(new_rows)} evidence_rows_written={evidence_written}",
                flush=True,
            )
        return results

    def poll_broker_activity_alpaca(self) -> dict[str, Any]:
        return self.poll_broker_activity(broker_filter="alpaca")

    def poll_broker_activity_kraken(self) -> dict[str, Any]:
        return self.poll_broker_activity(broker_filter="kraken")

    def capture_production_broker_snapshots(self) -> dict[str, Any]:
        """Capture Founder-facing broker truth in the shared production datastore.

        Stage timing is logged for each major phase (portfolio fetch, trading
        permissions, broker snapshot persistence, founder evidence generation) so a
        regression in any one stage is visible directly in the worker log rather
        than only as a total job timeout (AT-ED-003 corrective session, Part 1).
        """
        results: dict[str, Any] = {}
        broker_names = ("alpaca", "kraken")
        stage_start = time.monotonic()

        def fetch(broker_name: str) -> Any:
            return self._live_alpaca_portfolio() if broker_name == "alpaca" else self._exchange_portfolio(broker_name)

        panels: dict[str, Any] = {}
        # Alpaca and Kraken are independent brokers with no shared state or data
        # dependency between them; fetching their portfolios sequentially was a
        # confirmed dominant cost of the evidence-snapshot job's timeouts (up to
        # ~9 sequential broker HTTP round-trips -- see
        # PRODUCTION_TIMEOUT_ROOT_CAUSE_ANALYSIS.md). Running them concurrently
        # bounds the job's wall-clock time to the slower of the two brokers
        # instead of the sum of both. Only done against Postgres: SQLite (local
        # dev/tests) has no busy-timeout configured, so concurrent writers to
        # the same file can raise "database is locked" -- a real production
        # win is not worth introducing flakiness into the local/test backend.
        if selected_backend() == "postgres":
            with ThreadPoolExecutor(max_workers=len(broker_names)) as pool:
                futures = {broker_name: pool.submit(fetch, broker_name) for broker_name in broker_names}
                for broker_name, future in futures.items():
                    try:
                        panels[broker_name] = ("ok", future.result())
                    except Exception as exc:  # noqa: BLE001 - persist failure evidence for the Founder
                        panels[broker_name] = ("error", exc)
        else:
            for broker_name in broker_names:
                try:
                    panels[broker_name] = ("ok", fetch(broker_name))
                except Exception as exc:  # noqa: BLE001 - persist failure evidence for the Founder
                    panels[broker_name] = ("error", exc)
        print(f"[evidence-snapshot] stage=portfolio_fetch status=completed elapsed={time.monotonic() - stage_start:.1f}s", flush=True)

        # The Command screen and broker panels must show the same auto-trading
        # truth. That truth is the DB-backed setting plus the same governance
        # computation _broker_trading_permissions() already produces for the
        # live /brokers endpoint -- captured here so it travels with the
        # persisted snapshot the Founder-facing evidence payload actually reads
        # (AT-ED-003 Section 3). Kraken's ledger valuation reuses the prices the
        # portfolio fetch above already obtained (live_pricing disabled here) so
        # capturing governance never adds a second live Kraken API round trip to
        # this job -- that redundant call was the confirmed cause of this job's
        # 180s timeout regression (AT-ED-003 corrective session, Part 1).
        permissions_stage_start = time.monotonic()
        broker_auto_enabled = broker_auto_settings(self.settings.db_path)
        governance_by_broker: dict[str, dict[str, Any]] = {}
        for broker_name in broker_names:
            status, payload = panels[broker_name]
            auto_enabled = bool(broker_auto_enabled.get(broker_name, False))
            broker_stage_start = time.monotonic()
            print(f"[evidence-snapshot] stage=trading_permissions broker={broker_name} status=started", flush=True)
            price_hints = _kraken_price_hints_from_panel(payload) if broker_name == "kraken" and status == "ok" else None
            ledger_stage_start = time.monotonic()
            try:
                permissions = self._broker_trading_permissions(
                    broker_name,
                    auto_enabled,
                    kraken_price_hints=price_hints,
                    allow_live_kraken_pricing=False,
                )
            except Exception:
                logger.exception("Failed to compute %s trading permissions for broker snapshot.", broker_name)
                permissions = None
            if broker_name == "kraken":
                print(f"[evidence-snapshot] stage=capital_ledger broker=kraken status=completed elapsed={time.monotonic() - ledger_stage_start:.1f}s priced_from_hints={bool(price_hints)}", flush=True)
            governance_by_broker[broker_name] = {
                "auto_trading_enabled": auto_enabled,
                "auto_trading_status": "Enabled" if auto_enabled else "Disabled",
                "trading_permissions": permissions,
                "block_reason": _broker_block_reason(broker_name, auto_enabled, permissions),
            }
            print(f"[evidence-snapshot] stage=trading_permissions broker={broker_name} status=completed elapsed={time.monotonic() - broker_stage_start:.1f}s", flush=True)
        print(f"[evidence-snapshot] stage=trading_permissions status=completed elapsed={time.monotonic() - permissions_stage_start:.1f}s", flush=True)

        persistence_stage_start = time.monotonic()
        for broker_name in broker_names:
            status, payload = panels[broker_name]
            governance = governance_by_broker[broker_name]
            if status == "ok":
                panel = {**payload, "broker": broker_name, **governance}
                record_broker_snapshot(self.settings.db_path, panel)
                # Broker polling owns order/trade evidence. Snapshot capture owns
                # account, balance, and position truth only. Keeping ownership
                # separate prevents duplicate writes and preserves one clear
                # reconciliation path.
                results[broker_name] = {
                    "status": "captured",
                    "connection_status": panel.get("connection_status"),
                    "portfolio_value": panel.get("portfolio_value"),
                    "open_positions": panel.get("open_positions_summary"),
                    "auto_trading_enabled": governance["auto_trading_enabled"],
                    "block_reason": governance["block_reason"],
                }
            else:
                exc = payload
                logger.exception("Failed to capture %s production broker snapshot.", broker_name, exc_info=exc)
                record_broker_snapshot(
                    self.settings.db_path,
                    {
                        "broker": broker_name,
                        "connection_status": "Connection error",
                        "error": str(exc),
                        **governance,
                        "source": "broker snapshot worker",
                    },
                )
                results[broker_name] = {"status": "failed", "reason": str(exc)}
        print(f"[evidence-snapshot] stage=broker_snapshot_persistence status=completed elapsed={time.monotonic() - persistence_stage_start:.1f}s", flush=True)

        founder_stage_start = time.monotonic()
        results["founder_evidence"] = refresh_founder_evidence_snapshots(self.settings.db_path)
        print(f"[evidence-snapshot] stage=founder_evidence_generation status=completed elapsed={time.monotonic() - founder_stage_start:.1f}s", flush=True)
        print(f"[evidence-snapshot] stage=total status=completed elapsed={time.monotonic() - stage_start:.1f}s", flush=True)
        return results

    def broker_panels(self) -> list[dict[str, Any]]:
        panels = []
        settings = broker_auto_settings(self.settings.db_path)
        for broker in ["alpaca", "kraken", "coinbase", "binance", "interactive_brokers"]:
            runtime = {**update_broker_runtime(self.settings.db_path, broker).to_dict()}
            portfolio = self._exchange_portfolio(broker) if broker != "alpaca" else self._alpaca_panel_portfolio()
            counts = today_runtime_counts(self.settings.db_path, broker)
            auto_enabled = settings.get(broker, False)
            panels.append({
                "broker": broker,
                "label": _broker_label(broker),
                "connection_status": portfolio.get("connection_status") or runtime.get("connection_status"),
                "portfolio_value": portfolio.get("portfolio_value"),
                "cash_available": portfolio.get("cash_available"),
                "estimated_in_positions": _estimated_in_positions(portfolio.get("portfolio_value"), portfolio.get("cash_available")),
                "buying_power": portfolio.get("buying_power"),
                "open_positions": portfolio.get("open_positions_summary"),
                "todays_pnl": portfolio.get("todays_pnl"),
                "week_pnl": portfolio.get("week_pnl"),
                "month_pnl": portfolio.get("month_pnl"),
                "trades_today": counts["trades_today"],
                "research_status": runtime.get("research_status"),
                "due_diligence_status": runtime.get("due_diligence_status"),
                "auto_trading_enabled": auto_enabled,
                "trading_permissions": self._broker_trading_permissions(broker, auto_enabled),
                "current_asset": runtime.get("current_asset"),
                "current_stage": runtime.get("current_stage"),
                "research_queue": runtime.get("research_queue"),
                "assets_reviewed_today": runtime.get("assets_reviewed_today"),
                "research_cycles_today": runtime.get("research_cycles_today"),
                "last_scan": runtime.get("last_scan"),
                "next_scan": runtime.get("next_scan"),
                "research_freshness": runtime.get("research_freshness"),
                "last_recommendation": runtime.get("last_recommendation"),
                "last_trade_submitted": runtime.get("last_trade_submitted"),
                "trade_history": self._broker_trade_rows(broker),
                "managed_exits": self._managed_exit_rows(broker),
                "source": portfolio.get("source"),
            })
        return panels

    def _broker_trade_rows(self, broker: str) -> list[dict[str, Any]]:
        rows = latest_broker_trades(self.settings.db_path, broker, limit=10)
        if broker != "kraken":
            return rows
        adapter = self.orchestrator.adapters.get("kraken")
        if adapter is None or not hasattr(adapter, "current_prices"):
            return rows
        enriched: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            pair = _broker_trade_symbol(item)
            if pair:
                try:
                    item["current_price"] = _kraken_last_price(adapter.current_prices([pair]), pair)
                except Exception as exc:
                    item["current_price_error"] = str(exc)
            enriched.append(item)
        return enriched

    def _managed_exit_rows(self, broker: str) -> list[dict[str, Any]]:
        rows = open_managed_exits(self.settings.db_path, broker)
        if broker != "kraken":
            return rows
        adapter = self.orchestrator.adapters.get("kraken")
        if adapter is None or not hasattr(adapter, "current_prices"):
            return rows
        enriched: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            pair = _kraken_pair(item["symbol"])
            try:
                item["current_price"] = _kraken_last_price(adapter.current_prices([pair]), pair)
                item["broker_pair"] = pair
            except Exception as exc:
                item["current_price_error"] = str(exc)
            enriched.append(item)
        return enriched

    def _broker_trading_permissions(
        self,
        broker: str,
        auto_enabled: bool,
        *,
        kraken_price_hints: dict[str, float] | None = None,
        allow_live_kraken_pricing: bool = True,
    ) -> dict[str, Any]:
        key = broker.lower()
        if key == "kraken":
            live_approved = _bool_env("KRAKEN_LIVE_TRADING_APPROVED", False)
            submit_real_orders = _bool_env("KRAKEN_SUBMIT_REAL_ORDERS", False)
            trading_enabled = _bool_env("KRAKEN_TRADING_ENABLED", False)
            allowed_pairs = _csv_env("KRAKEN_ALLOWED_PAIRS", "XBTGBP,ETHGBP,SOLGBP")
            max_open_trades = _int_env("KRAKEN_MAX_OPEN_TRADES", 1)
            ai_managed_open_trades = self._ai_managed_open_trade_count(key)
            buy_only_entries = _bool_env("KRAKEN_BUY_ONLY_ENTRIES", True)
            reconciliation = reconciliation_control(self.settings.db_path)
            ledger = self._kraken_ai_capital_ledger(
                price_hints=kraken_price_hints,
                allow_live_pricing=allow_live_kraken_pricing,
            )
            hold_active = bool(reconciliation.get("hold_new_entries"))
            can_submit_real_orders = bool(
                auto_enabled
                and trading_enabled
                and live_approved
                and submit_real_orders
                and not hold_active
                and ai_managed_open_trades < max_open_trades
            )
            return {
                "broker": key,
                "status": "Real Kraken orders enabled" if can_submit_real_orders else "Real Kraken orders blocked or dry-run only",
                "auto_trading_enabled": auto_enabled,
                "trading_enabled": trading_enabled,
                "live_trading_approved": live_approved,
                "submit_real_orders": submit_real_orders,
                "can_submit_real_orders": can_submit_real_orders,
                "reconciliation_hold_active": hold_active,
                "reconciliation_status": reconciliation.get("status"),
                "reconciliation_hold_reason": reconciliation.get("hold_reason"),
                "ai_capital_ledger": ledger,
                "trading_allocation_gbp": _float_env("KRAKEN_TRADING_ALLOCATION_GBP", 100.0),
                "max_order_gbp": _float_env("KRAKEN_MAX_ORDER_GBP", 5.0),
                "min_order_gbp": _float_env("KRAKEN_MIN_ORDER_GBP", 1.0),
                "max_open_trades": max_open_trades,
                "ai_managed_open_trades": ai_managed_open_trades,
                "remaining_ai_trade_slots": max(0, max_open_trades - ai_managed_open_trades),
                "buy_only_entries": buy_only_entries,
                "allowed_pairs": allowed_pairs,
                "notes": [
                    "New Kraken entries are capped by trading allocation, max order size, allowed pairs, and AI Trader-managed open-trade limit.",
                    "Existing Kraken holdings are reported separately and do not count against the AI Trader-managed open-trade limit.",
                    "Existing managed exits remain monitored even when new auto trading is disabled.",
                    "Kraken entry reconciliation may temporarily pause new entries without disabling managed exits.",
                    "The AI capital ledger excludes all personal and pre-existing Kraken holdings.",
                    "Real orders require Auto Trading, KRAKEN_TRADING_ENABLED, KRAKEN_LIVE_TRADING_APPROVED, and KRAKEN_SUBMIT_REAL_ORDERS.",
                ],
            }
        if key == "alpaca":
            paper_only = _bool_env("PAPER_TRADING_ONLY", True)
            return {
                "broker": key,
                "status": "Alpaca paper trading enabled" if self.settings.has_alpaca_credentials else "Alpaca credentials missing",
                "auto_trading_enabled": auto_enabled,
                "trading_enabled": self.settings.has_alpaca_credentials,
                "live_trading_approved": False,
                "submit_real_orders": False,
                "can_submit_real_orders": False,
                "paper_only": paper_only,
                "max_order_gbp": _float_env("MAX_AUTO_TRADE_AMOUNT", 25.0),
                "max_open_trades": self.settings.guardrails.max_open_positions,
                "allowed_pairs": [],
                "notes": [
                    "Alpaca is configured as paper trading only in Version 1.",
                    "Paper orders still require orchestrator and guardrail validation before submission.",
                ],
            }
        env_prefixes = {
            "coinbase": "COINBASE",
            "binance": "BINANCE",
            "interactive_brokers": "IBKR",
        }
        prefix = env_prefixes.get(key, key.upper())
        trading_enabled = _bool_env(f"{prefix}_TRADING_ENABLED", False)
        live_approved = _bool_env(f"{prefix}_LIVE_TRADING_APPROVED", False)
        submit_real_orders = _bool_env(f"{prefix}_SUBMIT_REAL_ORDERS", False)
        can_submit_real_orders = bool(auto_enabled and trading_enabled and live_approved and submit_real_orders)
        return {
            "broker": key,
            "status": "Real orders enabled" if can_submit_real_orders else "Not configured or real orders blocked",
            "auto_trading_enabled": auto_enabled,
            "trading_enabled": trading_enabled,
            "live_trading_approved": live_approved,
            "submit_real_orders": submit_real_orders,
            "can_submit_real_orders": can_submit_real_orders,
            "trading_allocation_gbp": _float_env(f"{prefix}_TRADING_ALLOCATION_GBP", 0.0),
            "max_order_gbp": _float_env(f"{prefix}_MAX_ORDER_GBP", 0.0),
            "min_order_gbp": _float_env(f"{prefix}_MIN_ORDER_GBP", 0.0),
            "max_open_trades": _int_env(f"{prefix}_MAX_OPEN_TRADES", 0),
            "buy_only_entries": _bool_env(f"{prefix}_BUY_ONLY_ENTRIES", True),
            "allowed_pairs": _csv_env(f"{prefix}_ALLOWED_PAIRS", ""),
            "notes": [
                f"{_broker_label(key)} will use this same permissions shape when the adapter is configured.",
            ],
        }

    def _ai_managed_open_trade_count(self, broker: str) -> int:
        return len(open_managed_exits(self.settings.db_path, broker))

    def _kraken_ai_capital_ledger(
        self,
        *,
        price_hints: dict[str, float] | None = None,
        allow_live_pricing: bool = True,
    ) -> dict[str, Any]:
        """Value AI-managed Kraken positions, preferring prices already fetched this cycle.

        price_hints is a symbol->GBP-price map the caller already obtained during the same
        broker-snapshot cycle (e.g. from the wallet balance conversion already done in
        _kraken_balance_summary) -- reusing it avoids a second live Kraken API round trip for
        the same market data. Any symbol still unpriced after applying the hints falls back to
        a fresh live lookup only when allow_live_pricing is True; scheduled evidence-snapshot
        capture passes False so this can never push that job over its worker timeout budget
        (AT-ED-003 corrective session, Part 1). When live pricing is unavailable or disabled,
        the persisted ledger summary already labels unpriced positions clearly via
        unrealized_pnl_status/unpriced_open_symbols -- no separate "unavailable" placeholder is
        needed here.
        """
        ledger = kraken_capital_ledger_summary(self.settings.db_path)
        symbols = list(ledger.get("unpriced_open_symbols") or [])
        price_map: dict[str, float] = {
            str(symbol).upper(): float(price)
            for symbol, price in (price_hints or {}).items()
            if price is not None
        }
        remaining = [symbol for symbol in symbols if symbol not in price_map]
        adapter = self.orchestrator.adapters.get("kraken")
        if remaining and allow_live_pricing and adapter is not None and hasattr(adapter, "current_prices"):
            try:
                pairs = [_kraken_pair(symbol) for symbol in remaining]
                prices = adapter.current_prices(pairs)
                for symbol, pair in zip(remaining, pairs):
                    price = _kraken_last_price(prices, pair)
                    if price is not None:
                        price_map[symbol] = float(price)
            except Exception as exc:
                logger.warning("Live Kraken pricing failed while valuing the AI capital ledger: %s", exc)
        if not price_map:
            return ledger
        return kraken_capital_ledger_summary(self.settings.db_path, current_prices=price_map)

    def _broker_managed_trade_capacity(self, broker: str) -> dict[str, Any]:
        key = broker.lower()
        if key != "kraken":
            return {
                "broker": key,
                "can_open": True,
                "ai_managed_open_trades": self._ai_managed_open_trade_count(key),
                "max_ai_managed_open_trades": None,
                "remaining_ai_trade_slots": None,
                "message": "No broker-specific AI-managed trade slot limit applies.",
            }
        max_trades = _int_env("KRAKEN_MAX_OPEN_TRADES", 1)
        open_trades = self._ai_managed_open_trade_count(key)
        remaining = max(0, max_trades - open_trades)
        can_open = open_trades < max_trades
        message = (
            f"AI Trader has {open_trades} managed Kraken trade(s) open out of {max_trades}; {remaining} new slot(s) remain. "
            "Existing/manual Kraken holdings are not counted."
        )
        if not can_open:
            message = (
                f"AI Trader already has {open_trades} managed Kraken trade(s) open, meeting the limit of {max_trades}. "
                "It will not open another managed Kraken trade until one exits. Existing/manual Kraken holdings are not counted."
            )
        return {
            "broker": key,
            "can_open": can_open,
            "ai_managed_open_trades": open_trades,
            "max_ai_managed_open_trades": max_trades,
            "remaining_ai_trade_slots": remaining,
            "message": message,
        }

    def _active_broker_names(self) -> list[str]:
        return [name for name, adapter in self.orchestrator.adapters.items() if adapter.get_supported_assets()]

    def _latest_snapshot_summary(self, broker: str, label: str) -> dict[str, Any] | None:
        row = self._query_executor.row("SELECT * FROM PORTFOLIO_SNAPSHOTS WHERE broker = ? ORDER BY snapshot_id DESC LIMIT 1", (broker,))
        if not row:
            return None
        return {
            "broker": label,
            "portfolio_balance": display_value(row["portfolio_value"], "no portfolio snapshot value"),
            "cash_balance": display_value(row["cash"], "no cash snapshot value"),
            "estimated_in_positions": _estimated_in_positions(row["portfolio_value"], row["cash"]),
            "last_day_pnl": display_value(row["day_pnl"], "no prior snapshot"),
            "last_week_pnl": display_value(row["week_pnl"], "no prior weekly snapshot"),
            "last_month_pnl": display_value(row["month_pnl"], "no month-start snapshot"),
            "amount_traded_today": 0,
            "month_start_portfolio_balance": display_value(row["month_start_value"], "no month-start snapshot"),
            "open_positions": display_value(row["open_positions_count"], "no position snapshots yet"),
            "status": "Connected",
        }

    def _unconfigured_exchange_portfolio(self, broker: str) -> dict[str, Any]:
        label = broker.capitalize()
        return {
            "broker": broker,
            "exchange": label,
            "portfolio_value": f"Not available - {label} not configured",
            "cash_available": f"Not available - {label} not configured",
            "todays_pnl": f"Not available - {label} not configured",
            "open_positions": [],
            "open_positions_summary": f"Not available - {label} not configured",
            "recent_orders": [],
            "recent_activities": [],
            "source": f"{label} not configured",
        }

    def _exchange_portfolio(self, broker: str) -> dict[str, Any]:
        broker = broker.lower()
        adapter = self.orchestrator.adapters.get(broker)
        if not adapter:
            return self._unconfigured_exchange_portfolio(broker)
        account = adapter.get_account()
        configured = getattr(adapter, "configured", False)
        if isinstance(account, dict) and account.get("status") == "authentication_failed":
            update_broker_runtime(self.settings.db_path, broker, connection_status=f"Authentication failed - {account.get('reason')}", details=account)
            return {
                "broker": broker,
                "exchange": _broker_label(broker),
                "connection_status": f"Authentication failed - {account.get('reason')}",
                "portfolio_value": f"Not available - {account.get('reason')}",
                "cash_available": f"Not available - {account.get('reason')}",
                "buying_power": f"Not available - {account.get('reason')}",
                "todays_pnl": f"Not available - {account.get('reason')}",
                "week_pnl": f"Not available - {account.get('reason')}",
                "month_pnl": f"Not available - {account.get('reason')}",
                "open_positions": [],
                "open_positions_summary": "Not available - authentication failed",
                "recent_orders": [],
                "recent_activities": [],
                "source": f"{_broker_label(broker)} authentication failed",
            }
        if not configured:
            return self._unconfigured_exchange_portfolio(broker)
        # Pass the account payload already fetched above instead of letting
        # get_positions() re-fetch it -- Kraken's get_positions() derives
        # positions from account balances, so re-fetching was a confirmed
        # redundant private API call on every evidence-snapshot cycle
        # (PRODUCTION_TIMEOUT_ROOT_CAUSE_ANALYSIS.md).
        positions = adapter.get_positions(account) if broker == "kraken" else adapter.get_positions()
        orders = adapter.get_orders()
        history = adapter.get_trade_history()
        record_broker_trade_history(self.settings.db_path, broker, orders + history)
        update_broker_runtime(
            self.settings.db_path,
            broker,
            connection_status="Connected",
            details={"account_status": account.get("status") if isinstance(account, dict) else "connected"},
        )
        cash = _sum_balances(account.get("balances") if isinstance(account, dict) else None)
        balance_summary = None
        if broker == "kraken":
            balance_summary = self._kraken_balance_summary_lookup(account.get("balances") if isinstance(account, dict) else None, adapter)
            cash = balance_summary.get("gbp_cash")
            equity = balance_summary.get("total_estimated_gbp")
        else:
            equity = cash
        snapshot = record_portfolio_snapshot(
            self.settings.db_path,
            broker=broker,
            exchange=_broker_label(broker),
            account={"cash": cash, "equity": equity},
            positions=positions,
            notes="Broker panel refresh snapshot.",
        )
        return {
            "broker": broker,
            "exchange": _broker_label(broker),
            "connection_status": "Connected",
            "portfolio_value": equity if equity is not None else "Not available - broker returned no portfolio valuation",
            "cash_available": cash if cash is not None else "Not available - broker returned no balances",
            "estimated_in_positions": _estimated_in_positions(equity, cash),
            "buying_power": (
                balance_summary.get("trading_allocation_gbp")
                if balance_summary
                else cash if cash is not None else "Not available - broker returned no buying power"
            ),
            "todays_pnl": display_value(snapshot["day_pnl"], "no prior snapshot yet"),
            "week_pnl": display_value(snapshot["week_pnl"], "no prior weekly snapshot yet"),
            "month_pnl": display_value(snapshot["month_pnl"], "no month-start snapshot yet"),
            "month_start_value": display_value(snapshot["month_start_value"], "no month-start snapshot yet"),
            "open_positions": positions,
            "open_positions_summary": f"{len(positions)}",
            "recent_orders": orders[:10],
            "recent_activities": history[:10],
            "balance_summary": balance_summary,
            "source": _broker_label(broker),
        }

    def _alpaca_panel_portfolio(self) -> dict[str, Any]:
        if not self.settings.has_alpaca_credentials:
            return self._unconfigured_exchange_portfolio("alpaca")
        try:
            return self._live_alpaca_portfolio()
        except Exception as exc:
            row = self._latest_snapshot_summary("alpaca", "Alpaca")
            if not row:
                return {"connection_status": "Connected", "source": f"Alpaca Paper Trading - live refresh failed: {exc}"}
            return {
                "connection_status": row.get("status") or "Connected",
                "portfolio_value": row.get("portfolio_balance"),
                "cash_available": row.get("cash_balance"),
                "estimated_in_positions": _estimated_in_positions(row.get("portfolio_balance"), row.get("cash_balance")),
                "buying_power": row.get("buying_power"),
                "todays_pnl": row.get("last_day_pnl"),
                "week_pnl": row.get("last_week_pnl"),
                "month_pnl": row.get("last_month_pnl"),
                "month_start_value": row.get("month_start_portfolio_balance"),
                "open_positions_summary": row.get("open_positions"),
                "source": f"Alpaca Paper Trading - cached snapshot because live refresh failed: {exc}",
            }

    def _live_alpaca_portfolio(self) -> dict[str, Any]:
        broker = self._broker_factory()
        account = broker.get_account()
        positions = broker.get_positions()
        orders = broker.get_orders(status="all", limit=10)
        activities = broker.get_activities("FILL")
        record_broker_trade_history(self.settings.db_path, "alpaca", list(orders) + list(activities))
        snapshot = record_portfolio_snapshot(
            self.settings.db_path,
            broker="alpaca",
            exchange="Alpaca",
            account=account,
            positions=positions,
            notes="Dashboard refresh snapshot.",
        )
        latest_trade = _latest_trade(orders, activities)
        return {
            "broker": "alpaca",
            "exchange": "Alpaca",
            "connection_status": "Connected",
            "portfolio_value": display_value(snapshot["portfolio_value"], "Alpaca returned no portfolio value"),
            "cash_available": display_value(snapshot["cash"], "Alpaca returned no cash balance"),
            "estimated_in_positions": _estimated_in_positions(snapshot["portfolio_value"], snapshot["cash"]),
            "buying_power": display_value(snapshot["buying_power"], "Alpaca returned no buying power"),
            "todays_pnl": display_value(snapshot["day_pnl"], "no prior snapshot yet"),
            "week_pnl": display_value(snapshot["week_pnl"], "no prior weekly snapshot yet"),
            "month_pnl": display_value(snapshot["month_pnl"], "no month-start snapshot yet"),
            "month_start_value": display_value(snapshot["month_start_value"], "no month-start snapshot yet"),
            "amount_traded_today": _amount_traded_today(activities),
            "latest_trade": latest_trade or "Not available - no Alpaca fills or orders returned",
            "open_positions": [
                {
                    "symbol": row.get("symbol"),
                    "qty": safe_float(row.get("qty")),
                    "market_value": safe_float(row.get("market_value")),
                    "unrealized_pl": safe_float(row.get("unrealized_pl")),
                }
                for row in positions
            ],
            "open_positions_summary": f"{len(positions)}" if positions else "0",
            "recent_orders": orders[:10] if isinstance(orders, list) else [],
            "recent_activities": activities[:10] if isinstance(activities, list) else [],
            "source": "Alpaca Paper Trading",
        }

    def broker_decisions(self, *, broker: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Read-only view of BROKER_DECISIONS.reason -- the specific guardrail/policy

        failure(s) that rejected a candidate, which no other endpoint exposes (the
        operational-events/decision-journal summaries only say "blocked", not why).
        """

        if broker:
            rows = self._query_executor.rows(
                "SELECT * FROM BROKER_DECISIONS WHERE selected_broker = ? ORDER BY created_at DESC LIMIT ?",
                (broker, max(1, int(limit))),
            )
        else:
            rows = self._query_executor.rows(
                "SELECT * FROM BROKER_DECISIONS ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            )
        return [dict(row) for row in rows]

    def order_intent_locks(self, *, broker: str | None = None, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Read-only view of ORDER_INTENT_LOCKS -- see release_order_intent_lock_for below

        for why a lock can outlive the process that created it (2026-08-01 incident).
        """

        clauses: list[str] = []
        params: list[Any] = []
        if broker:
            clauses.append("broker = ?")
            params.append(broker.lower())
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query_executor.rows(
            f"SELECT * FROM ORDER_INTENT_LOCKS {where} ORDER BY created_at DESC LIMIT ?",
            (*params, max(1, int(limit))),
        )
        return [dict(row) for row in rows]

    def release_order_intent_lock_for(self, *, broker: str, client_order_id: str, confirmed_no_order_placed: bool) -> dict[str, Any]:
        """Manually release one specific order-intent lock.

        acquire_order_intent_lock is a deliberate safety mechanism: once acquired, a
        lock only clears when the broker gives a definite "no order was placed"
        answer, precisely so a process that dies mid-submission (a timeout kill, a
        crash) can never cause the same proposal to be blindly resubmitted -- see
        release_order_intent_lock's docstring in multi_broker.py. That means a killed
        process orphans its lock forever unless someone with independent proof (e.g.
        the broker's own order history showing nothing was placed) releases it by
        hand. confirmed_no_order_placed must be explicitly set True by the caller as
        a deliberate acknowledgement that such proof was actually checked -- this
        does not check the broker itself, it only records the caller's confirmation
        and performs the release.
        """

        if not confirmed_no_order_placed:
            return {
                "status": "refused",
                "message": "Set confirmed_no_order_placed=true only after independently verifying "
                "(e.g. against the broker's own order history) that no order was actually placed "
                "for this client_order_id.",
            }
        release_order_intent_lock(self.settings.db_path, broker=broker.lower(), client_order_id=client_order_id)
        return {"status": "released", "broker": broker.lower(), "client_order_id": client_order_id}
