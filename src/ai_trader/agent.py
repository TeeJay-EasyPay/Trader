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
from .operational import safe_score
from .proposal_context import build_proposal_context
from .liquidity_map import liquidity_map_for_pair
from .sprint6 import _ai_managed_symbols
from .symbol_track_record import symbol_track_record
from .market_intelligence_platform import load_recent_observations_batch
from .technical_discretion import (
    clears_fee_hurdle,
    risk_based_notional,
    technical_stop_loss,
    technical_take_profit,
)
from .trading_intelligence import analyze_price_series, evaluate_trade_intelligence, load_recent_candles_batch

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

        # Phase 2 of the CIO-level forecasting build (2026-08-20): analyze_price_series/
        # infer_market_regime were already called on every proposal via
        # evaluate_trade_intelligence below, but starved to a single current-price bar --
        # HISTORICAL_CANDLES has had real daily equity history since the strategy-lab
        # work, just never reached this live path. Additive only: on any read failure,
        # market["history"] is simply absent and _candles_for_symbol falls back to its
        # existing single-bar behavior, same "must never block a proposal" convention as
        # build_proposal_context below.
        if self.db_path is not None:
            try:
                market["history"] = load_recent_candles_batch(self.db_path, symbols=symbols, asset_type="stock", timeframe="1d", limit=120)
            except Exception:  # noqa: BLE001
                pass

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
                        philosophy_fit = self._watchlist_philosophy_fit(symbol)
                        if philosophy_fit is not None:
                            proposal = replace(proposal, philosophy_fit=philosophy_fit)
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

    def _watchlist_philosophy_fit(self, symbol: str) -> float | None:
        """This system's own recorded view of how well a company fits the investment
        philosophy, from INVESTMENT_WATCHLIST.

        2026-08-24 hosted finding: exactly the same class of bug as
        _known_exchange_for_symbol above. ai.py's prompt never asks the model for
        philosophy_fit, TradeProposal.from_dict only keeps fields the model returned, and
        the field defaults to 0.0 -- so every equity proposal this system has ever
        generated carried philosophy_fit 0.0, while the crypto path sets it explicitly
        (agent.py's crypto branch). Zero fails three separate gates at once:
        philosophy_fit_below_auto_trade_minimum, investment_policy_score_below_minimum,
        and investment_policy_status -> due_diligence_incomplete.

        Confirmed live that day: Alpaca produced 14 fresh, guardrail-passing equity
        recommendations at confidence 0.85-0.87 and every one was rejected with those
        three reasons, with the account sitting 100% in cash. The values were in the
        database the whole time (FSLR 0.9, NEE 0.9, MLM 0.9, NVDA 0.75, AAPL 0.75) and
        the display layer already joined them for the app -- only the proposal that gets
        judged never carried one.

        Deliberately NOT the model's confidence score: that is already checked separately
        as min_ai_confidence, and reusing it here would make this gate a duplicate of
        that one rather than the independent business-fit check it exists to be. Returns
        None when this system holds no assessment, leaving the existing default so a
        company it has never assessed cannot auto-trade on an invented score.
        """
        if self.db_path is None:
            return None
        try:
            with closing(connect(self.db_path)) as conn:
                row = conn.execute(
                    """
                    SELECT iw.current_investment_philosophy_fit
                    FROM INVESTMENT_WATCHLIST iw
                    JOIN COMPANY_MASTER cm ON cm.id = iw.company_id
                    WHERE UPPER(cm.ticker) = UPPER(?)
                    ORDER BY iw.id DESC LIMIT 1
                    """,
                    (symbol,),
                ).fetchone()
        except Exception:  # noqa: BLE001 - a lookup failure must fall back to the existing default, never block a proposal
            return None
        # Stored qualitatively ("Strong", "Moderate") as often as numerically, which is
        # why every reader of this column goes through safe_score -- float() raises on the
        # real seed data. QUALITATIVE_SCORES maps the words to the same 0-1 scale the
        # gates compare against.
        return safe_score(row[0]) if row else None

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
    # 2026-08-20 live finding: this MUST be the real policy ceiling, not the default.
    # See the technical_stop_loss call below for the bug this fixes.
    max_stop_loss_pct: float = 0.05,
    now: datetime | None = None,
    on_symbol_complete: Callable[[str, list[TradeProposal]], None] | None = None,
    reviewer: Any = None,
    # Founder-directed 2026-08-20. risk_budget=None keeps the previous flat sizing, so an
    # existing caller is unaffected until it opts in. round_trip_fee_pct=0 disables the
    # fee gate entirely rather than blocking every trade on an unknown cost.
    risk_budget: float | None = None,
    round_trip_fee_pct: float = 0.0,
    min_net_reward_risk: float = 1.0,
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
    # Phase 2 of the CIO-level forecasting build (2026-08-20): evaluate_trade_intelligence
    # was already called for every crypto proposal below, but never even received a
    # `market` kwarg at all -- analyze_price_series/infer_market_regime saw nothing.
    # Real Kraken candle history exists now (Phase 1, MARKET_DATA_OBSERVATIONS); read once
    # for the whole batch, not per symbol. On any read failure this is simply an empty
    # dict and every symbol falls back to today's crypto_score-only behavior -- additive,
    # never blocks a proposal.
    try:
        crypto_candle_history = load_recent_observations_batch(db_path, [symbol.upper() for symbol in symbols], timeframe="1d", limit=120)
    except Exception:  # noqa: BLE001
        crypto_candle_history = {}
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
            # Phase 5.5 (2026-08-20, Founder-requested): place the stop/target at REAL
            # technical levels from the price history Phase 1/2 now provide, instead of a
            # flat percentage -- but clamped so the result can never be riskier than the
            # flat calculation above would have been. Discretion within the mandate, never
            # authority to rewrite it (see technical_discretion.py's module docstring).
            # max_stop_loss_pct here is the effective volatility-scaled distance, so this
            # can only ever tighten the stop relative to today's behavior, never widen it.
            symbol_candles = crypto_candle_history.get(symbol.upper()) or []
            symbol_metrics = analyze_price_series(symbol_candles) if symbol_candles else {}
            atr_absolute = symbol_metrics.get("atr_pct") * price if symbol_metrics.get("atr_pct") else None
            # 2026-08-20 live verification caught a real bug here: this originally passed
            # effective_stop_pct as BOTH the ceiling and the default, so the clamp ceiling
            # equalled the fallback -- any support level further than the default distance
            # clamped exactly back to it. Since support (a 20-day low) is almost always
            # further than ~2% away on a trending asset, the technical stop was inert in
            # the common case: a live XLM proposal came out at exactly 2.0000%/4.0000%,
            # i.e. the flat calculation, despite XLM having real stored candle history.
            # The ceiling must be the real POLICY maximum (5%), which is what "never wider
            # than policy allows" actually meant -- the volatility-scaled value stays as
            # the fallback for when no usable technical level exists.
            stop_loss = technical_stop_loss(
                entry_price=price,
                side="buy",
                support=symbol_metrics.get("support"),
                resistance=symbol_metrics.get("resistance"),
                atr=atr_absolute,
                max_stop_loss_pct=max(effective_stop_pct, max_stop_loss_pct),
                default_stop_loss_pct=effective_stop_pct,
            )
            take_profit = technical_take_profit(
                entry_price=price,
                stop_loss=stop_loss,
                side="buy",
                resistance=symbol_metrics.get("resistance"),
                support=symbol_metrics.get("support"),
                min_reward_risk=2.0,
            )
            # Founder-directed 2026-08-20. Two changes here, in this order deliberately.
            #
            # (a) Size from the money at risk, not a flat pound amount. Under the old flat
            #     sizing the stop distance mapped one-for-one into cash at risk, so a wider
            #     stop simply risked more -- which is why handing a model the stop distance
            #     would have handed it a risk dial. Now a wider stop buys a smaller position
            #     and the risk stops growing. requested_notional remains the hard ceiling.
            if risk_budget and risk_budget > 0:
                sized_notional = risk_based_notional(
                    risk_budget=risk_budget,
                    entry_price=price,
                    stop_loss=stop_loss,
                    max_notional=requested_notional,
                )
            else:
                sized_notional = requested_notional
            # (b) Refuse trades that cannot pay for themselves. Measured live: fees run about
            #     1.6% of notional per round trip, so a target only 3% away keeps barely half
            #     the move. XRP was a CORRECT call that returned +0.004 net on +0.036 gross.
            if not clears_fee_hurdle(
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                round_trip_fee_pct=round_trip_fee_pct,
                min_net_reward_risk=min_net_reward_risk,
            ):
                audit.record_execution_event(
                    proposal_id=f"fee-hurdle-{symbol}",
                    event_type="agent_no_trade",
                    payload={"symbol": symbol, "reason": "fee_hurdle_not_cleared",
                             "round_trip_fee_pct": round_trip_fee_pct},
                )
                print(
                    f"[crypto-research] symbol={symbol} stage=completed outcome=fee_hurdle_not_cleared "
                    f"fee_pct={round_trip_fee_pct:.4f}",
                    flush=True,
                )
                if on_symbol_complete:
                    on_symbol_complete(symbol, [])
                continue
            # 2026-08-24, Founder-directed: this system's own realised record on this coin
            # -- the one input no other trader has, and the only one here that isn't
            # published for free to everyone. Placed before the proposal is built so a
            # coin that has taken money off us repeatedly is stood aside from rather than
            # argued into, and recorded as its own no-trade reason so the Founder can see
            # it happen. See symbol_track_record.py for why this can only ever lower
            # conviction, never raise it.
            track_record = symbol_track_record(db_path, symbol)
            if track_record.verdict == "avoid":
                audit.record_execution_event(
                    proposal_id=f"no-trade-crypto-{symbol}",
                    event_type="agent_no_trade",
                    payload={
                        "symbol": symbol,
                        "reason": "own_track_record_negative",
                        "track_record": track_record.to_dict(),
                    },
                )
                print(
                    f"[crypto-research] symbol={symbol} stage=completed outcome=own_track_record_negative "
                    f"record={track_record.wins}/{track_record.trades} net={track_record.net_profit_loss:.2f}",
                    flush=True,
                )
                if on_symbol_complete:
                    on_symbol_complete(symbol, [])
                continue
            if track_record.confidence_penalty:
                confidence = max(0.0, round(confidence - track_record.confidence_penalty, 4))
            # 2026-08-24, Founder-directed: where the real money is actually resting, and
            # which side is doing the hitting. Free from Kraken's public API and, like the
            # track record above, not something every other trader is already looking at.
            # Read after the fee hurdle so the two order-book calls only happen for
            # candidates that have already survived everything cheaper.
            liquidity = liquidity_map_for_pair(adapter, _kraken_pair(symbol)) if adapter is not None else None
            if liquidity is not None:
                if liquidity.verdict == "avoid":
                    audit.record_execution_event(
                        proposal_id=f"no-trade-crypto-{symbol}",
                        event_type="agent_no_trade",
                        payload={
                            "symbol": symbol,
                            "reason": "liquidity_structure_unfavourable",
                            "liquidity_map": liquidity.to_dict(),
                        },
                    )
                    print(
                        f"[crypto-research] symbol={symbol} stage=completed outcome=liquidity_structure_unfavourable "
                        f"detail={liquidity.summary}",
                        flush=True,
                    )
                    if on_symbol_complete:
                        on_symbol_complete(symbol, [])
                    continue
                if liquidity.confidence_penalty:
                    confidence = max(0.0, round(confidence - liquidity.confidence_penalty, 4))
            quantity = sized_notional / price if price > 0 else 0.0
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
                # 2026-08-29: was `philosophy_fit=confidence`, which quietly held crypto to a
                # far higher bar than equities and is why it has never traded.
                #
                # philosophy_fit is the PERMISSION field -- "is this an asset the Founder has
                # approved owning" -- and the orchestrator tests it against
                # min_investment_policy_fit, which is 0.85. Feeding the coin's confidence into
                # it meant crypto needed 0.85 confidence to pass a permission check, while the
                # actual confidence gate sits at 0.75. Confirmed live: the best coins scored
                # 0.60-0.67 and were rejected as not_in_permitted_universe -- a permission
                # failure reported for a coin that IS permitted.
                #
                # Permission for crypto is already established elsewhere and properly: this
                # loop only iterates the approved universe, and foundation.py separately
                # requires an active CRYPTO_MASTER row before any crypto order. So a coin
                # reaching this line is permitted by construction, and says so. Its conviction
                # continues to be judged on confidence_score, once, like everything else.
                philosophy_fit=1.0,
            ).normalized()
            intelligence = evaluate_trade_intelligence(
                db_path,
                proposal,
                account,
                market={"history": {symbol.upper(): crypto_candle_history.get(symbol.upper(), [])}},
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
            validation = validate_trade_proposal(
                proposal, account, guardrails, now=now,
                # 2026-08-25: a coin the Founder holds personally is not a position this
                # system opened, and must not block it from entering. See
                # guardrails.validate_trade_proposal for the measured effect.
                ai_managed_symbols=_ai_managed_symbols(db_path, "kraken"),
            )
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
                # into this crypto proposal's reasoning text for transparency and audit.
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
                    context = None
                # Phase 5 of the CIO-level forecasting build (2026-08-20, Founder-directed):
                # a real qualitative review, which this path has never had -- crypto trade
                # generation was pure scoring arithmetic while equities got genuine LLM
                # judgment. Runs only for candidates that already cleared every mechanical
                # gate (so at most a couple of symbols per cycle, not one call per symbol),
                # and can only veto or LOWER confidence, never raise it or touch
                # price/size/stop/target -- those stay deterministic risk-management math,
                # never model-authored. Any failure falls back to the existing deterministic
                # proposal unchanged, matching propose_trades' per-symbol isolation.
                review = None
                if reviewer is not None:
                    try:
                        review = reviewer.review(symbol=symbol, candidate=_review_candidate(proposal, row), context=context)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[crypto-research] symbol={symbol} stage=review outcome=failed detail={exc}", flush=True)
                        review = None
                if review is not None:
                    proposal = _apply_crypto_review(proposal, review)
                    if not review["proceed"]:
                        audit.record_execution_event(
                            proposal_id=proposal.proposal_id,
                            event_type="agent_no_trade",
                            payload={"symbol": symbol, "reason": "ai_review_declined", "review": review},
                        )
                        print(f"[crypto-research] symbol={symbol} stage=completed outcome=ai_review_declined", flush=True)
                        if on_symbol_complete:
                            on_symbol_complete(symbol, [])
                        continue
                    if proposal.confidence_score < min_confidence:
                        audit.record_execution_event(
                            proposal_id=proposal.proposal_id,
                            event_type="agent_no_trade",
                            payload={"symbol": symbol, "reason": "ai_review_lowered_confidence_below_minimum", "review": review},
                        )
                        print(f"[crypto-research] symbol={symbol} stage=completed outcome=ai_review_lowered_confidence", flush=True)
                        if on_symbol_complete:
                            on_symbol_complete(symbol, [])
                        continue
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


def _review_candidate(proposal: TradeProposal, row: Any) -> dict[str, Any]:
    """The candidate as the reviewer sees it: real evidence plus the already-fixed
    risk-management numbers, clearly labelled as fixed so the model treats them as
    context rather than something to negotiate."""
    return {
        "confidence_score": proposal.confidence_score,
        "scores": {
            "technical_trend": row["technical_trend_score"],
            "momentum": row["momentum_score"],
            "volatility": row["volatility"],
            "liquidity": row["liquidity"],
            "risk_score": row["risk_score"],
            "overall_due_diligence": row["overall_due_diligence_score"],
        },
        "technical_read": proposal.intelligence.get("market_intelligence", {}).get("metrics") if proposal.intelligence else None,
        "regime": proposal.intelligence.get("regime") if proposal.intelligence else None,
        "fixed_by_risk_management_not_negotiable": {
            "entry_price": proposal.entry_price,
            "stop_loss": proposal.stop_loss,
            "take_profit": proposal.take_profit,
            "position_size": proposal.position_size,
        },
    }


def _apply_crypto_review(proposal: TradeProposal, review: dict[str, Any]) -> TradeProposal:
    """Fold a review into the proposal: real reasoning text always, and a LOWERED
    confidence when the reviewer argued for one. Never raises confidence -- see
    CryptoTradeReviewer's docstring for why that asymmetry is deliberate."""
    reasoning = str(proposal.plain_english_reasoning or "")
    addition = f"\n\nAI review: {review['reasoning']}"
    if review.get("concerns"):
        addition += f" Concerns: {'; '.join(review['concerns'])}."
    confidence = proposal.confidence_score
    reviewed = review.get("confidence")
    if reviewed is not None and reviewed < confidence:
        addition += f" Confidence lowered from {confidence:.2f} to {reviewed:.2f} on this review."
        confidence = reviewed
    return replace(proposal, plain_english_reasoning=reasoning + addition, confidence_score=confidence)


def _json_loads(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        import json

        data = json.loads(value)
        return data if isinstance(data, dict) else None
    except (TypeError, ValueError):
        return None
