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
from .entry_drift import should_abandon_entry


class BrokerAdapter(Protocol):
    name: str
    # Whether the orchestrator's production governance chain (Strategy Entitlement -> Portfolio
    # Manager -> Risk Sentinel, via sprint6.pre_execution_decision_packet) must approve any trade
    # routed to this broker before submission. Defaults True for every adapter; a broker can only
    # skip governance by explicitly setting this False, never by omission - previously this was a
    # hardcoded {"alpaca", "kraken"} name allowlist in orchestrator.py, so a new adapter that
    # implemented this Protocol correctly would silently bypass governance unless a human
    # separately remembered to edit that unrelated line.
    requires_production_governance: bool

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
    requires_production_governance = True

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
        try:
            return self.client.get_activities("FILL", page_size=100, direction="desc")
        except TypeError:
            # Preserve compatibility with local/demo clients that implement the
            # original single-argument interface.
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

    def place_trailing_stop_order(self, order_request: OrderRequest, trailing_pct: float) -> dict[str, Any]:
        """Native Alpaca trailing stop, so the exit lives on Alpaca's book, not in our loop.

        Founder-directed 2026-08-22, as the risk control that must exist BEFORE leverage is
        enabled on this account. Same reasoning as the Kraken equivalent: a software-side
        trailing stop in monitor_managed_exits can only act while this process is up and the
        broker is reachable, which is exactly when a leveraged position most needs an exit.

        Alpaca expresses this as type="trailing_stop" with trail_percent, and it must be
        good-til-cancelled -- a "day" exit leg is the 2026-08-12 CSL incident, where both
        protective legs expired at the close on the day they were placed and a real position
        then sat unprotected for over a month.
        """
        if trailing_pct <= 0:
            return {"status": "rejected", "broker": self.name, "reason": "trailing_pct_invalid"}
        quantity = float(order_request.quantity or 0)
        if quantity <= 0:
            return {"status": "rejected", "broker": self.name, "reason": "quantity_invalid"}
        payload = {
            "symbol": order_request.symbol.upper(),
            "qty": str(quantity),
            "side": order_request.side.lower(),
            "type": "trailing_stop",
            # Alpaca takes a percentage, not a fraction: 0.015 -> "1.5".
            "trail_percent": f"{trailing_pct * 100:g}",
            "time_in_force": "gtc",
        }
        if order_request.client_order_id:
            payload["client_order_id"] = str(order_request.client_order_id)
        try:
            result = self.client._request("POST", "/v2/orders", payload=payload)
        except Exception as exc:  # noqa: BLE001 - must never lose an entry that already filled
            return {"status": "attach_failed", "broker": self.name, "reason": str(exc)}
        order_id = str((result or {}).get("id") or "")
        if not order_id:
            return {"status": "attach_failed", "broker": self.name, "reason": "no_order_id_returned", "raw": result}
        # "accepted" is the status the orchestrator's attach hook checks for.
        return {"status": "accepted", "broker": self.name, "id": order_id, "raw": result}

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        self.client._request("DELETE", f"/v2/orders/{order_id}")
        return {"id": order_id, "status": "cancel_requested"}

    def close_position(self, symbol: str) -> dict[str, Any]:
        return self.client._request("DELETE", f"/v2/positions/{symbol.upper()}")


@dataclass
class PlaceholderBrokerAdapter:
    name: str
    required_env_vars: tuple[str, ...]
    requires_production_governance: bool = True

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
        self._pair_minimum_cache: dict[str, float | None] = {}
        # Kraken's full pair list, fetched at most once per adapter instance. Pair listings
        # do not change within a process lifetime, and this is only read by a diagnostic.
        self._known_pairs_cache: set[str] | None = None
        self._pair_decimals_cache: dict[str, int | None] = {}

    def unlistable_allowed_pairs(self) -> list[str] | None:
        """Configured KRAKEN_ALLOWED_PAIRS entries that Kraken does not actually list.

        2026-08-22: the Founder widened KRAKEN_ALLOWED_PAIRS from 3 pairs to 10, but four of
        them -- BTCGBP (Kraken calls Bitcoin XBT), BNBGBP, TRXGBP, HBARGBP -- are not real
        Kraken GBP pairs. Nothing anywhere said so, so 40% of the AI's search universe was
        silently doing nothing and the widening delivered 6 tradeable coins instead of 10.

        Returns [] when every configured pair is real, a list of the bad ones when not, and
        None when the check itself could not run -- "could not check" must stay
        distinguishable from "checked and everything is fine". Never raises: this is a
        diagnostic, and it must not be able to break the broker panel it reports into.
        """
        allowed = _csv_env("KRAKEN_ALLOWED_PAIRS", "XBTGBP,ETHGBP,SOLGBP")
        if not allowed:
            return []
        known = self.known_pair_map()
        if not known:
            return None
        return sorted(pair for pair in allowed if pair.upper() not in known)

    def known_pair_map(self) -> dict[str, str] | None:
        """Every listed pair name -> the key Kraken actually returns it under, cached.

        Both directions of this matter and neither is guessable:

        - Kraken answers a Ticker request for XBTGBP under the key XXBTZGBP, so a
          batched read that looks up the name it asked for finds nothing. Getting
          this wrong doesn't fail loudly -- it silently prices nothing and falls
          back to one-call-per-asset, which is the slow path it was meant to replace.
        - Kraken rejects an ENTIRE Ticker request if any single pair in it is
          unknown (EQuery:Unknown asset pair). Speculative names like USDGBP, which
          isn't a real pair, would otherwise poison every batch they appear in.

        Returns None when the lookup could not run, so callers can tell "unknown"
        from "known to be empty". Never raises.
        """
        if self._known_pairs_cache is None:
            try:
                data = self._public_request("/0/public/AssetPairs")
                result = data.get("result") or {}
                known: dict[str, str] = {}
                for key, info in result.items():
                    if not isinstance(info, dict) or info.get("status") not in (None, "online"):
                        continue
                    canonical = str(key)
                    known[canonical.upper()] = canonical
                    altname = info.get("altname")
                    if altname:
                        known[str(altname).upper()] = canonical
                self._known_pairs_cache = known or None
            except Exception:  # noqa: BLE001 - a diagnostic must never break the panel
                self._known_pairs_cache = None
        return self._known_pairs_cache

    def best_bid(self, pair: str) -> float | None:
        """The current best bid for a pair, or None if it cannot be read.

        2026-08-24 finding: patient limit entries almost never filled, so nearly every buy
        took the market fallback and paid the 0.80% taker rate anyway -- confirmed against
        real orders, where only 1 of 4 overnight entries stayed a limit. The cause was the
        price: _limit_entry_price works from the PROPOSAL's entry price, which is whatever
        the market was doing when research ran, potentially an hour earlier. By the time the
        order is placed the market has moved and the bid sits somewhere irrelevant.

        Resting at the live best bid puts the order at the front of the queue, where it
        fills as soon as any seller crosses -- the highest-probability maker fill available
        without ever crossing the spread ourselves.
        """
        try:
            payload = self._public_request(f"/0/public/Ticker?{parse.urlencode({'pair': pair})}")
            info = (payload.get("result") or {}).get(pair) or next(iter((payload.get("result") or {}).values()), None)
            bid = (info or {}).get("b")
            value = float(bid[0]) if isinstance(bid, (list, tuple)) and bid else None
            return value if value and value > 0 else None
        except Exception:  # noqa: BLE001 - a pricing read must never break an order attempt
            return None

    def pair_price_decimals(self, pair: str) -> int | None:
        """How many decimal places Kraken accepts in a PRICE for this pair.

        2026-08-23 live incident: every Kraken buy was rejected with
        "EOrder:Invalid price:ETH/GBP price can only be specified up to 2 decimals." from
        the moment maker/limit entries were switched on. A market order carries no price,
        so the fault could not appear until limit orders went live -- last accepted order
        2026-08-21 23:43, first rejection 2026-08-22 18:41. The limit price is computed as
        notional/quantity with an offset applied, which routinely produces 7+ decimals.

        The allowance is per-pair and varies widely (ETHGBP 2, LINKGBP 3, XBTGBP 1,
        ADAGBP 5), so a single fixed rounding would be wrong for most pairs. Read from
        AssetPairs' pair_decimals and cached, since it cannot change within a process.
        Returns None when unknown, which the caller treats as "do not risk a limit order".
        """
        if pair in self._pair_decimals_cache:
            return self._pair_decimals_cache[pair]
        decimals: int | None = None
        try:
            data = self._public_request(f"/0/public/AssetPairs?pair={pair}")
            result = data.get("result") or {}
            info = result.get(pair) or next(iter(result.values()), None)
            if isinstance(info, dict) and info.get("pair_decimals") is not None:
                decimals = int(info["pair_decimals"])
        except Exception:  # noqa: BLE001 - never let a price lookup crash an order attempt
            decimals = None
        self._pair_decimals_cache[pair] = decimals
        return decimals

    def pair_minimum_notional(self, pair: str, price: float) -> float | None:
        # 2026-08-10 hosted incident: KRAKEN_MIN_ORDER_GBP is a single flat guess applied to
        # every pair, but Kraken's real minimum order size (published per-pair via the public
        # AssetPairs endpoint as "ordermin", a base-currency volume, and "costmin", a
        # quote-currency minimum cost) varies by pair. A flat GBP floor that happens to clear
        # this guess can still be genuinely below the exchange's own minimum for a specific pair
        # -- confirmed live: a proposal floored to GBP 2.00 was accepted through every governance
        # check, submitted to Kraken, and rejected by the exchange itself with "EGeneral:Invalid
        # arguments:volume minimum not met". Cached per pair for the life of this adapter
        # instance (each worker/request process constructs its own; pair minimums do not change
        # within a process lifetime) so this network call only happens once per pair, not once
        # per candidate evaluation.
        #
        # 2026-08-13 hosted incident: the first version of this fix preferred costmin over
        # ordermin*price whenever costmin was present, treating them as alternatives -- but
        # Kraken enforces both simultaneously; an order must clear whichever is larger, not just
        # whichever the API happened to publish first. Confirmed live: XLMGBP publishes
        # costmin=0.43 (GBP) *and* ordermin=30 (XLM units, ~GBP 3.56 at the price then in
        # effect) -- this code used 0.43, the resulting order cleared every governance check,
        # and Kraken itself rejected it with the same "volume minimum not met" error the 2026-
        # 08-10 fix was meant to prevent. Now takes the real binding constraint: the larger of
        # the two, when both are available.
        if pair in self._pair_minimum_cache:
            return self._pair_minimum_cache[pair]
        minimum: float | None = None
        try:
            data = self._public_request(f"/0/public/AssetPairs?pair={pair}")
            info = (data.get("result") or {}).get(pair) or next(iter((data.get("result") or {}).values()), None)
            if isinstance(info, dict):
                costmin = info.get("costmin")
                ordermin = info.get("ordermin")
                candidates = []
                if costmin is not None:
                    candidates.append(float(costmin))
                if ordermin is not None and price > 0:
                    candidates.append(float(ordermin) * price)
                if candidates:
                    minimum = max(candidates)
        except Exception:
            minimum = None
        self._pair_minimum_cache[pair] = minimum
        return minimum

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

    def get_positions(self, account: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if account is None:
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
                # 2026-08-22: Kraken's own balance keys use its legacy asset codes (XETH,
                # XXRP, XXBT, ...) while every AI-side record (KRAKEN_RECONCILED_RESULTS,
                # MANAGED_TRADE_EXITS, proposals) uses the plain symbol (ETH, XRP, BTC).
                # Returning the raw code here meant the mobile app's AI-managed-position
                # match (position.symbol vs. managed_exits[].symbol) could never succeed for
                # any legacy-coded asset, no matter how completely the rest of the pipeline
                # was fixed.
                positions.append({"symbol": _kraken_asset_symbol(symbol), "qty": qty, "asset_type": "crypto", "broker": self.name})
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
            history.extend(
                {"id": key, **value, "status": value.get("status", "closed"), "kraken_record_type": "closed_order"}
                for key, value in closed.items()
            )
        except Exception:
            pass
        try:
            trades = self._private_request("/0/private/TradesHistory").get("result", {}).get("trades", {})
            history.extend(
                {"id": key, **value, "status": "filled", "kraken_record_type": "trade_fill"}
                for key, value in trades.items()
            )
        except Exception:
            pass
        return history

    def current_prices(self, pairs: list[str]) -> dict[str, Any]:
        if not pairs:
            return {}
        query = parse.urlencode({"pair": ",".join(pairs)})
        return self._public_request(f"/0/public/Ticker?{query}").get("result", {})

    def order_book(self, pair: str, *, count: int = 500) -> dict[str, list[list[str]]] | None:
        """Live resting bids and asks for one pair.

        2026-08-24, Founder-directed: the signals driving entries until now (trend,
        momentum, RSI, moving averages) are published free to every trader alive, so none
        of them can be an edge. This is the opposite -- real money committed at real
        prices, free from Kraken's public API, and almost never read systematically by
        retail. It answers where the buyers actually are, rather than where a drawn line
        says support "should" be.

        Returns None rather than raising: market structure is an extra input, and its
        absence must never stop a trade being evaluated on everything else.
        """
        try:
            result = self._public_request(f"/0/public/Depth?{parse.urlencode({'pair': pair, 'count': max(1, min(int(count), 500))})}").get("result", {})
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(result, dict) or not result:
            return None
        # Kraken answers under its canonical pair name (XBTGBP -> XXBTZGBP), so take the
        # single payload rather than looking up the name we asked for. Same trap that
        # made the batched Ticker read silently price nothing.
        book = next(iter(result.values()), None)
        if not isinstance(book, dict) or "bids" not in book or "asks" not in book:
            return None
        return {"bids": book.get("bids") or [], "asks": book.get("asks") or []}

    def recent_trades(self, pair: str) -> list[list[Any]] | None:
        """Recently executed trades: price, volume, timestamp, side.

        The order book is intent and can be withdrawn; this is money that actually
        changed hands. Read together they catch the case the book alone cannot -- a wall
        that vanishes before anything trades through it.
        """
        try:
            result = self._public_request(f"/0/public/Trades?{parse.urlencode({'pair': pair})}").get("result", {})
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(result, dict):
            return None
        for key, value in result.items():
            if key != "last" and isinstance(value, list):
                return value
        return None

    def get_ohlc_candles(self, pair: str, *, interval_minutes: int = 1440, since: int | None = None) -> list[dict[str, Any]]:
        """Real multi-candle price history for one pair -- see kraken_market_data.py's
        module docstring for why this didn't exist anywhere in the codebase before
        2026-08-20 (every prior Kraken price read was a single current-price snapshot).
        """
        from .kraken_market_data import fetch_kraken_ohlc

        return fetch_kraken_ohlc(pair, interval_minutes=interval_minutes, since=since)

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
        # Founder-directed 2026-08-20: entries as resting limit orders to earn the maker fee.
        # Confirmed on pro.kraken.com, Tier 1: maker 0.40% vs taker 0.80% -- so a patient
        # entry halves the cost of that leg (1.60% -> 1.20% round trip).
        #
        # ENTRIES ONLY, deliberately. The sell side is already occupied by the native
        # trailing stop, and a resting sell reserves the coins, so only one can exist per
        # position. Buying is uncontested: nothing else is waiting there, so this costs no
        # protection whatsoever.
        #
        # post-only (`oflags: post`) is what actually guarantees the saving. Without it a
        # limit order priced at or through the current market executes immediately and is
        # charged as a taker anyway -- the exact trap that made the reactive take-profit
        # version of this change worthless. post-only tells Kraken to CANCEL rather than
        # cross, so the order either rests (maker) or does not exist. The caller is then
        # responsible for falling back to a market order, which is why this is gated off by
        # default until that fallback is wired.
        is_patient_limit_entry = False
        limit_price = _limit_entry_price(order_request)
        # 2026-08-23: the price MUST be rounded to the pair's own allowed precision, or
        # Kraken rejects the order outright ("price can only be specified up to N
        # decimals") and the trade is lost -- which is exactly what happened to every buy
        # for a day. Rounded DOWN for a buy: rounding up could place the bid above the
        # price the proposal was sized against, and paying more to save a fee is
        # self-defeating. If the precision is unknown we do not guess -- fall through to
        # the market order that was already built, since a fee optimisation must never
        # cost the trade itself.
        if limit_price is not None and order_request.side.lower() == "buy":
            # Rest at the live best bid where possible. Capped by the proposal-derived price
            # so we never bid MORE than the trade was sized against -- paying above that to
            # save 0.40% is self-defeating. When the market has run above the proposal price
            # the cap binds, the order sits below market and probably will not fill, and the
            # market fallback takes it: that is the correct outcome, not a bug. We decline to
            # chase, we do not decline to trade.
            live_bid = self.best_bid(pair)
            if live_bid is not None:
                # Rest AT the best bid, capped by the proposal price so we never bid above
                # what the trade was sized against. No extra concession: the bid already is
                # the maker-optimal price, and going below it only removes the fill.
                limit_price = min(live_bid, limit_price)
            else:
                # No live bid to aim at, so step back from the proposal price rather than
                # sitting exactly on it and risking a taker fill if the market has moved.
                offset = max(0.0, _float_env("KRAKEN_LIMIT_ENTRY_OFFSET_PCT", 0.0005))
                limit_price = limit_price * (1.0 - offset)
            decimals = self.pair_price_decimals(pair)
            if decimals is None:
                limit_price = None
            else:
                factor = 10 ** decimals
                limit_price = math.floor(limit_price * factor) / factor
                if limit_price <= 0:
                    limit_price = None
        if limit_price is not None and order_request.side.lower() == "buy":
            is_patient_limit_entry = True
            payload["ordertype"] = "limit"
            payload["price"] = _format_decimal(limit_price)
            payload["oflags"] = "post"
            # Kraken-side expiry must outlast our own poll budget, or Kraken cancels the
            # order while we are still waiting for it and we fall back for no reason.
            expire_seconds = max(30, int(_float_env("KRAKEN_LIMIT_ENTRY_TIMEOUT_SECONDS", 420)))
            # Kraken cancels the order itself once this expires, so an unfilled patient
            # entry cannot sit on the book indefinitely holding cash against a stale idea.
            payload["expiretm"] = f"+{expire_seconds}"
        userref = _userref(order_request.client_order_id)
        if userref is not None:
            payload["userref"] = str(userref)
        try:
            result = self._private_request("/0/private/AddOrder", payload)
        except RuntimeError as exc:
            # Same reasoning as place_exit_order: _private_request only raises RuntimeError
            # for Kraken's own populated "error" response -- a definite, synchronous
            # rejection, not the "we genuinely don't know what happened" case a network
            # failure would raise a different exception type for. evaluate_recommendation's
            # existing handling of a "rejected" order status already records this candidate
            # as one rejected proposal and completes its order-intent lock normally, instead
            # of letting the exception crash the whole auto-execution batch.
            #
            # 2026-08-23: if the PATIENT LIMIT version was rejected, retry once as the plain
            # market order this would have been anyway. The existing fallback only covered a
            # limit order that rested and failed to fill; a synchronous rejection killed the
            # trade outright. That is how a price-precision bug in the fee optimisation
            # silently blocked every Kraken buy for a day. The principle this restores: an
            # attempt to save a fee must never be able to cost the trade.
            if is_patient_limit_entry:
                market_payload = dict(payload)
                market_payload["ordertype"] = "market"
                for field in ("price", "oflags", "expiretm"):
                    market_payload.pop(field, None)
                try:
                    result = self._private_request("/0/private/AddOrder", market_payload)
                except RuntimeError as market_exc:
                    return {
                        "status": "rejected", "broker": self.name,
                        "reason": f"{exc}; market fallback also rejected: {market_exc}",
                        "pair": pair,
                    }
                txids = result.get("result", {}).get("txid", [])
                order_id = txids[0] if txids else None
                return {
                    "status": "accepted" if order_id else "submitted",
                    "broker": self.name, "id": order_id, "order_id": order_id, "pair": pair,
                    "side": order_request.side.lower(), "quantity": check["volume"],
                    "notional": check["notional"],
                    "fallback_from_rejected_limit_order": str(exc),
                }
            return {"status": "rejected", "broker": self.name, "reason": str(exc), "pair": pair}
        txids = result.get("result", {}).get("txid", [])
        order_id = txids[0] if txids else None
        response = {
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
        # 2026-08-22 Founder-directed: this is the fallback the patient-limit-entry feature
        # was shipped inert (2026-08-20) waiting on -- a post-only order that never rests
        # simply does not exist, so without this, enabling limit entries would have quietly
        # turned some fraction of unfilled patient entries into missed trades. Bounded wait,
        # not the full expiretm window: polling for the whole 120s would tie up a research
        # cycle that evaluates many candidates per run. If the maker fill hasn't happened
        # by the shorter wait, fall back to a normal market order so the trade still
        # happens -- paying the taker fee this one time is strictly better than not trading
        # the idea at all.
        if is_patient_limit_entry and order_id:
            return self._await_fill_or_fallback_to_market(order_id, order_request, check, pair, response)
        return response

    def _await_fill_or_fallback_to_market(
        self,
        order_id: str,
        order_request: OrderRequest,
        check: dict[str, Any],
        pair: str,
        limit_response: dict[str, Any],
    ) -> dict[str, Any]:
        # 2026-08-23, measured: the 20s budget made the whole maker strategy inert. A
        # post-only buy priced BELOW the market essentially never fills in 20 seconds, so
        # every order took the market fallback and paid the 0.80% taker rate. Confirmed
        # against three real trades -- LINK 1.606%, XLM 1.600%, LTC 1.592% round trip,
        # indistinguishable from the ~1.63% every pre-maker trade paid.
        #
        # 20s -> 300s gives a resting order a real chance to fill. The interval moves 5s ->
        # 30s DELIBERATELY and must not be lowered without thought: at 5s a 300s budget
        # would be 60 QueryOrders calls per order instead of 4, a 15x rise in private API
        # pressure against an account that hit "EGeneral:Temporary lockout" the same day.
        # 30s over 300s is 10 calls -- more patience AND fewer calls per minute than before.
        poll_interval = max(1.0, _float_env("KRAKEN_LIMIT_ENTRY_POLL_INTERVAL_SECONDS", 30.0))
        poll_budget = max(0.0, _float_env("KRAKEN_LIMIT_ENTRY_POLL_BUDGET_SECONDS", 300.0))
        deadline = time.monotonic() + poll_budget
        requested_volume = _float_or_zero(check.get("volume"))
        filled_volume = 0.0
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            try:
                status, filled_volume = self._order_fill_state(order_id)
            except Exception:  # noqa: BLE001 - a status-check failure must not crash order placement
                status = None
            if status == "closed":
                # Filled as a maker -- the whole point of resting the order.
                return limit_response
            if status not in ("open", "pending", None):
                # Kraken already cancelled/expired it (post-only crossed the spread, or the
                # window ran out on Kraken's own clock) -- stop waiting and fall back now
                # rather than burning the rest of the poll budget on a dead order.
                break
        try:
            self._private_request("/0/private/CancelOrder", {"txid": order_id})
        except Exception:  # noqa: BLE001 - best-effort; if it already filled or is already gone, cancellation legitimately fails
            pass
        # 2026-09-05: re-read AFTER cancelling, not before. The order stays live during the
        # final poll interval and through the cancel round trip, and on a thin book that is
        # ample time for more of it to fill. Sizing the fallback off the last poll would
        # re-buy whatever landed in that gap -- a smaller version of the same over-buy this
        # whole block exists to prevent.
        try:
            _final_status, final_filled = self._order_fill_state(order_id)
            filled_volume = max(filled_volume, final_filled)
        except Exception:  # noqa: BLE001 - fall back to the last figure we did read
            pass
        # The price the proposal was sized against; used to express volumes as money below.
        unit_price = _float_or_zero(check.get("notional")) / requested_volume if requested_volume else 0.0
        remaining_volume = requested_volume - filled_volume
        if requested_volume > 0 and remaining_volume <= 0:
            # The patient order filled after all, between the last poll and the cancel.
            filled_response = dict(limit_response)
            filled_response["quantity"] = filled_volume
            filled_response["filled_quantity"] = filled_volume
            filled_response["patient_limit_fully_filled_before_fallback"] = True
            return filled_response
        if filled_volume > 0:
            # A partial fill is a real position. The remainder may now be too small for the
            # exchange to accept, and submitting it would be an order known to fail -- the
            # same reasoning as _kraken_min_order_floor_notional in orchestrator.py.
            try:
                minimum_notional = self.pair_minimum_notional(pair, unit_price) if unit_price > 0 else None
            except Exception:  # noqa: BLE001 - an unavailable minimum must not block the decision below
                minimum_notional = None
            remaining_notional = remaining_volume * unit_price
            if minimum_notional is not None and remaining_notional < minimum_notional:
                partial_response = dict(limit_response)
                partial_response["quantity"] = filled_volume
                partial_response["filled_quantity"] = filled_volume
                partial_response["notional"] = filled_volume * unit_price
                partial_response["patient_limit_partially_filled"] = True
                partial_response["remainder_below_exchange_minimum"] = {
                    "remaining_volume": remaining_volume,
                    "remaining_notional": remaining_notional,
                    "exchange_minimum_notional": minimum_notional,
                }
                return partial_response

        # 2026-09-03, Founder-directed: "if the price moves substantially, then that changes the
        # whole nature of the trade. And so, yes, it's better to abandon that trade than to risk
        # the money."
        #
        # This is the market fallback: the patient order did not fill, so we are about to buy at
        # whatever the market asks. That is right when the price drifted a little and wrong when
        # it ran away -- after up to 300 seconds on coins that swing a median 5.6% a day, the
        # trade on offer may not be the trade that was analysed. Its entry is worse, its target
        # is further off, and the reward-to-risk that justified it has quietly become something
        # else.
        #
        # Checked against the CURRENT price, not the one from five minutes ago. A price that
        # moved in our favour is never a reason to abandon -- see entry_drift.
        try:
            latest = self.current_prices([pair]) if hasattr(self, "current_prices") else {}
            current_price = _kraken_last_price(latest, pair)
        except Exception:  # noqa: BLE001 - a price read must never crash order placement
            current_price = None
        # OrderRequest carries no entry price of its own -- notional/quantity IS the price
        # the proposal was sized against, the same derivation _limit_entry_price uses.
        try:
            intended_entry = float(order_request.notional_amount or 0.0) / float(order_request.quantity or 0.0)
        except (TypeError, ValueError, ZeroDivisionError):
            intended_entry = 0.0
        if current_price and intended_entry > 0:
            abandon, why = should_abandon_entry(
                intended_entry=intended_entry,
                current_price=current_price,
                side=order_request.side,
            )
            if abandon:
                return {
                    "status": "abandoned",
                    "broker": self.name,
                    "pair": pair,
                    "reason": why,
                    "intended_entry_price": intended_entry,
                    "price_when_abandoned": current_price,
                    "abandoned_from_unfilled_limit_order_id": order_id,
                }
        # 2026-09-05: the REMAINDER, never the original volume. This line previously read
        # check["volume"], so anything the limit order had already filled was bought a second
        # time. remaining_volume equals the original whenever nothing filled, so the ordinary
        # "patient order never rested" case is unchanged.
        fallback_volume = remaining_volume if filled_volume > 0 else check["volume"]
        market_payload = {
            "pair": pair,
            "type": order_request.side.lower(),
            "ordertype": "market",
            "volume": _format_decimal(fallback_volume),
            "validate": "false" if _bool_env("KRAKEN_SUBMIT_REAL_ORDERS", False) else "true",
        }
        userref = _userref(order_request.client_order_id)
        if userref is not None:
            market_payload["userref"] = str(userref)
        try:
            fallback_result = self._private_request("/0/private/AddOrder", market_payload)
        except RuntimeError as exc:
            return {
                "status": "rejected", "broker": self.name, "pair": pair,
                "reason": f"Patient limit entry {order_id} did not fill and the market fallback was also rejected: {exc}",
            }
        fallback_txids = fallback_result.get("result", {}).get("txid", [])
        fallback_order_id = fallback_txids[0] if fallback_txids else None
        # The position is what the limit order filled PLUS what the fallback just bought, so
        # that is what gets reported downstream -- the exit manager and the ledger must size
        # against the real holding, not against the fallback leg alone.
        total_quantity = filled_volume + fallback_volume
        return {
            "status": "accepted" if fallback_order_id else "submitted",
            "broker": self.name,
            "id": fallback_order_id,
            "order_id": fallback_order_id,
            "pair": pair,
            "side": order_request.side.lower(),
            "quantity": total_quantity,
            "notional": total_quantity * unit_price if unit_price else check["notional"],
            "kraken_result": fallback_result.get("result", {}),
            "fallback_from_unfilled_limit_order_id": order_id,
            "patient_limit_filled_quantity": filled_volume,
            "market_fallback_quantity": fallback_volume,
        }

    def _order_status(self, order_id: str) -> str | None:
        """The real Kraken status string ("open", "closed", "canceled", "expired", ...) for
        one order, or None if it cannot be determined -- treated as "assume gone" by the
        caller so a status-check failure can never leave a patient entry waiting forever."""
        return self._order_fill_state(order_id)[0]

    def _order_fill_state(self, order_id: str) -> tuple[str | None, float]:
        """Status AND how much of the order has already executed.

        2026-09-05 incident, real money. Reading `status` alone is not enough, and the
        difference cost roughly GBP 19 on the first live trade in eleven days.

        Kraken reports a PARTIALLY filled order that is still resting as "open" -- the same
        string as one that has not filled at all. `_await_fill_or_fallback_to_market` only
        returned early on "closed" (fully filled), so a limit order that had quietly filled
        most of the way still looked untouched when the patience budget expired. It was then
        cancelled and a market order was placed for the ORIGINAL volume, buying the whole
        position a second time.

        Measured on XRPGBP: the limit entry filled ~17.99 XRP in small pieces (Kraken's own
        minimum-sized chunks, which is simply how a thin GBP book fills), then the fallback
        bought a further 24.14 at market. Intended 24.14, actually acquired ~42.1 -- about
        1.75x the authorised size, with a stop loss sized for the smaller one.

        `vol_exec` is the field that was never read. Returning it alongside the status is the
        whole fix; the caller now nets it off.
        """
        result = self._private_request("/0/private/QueryOrders", {"txid": order_id})
        orders = result.get("result", {})
        order = orders.get(order_id)
        if not isinstance(order, dict):
            return None, 0.0
        try:
            filled = float(order.get("vol_exec") or 0.0)
        except (TypeError, ValueError):
            filled = 0.0
        return order.get("status"), filled

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
        volume = order_request.quantity
        if order_request.side.lower() == "sell":
            # A managed exit's recorded quantity is computed once at entry time
            # (notional / entry_price, full float precision) and can end up a hair
            # above Kraken's own rounded wallet balance for that asset -- Kraken
            # rejects a sell that exceeds the real balance even by a tiny epsilon
            # ("EOrder:Insufficient funds"). Capping to the live balance avoids that
            # without ever selling more than actually recorded quantity.
            available = self._available_balance(order_request.symbol)
            if available is not None and 0 < available < volume:
                volume = available
        payload = {
            "pair": pair,
            "type": order_request.side.lower(),
            "ordertype": "market",
            "volume": _format_decimal(volume),
            "validate": "false" if _bool_env("KRAKEN_SUBMIT_REAL_ORDERS", False) else "true",
        }
        userref = _userref(order_request.client_order_id)
        if userref is not None:
            payload["userref"] = str(userref)
        try:
            result = self._private_request("/0/private/AddOrder", payload)
        except RuntimeError as exc:
            # _private_request only raises RuntimeError when Kraken itself returned
            # a populated "error" array -- i.e. the request definitely reached Kraken
            # and Kraken definitively declined it (e.g. "EOrder:Insufficient funds").
            # That is a synchronous, unambiguous rejection, not the "we genuinely
            # don't know what happened" case (a network timeout would raise a
            # different exception type from inside urlopen/json.loads, before ever
            # reaching that check) -- so it is safe to report it as "rejected" and
            # let the caller release the order-intent lock for a legitimate retry.
            return {"status": "rejected", "broker": self.name, "reason": str(exc), "pair": pair}
        txids = result.get("result", {}).get("txid", [])
        order_id = txids[0] if txids else None
        return {
            "status": "accepted" if order_id else "submitted",
            "broker": self.name,
            "id": order_id,
            "order_id": order_id,
            "pair": pair,
            "side": order_request.side.lower(),
            "quantity": volume,
            "notional": order_request.notional_amount,
            "kraken_result": result.get("result", {}),
        }

    def place_trailing_stop_order(self, order_request: OrderRequest, trailing_pct: float) -> dict[str, Any]:
        """Place a native Kraken trailing-stop order so the stop-loss lives on Kraken's own
        order book instead of only in AI Trader's polling loop. Founder's stated reasoning
        (2026-08-19): the software-side trailing stop in monitor_managed_exits can only act
        while this process is up and Kraken is reachable -- a connectivity gap or heavy
        traffic during a bull run would leave an open position with no working exit. A
        native order is Kraken's own responsibility to trigger and fill, independent of
        AI Trader's uptime.
        """
        if not self.configured:
            return self._not_configured()
        if not _bool_env("KRAKEN_LIVE_TRADING_APPROVED", False):
            return {"status": "disabled", "broker": self.name, "reason": "KRAKEN_LIVE_TRADING_APPROVED is false"}
        if trailing_pct <= 0:
            return {"status": "rejected", "broker": self.name, "reason": "trailing_pct_invalid"}
        pair = order_request.broker_pair or _kraken_pair(order_request.symbol, order_request.quote_currency)
        volume = order_request.quantity
        if order_request.side.lower() == "sell":
            # Same reasoning as place_exit_order: the recorded quantity can end up a hair
            # above Kraken's own rounded wallet balance, so cap to what is actually available.
            available = self._available_balance(order_request.symbol)
            if available is not None and 0 < available < volume:
                volume = available
        payload = {
            "pair": pair,
            "type": order_request.side.lower(),
            "ordertype": "trailing-stop",
            "price": f"+{trailing_pct * 100:g}%",
            "volume": _format_decimal(volume),
            "validate": "false" if _bool_env("KRAKEN_SUBMIT_REAL_ORDERS", False) else "true",
        }
        userref = _userref(order_request.client_order_id)
        if userref is not None:
            payload["userref"] = str(userref)
        try:
            result = self._private_request("/0/private/AddOrder", payload)
        except RuntimeError as exc:
            # Same reasoning as place_order/place_exit_order: _private_request only raises
            # for Kraken's own populated "error" response, a definite synchronous rejection.
            return {"status": "rejected", "broker": self.name, "reason": str(exc), "pair": pair}
        txids = result.get("result", {}).get("txid", [])
        order_id = txids[0] if txids else None
        return {
            "status": "accepted" if order_id else "submitted",
            "broker": self.name,
            "id": order_id,
            "order_id": order_id,
            "pair": pair,
            "side": order_request.side.lower(),
            "quantity": volume,
            "trailing_pct": trailing_pct,
            "kraken_result": result.get("result", {}),
        }

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        if not self.configured:
            return self._not_configured()
        if not order_id:
            return {"status": "rejected", "broker": self.name, "reason": "order_id_missing"}
        try:
            result = self._private_request("/0/private/CancelOrder", {"txid": order_id})
        except RuntimeError as exc:
            # Kraken's real error string for an order that already filled, was already
            # cancelled, or never existed. Treated as a non-fatal "nothing left to cancel"
            # outcome rather than a failure, so a caller racing a native trailing-stop fill
            # against its own take-profit check can tell "it already triggered" apart from
            # "the cancel attempt itself failed and the order might still be live."
            if "unknown order" in str(exc).lower():
                return {"status": "already_resolved", "broker": self.name, "order_id": order_id, "reason": str(exc)}
            return {"status": "cancel_failed", "broker": self.name, "order_id": order_id, "reason": str(exc)}
        return {"status": "cancelled", "broker": self.name, "order_id": order_id, "kraken_result": result.get("result", {})}

    def _available_balance(self, symbol: str) -> float | None:
        account = self.get_account()
        balances = account.get("balances") if isinstance(account, dict) else None
        if not isinstance(balances, dict):
            return None
        target = symbol.upper()
        for key, value in balances.items():
            if _kraken_asset_symbol(key) == target:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return None

    def _validate_live_order(self, order_request: OrderRequest) -> dict[str, Any]:
        failures: list[str] = []
        if order_request.asset_type.lower() != "crypto":
            failures.append("asset_type_not_crypto")
        if order_request.side.lower() not in {"buy", "sell"}:
            failures.append("invalid_side")
        if order_request.side.lower() == "sell" and _bool_env("KRAKEN_BUY_ONLY_ENTRIES", True):
            failures.append("kraken_entry_sells_disabled")
        pair = order_request.broker_pair or _kraken_pair(order_request.symbol, order_request.quote_currency)
        allowed_pairs = _csv_env("KRAKEN_ALLOWED_PAIRS", "XBTGBP,ETHGBP,SOLGBP")
        if pair not in allowed_pairs:
            failures.append("pair_not_allowed")
        if order_request.quantity <= 0 or not math.isfinite(order_request.quantity):
            failures.append("quantity_invalid")
        notional = order_request.notional_amount or 0.0
        if notional <= 0:
            failures.append("notional_missing")
        # 2026-08-20, Founder-directed: cap order size as a PERCENTAGE of the cash actually
        # available rather than a fixed pound amount, "that way they can scale with the cash
        # available". The previous flat KRAKEN_MAX_ORDER_GBP (GBP 5) was a hard rejection
        # that silently capped every trade regardless of how much capital had been added --
        # so growing the account changed nothing. The percentage cap is authoritative; the
        # flat amount is kept only as the fallback for when the live balance cannot be read
        # (a failed balance call must not become an accidental green light).
        gbp_balance: float | None = None
        if order_request.side.lower() == "buy":
            balances = self.get_account().get("balances", {})
            gbp_balance = _balance_amount(balances, ("ZGBP", "GBP"))
            if gbp_balance is not None and gbp_balance < notional * 1.01:
                failures.append("insufficient_gbp_balance")
        # Raised 0.05 -> 0.10 (2026-08-22, Founder-directed): must move together with
        # AutoTradeConfig.crypto_max_trade_pct (models.py) -- this is the hard rejection
        # ceiling, so leaving it at 5% while the requested-size percentage moved to 10%
        # would have rejected every trade the sizing change was meant to produce, the
        # exact "three limits must move together" trap already documented in this file's
        # history (see the 2026-08-20 GBP 100 ledger incident above).
        max_order_pct = kraken_max_order_pct_of_cash()
        if gbp_balance is not None and max_order_pct > 0:
            max_notional = max(0.0, gbp_balance) * max_order_pct
        else:
            max_notional = _float_env("KRAKEN_MAX_ORDER_GBP", 5.0)
        if notional > max_notional:
            failures.append("max_order_amount_exceeded")
        allocation = _float_env("KRAKEN_TRADING_ALLOCATION_GBP", 100.0)
        if notional > allocation:
            failures.append("kraken_trading_allocation_exceeded")
        min_notional = _float_env("KRAKEN_MIN_ORDER_GBP", 1.0)
        if notional < min_notional:
            failures.append("min_order_amount_not_met")
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


def kraken_max_order_pct_of_cash() -> float:
    """The hard-rejection order ceiling, as a share of live GBP cash.

    Public and shared on purpose. broker_service.py reports this limit to the Founder while
    _validate_live_order enforces it; when each read the env var with its own default
    literal they drifted (reported 5% while 10% was enforced) -- the same "report the cap
    that is actually enforced" bug already fixed once in this codebase's history. One
    accessor makes reported and enforced the same number by construction.
    """
    return _float_env("KRAKEN_MAX_ORDER_PCT_OF_CASH", 0.10)


def kraken_limit_entries_enabled() -> bool:
    """Whether patient (maker-fee) limit entries are actually switched on right now.

    Surfaced through /activity/brokers trading_permissions so this can be VERIFIED rather
    than assumed. On 2026-08-22 four separate switches were each believed active while
    sitting off -- including this one, whose Render variable had been created under a
    misspelled name and so silently did nothing.
    """
    return _bool_env("KRAKEN_LIMIT_ENTRIES_ENABLED", False)


def _kraken_asset_symbol(asset: str) -> str:
    # Mirrors api/__init__.py's _kraken_asset_symbol (duplicated rather than imported
    # to avoid a circular import: api/__init__.py imports this module to build adapters).
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


def _float_or_zero(value: Any) -> float:
    """A number from a broker payload, or 0.0 when it is missing or unparseable.

    Used where a bad value must not raise mid-order-placement: an exception between a
    resting limit order and its fallback is how a partial fill gets orphaned.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0



def _limit_entry_price(order_request: Any) -> float | None:
    """The price to rest a patient buy at, or None to keep today's market order.

    Founder-directed 2026-08-20. Returns None unless KRAKEN_LIMIT_ENTRIES_ENABLED is on, so
    this ships inert: the behaviour change only begins when the market-order fallback that
    protects against an unfilled entry is wired and the Founder switches it on.

    Prices at or just below the intended entry, never above it. Paying MORE than the
    proposal's entry price to save a fee would be self-defeating -- the fee saved on this
    leg is 0.40%, so any slippage beyond that wipes out the whole point.
    """
    if not kraken_limit_entries_enabled():
        return None
    # OrderRequest carries no entry price of its own, but notional/quantity is exactly
    # that -- and it is the figure the proposal was actually sized against.
    try:
        notional = float(order_request.notional_amount or 0.0)
        quantity = float(order_request.quantity or 0.0)
    except (TypeError, ValueError):
        return None
    if notional <= 0 or quantity <= 0:
        return None
    # The ceiling only: the price the proposal was actually sized against. The caller
    # applies the offset ONLY when it has no live bid to rest at.
    #
    # 2026-08-25: this used to subtract the offset here, unconditionally, before the
    # caller capped the result at the live best bid. Measured against the real book that
    # morning, the spread on XRPGBP was 0.011% -- so subtracting 0.05% put the order
    # roughly 0.04% BELOW the best bid, where it fills only if the market ticks down.
    # Every buy therefore rested, failed to fill, took the market fallback and paid the
    # 0.80% taker rate: eight consecutive buys at 0.800%, with the maker switch verified
    # ON the whole time. The offset was making the order less likely to fill, which is
    # the opposite of what it was added to do.
    #
    # The best bid IS the maker-optimal price -- resting there is by definition not
    # paying above the market, and it is first in the queue for any seller who crosses.
    # An offset only helps where there is no live bid to aim at.
    return round(notional / quantity, 10)

def _userref(client_order_id: str | None) -> int | None:
    if not client_order_id:
        return None
    digest = hashlib.sha256(client_order_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 2_000_000_000