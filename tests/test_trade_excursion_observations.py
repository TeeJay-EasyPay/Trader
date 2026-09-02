"""The excursion measurement gets the price history it was always supposed to have.

2026-09-02, Founder-directed: "fix the observations line."

sprint6._learning_payload_from_canonical_trade hardcoded `"observations": []`, and that one
empty list defeated a whole measurement system. calculate_mae_mfe walks those observations to
find how far a trade moved AGAINST the entry before closing -- the maximum adverse excursion,
which is the single fact that answers "was the stop too tight?". With nothing to walk it
always measured zero, so production accumulated 22 TRADE_EXCURSIONS rows every one of which
read 0.00%. The table looked populated and contained nothing, which is worse than being empty:
a row count suggests data.

The price history was there the whole time -- in MARKET_DATA_OBSERVATIONS.

IT TOOK TWO ATTEMPTS TO GET THE TABLE RIGHT, which is why the last test here exists. The
first fix read HISTORICAL_CANDLES: the obvious name, holding 91 rows for a single ETF and
last written three weeks earlier, because crypto was never ingested into it. Correct code
pointed at an empty table would have shipped, looked finished, and measured exactly as much
as the bug it replaced. Fourth time this week for that trap, second time it caught me while
I was fixing the trap itself.

THE TRAP THESE TESTS EXIST FOR. A daily candle's high and low span the whole day. Using the
day's range for a trade held 91 seconds -- JNJ on 2026-09-01 -- would report a 2% excursion
where the real one was 0.19%. That is far worse than no answer, because it looks authoritative
while arguing to loosen a stop that was never actually tested. So only candles falling INSIDE
the holding window are used, and an intraday trade correctly yields nothing.
"""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

from ai_trader.sprint6 import _learning_payload_from_canonical_trade, _observations_for_trade

CANDLES = """
CREATE TABLE IF NOT EXISTS MARKET_DATA_OBSERVATIONS (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL, provider TEXT NOT NULL,
    original_symbol TEXT NOT NULL, normalized_symbol TEXT NOT NULL,
    exchange TEXT, asset_type TEXT NOT NULL, timeframe TEXT NOT NULL,
    observation_time TEXT NOT NULL, retrieval_time TEXT NOT NULL,
    freshness TEXT NOT NULL, completeness TEXT NOT NULL,
    adjusted_status TEXT NOT NULL, source_quality_status TEXT NOT NULL,
    payload_provenance TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL, payload_json TEXT NOT NULL
);
"""

DAYS = [
    ("2026-08-28T00:00:00Z", 100.0, 101.0, 99.0, 100.5),
    ("2026-08-29T00:00:00Z", 100.5, 102.0, 96.0, 97.0),   # the worst day
    ("2026-08-30T00:00:00Z", 97.0, 99.0, 96.5, 98.5),
    ("2026-08-31T00:00:00Z", 98.5, 104.0, 98.0, 103.0),
    ("2026-09-05T00:00:00Z", 103.0, 120.0, 80.0, 110.0),  # AFTER the trade closed
]


@pytest.fixture()
def db():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "candles.db"
        with closing(sqlite3.connect(path)) as conn:
            with conn:
                conn.executescript(CANDLES)
                for observed_at, o, h, l, c in DAYS:
                    conn.execute(
                        """INSERT INTO MARKET_DATA_OBSERVATIONS
                           (created_at, provider, original_symbol, normalized_symbol, exchange,
                            asset_type, timeframe, observation_time, retrieval_time, freshness,
                            completeness, adjusted_status, source_quality_status,
                            payload_provenance, open, high, low, close, volume, payload_json)
                           VALUES (?, 'kraken', 'XBTGBP', 'BTC', 'KRAKEN', 'crypto', '1d', ?, ?,
                                   'fresh','complete','unadjusted','pass','kraken_ohlc_api',
                                   ?,?,?,?,0,'{}')""",
                        (observed_at, observed_at, observed_at, o, h, l, c),
                    )
        yield path


def _trade(**over):
    base = {
        "symbol": "BTC", "broker": "kraken", "asset_type": "crypto", "side": "buy",
        "created_at": "2026-08-28T00:00:00Z", "closed_at": "2026-08-31T23:59:59Z",
        "intended_entry_price": 100.0, "original_stop": 95.0, "intended_target": 110.0,
        "entry_filled_quantity": 1.0, "average_entry_price": 100.0, "average_exit_price": 103.0,
        "decision_context_json": "{}",
    }
    base.update(over)
    return base


def test_observations_are_no_longer_empty(db):
    """The whole bug, in one assertion."""
    assert _observations_for_trade(db, _trade()) != []


def test_only_candles_inside_the_holding_window_are_used(db):
    """The 5 September candle swings 80-120. Including it would report a catastrophic
    excursion on a trade that had already closed."""
    stamps = [o["observed_at"] for o in _observations_for_trade(db, _trade())]
    assert "2026-09-05T00:00:00Z" not in stamps
    assert len(stamps) == 4


def test_each_observation_carries_a_high_and_a_low(db):
    """calculate_mae_mfe reads item['high'] and item['low']. Without both it silently
    measures nothing -- which is exactly how this failed for weeks."""
    for observed in _observations_for_trade(db, _trade()):
        assert observed["high"] is not None and observed["low"] is not None
        assert observed["low"] <= observed["high"]


def test_the_worst_day_is_present_so_the_excursion_can_be_found(db):
    """29 August dipped to 96 against a 100 entry -- a 4% adverse move. If that candle is
    missing the measurement understates the risk taken, which is the dangerous direction."""
    lows = [o["low"] for o in _observations_for_trade(db, _trade())]
    assert min(lows) == 96.0


def test_an_intraday_trade_yields_nothing_rather_than_a_wrong_number(db):
    """JNJ was held 91 seconds on 2026-09-01. A daily candle would claim a 2% excursion
    where the truth was 0.19%, and that answer would argue for loosening a stop that was
    never tested. Nothing is the honest result until intraday candles exist."""
    intraday = _trade(created_at="2026-09-01T14:27:44Z", closed_at="2026-09-01T14:29:15Z")
    assert _observations_for_trade(db, intraday) == []


def test_a_trade_with_no_candles_at_all_is_survivable(db):
    assert _observations_for_trade(db, _trade(symbol="NOSUCHCOIN")) == []


def test_a_missing_opening_time_does_not_raise(db):
    assert _observations_for_trade(db, _trade(created_at="")) == []


def test_the_payload_now_carries_observations_and_its_granularity(db):
    """The granularity is recorded so nobody reads a daily measurement as an intraday one."""
    payload = _learning_payload_from_canonical_trade(db, _trade())
    assert payload["observations"], "the payload is still empty"
    assert payload["data_granularity"] == "1d"


def test_a_still_open_trade_uses_everything_up_to_now(db):
    """closed_at is empty until a trade settles. It must not collapse the window to nothing."""
    assert len(_observations_for_trade(db, _trade(closed_at=""))) >= 4


def test_the_query_targets_the_table_that_actually_holds_candles():
    """A guard against the mistake that was made writing this file.

    The first version of the fix read HISTORICAL_CANDLES: right-looking code, empty table,
    zero behaviour change. Nothing in a unit test would have caught it, because a test fixture
    populates whatever table the test creates. So this asserts the production table by name,
    and the name is the thing that was wrong.
    """
    import pathlib as _pathlib

    source = (_pathlib.Path(__file__).resolve().parents[1] / "src" / "ai_trader" / "sprint6.py")
    body = source.read_text(encoding="utf-8")
    start = body.index("def _observations_for_trade")
    end = body.index("\ndef ", start + 1)
    query = "\n".join(
        line for line in body[start:end].splitlines() if not line.strip().startswith("#")
    )
    assert "MARKET_DATA_OBSERVATIONS" in query, (
        "excursions must read MARKET_DATA_OBSERVATIONS -- the table the hourly refresh "
        "actually writes to"
    )
    assert "FROM HISTORICAL_CANDLES" not in query, (
        "HISTORICAL_CANDLES holds equities only and has not been written since 2026-08-13"
    )
