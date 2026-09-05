from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.error import HTTPError
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


class CryptoTradeReviewer:
    """A real qualitative review of an already-deterministically-approved crypto candidate.

    Phase 5 of the CIO-level forecasting build (2026-08-20, Founder-directed). Crypto
    trade generation has never had an LLM step at all -- propose_crypto_trades is pure
    scoring arithmetic. The Founder asked for genuine judgment here, matching what
    equities already get.

    Deliberately a REVIEW, not a proposal: price, size, stop-loss and take-profit stay
    deterministic risk-management math and are never authored by a model. This step can
    only (a) veto a candidate, or (b) lower its confidence -- never raise it, never widen
    risk. That asymmetry is the point: real-money sizing must not depend on model output,
    but a model spotting a reason not to trade is genuinely valuable.
    """

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def review(self, *, symbol: str, candidate: dict[str, Any], context: dict[str, str] | None = None) -> dict[str, Any] | None:
        prompt = {
            "role": "crypto_trade_reviewer",
            "instruction": (
                "You are reviewing a crypto trade candidate that has already passed this system's mechanical "
                "screens (due-diligence score, trend, 24h-range position, BTC regime, re-entry cooldown). "
                "Your job is judgment, not arithmetic: decide whether this is genuinely worth taking right now. "
                "Return only JSON with fields: proceed, confidence, reasoning, concerns, "
                "strategy_fit, better_suited_strategy. "
                "proceed must be true or false. confidence must be a decimal fraction between 0 and 1 and must "
                "NOT exceed the supplied candidate confidence -- you may lower it, never raise it. "
                "reasoning must be 2-4 sentences in plain English a non-technical founder can follow, citing the "
                "actual evidence supplied. concerns must be an array of at most 3 short strings. "
                "Set proceed=false when the evidence genuinely does not support entering now -- a thin or "
                "contradictory case is a real reason to pass, and passing costs nothing. "
                # Phase 5, 2026-09-05, Founder-directed. Until now this reviewer saw one
                # already-chosen strategy and could only accept or refuse the trade. It now
                # receives strategy_evidence: how every candidate strategy has actually
                # performed ON THIS COIN and overall. That distinction is the point -- the same
                # strategy measured -0.15R on BCH and -1.77R on XRP, so a per-strategy average
                # is the wrong basis for a per-coin decision.
                "strategy_evidence shows how each candidate strategy has performed on THIS coin and "
                "overall, separating this system's own closed trades (real_money) from simulated "
                "outcomes of candidates it recorded but did not take (shadow_simulation). Weigh the "
                "record on this specific coin above the general one: the same strategy can work on one "
                "coin and fail badly on another, and a thin sample is an anecdote, not a finding. "
                "strategy_fit must be one of 'good', 'poor' or 'unproven', judging whether the strategy "
                "actually assigned to this candidate suits this coin on that evidence. "
                "better_suited_strategy must be the id of a listed strategy you judge a better fit, or "
                "null when none is clearly better -- naming one does not change this trade's stop or "
                "target, it is recorded so selection can improve. Do NOT prefer a strategy merely "
                "because it has no losing record; absent evidence is not good evidence. "
                "You are NOT setting the entry price, position size, stop-loss or take-profit; those are fixed by "
                "risk management and are shown only as context."
            ),
            "symbol": symbol,
            "candidate": candidate,
        }
        if context:
            prompt.update(context)
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
        with urlopen(request, timeout=25) as response:
            raw = json.loads(response.read().decode("utf-8"))
        return _review_from_response_text(_extract_response_text(raw))


BENCHMARK_CONFIDENCE_LABELS = ("High", "Medium", "Low")


class BenchmarkResearchAnalyzer:
    """Produces genuine, web-grounded research on what a specific real benchmark trader
    has publicly done or said recently.

    Founder-directed 2026-08-21. Replaces the static, one-time-seeded
    BENCHMARK_DAILY_RESEARCH content (frozen at whatever date benchmark.py's seed list
    was written with) that was silently blocking every Alpaca due-diligence assessment --
    foundation.py's _behavioural_context_available() only reports "completed" when a row
    exists dated exactly today, and nothing in this codebase ever wrote one before this.

    CRITICAL, non-negotiable design constraint: this must use the Responses API's real
    web_search_preview tool and report ONLY what search results actually surface. There
    is no other live data source in this codebase for "what did a specific real investor
    do today" -- inventing plausible-sounding content without grounding it in a real
    search would be fabrication, which every other AI feature in this project explicitly
    refuses to do (forecasting.py's anti-circularity check; this module's other analyzers
    all return None rather than a half-trusted answer). When nothing concrete turns up,
    this returns an honest "no notable public activity found" result -- never invented
    detail dressed up as a finding.
    """

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def research(self, *, trader_name: str, platform: str, strategy_style: str) -> dict[str, Any] | None:
        prompt = {
            "role": "benchmark_trader_researcher",
            "instruction": (
                "Use web search to find real, recent, publicly available information about this specific "
                "investor's activity in roughly the last 30 days -- portfolio changes, 13F filings, public "
                "statements, or interviews. Report only what your search actually finds; never invent a trade, "
                "holding, or quote that is not backed by a real source you found. "
                "Respond with ONLY a single raw JSON object and nothing else -- no markdown code fences, no "
                "prose before or after it, no explanation of your search process. "
                "The JSON object must have exactly these fields: found_activity, observed_trade_or_portfolio_change, "
                "ai_interpretation, risk_lesson, market_lesson, related_sector, related_theme, confidence, "
                "source_urls. "
                "found_activity must be true or false -- set it false when nothing concrete turned up, and in "
                "that case observed_trade_or_portfolio_change must honestly say so rather than being padded with "
                "generic filler dressed up as a finding. "
                "observed_trade_or_portfolio_change must describe only what a real source reports, naming that "
                "source's general nature (e.g. '13F filing', 'public interview') without fabricating a quote. "
                "ai_interpretation, risk_lesson and market_lesson are your own analysis of what this system "
                "should learn from that real activity -- one sentence each, and honestly thin (e.g. 'no fresh "
                "lesson without new activity') when found_activity is false. "
                f"confidence must be one of {list(BENCHMARK_CONFIDENCE_LABELS)}, reflecting how directly your "
                "search results support what you reported, not how interesting the story is. "
                "source_urls must be an array of the real URLs your search actually returned, or an empty array."
            ),
            "trader_name": trader_name,
            "platform": platform,
            "strategy_style": strategy_style,
        }
        payload = {
            "model": self.model,
            "input": json.dumps(prompt, default=str),
            # The web_search_preview tool and structured JSON mode (text.format) are
            # mutually exclusive on this API -- live-confirmed 2026-08-21 ("Web Search
            # cannot be used with JSON mode", HTTP 400). Every other analyzer in this file
            # uses text.format because none of them need a live tool; this one trades that
            # guarantee for real web grounding and relies on the instruction above plus
            # _benchmark_research_from_response_text's tolerant parsing instead. An
            # unparseable response still fails safely (returns None, caller records
            # nothing for that trader today) rather than half-trusting free text.
            "tools": [{"type": "web_search_preview"}],
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
        try:
            with urlopen(request, timeout=60) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # 2026-08-21 live-verification finding: this is the first analyzer in this
            # codebase to use a hosted tool (web_search_preview) -- the other analyzers'
            # plain "HTTP Error 400: Bad Request" (no body) was never enough to diagnose a
            # tool/model-compatibility rejection, only enough to know something failed.
            # Surfacing OpenAI's real error body here, not changing the other analyzers,
            # since this is the one where a bare status code was actually insufficient.
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{exc}: {detail}") from exc
        return _benchmark_research_from_response_text(_extract_response_text(raw))


class OpenAIReadOnlyExplainer:
    # 2026-08-24: the caller passes what's left of its own wall-clock budget. Render's
    # proxy hangs up at 60s, so an OpenAI call that outlives the budget doesn't produce
    # a late answer -- it produces no answer at all, and the Founder sees "timed out".
    # Failing fast here lets the caller return the deterministic evidence answer instead.
    DEFAULT_TIMEOUT_SECONDS = 35.0

    def __init__(self, api_key: str, model: str, timeout_seconds: float | None = None):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = float(timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS)

    def answer(self, question: str, context: dict[str, Any], history: list[dict[str, Any]] | None = None) -> str:
        prompt = {
            "role": "read_only_ai_trader_explainer",
            "instruction": (
                # 2026-09-04, Founder-directed: "I want to be able to talk to the app like I'm
                # talking to you or I'm talking to chat GPT where it's an actual conversation.
                # Otherwise, if it's just gonna read basic data for me, what is the whole point
                # of it?"
                #
                # The previous instruction said "be concise, practical, and clear" and handed
                # over the whole context as JSON. That produced exactly what he objected to:
                # headings, bullet lists, and a recital of every available number. Concise was
                # never the problem -- the problem was that it read like a report rather than
                # a reply.
                "You are AI Trader, talking with the Founder about his own trading account. Have a "
                "CONVERSATION with him, do not file a report. "
                "Answer the actual question in your first sentence, before any detail. If he asks "
                "whether he is up, say whether he is up. "
                "Write in flowing prose, the way you would say it out loud. Do not use headings, "
                "bullet points, numbered lists or bold labels unless he asks for a list or is "
                "genuinely comparing several things. "
                "Give him the one or two figures that matter and what they mean, not every number "
                "you can see -- he can ask for more, and he will. "
                "Never open with what you are or what you cannot do. Only mention that you are "
                "read-only if he actually asks you to place, approve or change something. "
                "Do not restate his question back to him, and do not end with a summary of what "
                "you just said. "
                "If something in the evidence is surprising, contradictory or worth his attention, "
                "say so unprompted -- that judgement is the reason he is asking you rather than "
                "reading the numbers himself. "
                "It is fine to be brief. A one-line answer to a one-line question is the right "
                "length, and better than padding it out. "
                # The substantive rules below are unchanged: they are what keeps the answer TRUE.
                "You are read-only. You must never place trades, approve trades, disable guardrails, enable auto trading, "
                "change broker settings, or claim that you performed any action. "
                "If the evidence is incomplete, say what is missing and what can be inferred. "
                # 2026-08-24: asked how XRP might do, this answered that it had no view --
                # while a 14-day XRP forecast with full reasoning sat unread in the context.
                # The context is not only the trade history, and a question about a coin's
                # outlook is answerable from the research even when nothing has been traded.
                "market_forecasts, crypto_research_scores and recent_crypto_news are the system's own "
                "research, and are evidence in exactly the same way trades are. When asked how a coin "
                "may perform, use them: give the forecast direction, its confidence and horizon, the "
                "reasoning behind it, and what would invalidate it. Say plainly that a forecast is the "
                "system's estimate rather than a certainty, and give the honest answer when the "
                "confidence is low or the signals disagree -- but do not claim to have no view when a "
                "forecast for that symbol is present. "
                # 2026-08-24, Founder-directed: every other signal here is published free to
                # everyone. This one is not, and it is the one most worth saying out loud.
                # 2026-08-25: see the currencies block in the context.
                "Every figure in this context is either pounds or dollars depending on which broker it "
                "belongs to: Kraken is GBP (£), Alpaca is USD ($). Always state the correct symbol, never "
                "default to $, and never add a Kraken figure to an Alpaca one or convert between them -- "
                "they are two separate accounts. "
                "own_track_record_by_coin is what this system's own money actually did on each coin, "
                "at its own fees. When a coin is discussed, say what that record is -- including when "
                "it is bad, and especially when it contradicts a positive technical signal. A losing "
                "record on a handful of trades is weak evidence, not proof, so give the trade count "
                "alongside it rather than treating a small sample as settled."
            ),
            "question": question,
            # 2026-09-04: the previous turns, so this is a conversation rather than a series of
            # interrogations. Without them "what about crypto?" arrived with nothing to say what
            # "what about" referred to, and every question had to be self-contained.
            "conversation_so_far": history or [],
            "context": context,
        }
        if history:
            prompt["instruction"] += (
                "conversation_so_far is what the two of you have already said, oldest first. Use it: "
                "resolve 'it', 'that', 'the other one' and 'why?' against what was actually said, and "
                "do not re-explain something you have just told him. If a follow-up is ambiguous, "
                "make the most reasonable reading and answer it rather than asking him to rephrase."
            )
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
        with urlopen(request, timeout=self.timeout_seconds) as response:
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


def _review_from_response_text(text: str) -> dict[str, Any] | None:
    """Parse a crypto trade review. Returns None when the response isn't usable -- the
    caller then keeps the existing deterministic proposal unchanged rather than acting on
    a half-understood answer."""
    if not text or text.strip() == "null":
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "proceed" not in data:
        return None
    reasoning = str(data.get("reasoning") or "").strip()
    if not reasoning:
        return None
    confidence: float | None
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None and not 0.0 <= confidence <= 1.0:
        confidence = None
    # Phase 5, 2026-09-05. Both fields are optional on purpose: a model that omits them still
    # produces a usable review, so this cannot become a new way for a trade to be lost. The
    # strategy judgement is recorded and used to improve selection -- it never alters this
    # trade's price, size, stop or target, which stay deterministic risk management.
    strategy_fit = str(data.get("strategy_fit") or "").strip().lower()
    if strategy_fit not in {"good", "poor", "unproven"}:
        strategy_fit = None
    better = data.get("better_suited_strategy")
    better_suited = str(better).strip() if isinstance(better, str) and better.strip() else None
    return {
        "proceed": bool(data.get("proceed")),
        "confidence": confidence,
        "reasoning": reasoning,
        "concerns": _string_list(data.get("concerns")),
        "strategy_fit": strategy_fit,
        "better_suited_strategy": better_suited,
    }


def _lenient_json_object(text: str) -> dict[str, Any] | None:
    """Parses a JSON object out of a response that was NOT produced under structured
    JSON mode (BenchmarkResearchAnalyzer cannot use text.format alongside web_search_preview
    -- see that class's docstring). Models asked for "only JSON" still sometimes wrap it in
    a markdown code fence or add a stray sentence before/after it; this strips a fence if
    present, then falls back to the outermost {...} substring if the text still isn't
    directly parseable. Returns None rather than guessing at a fragment when no valid JSON
    object can be recovered -- the caller then honestly records nothing for this trader
    today instead of trusting a mangled parse.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped).strip()
    try:
        data = json.loads(stripped)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _benchmark_research_from_response_text(text: str) -> dict[str, Any] | None:
    """Parse a benchmark-research response. Returns None when the response isn't usable
    -- the caller then records nothing for this trader today rather than a half-understood
    or fabricated-looking answer.

    Deliberately does NOT require found_activity=True or a real source URL to accept the
    result: an honest "nothing found" is a valid, usable answer here (that's the entire
    point of asking the model to say so rather than invent something), so this only
    rejects responses that are structurally unusable, not ones that are honestly empty.
    """
    if not text or text.strip() == "null":
        return None
    data = _lenient_json_object(text)
    if data is None:
        return None
    confidence = str(data.get("confidence") or "").strip().title()
    if confidence not in BENCHMARK_CONFIDENCE_LABELS:
        return None
    found_activity = bool(data.get("found_activity"))
    observed = str(data.get("observed_trade_or_portfolio_change") or "").strip()
    if not observed:
        return None
    return {
        "found_activity": found_activity,
        "observed_trade_or_portfolio_change": observed,
        "ai_interpretation": str(data.get("ai_interpretation") or "").strip() or None,
        "risk_lesson": str(data.get("risk_lesson") or "").strip() or None,
        "market_lesson": str(data.get("market_lesson") or "").strip() or None,
        "related_sector": str(data.get("related_sector") or "").strip() or None,
        "related_theme": str(data.get("related_theme") or "").strip() or None,
        "confidence": confidence,
        "source_urls": _string_list(data.get("source_urls")),
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


# 2026-08-25, Founder-directed: a microphone button on Ask AI Trader, "so I don't need to type
# stuff, I can just press it and ask the app something verbally".
#
# Transcription happens here rather than on the phone deliberately. On-device speech recognition
# would mean a second native dependency and a second permission prompt, and would still differ
# between Android and iOS; the recording itself is the only thing that genuinely has to happen on
# the device. This keeps the phone's job to "record audio, send bytes" and leaves the words to the
# same OpenAI account the rest of the app already uses.
MAX_TRANSCRIPTION_BYTES = 20 * 1024 * 1024


# Speech happens here rather than on the phone for the same reason transcription does, plus
# one specific to this app: expo-speech would be a THIRD native module and therefore a new
# build the Founder has to install by hand. expo-av is already in the shipped binary and can
# play audio as well as record it, so generating the speech server-side means the whole voice
# loop ships as an over-the-air update like every other change.
#
# 2026-08-31, Founder-directed: "can it have a speaking function as well so that when I speak
# to it it responds back to me with text and speech".
MAX_SPEECH_CHARACTERS = 4000


class OpenAISpeaker:
    """Text to speech for one answer. Never raises for a bad request."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini-tts", voice: str = "alloy",
                 timeout_seconds: float = 30.0):
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.timeout_seconds = float(timeout_seconds)

    def speak(self, text: str) -> bytes:
        """MP3 bytes for the given text, or b"" if there is nothing worth speaking.

        Truncates rather than refusing: a long answer read aloud is still useful, and
        failing the whole request because an answer ran long would make the voice reply
        unreliable exactly when the app had most to say.
        """
        cleaned = str(text or "").strip()
        if not cleaned:
            return b""
        if len(cleaned) > MAX_SPEECH_CHARACTERS:
            cleaned = cleaned[:MAX_SPEECH_CHARACTERS].rsplit(" ", 1)[0] + "..."
        request = Request(
            "https://api.openai.com/v1/audio/speech",
            data=json.dumps({
                "model": self.model,
                "voice": self.voice,
                "input": cleaned,
                "response_format": "mp3",
            }).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read()


class OpenAITranscriber:
    """Speech to text for one recorded question. Never raises for a bad recording."""

    def __init__(self, api_key: str, model: str = "whisper-1", timeout_seconds: float = 45.0):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = float(timeout_seconds)

    def transcribe(self, audio: bytes, *, filename: str = "question.m4a") -> str:
        if not audio:
            return ""
        # multipart/form-data by hand: this codebase deliberately has no HTTP client
        # dependency, and one endpoint does not justify adding one.
        boundary = "----aitrader" + hashlib.sha256(audio[:64] + filename.encode()).hexdigest()[:24]
        parts: list[bytes] = []
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{self.model}\r\n".encode())
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n".encode()
        )
        parts.append(audio)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        body = b"".join(parts)
        request = Request(
            "https://api.openai.com/v1/audio/transcriptions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload.get("text") or "").strip()
