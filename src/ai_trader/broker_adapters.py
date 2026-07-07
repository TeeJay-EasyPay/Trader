from __future__ import annotations

import os
import base64
import hashlib
import hmac
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import parse, request

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
        return (
            os.getenv("KRAKEN_AUTO_TRADING")
            or os.getenv("KRAKEN_TRADING_ENABLED", "false")
        ).strip().lower() in {"1", "true", "yes", "on"}

    def get_supported_markets(self) -> list[str]:
        return ["KRAKEN"] if self.configured else []

    def get_supported_assets(self) -> list[str]:
        return ["crypto"] if self.configured else []

    def get_account(self) -> dict[str, Any]:
        if not self.configured:
            return self._not_configured()
        try:
            balances = self._private_request("/0/private/Balance")
            return {"status": "connected", "broker": self.name, "balances": balances.get("result", {})}
        except Exception as exc:
            return {"status": "authentication_failed", "broker": self.name, "reason": str(exc)}

    def get_balances(self) -> dict[str, Any]:
        return self.get_account()

    def get_positions(self) -> list[dict[str, Any]]:
        account = self.get_account()
        balances = account.get("balances") if isinstance(account, dict) else None
        if not isinstance(balances, dict):
            return []
        positions = []
        for symbol, amount in balances.items():
            try:
                qty = float(amount)
            except (TypeError, ValueError):
                continue
            if qty:
                positions.append({"symbol": symbol, "qty": qty, "asset_type": "crypto", "broker": self.name})
        return positions

    def get_orders(self) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        try:
            payload = self._private_request("/0/private/OpenOrders")
            orders = payload.get("result", {}).get("open", {})
            return [{"id": key, **value, "status": "open"} for key, value in orders.items()]
        except Exception:
            return []

    def get_trade_history(self) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        history: list[dict[str, Any]] = []
        try:
            closed = self._private_request("/0/private/ClosedOrders").get("result", {}).get("closed", {})
            history.extend({"id": key, **value, "status": value.get("status", "closed")} for key, value in closed.items())
        except Exception:
            pass
        try:
            trades = self._private_request("/0/private/TradesHistory").get("result", {}).get("trades", {})
            history.extend({"id": key, **value, "status": "filled"} for key, value in trades.items())
        except Exception:
            pass
        return history

    def current_prices(self, pairs: list[str]) -> dict[str, Any]:
        if not pairs:
            return {}
        query = parse.urlencode({"pair": ",".join(pairs)})
        return self._public_request(f"/0/public/Ticker?{query}").get("result", {})

    def is_asset_available(self, symbol: str, exchange: str, asset_type: str) -> bool:
        if not self.configured or asset_type.lower() != "crypto":
            return False
        return not exchange or exchange.upper() == "KRAKEN"

    def is_market_open(self, exchange: str) -> bool:
        return self.configured

    def place_order(self, order_request: OrderRequest) -> dict[str, Any]:
        if not self.configured:
            return self._not_configured()
        if not self.trading_enabled:
            return {"status": "disabled", "broker": self.name, "reason": "KRAKEN_AUTO_TRADING is false"}
        if not _bool_env("KRAKEN_LIVE_TRADING_APPROVED", False):
            return {"status": "disabled", "broker": self.name, "reason": "KRAKEN_LIVE_TRADING_APPROVED is false"}
        check = self._validate_live_order(order_request)
        if not check["passed"]:
            return {"status": "rejected", "broker": self.name, "reason": ", ".join(check["failures"]), "seatbelt_failures": check["failures"]}
        pair = check["pair"]
        payload = {
            "pair": pair,
            "type": order_request.side.lower(),
            "ordertype": "market",
            "volume": _format_decimal(check["volume"]),
            "validate": "false" if _bool_env("KRAKEN_SUBMIT_REAL_ORDERS", False) else "true",
        }
        userref = _userref(order_request.client_order_id)
        if userref is not None:
            payload["userref"] = str(userref)
        result = self._private_request("/0/private/AddOrder", payload)
        txids = result.get("result", {}).get("txid", [])
        order_id = txids[0] if txids else None
        return {
            "status": "accepted" if order_id else "submitted",
            "broker": self.name,
            "id": order_id,
            "order_id": order_id,
            "pair": pair,
            "side": order_request.side.lower(),
            "quantity": check["volume"],
            "notional": check["notional"],
            "kraken_result": result.get("result", {}),
        }

    def place_bracket_order(self, order_request: OrderRequest) -> dict[str, Any]:
        result = self.place_order(order_request)
        if result.get("status") in {"accepted", "submitted"}:
            result["exit_management"] = "managed_by_ai_trader"
            result["stop_loss"] = order_request.stop_loss
            result["take_profit"] = order_request.take_profit
        return result

    def place_exit_order(self, order_request: OrderRequest) -> dict[str, Any]:
        if not self.configured:
            return self._not_configured()
        if not _bool_env("KRAKEN_LIVE_TRADING_APPROVED", False):
            return {"status": "disabled", "broker": self.name, "reason": "KRAKEN_LIVE_TRADING_APPROVED is false"}
        pair = order_request.broker_pair or _kraken_pair(order_request.symbol, order_request.quote_currency)
        payload = {
            "pair": pair,
            "type": order_request.side.lower(),
            "ordertype": "market",
            "volume": _format_decimal(order_request.quantity),
            "validate": "false" if _bool_env("KRAKEN_SUBMIT_REAL_ORDERS", False) else "true",
        }
        userref = _userref(order_request.client_order_id)
        if userref is not None:
            payload["userref"] = str(userref)
        result = self._private_request("/0/private/AddOrder", payload)
        txids = result.get("result", {}).get("txid", [])
        order_id = txids[0] if txids else None
        return {
            "status": "accepted" if order_id else "submitted",
            "broker": self.name,
            "id": order_id,
            "order_id": order_id,
            "pair": pair,
            "side": order_request.side.lower(),
            "quantity": order_request.quantity,
            "notional": order_request.notional_amount,
            "kraken_result": result.get("result", {}),
        }

    def _validate_live_order(self, order_request: OrderRequest) -> dict[str, Any]:
        failures: list[str] = []
        if order_request.asset_type.lower() != "crypto":
            failures.append("asset_type_not_crypto")
        if order_request.side.lower() not in {"buy", "sell"}:
            failures.append("invalid_side")
        pair = order_request.broker_pair or _kraken_pair(order_request.symbol, order_request.quote_currency)
        allowed_pairs = _csv_env("KRAKEN_ALLOWED_PAIRS", "XBTGBP,ETHGBP,SOLGBP")
        if pair not in allowed_pairs:
            failures.append("pair_not_allowed")
        if order_request.quantity <= 0 or not math.isfinite(order_request.quantity):
            failures.append("quantity_invalid")
        notional = order_request.notional_amount or 0.0
        if notional <= 0:
            failures.append("notional_missing")
        max_notional = _float_env("KRAKEN_MAX_ORDER_GBP", 5.0)
        if notional > max_notional:
            failures.append("max_order_amount_exceeded")
        min_notional = _float_env("KRAKEN_MIN_ORDER_GBP", 1.0)
        if notional < min_notional:
            failures.append("min_order_amount_not_met")
        open_orders = self.get_orders()
        if len(open_orders) >= _int_env("KRAKEN_MAX_OPEN_TRADES", 1):
            failures.append("max_open_kraken_trades_exceeded")
        if order_request.side.lower() == "buy":
            balances = self.get_account().get("balances", {})
            gbp_balance = _balance_amount(balances, ("ZGBP", "GBP"))
            if gbp_balance is not None and gbp_balance < notional * 1.01:
                failures.append("insufficient_gbp_balance")
        if order_request.stop_loss <= 0:
            failures.append("stop_loss_missing")
        if order_request.take_profit <= 0:
            failures.append("take_profit_missing")
        if order_request.side.lower() == "buy" and order_request.stop_loss >= order_request.take_profit:
            failures.append("invalid_exit_prices")
        return {
            "passed": not failures,
            "failures": failures,
            "pair": pair,
            "volume": order_request.quantity,
            "notional": notional,
        }

    def _public_request(self, path: str) -> dict[str, Any]:
        base_url = os.getenv("KRAKEN_BASE_URL", "https://api.kraken.com")
        with request.urlopen(f"{base_url}{path}", timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("error"):
            raise RuntimeError("; ".join(data["error"]))
        return data

    def _private_request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        api_key = os.getenv("KRAKEN_API_KEY")
        secret = os.getenv("KRAKEN_PRIVATE_KEY") or os.getenv("KRAKEN_API_SECRET")
        if not api_key or not secret:
            raise RuntimeError("KRAKEN_API_KEY and KRAKEN_PRIVATE_KEY are required")
        base_url = os.getenv("KRAKEN_BASE_URL", "https://api.kraken.com")
        body = dict(payload or {})
        body["nonce"] = str(int(time.time() * 1000))
        encoded = parse.urlencode(body).encode("utf-8")
        message = path.encode("utf-8") + hashlib.sha256(body["nonce"].encode("utf-8") + encoded).digest()
        signature = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
        headers = {
            "API-Key": api_key,
            "API-Sign": base64.b64encode(signature.digest()).decode("ascii"),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        req = request.Request(f"{base_url}{path}", data=encoded, headers=headers, method="POST")
        with request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("error"):
            raise RuntimeError("; ".join(data["error"]))
        return data


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


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    try:
        return default if value is None else float(value)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    try:
        return default if value is None else int(value)
    except ValueError:
        return default


def _csv_env(name: str, default: str) -> set[str]:
    value = os.getenv(name, default)
    return {item.strip().upper() for item in value.split(",") if item.strip()}


def _kraken_pair(symbol: str, quote_currency: str = "GBP") -> str:
    base = symbol.upper().replace("/", "").replace("-", "")
    if base.endswith(quote_currency.upper()):
        base = base[: -len(quote_currency)]
    if base == "BTC":
        base = "XBT"
    return f"{base}{quote_currency.upper()}"


def _kraken_last_price(prices: dict[str, Any], pair: str) -> float | None:
    if not isinstance(prices, dict):
        return None
    payload = prices.get(pair) or next(iter(prices.values()), None)
    if not isinstance(payload, dict):
        return None
    last = payload.get("c")
    if isinstance(last, list) and last:
        try:
            return float(last[0])
        except (TypeError, ValueError):
            return None
    try:
        return float(last) if last is not None else None
    except (TypeError, ValueError):
        return None


def _balance_amount(balances: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in balances:
            try:
                return float(balances[key])
            except (TypeError, ValueError):
                return None
    return None


def _format_decimal(value: float) -> str:
    text = f"{value:.10f}"
    return text.rstrip("0").rstrip(".")


def _userref(client_order_id: str | None) -> int | None:
    if not client_order_id:
        return None
    digest = hashlib.sha256(client_order_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 2_000_000_000
