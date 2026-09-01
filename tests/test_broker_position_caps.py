"""One position cap per broker, not one shared across all of them.

2026-09-01, Founder-directed: "what can we do to increase the number of trades that can be
done on alpaca."

The cap was a single number sized for Kraken -- where a position is 25-50 pounds against a
500 allocation. Applied unchanged to Alpaca it meant 5 positions of ~2,500 dollars on a
101,000 dollar account, so the broker that is actually trading sat full with 93,000 dollars
idle while 76 ideas were refused in one night on maximum_open_positions_exceeded.

The app's own learning data says those are the most expensive refusals it makes: 19 of them,
and the price moved +3.24% on average afterwards.
"""

from __future__ import annotations

from ai_trader.foundation import position_cap_for


class _Policy:
    def __init__(self, shared, caps):
        self.max_concurrent_positions = shared
        self.broker_position_caps = caps


def test_each_broker_gets_its_own_cap():
    policy = _Policy(5, {"alpaca": 12, "kraken": 5})
    assert position_cap_for(policy, "alpaca") == 12
    assert position_cap_for(policy, "kraken") == 5


def test_a_broker_without_its_own_cap_keeps_the_shared_one():
    """Adding a broker must never silently grant it more room than intended. It has to be
    given a cap on purpose."""
    policy = _Policy(5, {"alpaca": 12})
    assert position_cap_for(policy, "binance") == 5
    assert position_cap_for(policy, None) == 5


def test_broker_names_are_matched_case_insensitively():
    policy = _Policy(5, {"alpaca": 12})
    assert position_cap_for(policy, "Alpaca") == 12
    assert position_cap_for(policy, "ALPACA") == 12


def test_no_overrides_at_all_behaves_exactly_as_before():
    """The pre-2026-09-01 behaviour, so an existing deployment changes nothing until it is
    given per-broker values."""
    policy = _Policy(3, {})
    for broker in ("alpaca", "kraken", "anything"):
        assert position_cap_for(policy, broker) == 3


def test_kraken_is_not_loosened_by_this_change():
    """Kraken is real money on a small allocation, where 5 positions is already half the
    sleeve at full size. Only the paper equities account gets more room."""
    from ai_trader.foundation import DEFAULT_BROKER_POLICIES

    assert DEFAULT_BROKER_POLICIES["kraken"]["maximum_concurrent_positions"][0] == 5
    assert DEFAULT_BROKER_POLICIES["alpaca"]["maximum_concurrent_positions"][0] > 5


def test_the_alpaca_cap_stays_inside_the_capital_allocation_guardrail():
    """More positions must not mean more capital at risk than the Founder allowed.

    12 positions at the ~2,500 dollars Alpaca actually uses is ~30,000 against a 101,000
    dollar account -- under the 25% maximum_capital_allocation_pct that governs how much may
    be at work at once. The allocation check still runs independently; this only stops the
    position COUNT being the thing that blocks a trade the allocation would have allowed.
    """
    from ai_trader.foundation import DEFAULT_BROKER_POLICIES, DEFAULT_RISK_POLICIES

    cap = DEFAULT_BROKER_POLICIES["alpaca"]["maximum_concurrent_positions"][0]
    allocation_pct = DEFAULT_RISK_POLICIES["maximum_capital_allocation_pct"][0]
    account, position = 101_000.0, 2_500.0
    assert (cap * position) / account <= allocation_pct + 1e-9, (
        f"{cap} positions of {position} on {account} exceeds the {allocation_pct:.0%} allocation cap"
    )


def test_the_shared_env_ceiling_is_not_below_any_per_broker_cap():
    """The per-broker cap is unreachable if the broker-blind guardrail sits below it.

    2026-09-01. This is the bug this test exists for, and it shipped: the per-broker caps
    above were added and were completely INERT, because guardrails.py runs first and knows
    nothing about brokers --

        if len(account.open_positions) >= config.max_open_positions:
            failures.append("maximum_open_positions_exceeded")

    -- and orchestrator.py calls validate_trade_proposal BEFORE consulting position_cap_for.
    So Alpaca was refused at MAX_OPEN_POSITIONS (5) and the 10 was never reached. Everything
    looked shipped; nothing had changed.

    MAX_OPEN_POSITIONS is therefore a CEILING, not the cap: it must be at least the largest
    per-broker cap, or that broker silently loses the room it was given. Raising it does not
    loosen any broker that has its own lower number -- Kraken keeps 5 both here and through
    its independent KRAKEN_MAX_OPEN_TRADES dry-run gate.
    """
    import re
    from pathlib import Path

    from ai_trader.foundation import DEFAULT_BROKER_POLICIES

    blueprint = Path(__file__).resolve().parents[1] / "render.yaml"
    values = re.findall(
        r"- key: MAX_OPEN_POSITIONS\b.*?^\s*value: \"(\d+)\"",
        blueprint.read_text(encoding="utf-8"),
        re.DOTALL | re.MULTILINE,
    )
    assert values, "MAX_OPEN_POSITIONS is no longer declared in render.yaml"

    broker_caps = {
        broker: policies["maximum_concurrent_positions"][0]
        for broker, policies in DEFAULT_BROKER_POLICIES.items()
        if "maximum_concurrent_positions" in policies
    }
    largest = max(broker_caps.values())
    for ceiling in (int(v) for v in values):
        assert ceiling >= largest, (
            f"MAX_OPEN_POSITIONS={ceiling} sits below the largest per-broker cap "
            f"({broker_caps}); that broker's cap is unreachable and the change is inert"
        )
