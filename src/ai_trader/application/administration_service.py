from __future__ import annotations

import json
import logging
from contextlib import closing
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote

from ..audit import AuditDatabase
from ..config import Settings
from ..models import utc_now_iso
from ..multi_broker import (
    record_notification,
    release_order_intent_lock,
    set_broker_auto_trading,
    update_broker_runtime,
)
from ..persistence.query_executor import QueryExecutor

logger = logging.getLogger("ai_trader.api")

BROKER_AUTO_TRADING_ENV_VARS = {
    "alpaca": "ALPACA_AUTO_TRADING",
    "kraken": "KRAKEN_AUTO_TRADING",
    "coinbase": "COINBASE_AUTO_TRADING",
    "binance": "BINANCE_AUTO_TRADING",
    "interactive_brokers": "IBKR_AUTO_TRADING",
}


class AdministrationService:
    """Guarded administrative actions (architecture/AI_TRADER_MODULARISATION_
    ARCHITECTURE_2026-08-02.md Phase 7): trading-state administration, broker
    auto-trading settings, Render API synchronisation, and guarded order-intent-lock
    release, moved out of LocalApiService.

    Four of these five methods (everything except set_trading_state) were originally
    moved into application/broker_service.py during Phase 6a -- a scoping mistake in
    that phase's instructions, since Phase 6 was meant to be presentation-only
    (dependency rule 4: "presentation services may read operational state but must
    not mutate trading state") and all four genuinely mutate: set_broker_auto_trading
    writes to the DB and triggers a Render deploy, _sync_broker_auto_trading_to_render/
    _render_api_json perform that Render API call, and release_order_intent_lock_for
    manually releases a safety lock. Corrected here, moved a second time (from
    broker_service.py, not from api/__init__.py -- they no longer live there).

    No injected Callables needed: unlike every other application service so far, none
    of these five methods depend on any not-yet-extracted LocalApiService state --
    only settings, audit, and query_executor, all standard dependencies.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        audit: AuditDatabase,
        query_executor: QueryExecutor,
    ) -> None:
        self.settings = settings
        self.audit = audit
        self._query_executor = query_executor

    def set_trading_state(self, state: str, command: str) -> dict[str, Any]:
        with closing(self._query_executor.connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO engine_control (id, trading_state, updated_at, last_command)
                    VALUES (1, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        trading_state = excluded.trading_state,
                        updated_at = excluded.updated_at,
                        last_command = excluded.last_command
                    """,
                    (state, utc_now_iso(), command),
                )
        self.audit.record_execution_event(f"control-{command}", "engine_control", {"state": state, "command": command})
        return {"status": state, "command": command}

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
