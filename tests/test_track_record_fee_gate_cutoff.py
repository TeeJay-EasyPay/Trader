"""The app must not be punished for losses made under rules that no longer exist.

2026-09-03, Founder-directed: "do the first item please."

WHY CRYPTO HAD STOPPED TRADING ENTIRELY. Research ran every cycle and ideas were generated --
40 to 88 coins scored, several through the confidence bar, FIL top at 0.82 -- and every
proposal was refused with confidence_below_minimum. The cause was symbol_track_record: a coin
that has lost money loses up to MAX_CONFIDENCE_PENALTY (0.25) of confidence, so a coin scoring
0.72 reached the 0.70 bar on 0.47. ADA was 0 from 2, LINK 0 from 3, SOL 0 from 6 -- the full
penalty each.

Those losses were the FEE problem, not bad selection. The trades aimed at moves smaller than
the 1.54% round trip, so they lost whether the call was right or wrong. That defect is fixed,
but the penalty kept charging for it, and could never clear: the penalty only lifts when a coin
wins, and a coin cannot win if it is never traded. A doom loop with no exit.

TWO THINGS ALMOST MADE THIS FIX A FAKE ONE, and both have a test below.

  1. THE DATE. The obvious cutoff was 2026-08-20, when the fee gate shipped. Wrong: the gate
     measures the fee rate from settled trades and defaults to INACTIVE when it cannot measure
     one. The first trade with a recorded fee settled 2026-08-31, so nothing could have been
     refused on fees before then. The losing ADA/LINK/SOL trades are dated 23-24 August -- a
     20 August cutoff would have kept every one of them and changed nothing at all.

  2. THE TIMESTAMP FORMAT. 26 of the 66 rows in PERFORMANCE_ATTRIBUTION store an epoch integer
     ("1787586949") instead of an ISO date, and "1787586949" sorts BEFORE "2026-08-31" because
     "1" < "2". A plain SQL >= would have silently dropped most of the recent trades. The
     change would have appeared to work while measuring something else.
"""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_trader.symbol_track_record import (
    FEE_GATE_EFFECTIVE_FROM,
    MAX_CONFIDENCE_PENALTY,
    _at_or_after,
    symbol_track_record,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS PERFORMANCE_ATTRIBUTION (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT, profit_loss REAL, closed_at TEXT, created_at TEXT
);
"""

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
BEFORE_GATE = "2026-08-24T10:00:00+00:00"   # the real ADA/LINK loss dates
AFTER_GATE = "2026-09-02T10:00:00+00:00"
EPOCH_AFTER_GATE = "1788566400"              # 2026-09-05, stored the way 26 real rows are
EPOCH_BEFORE_GATE = "1787586949"             # 2026-08-24 -- a real value from production


def _db(rows):
    tmp = tempfile.mkdtemp()
    path = Path(tmp) / "attr.db"
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.executescript(SCHEMA)
            for symbol, pnl, when in rows:
                conn.execute(
                    "INSERT INTO PERFORMANCE_ATTRIBUTION (symbol, profit_loss, closed_at, created_at)"
                    " VALUES (?,?,?,?)", (symbol, pnl, when, when))
    return path


def test_losses_from_before_the_fee_gate_no_longer_penalise():
    """The exact situation: ADA, 0 from 2, both losses on 24 August."""
    db = _db([("ADA", -0.40, BEFORE_GATE), ("ADA", -0.37, BEFORE_GATE)])
    record = symbol_track_record(db, "ADA", now=NOW)
    assert record.confidence_penalty == 0.0, (
        "trades made before the fee rule started working must not drive the penalty"
    )


def test_losses_after_the_fee_gate_still_penalise():
    """The rule must keep working. Losing under the CURRENT rules is real information."""
    db = _db([("ADA", -0.40, AFTER_GATE), ("ADA", -0.37, AFTER_GATE),
              ("ADA", -0.20, AFTER_GATE), ("ADA", -0.10, AFTER_GATE)])
    record = symbol_track_record(db, "ADA", now=NOW)
    assert record.confidence_penalty > 0.0
    assert record.confidence_penalty <= MAX_CONFIDENCE_PENALTY


def test_the_cutoff_is_when_the_rule_started_working_not_when_it_shipped():
    """The fee gate shipped 2026-08-20 but could not measure a fee rate until trades settled
    with fees recorded, which first happened 2026-08-31. Using the ship date would have kept
    every one of the 23-24 August losses and fixed nothing."""
    assert FEE_GATE_EFFECTIVE_FROM.startswith("2026-08-31")
    assert _at_or_after("2026-08-24T10:00:00+00:00", FEE_GATE_EFFECTIVE_FROM) is False
    assert _at_or_after("2026-09-01T10:00:00+00:00", FEE_GATE_EFFECTIVE_FROM) is True


def test_epoch_timestamps_are_compared_as_dates_not_as_text():
    """The trap. "1788000000" < "2026-08-31" as text, so a string comparison would drop it --
    and 26 of 66 real rows are stored exactly like that."""
    assert "1788566400" < "2026-08-31"          # what a naive text comparison sees
    assert _at_or_after("1788566400", FEE_GATE_EFFECTIVE_FROM) is True   # what is actually true
    # And the reverse must hold too, or the guard would just wave everything through.
    assert _at_or_after(EPOCH_BEFORE_GATE, FEE_GATE_EFFECTIVE_FROM) is False


def test_an_epoch_stamped_recent_loss_still_counts():
    """End to end for the trap above: if these were dropped, a coin losing badly right now
    would look spotless."""
    db = _db([("LINK", -0.30, EPOCH_AFTER_GATE), ("LINK", -0.25, EPOCH_AFTER_GATE),
              ("LINK", -0.20, EPOCH_AFTER_GATE), ("LINK", -0.15, EPOCH_AFTER_GATE)])
    assert symbol_track_record(db, "LINK", now=NOW).confidence_penalty > 0.0


def test_an_epoch_stamped_old_loss_is_excluded():
    db = _db([("SOL", -0.30, EPOCH_BEFORE_GATE), ("SOL", -0.25, EPOCH_BEFORE_GATE)])  # 24 Aug
    assert symbol_track_record(db, "SOL", now=NOW).confidence_penalty == 0.0


def test_the_rolling_window_still_applies_when_it_is_the_tighter_limit():
    """The cutoff is the LATER of the two. Far in the future, the 45-day window is stricter and
    must still bound the sample -- otherwise this fix quietly removes the lookback."""
    db = _db([("ETH", -0.50, AFTER_GATE)])
    far_future = datetime(2027, 6, 1, tzinfo=timezone.utc)
    assert symbol_track_record(db, "ETH", now=far_future).trades == 0


def test_a_coin_with_no_qualifying_trades_is_not_treated_as_bad():
    """No evidence is not evidence of failure. This is what unblocks the doom loop: a coin with
    nothing to judge gets a clean slate rather than a penalty."""
    db = _db([("DOT", -0.40, BEFORE_GATE)])
    record = symbol_track_record(db, "DOT", now=NOW)
    assert record.confidence_penalty == 0.0
    assert record.trades == 0


def test_unparseable_timestamps_are_excluded_rather_than_assumed_recent():
    """Erring towards excluding is right here: wrongly including an old loss re-creates the
    doom loop, while wrongly excluding one only costs a little caution."""
    assert _at_or_after("not a date", FEE_GATE_EFFECTIVE_FROM) is False
    assert _at_or_after(None, FEE_GATE_EFFECTIVE_FROM) is False
    assert _at_or_after("", FEE_GATE_EFFECTIVE_FROM) is False


def test_naive_timestamps_are_treated_as_utc_not_rejected():
    """Some rows have no timezone. Rejecting them would silently shrink the sample."""
    assert _at_or_after("2026-09-02T10:00:00", FEE_GATE_EFFECTIVE_FROM) is True
    assert _at_or_after("2026-08-24T10:00:00", FEE_GATE_EFFECTIVE_FROM) is False
