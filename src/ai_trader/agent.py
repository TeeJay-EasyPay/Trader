from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from .audit import AuditDatabase
from .broker_adapters import _kraken_last_price, _kraken_pair
from .guardrails import validate_trade_proposal
from .models import AccountContext, GuardrailConfig, TradeProposal
from .trading_intelligence import evaluate_trade_intelligence


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
            if not _has_latest_bar(symbol, market):
                self._no_trade_probe(
                    symbol,
                    market,
                    news,
                    reason="No latest market bar was returned. The symbol may be unsupported by the broker/data provider.",
                )
                continue
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
            intelligence = evaluate_trade_intelligence(
                self.audit.path,
                proposal,
                account,
                market=market,
                news=news,
                source="demo" if demo else "agent",
            )
            if intelligence is None:
                self.audit.record_execution_event(
                    proposal_id=proposal.proposal_id,
                    event_type="agent_no_trade",
                    payload={
                        "symbol": symbol,
                        "reason": "Trading Intelligence could not articulate both strongest argument for and strongest argument against.",
                    },
                )
                continue
            validation = validate_trade_proposal(proposal, account, self.guardrails, now=now)
            proposal = replace(
                proposal,
                ai_guardrails_passed=validation.passed,
                ai_guardrail_failures=validation.failures,
            )
            self.audit.record_trade_event("agent_proposal", proposal, validation=validation, intelligence=intelligence.to_dict())
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

    def _no_trade_probe(self, symbol: str, market: dict, news: dict, reason: str | None = None) -> TradeProposal | None:
        self.audit.record_execution_event(
            proposal_id=f"no-trade-{symbol}",
            event_type="agent_no_trade",
            payload={
                "symbol": symbol,
                "reason": reason or "No configured AI key or approved deterministic strategy produced a trade.",
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


def _has_latest_bar(symbol: str, market: dict) -> bool:
    bars = market.get("bars", {})
    return bool(bars.get(symbol) or bars.get(symbol.upper()))


def _news_summary(news: dict) -> str:
    items = news.get("news", [])
    if not items:
        return "No recent news returned."
    headlines = [str(item.get("headline") or item.get("summary") or "News item") for item in items[:3]]
    return " | ".join(headlines)


def propose_crypto_trades(
    db_path: Path,
    adapter: Any,
    symbols: list[str],
    account: AccountContext,
    guardrails: GuardrailConfig,
    audit: AuditDatabase,
    *,
    min_confidence: float,
    requested_notional: float,
    default_stop_loss_pct: float,
    now: datetime | None = None,
) -> list[TradeProposal]:
    """Generates crypto trade proposals from the same CRYPTO_RESEARCH_SCORES data the due
    diligence pipeline reads, so a proposal only exists when there's real evidence behind
    it - no LLM call, no floors, just the live technical/momentum/liquidity/risk scores
    computed from CoinGecko market data. Only proposes a long entry when the score clears
    the confidence bar and the 7-day trend is positive; otherwise the symbol is skipped."""
    proposals: list[TradeProposal] = []
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        for symbol in symbols:
            row = conn.execute(
                """
                SELECT * FROM CRYPTO_RESEARCH_SCORES WHERE UPPER(symbol) = UPPER(?)
                ORDER BY score_id DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if row is None:
                continue
            confidence = float(row["overall_due_diligence_score"] or 0.0)
            trend = row["technical_trend_score"]
            if confidence < min_confidence or trend is None or trend <= 0.5:
                audit.record_execution_event(
                    proposal_id=f"no-trade-crypto-{symbol}",
                    event_type="agent_no_trade",
                    payload={"symbol": symbol, "reason": "crypto_due_diligence_below_threshold_or_negative_trend", "score": dict(row)},
                )
                continue
            pair = _kraken_pair(symbol)
            prices = adapter.current_prices([pair]) if hasattr(adapter, "current_prices") else {}
            price = _kraken_last_price(prices, pair)
            if price is None or price <= 0:
                audit.record_execution_event(
                    proposal_id=f"no-trade-crypto-{symbol}",
                    event_type="agent_no_trade",
                    payload={"symbol": symbol, "reason": "current_price_not_available"},
                )
                continue
            stop_loss = round(price * (1 - default_stop_loss_pct), 8)
            take_profit = round(price * (1 + default_stop_loss_pct * 2), 8)
            quantity = requested_notional / price if price > 0 else 0.0
            risk_amount = quantity * abs(price - stop_loss)
            risk_percentage = risk_amount / account.equity if account.equity > 0 else 0.0
            reasoning = _json_loads(row["reasoning_json"]) or {}
            score_payload = dict(row)
            proposal = TradeProposal(
                symbol=symbol,
                side="buy",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size=quantity,
                risk_percentage=risk_percentage,
                confidence_score=confidence,
                news_summary=str(reasoning.get("note") or "Crypto research score reviewed."),
                market_sentiment_summary=f"7d trend score {trend}.",
                technical_summary=f"Momentum {row['momentum_score']}, volatility {row['volatility']}, liquidity {row['liquidity']}.",
                plain_english_reasoning=(
                    f"Live crypto due diligence score {confidence:.2f} with a positive 7-day trend "
                    f"and liquidity {row['liquidity']}."
                ),
                asset_type="crypto",
                exchange="KRAKEN",
                philosophy_fit=confidence,
            ).normalized()
            intelligence = evaluate_trade_intelligence(
                db_path,
                proposal,
                account,
                crypto_score=score_payload,
                source="crypto",
            )
            if intelligence is None:
                audit.record_execution_event(
                    proposal_id=f"no-trade-crypto-{symbol}",
                    event_type="agent_no_trade",
                    payload={
                        "symbol": symbol,
                        "reason": "Trading Intelligence could not articulate both strongest argument for and strongest argument against.",
                    },
                )
                continue
            validation = validate_trade_proposal(proposal, account, guardrails, now=now)
            proposal = replace(proposal, ai_guardrails_passed=validation.passed, ai_guardrail_failures=validation.failures)
            audit.record_trade_event("agent_proposal", proposal, validation=validation, intelligence=intelligence.to_dict())
            if validation.passed:
                proposals.append(proposal)
    return proposals


def _json_loads(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        import json

        data = json.loads(value)
        return data if isinstance(data, dict) else None
    except (TypeError, ValueError):
        return None
