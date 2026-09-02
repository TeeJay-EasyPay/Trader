"""A refusal must be able to explain itself in numbers.

2026-09-02, P6 of the "one home per decision" work.

Until now a blocked trade recorded only that a rule fired -- "maximum_open_positions_exceeded"
-- and nothing about what the value actually was or what it needed to be. Answering the
Founder's plainest question, "why isn't it trading?", therefore meant reading the code to find
which number the gate used, then querying production by hand to find out what that number
currently was. That happened twice in one week and cost most of a session each time.

Every numeric gate now records {"actual": x, "limit": y} alongside the failure, so the record
answers the question by itself: "9 open, limit 9" rather than a gate name.

Deliberately NOT recorded for non-numeric gates (market_closed, asset_unavailable,
invalid_side). There is no measurement to report, and inventing one would make the evidence
less trustworthy, not more.
"""

from __future__ import annotations

from ai_trader.guardrails import validate_trade_proposal
from ai_trader.models import AccountContext, GuardrailConfig, Position, TradeProposal


def _proposal(confidence=0.9):
    return TradeProposal(
        symbol="AAPL", side="buy", entry_price=100.0, stop_loss=97.0, take_profit=106.0,
        position_size=1.0, risk_percentage=0.01, confidence_score=confidence,
        news_summary="", market_sentiment_summary="", technical_summary="",
        plain_english_reasoning="", asset_type="stock",
    )


def _account(n=0, daily_pnl=0.0):
    return AccountContext(
        equity=100_000.0, daily_realized_pnl=daily_pnl, is_paper=True,
        open_positions=[Position(symbol=f"S{i}", qty=1.0, market_value=100.0) for i in range(n)],
    )


def test_a_position_cap_refusal_says_how_many_and_the_limit():
    result = validate_trade_proposal(_proposal(), _account(n=9), GuardrailConfig(), max_open_positions=9)
    assert "maximum_open_positions_exceeded" in result.failures
    assert result.evidence["maximum_open_positions_exceeded"] == {"actual": 9, "limit": 9}


def test_a_confidence_refusal_says_the_score_and_the_bar():
    result = validate_trade_proposal(
        _proposal(confidence=0.62), _account(), GuardrailConfig(), min_confidence_score=0.70
    )
    assert result.evidence["confidence_below_minimum"] == {"actual": 0.62, "limit": 0.7}


def test_a_daily_loss_refusal_says_the_loss_and_the_limit():
    account = _account(daily_pnl=-4000.0)
    result = validate_trade_proposal(_proposal(), account, GuardrailConfig(max_daily_loss_pct=0.03))
    assert "maximum_daily_loss_exceeded" in result.failures
    ev = result.evidence["maximum_daily_loss_exceeded"]
    assert ev["actual"] == -4000.0 and ev["limit"] == -3000.0


def test_a_passing_trade_records_no_evidence():
    """Evidence explains refusals. A clean pass should not carry a pile of numbers nobody
    asked for -- that would bury the useful ones when something does fail."""
    result = validate_trade_proposal(_proposal(), _account(n=1), GuardrailConfig(max_open_positions=5))
    assert "maximum_open_positions_exceeded" not in result.evidence


def test_every_gate_with_evidence_reports_both_sides():
    """An 'actual' without a 'limit' is half an answer and invites the same digging again."""
    result = validate_trade_proposal(
        _proposal(confidence=0.10), _account(n=9, daily_pnl=-9000.0),
        GuardrailConfig(max_daily_loss_pct=0.03), max_open_positions=9, min_confidence_score=0.70,
    )
    assert len(result.evidence) >= 3
    for gate, measured in result.evidence.items():
        assert "actual" in measured and "limit" in measured, f"{gate} recorded {measured}"


def test_evidence_survives_serialisation():
    """It is stored as JSON in the decision record, so it must round-trip."""
    import json

    result = validate_trade_proposal(_proposal(), _account(n=9), GuardrailConfig(), max_open_positions=9)
    restored = json.loads(json.dumps(result.to_dict()))
    assert restored["evidence"]["maximum_open_positions_exceeded"]["limit"] == 9


def test_the_field_is_optional_so_existing_callers_are_unaffected():
    """Several modules construct ValidationResult directly. None of them should need editing."""
    from ai_trader.models import ValidationResult

    assert ValidationResult(passed=True).evidence == {}
