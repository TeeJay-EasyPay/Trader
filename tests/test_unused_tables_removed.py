"""Ten tables that were declared, never written and never read.

2026-09-02, Founder-directed after reviewing the inventory: delete them, keep two ideas.

Every one held zero rows in production, verified immediately before removal. They were not
storage; they were names to guess between when looking for where a number lives — which is the
same problem the "one home per decision" work spent two days removing, in a different costume.

THE NEAR MISS THIS FILE EXISTS FOR. `CRYPTO_SENTIMENT` was on the list and is empty.
`CRYPTO_SENTIMENT_SCORES` holds 1,220 rows and does real work. The names differ by one word,
and a careless pattern match would have dropped the wrong one. That is asserted below, because
it is the mistake most likely to be repeated by whoever tidies next.

The two ideas worth keeping are written up in governance/DEFERRED_IDEAS.md, with the Founder's
own reasoning for the on-chain one. An empty table preserves nothing; a note does.
"""

from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "ai_trader"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOVED = [
    "CRYPTO_BENCHMARK_ALIGNMENT",
    "CRYPTO_DAILY_UPDATES",
    "CRYPTO_ONCHAIN_METRICS",
    "CRYPTO_PROJECT_ANALYSIS",
    "CRYPTO_RISK",
    "CRYPTO_SENTIMENT",
    "CRYPTO_TOKENOMICS",
    "CRYPTO_TRADING_HISTORY",
    "PORTFOLIO_CORRELATION_WARNINGS",
    "PORTFOLIO_STRESS_TESTS",
]

# Empty, and doing real work respectively. One word apart.
KEPT_BECAUSE_IT_HAS_DATA = "CRYPTO_SENTIMENT_SCORES"


def _all_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in SRC.rglob("*.py"))


def test_none_of_them_is_created_any_more():
    """If a CREATE comes back, the table returns on the next deploy and the tidy-up is undone."""
    source = _all_source()
    still_there = [
        name for name in REMOVED
        if re.search(rf"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?{name}\s*\(", source)
    ]
    assert not still_there, f"these were removed and have been re-declared: {still_there}"


def test_nothing_reads_or_writes_them():
    """A stray query against a dropped table is a 500 in production, not a quiet no-op."""
    source = _all_source()
    offenders = []
    for name in REMOVED:
        for verb in ("FROM", "INTO", "JOIN", "UPDATE"):
            if re.search(rf"\b{verb}\s+{name}\b", source, re.I):
                offenders.append(f"{verb} {name}")
    assert not offenders, f"code still queries removed tables: {offenders}"


def test_the_sentiment_table_that_holds_data_survived():
    """The near miss. One word apart from a table on the deletion list, and holding 1,220 rows
    of real sentiment scores. Dropping it would have silently blinded crypto research."""
    source = _all_source()
    assert re.search(rf"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?{KEPT_BECAUSE_IT_HAS_DATA}\s*\(", source), (
        f"{KEPT_BECAUSE_IT_HAS_DATA} must still be created -- it holds real data"
    )


def test_the_removed_names_are_not_prefixes_of_something_still_in_use():
    """Guards the general form of the near miss, not just the one instance.

    If a removed name is a prefix of a surviving table, any future cleanup that matches on
    prefix rather than exact name repeats the mistake.
    """
    source = _all_source()
    created = set(re.findall(r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?([A-Z_][A-Z_0-9]*)\s*\(", source))
    collisions = [
        f"{removed} is a prefix of {surviving}"
        for removed in REMOVED
        for surviving in created
        if surviving != removed and surviving.startswith(removed)
    ]
    # This is expected to be non-empty (CRYPTO_SENTIMENT / CRYPTO_SENTIMENT_SCORES). The point
    # is that the survivor is still created, which the test above asserts. Recorded here so the
    # hazard is visible rather than implicit.
    for collision in collisions:
        assert KEPT_BECAUSE_IT_HAS_DATA in collision, f"unexamined prefix collision: {collision}"


def test_the_two_kept_ideas_are_written_down():
    """The whole justification for deleting rather than keeping empty schema. If the note is
    gone, the ideas are gone, and the deletion becomes a loss instead of a tidy-up."""
    notes = ROOT / "governance" / "DEFERRED_IDEAS.md"
    assert notes.exists(), "governance/DEFERRED_IDEAS.md is missing"
    text = notes.read_text(encoding="utf-8")
    assert "exchange" in text.lower() and "netflow" in text.lower(), (
        "the on-chain note must capture the exchange-flow reasoning, which is the actual idea"
    )
    assert "correlation" in text.lower()
    for name in REMOVED:
        assert name in text, f"{name} was deleted without a recorded reason"
