"""Every input that feeds a trading decision, and whether it is actually wired.

2026-09-04, Founder-directed, after the fourth inert-feature discovery in a week:
"how are we making such basic mistakes here? ... these misses should not be happening."

The answer is specific, and it is not "concentrate harder". proposal_context builds
four blocks of evidence for the AI reviewer, and when a source is empty it writes a
polite sentence into the prompt:

    "No matching curated reference material for this asset type/sector."
    "No prior backtest on record for this symbol/strategy."

Those sentences are indistinguishable from genuine findings. The model reads them as
"there is nothing relevant for this coin" -- a reasonable reading, and completely
wrong. STRATEGY_BACKTEST_RESULTS holds zero rows and the knowledge-base tables do not
exist, so both sentences are true of every symbol, forever. A missing pipe and a real
absence produce identical text, and neither the model nor anyone reading the reasoning
can tell them apart.

Every enrichment path in this codebase shares that design -- 136 exception handlers,
each deliberately "additive; its failure must never block a proposal". That is the
right call for availability and the wrong one for truth: the app currently has no way
to say "I am running blind."

This module is the missing half. It declares each decision input once, next to the
table behind it, so that:

  (a) an empty source is REPORTED rather than absorbed, and
  (b) the prompt can distinguish "nothing for this symbol" from "this input has never
      been wired", which are different facts and must never read alike.

Declaring them here rather than checking ad hoc is the same principle as
decision_registry: one home per fact. A new decision input that is not added to this
list will not be watched, which is why the test suite asserts that every table
proposal_context reads from appears below.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .database import connect


# Sources that carry EVIDENCE into a decision. Deliberately not every table in the
# schema -- only the ones whose emptiness would silently weaken a trade decision
# while the app carried on looking healthy.
@dataclass(frozen=True)
class DecisionInput:
    name: str
    table: str
    feeds: str
    # "required" -- a decision made without this is materially worse and we want to
    # know immediately. "enrichment" -- genuinely optional, but its absence must
    # still be stated honestly in the prompt rather than dressed up as a finding.
    kind: str
    # Not every evidence source is a table. The curated reference library is
    # knowledge/*.md on disk, and checking it against a database table -- which is
    # what the first draft of this module did -- would have reported a working
    # library as missing, turning a truthfulness fix into a new false alarm. The
    # source of truth has to be checked where it actually lives.
    source: str = "table"


DECISION_INPUTS: tuple[DecisionInput, ...] = (
    DecisionInput(
        name="backtest_evidence",
        table="STRATEGY_BACKTEST_RESULTS",
        feeds="AI reviewer prompt (crypto and equity) -- prior performance of this strategy",
        kind="required",
    ),
    DecisionInput(
        name="reference_material",
        table="knowledge/*.md",
        feeds="AI reviewer prompt -- curated public trading literature",
        kind="required",
        source="knowledge_files",
    ),
    DecisionInput(
        name="crypto_news",
        table="CRYPTO_NEWS",
        feeds="AI reviewer prompt -- recent headlines for the symbol",
        kind="enrichment",
    ),
    DecisionInput(
        name="news_catalysts",
        table="NEWS_CATALYST_EVIDENCE",
        feeds="AI reviewer prompt -- market commentary tied to a catalyst",
        kind="enrichment",
    ),
    DecisionInput(
        name="market_regime",
        table="MARKET_REGIME_EVIDENCE",
        feeds="AI reviewer prompt -- the current global regime read",
        kind="enrichment",
    ),
    DecisionInput(
        name="market_observations",
        table="MARKET_DATA_OBSERVATIONS",
        feeds="post-trade learning payloads -- the candles inside a holding window",
        kind="required",
    ),
    DecisionInput(
        name="trade_outcomes",
        table="TRADE_R_MULTIPLES",
        feeds="expectancy, and the outcome feedback the AI learns from",
        kind="required",
    ),
)


@dataclass(frozen=True)
class InputStatus:
    name: str
    table: str
    feeds: str
    kind: str
    rows: int          # -1 when the table does not exist at all
    wired: bool

    # A file-backed source counted in "rows" reads as a database table that is fine, which
    # is the wrong mental model for anyone later asking why it is empty -- they would go
    # looking for a table that does not exist. Name the unit the source actually has.
    unit: str = "rows"

    @property
    def headline(self) -> str:
        if self.rows < 0:
            return f"{self.name}: NOT WIRED - {self.table} does not exist"
        if self.rows == 0:
            return f"{self.name}: NOT WIRED - {self.table} is empty"
        return f"{self.name}: ok ({self.rows} {self.unit})"


def _row_count(db_path: Path, table: str) -> int:
    """Rows in `table`, or -1 if it does not exist.

    Indexes the row explicitly rather than unpacking: production is Postgres and
    tests are SQLite, and the two disagree about row shape often enough that
    tuple-unpacking here would be a bug the test suite could never catch.
    """
    try:
        with closing(connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608 - name is from the frozen list above, never user input
    except Exception:  # noqa: BLE001 - a missing table is the answer here, not an error
        return -1
    if row is None:
        return -1
    return int(row[0])


def _knowledge_file_count() -> int:
    """Curated markdown files the retrieval layer can actually see.

    Deliberately asks knowledge_base for its own directory rather than recomputing
    the path here: KNOWLEDGE_DIR is resolved relative to the installed package and
    is overridable by AI_TRADER_KNOWLEDGE_DIR, so a second copy of that logic would
    drift and report on a directory the app never reads.
    """
    try:
        from .knowledge_base import KNOWLEDGE_DIR

        return len(list(KNOWLEDGE_DIR.glob("*.md")))
    except Exception:  # noqa: BLE001 - an unreadable library is the answer, not an error
        return -1


def check_decision_inputs(db_path: Path) -> list[InputStatus]:
    """Every declared input, with whether it actually carries data."""
    statuses = []
    for declared in DECISION_INPUTS:
        if declared.source == "knowledge_files":
            rows = _knowledge_file_count()
        else:
            rows = _row_count(db_path, declared.table)
        statuses.append(
            InputStatus(
                name=declared.name,
                table=declared.table,
                feeds=declared.feeds,
                kind=declared.kind,
                rows=rows,
                wired=rows > 0,
                unit="files" if declared.source == "knowledge_files" else "rows",
            )
        )
    return statuses


def unwired_inputs(db_path: Path) -> list[InputStatus]:
    """The ones feeding nothing. Empty list is the healthy answer."""
    return [status for status in check_decision_inputs(db_path) if not status.wired]


def is_wired(db_path: Path, name: str) -> bool:
    """Whether one named input carries any data at all.

    Used by the prompt serializers to tell "nothing for THIS symbol" apart from
    "this source has never held anything", which is the distinction that made the
    empty backtest table invisible for weeks.
    """
    for declared in DECISION_INPUTS:
        if declared.name == name:
            if declared.source == "knowledge_files":
                return _knowledge_file_count() > 0
            return _row_count(db_path, declared.table) > 0
    return False


def startup_report(db_path: Path) -> str:
    """A single block for the worker log at boot.

    Deliberately loud and deliberately unconditional: printed whether or not
    anything is wrong, so that a silent log means the check itself stopped running
    rather than everything being fine.
    """
    statuses = check_decision_inputs(db_path)
    missing = [s for s in statuses if not s.wired]
    lines = ["[decision-inputs] evidence sources feeding trade decisions:"]
    for status in statuses:
        lines.append(f"[decision-inputs]   {status.headline}")
    if missing:
        required = [s.name for s in missing if s.kind == "required"]
        lines.append(
            f"[decision-inputs] RUNNING BLIND on {len(missing)} source(s)"
            + (f"; {len(required)} of them required: {', '.join(required)}" if required else "")
        )
    else:
        lines.append("[decision-inputs] all declared sources carry data")
    return "\n".join(lines)
