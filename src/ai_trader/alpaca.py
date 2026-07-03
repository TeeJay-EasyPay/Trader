from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import AccountContext, Position


class AlpacaError(RuntimeError):
    pass


@dataclass(frozen=True)
class AlpacaCredentials:
    api_key: str
    secret_key: str
    base_url: str = "https://paper-api.alpaca.markets"
    data_base_url: str = "https://data.alpaca.markets"

    def validate_paper(self) -> None:
        if "paper-api.alpaca.markets" not in self.base_url:
            raise AlpacaError("Refusing to use a non-paper Alpaca trading endpoint")


class AlpacaPaperClient:
    def __init__(self, credentials: AlpacaCredentials):
        credentials.validate_paper()
        self.credentials = credentials

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        data_api: bool = False,
    ) -> Any:
        base = self.credentials.data_base_url if data_api else self.credentials.base_url
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{base}{path}",
            data=body,
            method=method,
            headers={
                "APCA-API-KEY-ID": self.credentials.api_key,
                "APCA-API-SECRET-KEY": self.credentials.secret_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AlpacaError(f"Alpaca API error {exc.code}: {detail}") from exc

    def get_account(self) -> dict[str, Any]:
        return self._request("GET", "/v2/account")

    def get_positions(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v2/positions")

    def get_orders(self, status: str = "all", limit: int = 50) -> list[dict[str, Any]]:
        query = urlencode({"status": status, "limit": limit})
        return self._request("GET", f"/v2/orders?{query}")

    def get_activities(self, activity_type: str = "FILL") -> list[dict[str, Any]]:
        return self._request("GET", f"/v2/account/activities/{activity_type}")

    def get_latest_bars(self, symbols: list[str]) -> dict[str, Any]:
        query = urlencode({"symbols": ",".join(symbols), "feed": "iex"})
        try:
            return self._request("GET", f"/v2/stocks/bars/latest?{query}", data_api=True)
        except AlpacaError as exc:
            if "asset" in str(exc).lower() and "not found" in str(exc).lower():
                return {"bars": {}, "unavailable_symbols": symbols, "error": str(exc)}
            raise

    def get_news(self, symbols: list[str], limit: int = 5) -> dict[str, Any]:
        query = urlencode({"symbols": ",".join(symbols), "limit": limit})
        try:
            return self._request("GET", f"/v1beta1/news?{query}", data_api=True)
        except AlpacaError as exc:
            if "asset" in str(exc).lower() and "not found" in str(exc).lower():
                return {"news": [], "unavailable_symbols": symbols, "error": str(exc)}
            raise

    def place_bracket_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict[str, Any]:
        payload = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "market",
            "time_in_force": "day",
            "order_class": "bracket",
            "take_profit": {"limit_price": str(round(take_profit, 2))},
            "stop_loss": {"stop_price": str(round(stop_loss, 2))},
        }
        return self._request("POST", "/v2/orders", payload=payload)

    def account_context(self, daily_realized_pnl: float = 0.0) -> AccountContext:
        account = self.get_account()
        positions = [
            Position(
                symbol=str(row.get("symbol", "")).upper(),
                qty=float(row.get("qty", 0)),
                market_value=float(row.get("market_value", 0) or 0),
                unrealized_pl=float(row.get("unrealized_pl", 0) or 0),
            )
            for row in self.get_positions()
        ]
        return AccountContext(
            equity=float(account.get("equity", 0)),
            daily_realized_pnl=daily_realized_pnl,
            open_positions=positions,
            is_paper=True,
        )


class MockAlpacaPaperClient:
    def __init__(self, equity: float = 100_000.0):
        self.orders: list[dict[str, Any]] = []
        self.positions: list[dict[str, Any]] = []
        self.equity = equity

    def account_context(self, daily_realized_pnl: float = 0.0) -> AccountContext:
        return AccountContext(
            equity=self.equity,
            daily_realized_pnl=daily_realized_pnl,
            open_positions=[
                Position(symbol=row["symbol"], qty=float(row["qty"])) for row in self.positions
            ],
            is_paper=True,
        )

    def place_bracket_order(self, *, symbol: str, side: str, qty: float, stop_loss: float, take_profit: float) -> dict[str, Any]:
        order = {
            "id": f"mock-{len(self.orders) + 1}",
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "status": "accepted",
            "paper": True,
        }
        self.orders.append(order)
        if side == "buy":
            self.positions.append({"symbol": symbol, "qty": qty})
        return order

    def get_latest_bars(self, symbols: list[str]) -> dict[str, Any]:
        return {"bars": {symbol: {"c": 100.0, "h": 101.0, "l": 99.0, "v": 1000000} for symbol in symbols}}

    def get_news(self, symbols: list[str], limit: int = 5) -> dict[str, Any]:
        return {"news": [{"symbols": symbols, "headline": "Mock market news", "summary": "Demo-only news context."}]}
