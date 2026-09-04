"""A backtest is only worth having if it cannot flatter the strategy.

2026-09-04, Founder-directed: "The back test is necessary... It's absolutely essential."

The danger with this particular build is not that it produces no number -- it is that it
produces a confident wrong one, which then gets quoted to the model as evidence and
raises confidence on a strategy that does not work. Every test below exists to pin one of
the ways a backtest lies:

  - counting a win that the bar could not prove (the stop and target both inside one day)
  - quietly dropping trades that never resolved, which are disproportionately the duds
  - modelling fees at a rate the Founder does not pay
  - reading a candle the trade could not have seen yet
"""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from ai_trader.backtest import (
    ROUND_TRIP_FEE_PCT,
    BacktestResult,
    BacktestTrade,
    Candle,
    atr_pct_from,
    backtest_symbol,
    record_backtest_result,
    simulate_trade,
    summarize,
)
from ai_trader.database import connect


def _candles(spec):
    return [Candle(date=d, open=o, high=h, low=lo, close=c) for d, o, h, lo, c in spec]


def _flat(entry=100.0):
    return Candle(date="2026-08-01", open=entry, high=entry, low=entry, close=entry)


# --------------------------------------------------------------------------
# 1. The pessimistic intraday rule -- the assumption that stops flattery
# --------------------------------------------------------------------------
def test_a_bar_spanning_both_stop_and_target_is_recorded_as_a_stop():
    """Daily candles cannot say which came first. Assuming the target would inflate
    results in exactly the cases where the strategy looked most impressive."""
    forward = _candles([("2026-08-02", 100, 130, 90, 120)])  # touches both
    trade = simulate_trade(_flat(), forward, stop_pct=0.05, reward_risk=2.0, symbol="BTC")
    assert trade.outcome == "stop"
    assert trade.r_multiple < 0


def test_a_clean_target_day_is_still_recorded_as_a_win():
    """The pessimism must not be indiscriminate -- a bar that never traded down to the
    stop is a genuine win and has to count as one."""
    forward = _candles([("2026-08-02", 100, 130, 99.5, 128)])
    trade = simulate_trade(_flat(), forward, stop_pct=0.05, reward_risk=2.0, symbol="BTC")
    assert trade.outcome == "target"
    assert trade.r_multiple > 0


# --------------------------------------------------------------------------
# 2. Fees -- the reason published backtests are unusable here
# --------------------------------------------------------------------------
def test_fees_are_charged_at_the_rate_the_founder_actually_pays():
    assert ROUND_TRIP_FEE_PCT == 0.0154, "measured over 26 real Kraken round trips"


def test_a_trade_that_hits_its_target_can_still_lose_money_after_fees():
    """The single most important property. At a 1-to-1 reward:risk on a 2% stop, the
    1.54% round trip eats most of the win -- which is why the live system needs a
    reward:risk floor, and why a fee-free backtest would have hidden that entirely."""
    forward = _candles([("2026-08-02", 100, 103, 99.9, 102)])
    trade = simulate_trade(_flat(), forward, stop_pct=0.02, reward_risk=1.0, symbol="BTC")
    assert trade.outcome == "target"
    assert trade.r_multiple < 0.3, f"fees barely modelled: {trade.r_multiple}R"


def test_removing_fees_would_make_the_same_trade_look_better():
    """Guards against a future refactor that drops the fee term silently."""
    forward = _candles([("2026-08-02", 100, 103, 99.9, 102)])
    charged = simulate_trade(_flat(), forward, stop_pct=0.02, reward_risk=1.0, symbol="BTC")
    free = simulate_trade(_flat(), forward, stop_pct=0.02, reward_risk=1.0, symbol="BTC", fee_pct=0.0)
    assert free.r_multiple > charged.r_multiple


# --------------------------------------------------------------------------
# 3. Unresolved trades are counted, not discarded
# --------------------------------------------------------------------------
def test_a_trade_that_never_resolves_is_still_counted():
    """Dropping open trades is a classic way to make a backtest look good: the ones
    going nowhere are disproportionately the ones still open."""
    forward = _candles([(f"2026-08-{d:02d}", 100, 100.5, 99.5, 100) for d in range(2, 12)])
    trade = simulate_trade(_flat(), forward, stop_pct=0.05, reward_risk=2.0, symbol="BTC",
                           max_holding_days=5)
    assert trade is not None
    assert trade.outcome == "timeout"


def test_an_unmodellable_trade_is_dropped_rather_than_scored_as_zero():
    """A zero-R trade would dilute the average toward flattery; None is honest."""
    assert simulate_trade(_flat(entry=0.0), _candles([("2026-08-02", 1, 1, 1, 1)]),
                          stop_pct=0.02, reward_risk=1.0, symbol="BTC") is None
    assert simulate_trade(_flat(), [], stop_pct=0.02, reward_risk=1.0, symbol="BTC") is None


# --------------------------------------------------------------------------
# 4. No lookahead
# --------------------------------------------------------------------------
def test_atr_needs_real_history_and_never_reports_zero_volatility():
    """A coin with too little history must return None so the caller uses the fallback.
    Reporting zero would size the stop at the floor for the most volatile new listings."""
    assert atr_pct_from(_candles([("2026-08-01", 100, 101, 99, 100)])) is None
    deep = _candles([(f"2026-08-{d:02d}", 100, 104, 96, 100) for d in range(1, 20)])
    measured = atr_pct_from(deep)
    assert measured is not None and measured > 0


def test_the_entry_bar_itself_is_never_used_as_an_exit():
    """Entry is at the close, so the same day's high and low are already spent."""
    entry = Candle(date="2026-08-01", open=100, high=200, low=50, close=100)
    forward = _candles([("2026-08-02", 100, 100.2, 99.8, 100)])
    trade = simulate_trade(entry, forward, stop_pct=0.05, reward_risk=2.0, symbol="BTC",
                           max_holding_days=1)
    assert trade.exit_date == "2026-08-02", "the entry bar's own range must not resolve the trade"


# --------------------------------------------------------------------------
# 5. The summary statistics
# --------------------------------------------------------------------------
def _result(*r_multiples):
    result = BacktestResult(strategy_id="s", symbol="BTC")
    for index, r in enumerate(r_multiples):
        result.trades.append(BacktestTrade("BTC", f"2026-08-{index+1:02d}", 100, 98, 104,
                                           f"2026-08-{index+2:02d}", 104,
                                           "target" if r > 0 else "stop", r))
    return result


def test_expectancy_matches_the_live_definition():
    """A backtest R the Founder cannot compare against the live scorecard is useless."""
    assert _result(1.0, -1.0, 2.0).expectancy_r == round(2.0 / 3, 4)


def test_max_drawdown_measures_peak_to_trough_not_the_worst_trade():
    # +2 then -1 -1 -1: peak 2, trough -1, so the run down is 3R.
    assert _result(2.0, -1.0, -1.0, -1.0).max_drawdown_r == 3.0


def test_an_empty_result_reports_nothing_rather_than_zero():
    """Zero trades reported as "0% win rate" would read as a failing strategy rather
    than an absent measurement -- the same confusion as the empty backtest table."""
    empty = BacktestResult(strategy_id="s", symbol="BTC")
    assert empty.win_rate is None and empty.expectancy_r is None
    assert "nothing to conclude" in summarize(empty)


def test_the_summary_states_the_verdict_in_plain_words():
    assert "losing" in summarize(_result(-1.0, -1.0))
    assert "profitable" in summarize(_result(2.0, 1.0))


# --------------------------------------------------------------------------
# 6. End to end, against the real tables
# --------------------------------------------------------------------------
def _seed(db_path: Path, *, confidence: float = 0.8, days: int = 40) -> None:
    with closing(connect(db_path)) as conn:
        conn.execute("""CREATE TABLE MARKET_DATA_OBSERVATIONS (
            observation_id INTEGER PRIMARY KEY, observation_time TEXT, normalized_symbol TEXT,
            timeframe TEXT, open REAL, high REAL, low REAL, close REAL)""")
        conn.execute("""CREATE TABLE CRYPTO_RESEARCH_SCORES (
            score_id INTEGER PRIMARY KEY, created_at TEXT, symbol TEXT,
            overall_due_diligence_score REAL, technical_trend_score REAL)""")
        for day in range(1, days + 1):
            price = 100.0 + day  # a steady uptrend, so targets are reachable
            conn.execute(
                "INSERT INTO MARKET_DATA_OBSERVATIONS (observation_time, normalized_symbol, timeframe, open, high, low, close)"
                " VALUES (?,?,?,?,?,?,?)",
                (f"2026-07-{day:02d}T00:00:00Z", "BTC", "1d", price, price * 1.03, price * 0.98, price),
            )
        conn.execute(
            "INSERT INTO CRYPTO_RESEARCH_SCORES (created_at, symbol, overall_due_diligence_score, technical_trend_score)"
            " VALUES (?,?,?,?)",
            ("2026-07-20T00:00:00Z", "BTC", confidence, 5.0),
        )
        conn.commit()


def test_a_full_replay_produces_trades_and_persists_them():
    tmp = Path(tempfile.mkdtemp()) / "bt.db"
    _seed(tmp)
    result = backtest_symbol(tmp, "BTC", min_confidence=0.6)
    assert result.count >= 1

    record_backtest_result(tmp, result)
    with closing(connect(tmp)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM STRATEGY_BACKTEST_RESULTS").fetchone()
    assert row["symbol"] == "BTC"
    assert row["trades"] == result.count
    assert "expectancy" in row["result_summary"]


def test_a_symbol_below_the_confidence_bar_produces_no_trades():
    """The replay must honour the live entry rule, or it is measuring a different
    strategy from the one that runs."""
    tmp = Path(tempfile.mkdtemp()) / "bt2.db"
    _seed(tmp, confidence=0.2)
    assert backtest_symbol(tmp, "BTC", min_confidence=0.6).count == 0


def test_the_stored_payload_records_the_assumptions_that_produced_the_number():
    """A backtest whose assumptions are not written down cannot be audited later, and
    this one's assumptions are the whole reason to trust or distrust it."""
    import json

    tmp = Path(tempfile.mkdtemp()) / "bt3.db"
    _seed(tmp)
    record_backtest_result(tmp, backtest_symbol(tmp, "BTC", min_confidence=0.6))
    with closing(connect(tmp)) as conn:
        conn.row_factory = sqlite3.Row
        payload = json.loads(conn.execute("SELECT payload_json FROM STRATEGY_BACKTEST_RESULTS").fetchone()["payload_json"])
    assert payload["fee_pct_round_trip"] == ROUND_TRIP_FEE_PCT
    assert "stop-first" in payload["intraday_assumption"]
