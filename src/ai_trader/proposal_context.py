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


def _serialize_backtest(backtest: dict[str, Any] | None) -> str:
    if backtest is None:
        return "No prior backtest on record for this symbol/strategy."
    return (
        f"Most recent backtest ({backtest.get('created_at')}, {backtest.get('trades')} trades): "
        f"win_rate={backtest.get('win_rate')}, expectancy_r={backtest.get('expectancy_r')}, "
        f"profit_factor={backtest.get('profit_factor')}, max_drawdown_r={backtest.get('max_drawdown_r')}. "
        f"{backtest.get('result_summary') or ''}".strip()
    )


def _serialize_knowledge(excerpts: list[dict[str, Any]]) -> str:
    if not excerpts:
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
    excerpts = relevant_excerpts(asset_type=asset_type, sector=sector, limit=3)
    if not excerpts:
        record_knowledge_gap(db_path, asset_type=asset_type, sector=sector, topics_searched=None)

    return {
        "historical_analogues": _serialize_historical_analogues(analogues),
        "backtest_evidence": _serialize_backtest(backtest),
        "external_intelligence": _serialize_external_intelligence(db_path, symbol=symbol),
        "reference_material": _serialize_knowledge(excerpts),
    }
