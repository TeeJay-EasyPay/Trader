from __future__ import annotations

import sqlite3
from .database import connect
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from .audit import AuditDatabase
from .database import connect
from .broker_adapters import _kraken_last_price, _kraken_pair
from .guardrails import validate_trade_proposal
from .models import AccountContext, GuardrailConfig, TradeProposal, utc_now_iso
from .proposal_context import build_proposal_context
from .trading_intelligence import evaluate_trade_intelligence

# 2026-08-15 (Founder-requested, following observed buy-high/sell-low entries): four
# deterministic gates layered onto the crypto entry heuristic below, each translating a
# specific passage already sitting inert in knowledge/*.md into an enforced check instead
# of decorative reasoning text (see agent.py's own Phase D comment on why this heuristic
# has no live LLM call to reason over that text directly). Kept as plain module constants,
# not full settings-plumbed config, matching the scope of a real-but-shallow first pass --
# revisit as config if they need per-environment tuning later.
CRYPTO_MAX_ENTRY_RANGE_POSITION = 0.75  # knowledge/momentum_vs_mean_reversion.md: don't buy into the top of a 24h range.
CRYPTO_BTC_WEAK_REGIME_THRESHOLD_PCT = -0.03  # knowledge/sector_crypto_l1_defi_tokens.md: BTC-correlation risk factor.
CRYPTO_RE_ENTRY_COOLDOWN_HOURS = 4.0  # Don't walk straight back into a symbol that just stopped this out.


class MarketDataClient(Protocol):
    def get_latest_bars(self, symbols: list[str]) -> dict: ...
    def get_news(self, symbols: list[str], limit: int = 5) -> dict: ...


class ProposalAnalyzer(Protocol):
    def propose(
        self, symbol: str, market: dict, news: dict, account: AccountContext, *, context: dict[str, str] | None = None
    ) -> TradeProposal | None: ...


class AITradingAgent:
    def __init__(
        self,
        *,
        market_data: MarketDataClient,
        audit: AuditDatabase,
        guardrails: GuardrailConfig,
        analyzer: ProposalAnalyzer | None = None,
        db_path: Path | None = None,
    ):
        self.market_data = market_data
        self.audit = audit
        self.guardrails = guardrails
        self.analyzer = analyzer
        # Phase C: real historical-analogue/backtest/external-intelligence/
        # knowledge-base context for the proposal LLM call. Optional and
        # defaults to the audit database (this agent already has a db_path
        # via audit.path) so existing callers that only pass market_data/
        # audit/guardrails/analyzer keep working unchanged.
        self.db_path = db_path or audit.path

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
                    try:
                        context = build_proposal_context(self.db_path, symbol=symbol, asset_type="stock")
                    except Exception:  # noqa: BLE001 - richer context is additive; its failure must never block a proposal
                        context = None
                    proposal = self.analyzer.propose(symbol, market, news, account, context=context)
                    if proposal is None:
                        self._no_trade_probe(symbol, market, news)
                    elif proposal.asset_type != "crypto":
                        real_exchange = self._known_exchange_for_symbol(symbol)
                        if real_exchange:
                            proposal = replace(proposal, exchange=real_exchange)
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

    def _known_exchange_for_symbol(self, symbol: str) -> str | None:
        """The symbol's real listing exchange from COMPANY_MASTER, if this system has one on file.

        2026-08-13 hosted incident: OpenAIProposalAnalyzer.propose's prompt never asks the model
        for `exchange` (see ai.py's field list) or `asset_type`, and TradeProposal.exchange
        defaults to "NYSE" when unset -- so every equity proposal this system has ever generated,
        for every symbol, silently inherited that default regardless of where the symbol is
        actually listed. Confirmed live: FRES (Fresnillo plc, correctly tagged "LSE" in this
        system's own COMPANY_MASTER seed data) kept being proposed with exchange="NYSE", routed
        to Alpaca (a US-only broker) via _proposal_broker's "not crypto -> alpaca" rule, and then
        failed asset_unavailable against Alpaca's real API on every single evaluation for over 4
        hours straight -- a permanent, self-inflicted dead end for any non-US symbol in the
        research watchlist, not a FRES-specific glitch.

        The LLM is never trusted for this: it's an operationally load-bearing routing field, and
        was never even asked for it. When COMPANY_MASTER has no row for this symbol, this
        returns None and the caller keeps TradeProposal's existing default -- unchanged behaviour
        for symbols this system has no exchange metadata for at all.
        """
        if self.db_path is None:
            return None
        try:
            with closing(connect(self.db_path)) as conn:
                row = conn.execute(
                    "SELECT exchange FROM COMPANY_MASTER WHERE ticker = ? ORDER BY updated_at DESC LIMIT 1",
                    (symbol.upper(),),
                ).fetchone()
        except Exception:  # noqa: BLE001 - a lookup failure must fall back to the existing default, never block a proposal
            return None
        return str(row[0]).strip().upper() if row and row[0] else None

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


def _kraken_range_position(prices: dict[str, Any], pair: str) -> float | None:
    """Where the current price sits within Kraken's own reported 24h high/low range:
    0.0 = at the 24h low, 1.0 = at the 24h high. None if range data is unavailable or
    degenerate (high == low). Kraken's Ticker response already carries `h`/`l` as
    [today, last24h] pairs alongside the `c` (last trade) field this module already
    reads for the current price -- this is the same payload already being fetched for
    every symbol, not an extra API call."""
    payload = prices.get(pair)
    if not isinstance(payload, dict):
        return None
    high, low, last = payload.get("h"), payload.get("l"), payload.get("c")
    if not (isinstance(high, list) and len(high) > 1 and isinstance(low, list) and len(low) > 1):
        return None
    try:
        high_24h, low_24h = float(high[1]), float(low[1])
        current = float(last[0]) if isinstance(last, list) and last else None
    except (TypeError, ValueError, IndexError):
        return None
    if current is None or high_24h <= low_24h:
        return None
    return max(0.0, min(1.0, (current - low_24h) / (high_24h - low_24h)))


def _kraken_btc_daily_change_pct(adapter: Any) -> float | None:
    """BTC's own same-session change (current price vs. today's Kraken-reported open),
    used as a simple crypto-market-regime proxy: a weak/volatile BTC session is a real
    portfolio-level risk factor for every altcoin regardless of that altcoin's own
    trend score (knowledge/sector_crypto_l1_defi_tokens.md). One extra ticker call per
    research batch, not per symbol -- callers should compute this once and reuse it."""
    try:
        prices = adapter.current_prices(["XBTGBP"]) if hasattr(adapter, "current_prices") else {}
    except Exception:  # noqa: BLE001 - a regime read that fails must never abort research
        return None
    payload = prices.get("XBTGBP") if isinstance(prices, dict) else None
    if not isinstance(payload, dict):
        return None
    try:
        current = float(payload["c"][0])
        open_price = float(payload["o"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if open_price <= 0:
        return None
    return (current - open_price) / open_price


def _recently_stopped_out(db_path: Path, *, broker: str, symbol: str, since_iso: str) -> bool:
    """True if this symbol has a managed position closed by its own stop-loss more
    recently than since_iso -- stops a fresh proposal from walking straight back into
    a level that just failed on the exact same symbol."""
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT 1 FROM MANAGED_TRADE_EXITS
            WHERE broker = ? AND symbol = ? AND status = 'closed'
              AND exit_reason = 'stop_loss_triggered' AND updated_at >= ?
            LIMIT 1
            """,
            (broker.lower(), symbol.upper(), since_iso),
        ).fetchone()
    return row is not None


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
    # Computed once per batch, not per symbol: a stop-loss lookback cutoff (no-immediate-
    # re-entry gate) and a single BTC regime read (BTC-regime gate) reused for every
    # altcoin evaluated this cycle.
    cooldown_cutoff_iso = (
        (now or datetime.now(timezone.utc)).astimezone(timezone.utc) - timedelta(hours=CRYPTO_RE_ENTRY_COOLDOWN_HOURS)
    ).isoformat()
    btc_change_pct = _kraken_btc_daily_change_pct(adapter)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        for symbol in symbols:
            print(f"[crypto-research] symbol={symbol} stage=evaluating", flush=True)
            row = conn.execute(
                """
                SELECT * FROM CRYPTO_RESEARCH_SCORES WHERE UPPER(symbol) = UPPER(?)
                ORDER BY score_id DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if row is None:
                print(f"[crypto-research] symbol={symbol} stage=completed outcome=no_research_score", flush=True)
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
                print(f"[crypto-research] symbol={symbol} stage=completed outcome=below_threshold", flush=True)
                if on_symbol_complete:
                    on_symbol_complete(symbol, [])
                continue
            if _recently_stopped_out(db_path, broker="kraken", symbol=symbol, since_iso=cooldown_cutoff_iso):
                audit.record_execution_event(
                    proposal_id=f"no-trade-crypto-{symbol}",
                    event_type="agent_no_trade",
                    payload={"symbol": symbol, "reason": "recently_stopped_out", "cooldown_hours": CRYPTO_RE_ENTRY_COOLDOWN_HOURS},
                )
                print(f"[crypto-research] symbol={symbol} stage=completed outcome=recent_stop_loss_cooldown", flush=True)
                if on_symbol_complete:
                    on_symbol_complete(symbol, [])
                continue
            if symbol.upper() != "BTC" and btc_change_pct is not None and btc_change_pct <= CRYPTO_BTC_WEAK_REGIME_THRESHOLD_PCT:
                audit.record_execution_event(
                    proposal_id=f"no-trade-crypto-{symbol}",
                    event_type="agent_no_trade",
                    payload={"symbol": symbol, "reason": "btc_weak_regime", "btc_change_pct": btc_change_pct},
                )
                print(f"[crypto-research] symbol={symbol} stage=completed outcome=btc_weak_regime btc_change_pct={btc_change_pct:.4f}", flush=True)
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
                print(f"[crypto-research] symbol={symbol} stage=completed outcome=pair_unavailable", flush=True)
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
                print(f"[crypto-research] symbol={symbol} stage=completed outcome=no_current_price", flush=True)
                if on_symbol_complete:
                    on_symbol_complete(symbol, [])
                continue
            range_position = _kraken_range_position(prices, pair)
            if range_position is not None and range_position > CRYPTO_MAX_ENTRY_RANGE_POSITION:
                audit.record_execution_event(
                    proposal_id=f"no-trade-crypto-{symbol}",
                    event_type="agent_no_trade",
                    payload={"symbol": symbol, "reason": "entry_too_extended_in_24h_range", "range_position": range_position},
                )
                print(f"[crypto-research] symbol={symbol} stage=completed outcome=entry_too_extended range_position={range_position:.2f}", flush=True)
                if on_symbol_complete:
                    on_symbol_complete(symbol, [])
                continue
            # Volatility-scaled stop distance (knowledge/stop_loss_and_take_profit_mechanics.md
            # + sector_crypto_l1_defi_tokens.md's note that crypto stops are more readily
            # triggered by ordinary liquidity gaps than in equities): a calmer coin keeps the
            # base stop; a more volatile one gets proportionally more room, rather than every
            # coin being held to one flat percentage regardless of its own behaviour.
            # take_profit keeps the same 2:1 reward:risk ratio against whatever the effective
            # stop distance ends up being.
            volatility_score = row["volatility"]
            volatility_multiplier = 1.0 + max(0.0, min(1.0, float(volatility_score))) if volatility_score is not None else 1.0
            effective_stop_pct = default_stop_loss_pct * volatility_multiplier
            stop_loss = round(price * (1 - effective_stop_pct), 8)
            take_profit = round(price * (1 + effective_stop_pct * 2), 8)
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
                print(f"[crypto-research] symbol={symbol} stage=completed outcome=no_bull_bear_case", flush=True)
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
            if validation.passed:
                # Phase D: the same historical-analogue/backtest/external-intelligence/
                # knowledge-base context Phase C gives the Alpaca LLM proposal call, folded
                # into this already-deterministic-and-approved crypto proposal's reasoning
                # text for transparency and audit -- not a gate. This governed path has no
                # LLM call at all (propose_crypto_trades never had one, and adding a live,
                # synchronous OpenAI call into this job's per-symbol loop is a separate,
                # larger decision involving real timeout and real-money-veto tradeoffs not
                # made here) and this enrichment never changes whether validation.passed or
                # the proposal's price/size/stop/target -- only what its reasoning text says.
                try:
                    context = build_proposal_context(db_path, symbol=symbol, asset_type="crypto")
                    # 2026-08-15 incident: reference_material (the actual curated knowledge-base
                    # excerpts) was fetched here and then silently dropped -- never included below,
                    # so it never even reached this proposal's own reasoning text, let alone
                    # influenced anything. Every other piece build_proposal_context returns was
                    # included; this one was missing outright, not just non-gating like the rest.
                    context_note = (
                        f"\n\nAdditional context: {context['historical_analogues']} "
                        f"{context['backtest_evidence']} {context['external_intelligence']}\n\n"
                        f"Reference material: {context['reference_material']}"
                    ).strip()
                    proposal = replace(proposal, plain_english_reasoning=(proposal.plain_english_reasoning or "") + context_note)
                except Exception:  # noqa: BLE001 - enrichment is additive; its failure must never block a proposal
                    pass
            audit.record_trade_event("agent_proposal", proposal, validation=validation, intelligence=intelligence.to_dict())
            if validation.passed:
                proposals.append(proposal)
                print(f"[crypto-research] symbol={symbol} stage=completed outcome=proposal_generated", flush=True)
                if on_symbol_complete:
                    on_symbol_complete(symbol, [proposal])
            else:
                # 2026-08-16: Founder asked whether the consistent zero-recommendations
                # streak means the gates are too strict or something is broken -- the prior
                # log line just said "guardrails_failed" with no detail, and /recommendations
                # doesn't surface crypto rows in the confidence-sorted top 50 (equity
                # proposals dominate), so there was no cheap way to see which check actually
                # failed. Logging the real failure list closes that gap.
                print(
                    f"[crypto-research] symbol={symbol} stage=completed outcome=guardrails_failed "
                    f"failures={validation.failures}",
                    flush=True,
                )
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
