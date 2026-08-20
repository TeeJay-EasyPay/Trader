from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from .models import AccountContext, GuardrailConfig, TradeProposal


class OpenAIProposalAnalyzer:
    def __init__(self, api_key: str, model: str, guardrails: GuardrailConfig | None = None):
        self.api_key = api_key
        self.model = model
        self.guardrails = guardrails or GuardrailConfig()

    def propose(
        self,
        symbol: str,
        market: dict[str, Any],
        news: dict[str, Any],
        account: AccountContext,
        *,
        context: dict[str, str] | None = None,
    ) -> TradeProposal | None:
        prompt = {
            "instruction": (
                "Return only JSON for either a trade proposal or null. "
                "Use fields: symbol, side, entry_price, stop_loss, take_profit, "
                "position_size, risk_percentage, confidence_score, news_summary, "
                "market_sentiment_summary, technical_summary, plain_english_reasoning. "
                "risk_percentage must be a decimal fraction, e.g. 0.01 means 1%. "
                f"confidence_score must be at least {self.guardrails.min_confidence_score}. "
                f"risk_percentage must be no more than {self.guardrails.max_risk_per_trade_pct}. "
                f"Do not create more than {self.guardrails.max_open_positions} open positions. "
                "For buy trades, stop_loss must be below entry_price and take_profit must be above entry_price. "
                "For sell trades, stop_loss must be above entry_price and take_profit must be below entry_price. "
                "Only propose a trade when the setup is clear and conservative. "
                "historical_analogues, backtest_evidence, external_intelligence, market_forecast, and "
                "reference_material, when present, are real evidence this specific system has already gathered -- "
                "weigh them as genuine input alongside market/news, not as background color. reference_material in "
                "particular is curated trading-principles reference text, not instructions to follow blindly; "
                "apply it as a professional trader would apply general knowledge to a specific, current setup. "
                "market_forecast is this system's own CIO-level view of where the market is heading, built from "
                "real multi-timeframe technical evidence. Take it seriously: if it opposes the trade you are "
                "considering, either do not propose the trade, or state explicitly in plain_english_reasoning why "
                "this specific setup justifies going against that view. Never propose a trade that silently "
                "ignores an opposing forecast."
            ),
            "symbol": symbol,
            "market": market,
            "news": news,
            "account_equity": account.equity,
        }
        if context:
            prompt.update(context)
        payload = {
            "model": self.model,
            "input": json.dumps(prompt),
            "text": {"format": {"type": "json_object"}},
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=30) as response:
            raw = json.loads(response.read().decode("utf-8"))
        text = _extract_response_text(raw)
        return _proposal_from_response_text(text)


FORECAST_DIRECTIONS = ("bullish", "bearish", "neutral", "uncertain")


class MarketForecastAnalyzer:
    """Produces a real, CIO-style market forecast from genuine market evidence.

    Phase 3 of the CIO-level forecasting build (2026-08-20, Founder-directed). The
    Founder's own words on why this exists: the previous "forecast" simply averaged the
    AI's own past closed trades and projected that forward -- "that's not forecasting...
    forecasting is about planning, looking at market trends, looking at whether there is
    a bull run coming or not."

    CRITICAL, non-negotiable design constraint: this must NEVER see the AI's own trade
    P&L or win rate. Feeding a model its own past results and calling the output a market
    forecast is circular -- it would reinforce whatever pattern it already had on no new
    information, and the Founder explicitly accepted this risk framing when approving the
    build. Every input here traces back to real market data (price history, technical
    analysis, regime, macro/news evidence) or curated reference material. See
    forecasting.py::build_forecast_evidence for the assembly side and its accompanying
    anti-circularity regression test.
    """

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def forecast(self, *, scope: str, symbol: str | None, asset_type: str, evidence: dict[str, Any]) -> dict[str, Any] | None:
        prompt = {
            "role": "chief_investment_officer_market_forecast",
            "instruction": (
                "You are acting as a Chief Investment Officer briefing a founder on where a market is heading. "
                "Reason like a professional investor over the supplied evidence: multi-timeframe price trend, "
                "momentum, volatility, support/resistance structure, the detected market regime, and any macro or "
                "news context. Judge whether conditions favour continuation, reversal, or neither. "
                "Return only JSON with fields: direction, horizon_days, confidence, reasoning, supporting_evidence, "
                "contradictory_evidence, key_risks, invalidation. "
                f"direction must be one of {list(FORECAST_DIRECTIONS)}. "
                "confidence must be a decimal fraction between 0 and 1. "
                "horizon_days must be a positive integer. "
                "supporting_evidence, contradictory_evidence and key_risks must each be arrays of at most 3 short "
                "strings (one line each, no sub-clauses). "
                "invalidation must state, in one sentence, what would prove this view wrong. "
                "reasoning must be 2-4 sentences, no longer, and must cite the actual numbers you were given -- a "
                "reader must be able to check your claims against the evidence block. This is read by a busy "
                "founder, so be direct and concrete rather than exhaustive. Never invent a data point that is "
                "not present. "
                "If the evidence is too thin to support a real view, say so honestly: return direction 'uncertain' "
                "with low confidence and explain what is missing, rather than manufacturing a confident call. "
                "You are forecasting the MARKET, not grading any trading system's past performance -- no "
                "past-trade results are supplied and you must not speculate about any."
            ),
            "scope": scope,
            "symbol": symbol,
            "asset_type": asset_type,
            "evidence": evidence,
        }
        payload = {
            "model": self.model,
            "input": json.dumps(prompt, default=str),
            "text": {"format": {"type": "json_object"}},
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=45) as response:
            raw = json.loads(response.read().decode("utf-8"))
        return _forecast_from_response_text(_extract_response_text(raw))


class OpenAIReadOnlyExplainer:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def answer(self, question: str, context: dict[str, Any]) -> str:
        prompt = {
            "role": "read_only_ai_trader_explainer",
            "instruction": (
                "Answer the Founder's question in plain English using only the supplied AI Trader context. "
                "You are read-only. You must never place trades, approve trades, disable guardrails, enable auto trading, "
                "change broker settings, or claim that you performed any action. "
                "If the evidence is incomplete, say what is missing and what can be inferred. "
                "Be concise, practical, and clear for a non-technical founder."
            ),
            "question": question,
            "context": context,
        }
        payload = {
            "model": self.model,
            "input": json.dumps(prompt, default=str),
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=35) as response:
            raw = json.loads(response.read().decode("utf-8"))
        return _extract_response_text(raw).strip()


def _extract_response_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                chunks.append(str(content.get("text", "")))
    if chunks:
        return "".join(chunks)
    return str(response.get("output_text", ""))


def _forecast_from_response_text(text: str) -> dict[str, Any] | None:
    """Parse and sanity-check a forecast response. Returns None rather than a
    half-trusted dict when the model didn't produce a usable, in-range answer -- the
    caller records an honest "no forecast available" instead of a fabricated one."""
    if not text or text.strip() == "null":
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    direction = str(data.get("direction") or "").strip().lower()
    if direction not in FORECAST_DIRECTIONS:
        return None
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        return None
    if not 0.0 <= confidence <= 1.0:
        return None
    try:
        horizon_days = int(data.get("horizon_days"))
    except (TypeError, ValueError):
        return None
    if horizon_days <= 0:
        return None
    reasoning = str(data.get("reasoning") or "").strip()
    if not reasoning:
        return None
    return {
        "direction": direction,
        "horizon_days": horizon_days,
        "confidence": confidence,
        "reasoning": reasoning,
        "supporting_evidence": _string_list(data.get("supporting_evidence")),
        "contradictory_evidence": _string_list(data.get("contradictory_evidence")),
        "key_risks": _string_list(data.get("key_risks")),
        "invalidation": str(data.get("invalidation") or "").strip(),
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _proposal_from_response_text(text: str) -> TradeProposal | None:
    if not text or text.strip() == "null":
        return None
    data = json.loads(text)
    if data in (None, "null"):
        return None
    if not isinstance(data, dict) or not data.get("symbol"):
        return None
    return TradeProposal.from_dict(data)
