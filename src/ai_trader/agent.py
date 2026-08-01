from __future__ import annotations

import sqlite3
from .database import connect
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from .audit import AuditDatabase
from .database import connect
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
        skipped_symbols: list[dict[str, str]] | None = None,
    ) -> list[TradeProposal]:
        """Fetch market/news data once for the whole batch, then evaluate each symbol.

        `run_analysis` used to call this once per symbol, which meant one full
        `get_latest_bars`/`get_news` HTTP round trip *per symbol* (60 calls for a 30-symbol
        watchlist) on top of a per-symbol OpenAI call -- confirmed as the reason equity research
        was consistently timing out before generating any proposals, since the batch fetch is a
        single call regardless of symbol count. `skipped_symbols`, if given, is appended to with
        a reason for every symbol that could not produce a proposal, preserving the per-symbol
        fault isolation the old per-symbol caller relied on.
        """
        proposals: list[TradeProposal] = []
        try:
            market = self.market_data.get_latest_bars(symbols)
            news = self.market_data.get_news(symbols, limit=5)
        except Exception as exc:
            reason = str(exc)
            if skipped_symbols is not None:
                skipped_symbols.extend({"symbol": symbol, "reason": reason} for symbol in symbols)
            for symbol in symbols:
                self.audit.record_execution_event(
                    f"analysis-skip-{symbol}",
                    "agent_no_trade",
                    {"symbol": symbol, "reason": reason},
                )
            return proposals

        for symbol in symbols:
            try:
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
                    intelligence=intelligence.to_dict(),
                    strategy_id=str(intelligence.strategy.get("strategy_id") or ""),
                )
                self.audit.record_trade_event("agent_proposal", proposal, validation=validation, intelligence=intelligence.to_dict())
                if validation.passed:
                    proposals.append(proposal)
            except Exception as exc:
                reason = str(exc)
                if skipped_symbols is not None:
                    skipped_symbols.append({"symbol": symbol, "reason": reason})
                self.audit.record_execution_event(
                    f"analysis-skip-{symbol}",
                    "agent_no_trade",
                    {"symbol": symbol, "reason": reason},
                )
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
    on_symbol_complete: Callable[[str, list[TradeProposal]], None] | None = None,
) -> list[TradeProposal]:
    """Generates crypto trade proposals from the same CRYPTO_RESEARCH_SCORES data the due
    diligence pipeline reads, so a proposal only exists when there's real evidence behind
    it - no LLM call, no floors, just the live technical/momentum/liquidity/risk scores
    computed from CoinGecko market data. Only proposes a long entry when the score clears
    the confidence bar and the 7-day trend is positive; otherwise the symbol is skipped.

    on_symbol_complete, if given, fires immediately after each symbol's outcome is known
    (empty list if skipped/rejected) so a caller can persist research-freshness evidence
    per symbol instead of only after the whole batch returns -- a single shared connection
    for the batch is still opened below, so this adds no per-symbol connection overhead."""
    proposals: list[TradeProposal] = []
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        for symbol in symbols:
            print(f"[overnight-crypto] symbol={symbol} stage=evaluating", flush=True)
            row = conn.execute(
                """
                SELECT * FROM CRYPTO_RESEARCH_SCORES WHERE UPPER(symbol) = UPPER(?)
                ORDER BY score_id DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if row is None:
                print(f"[overnight-crypto] symbol={symbol} stage=completed outcome=no_research_score", flush=True)
                if on_symbol_complete:
                    on_symbol_complete(symbol, [])
                continue
            confidence = float(row["overall_due_diligence_score"] or 0.0)
            trend = row["technical_trend_score"]
            if confidence < min_confidence or trend is None or trend <= 0.5:
                audit.record_execution_event(
                    proposal_id=f"no-trade-crypto-{symbol}",
                    event_type="agent_no_trade",
                    payload={"symbol": symbol, "reason": "crypto_due_diligence_below_threshold_or_negative_trend", "score": dict(row)},
                )
                print(f"[overnight-crypto] symbol={symbol} stage=completed outcome=below_threshold", flush=True)
                if on_symbol_complete:
                    on_symbol_complete(symbol, [])
                continue
            pair = _kraken_pair(symbol)
            try:
                prices = adapter.current_prices([pair]) if hasattr(adapter, "current_prices") else {}
            except Exception as exc:  # noqa: BLE001 - one unavailable pair must not abort the research cycle
                audit.record_execution_event(
                    proposal_id=f"no-trade-crypto-{symbol}",
                    event_type="agent_no_trade",
                    payload={"symbol": symbol, "pair": pair, "reason": "kraken_pair_unavailable", "detail": str(exc)},
                )
                print(f"[overnight-crypto] symbol={symbol} stage=completed outcome=pair_unavailable", flush=True)
                if on_symbol_complete:
                    on_symbol_complete(symbol, [])
                continue
            price = _kraken_last_price(prices, pair)
            if price is None or price <= 0:
                audit.record_execution_event(
                    proposal_id=f"no-trade-crypto-{symbol}",
                    event_type="agent_no_trade",
                    payload={"symbol": symbol, "reason": "current_price_not_available"},
                )
                print(f"[overnight-crypto] symbol={symbol} stage=completed outcome=no_current_price", flush=True)
                if on_symbol_complete:
                    on_symbol_complete(symbol, [])
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
                print(f"[overnight-crypto] symbol={symbol} stage=completed outcome=no_bull_bear_case", flush=True)
                if on_symbol_complete:
                    on_symbol_complete(symbol, [])
                continue
            validation = validate_trade_proposal(proposal, account, guardrails, now=now)
            proposal = replace(
                proposal,
                ai_guardrails_passed=validation.passed,
                ai_guardrail_failures=validation.failures,
                intelligence=intelligence.to_dict(),
                strategy_id=str(intelligence.strategy.get("strategy_id") or ""),
            )
            audit.record_trade_event("agent_proposal", proposal, validation=validation, intelligence=intelligence.to_dict())
            if validation.passed:
                proposals.append(proposal)
                print(f"[overnight-crypto] symbol={symbol} stage=completed outcome=proposal_generated", flush=True)
                if on_symbol_complete:
                    on_symbol_complete(symbol, [proposal])
            else:
                print(f"[overnight-crypto] symbol={symbol} stage=completed outcome=guardrails_failed", flush=True)
                if on_symbol_complete:
                    on_symbol_complete(symbol, [])
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
