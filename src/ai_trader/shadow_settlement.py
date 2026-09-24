"""Broker-separated, versioned inputs for legacy shadow settlement.

The legacy shadow journal predates the governed experiment engine.  It may share a
result *shape*, but equity and crypto records must never share price, calendar or
cost assumptions.  Adapters convert each broker's row into one canonical contract;
the settlement arithmetic can then remain common and auditable.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .alpaca_costs import estimate_alpaca_round_trip_cost


SETTLEMENT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class CanonicalShadow:
    schema_version: int
    shadow_trade_id: Any
    broker: str
    asset_class: str
    currency: str
    symbol: str
    market_symbol: str
    entry: float
    stop: float
    target: float
    quantity: float | None
    cost_basis: str
    simulated_costs: dict[str, Any]


class SettlementAdapter:
    broker = ""
    asset_class = ""
    currency = ""

    def market_symbol(self, symbol: str) -> str:
        return symbol.upper()

    def cost_r(self, trade: CanonicalShadow, risk_per_unit: float) -> float | None:
        raise NotImplementedError

    def normalize(self, row: dict[str, Any]) -> CanonicalShadow:
        broker = str(row.get("intended_broker") or "").strip().lower()
        asset = str(row.get("asset_type") or "").strip().lower()
        if broker != self.broker or (asset and asset != self.asset_class):
            raise ValueError(f"{broker or 'unknown'} / {asset or 'unknown'} is not supported by {self.broker}")
        entry = _positive(row.get("intended_entry"), "entry")
        stop = _positive(row.get("stop_loss"), "stop")
        target = _positive(row.get("take_profit"), "target")
        if not stop < entry < target:
            raise ValueError("Only a complete long setup with stop < entry < target can be settled")
        quantity = _optional_positive(row.get("quantity"))
        return CanonicalShadow(
            schema_version=SETTLEMENT_SCHEMA_VERSION,
            shadow_trade_id=row.get("shadow_trade_id"),
            broker=self.broker,
            asset_class=self.asset_class,
            currency=self.currency,
            symbol=str(row.get("symbol") or "").strip().upper(),
            market_symbol=self.market_symbol(str(row.get("symbol") or "")),
            entry=entry,
            stop=stop,
            target=target,
            quantity=quantity,
            cost_basis=self.cost_basis(row),
            simulated_costs=_json_object(row.get("simulated_costs_json")),
        )

    def cost_basis(self, row: dict[str, Any]) -> str:
        return "broker_specific_estimate"


class KrakenSettlementAdapter(SettlementAdapter):
    broker = "kraken"
    asset_class = "crypto"
    currency = "GBP"

    def market_symbol(self, symbol: str) -> str:
        normalized = symbol.replace("/", "").replace("-", "").upper()
        return normalized if normalized.endswith("GBP") else normalized + "GBP"

    def cost_basis(self, row: dict[str, Any]) -> str:
        costs = _json_object(row.get("simulated_costs_json"))
        return "stored_simulated_cost" if _stored_cost_pct(costs) is not None else "kraken_measured_fee_fallback"

    def cost_r(self, trade: CanonicalShadow, risk_per_unit: float) -> float:
        pct = _stored_cost_pct(trade.simulated_costs)
        if pct is None:
            pct = 0.0158
        return pct * trade.entry / risk_per_unit


class AlpacaSettlementAdapter(SettlementAdapter):
    broker = "alpaca"
    asset_class = "equity"
    currency = "USD"

    def cost_basis(self, row: dict[str, Any]) -> str:
        return "stored_simulated_cost" if _stored_cost_amount(_json_object(row.get("simulated_costs_json"))) is not None else "alpaca_published_regulatory_formula"

    def cost_r(self, trade: CanonicalShadow, risk_per_unit: float) -> float | None:
        amount = _stored_cost_amount(trade.simulated_costs)
        quantity = trade.quantity
        if amount is None:
            # Old rows without quantity cannot be assigned a plausible per-trade equity
            # cost.  Refusing to guess preserves the evidence boundary.
            if quantity is None:
                return None
            amount = estimate_alpaca_round_trip_cost(
                sell_notional=trade.target * quantity, quantity=quantity
            )["estimated_round_trip_fee_usd"]
        if quantity is None or quantity <= 0:
            return None
        return float(amount) / (risk_per_unit * quantity)


ADAPTERS: dict[str, SettlementAdapter] = {
    "kraken": KrakenSettlementAdapter(),
    "alpaca": AlpacaSettlementAdapter(),
}


def adapter_for(broker: str) -> SettlementAdapter:
    try:
        return ADAPTERS[str(broker or "").strip().lower()]
    except KeyError as exc:
        raise ValueError(f"No shadow settlement adapter for broker {broker!r}") from exc


def _positive(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Missing {name}") from exc
    if number <= 0:
        raise ValueError(f"Invalid {name}")
    return number


def _optional_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _stored_cost_pct(costs: dict[str, Any]) -> float | None:
    for key in ("round_trip_fee_pct", "fee_pct", "estimated_round_trip_fee_pct"):
        value = _optional_positive(costs.get(key))
        if value is not None:
            return value / 100 if value > 0.25 else value
    return None


def _stored_cost_amount(costs: dict[str, Any]) -> float | None:
    for key in ("estimated_round_trip_fee_usd", "total_fee", "fees"):
        value = _optional_positive(costs.get(key))
        if value is not None:
            return value
    return None
