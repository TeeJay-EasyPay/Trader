from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
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


def _whole_share_quantity(qty: float) -> int | None:
    """Whole shares only, rounded down. None when there is not even one.

    Returning None rather than silently submitting 0 or rounding up: a size below one
    share is a real answer ("this account cannot take a protected position in this stock
    at this risk level"), and the caller reports it instead of sending an order Alpaca
    will reject or one larger than the risk budget allowed.
    """
    try:
        shares = int(float(qty))
    except (TypeError, ValueError):
        return None
    return shares if shares >= 1 else None


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

    def get_activities(
        self,
        activity_type: str = "FILL",
        *,
        page_size: int = 100,
        direction: str = "desc",
    ) -> list[dict[str, Any]]:
        query = urlencode({"page_size": max(1, min(int(page_size), 100)), "direction": direction})
        return self._request("GET", f"/v2/account/activities/{activity_type}?{query}")

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

    def get_daily_bars(self, symbols: list[str], *, days: int = 120) -> dict[str, Any]:
        """Daily OHLCV history per symbol for the trailing `days` calendar days, keyed by symbol.

        Used to populate HISTORICAL_CANDLES for the backtester/walk-forward validator, not the
        live proposal path (which uses get_latest_bars). One paginated request per symbol because
        Alpaca's multi-symbol bars endpoint truncates each symbol's page independently, which would
        otherwise silently under-fill history for whichever symbol sorts last.
        """
        end = date.today()
        start = end - timedelta(days=days)
        bars: dict[str, list[dict[str, Any]]] = {}
        unavailable: list[str] = []
        for symbol in symbols:
            query = urlencode(
                {
                    "timeframe": "1Day",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "limit": 1000,
                    "feed": "iex",
                    "adjustment": "raw",
                }
            )
            try:
                response = self._request("GET", f"/v2/stocks/{symbol}/bars?{query}", data_api=True)
            except AlpacaError:
                # Any per-symbol failure here (Alpaca has used at least two different
                # message phrasings for "this ticker doesn't exist to us" -- "asset ...
                # not found" and "invalid symbol: X" -- and there is no guarantee those
                # are the only two) must not abort the whole backtest/walk-forward cycle.
                # This loop's entire purpose is per-symbol isolation: one bad ticker in
                # the equity universe (e.g. a foreign share class Alpaca doesn't carry)
                # previously crashed strategy-lab-refresh outright, silently, for at
                # least 3 consecutive days (2026-07-29 through 2026-07-31 hosted
                # evidence) before this was ever noticed.
                unavailable.append(symbol)
                continue
            bars[symbol] = response.get("bars") or []
        return {"bars": bars, "unavailable_symbols": unavailable}

    def place_bracket_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict[str, Any]:
        whole_qty = _whole_share_quantity(qty)
        if whole_qty is None:
            return {
                "status": "rejected",
                "reason": "below_one_whole_share",
                "message": (
                    f"A bracket order for {symbol} needs at least one whole share; the risk-based "
                    f"size was {qty}. Alpaca allows fractional quantities only on plain day orders, "
                    "which cannot carry the protective stop-loss and take-profit legs."
                ),
            }
        payload = {
            "symbol": symbol,
            "qty": str(whole_qty),
            "side": side,
            "type": "market",
            # 2026-08-24 hosted incident, the first equity order this system ever got as
            # far as submitting: Alpaca rejected it outright with 422 "fractional orders
            # must be DAY orders", and the exception took the whole auto-execution job
            # down with it. Risk-based sizing produces fractional share counts naturally
            # (5% of a $101k account in a ~$200 stock is 24.7 shares), and Alpaca supports
            # fractional quantities only for plain DAY orders -- never for a bracket, and
            # never good-til-cancelled.
            #
            # Rounding down to whole shares is the fix rather than switching to a DAY
            # fractional order, because DAY would mean giving up the bracket, and the
            # bracket is what the 2026-08-12 CSL incident bought: exits that survive the
            # close instead of expiring the same day and leaving a real position
            # unprotected for a month. A slightly smaller position is a trivial cost; an
            # unprotected one is not. See _whole_share_quantity for the sub-one-share case.
            # 2026-08-12 hosted incident: "day" applies to every leg of a bracket order,
            # including the take_profit/stop_loss exit legs -- not just the market entry. A
            # real position (CSL, opened 2026-07-03) sat with a growing unrealized gain for
            # over a month with zero exit protection: confirmed live via /founder/trades that
            # both its stop-loss and take-profit legs expired at market close the same day
            # they were placed (2026-07-06) because neither had been hit yet, and nothing ever
            # resubmitted replacement legs. The entry itself is still meant to be a same-day
            # market order (unaffected), but the protective exit legs must survive until they
            # actually trigger -- gtc (good-til-canceled) matches how every other broker
            # integration in this codebase treats a stop-loss/take-profit as a standing
            # instruction, not a one-day request.
            "time_in_force": "gtc",
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

    def get_daily_bars(self, symbols: list[str], *, days: int = 120) -> dict[str, Any]:
        return {"bars": {}, "unavailable_symbols": []}
