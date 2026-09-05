"""Assembles real context -- the app's own trade history, its own backtests,
external market/news/macro intelligence, and curated reference material --
into a compact, prompt-ready block for the proposal-generation LLM call.

Phase C of the external-intelligence work (see external_intelligence.py for
Phase A, knowledge_base.py for Phase B). Before this module, OpenAIProposalAnalyzer.propose()
(ai.py) saw only a live market snapshot and a thin news blurb; every source
this module assembles already existed in the database or was added in an
earlier phase, but none of it reached the proposal call. This module is pure
assembly/serialization -- it does not fetch external data itself (Phase A's
job) and does not call the LLM itself (ai.py's job); it turns already-fetched
evidence into text a model can actually use.

Every source is best-effort: a symbol with no historical analogues, no
backtest result, no external intelligence, or no matching knowledge-base
entry simply contributes nothing to the context rather than raising --
sparse context on a new symbol is expected and honest, not an error.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .database import connect
from .decision_inputs import is_wired
from .experience_engine import find_historical_analogues
from .knowledge_base import record_knowledge_gap, relevant_excerpts
from .trading_intelligence import initialize_trading_intelligence_schema


def _most_relevant_backtest(db_path: Path, *, symbol: str, strategy_id: str | None) -> dict[str, Any] | None:
    """Most recent STRATEGY_BACKTEST_RESULTS row for this symbol, preferring a
    match on strategy_id when one is known. No existing "most relevant
    backtest" retrieval function exists in trading_intelligence.py (it only
    runs and stores backtests via run_strategy_backtest) -- this is that
    retrieval, added here since it is proposal_context's specific need.
    """
    initialize_trading_intelligence_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = None
        if strategy_id:
            row = conn.execute(
                """
                SELECT * FROM STRATEGY_BACKTEST_RESULTS
                WHERE symbol = ? AND strategy_id = ?
                ORDER BY backtest_id DESC LIMIT 1
                """,
                (symbol.upper(), strategy_id),
            ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM STRATEGY_BACKTEST_RESULTS WHERE symbol = ? ORDER BY backtest_id DESC LIMIT 1",
                (symbol.upper(),),
            ).fetchone()
    return dict(row) if row is not None else None


def _serialize_historical_analogues(analogues: dict[str, Any]) -> str:
    """Turn find_historical_analogues's output into compact prompt text.
    Deliberately conservative: comparable_cases below the function's own
    minimum_cases threshold is reported as low-confidence context, not
    hidden -- the LLM should know a "similar situation" claim rests on a
    thin sample, the same honesty standard the rest of this codebase applies
    to small-sample statistics (see forecastEngine.js's MIN_SAMPLE_SIZE
    handling on the mobile side for the same principle).
    """
    comparable = analogues.get("comparable_cases") or 0
    if comparable == 0:
        return "No historical analogues on record for this symbol/strategy/regime combination."
    confidence = analogues.get("confidence") or "low"
    lines = [f"{comparable} historical analogue(s) on record (confidence: {confidence})."]
    for case in (analogues.get("similar_historical_situations") or [])[:5]:
        result_context = _safe_json_loads(case.get("result_context_json"))
        outcome = result_context.get("outcome") if isinstance(result_context, dict) else None
        pnl = result_context.get("pnl") if isinstance(result_context, dict) else None
        summary_bits = [f"symbol={case.get('symbol')}"]
        if outcome is not None:
            summary_bits.append(f"outcome={outcome}")
        if pnl is not None:
            summary_bits.append(f"pnl={pnl}")
        # rejection_review.py's records (2026-08-16) are the one decision_context
        # shape with a reliable "why" -- real executed-trade decision_context is a
        # large free-form dict with no consistent reason field, so this is
        # deliberately gated on the record_type marker rather than guessing at a
        # key that might mean something different for a real trade.
        decision_context = _safe_json_loads(case.get("decision_context_json"))
        if isinstance(decision_context, dict) and decision_context.get("record_type") == "rejection_review":
            reason = decision_context.get("dominant_reason")
            if reason:
                summary_bits.append(f"reason={reason}")
        lines.append("  - " + ", ".join(summary_bits))
    return "\n".join(lines)


def _serialize_backtest(backtest: dict[str, Any] | None, *, source_wired: bool = True) -> str:
    if backtest is None:
        # 2026-09-04: these two cases used to read identically, and the difference
        # matters more than anything else in this block. "No prior backtest for this
        # symbol" is a finding -- it says something about the symbol. But
        # STRATEGY_BACKTEST_RESULTS has held zero rows since it was created, so the
        # same sentence was being emitted for every symbol, forever, and the model
        # was reading a missing pipe as evidence of absence. Say which one it is.
        if not source_wired:
            return (
                "BACKTEST EVIDENCE UNAVAILABLE: this system holds no backtest results for any "
                "symbol, so the absence says nothing about this trade. Do not treat it as a "
                "negative signal; treat this input as missing."
            )
        return "No prior backtest on record for this symbol/strategy."
    return (
        f"Most recent backtest ({backtest.get('created_at')}, {backtest.get('trades')} trades): "
        f"win_rate={backtest.get('win_rate')}, expectancy_r={backtest.get('expectancy_r')}, "
        f"profit_factor={backtest.get('profit_factor')}, max_drawdown_r={backtest.get('max_drawdown_r')}. "
        f"{backtest.get('result_summary') or ''}".strip()
    )


def _serialize_knowledge(excerpts: list[dict[str, Any]], *, source_wired: bool = True) -> str:
    if not excerpts:
        # Same distinction as _serialize_backtest. The knowledge-base tables do not
        # exist in production at all, so "no matching reference material for this
        # asset type" was describing a library that was never built as though it were
        # a library that had been searched.
        if not source_wired:
            return (
                "REFERENCE MATERIAL UNAVAILABLE: the curated knowledge base is not populated in "
                "this deployment, so nothing was searched. This is a missing input, not a "
                "finding about this asset type."
            )
        return "No matching curated reference material for this asset type/sector."
    blocks = []
    for entry in excerpts:
        excerpt_text = str(entry.get("excerpt") or "")
        if len(excerpt_text) > 1200:
            excerpt_text = excerpt_text[:1200] + "..."
        blocks.append(f"### {entry.get('title')}\n{excerpt_text}")
    return "\n\n".join(blocks)


def _serialize_external_intelligence(db_path: Path, *, symbol: str) -> str:
    """Best-effort recent rows from Phase A's tables for this symbol, plus the
    latest global market-regime read. Silently returns a plain "no data"
    string on any query error (e.g. tables not yet created on a fresh
    database) rather than raising -- external intelligence being unavailable
    must never block proposal generation."""
    lines: list[str] = []
    try:
        with closing(connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            news_rows = conn.execute(
                "SELECT title, published_at FROM CRYPTO_NEWS WHERE symbol = ? ORDER BY crypto_id DESC LIMIT 3",
                (symbol.upper(),),
            ).fetchall()
            for row in news_rows:
                lines.append(f"Crypto news: {row['title']} ({row['published_at']})")
    except sqlite3.OperationalError:
        pass
    try:
        with closing(connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            catalyst_rows = conn.execute(
                "SELECT market_commentary, source_timestamp FROM NEWS_CATALYST_EVIDENCE "
                "WHERE normalized_symbol = ? ORDER BY created_at DESC LIMIT 3",
                (symbol.upper(),),
            ).fetchall()
            for row in catalyst_rows:
                lines.append(f"News: {row['market_commentary']} ({row['source_timestamp']})")
    except sqlite3.OperationalError:
        pass
    try:
        with closing(connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            regime_row = conn.execute(
                "SELECT primary_regime, confidence, plain_english FROM MARKET_REGIME_EVIDENCE "
                "WHERE scope = 'global' ORDER BY regime_id DESC LIMIT 1"
            ).fetchone()
            if regime_row is not None:
                lines.append(
                    f"Market regime: {regime_row['primary_regime']} (confidence {regime_row['confidence']}). "
                    f"{regime_row['plain_english']}"
                )
    except sqlite3.OperationalError:
        pass
    return "\n".join(lines) if lines else "No external intelligence on record for this symbol yet."


def _safe_json_loads(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


# The library tags its files with topics like [momentum, mean_reversion, market_regime,
# risk_management, position_sizing, drawdown]. A strategy_id and a regime_id are not those
# words, so they are translated here rather than passed through raw and matching nothing.
# Nothing is included unconditionally. An earlier version always added risk_management and
# position_sizing, and those two score so highly that they filled every slot -- leaving the
# situational file, the one that actually distinguishes a crypto trend trade from an equity
# value trade, permanently outside the top three. The generic discipline files still surface
# whenever the strategy genuinely calls for them.
_STRATEGY_TOPICS: dict[str, tuple[str, ...]] = {
    "momentum": ("momentum",),
    "trend_following": ("momentum", "market_regime"),
    "crypto_trend_following_2r": ("momentum", "market_regime", "crypto"),
    "crypto_infrastructure_trend": ("momentum", "crypto", "sector_analysis"),
    "swing_continuation": ("momentum", "market_regime"),
    "breakout": ("momentum", "market_regime"),
    "volatility_expansion": ("market_regime", "drawdown"),
    "mean_reversion": ("mean_reversion",),
    "range_trading": ("mean_reversion", "market_regime"),
    "pullback": ("mean_reversion", "momentum"),
    "value_pullback": ("mean_reversion", "fundamentals"),
    "quality_growth": ("fundamentals",),
    "institutional_accumulation": ("market_regime", "fundamentals"),
    "equity_conservative_ai_assisted": ("risk_management", "fundamentals"),
}

_REGIME_TOPICS: dict[str, tuple[str, ...]] = {
    "trending": ("momentum", "market_regime"),
    "ranging": ("mean_reversion", "market_regime"),
    "range_bound": ("mean_reversion", "market_regime"),
    "high_volatility": ("drawdown", "risk_management"),
    "crisis": ("drawdown", "risk_management", "correlation"),
    "bear": ("drawdown", "risk_management"),
}


def _knowledge_topics(*, strategy_id: str | None, regime_id: str | None) -> list[str]:
    """The library's own tag vocabulary, derived from what this trade actually is."""
    topics: list[str] = []
    for value, table in ((strategy_id, _STRATEGY_TOPICS), (regime_id, _REGIME_TOPICS)):
        key = str(value or "").strip().lower()
        for topic in table.get(key, ()):
            if topic not in topics:
                topics.append(topic)
    return topics


def build_proposal_context(
    db_path: Path,
    *,
    symbol: str,
    asset_type: str,
    strategy_id: str | None = None,
    regime_id: str | None = None,
    sector: str | None = None,
) -> dict[str, str]:
    """Assemble real context for symbol before the proposal LLM call.

    Returns a dict of plain-text blocks (historical_analogues, backtest_evidence,
    external_intelligence, reference_material) meant to be folded directly
    into the LLM prompt alongside the existing market/news dicts -- kept as
    separate labeled blocks rather than one blob so the prompt can label each
    source for the model, matching how the existing prompt already labels
    "market"/"news" as distinct keys (ai.py's OpenAIProposalAnalyzer.propose).
    """
    analogues = find_historical_analogues(db_path, {"symbol": symbol, "strategy_id": strategy_id, "regime_id": regime_id})
    backtest = _most_relevant_backtest(db_path, symbol=symbol, strategy_id=strategy_id)
    # 2026-09-05, Phase 4 of the learning work. `relevant_excerpts` has always accepted a
    # `topics` argument and this call never passed one, so selection fell back to asset type
    # alone -- and with a seven-file library that returns the SAME three files for every trade.
    # Measured that day: the reference_material block was byte-for-byte identical for XRP, AAVE
    # and NVDA. It was not a library being consulted, it was a constant being pasted, and the
    # model could not tell one situation from another by reading it.
    #
    # The strategy chosen and the regime detected are what actually make one trade different
    # from another, and both are already resolved by the time this runs. Mapping them onto the
    # library's own declared tags is what turns a fixed passage into relevant reading.
    # Deliberately still three. Raising it to four to make room was tried and made things
    # worse: with a seven-file library the fourth slot pulled in "Sector Notes: Airlines" for an
    # NVDA trade, and irrelevant reading is worse than less reading -- it invites the model to
    # draw an analogy that does not hold. Relevance beats volume.
    topics = _knowledge_topics(strategy_id=strategy_id, regime_id=regime_id)
    excerpts = relevant_excerpts(asset_type=asset_type, sector=sector, topics=topics, limit=3)
    if not excerpts:
        record_knowledge_gap(db_path, asset_type=asset_type, sector=sector, topics_searched=topics)

    return {
        "historical_analogues": _serialize_historical_analogues(analogues),
        # Whether the SOURCE holds anything at all, not just whether it held something
        # for this symbol -- see the comment in each serializer.
        "backtest_evidence": _serialize_backtest(
            backtest, source_wired=is_wired(db_path, "backtest_evidence")
        ),
        "external_intelligence": _serialize_external_intelligence(db_path, symbol=symbol),
        "reference_material": _serialize_knowledge(
            excerpts, source_wired=is_wired(db_path, "reference_material")
        ),
        "market_forecast": _serialize_market_forecast(db_path, symbol=symbol),
    }


def _serialize_market_forecast(db_path: Path, *, symbol: str) -> str:
    """The latest real CIO-level market forecast for this symbol, as prompt text.

    Phase 4 of the CIO-level forecasting build (2026-08-20). This is the "upstream" half
    of making the forecast a genuine input to trade selection: the model sees the market
    view BEFORE it reasons, so the forecast shapes confidence and the written thesis at
    the point they are formed, rather than only being checked against afterwards. The
    "downstream" half is the rare hard-block circuit breaker in sprint6.py's Risk
    Sentinel (_market_forecast_conflict).

    Deliberately includes the contradictory evidence and invalidation level too -- a
    forecast presented as one-sided would push the model toward agreeing with it, which
    is the opposite of the judgment this is meant to improve.
    """
    try:
        from .forecasting import latest_forecast

        forecast = latest_forecast(db_path, symbol=symbol)
    except Exception:  # noqa: BLE001 - context is additive; its failure must never block a proposal
        return "No market forecast is available for this symbol."
    if not forecast:
        return "No market forecast has been generated for this symbol yet."
    lines = [
        f"Direction: {forecast.get('direction')} over ~{forecast.get('horizon_days')} days "
        f"(confidence {forecast.get('confidence')}), generated {forecast.get('created_at')}.",
        f"Reasoning: {forecast.get('reasoning')}",
    ]
    if forecast.get("invalidation"):
        lines.append(f"What would invalidate this view: {forecast['invalidation']}")
    payload = _safe_json_loads(forecast.get("evidence_json"))
    if isinstance(payload, dict):
        for label, key in (("Supporting", "supporting_evidence"), ("Contradictory", "contradictory_evidence"), ("Key risks", "key_risks")):
            items = payload.get(key) or []
            if items:
                lines.append(f"{label}: " + "; ".join(str(item) for item in items[:3]))
    lines.append(
        "Weigh this as a real market view, not an instruction -- if the specific setup in front of you "
        "genuinely argues otherwise, say so explicitly and explain why."
    )
    return "\n".join(lines)
