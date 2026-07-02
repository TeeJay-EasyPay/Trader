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

    def propose(self, symbol: str, market: dict[str, Any], news: dict[str, Any], account: AccountContext) -> TradeProposal | None:
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
                "Only propose a trade when the setup is clear and conservative."
            ),
            "symbol": symbol,
            "market": market,
            "news": news,
            "account_equity": account.equity,
        }
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
        if not text or text.strip() == "null":
            return None
        data = json.loads(text)
        if data in (None, "null"):
            return None
        return TradeProposal.from_dict(data)


def _extract_response_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                chunks.append(str(content.get("text", "")))
    if chunks:
        return "".join(chunks)
    return str(response.get("output_text", ""))
