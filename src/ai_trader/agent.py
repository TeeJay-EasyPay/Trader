from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Protocol

from .audit import AuditDatabase
from .guardrails import validate_trade_proposal
from .models import AccountContext, GuardrailConfig, TradeProposal


class MarketDataClient(Protocol):
    def get_latest_bars(self, symbols: list[str]) -> dict: ...
    def get_news(self, symbols: list[str], limit: int = 5) -> dict: ...


class ProposalAnalyzer(Protocol):
    def propose(self, symbol: str, market: dict, news: dict, account: AccountContext) -> TradeProposal | None: ...


class AITradingAgent:
    def __init__(
        self,
        *,
        market_data: MarketDataClient,
        audit: AuditDatabase,
        guardrails: GuardrailConfig,
        analyzer: ProposalAnalyzer | None = None,
    ):
        self.market_data = market_data
        self.audit = audit
        self.guardrails = guardrails
        self.analyzer = analyzer

    def propose_trades(
        self,
        symbols: list[str],
        account: AccountContext,
        *,
        demo: bool = False,
        now: datetime | None = None,
    ) -> list[TradeProposal]:
        proposals: list[TradeProposal] = []
        market = self.market_data.get_latest_bars(symbols)
        news = self.market_data.get_news(symbols, limit=5)

        for symbol in symbols:
            if demo:
                proposal = self._demo_proposal(symbol, market, news, account)
            elif self.analyzer is not None:
                proposal = self.analyzer.propose(symbol, market, news, account)
                if proposal is None:
                    self._no_trade_probe(symbol, market, news)
            else:
                proposal = self._no_trade_probe(symbol, market, news)
            if proposal is None:
                continue
            validation = validate_trade_proposal(proposal, account, self.guardrails, now=now)
            proposal = replace(
                proposal,
                ai_guardrails_passed=validation.passed,
                ai_guardrail_failures=validation.failures,
            )
            self.audit.record_trade_event("agent_proposal", proposal, validation=validation)
            if validation.passed:
                proposals.append(proposal)
        return proposals

    def _demo_proposal(self, symbol: str, market: dict, news: dict, account: AccountContext) -> TradeProposal:
        price = _latest_close(symbol, market) or 100.0
        risk_per_share = max(price * 0.01, 0.01)
        max_risk_dollars = account.equity * min(self.guardrails.max_risk_per_trade_pct, 0.005)
        qty = max(1, int(max_risk_dollars / risk_per_share))
        return TradeProposal(
            symbol=symbol,
            side="buy",
            entry_price=round(price, 2),
            stop_loss=round(price - risk_per_share, 2),
            take_profit=round(price + (risk_per_share * 2), 2),
            position_size=float(qty),
            risk_percentage=(risk_per_share * qty) / account.equity,
            confidence_score=max(self.guardrails.min_confidence_score, 0.72),
            news_summary=_news_summary(news),
            market_sentiment_summary="Demo sentiment is neutral-positive for paper validation.",
            technical_summary="Demo setup uses latest price with 1R stop and 2R target.",
            plain_english_reasoning="Demo proposal for end-to-end paper trading validation only.",
        ).normalized()

    def _no_trade_probe(self, symbol: str, market: dict, news: dict) -> TradeProposal | None:
        self.audit.record_execution_event(
            proposal_id=f"no-trade-{symbol}",
            event_type="agent_no_trade",
            payload={
                "symbol": symbol,
                "reason": "No configured AI key or approved deterministic strategy produced a trade.",
                "market": market,
                "news_summary": _news_summary(news),
            },
        )
        return None


def _latest_close(symbol: str, market: dict) -> float | None:
    bars = market.get("bars", {})
    row = bars.get(symbol) or bars.get(symbol.upper())
    if not row:
        return None
    value = row.get("c") or row.get("close")
    return None if value is None else float(value)


def _news_summary(news: dict) -> str:
    items = news.get("news", [])
    if not items:
        return "No recent news returned."
    headlines = [str(item.get("headline") or item.get("summary") or "News item") for item in items[:3]]
    return " | ".join(headlines)
