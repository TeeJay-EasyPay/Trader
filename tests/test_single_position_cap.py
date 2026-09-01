"""The position cap is enforced once, not twice.

2026-09-01, P1 of the "one home per decision" work, Founder-directed: "can you do P1, P2 and
P3 in one go one after the other?"

Two checks used to enforce the same decision against two different numbers:

    guardrails.py       len(open_positions) >= config.max_open_positions
                        -> "maximum_open_positions_exceeded"        (broker-blind)
    orchestrator.py     len(open_positions) >= position_cap_for(...)
                        -> "maximum_concurrent_positions_exceeded"  (per broker)

Measured against live refusals the day this was written: 34 hits on the first and 17 on the
second -- 51 of 77 refusals in total, all of them one rule counted twice. It is also exactly
why raising Alpaca's cap from 5 to 10 the previous day changed nothing: the per-broker value
said 10, the broker-blind one still said 5, and the broker-blind one runs first.

Now the orchestrator resolves the per-broker cap and hands it to the single check. These tests
exist so the second check cannot quietly grow back.
"""

from __future__ import annotations

import pathlib
import re

from ai_trader.guardrails import validate_trade_proposal
from ai_trader.models import AccountContext, GuardrailConfig, Position, TradeProposal

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "ai_trader"


def _proposal():
    return TradeProposal(
        symbol="AAPL", side="buy", entry_price=100.0, stop_loss=97.0, take_profit=106.0,
        position_size=1.0, risk_percentage=0.01, confidence_score=0.9,
        news_summary="", market_sentiment_summary="", technical_summary="",
        plain_english_reasoning="", asset_type="stock",
    )


def _account(n_positions: int):
    return AccountContext(
        equity=100_000.0,
        daily_realized_pnl=0.0,
        open_positions=[Position(symbol=f"SYM{i}", qty=1.0, market_value=100.0) for i in range(n_positions)],
        is_paper=True,
    )


def _config(shared_cap: int):
    return GuardrailConfig(max_open_positions=shared_cap)


def test_the_override_replaces_the_shared_cap():
    """Alpaca's 10 must actually be 10, not silently floored by a shared 5."""
    result = validate_trade_proposal(
        _proposal(), _account(7), _config(5), max_open_positions=10
    )
    assert "maximum_open_positions_exceeded" not in result.failures


def test_the_override_still_blocks_once_it_is_reached():
    result = validate_trade_proposal(
        _proposal(), _account(10), _config(5), max_open_positions=10
    )
    assert "maximum_open_positions_exceeded" in result.failures


def test_a_caller_that_passes_nothing_keeps_the_old_behaviour_exactly():
    """Opt-in, like ai_managed_symbols. agent.py, execution.py and sprint6.py all call this
    without broker context, and none of them may lose its cap as a side effect of P1."""
    blocked = validate_trade_proposal(_proposal(), _account(5), _config(5))
    allowed = validate_trade_proposal(_proposal(), _account(4), _config(5))
    assert "maximum_open_positions_exceeded" in blocked.failures
    assert "maximum_open_positions_exceeded" not in allowed.failures


def test_an_override_may_also_tighten():
    """Kraken keeps 5 while Alpaca has 10; the override is not a licence to widen only."""
    result = validate_trade_proposal(
        _proposal(), _account(5), _config(10), max_open_positions=5
    )
    assert "maximum_open_positions_exceeded" in result.failures


def test_the_second_gate_no_longer_exists_anywhere():
    """The whole point of P1. If this name comes back, so has the bug.

    Asserted against the source rather than behaviour because the failure mode is someone
    re-adding a well-meaning second check, which no behavioural test would notice -- it would
    simply refuse trades for a reason nobody is looking for.
    """
    offenders = []
    for path in SRC.rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # Comments may name the old gate -- the history is worth keeping. Only live code
            # counts as a reintroduction.
            if line.lstrip().startswith("#"):
                continue
            if "maximum_concurrent_positions_exceeded" in line:
                offenders.append(f"{path.name}:{n}")
    assert not offenders, f"the duplicate position-cap gate is back in: {offenders}"


def test_only_one_place_in_the_source_compares_open_positions_to_a_cap():
    """A stronger version of the above: count the comparisons, not the string.

    Someone could re-introduce the duplicate under a new name. This counts how many places
    compare a position count against a limit, and there must be exactly one.
    """
    pattern = re.compile(r"len\(\s*[\w.]*\.?open_positions\s*\)\s*>=")
    hits = []
    for path in SRC.rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.name}:{n}")
    assert len(hits) == 1, f"expected exactly one position-cap comparison, found: {hits}"
