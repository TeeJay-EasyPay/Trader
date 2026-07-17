from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import AccountContext, TradeProposal, utc_now_iso


TRADING_INTELLIGENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS STRATEGY_REGISTRY (
    strategy_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    purpose TEXT NOT NULL,
    supported_assets_json TEXT NOT NULL,
    supported_regimes_json TEXT NOT NULL,
    expected_holding_period TEXT NOT NULL,
    historical_edge TEXT NOT NULL,
    minimum_evidence_json TEXT NOT NULL,
    maximum_risk REAL NOT NULL,
    exit_methodology TEXT NOT NULL,
    invalid_conditions_json TEXT NOT NULL,
    production_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS MARKET_REGIME_SNAPSHOTS (
    regime_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    exchange TEXT NOT NULL,
    primary_regime TEXT NOT NULL,
    volatility_regime TEXT NOT NULL,
    trend_regime TEXT NOT NULL,
    liquidity_regime TEXT NOT NULL,
    risk_regime TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS TRADE_SIGNALS (
    signal_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    regime_id TEXT NOT NULL,
    signal_name TEXT NOT NULL,
    score REAL NOT NULL,
    confidence REAL NOT NULL,
    weight REAL NOT NULL,
    historical_effectiveness REAL,
    evidence_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS TRADING_COMMITTEE_REVIEWS (
    review_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    regime_id TEXT NOT NULL,
    committee_result TEXT NOT NULL,
    strongest_argument_for TEXT NOT NULL,
    strongest_argument_against TEXT NOT NULL,
    member_votes_json TEXT NOT NULL,
    supporting_evidence_json TEXT NOT NULL,
    opposing_evidence_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS PROBABILITY_ESTIMATES (
    estimate_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    regime_id TEXT NOT NULL,
    probability_of_success REAL NOT NULL,
    expected_return_r REAL NOT NULL,
    expected_drawdown_r REAL NOT NULL,
    historical_sample_size INTEGER NOT NULL,
    confidence_interval_low REAL NOT NULL,
    confidence_interval_high REAL NOT NULL,
    expected_holding_time TEXT NOT NULL,
    expected_volatility REAL NOT NULL,
    calibration_status TEXT NOT NULL,
    evidence_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS TRADE_LIFECYCLE (
    lifecycle_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    broker TEXT,
    strategy_id TEXT,
    stage TEXT NOT NULL,
    stage_reason TEXT NOT NULL,
    measurable INTEGER NOT NULL,
    fees REAL,
    slippage REAL,
    r_multiple REAL,
    mae REAL,
    mfe REAL,
    holding_time_seconds REAL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CONFIDENCE_CALIBRATION (
    calibration_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    confidence_bucket TEXT NOT NULL,
    predicted_probability REAL NOT NULL,
    observed_win_rate REAL,
    average_r REAL,
    sample_size INTEGER NOT NULL,
    calibration_note TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS STRATEGY_LAB_RUNS (
    lab_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    input_summary TEXT NOT NULL,
    result_summary TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS HISTORICAL_CANDLES (
    candle_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL NOT NULL,
    volume REAL,
    source TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(symbol, asset_type, timeframe, observed_at)
);

CREATE TABLE IF NOT EXISTS STRATEGY_BACKTEST_RESULTS (
    backtest_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    start_at TEXT,
    end_at TEXT,
    trades INTEGER NOT NULL,
    win_rate REAL,
    average_r REAL,
    expectancy_r REAL,
    profit_factor REAL,
    max_drawdown_r REAL,
    sharpe_proxy REAL,
    sortino_proxy REAL,
    result_summary TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS PERFORMANCE_INTELLIGENCE (
    performance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    symbol TEXT,
    sample_size INTEGER NOT NULL,
    win_rate REAL,
    average_r REAL,
    expectancy_r REAL,
    profit_factor REAL,
    max_drawdown_r REAL,
    average_holding_seconds REAL,
    brier_score REAL,
    calibration_error REAL,
    payload_json TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class IntelligencePacket:
    strategy: dict[str, Any]
    market_intelligence: dict[str, Any]
    regime: dict[str, Any]
    signals: list[dict[str, Any]]
    trade_setup: dict[str, Any]
    portfolio: dict[str, Any]
    committee: dict[str, Any]
    probability: dict[str, Any]
    explainability: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "market_intelligence": self.market_intelligence,
            "regime": self.regime,
            "signals": self.signals,
            "trade_setup": self.trade_setup,
            "portfolio": self.portfolio,
            "committee": self.committee,
            "probability": self.probability,
            "explainability": self.explainability,
        }


def initialize_trading_intelligence_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.executescript(TRADING_INTELLIGENCE_SCHEMA)
            _ensure_column(conn, "TRADE_LIFECYCLE", "fees", "REAL")
            _ensure_column(conn, "TRADE_LIFECYCLE", "slippage", "REAL")
            _ensure_column(conn, "TRADE_LIFECYCLE", "r_multiple", "REAL")
            _ensure_column(conn, "TRADE_LIFECYCLE", "mae", "REAL")
            _ensure_column(conn, "TRADE_LIFECYCLE", "mfe", "REAL")
            _ensure_column(conn, "TRADE_LIFECYCLE", "holding_time_seconds", "REAL")
            _seed_strategy_registry(conn)


def evaluate_trade_intelligence(
    db_path: Path,
    proposal: TradeProposal,
    account: AccountContext,
    *,
    market: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
    crypto_score: dict[str, Any] | None = None,
    source: str = "agent",
) -> IntelligencePacket | None:
    """Builds and stores the evidence packet that must exist before a recommendation is recorded.

    This layer does not execute trades and does not weaken guardrails. It converts available
    evidence into structured strategy, signal, regime, committee, and probability records.
    A packet is rejected if it cannot articulate both the best bull case and best bear case.
    """
    initialize_trading_intelligence_schema(db_path)
    p = proposal.normalized()
    market_intelligence = build_market_intelligence(p, market=market, news=news, crypto_score=crypto_score)
    regime = infer_market_regime(p, crypto_score=crypto_score, market=market, market_intelligence=market_intelligence)
    strategy = select_strategy(p, source=source, market_intelligence=market_intelligence, regime=regime, crypto_score=crypto_score)
    signals = build_signal_evidence(
        p,
        strategy,
        regime,
        market=market,
        news=news,
        crypto_score=crypto_score,
        market_intelligence=market_intelligence,
    )
    trade_setup = evaluate_trade_setup(p, signals, regime)
    portfolio = evaluate_portfolio_fit(p, account)
    probability = estimate_probability(db_path, p, strategy, regime, signals, trade_setup)
    committee = run_trading_committee(p, strategy, regime, signals, trade_setup, portfolio, probability)
    if not _has_bull_and_bear(committee):
        record_lifecycle_stage(
            db_path,
            p,
            stage="rejected",
            reason="Trading Intelligence rejected proposal because strongest argument for and against were not both available.",
            strategy_id=strategy["strategy_id"],
            payload={"committee": committee},
        )
        return None
    explainability = build_explainability(p, strategy, regime, signals, trade_setup, portfolio, committee, probability)
    packet = IntelligencePacket(
        strategy=strategy,
        market_intelligence=market_intelligence,
        regime=regime,
        signals=signals,
        trade_setup=trade_setup,
        portfolio=portfolio,
        committee=committee,
        probability=probability,
        explainability=explainability,
    )
    persist_intelligence_packet(db_path, p, packet)
    record_lifecycle_stage(
        db_path,
        p,
        stage="candidate",
        reason="Recommendation candidate passed Trading Intelligence evidence and bull/bear review.",
        strategy_id=strategy["strategy_id"],
        payload=packet.to_dict(),
    )
    return packet


def select_strategy(
    proposal: TradeProposal,
    *,
    source: str = "agent",
    market_intelligence: dict[str, Any] | None = None,
    regime: dict[str, Any] | None = None,
    crypto_score: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = proposal.normalized()
    if "demo" in p.plain_english_reasoning.lower() or source == "demo":
        selected = strategy_definition("paper_validation_2r")
        selected["selection_reason"] = "Demo/test proposal selected the paper validation strategy."
        selected["candidate_scores"] = [{"strategy_id": "paper_validation_2r", "score": 1.0, "reason": "Operational validation path."}]
        selected["rejected_strategies"] = []
        return selected
    candidates = _candidate_strategy_ids(p)
    scored = [_score_strategy_candidate(strategy_definition(strategy_id), p, market_intelligence or {}, regime or {}, crypto_score) for strategy_id in candidates]
    scored.sort(key=lambda item: item["score"], reverse=True)
    winner = scored[0] if scored else _score_strategy_candidate(strategy_definition("equity_conservative_ai_assisted"), p, market_intelligence or {}, regime or {}, crypto_score)
    selected = strategy_definition(winner["strategy_id"])
    selected["selection_reason"] = winner["reason"]
    selected["candidate_scores"] = scored
    selected["rejected_strategies"] = [
        {
            "strategy_id": item["strategy_id"],
            "strategy_name": item["strategy_name"],
            "score": item["score"],
            "reason_rejected": item["reason_rejected"],
        }
        for item in scored[1:]
    ]
    selected["production_ready"] = bool(
        selected.get("production_status") in {"paper_only", "founder_controlled_live_kraken", "production_ready"}
        and (_float((selected.get("historical_statistics") or {}).get("sample_size")) or 0) >= selected.get("minimum_sample_size", 30)
    )
    selected["validation_status"] = "production_ready" if selected["production_ready"] else "research_or_validation_required"
    return selected


def strategy_definition(strategy_id: str) -> dict[str, Any]:
    base = dict(STRATEGIES.get(strategy_id, STRATEGIES["equity_conservative_ai_assisted"]))
    base.setdefault("entry_conditions", list(base.get("minimum_evidence", [])))
    base.setdefault("exit_conditions", [base.get("exit_methodology", "Defined stop and target.")])
    base.setdefault("position_sizing_assumptions", "Sizing remains controlled by Investment Orchestrator capital allocation.")
    base.setdefault("ideal_regime", list(base.get("supported_regimes", [])))
    base.setdefault("poor_regime", ["bear", "crisis", "high_volatility"])
    base.setdefault("historical_statistics", {"sample_size": 0, "win_rate": None, "average_r": None, "expectancy_r": None})
    base.setdefault("required_evidence", list(base.get("minimum_evidence", [])))
    base.setdefault("invalidating_evidence", list(base.get("invalid_conditions", [])))
    base.setdefault("minimum_reward_risk", 1.5)
    base.setdefault("maximum_acceptable_volatility", 0.08)
    base.setdefault("maximum_holding_period", base.get("expected_holding_period", "unknown"))
    base.setdefault("minimum_sample_size", 30)
    base.setdefault("confidence_requirement", 0.75)
    base.setdefault("risk_assumptions", "Risk is controlled by stop loss, position sizing, and orchestrator policy.")
    return base


def _candidate_strategy_ids(proposal: TradeProposal) -> list[str]:
    p = proposal.normalized()
    if p.asset_type == "crypto":
        return [
            "crypto_trend_following_2r",
            "crypto_infrastructure_trend",
            "trend_following",
            "momentum",
            "pullback",
            "breakout",
            "range_trading",
            "mean_reversion",
            "institutional_accumulation",
        ]
    return [
        "trend_following",
        "momentum",
        "pullback",
        "breakout",
        "mean_reversion",
        "range_trading",
        "volatility_expansion",
        "swing_continuation",
        "institutional_accumulation",
        "quality_growth",
        "value_pullback",
        "equity_conservative_ai_assisted",
    ]


def _score_strategy_candidate(
    strategy: dict[str, Any],
    proposal: TradeProposal,
    market_intelligence: dict[str, Any],
    regime: dict[str, Any],
    crypto_score: dict[str, Any] | None,
) -> dict[str, Any]:
    p = proposal.normalized()
    metrics = market_intelligence.get("metrics") or {}
    trend = _float(metrics.get("trend_score"))
    momentum = _float(metrics.get("momentum_score"))
    atr_pct = _float(metrics.get("atr_pct"))
    volume = _float(metrics.get("volume_trend"))
    liquidity = _float(metrics.get("crypto_liquidity"))
    risk_score = _float(metrics.get("crypto_risk_score"))
    strategy_id = strategy["strategy_id"]
    score = 0.35
    reasons: list[str] = []
    rejected_reasons: list[str] = []
    if p.asset_type in strategy.get("supported_assets", []):
        score += 0.10
        reasons.append("asset type fits")
    else:
        score -= 0.30
        rejected_reasons.append("asset type does not fit")
    regime_terms = {regime.get("primary_regime"), regime.get("trend_regime"), regime.get("volatility_regime"), regime.get("risk_regime")}
    if regime_terms.intersection(set(strategy.get("supported_regimes", []))):
        score += 0.12
        reasons.append("market regime fits")
    elif regime.get("primary_regime") == "unknown":
        score -= 0.04
        rejected_reasons.append("regime evidence is incomplete")
    else:
        score -= 0.10
        rejected_reasons.append("market regime is not ideal")
    if strategy_id in {"trend_following", "crypto_trend_following_2r", "crypto_infrastructure_trend", "swing_continuation", "quality_growth"}:
        score += ((trend or 0.5) - 0.5) * 0.45
        score += ((momentum or 0.5) - 0.5) * 0.20
        if (trend or 0) >= 0.58:
            reasons.append("trend evidence supports continuation")
        else:
            rejected_reasons.append("trend evidence is not strong enough")
    elif strategy_id == "momentum":
        score += ((momentum or 0.5) - 0.5) * 0.55
        score += ((volume or 0.5) - 0.5) * 0.15
        if (momentum or 0) >= 0.58:
            reasons.append("momentum evidence is supportive")
        else:
            rejected_reasons.append("momentum is not clearly strong")
    elif strategy_id == "breakout":
        if metrics.get("breakout") == "upside_breakout":
            score += 0.28
            reasons.append("price is attempting an upside breakout")
        else:
            score -= 0.10
            rejected_reasons.append("no confirmed upside breakout")
    elif strategy_id in {"mean_reversion", "range_trading", "value_pullback"}:
        if metrics.get("mean_reversion") == "oversold_below_mean" or regime.get("trend_regime") == "range":
            score += 0.20
            reasons.append("range or pullback evidence is present")
        else:
            score -= 0.08
            rejected_reasons.append("asset is not clearly oversold or range-bound")
    elif strategy_id == "pullback":
        if (trend or 0) >= 0.55 and metrics.get("mean_reversion") in {"oversold_below_mean", "not_overextended"}:
            score += 0.18
            reasons.append("trend remains positive while pullback risk is controlled")
        else:
            rejected_reasons.append("pullback setup lacks trend support")
    elif strategy_id == "volatility_expansion":
        if metrics.get("breakout") == "upside_breakout" and atr_pct is not None and atr_pct <= 0.08:
            score += 0.20
            reasons.append("breakout with acceptable volatility")
        else:
            rejected_reasons.append("volatility expansion evidence is incomplete")
    elif strategy_id == "institutional_accumulation":
        if (volume or 0) >= 0.55 and metrics.get("price_structure") in {"higher_bias", "balanced"}:
            score += 0.18
            reasons.append("volume and structure are consistent with accumulation")
        else:
            rejected_reasons.append("accumulation evidence is not strong")
    if p.asset_type == "crypto":
        if liquidity is not None:
            score += (liquidity - 0.5) * 0.12
        if risk_score is not None:
            score += (risk_score - 0.5) * 0.12
        if crypto_score and strategy_id in {"crypto_trend_following_2r", "crypto_infrastructure_trend"}:
            score += 0.05
            reasons.append("crypto-specific evidence is available")
    if atr_pct is not None and atr_pct > strategy.get("maximum_acceptable_volatility", 0.08):
        score -= 0.15
        rejected_reasons.append("volatility is above the strategy comfort zone")
    score = round(max(0.0, min(1.0, score)), 4)
    reason = "; ".join(reasons[:3]) if reasons else "Selected as the best available fit from limited evidence."
    reason_rejected = "; ".join(rejected_reasons[:3]) if rejected_reasons else "Lower evidence score than selected strategy."
    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy["name"],
        "score": score,
        "reason": reason,
        "reason_rejected": reason_rejected,
    }


def build_market_intelligence(
    proposal: TradeProposal,
    *,
    market: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
    crypto_score: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = proposal.normalized()
    candles = _candles_for_symbol(p.symbol, market or {})
    metrics = analyze_price_series(candles)
    news_items = (news or {}).get("news", []) if isinstance(news, dict) else []
    unknown = []
    for key in ["trend_score", "momentum_score", "volatility", "atr_pct", "relative_strength", "volume_trend", "support", "resistance"]:
        if metrics.get(key) is None:
            unknown.append(key)
    if p.asset_type == "crypto" and crypto_score:
        metrics.update(
            {
                "crypto_trend_score": _float(crypto_score.get("technical_trend_score")),
                "crypto_momentum_score": _float(crypto_score.get("momentum_score")),
                "crypto_liquidity": _float(crypto_score.get("liquidity")),
                "crypto_risk_score": _float(crypto_score.get("risk_score")),
                "crypto_sentiment": _float(crypto_score.get("sentiment")),
            }
        )
    return {
        "market_intelligence_id": f"market-{p.proposal_id}",
        "symbol": p.symbol,
        "asset_type": p.asset_type,
        "data_quality": {
            "candle_count": len(candles),
            "news_count": len(news_items),
            "crypto_score_available": bool(crypto_score),
            "unknown_fields": unknown,
        },
        "metrics": metrics,
        "supporting_evidence": _market_supporting_evidence(metrics, crypto_score),
        "contradictory_evidence": _market_contradictory_evidence(metrics, crypto_score),
    }


def analyze_price_series(candles: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [_float(item.get("close") or item.get("c")) for item in candles]
    highs = [_float(item.get("high") or item.get("h")) for item in candles]
    lows = [_float(item.get("low") or item.get("l")) for item in candles]
    volumes = [_float(item.get("volume") or item.get("v")) for item in candles]
    closes = [value for value in closes if value is not None]
    highs = [value for value in highs if value is not None]
    lows = [value for value in lows if value is not None]
    volumes = [value for value in volumes if value is not None]
    if not closes:
        return {
            "trend_score": None,
            "momentum_score": None,
            "moving_average_position": "unknown",
            "volatility": None,
            "atr_pct": None,
            "relative_strength": None,
            "volume_trend": None,
            "price_structure": "unknown",
            "breakout": "unknown",
            "mean_reversion": "unknown",
            "gap_pct": None,
            "support": None,
            "resistance": None,
        }
    latest = closes[-1]
    short_ma = _mean(closes[-5:]) if len(closes) >= 5 else None
    long_ma = _mean(closes[-20:]) if len(closes) >= 20 else (_mean(closes) if len(closes) >= 2 else None)
    returns = _returns(closes)
    volatility = _stddev(returns[-20:]) if returns else None
    momentum = ((latest / closes[-min(10, len(closes))]) - 1) if len(closes) >= 2 and closes[-min(10, len(closes))] else 0.0
    trend_raw = 0.5
    if short_ma is not None and long_ma is not None and long_ma:
        trend_raw = 0.5 + max(-0.5, min(0.5, (short_ma - long_ma) / long_ma * 5))
    support = min(lows[-20:]) if lows else min(closes[-20:])
    resistance = max(highs[-20:]) if highs else max(closes[-20:])
    atr = _atr(highs, lows, closes)
    prev_close = closes[-2] if len(closes) > 1 else latest
    gap_pct = ((latest / prev_close) - 1) if prev_close else None
    avg_volume_recent = _mean(volumes[-5:]) if len(volumes) >= 5 else None
    avg_volume_prior = _mean(volumes[-20:-5]) if len(volumes) >= 20 else None
    volume_trend = None
    if avg_volume_recent is not None and avg_volume_prior:
        volume_trend = max(0.0, min(1.0, avg_volume_recent / avg_volume_prior / 2))
    breakout = "upside_breakout" if resistance and latest >= resistance else "no_breakout"
    if support and latest <= support:
        breakout = "downside_breakdown"
    mean_reversion = "overextended_above_mean" if short_ma and latest > short_ma * 1.08 else "not_overextended"
    if short_ma and latest < short_ma * 0.92:
        mean_reversion = "oversold_below_mean"
    price_structure = "higher_bias" if trend_raw > 0.57 else "lower_bias" if trend_raw < 0.43 else "balanced"
    return {
        "trend_score": round(max(0.0, min(1.0, trend_raw)), 4),
        "momentum_score": round(_pct_to_score(momentum), 4),
        "moving_average_position": "above_short_and_long" if short_ma and long_ma and latest >= short_ma >= long_ma else "mixed_or_below",
        "short_ma": round(short_ma, 8) if short_ma is not None else None,
        "long_ma": round(long_ma, 8) if long_ma is not None else None,
        "volatility": round(volatility or 0.0, 6) if volatility is not None else None,
        "atr_pct": round((atr / latest), 6) if atr is not None and latest else None,
        "relative_strength": round(_pct_to_score(momentum), 4),
        "volume_trend": round(volume_trend, 4) if volume_trend is not None else None,
        "price_structure": price_structure,
        "breakout": breakout,
        "mean_reversion": mean_reversion,
        "gap_pct": round(gap_pct, 6) if gap_pct is not None else None,
        "support": round(support, 8) if support is not None else None,
        "resistance": round(resistance, 8) if resistance is not None else None,
    }


def infer_market_regime(
    proposal: TradeProposal,
    *,
    crypto_score: dict[str, Any] | None = None,
    market: dict[str, Any] | None = None,
    market_intelligence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = proposal.normalized()
    evidence: dict[str, Any] = {"asset_type": p.asset_type, "exchange": p.exchange}
    contradictions: list[str] = []
    metrics = (market_intelligence or {}).get("metrics") or {}
    trend_metric = _float(metrics.get("trend_score"))
    momentum_metric = _float(metrics.get("momentum_score"))
    volatility_metric = _float(metrics.get("volatility"))
    atr_pct = _float(metrics.get("atr_pct"))
    if p.asset_type == "crypto" and crypto_score:
        trend = _float(crypto_score.get("technical_trend_score"))
        volatility = _float(crypto_score.get("volatility"))
        liquidity = _float(crypto_score.get("liquidity"))
        risk = _float(crypto_score.get("risk_score"))
        trend_blend = _average([value for value in [trend, trend_metric, momentum_metric] if value is not None])
        evidence.update({"trend": trend, "trend_blend": trend_blend, "volatility": volatility, "liquidity": liquidity, "risk": risk, "market_metrics": metrics})
        if trend is not None and momentum_metric is not None and abs(trend - momentum_metric) > 0.35:
            contradictions.append("Crypto trend score and price-series momentum disagree.")
        trend_regime = "trending" if trend_blend >= 0.6 else "mean_reverting" if trend_blend <= 0.4 else "range"
        volatility_value = volatility if volatility is not None else volatility_metric
        volatility_regime = "high_volatility" if volatility_value is not None and volatility_value >= 0.55 else "low_volatility"
        liquidity_regime = "liquid" if liquidity is not None and liquidity >= 0.25 else "thin_liquidity"
        risk_regime = "risk_on" if risk is not None and risk >= 0.55 else "risk_off"
        primary = _primary_regime(trend_blend, risk, volatility_value)
        confidence = _average([trend_blend, risk or 0.0, liquidity or 0.0])
    else:
        latest_close = _latest_close(p.symbol, market or {})
        evidence.update({"latest_close": latest_close, "market_payload_available": bool(market), "market_metrics": metrics})
        if trend_metric is None and momentum_metric is None:
            trend_regime = "unknown"
            primary = "unknown"
        else:
            trend_regime = "trending" if _average([trend_metric or 0.5, momentum_metric or 0.5]) >= 0.6 else "mean_reverting" if _average([trend_metric or 0.5, momentum_metric or 0.5]) <= 0.4 else "range"
            primary = _primary_regime(_average([trend_metric or 0.5, momentum_metric or 0.5]), None, volatility_metric)
        volatility_source = atr_pct if atr_pct is not None else volatility_metric
        volatility_regime = "high_volatility" if volatility_source is not None and volatility_source >= 0.04 else "low_volatility" if volatility_source is not None else "unknown"
        liquidity_regime = "unknown"
        risk_regime = "neutral"
        confidence = _average([value for value in [trend_metric, momentum_metric, 0.35 if latest_close else 0.2] if value is not None])
    return {
        "regime_id": f"regime-{p.proposal_id}",
        "asset_type": p.asset_type,
        "exchange": p.exchange,
        "primary_regime": primary,
        "volatility_regime": volatility_regime,
        "trend_regime": trend_regime,
        "liquidity_regime": liquidity_regime,
        "risk_regime": risk_regime,
        "confidence": round(float(confidence), 4),
        "evidence": evidence,
        "contradictory_evidence": contradictions,
    }


def build_signal_evidence(
    proposal: TradeProposal,
    strategy: dict[str, Any],
    regime: dict[str, Any],
    *,
    market: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
    crypto_score: dict[str, Any] | None = None,
    market_intelligence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    p = proposal.normalized()
    metrics = (market_intelligence or {}).get("metrics") or {}
    market_support = (market_intelligence or {}).get("supporting_evidence") or []
    market_contra = (market_intelligence or {}).get("contradictory_evidence") or []
    if p.asset_type == "crypto" and crypto_score:
        return [
            _signal(p, strategy, regime, "trend", _average_known([crypto_score.get("technical_trend_score"), metrics.get("trend_score")]), 0.16, "7-day crypto trend blended with price-series trend.", supporting=market_support, opposing=market_contra),
            _signal(p, strategy, regime, "momentum", _average_known([crypto_score.get("momentum_score"), metrics.get("momentum_score")]), 0.14, "24-hour crypto momentum blended with candle momentum.", supporting=market_support, opposing=market_contra),
            _signal(p, strategy, regime, "breakout", _breakout_score(metrics), 0.10, f"Breakout state: {metrics.get('breakout', 'unknown')}."),
            _signal(p, strategy, regime, "volume", metrics.get("volume_trend"), 0.08, "Recent volume trend relative to prior volume."),
            _signal(p, strategy, regime, "atr_volatility", _atr_score(metrics), 0.08, "ATR/volatility suitability for controlled stop distance."),
            _signal(p, strategy, regime, "liquidity", crypto_score.get("liquidity"), 0.14, "Volume to market-cap liquidity proxy."),
            _signal(p, strategy, regime, "risk", crypto_score.get("risk_score"), 0.14, "Risk score derived from volatility and available risk data."),
            _signal(p, strategy, regime, "support_resistance", _support_resistance_score(p, metrics), 0.08, "Entry distance from observed support/resistance."),
            _signal(p, strategy, regime, "sentiment", crypto_score.get("sentiment"), 0.04, "Crypto sentiment when available; unknown otherwise."),
            _signal(p, strategy, regime, "reward_risk", _reward_risk_score(p), 0.04, "Reward-to-risk score from stop and target distance."),
        ]
    latest_close = _latest_close(p.symbol, market or {})
    news_items = (news or {}).get("news", []) if isinstance(news, dict) else []
    return [
        _signal(p, strategy, regime, "trend", metrics.get("trend_score"), 0.14, "Trend score calculated from moving-average relationship.", supporting=market_support, opposing=market_contra),
        _signal(p, strategy, regime, "momentum", metrics.get("momentum_score"), 0.12, "Momentum score calculated from recent close-to-close change."),
        _signal(p, strategy, regime, "breakout", _breakout_score(metrics), 0.10, f"Breakout state: {metrics.get('breakout', 'unknown')}."),
        _signal(p, strategy, regime, "volume", metrics.get("volume_trend"), 0.08, "Recent volume trend relative to prior volume."),
        _signal(p, strategy, regime, "atr_volatility", _atr_score(metrics), 0.08, "ATR/volatility suitability for controlled stop distance."),
        _signal(p, strategy, regime, "support_resistance", _support_resistance_score(p, metrics), 0.10, "Entry distance from observed support/resistance."),
        _signal(p, strategy, regime, "catalyst_news", min(1.0, len(news_items) / 3) if news_items else 0.0, 0.12, p.news_summary or "No recent news."),
        _signal(p, strategy, regime, "market_sentiment", _text_evidence_score(p.market_sentiment_summary), 0.10, p.market_sentiment_summary or "No sentiment summary."),
        _signal(p, strategy, regime, "reward_risk", _reward_risk_score(p), 0.10, "Reward-to-risk score from stop and target distance."),
        _signal(p, strategy, regime, "data_quality", 0.75 if latest_close else 0.25, 0.06, "Latest market bar availability."),
    ]


def evaluate_trade_setup(proposal: TradeProposal, signals: list[dict[str, Any]], regime: dict[str, Any]) -> dict[str, Any]:
    p = proposal.normalized()
    reward = abs(p.take_profit - p.entry_price)
    risk = abs(p.entry_price - p.stop_loss)
    expected_r = reward / risk if risk > 0 else 0.0
    weighted_signal_score = sum(item["score"] * item["weight"] for item in signals)
    total_weight = sum(item["weight"] for item in signals) or 1.0
    quality = weighted_signal_score / total_weight
    return {
        "reward_per_unit": round(reward, 8),
        "risk_per_unit": round(risk, 8),
        "expected_r_multiple": round(expected_r, 4),
        "quality_score": round(quality, 4),
        "timing_score": round(_average([quality, regime.get("confidence", 0.0)]), 4),
        "regime_alignment": regime_alignment(proposal, regime),
        "execution_quality": "basic_market_or_bracket_execution",
        "invalidation_conditions": [
            "price_hits_stop_loss",
            "recommendation_expires_before_execution",
            "broker_or_guardrail_rejects_order",
        ],
    }


def evaluate_portfolio_fit(proposal: TradeProposal, account: AccountContext) -> dict[str, Any]:
    p = proposal.normalized()
    notional = p.entry_price * p.position_size
    position_values = [
        {
            "symbol": getattr(pos, "symbol", "unknown"),
            "market_value": abs(getattr(pos, "market_value", 0.0) or 0.0),
            "unrealized_pl": getattr(pos, "unrealized_pl", 0.0) or 0.0,
        }
        for pos in account.open_positions
    ]
    exposure = sum(item["market_value"] for item in position_values)
    prospective = exposure + notional
    equity = account.equity or 0.0
    duplicate = any(pos.symbol.upper() == p.symbol for pos in account.open_positions)
    largest = max(position_values, key=lambda item: item["market_value"], default=None)
    concentration = (largest["market_value"] / equity) if largest and equity > 0 else None
    proposed_contribution = (notional / prospective) if prospective > 0 else None
    diversification = "limited_data"
    if len(position_values) >= 5 and (concentration is None or concentration < 0.25):
        diversification = "diversified_by_position_count"
    elif len(position_values) <= 2:
        diversification = "concentrated_by_position_count"
    return {
        "current_exposure": round(exposure, 4),
        "proposed_notional": round(notional, 4),
        "prospective_exposure": round(prospective, 4),
        "prospective_exposure_pct": round(prospective / equity, 4) if equity > 0 else None,
        "open_positions": len(account.open_positions),
        "duplicate_position": duplicate,
        "largest_position": largest,
        "largest_position_pct": round(concentration, 4) if concentration is not None else None,
        "proposed_risk_contribution_pct": round(proposed_contribution, 4) if proposed_contribution is not None else None,
        "diversification_status": diversification,
        "sector_concentration": "unknown - sector data not present in account context",
        "theme_concentration": "unknown - theme data not present in account context",
        "correlation": "unknown - correlation data provider not configured",
        "currency_exposure": "broker/account currency evidence only",
        "country_exposure": "unknown - country data not present in account context",
        "capital_efficiency": "reasonable" if equity > 0 and prospective / equity < 0.8 else "highly_deployed" if equity > 0 else "unknown",
        "capital_efficiency_note": "reasonable" if equity > 0 and prospective / equity < 0.8 else "highly deployed" if equity > 0 else "unknown",
        "liquidity": "unknown - portfolio liquidity provider not configured",
        "portfolio_alignment": "duplicate_position_risk" if duplicate else "adds_new_ai_managed_candidate",
        "risk_budget_note": "Final sizing remains controlled by Investment Orchestrator capital allocation.",
    }


def estimate_probability(
    db_path: Path,
    proposal: TradeProposal,
    strategy: dict[str, Any],
    regime: dict[str, Any],
    signals: list[dict[str, Any]],
    trade_setup: dict[str, Any],
) -> dict[str, Any]:
    p = proposal.normalized()
    history = _strategy_history(db_path, strategy["strategy_id"])
    regime_history = _regime_history(db_path, strategy["strategy_id"], regime["primary_regime"])
    signal_history = _signal_history(db_path, strategy["strategy_id"], signals)
    signal_score = _average([item["score"] for item in signals])
    trade_quality = _float(trade_setup.get("quality_score")) or 0.0
    regime_score = float(regime.get("confidence") or 0.0)
    volatility_penalty = max(0.0, (_expected_volatility(regime) - 0.5) * 0.12)
    sample_penalty = 0.08 if history["sample_size"] < int(strategy.get("minimum_sample_size", 30)) else 0.0
    base_probability = (
        (signal_score * 0.34)
        + (trade_quality * 0.22)
        + (regime_score * 0.14)
        + ((_float(strategy.get("historical_statistics", {}).get("win_rate")) or 0.5) * 0.10)
        + ((_float(signal_history.get("observed_effectiveness")) or signal_score) * 0.10)
        + ((_float(regime_history.get("observed_win_rate")) or 0.5) * 0.10)
        - volatility_penalty
        - sample_penalty
    )
    if history["sample_size"] >= 10 and history["observed_win_rate"] is not None:
        base_probability = (base_probability * 0.60) + (history["observed_win_rate"] * 0.40)
    probability = max(0.01, min(0.99, base_probability))
    interval_width = 0.30 if history["sample_size"] < 10 else 0.18 if history["sample_size"] < int(strategy.get("minimum_sample_size", 30)) else 0.10
    expected_r = float(trade_setup.get("expected_r_multiple") or 0.0)
    calibration = calculate_calibration_metrics(db_path, strategy["strategy_id"])
    return {
        "estimate_id": f"prob-{p.proposal_id}",
        "strategy_id": strategy["strategy_id"],
        "regime_id": regime["regime_id"],
        "probability_of_success": round(probability, 4),
        "expected_return_r": round((probability * expected_r) - (1 - probability), 4),
        "expected_drawdown_r": round(1 - probability, 4),
        "historical_sample_size": history["sample_size"],
        "confidence_interval_low": round(max(0.0, probability - interval_width), 4),
        "confidence_interval_high": round(min(1.0, probability + interval_width), 4),
        "expected_holding_time": strategy["expected_holding_period"],
        "expected_volatility": _expected_volatility(regime),
        "calibration_status": "empirical" if history["sample_size"] >= int(strategy.get("minimum_sample_size", 30)) else "uncalibrated_small_sample",
        "evidence": {
            "raw_confidence": p.confidence_score,
            "signal_score": signal_score,
            "trade_quality": trade_quality,
            "regime_score": regime_score,
            "volatility_penalty": volatility_penalty,
            "sample_penalty": sample_penalty,
            "history": history,
            "regime_history": regime_history,
            "signal_history": signal_history,
            "calibration": calibration,
            "note": "Probability is an evidence estimate, not a guarantee.",
        },
    }


def run_trading_committee(
    proposal: TradeProposal,
    strategy: dict[str, Any],
    regime: dict[str, Any],
    signals: list[dict[str, Any]],
    trade_setup: dict[str, Any],
    portfolio: dict[str, Any],
    probability: dict[str, Any],
) -> dict[str, Any]:
    p = proposal.normalized()
    supporting = [
        f"Strategy {strategy['name']} is compatible with {p.asset_type}.",
        f"Expected R multiple is {trade_setup['expected_r_multiple']}.",
        f"Estimated probability of success is {probability['probability_of_success']}.",
        p.plain_english_reasoning,
    ]
    opposing = [
        f"Probability calibration status is {probability['calibration_status']}.",
        f"Market regime confidence is {regime['confidence']}.",
        f"Stop loss would invalidate the idea at {p.stop_loss}.",
    ]
    weak_signals = [item for item in signals if item["score"] < 0.5]
    if weak_signals:
        opposing.append("Weak signals: " + ", ".join(item["signal_name"] for item in weak_signals[:3]) + ".")
    for signal in signals:
        opposing.extend(signal.get("opposing_evidence") or [])
    if portfolio.get("duplicate_position"):
        opposing.append("Portfolio already has this symbol, creating duplicate exposure risk.")
    if trade_setup.get("regime_alignment") in {"poor", "mixed", "insufficient_regime_data"}:
        opposing.append(f"Regime alignment is {trade_setup.get('regime_alignment')}.")
    member_votes = [
        _committee_vote("Macro Analyst", _macro_opinion(regime), regime["confidence"], [f"Primary regime: {regime['primary_regime']}."], regime.get("contradictory_evidence") or []),
        _committee_vote("Technical Analyst", _technical_opinion(signals), _signal_score(signals, ["trend", "momentum", "breakout", "support_resistance"]), ["Reviewed trend, momentum, breakout, and support/resistance."], _weak_signal_names(signals)),
        _committee_vote("Quantitative Analyst", _quant_opinion(probability), probability["probability_of_success"], [f"Expected return {probability['expected_return_r']}R."], [probability["calibration_status"]]),
        _committee_vote("Portfolio Manager", "support" if not portfolio.get("duplicate_position") else "challenge", 0.35 if portfolio.get("duplicate_position") else 0.7, [portfolio["portfolio_alignment"]], ["duplicate exposure"] if portfolio.get("duplicate_position") else []),
        _committee_vote("Risk Officer", "support" if p.risk_percentage <= strategy["maximum_risk"] else "reject", min(1.0, max(0.0, 1.0 - p.risk_percentage)), ["Declared risk reviewed."], ["risk above strategy maximum"] if p.risk_percentage > strategy["maximum_risk"] else []),
        _committee_vote("Execution Specialist", "support", 0.7, ["Execution remains subject to broker adapter and orchestrator validation."], []),
        _committee_vote("Crypto Specialist" if p.asset_type == "crypto" else "Fundamental Analyst", _asset_specialist_opinion(p, signals), _asset_specialist_score(p, signals), [p.news_summary or "No asset-specific narrative."], []),
    ]
    approve_votes = [vote for vote in member_votes if vote["recommendation"] in {"approve", "approve_with_caution"}]
    reject_votes = [vote for vote in member_votes if vote["recommendation"] == "reject"]
    wait_votes = [vote for vote in member_votes if vote["recommendation"] in {"wait", "insufficient_evidence", "conflicting_evidence"}]
    if reject_votes:
        result = "Reject"
    elif len(approve_votes) >= 5 and probability["expected_return_r"] > 0 and not wait_votes:
        result = "Approve"
    elif len(approve_votes) >= 4 and probability["expected_return_r"] > 0:
        result = "Approve with caution"
    elif wait_votes:
        result = "Wait"
    else:
        result = "Insufficient evidence"
    strongest_for = _first_meaningful(supporting)
    strongest_against = _first_meaningful(opposing)
    return {
        "review_id": f"committee-{p.proposal_id}",
        "strategy_id": strategy["strategy_id"],
        "regime_id": regime["regime_id"],
        "committee_result": result,
        "strongest_argument_for": strongest_for,
        "strongest_argument_against": strongest_against,
        "member_votes": member_votes,
        "supporting_evidence": supporting,
        "opposing_evidence": opposing,
        "disagreements": [vote for vote in member_votes if vote["recommendation"] not in {"approve", "approve_with_caution"}],
    }


def build_explainability(
    proposal: TradeProposal,
    strategy: dict[str, Any],
    regime: dict[str, Any],
    signals: list[dict[str, Any]],
    trade_setup: dict[str, Any],
    portfolio: dict[str, Any],
    committee: dict[str, Any],
    probability: dict[str, Any],
) -> dict[str, Any]:
    p = proposal.normalized()
    return {
        "why": committee["strongest_argument_for"],
        "why_now": _why_now(signals, regime),
        "why_not_wait": "The recommendation is time-limited and will expire if not refreshed.",
        "strongest_argument_for": committee["strongest_argument_for"],
        "strongest_argument_against": committee["strongest_argument_against"],
        "historical_performance": probability["evidence"]["history"],
        "expected_outcome": (
            f"Estimated probability {probability['probability_of_success']}, "
            f"expected return {probability['expected_return_r']}R, "
            f"expected drawdown {probability['expected_drawdown_r']}R."
        ),
        "invalidation_conditions": trade_setup["invalidation_conditions"],
        "portfolio_impact": portfolio,
        "strategy": strategy["name"],
        "regime": regime["primary_regime"],
        "note": "Execution still requires Investment Orchestrator, Risk Engine, and broker validation.",
    }


def persist_intelligence_packet(db_path: Path, proposal: TradeProposal, packet: IntelligencePacket) -> None:
    initialize_trading_intelligence_schema(db_path)
    p = proposal.normalized()
    data = packet.to_dict()
    now = utc_now_iso()
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            regime = data["regime"]
            conn.execute(
                """
                INSERT OR REPLACE INTO MARKET_REGIME_SNAPSHOTS (
                    regime_id, created_at, asset_type, exchange, primary_regime,
                    volatility_regime, trend_regime, liquidity_regime, risk_regime,
                    confidence, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    regime["regime_id"],
                    now,
                    regime["asset_type"],
                    regime["exchange"],
                    regime["primary_regime"],
                    regime["volatility_regime"],
                    regime["trend_regime"],
                    regime["liquidity_regime"],
                    regime["risk_regime"],
                    regime["confidence"],
                    json.dumps(regime["evidence"], sort_keys=True),
                ),
            )
            for signal in data["signals"]:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO TRADE_SIGNALS (
                        signal_id, created_at, proposal_id, symbol, asset_type, strategy_id,
                        regime_id, signal_name, score, confidence, weight,
                        historical_effectiveness, evidence_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal["signal_id"],
                        now,
                        p.proposal_id,
                        p.symbol,
                        p.asset_type,
                        signal["strategy_id"],
                        signal["regime_id"],
                        signal["signal_name"],
                        signal["score"],
                        signal["confidence"],
                        signal["weight"],
                        signal.get("historical_effectiveness"),
                        json.dumps(signal["evidence"], sort_keys=True),
                    ),
                )
            committee = data["committee"]
            conn.execute(
                """
                INSERT OR REPLACE INTO TRADING_COMMITTEE_REVIEWS (
                    review_id, created_at, proposal_id, symbol, strategy_id, regime_id,
                    committee_result, strongest_argument_for, strongest_argument_against,
                    member_votes_json, supporting_evidence_json, opposing_evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    committee["review_id"],
                    now,
                    p.proposal_id,
                    p.symbol,
                    committee["strategy_id"],
                    committee["regime_id"],
                    committee["committee_result"],
                    committee["strongest_argument_for"],
                    committee["strongest_argument_against"],
                    json.dumps(committee["member_votes"], sort_keys=True),
                    json.dumps(committee["supporting_evidence"], sort_keys=True),
                    json.dumps(committee["opposing_evidence"], sort_keys=True),
                ),
            )
            probability = data["probability"]
            conn.execute(
                """
                INSERT OR REPLACE INTO PROBABILITY_ESTIMATES (
                    estimate_id, created_at, proposal_id, symbol, strategy_id, regime_id,
                    probability_of_success, expected_return_r, expected_drawdown_r,
                    historical_sample_size, confidence_interval_low, confidence_interval_high,
                    expected_holding_time, expected_volatility, calibration_status, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    probability["estimate_id"],
                    now,
                    p.proposal_id,
                    p.symbol,
                    probability["strategy_id"],
                    probability["regime_id"],
                    probability["probability_of_success"],
                    probability["expected_return_r"],
                    probability["expected_drawdown_r"],
                    probability["historical_sample_size"],
                    probability["confidence_interval_low"],
                    probability["confidence_interval_high"],
                    probability["expected_holding_time"],
                    probability["expected_volatility"],
                    probability["calibration_status"],
                    json.dumps(probability["evidence"], sort_keys=True),
                ),
            )
            _record_calibration_snapshot(conn, probability)


def record_lifecycle_stage(
    db_path: Path,
    proposal: TradeProposal,
    *,
    stage: str,
    reason: str,
    broker: str | None = None,
    strategy_id: str | None = None,
    fees: float | None = None,
    slippage: float | None = None,
    r_multiple: float | None = None,
    mae: float | None = None,
    mfe: float | None = None,
    holding_time_seconds: float | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    initialize_trading_intelligence_schema(db_path)
    p = proposal.normalized()
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO TRADE_LIFECYCLE (
                    created_at, proposal_id, symbol, broker, strategy_id, stage,
                    stage_reason, measurable, fees, slippage, r_multiple, mae, mfe,
                    holding_time_seconds, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    p.proposal_id,
                    p.symbol,
                    broker,
                    strategy_id,
                    stage,
                    reason,
                    1,
                    fees,
                    slippage,
                    r_multiple,
                    mae,
                    mfe,
                    holding_time_seconds,
                    json.dumps(payload or {}, sort_keys=True, default=str),
                ),
            )


def latest_intelligence_packet(db_path: Path, proposal_id: str) -> dict[str, Any] | None:
    initialize_trading_intelligence_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        committee = conn.execute(
            "SELECT * FROM TRADING_COMMITTEE_REVIEWS WHERE proposal_id = ? ORDER BY created_at DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        probability = conn.execute(
            "SELECT * FROM PROBABILITY_ESTIMATES WHERE proposal_id = ? ORDER BY created_at DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        signals = conn.execute(
            "SELECT * FROM TRADE_SIGNALS WHERE proposal_id = ? ORDER BY signal_name ASC",
            (proposal_id,),
        ).fetchall()
        lifecycle = conn.execute(
            "SELECT * FROM TRADE_LIFECYCLE WHERE proposal_id = ? ORDER BY lifecycle_id ASC",
            (proposal_id,),
        ).fetchall()
    if not committee and not probability and not signals:
        return None
    committee_dict = _row_dict(committee)
    probability_dict = _row_dict(probability)
    return {
        "committee": _decode_json_fields(committee_dict),
        "probability": _decode_json_fields(probability_dict),
        "signals": [_decode_json_fields(_row_dict(row)) for row in signals],
        "lifecycle": [_decode_json_fields(_row_dict(row)) for row in lifecycle],
    }


def update_calibration_from_attribution(db_path: Path) -> dict[str, Any]:
    initialize_trading_intelligence_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        strategies = conn.execute("SELECT strategy_id FROM STRATEGY_REGISTRY").fetchall()
    refresh_rows = []
    for row in strategies:
        strategy_id = row["strategy_id"]
        history = _strategy_history(db_path, strategy_id)
        calibration = calculate_calibration_metrics(db_path, strategy_id)
        perf = calculate_performance_metrics(db_path, strategy_id)
        refresh_rows.append((strategy_id, history, calibration, perf))
    metrics_written = 0
    with closing(sqlite3.connect(db_path)) as conn:
        updated = 0
        with conn:
            for strategy_id, history, calibration, perf in refresh_rows:
                conn.execute(
                    """
                    INSERT INTO CONFIDENCE_CALIBRATION (
                        created_at, strategy_id, confidence_bucket, predicted_probability,
                        observed_win_rate, average_r, sample_size, calibration_note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now_iso(),
                        strategy_id,
                        "all",
                        calibration.get("mean_predicted_probability") or 0.0,
                        history.get("observed_win_rate"),
                        history.get("average_r"),
                        history.get("sample_size", 0),
                        f"Calibration refreshed. Brier={calibration.get('brier_score')}, error={calibration.get('calibration_error')}.",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO PERFORMANCE_INTELLIGENCE (
                        created_at, strategy_id, symbol, sample_size, win_rate,
                        average_r, expectancy_r, profit_factor, max_drawdown_r,
                        average_holding_seconds, brier_score, calibration_error,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now_iso(),
                        strategy_id,
                        None,
                        perf["sample_size"],
                        perf["win_rate"],
                        perf["average_r"],
                        perf["expectancy_r"],
                        perf["profit_factor"],
                        perf["max_drawdown_r"],
                        perf["average_holding_seconds"],
                        calibration.get("brier_score"),
                        calibration.get("calibration_error"),
                        json.dumps({"performance": perf, "calibration": calibration}, sort_keys=True),
                    ),
                )
                updated += 1
                metrics_written += 1
    return {"status": "completed", "strategies_updated": updated, "performance_metrics_written": metrics_written}


def record_historical_candle(
    db_path: Path,
    *,
    symbol: str,
    asset_type: str,
    timeframe: str,
    observed_at: str,
    close: float,
    open: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: float | None = None,
    source: str = "manual",
    payload: dict[str, Any] | None = None,
) -> None:
    initialize_trading_intelligence_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO HISTORICAL_CANDLES (
                    symbol, asset_type, timeframe, observed_at, open, high, low,
                    close, volume, source, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol.upper(),
                    asset_type.lower(),
                    timeframe,
                    observed_at,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    source,
                    json.dumps(payload or {}, sort_keys=True),
                ),
            )


def run_strategy_backtest(
    db_path: Path,
    *,
    strategy_id: str,
    symbol: str,
    asset_type: str = "stock",
    timeframe: str = "1d",
    candles: list[dict[str, Any]] | None = None,
    transaction_cost_r: float = 0.02,
    slippage_r: float = 0.02,
) -> dict[str, Any]:
    initialize_trading_intelligence_schema(db_path)
    if candles is None:
        candles = _load_historical_candles(db_path, symbol=symbol, asset_type=asset_type, timeframe=timeframe)
    results = _simulate_strategy(strategy_definition(strategy_id), candles, transaction_cost_r=transaction_cost_r, slippage_r=slippage_r)
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO STRATEGY_BACKTEST_RESULTS (
                    created_at, strategy_id, symbol, asset_type, timeframe, start_at,
                    end_at, trades, win_rate, average_r, expectancy_r, profit_factor,
                    max_drawdown_r, sharpe_proxy, sortino_proxy, result_summary,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    strategy_id,
                    symbol.upper(),
                    asset_type,
                    timeframe,
                    results.get("start_at"),
                    results.get("end_at"),
                    results["trades"],
                    results["win_rate"],
                    results["average_r"],
                    results["expectancy_r"],
                    results["profit_factor"],
                    results["max_drawdown_r"],
                    results["sharpe_proxy"],
                    results["sortino_proxy"],
                    results["result_summary"],
                    json.dumps(results, sort_keys=True),
                ),
            )
            conn.execute(
                """
                INSERT INTO STRATEGY_LAB_RUNS (
                    created_at, strategy_id, run_type, status, input_summary,
                    result_summary, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    strategy_id,
                    "backtest",
                    "completed" if candles else "insufficient_data",
                    f"{symbol.upper()} {asset_type} {timeframe} candles={len(candles)}",
                    results["result_summary"],
                    json.dumps(results, sort_keys=True),
                ),
            )
    return results


def run_walk_forward_validation(
    db_path: Path,
    *,
    strategy_id: str,
    symbol: str,
    asset_type: str = "stock",
    timeframe: str = "1d",
    candles: list[dict[str, Any]] | None = None,
    train_window: int = 30,
    test_window: int = 10,
    transaction_cost_r: float = 0.02,
    slippage_r: float = 0.02,
) -> dict[str, Any]:
    initialize_trading_intelligence_schema(db_path)
    if candles is None:
        candles = _load_historical_candles(db_path, symbol=symbol, asset_type=asset_type, timeframe=timeframe)
    windows = []
    if len(candles) >= train_window + test_window:
        for start in range(0, len(candles) - train_window - test_window + 1, test_window):
            train = candles[start : start + train_window]
            test = candles[start + train_window : start + train_window + test_window]
            train_result = _simulate_strategy(strategy_definition(strategy_id), train, transaction_cost_r=transaction_cost_r, slippage_r=slippage_r)
            test_result = _simulate_strategy(strategy_definition(strategy_id), test, transaction_cost_r=transaction_cost_r, slippage_r=slippage_r)
            windows.append(
                {
                    "window": len(windows) + 1,
                    "train_start": train[0].get("observed_at") if train else None,
                    "train_end": train[-1].get("observed_at") if train else None,
                    "test_start": test[0].get("observed_at") if test else None,
                    "test_end": test[-1].get("observed_at") if test else None,
                    "train": train_result,
                    "out_of_sample": test_result,
                }
            )
    out_of_sample_r = [
        value
        for window in windows
        for value in (window.get("out_of_sample", {}).get("r_values") or [])
    ]
    benchmark = _benchmark_comparison(candles)
    aggregate = _backtest_result_from_r(candles, out_of_sample_r) if out_of_sample_r else _empty_backtest_result(candles, "Walk-forward completed but no out-of-sample trades triggered.")
    validation_status = "passed_validation" if aggregate["trades"] >= 5 and (aggregate["expectancy_r"] or 0) > 0 else "research_only"
    result = {
        "run_type": "walk_forward",
        "strategy_id": strategy_id,
        "symbol": symbol.upper(),
        "asset_type": asset_type,
        "timeframe": timeframe,
        "train_window": train_window,
        "test_window": test_window,
        "window_count": len(windows),
        "validation_status": validation_status,
        "out_of_sample": aggregate,
        "benchmark_comparison": benchmark,
        "benchmark": benchmark,
        "parameter_optimisation": {
            "tested": [
                {"name": "transaction_cost_r", "value": transaction_cost_r},
                {"name": "slippage_r", "value": slippage_r},
                {"name": "train_window", "value": train_window},
                {"name": "test_window", "value": test_window},
            ],
            "selected": "default_governed_parameters",
            "note": "Parameter optimisation is recorded for review only and never changes production rules automatically.",
        },
        "bias_controls": {
            "no_look_ahead_bias": True,
            "out_of_sample_only_for_validation": True,
            "survivorship_bias_note": "Only validates the supplied historical universe; broader universe survivorship checks require provider data.",
        },
        "windows": windows,
    }
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO STRATEGY_LAB_RUNS (
                    created_at, strategy_id, run_type, status, input_summary,
                    result_summary, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    strategy_id,
                    "walk_forward",
                    validation_status,
                    f"{symbol.upper()} {asset_type} {timeframe} train={train_window} test={test_window} candles={len(candles)}",
                    f"Walk-forward {validation_status}; windows={len(windows)}; out-of-sample trades={aggregate['trades']}.",
                    json.dumps(result, sort_keys=True, default=str),
                ),
            )
    return result


def replay_historical_strategy(
    db_path: Path,
    *,
    strategy_id: str,
    symbol: str,
    asset_type: str = "stock",
    timeframe: str = "1d",
    candles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = run_strategy_backtest(
        db_path,
        strategy_id=strategy_id,
        symbol=symbol,
        asset_type=asset_type,
        timeframe=timeframe,
        candles=candles,
    )
    result["replay_type"] = "historical_replay"
    result["note"] = "Historical replay is for validation only and does not approve live trading."
    return result


def calculate_calibration_metrics(db_path: Path, strategy_id: str) -> dict[str, Any]:
    initialize_trading_intelligence_schema(db_path)
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT pe.probability_of_success, pa.profit_loss
                FROM PROBABILITY_ESTIMATES pe
                JOIN PERFORMANCE_ATTRIBUTION pa ON pa.proposal_id = pe.proposal_id
                WHERE pe.strategy_id = ?
                """,
                (strategy_id,),
            ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    if not rows:
        return {
            "strategy_id": strategy_id,
            "sample_size": 0,
            "brier_score": None,
            "calibration_error": None,
            "mean_predicted_probability": None,
            "observed_win_rate": None,
            "buckets": {},
            "note": "No closed outcomes available for calibration.",
        }
    probs = [float(row["probability_of_success"]) for row in rows]
    outcomes = [1.0 if (_float(row["profit_loss"]) or 0.0) > 0 else 0.0 for row in rows]
    brier = sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(rows)
    mean_prob = sum(probs) / len(probs)
    win_rate = sum(outcomes) / len(outcomes)
    buckets: dict[str, dict[str, Any]] = {}
    for prob, outcome in zip(probs, outcomes):
        bucket = _confidence_bucket(prob)
        item = buckets.setdefault(bucket, {"count": 0, "prob_sum": 0.0, "wins": 0.0})
        item["count"] += 1
        item["prob_sum"] += prob
        item["wins"] += outcome
    calibration_error = 0.0
    for bucket in buckets.values():
        bucket["mean_probability"] = bucket["prob_sum"] / bucket["count"]
        bucket["observed_win_rate"] = bucket["wins"] / bucket["count"]
        calibration_error += abs(bucket["mean_probability"] - bucket["observed_win_rate"]) * (bucket["count"] / len(rows))
    return {
        "strategy_id": strategy_id,
        "sample_size": len(rows),
        "brier_score": round(brier, 6),
        "calibration_error": round(calibration_error, 6),
        "mean_predicted_probability": round(mean_prob, 4),
        "observed_win_rate": round(win_rate, 4),
        "buckets": buckets,
        "note": "Calibration metrics compare stored probabilities with closed trade outcomes.",
    }


def calculate_performance_metrics(db_path: Path, strategy_id: str) -> dict[str, Any]:
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT pa.*
                FROM PERFORMANCE_ATTRIBUTION pa
                LEFT JOIN TRADE_LIFECYCLE tl ON tl.proposal_id = pa.proposal_id
                WHERE tl.strategy_id = ?
                GROUP BY pa.attribution_id
                """,
                (strategy_id,),
            ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    pnls = [_float(row["profit_loss"]) or 0.0 for row in rows]
    holding = [_float(row["holding_period_seconds"]) for row in rows if _float(row["holding_period_seconds"]) is not None]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "strategy_id": strategy_id,
        "sample_size": len(pnls),
        "win_rate": round(len(wins) / len(pnls), 4) if pnls else None,
        "average_r": round(sum(pnls) / len(pnls), 4) if pnls else None,
        "expectancy_r": round(sum(pnls) / len(pnls), 4) if pnls else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "max_drawdown_r": round(_max_drawdown(pnls), 4) if pnls else None,
        "average_holding_seconds": round(sum(holding) / len(holding), 2) if holding else None,
    }


def _seed_strategy_registry(conn: sqlite3.Connection) -> None:
    now = utc_now_iso()
    for item in STRATEGIES.values():
        conn.execute(
            """
            INSERT OR IGNORE INTO STRATEGY_REGISTRY (
                strategy_id, name, purpose, supported_assets_json, supported_regimes_json,
                expected_holding_period, historical_edge, minimum_evidence_json,
                maximum_risk, exit_methodology, invalid_conditions_json,
                production_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["strategy_id"],
                item["name"],
                item["purpose"],
                json.dumps(item["supported_assets"], sort_keys=True),
                json.dumps(item["supported_regimes"], sort_keys=True),
                item["expected_holding_period"],
                item["historical_edge"],
                json.dumps(item["minimum_evidence"], sort_keys=True),
                item["maximum_risk"],
                item["exit_methodology"],
                json.dumps(item["invalid_conditions"], sort_keys=True),
                item["production_status"],
                now,
                now,
            ),
        )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _record_calibration_snapshot(conn: sqlite3.Connection, probability: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO CONFIDENCE_CALIBRATION (
            created_at, strategy_id, confidence_bucket, predicted_probability,
            observed_win_rate, average_r, sample_size, calibration_note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            utc_now_iso(),
            probability["strategy_id"],
            _confidence_bucket(probability["probability_of_success"]),
            probability["probability_of_success"],
            probability["evidence"]["history"].get("observed_win_rate"),
            probability["evidence"]["history"].get("average_r"),
            probability["historical_sample_size"],
            "Snapshot recorded when recommendation probability was estimated.",
        ),
    )


def _strategy_history(db_path: Path, strategy_id: str) -> dict[str, Any]:
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT pa.profit_loss
                FROM PERFORMANCE_ATTRIBUTION pa
                LEFT JOIN TRADE_LIFECYCLE tl ON tl.proposal_id = pa.proposal_id
                WHERE tl.strategy_id = ? OR ? = ''
                GROUP BY pa.attribution_id
                """,
                (strategy_id, strategy_id),
            ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    pnls = [_float(row["profit_loss"]) or 0.0 for row in rows]
    wins = [value for value in pnls if value > 0]
    sample = len(pnls)
    return {
        "strategy_id": strategy_id,
        "sample_size": sample,
        "observed_win_rate": (len(wins) / sample) if sample else None,
        "average_r": (sum(pnls) / sample) if sample else None,
        "predicted_probability": None,
        "note": "No statistically meaningful sample yet." if sample < 10 else "Empirical sample available.",
    }


def _regime_history(db_path: Path, strategy_id: str, regime_name: str) -> dict[str, Any]:
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT pa.profit_loss
                FROM PERFORMANCE_ATTRIBUTION pa
                JOIN MARKET_REGIME_SNAPSHOTS mrs ON mrs.regime_id IN (
                    SELECT regime_id FROM PROBABILITY_ESTIMATES WHERE proposal_id = pa.proposal_id
                )
                WHERE mrs.primary_regime = ?
                """,
                (regime_name,),
            ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    pnls = [_float(row["profit_loss"]) or 0.0 for row in rows]
    wins = [value for value in pnls if value > 0]
    return {
        "strategy_id": strategy_id,
        "regime": regime_name,
        "sample_size": len(pnls),
        "observed_win_rate": (len(wins) / len(pnls)) if pnls else None,
    }


def _signal_history(db_path: Path, strategy_id: str, signals: list[dict[str, Any]]) -> dict[str, Any]:
    names = [signal["signal_name"] for signal in signals]
    if not names:
        return {"sample_size": 0, "observed_effectiveness": None}
    placeholders = ",".join("?" for _ in names)
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT AVG(score) AS avg_score, COUNT(*) AS sample_size
                FROM TRADE_SIGNALS
                WHERE strategy_id = ? AND signal_name IN ({placeholders})
                """,
                (strategy_id, *names),
            ).fetchone()
    except sqlite3.OperationalError:
        rows = None
    sample = int(rows["sample_size"] or 0) if rows else 0
    return {
        "sample_size": sample,
        "observed_effectiveness": _float(rows["avg_score"]) if rows else None,
    }


def _signal(
    proposal: TradeProposal,
    strategy: dict[str, Any],
    regime: dict[str, Any],
    name: str,
    raw_score: Any,
    weight: float,
    evidence: str,
    supporting: list[str] | None = None,
    opposing: list[str] | None = None,
) -> dict[str, Any]:
    score = _float(raw_score)
    if score is None:
        score = 0.0
    score = max(0.0, min(1.0, score))
    return {
        "signal_id": f"signal-{proposal.proposal_id}-{name}",
        "strategy_id": strategy["strategy_id"],
        "regime_id": regime["regime_id"],
        "signal_name": name,
        "score": round(score, 4),
        "confidence": round(score, 4),
        "weight": weight,
        "historical_effectiveness": None,
        "supporting_evidence": list(supporting or [evidence]),
        "opposing_evidence": list(opposing or ([] if score >= 0.5 else [f"{name} evidence is weak or unknown."])),
        "evidence": {
            "summary": evidence,
            "source": "available_platform_data",
            "supporting_evidence": list(supporting or [evidence]),
            "opposing_evidence": list(opposing or ([] if score >= 0.5 else [f"{name} evidence is weak or unknown."])),
        },
    }


def _committee_vote(
    member: str,
    opinion: str,
    confidence: float,
    supporting: list[str],
    opposing: list[str],
) -> dict[str, Any]:
    normalized = max(0.0, min(1.0, float(confidence or 0.0)))
    recommendation = {
        "support": "approve",
        "caution": "approve_with_caution",
        "challenge": "conflicting_evidence",
        "wait": "wait",
        "reject": "reject",
        "insufficient": "insufficient_evidence",
    }.get(opinion, opinion)
    return {
        "member": member,
        "opinion": opinion,
        "confidence": round(normalized, 4),
        "score": round(normalized, 4),
        "vote": "support" if recommendation in {"approve", "approve_with_caution"} else "challenge",
        "supporting_evidence": supporting,
        "opposing_evidence": opposing,
        "questions": _committee_questions(member, recommendation, opposing),
        "recommendation": recommendation,
        "rationale": "; ".join(supporting + opposing),
    }


def _member_vote(member: str, score: float, rationale: str) -> dict[str, Any]:
    normalized = max(0.0, min(1.0, float(score or 0.0)))
    return {
        "member": member,
        "score": round(normalized, 4),
        "vote": "support" if normalized >= 0.55 else "challenge",
        "rationale": rationale,
    }


def _macro_opinion(regime: dict[str, Any]) -> str:
    if regime["primary_regime"] in {"bull", "recovery", "expansion"}:
        return "support"
    if regime["primary_regime"] in {"bear", "crisis", "contraction"}:
        return "reject"
    if regime["primary_regime"] == "unknown":
        return "insufficient"
    return "caution"


def _technical_opinion(signals: list[dict[str, Any]]) -> str:
    score = _signal_score(signals, ["trend", "momentum", "breakout", "support_resistance", "reward_risk"])
    if score >= 0.65:
        return "support"
    if score >= 0.52:
        return "caution"
    if score <= 0.35:
        return "reject"
    return "wait"


def _quant_opinion(probability: dict[str, Any]) -> str:
    if probability["expected_return_r"] <= 0:
        return "reject"
    if probability["calibration_status"] != "empirical":
        return "caution"
    return "support"


def _asset_specialist_opinion(proposal: TradeProposal, signals: list[dict[str, Any]]) -> str:
    if proposal.asset_type == "crypto":
        score = _signal_score(signals, ["liquidity", "risk", "sentiment", "trend"])
    else:
        score = _signal_score(signals, ["catalyst_news", "market_sentiment", "data_quality"])
    if score >= 0.6:
        return "support"
    if score >= 0.45:
        return "caution"
    return "insufficient"


def _asset_specialist_score(proposal: TradeProposal, signals: list[dict[str, Any]]) -> float:
    if proposal.asset_type == "crypto":
        return _signal_score(signals, ["liquidity", "risk", "sentiment", "trend"])
    return _signal_score(signals, ["catalyst_news", "market_sentiment", "data_quality"])


def _committee_questions(member: str, recommendation: str, opposing: list[str]) -> list[str]:
    if recommendation in {"approve", "approve_with_caution"} and not opposing:
        return []
    return [f"{member} asks for monitoring of: {item}" for item in opposing[:3]] or [f"{member} asks for more evidence before increasing conviction."]


def _weak_signal_names(signals: list[dict[str, Any]]) -> list[str]:
    return [f"{signal['signal_name']} weak at {signal['score']}" for signal in signals if signal["score"] < 0.5]


def _reward_risk_score(proposal: TradeProposal) -> float:
    risk = abs(proposal.entry_price - proposal.stop_loss)
    reward = abs(proposal.take_profit - proposal.entry_price)
    if risk <= 0:
        return 0.0
    return max(0.0, min(1.0, (reward / risk) / 3.0))


def _breakout_score(metrics: dict[str, Any]) -> float | None:
    breakout = metrics.get("breakout")
    if breakout == "upside_breakout":
        return 0.85
    if breakout == "no_breakout":
        return 0.5
    if breakout == "downside_breakdown":
        return 0.15
    return None


def _atr_score(metrics: dict[str, Any]) -> float | None:
    atr_pct = _float(metrics.get("atr_pct"))
    if atr_pct is None:
        return None
    if atr_pct <= 0.01:
        return 0.55
    if atr_pct <= 0.04:
        return 0.75
    if atr_pct <= 0.08:
        return 0.45
    return 0.2


def _support_resistance_score(proposal: TradeProposal, metrics: dict[str, Any]) -> float | None:
    support = _float(metrics.get("support"))
    resistance = _float(metrics.get("resistance"))
    if support is None or resistance is None or proposal.entry_price <= 0:
        return None
    distance_to_support = (proposal.entry_price - support) / proposal.entry_price
    distance_to_resistance = (resistance - proposal.entry_price) / proposal.entry_price
    if proposal.side == "buy":
        return max(0.0, min(1.0, 0.5 + distance_to_resistance - max(0, distance_to_support - 0.08)))
    return max(0.0, min(1.0, 0.5 + distance_to_support - max(0, distance_to_resistance - 0.08)))


def _text_evidence_score(text: str | None) -> float:
    if not text:
        return 0.0
    lower = text.lower()
    positives = sum(1 for word in ["positive", "constructive", "strong", "support", "bull", "improving"] if word in lower)
    negatives = sum(1 for word in ["negative", "weak", "risk", "bear", "declining", "caution"] if word in lower)
    return max(0.0, min(1.0, 0.5 + positives * 0.1 - negatives * 0.1))


def regime_alignment(proposal: TradeProposal, regime: dict[str, Any]) -> str:
    if regime["primary_regime"] in {"bear", "crisis", "contraction"} and proposal.side == "buy":
        return "poor"
    if regime["trend_regime"] == "trending" and regime["risk_regime"] in {"risk_on", "neutral"}:
        return "aligned"
    if regime["primary_regime"] == "unknown":
        return "insufficient_regime_data"
    return "mixed"


def _expected_volatility(regime: dict[str, Any]) -> float:
    if regime["volatility_regime"] == "high_volatility":
        return 0.75
    if regime["volatility_regime"] == "low_volatility":
        return 0.35
    return 0.5


def _why_now(signals: list[dict[str, Any]], regime: dict[str, Any]) -> str:
    strongest = max(signals, key=lambda item: item["score"], default=None)
    if strongest:
        return f"The strongest current signal is {strongest['signal_name']} at {strongest['score']} in a {regime['primary_regime']} regime."
    return "No strong timing signal was available."


def _signal_score(signals: list[dict[str, Any]], names: list[str]) -> float:
    selected = [item["score"] for item in signals if item["signal_name"] in names]
    return _average(selected)


def _average_known(values: list[Any]) -> float | None:
    numeric = [_float(value) for value in values]
    clean = [value for value in numeric if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _has_bull_and_bear(committee: dict[str, Any]) -> bool:
    return bool(str(committee.get("strongest_argument_for") or "").strip()) and bool(
        str(committee.get("strongest_argument_against") or "").strip()
    )


def _first_meaningful(items: list[str]) -> str:
    for item in items:
        text = str(item or "").strip()
        if text:
            return text
    return ""


def _confidence_bucket(value: float) -> str:
    if value >= 0.9:
        return "90_to_100"
    if value >= 0.85:
        return "85_to_90"
    if value >= 0.75:
        return "75_to_85"
    return "below_75"


def _latest_close(symbol: str, market: dict[str, Any]) -> float | None:
    bars = market.get("bars", {}) if isinstance(market, dict) else {}
    row = bars.get(symbol) or bars.get(symbol.upper())
    if not row:
        return None
    return _float(row.get("c") or row.get("close"))


def _candles_for_symbol(symbol: str, market: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(market, dict):
        return []
    history = market.get("history") or market.get("candles")
    if isinstance(history, dict):
        rows = history.get(symbol) or history.get(symbol.upper()) or []
        return [dict(item) for item in rows if isinstance(item, dict)]
    if isinstance(history, list):
        return [dict(item) for item in history if isinstance(item, dict)]
    bars = market.get("bars", {})
    row = bars.get(symbol) or bars.get(symbol.upper()) if isinstance(bars, dict) else None
    return [dict(row)] if isinstance(row, dict) else []


def _load_historical_candles(db_path: Path, *, symbol: str, asset_type: str, timeframe: str) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT observed_at, open, high, low, close, volume
            FROM HISTORICAL_CANDLES
            WHERE UPPER(symbol) = UPPER(?) AND asset_type = ? AND timeframe = ?
            ORDER BY observed_at ASC
            """,
            (symbol, asset_type, timeframe),
        ).fetchall()
    return [dict(row) for row in rows]


def _simulate_strategy(strategy: dict[str, Any], candles: list[dict[str, Any]], *, transaction_cost_r: float, slippage_r: float) -> dict[str, Any]:
    closes = [_float(item.get("close") or item.get("c")) for item in candles]
    closes = [value for value in closes if value is not None]
    if len(closes) < 25:
        return _empty_backtest_result(candles, "Insufficient candle history for backtest.")
    r_values: list[float] = []
    for i in range(20, len(closes) - 1):
        window = [{"close": close} for close in closes[: i + 1]]
        metrics = analyze_price_series(window)
        entry_signal = False
        if strategy["strategy_id"] in {"crypto_trend_following_2r", "trend_following", "momentum", "swing_continuation"}:
            entry_signal = (metrics.get("trend_score") or 0) >= 0.6 and (metrics.get("momentum_score") or 0) >= 0.55
        elif strategy["strategy_id"] in {"mean_reversion", "range_trading", "value_pullback"}:
            entry_signal = metrics.get("mean_reversion") == "oversold_below_mean"
        elif strategy["strategy_id"] in {"breakout", "volatility_expansion"}:
            entry_signal = metrics.get("breakout") == "upside_breakout"
        if not entry_signal:
            continue
        entry = closes[i]
        next_close = closes[i + 1]
        stop_distance = max(entry * 0.02, 0.000001)
        r = ((next_close - entry) / stop_distance) - transaction_cost_r - slippage_r
        r_values.append(max(-1.0, min(3.0, r)))
    return _backtest_result_from_r(candles, r_values)


def _empty_backtest_result(candles: list[dict[str, Any]], summary: str) -> dict[str, Any]:
    return {
        "start_at": candles[0].get("observed_at") if candles else None,
        "end_at": candles[-1].get("observed_at") if candles else None,
        "trades": 0,
        "win_rate": None,
        "average_r": None,
        "expectancy_r": None,
        "profit_factor": None,
        "max_drawdown_r": None,
        "sharpe_proxy": None,
        "sortino_proxy": None,
        "result_summary": summary,
        "r_values": [],
    }


def _backtest_result_from_r(candles: list[dict[str, Any]], r_values: list[float]) -> dict[str, Any]:
    if not r_values:
        return _empty_backtest_result(candles, "Backtest completed but no strategy entries triggered.")
    wins = [value for value in r_values if value > 0]
    losses = [value for value in r_values if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    avg = sum(r_values) / len(r_values)
    return {
        "start_at": candles[0].get("observed_at") if candles else None,
        "end_at": candles[-1].get("observed_at") if candles else None,
        "trades": len(r_values),
        "win_rate": round(len(wins) / len(r_values), 4),
        "average_r": round(avg, 4),
        "expectancy_r": round(avg, 4),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "max_drawdown_r": round(_max_drawdown(r_values), 4),
        "sharpe_proxy": round(avg / (_stddev(r_values) or 1), 4),
        "sortino_proxy": round(avg / (_stddev(losses) or 1), 4),
        "result_summary": f"Backtest completed with {len(r_values)} trade(s), average {avg:.2f}R.",
        "r_values": r_values,
    }


def _average(values: list[Any]) -> float:
    numeric = [_float(value) for value in values]
    clean = [float(value) for value in numeric if value is not None]
    return sum(clean) / len(clean) if clean else 0.0


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def _returns(closes: list[float]) -> list[float]:
    return [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes)) if closes[i - 1]]


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    if len(highs) < 2 or len(lows) < 2 or len(closes) < 2:
        return None
    ranges = []
    for i in range(1, min(len(highs), len(lows), len(closes))):
        ranges.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    recent = ranges[-period:]
    return sum(recent) / len(recent) if recent else None


def _pct_to_score(value: float | None) -> float:
    if value is None:
        return 0.5
    return max(0.0, min(1.0, 0.5 + value * 5))


def _primary_regime(trend: float | None, risk: float | None, volatility: float | None) -> str:
    trend_value = 0.5 if trend is None else trend
    risk_value = 0.5 if risk is None else risk
    volatility_value = 0.0 if volatility is None else volatility
    if trend_value >= 0.68 and risk_value >= 0.55:
        return "bull"
    if trend_value <= 0.32 and risk_value <= 0.45:
        return "bear"
    if trend_value >= 0.58 and risk_value < 0.5:
        return "transition"
    if volatility_value >= 0.75:
        return "crisis"
    if trend_value >= 0.55:
        return "recovery"
    if trend_value <= 0.45:
        return "contraction"
    return "range"


def _market_supporting_evidence(metrics: dict[str, Any], crypto_score: dict[str, Any] | None) -> list[str]:
    evidence = []
    if (metrics.get("trend_score") or 0) >= 0.6:
        evidence.append("Price-series trend is positive.")
    if (metrics.get("momentum_score") or 0) >= 0.6:
        evidence.append("Recent momentum is positive.")
    if metrics.get("breakout") == "upside_breakout":
        evidence.append("Price is attempting an upside breakout.")
    if crypto_score and (_float(crypto_score.get("liquidity")) or 0) >= 0.5:
        evidence.append("Crypto liquidity score is supportive.")
    return evidence or ["No strong market-level supporting evidence was available."]


def _market_contradictory_evidence(metrics: dict[str, Any], crypto_score: dict[str, Any] | None) -> list[str]:
    evidence = []
    if (metrics.get("trend_score") is not None) and metrics.get("trend_score") < 0.45:
        evidence.append("Price-series trend is weak.")
    if metrics.get("breakout") == "downside_breakdown":
        evidence.append("Price is breaking down through support.")
    if (metrics.get("atr_pct") or 0) > 0.08:
        evidence.append("ATR is high relative to price, increasing stop-out risk.")
    if crypto_score and (_float(crypto_score.get("risk_score")) or 0) < 0.45:
        evidence.append("Crypto risk score is weak.")
    return evidence


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return abs(max_dd)


def _benchmark_comparison(candles: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [_float(item.get("close") or item.get("c")) for item in candles]
    closes = [value for value in closes if value is not None]
    if len(closes) < 2 or not closes[0]:
        return {
            "benchmark": "buy_and_hold",
            "return_pct": None,
            "note": "Benchmark unavailable because there is not enough historical price data.",
        }
    return_pct = (closes[-1] / closes[0]) - 1
    return {
        "benchmark": "buy_and_hold",
        "return_pct": round(return_pct, 6),
        "note": "Benchmark compares strategy validation against simply holding the asset over the same supplied history.",
    }


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _decode_json_fields(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    decoded = dict(payload)
    for key in list(decoded):
        if key.endswith("_json") and decoded[key]:
            try:
                decoded[key[:-5]] = json.loads(decoded[key])
            except (TypeError, json.JSONDecodeError):
                pass
    return decoded


STRATEGIES: dict[str, dict[str, Any]] = {
    "equity_conservative_ai_assisted": {
        "strategy_id": "equity_conservative_ai_assisted",
        "name": "Conservative AI-Assisted Equity Setup",
        "purpose": "Use structured AI reasoning plus broker market/news data to identify conservative paper equity setups.",
        "supported_assets": ["stock", "etf"],
        "supported_regimes": ["unknown", "bull", "range", "recovery"],
        "expected_holding_period": "intraday_to_multi_day",
        "historical_edge": "Not yet statistically validated; requires paper attribution.",
        "minimum_evidence": ["latest_market_bar", "news_or_context", "stop_loss", "take_profit", "bull_case", "bear_case"],
        "maximum_risk": 0.01,
        "exit_methodology": "Bracket order with mandatory stop loss and take profit.",
        "invalid_conditions": ["market_closed", "stop_loss_missing", "take_profit_missing", "bear_case_missing"],
        "production_status": "paper_only",
    },
    "crypto_trend_following_2r": {
        "strategy_id": "crypto_trend_following_2r",
        "name": "Crypto Trend Following 2R",
        "purpose": "Trade approved Kraken crypto pairs when due-diligence, trend, liquidity, and risk scores support a small controlled long entry.",
        "supported_assets": ["crypto"],
        "supported_regimes": ["bull", "trending", "risk_on"],
        "expected_holding_period": "hours_to_days",
        "historical_edge": "Not yet statistically validated; early live/paper attribution required.",
        "minimum_evidence": ["crypto_score", "positive_trend", "liquidity", "stop_loss", "take_profit", "bull_case", "bear_case"],
        "maximum_risk": 0.01,
        "exit_methodology": "Managed exit with mandatory stop loss and take profit; trailing stop only when founder-approved.",
        "invalid_conditions": ["trend_below_threshold", "pair_not_allowed", "bear_case_missing", "crypto_policy_disabled"],
        "production_status": "founder_controlled_live_kraken",
    },
    "paper_validation_2r": {
        "strategy_id": "paper_validation_2r",
        "name": "Paper Validation 2R",
        "purpose": "Validate execution plumbing with a simple 1R stop and 2R target in paper trading only.",
        "supported_assets": ["stock"],
        "supported_regimes": ["unknown"],
        "expected_holding_period": "test_only",
        "historical_edge": "No trading edge claimed; operational validation only.",
        "minimum_evidence": ["latest_market_bar", "stop_loss", "take_profit", "bull_case", "bear_case"],
        "maximum_risk": 0.005,
        "exit_methodology": "Paper bracket order.",
        "invalid_conditions": ["non_paper_execution", "bear_case_missing"],
        "production_status": "test_only",
    },
    "trend_following": {
        "strategy_id": "trend_following",
        "name": "Trend Following",
        "purpose": "Enter long when moving-average trend, momentum, and regime support persistence.",
        "supported_assets": ["stock", "etf", "crypto"],
        "supported_regimes": ["bull", "trending", "recovery", "expansion"],
        "expected_holding_period": "multi_day_to_multi_week",
        "historical_edge": "Research object pending backtest validation.",
        "minimum_evidence": ["trend_score", "momentum_score", "atr", "reward_risk"],
        "maximum_risk": 0.01,
        "exit_methodology": "Stop below invalidation level; target based on minimum 2R or trailing stop when approved.",
        "invalid_conditions": ["bear_regime", "trend_break", "volatility_extreme"],
        "production_status": "research_only",
        "minimum_reward_risk": 2.0,
    },
    "momentum": {
        "strategy_id": "momentum",
        "name": "Momentum",
        "purpose": "Use independently measured price momentum and volume confirmation.",
        "supported_assets": ["stock", "etf", "crypto"],
        "supported_regimes": ["bull", "trending", "expansion"],
        "expected_holding_period": "hours_to_days",
        "historical_edge": "Research object pending backtest validation.",
        "minimum_evidence": ["momentum_score", "volume", "trend_score"],
        "maximum_risk": 0.01,
        "exit_methodology": "Exit on momentum failure, stop loss, or target.",
        "invalid_conditions": ["momentum_reversal", "thin_liquidity", "risk_off"],
        "production_status": "research_only",
    },
    "breakout": {
        "strategy_id": "breakout",
        "name": "Breakout",
        "purpose": "Enter when price clears observed resistance with acceptable volatility.",
        "supported_assets": ["stock", "crypto"],
        "supported_regimes": ["range", "transition", "trending"],
        "expected_holding_period": "hours_to_days",
        "historical_edge": "Research object pending backtest validation.",
        "minimum_evidence": ["resistance", "breakout", "volume", "atr"],
        "maximum_risk": 0.01,
        "exit_methodology": "Exit failed breakout, stop, or target.",
        "invalid_conditions": ["false_breakout", "no_volume_confirmation"],
        "production_status": "research_only",
    },
    "pullback": {
        "strategy_id": "pullback",
        "name": "Pullback",
        "purpose": "Enter a constructive trend after a controlled retracement toward moving averages or support.",
        "supported_assets": ["stock", "etf", "crypto"],
        "supported_regimes": ["bull", "recovery", "trending"],
        "expected_holding_period": "hours_to_days",
        "historical_edge": "Research object pending backtest validation.",
        "minimum_evidence": ["positive_primary_trend", "controlled_pullback", "support", "reward_risk"],
        "maximum_risk": 0.008,
        "exit_methodology": "Exit when support fails, trend resumes into target, or stop is hit.",
        "invalid_conditions": ["trend_broken", "support_lost", "risk_off"],
        "production_status": "research_only",
    },
    "mean_reversion": {
        "strategy_id": "mean_reversion",
        "name": "Mean Reversion",
        "purpose": "Enter oversold conditions near support only in range regimes.",
        "supported_assets": ["stock", "etf", "crypto"],
        "supported_regimes": ["range", "mean_reverting"],
        "expected_holding_period": "hours_to_days",
        "historical_edge": "Research object pending backtest validation.",
        "minimum_evidence": ["support", "oversold", "range_regime"],
        "maximum_risk": 0.008,
        "exit_methodology": "Exit at mean, resistance, stop, or failed support.",
        "invalid_conditions": ["bear_breakdown", "support_lost", "crisis_regime"],
        "production_status": "research_only",
    },
    "range_trading": {
        "strategy_id": "range_trading",
        "name": "Range Trading",
        "purpose": "Trade between visible support and resistance only when market structure is balanced.",
        "supported_assets": ["stock", "etf", "crypto"],
        "supported_regimes": ["range", "mean_reverting", "low_volatility"],
        "expected_holding_period": "hours_to_days",
        "historical_edge": "Research object pending range-specific validation.",
        "minimum_evidence": ["support", "resistance", "balanced_structure", "defined_stop"],
        "maximum_risk": 0.006,
        "exit_methodology": "Exit near range resistance, failed support, stop, or target.",
        "invalid_conditions": ["breakdown", "trend_acceleration", "volatility_expansion"],
        "production_status": "research_only",
    },
    "volatility_expansion": {
        "strategy_id": "volatility_expansion",
        "name": "Volatility Expansion",
        "purpose": "Identify expansion after compression, only with trend confirmation.",
        "supported_assets": ["stock", "crypto"],
        "supported_regimes": ["transition", "trending"],
        "expected_holding_period": "hours_to_days",
        "historical_edge": "Research object pending backtest validation.",
        "minimum_evidence": ["atr_change", "breakout", "volume"],
        "maximum_risk": 0.008,
        "exit_methodology": "Exit on volatility failure or bracket outcome.",
        "invalid_conditions": ["atr_extreme", "liquidity_weak"],
        "production_status": "research_only",
    },
    "swing_continuation": {
        "strategy_id": "swing_continuation",
        "name": "Swing Continuation",
        "purpose": "Continue with an established swing when trend, momentum, and risk/reward remain supportive.",
        "supported_assets": ["stock", "etf", "crypto"],
        "supported_regimes": ["bull", "trending", "recovery"],
        "expected_holding_period": "multi_day_to_multi_week",
        "historical_edge": "Research object pending swing attribution.",
        "minimum_evidence": ["trend_score", "momentum_score", "higher_bias", "reward_risk"],
        "maximum_risk": 0.01,
        "exit_methodology": "Exit on trend failure, stop, target, or adverse regime change.",
        "invalid_conditions": ["momentum_failure", "lower_bias", "bear_regime"],
        "production_status": "research_only",
    },
    "crypto_infrastructure_trend": {
        "strategy_id": "crypto_infrastructure_trend",
        "name": "Crypto Infrastructure Trend",
        "purpose": "Track infrastructure, layer 1, and layer 2 crypto assets when liquidity and trend evidence are aligned.",
        "supported_assets": ["crypto"],
        "supported_regimes": ["bull", "trending", "risk_on"],
        "expected_holding_period": "hours_to_days",
        "historical_edge": "Research object pending crypto attribution.",
        "minimum_evidence": ["crypto_score", "liquidity", "trend_score", "risk_score", "reward_risk"],
        "maximum_risk": 0.008,
        "exit_methodology": "Managed exit with mandatory stop and target; trailing stop only after Founder approval.",
        "invalid_conditions": ["thin_liquidity", "crypto_risk_weak", "trend_break"],
        "production_status": "research_only",
    },
    "institutional_accumulation": {
        "strategy_id": "institutional_accumulation",
        "name": "Institutional Accumulation",
        "purpose": "Identify possible accumulation using volume persistence, constructive price structure, and controlled volatility.",
        "supported_assets": ["stock", "etf", "crypto"],
        "supported_regimes": ["range", "recovery", "bull"],
        "expected_holding_period": "multi_day_to_multi_week",
        "historical_edge": "Research object pending volume and flow data expansion.",
        "minimum_evidence": ["volume_trend", "support", "balanced_or_higher_structure"],
        "maximum_risk": 0.008,
        "exit_methodology": "Exit if volume confirmation fails, support breaks, or target/stop is reached.",
        "invalid_conditions": ["distribution_volume", "support_lost", "liquidity_weak"],
        "production_status": "research_only",
    },
    "quality_growth": {
        "strategy_id": "quality_growth",
        "name": "Quality Growth",
        "purpose": "Longer-term quality company pullback or continuation research object.",
        "supported_assets": ["stock"],
        "supported_regimes": ["bull", "recovery", "expansion"],
        "expected_holding_period": "multi_week_to_multi_month",
        "historical_edge": "Research object pending fundamental data expansion.",
        "minimum_evidence": ["fundamental_quality", "trend", "reasonable_risk"],
        "maximum_risk": 0.01,
        "exit_methodology": "Exit on thesis impairment, stop, or target.",
        "invalid_conditions": ["fundamental_deterioration", "bear_regime"],
        "production_status": "research_only",
    },
    "value_pullback": {
        "strategy_id": "value_pullback",
        "name": "Value Pullback",
        "purpose": "Identify high-quality assets pulling back toward support or value zone.",
        "supported_assets": ["stock", "etf"],
        "supported_regimes": ["range", "recovery", "bull"],
        "expected_holding_period": "multi_day_to_multi_week",
        "historical_edge": "Research object pending valuation data expansion.",
        "minimum_evidence": ["support", "mean_reversion", "fundamental_context"],
        "maximum_risk": 0.01,
        "exit_methodology": "Exit on support failure, thesis impairment, or target.",
        "invalid_conditions": ["support_lost", "value_trap_risk"],
        "production_status": "research_only",
    },
}
