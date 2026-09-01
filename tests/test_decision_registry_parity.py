"""The registry must answer exactly what the running code answers.

2026-09-01, P2 of the "one home per decision" work.

This is the safety mechanism for the whole project. The registry is built dormant -- nothing
reads from it yet -- and these tests drive it alongside the real resolution path
(load_trading_policy) to prove it produces identical values before it is given any power over
what the app trades.

Two useful outcomes, and both are wins:

  * everything matches, and the registry is proven correct while it is still harmless; or
  * something disagrees, and that is a settings bug found for free, before it could do harm.

It is a second speedometer, read against the first for a while before the old one comes out.

WHAT THIS DOES NOT PROVE. It proves the registry reproduces the resolution LOGIC. It cannot
reach production, so it says nothing about whether the live database holds the values anyone
expects -- that is checked separately by running resolve_all against the hosted deployment and
comparing with /admin/trading-policy. Both checks are needed; neither substitutes for the
other.
"""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

from ai_trader.decision_registry import (
    BROKER_POLICY,
    CODE_DEFAULT,
    DECISIONS,
    GUARDRAIL_ENV,
    INVESTMENT_POLICY,
    RISK_POLICY,
    resolve_all,
)
from ai_trader.foundation import initialize_foundation_schema, load_trading_policy
from ai_trader.models import AutoTradeConfig, GuardrailConfig


@pytest.fixture()
def db():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "policy.db"
        initialize_foundation_schema(path)
        yield path


GUARDRAILS = GuardrailConfig(
    max_risk_per_trade_pct=0.01,
    max_daily_loss_pct=0.03,
    max_open_positions=10,
    min_confidence_score=0.70,
)
AUTO_TRADE = AutoTradeConfig()


def _both(db_path, broker=None):
    policy = load_trading_policy(db_path, auto_trade=AUTO_TRADE, guardrails=GUARDRAILS)
    registry = resolve_all(db_path, guardrails=GUARDRAILS, auto_trade=AUTO_TRADE, broker=broker)
    return policy, registry


def test_every_decision_matches_the_running_code(db):
    """The core assertion. One row per decision, so a failure names the culprit."""
    policy, registry = _both(db)
    mismatches = []
    for d in DECISIONS:
        if not d.policy_attr:
            continue
        live = getattr(policy, d.policy_attr)
        mine = registry[d.name].value
        if isinstance(live, float) or isinstance(mine, float):
            same = abs(float(live) - float(mine)) < 1e-9
        else:
            same = live == mine
        if not same:
            mismatches.append(f"{d.name}: registry={mine!r} running_code={live!r} (via {registry[d.name].source})")
    assert not mismatches, "registry disagrees with the running code:\n  " + "\n  ".join(mismatches)


def test_the_registry_covers_the_decisions_that_gate_a_trade(db):
    """A registry that quietly omits the number causing trouble is worse than none."""
    _, registry = _both(db)
    for name in (
        "min_ai_confidence",
        "max_concurrent_positions",
        "min_stop_loss_pct",
        "min_reward_risk",
        "default_stop_loss_pct",
        "max_stop_loss_pct",
        "risk_per_trade_pct",
        "max_capital_allocation_pct",
    ):
        assert name in registry, f"{name} is not declared in the registry"


def test_confidence_now_comes_from_the_database(db):
    """2026-09-02, Founder-directed: "move the confidence bar to the database. it's not an
    environment variable."

    It used to be the one decision that ignored its own database row. The live row was set to
    0.70 -- the value already in MIN_CONFIDENCE_SCORE -- before the reader was switched, so
    moving the home could not move the bar. Render stays as a fallback.
    """
    _, registry = _both(db)
    assert registry["min_ai_confidence"].source == INVESTMENT_POLICY
    assert registry["min_ai_confidence"].value == 0.70


def test_render_still_answers_if_the_confidence_row_is_missing(db):
    """The fallback must survive, or a database without that row silently drops the bar to a
    built-in default rather than the number the Founder set in Render."""
    import sqlite3
    from contextlib import closing as _closing
    with _closing(sqlite3.connect(db)) as conn:
        with conn:
            conn.execute("DELETE FROM INVESTMENT_POLICIES WHERE policy_key = 'minimum_overall_confidence'")
    _, registry = _both(db)
    assert registry["min_ai_confidence"].source == GUARDRAIL_ENV
    assert registry["min_ai_confidence"].value == 0.70


def test_a_broker_override_wins_and_says_so(db):
    """Alpaca's position cap and stop floor, resolved for Alpaca specifically."""
    with closing(sqlite3.connect(db)) as conn:
        with conn:
            conn.execute(
                """UPDATE BROKER_POLICIES SET policy_value = '10'
                   WHERE broker = 'alpaca' AND policy_key = 'maximum_concurrent_positions'"""
            )
    _, registry = _both(db, broker="alpaca")
    cap = registry["max_concurrent_positions"]
    assert cap.value == 10
    assert cap.source == BROKER_POLICY
    assert cap.broker == "alpaca"


def test_a_broker_without_an_override_falls_through(db):
    """Kraken has no stop floor of its own, so it must land on the shared risk policy --
    never on Alpaca's."""
    _, registry = _both(db, broker="kraken")
    floor = registry["min_stop_loss_pct"]
    assert floor.source in (RISK_POLICY, CODE_DEFAULT)
    assert floor.value < 0.015, "Kraken must not inherit the equities floor"


def test_every_value_can_say_where_it_came_from(db):
    """The whole point. A number that cannot be traced is a number nobody can check."""
    _, registry = _both(db)
    for name, resolved in registry.items():
        assert resolved.source, f"{name} resolved without a source"
        assert resolved.provenance, f"{name} has no plain-English provenance"


def test_no_decision_is_declared_twice():
    names = [d.name for d in DECISIONS]
    assert len(names) == len(set(names)), "a decision is declared more than once"


def test_every_decision_has_a_plain_english_summary():
    """These are shown to the Founder, who is not an engineer. A field name is not a summary."""
    for d in DECISIONS:
        assert d.summary and d.summary[0].isupper() and d.summary.endswith("."), d.name
        assert "_" not in d.summary, f"{d.name} summary reads like a variable name"


def test_every_chain_ends_in_a_default():
    """Resolution must always terminate with an answer, never fall off the end."""
    for d in DECISIONS:
        assert d.precedence[-1] == CODE_DEFAULT, f"{d.name} has no final fallback"
