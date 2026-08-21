from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class GuardrailConfig:
    max_risk_per_trade_pct: float = 0.01
    max_daily_loss_pct: float = 0.03
    max_open_positions: int = 3
    min_confidence_score: float = 0.65
    paper_trading_only: bool = True
    allow_short_selling: bool = False


@dataclass(frozen=True)
class AutoTradeConfig:
    enabled: bool = False
    broker_enabled: dict[str, bool] = field(default_factory=dict)
    min_confidence: float = 0.85
    min_philosophy_fit: float = 0.85
    max_trade_amount: float = 25.0
    default_stop_loss_pct: float = 0.03
    max_stop_loss_pct: float = 0.05
    crypto_max_trade_amount: float = 10.0
    # Founder-directed 2026-08-20: size as a share of available capital so trades scale
    # with the account instead of being pinned to a flat pound amount.
    # Raised 0.05 -> 0.10 (2026-08-22, Founder-directed: "trade larger, e.g. GBP 50 instead
    # of GBP 25"). Live trade history showed real recent entries landing at ~GBP 2 (Kraken's
    # own order minimum) -- reconstructing the OLD formula against a real trade's actual
    # entry/stop does NOT reproduce GBP 2 (it lands near the old GBP 25 ceiling instead), so
    # that specific historical pattern is not explained by this change and remains an open
    # question, separate from the deliberate size increase here. 10% of a GBP 500
    # allocation is the requested ~GBP 50 ceiling.
    crypto_max_trade_pct: float = 0.10
    # Founder-directed 2026-08-20: size crypto from the money at risk rather than a flat
    # amount, so choosing a wider stop shrinks the position instead of risking more.
    # Raised 0.0015 -> 0.005 (2026-08-22, Founder-directed) so the risk budget itself (GBP
    # 2.50 on a GBP 500 account) is large enough that the percentage-of-cash ceiling above,
    # not an unrelated tiny risk budget, is what actually determines typical trade size: at
    # a 5% (policy-maximum) stop distance it lands exactly on the new GBP 50 ceiling, and
    # only sizes smaller than that when a genuinely tighter stop justifies it.
    crypto_risk_per_trade_pct: float = 0.005
    # Minimum reward-to-risk AFTER trading costs. 1.0 only removes trades that cannot pay
    # for themselves; it is a floor, not a second opinion on trade quality.
    crypto_min_net_reward_risk: float = 1.0
    # Founder-directed 2026-08-20: tightened 0.02 -> 0.015. His reasoning: the market has
    # bottomed and looks like turning, so downside room matters less than keeping the loss
    # small if a trade is wrong. Tradeoff stated plainly to him: a tighter stop on an asset
    # with ~4% daily ATR will be hit more often by ordinary noise.
    crypto_default_stop_loss_pct: float = 0.015
    crypto_max_stop_loss_pct: float = 0.05


@dataclass(frozen=True)
class Position:
    symbol: str
    qty: float
    market_value: float = 0.0
    unrealized_pl: float = 0.0


@dataclass(frozen=True)
class AccountContext:
    equity: float
    daily_realized_pnl: float
    open_positions: list[Position] = field(default_factory=list)
    is_paper: bool = True
    timestamp: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class TradeProposal:
    symbol: str
    side: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    risk_percentage: float
    confidence_score: float
    news_summary: str
    market_sentiment_summary: str
    technical_summary: str
    plain_english_reasoning: str
    proposal_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now_iso)
    ai_guardrails_passed: bool = False
    ai_guardrail_failures: list[str] = field(default_factory=list)
    asset_type: str = "stock"
    exchange: str = "NYSE"
    philosophy_fit: float = 0.0
    intelligence: dict[str, Any] | None = None
    strategy_id: str = ""

    def normalized(self) -> "TradeProposal":
        return TradeProposal(
            proposal_id=self.proposal_id,
            created_at=self.created_at,
            symbol=self.symbol.upper().strip(),
            side=self.side.lower().strip(),
            entry_price=float(self.entry_price),
            stop_loss=float(self.stop_loss),
            take_profit=float(self.take_profit),
            position_size=float(self.position_size),
            risk_percentage=float(self.risk_percentage),
            confidence_score=float(self.confidence_score),
            news_summary=self.news_summary.strip(),
            market_sentiment_summary=self.market_sentiment_summary.strip(),
            technical_summary=self.technical_summary.strip(),
            plain_english_reasoning=self.plain_english_reasoning.strip(),
            ai_guardrails_passed=bool(self.ai_guardrails_passed),
            ai_guardrail_failures=list(self.ai_guardrail_failures),
            asset_type=self.asset_type.lower().strip() or "stock",
            exchange=self.exchange.upper().strip() or "NYSE",
            philosophy_fit=float(self.philosophy_fit or 0),
            intelligence=dict(self.intelligence) if isinstance(self.intelligence, dict) else None,
            strategy_id=str(self.strategy_id or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TradeProposal":
        fields = TradeProposal.__dataclass_fields__
        payload = {key: value for key, value in data.items() if key in fields}
        return TradeProposal(**payload).normalized()


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    checked_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str
    quantity: float
    asset_type: str
    exchange: str
    stop_loss: float
    take_profit: float
    notional_amount: float | None = None
    client_order_id: str | None = None
    quote_currency: str = "GBP"
    broker_pair: str | None = None


@dataclass(frozen=True)
class OrchestratorDecision:
    recommendation_id: str
    symbol: str
    asset_type: str
    exchange: str
    requested_action: str
    confidence_score: float
    philosophy_fit: float
    selected_broker: str | None
    market_open: bool
    asset_available: bool
    guardrails_passed: bool
    decision: str
    rejection_reason: str | None = None
    order_id: str | None = None
    notes: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
