from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from .alpaca import AlpacaCredentials, AlpacaPaperClient
from .models import OrderRequest


class BrokerAdapter(Protocol):
    name: str

    def get_account(self) -> dict[str, Any]: ...
    def get_balances(self) -> dict[str, Any]: ...
    def get_positions(self) -> list[dict[str, Any]]: ...
    def get_orders(self) -> list[dict[str, Any]]: ...
    def get_trade_history(self) -> list[dict[str, Any]]: ...
    def get_supported_markets(self) -> list[str]: ...
    def get_supported_assets(self) -> list[str]: ...
    def is_asset_available(self, symbol: str, exchange: str, asset_type: str) -> bool: ...
    def is_market_open(self, exchange: str) -> bool: ...
    def place_order(self, order_request: OrderRequest) -> dict[str, Any]: ...
    def place_bracket_order(self, order_request: OrderRequest) -> dict[str, Any]: ...
    def cancel_order(self, order_id: str) -> dict[str, Any]: ...
    def close_position(self, symbol: str) -> dict[str, Any]: ...


class AlpacaBrokerAdapter:
    name = "alpaca"

    def __init__(self, client: AlpacaPaperClient):
        self.client = client

    def get_account(self) -> dict[str, Any]:
        return self.client.get_account()

    def get_balances(self) -> dict[str, Any]:
        account = self.client.get_account()
        return {"cash": account.get("cash"), "currency": account.get("currency"), "buying_power": account.get("buying_power")}

    def get_positions(self) -> list[dict[str, Any]]:
        return self.client.get_positions()

    def get_orders(self) -> list[dict[str, Any]]:
        return self.client.get_orders(status="all", limit=50)

    def get_trade_history(self) -> list[dict[str, Any]]:
        return self.client.get_activities("FILL")

    def get_supported_markets(self) -> list[str]:
        return ["NYSE", "NASDAQ", "AMEX", "ARCA", "OTC"]

    def get_supported_assets(self) -> list[str]:
        return ["stock", "etf"]

    def is_asset_available(self, symbol: str, exchange: str, asset_type: str) -> bool:
        if asset_type.lower() not in self.get_supported_assets():
            return False
        try:
            asset = self.client._request("GET", f"/v2/assets/{symbol.upper()}")
        except Exception:
            return False
        if str(asset.get("status", "")).lower() != "active":
            return False
        if not bool(asset.get("tradable", False)):
            return False
        asset_exchange = str(asset.get("exchange", "")).upper()
        return not exchange or exchange.upper() == asset_exchange or asset_exchange in self.get_supported_markets()

    def is_market_open(self, exchange: str) -> bool:
        try:
            clock = self.client._request("GET", "/v2/clock")
        except Exception:
            return False
        return bool(clock.get("is_open", False))

    def place_order(self, order_request: OrderRequest) -> dict[str, Any]:
        payload = {
            "symbol": order_request.symbol,
            "qty": str(order_request.quantity),
            "side": order_request.side,
            "type": "market",
            "time_in_force": "day",
        }
        return self.client._request("POST", "/v2/orders", payload=payload)

    def place_bracket_order(self, order_request: OrderRequest) -> dict[str, Any]:
        return self.client.place_bracket_order(
            symbol=order_request.symbol,
            side=order_request.side,
            qty=order_request.quantity,
            stop_loss=order_request.stop_loss,
            take_profit=order_request.take_profit,
        )

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        self.client._request("DELETE", f"/v2/orders/{order_id}")
        return {"id": order_id, "status": "cancel_requested"}

    def close_position(self, symbol: str) -> dict[str, Any]:
        return self.client._request("DELETE", f"/v2/positions/{symbol.upper()}")


@dataclass
class PlaceholderBrokerAdapter:
    name: str
    required_env_vars: tuple[str, ...]

    @property
    def configured(self) -> bool:
        return all(os.getenv(key) for key in self.required_env_vars)

    def _not_configured(self) -> dict[str, Any]:
        return {"status": "not_configured", "broker": self.name}

    def get_account(self) -> dict[str, Any]:
        return self._not_configured()

    def get_balances(self) -> dict[str, Any]:
        return self._not_configured()

    def get_positions(self) -> list[dict[str, Any]]:
        return []

    def get_orders(self) -> list[dict[str, Any]]:
        return []

    def get_trade_history(self) -> list[dict[str, Any]]:
        return []

    def get_supported_markets(self) -> list[str]:
        return []

    def get_supported_assets(self) -> list[str]:
        return []

    def is_asset_available(self, symbol: str, exchange: str, asset_type: str) -> bool:
        return False

    def is_market_open(self, exchange: str) -> bool:
        return False

    def place_order(self, order_request: OrderRequest) -> dict[str, Any]:
        return self._not_configured()

    def place_bracket_order(self, order_request: OrderRequest) -> dict[str, Any]:
        return self._not_configured()

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._not_configured()

    def close_position(self, symbol: str) -> dict[str, Any]:
        return self._not_configured()


class InteractiveBrokersAdapter(PlaceholderBrokerAdapter):
    def __init__(self) -> None:
        super().__init__("interactive_brokers", ("IBKR_API_KEY",))


class SaxoAdapter(PlaceholderBrokerAdapter):
    def __init__(self) -> None:
        super().__init__("saxo", ("SAXO_API_KEY",))


class KrakenAdapter(PlaceholderBrokerAdapter):
    def __init__(self) -> None:
        super().__init__("kraken", ("KRAKEN_API_KEY",))

    @property
    def configured(self) -> bool:
        return bool(os.getenv("KRAKEN_API_KEY") and (os.getenv("KRAKEN_PRIVATE_KEY") or os.getenv("KRAKEN_API_SECRET")))

    @property
    def trading_enabled(self) -> bool:
        return os.getenv("KRAKEN_TRADING_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

    def get_supported_markets(self) -> list[str]:
        return ["KRAKEN"] if self.configured else []

    def get_supported_assets(self) -> list[str]:
        return ["crypto"] if self.configured else []

    def place_order(self, order_request: OrderRequest) -> dict[str, Any]:
        if not self.configured:
            return self._not_configured()
        if not self.trading_enabled:
            return {"status": "disabled", "broker": self.name, "reason": "KRAKEN_TRADING_ENABLED is false"}
        return {"status": "not_implemented", "broker": self.name, "reason": "Kraken live integration is prepared but not enabled in Sprint 5"}

    def place_bracket_order(self, order_request: OrderRequest) -> dict[str, Any]:
        return self.place_order(order_request)


class CoinbaseAdapter(PlaceholderBrokerAdapter):
    def __init__(self) -> None:
        super().__init__("coinbase", ("COINBASE_API_KEY", "COINBASE_API_SECRET"))

    @property
    def trading_enabled(self) -> bool:
        return os.getenv("COINBASE_TRADING_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

    def get_supported_markets(self) -> list[str]:
        return ["COINBASE"] if self.configured else []

    def get_supported_assets(self) -> list[str]:
        return ["crypto"] if self.configured else []

    def place_order(self, order_request: OrderRequest) -> dict[str, Any]:
        if not self.configured:
            return self._not_configured()
        if not self.trading_enabled:
            return {"status": "disabled", "broker": self.name, "reason": "COINBASE_TRADING_ENABLED is false"}
        return {"status": "not_implemented", "broker": self.name, "reason": "Coinbase Advanced Trade integration is prepared but not enabled in Sprint 5"}

    def place_bracket_order(self, order_request: OrderRequest) -> dict[str, Any]:
        return self.place_order(order_request)


def alpaca_adapter_from_env(
    *,
    api_key: str | None,
    secret_key: str | None,
    base_url: str,
    data_base_url: str,
) -> AlpacaBrokerAdapter | None:
    if not api_key or not secret_key:
        return None
    return AlpacaBrokerAdapter(
        AlpacaPaperClient(
            AlpacaCredentials(
                api_key=api_key,
                secret_key=secret_key,
                base_url=base_url,
                data_base_url=data_base_url,
            )
        )
    )
