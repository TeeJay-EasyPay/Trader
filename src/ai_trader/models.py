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

