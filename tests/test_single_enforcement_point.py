"""Five rules that ran twice now run once — and two of them were wrong.

2026-09-02, P5 of the "one home per decision" work, Founder-directed: "please now complete p5
through to p9."

I expected duplication. Two of the five were latent bugs, dormant only because of the values
currently set, and both would have surfaced at the worst possible moment.

  1. PAPER TRADING. orchestrator.py read `if not policy.paper_trading_only: fail`. That fires
     when live trading is ALLOWED -- backwards. It is quiet today only because
     PAPER_TRADING_ONLY is true. The first time the Founder set it false to trade live for
     real, every single trade would have been refused, and the reason shown would have been
     "paper_trading_only_failed", which reads like the opposite of the problem.

  2. SHORT SELLING. orchestrator.py refused EVERY sell when short selling is off, including
     closing a position we already hold. The app could open a trade and then be blocked from
     exiting it. guardrails.py has the correct test -- short selling means selling something
     NOT held -- and that is the one that survived.

  3. TAKE PROFIT. orchestrator.py was the only place honouring policy.take_profit_required
     while guardrails.py demanded a target unconditionally, so the policy flag was decorative:
     turning it off changed nothing. guardrails.py now takes the flag.

  4. CONFIDENCE. Same rule, two sources -- the Render variable here, the policy value there.
     One check now, fed the registry-resolved number.

  5. STOP LOSS. Genuinely identical. Deleted without ceremony.

These tests pin the survivor's behaviour, so a well-meaning second copy cannot come back.
"""

from __future__ import annotations

import pathlib
import re

from ai_trader.guardrails import validate_trade_proposal
from ai_trader.models import AccountContext, GuardrailConfig, Position, TradeProposal

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "ai_trader"
ORCHESTRATOR = SRC / "orchestrator.py"


def _proposal(side="buy", entry=100.0, stop=97.0, target=106.0, confidence=0.9, asset_type="stock"):
    if side == "sell":
        stop, target = 103.0, 94.0
    return TradeProposal(
        symbol="AAPL", side=side, entry_price=entry, stop_loss=stop, take_profit=target,
        position_size=1.0, risk_percentage=0.01, confidence_score=confidence,
        news_summary="", market_sentiment_summary="", technical_summary="",
        plain_english_reasoning="", asset_type=asset_type,
    )


def _account(symbols=(), is_paper=True):
    return AccountContext(
        equity=100_000.0, daily_realized_pnl=0.0, is_paper=is_paper,
        open_positions=[Position(symbol=s, qty=1.0, market_value=100.0) for s in symbols],
    )


def _code_lines(path):
    """Source with comments stripped -- the notes above name every removed check."""
    return [re.sub(r"#.*$", "", line) for line in path.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------
# The five must not be checked in the orchestrator any more.
# --------------------------------------------------------------------------
def test_the_orchestrator_no_longer_duplicates_any_of_the_five():
    lines = _code_lines(ORCHESTRATOR)
    for gate in (
        "paper_trading_only_failed",
        "short_selling_disabled",
        "confidence_below_minimum",
        "stop_loss_mandatory",
        "take_profit_mandatory",
    ):
        offenders = [n for n, line in enumerate(lines, 1) if f'"{gate}"' in line]
        assert not offenders, f"{gate} is being checked in orchestrator.py again at {offenders}"


# --------------------------------------------------------------------------
# 1. Paper trading: the inverted test must not come back.
# --------------------------------------------------------------------------
def test_paper_only_does_not_block_a_paper_account():
    result = validate_trade_proposal(_proposal(), _account(is_paper=True), GuardrailConfig(paper_trading_only=True))
    assert "paper_trading_only_failed" not in result.failures


def test_paper_only_blocks_a_live_account():
    """The check exists for this case and only this case."""
    result = validate_trade_proposal(_proposal(), _account(is_paper=False), GuardrailConfig(paper_trading_only=True))
    assert "paper_trading_only_failed" in result.failures


def test_turning_paper_only_off_does_not_block_everything():
    """The bug that was removed. `if not paper_trading_only: fail` would refuse every trade
    the moment the Founder went live -- exactly when it must not."""
    result = validate_trade_proposal(_proposal(), _account(is_paper=False), GuardrailConfig(paper_trading_only=False))
    assert "paper_trading_only_failed" not in result.failures


# --------------------------------------------------------------------------
# 2. Short selling: closing a held position is not a short.
# --------------------------------------------------------------------------
def test_selling_something_we_hold_is_allowed_with_shorting_off():
    """The other removed bug: the app could open a trade and then be unable to exit it."""
    result = validate_trade_proposal(
        _proposal(side="sell"), _account(symbols=["AAPL"]), GuardrailConfig(allow_short_selling=False)
    )
    assert "short_selling_disabled" not in result.failures


def test_selling_something_we_do_not_hold_is_still_refused():
    result = validate_trade_proposal(
        _proposal(side="sell"), _account(symbols=["MSFT"]), GuardrailConfig(allow_short_selling=False)
    )
    assert "short_selling_disabled" in result.failures


# --------------------------------------------------------------------------
# 3. Take profit: the policy flag must actually do something.
# --------------------------------------------------------------------------
def test_the_take_profit_flag_is_no_longer_decorative():
    no_target = _proposal(target=0.0)
    required = validate_trade_proposal(no_target, _account(), GuardrailConfig(), take_profit_required=True)
    optional = validate_trade_proposal(no_target, _account(), GuardrailConfig(), take_profit_required=False)
    assert "take_profit_mandatory" in required.failures
    assert "take_profit_mandatory" not in optional.failures


def test_a_caller_without_the_flag_still_requires_a_target():
    """Opt-in, like every other override. agent.py and execution.py pass nothing."""
    result = validate_trade_proposal(_proposal(target=0.0), _account(), GuardrailConfig())
    assert "take_profit_mandatory" in result.failures


# --------------------------------------------------------------------------
# 4. Confidence: one check, fed the policy number.
# --------------------------------------------------------------------------
def test_the_passed_confidence_bar_beats_the_render_value():
    config = GuardrailConfig(min_confidence_score=0.60)
    result = validate_trade_proposal(_proposal(confidence=0.65), _account(), config, min_confidence_score=0.70)
    assert "confidence_below_minimum" in result.failures


def test_a_caller_without_a_bar_keeps_the_render_value():
    config = GuardrailConfig(min_confidence_score=0.60)
    result = validate_trade_proposal(_proposal(confidence=0.65), _account(), config)
    assert "confidence_below_minimum" not in result.failures


# --------------------------------------------------------------------------
# The general guarantee.
# --------------------------------------------------------------------------
def test_no_rule_is_enforced_in_both_files():
    """The standing protection. Any gate name appearing in both is a duplicate by definition."""
    orch = {m for line in _code_lines(ORCHESTRATOR)
            for m in re.findall(r'failures\.append\("([a-z_0-9]+)"\)', line)}
    guard = {m for line in _code_lines(SRC / "guardrails.py")
             for m in re.findall(r'failures\.append\("([a-z_0-9]+)"\)', line)}
    assert not (orch & guard), f"these rules are enforced twice: {sorted(orch & guard)}"
