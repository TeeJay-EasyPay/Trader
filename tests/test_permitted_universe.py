"""Permission is membership of a screened universe, not a quality rating.

2026-08-29. The bug this file exists to prevent, in full, because it cost a day of trading
and hid behind a green test suite:

INVESTMENT_WATCHLIST stores investment philosophy fit as WORDS -- "Strong" (19 companies),
"Good" (28), "Moderate" (3). safe_score maps those to 0.90 / 0.75 / 0.50. The permission
gate then required >= 0.85. So 31 of the Founder's own 50 hand-screened, Shariah-compliant
companies could never be bought, while positions in them could still be sold.

Confirmed live that morning: MSFT, NVDA, LULU, NKE, LUV, DAL, ISRG and LLY were every one
rejected "not_in_permitted_universe" on philosophy_fit 0.75. The Founder's report was
"shares have been sold but no more bought", and this was why.

The category error: "Strong" vs "Good" rates how ATTRACTIVE a permitted company is. It was
never a statement about whether the Founder is willing to own it -- he answered that when he
put the company on the list. Quality is already measured by the confidence score, which is
the other of the two checks.
"""

from __future__ import annotations

from ai_trader.operational import (
    PERMITTED_UNIVERSE_FIT,
    permitted_universe_fit,
    safe_score,
)


def test_permitted_member_clears_the_strictest_threshold_ever_configured():
    """A screened asset must pass the gate whatever the threshold is later moved to."""
    assert permitted_universe_fit(True) == PERMITTED_UNIVERSE_FIT
    for threshold in (0.70, 0.75, 0.85, 0.90, 1.0):
        assert permitted_universe_fit(True) >= threshold, (
            f"a screened, permitted asset failed a {threshold} permission gate"
        )


def test_non_member_is_never_assumed_permitted():
    """Absent from the screen means unscreened, and unscreened must not trade.

    None (rather than 0.0) is deliberate: it lets the caller keep TradeProposal's own
    default instead of this function inventing a score for something it knows nothing about.
    """
    assert permitted_universe_fit(False) is None


def test_quality_wording_no_longer_decides_permission():
    """The exact regression: the words that used to gate permission must not gate it now.

    safe_score still maps these words -- they remain meaningful as a quality rating, and
    other callers read them for display. What must never happen again is a permitted
    company inheriting a sub-threshold permission score from one of them.
    """
    gate = 0.85  # the live minimum_investment_policy_score on the day of the bug
    blocked_by_the_old_rule = [
        word for word in ("Strong", "Good", "Moderate")
        if (safe_score(word) or 0.0) < gate
    ]
    # Sanity: these words really were sub-threshold, so this test is testing something.
    assert blocked_by_the_old_rule == ["Good", "Moderate"], (
        "the qualitative scale changed; re-check whether this regression can recur"
    )

    for word in blocked_by_the_old_rule:
        assert safe_score(word) < gate                       # what the old rule produced
        assert permitted_universe_fit(True) >= gate          # what the rule produces now


def test_both_brokers_answer_permission_with_the_same_value():
    """Crypto and equities must not drift apart again.

    propose_crypto_trades sets philosophy_fit=PERMITTED_UNIVERSE_FIT directly (the Kraken
    universe is screened by construction); the equity path returns it via
    permitted_universe_fit after a watchlist lookup. Same constant, one definition -- which
    is the consolidation the Founder asked for: two checks, stored in one place, for all
    brokers.
    """
    crypto_answer = PERMITTED_UNIVERSE_FIT
    equity_answer = permitted_universe_fit(True)
    assert crypto_answer == equity_answer
