"""An empty evidence source must never read as a finding.

2026-09-04, Founder-directed: "we knew that we had created a library of publicly
available material that the AI is supposed to use, but for some reason, it's not wired
in. We knew that they were supposed to be backtest evidence, but for some reason, it's
not wired in... these misses should not be happening."

He is right, and the reason they kept happening is mechanical rather than careless.
proposal_context degrades silently by design -- every enrichment source is wrapped so
its failure can never block a proposal -- and the sentence it substitutes when a source
is empty is written in the vocabulary of a finding:

    "No prior backtest on record for this symbol/strategy."

STRATEGY_BACKTEST_RESULTS has held zero rows since it was created. So that sentence was
emitted for every symbol on every cycle, and read -- by the model, and by anyone
auditing the reasoning -- as a fact about the coin rather than a missing pipe.

These tests pin the distinction. They are deliberately about WORDING as much as
plumbing, because the wording is what made this invisible for weeks.
"""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from ai_trader.database import connect
from ai_trader.decision_inputs import (
    DECISION_INPUTS,
    check_decision_inputs,
    is_wired,
    startup_report,
    unwired_inputs,
)
from ai_trader.proposal_context import _serialize_backtest, _serialize_knowledge


def _db_with(table: str | None, rows: int = 0) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "inputs.db"
    with closing(connect(tmp)) as conn:
        if table:
            conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
            for _ in range(rows):
                conn.execute(f"INSERT INTO {table} DEFAULT VALUES")
        conn.commit()
    return tmp


# --------------------------------------------------------------------------
# 1. The wording distinction -- the actual bug
# --------------------------------------------------------------------------
def test_an_unwired_backtest_source_does_not_read_as_a_finding():
    """The exact defect: a table that has never held a row, described as though the
    symbol had been looked up and found wanting."""
    text = _serialize_backtest(None, source_wired=False)
    assert "UNAVAILABLE" in text
    assert "says nothing about this trade" in text
    assert "No prior backtest on record" not in text


def test_a_genuinely_absent_backtest_still_reads_as_a_finding():
    """The other half. Once backtests exist, "none for this symbol" IS informative and
    must not be downgraded to a plumbing warning."""
    text = _serialize_backtest(None, source_wired=True)
    assert "No prior backtest on record" in text
    assert "UNAVAILABLE" not in text


def test_an_unwired_knowledge_base_says_nothing_was_searched():
    text = _serialize_knowledge([], source_wired=False)
    assert "not populated" in text
    assert "nothing was searched" in text
    assert "not a finding" in text


def test_the_model_is_told_not_to_treat_a_missing_input_as_negative():
    """Without this the model does the reasonable thing with "no backtest evidence" --
    it lowers confidence. A missing pipe would then quietly suppress good trades, which
    is the same shape as the track-record doom loop."""
    assert "Do not treat it as a negative signal" in _serialize_backtest(None, source_wired=False)


def test_real_backtest_content_is_unaffected_by_the_wiring_flag():
    backtest = {"created_at": "2026-09-01", "trades": 40, "win_rate": 0.55,
                "expectancy_r": 0.3, "profit_factor": 1.4, "max_drawdown_r": 2.0,
                "result_summary": "steady"}
    for wired in (True, False):
        text = _serialize_backtest(backtest, source_wired=wired)
        assert "win_rate=0.55" in text
        assert "UNAVAILABLE" not in text


# --------------------------------------------------------------------------
# 2. The check itself
# --------------------------------------------------------------------------
def test_a_missing_table_counts_as_unwired_rather_than_raising():
    """The knowledge-base tables do not exist in production at all. A checker that
    threw on that would have been switched off, which is how this stays broken."""
    db = _db_with(None)
    assert is_wired(db, "backtest_evidence") is False
    assert any(s.rows == -1 for s in check_decision_inputs(db))


def test_an_empty_table_is_unwired_and_a_populated_one_is_not():
    empty = _db_with("STRATEGY_BACKTEST_RESULTS", rows=0)
    assert is_wired(empty, "backtest_evidence") is False

    filled = _db_with("STRATEGY_BACKTEST_RESULTS", rows=3)
    assert is_wired(filled, "backtest_evidence") is True


def test_an_unknown_input_name_is_never_reported_as_wired():
    assert is_wired(_db_with(None), "no_such_input") is False


def test_the_knowledge_library_is_checked_where_it_actually_lives():
    """The first draft of this module checked reference material against a database
    table. The library is knowledge/*.md on disk and is genuinely populated, so that
    check would have reported a WORKING input as missing -- a truthfulness fix that
    introduced a new false alarm. Checking the real source is the whole point.
    """
    db = _db_with(None)  # no tables at all
    assert is_wired(db, "reference_material") is True, "the curated library is real; do not report it missing"


def test_the_knowledge_library_is_not_empty():
    """If the curated files ever stop shipping with the deploy, the AI silently loses
    its only source of trading literature. Better to fail here than to find out from
    a prompt that says nothing was searched."""
    from ai_trader.knowledge_base import KNOWLEDGE_DIR

    assert list(KNOWLEDGE_DIR.glob("*.md")), f"no curated knowledge files under {KNOWLEDGE_DIR}"


def test_unwired_inputs_names_what_is_blind():
    db = _db_with("CRYPTO_NEWS", rows=5)
    blind = {status.name for status in unwired_inputs(db)}
    assert "backtest_evidence" in blind
    assert "crypto_news" not in blind


# --------------------------------------------------------------------------
# 3. The startup report -- so this is discovered at boot, not weeks later
# --------------------------------------------------------------------------
def test_the_startup_report_says_running_blind_in_plain_words():
    report = startup_report(_db_with(None))
    assert "RUNNING BLIND" in report
    assert "required" in report


def test_the_startup_report_prints_even_when_everything_is_healthy():
    """A check that only speaks up on failure is indistinguishable from a check that
    has stopped running. That ambiguity is what this whole module exists to remove."""
    tmp = Path(tempfile.mkdtemp()) / "all.db"
    with closing(connect(tmp)) as conn:
        for declared in DECISION_INPUTS:
            if declared.source != "table":
                continue  # the knowledge library is files on disk and is really present
            conn.execute(f"CREATE TABLE {declared.table} (id INTEGER PRIMARY KEY)")
            conn.execute(f"INSERT INTO {declared.table} DEFAULT VALUES")
        conn.commit()
    report = startup_report(tmp)
    assert "all declared sources carry data" in report
    assert "RUNNING BLIND" not in report


def test_every_declared_input_names_what_it_feeds():
    """A source listed without a consequence is one nobody will prioritise fixing."""
    for declared in DECISION_INPUTS:
        assert declared.feeds.strip(), declared.name
        assert declared.kind in {"required", "enrichment"}


def test_the_two_known_gaps_are_declared():
    """The two the Founder named. If either is ever removed from the list, the check
    stops watching the thing it was built for."""
    names = {declared.name for declared in DECISION_INPUTS}
    assert {"backtest_evidence", "reference_material"} <= names
