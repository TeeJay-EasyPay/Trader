"""One question must not consume the whole minute's OpenAI allowance.

2026-09-04, Founder-reported: "it gives me an answer which is just taken from the tables. It's
not giving me an answer like, say, you would give me... if it's just gonna read basic data for
me, what is the whole point of it?"

He was right, and the cause was not the model or the prompt. THE MODEL NEVER RAN. Every request
came back 429, so Ask fell back to its hardcoded evidence summary -- and reported "Answered
using gpt-4.1" while doing it, so a failure was displayed as a success.

Measured against the account:

    x-ratelimit-limit-tokens: 30000     per minute
    one Ask question:         ~25,400   tokens

A single question consumed 85% of the minute. A second question, or a scheduled research call
landing in the same window, was refused.

WHY A BUDGET RATHER THAN MORE LIMITS. This was trimmed once already, on 2026-08-24, from 102KB
to about half -- and it crept straight back as the research sections were added. Per-section
limits only constrain the sections someone thought of. A budget enforced after the context is
built constrains every future addition too, including ones nobody has written yet.
"""

from __future__ import annotations

import json

from ai_trader.api import (
    _ASK_CONTEXT_TOKEN_BUDGET,
    _ASK_RECOMMENDATION_FIELDS,
    _estimated_tokens,
    enforce_context_budget,
)


def _big_context(sections: int = 6, rows: int = 120) -> dict:
    return {
        f"section_{n}": [
            {"symbol": f"SYM{i}", "reasoning": "x" * 400, "created_at": "2026-09-04T00:00:00Z"}
            for i in range(rows)
        ]
        for n in range(sections)
    }


def test_an_oversized_context_is_brought_under_budget():
    context = _big_context()
    assert _estimated_tokens(context) > _ASK_CONTEXT_TOKEN_BUDGET
    assert _estimated_tokens(enforce_context_budget(context)) <= _ASK_CONTEXT_TOKEN_BUDGET


def test_a_context_already_within_budget_is_untouched():
    """Trimming what already fits would lose evidence for nothing."""
    small = {"trades": [{"symbol": "BTC", "pnl": 1.2}], "note": "all fine"}
    assert enforce_context_budget(small) == small


def test_the_budget_leaves_room_for_more_than_one_question_a_minute():
    """25,400 of a 30,000 allowance is what caused this. The budget has to leave room for
    several questions AND the scheduled research calls that share the same allowance."""
    assert _ASK_CONTEXT_TOKEN_BUDGET * 3 <= 30_000


def test_nothing_is_removed_entirely_only_shortened():
    """A section that disappears reads to the model as "there is none" -- which is exactly how
    Ask came to invent a week of stopped research from an empty list. Every key survives."""
    context = _big_context()
    trimmed = enforce_context_budget(context)
    for key in context:
        assert key in trimmed, f"{key} vanished instead of being shortened"


def test_a_shortened_section_says_so():
    """So the model can tell "this is the recent part" from "this is all there is"."""
    trimmed = enforce_context_budget(_big_context())
    notes = [k for k in trimmed if k.endswith("_note")]
    assert notes, "a trimmed list must carry a note explaining it was shortened"
    assert "omitted for length" in trimmed[notes[0]]


def test_the_biggest_section_is_trimmed_first():
    """The problem is always one or two sections that grew, not uniform bloat. On 2026-09-04 a
    single global market_regime string was repeated inside all ten recommendations."""
    context = {
        "huge": [{"text": "y" * 500} for _ in range(200)],
        "small": [{"text": "kept"}],
    }
    trimmed = enforce_context_budget(context)
    assert len(trimmed["small"]) == 1, "the small section should survive intact"
    assert len(trimmed["huge"]) < 200


def test_the_market_regime_is_no_longer_repeated_inside_every_recommendation():
    """It is a GLOBAL fact and was 770 characters inside each of ten recommendations -- 7,700
    characters of the same sentence, nearly a third of the whole recommendations block."""
    assert "market_regime" not in _ASK_RECOMMENDATION_FIELDS


def test_it_terminates_even_on_something_it_cannot_shrink():
    """A context of irreducible scalars must not loop forever on every question."""
    stubborn = {f"k{n}": n for n in range(5000)}
    enforce_context_budget(stubborn)


def test_a_bad_value_does_not_break_the_answer():
    """A size estimate failing must never cost the Founder his reply."""

    class Unserialisable:
        def __repr__(self):
            raise RuntimeError("no")

    assert _estimated_tokens({"bad": Unserialisable()}) >= 0
    enforce_context_budget({"bad": Unserialisable(), "fine": "ok"})


def test_the_trimmed_context_is_still_valid_json():
    """It is serialised into the prompt. A trim that produced something unserialisable would
    fail the request in a way that looks exactly like the rate limit being fixed here."""
    trimmed = enforce_context_budget(_big_context())
    json.loads(json.dumps(trimmed, default=str))
