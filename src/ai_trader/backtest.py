"""Replay this system's own entry rules over its own price history, at its own fees.

2026-09-04, Founder-directed: "The back test is necessary. It's one of those things that
the model will be able to use to test its theories and look at how things performed. It's
absolutely essential."

He also asked whether published backtests could be used instead. They cannot, and the
reason is his fee tier rather than anything about the strategies: Kraken charges him
0.40%/0.80%, measured at 1.54% round trip across 26 real trades, while essentially every
published crypto backtest assumes ~0.1% or zero. Fees alone consume 1.023R of his risk
budget per trade, so a strategy that publishes as clearly profitable can be firmly
negative in his account. A backtest is only evidence if it is HIS rules, HIS fees, HIS
history.

WHAT LIMITS THE WINDOW
----------------------
propose_crypto_trades does not read candles. It reads precomputed research scores
(overall_due_diligence_score, technical_trend_score, momentum_score) out of
CRYPTO_RESEARCH_SCORES. Candles go back two years; the scores go back 47 days. So a
FAITHFUL replay -- the real rule, on the real inputs, as they actually stood on the day --
can only cover the days where scores were retained.

The alternative is to recompute historical scores from candles and reach two years. That
is worth doing, but only behind a validation gate: recompute the days where stored scores
also exist, compare, and extend backwards only if they agree. A backtest built on a
scorer that has silently drifted from the live one measures a strategy nobody runs, and
would then be quoted to the model as evidence. A confident wrong number is worse here
than no number, which is why this module ships the trustworthy half first.

THREE MODELLING CHOICES, ALL DELIBERATELY PESSIMISTIC
-----------------------------------------------------
1. Real fees, first-class. ROUND_TRIP_FEE_PCT below, not a token 0.1%.
2. Pessimistic intraday ordering. Daily candles record the high and the low but not the
   order they occurred. When one day's range spans both the stop and the target, this
   assumes the STOP filled first. It is the only assumption that cannot flatter a result.
3. No lookahead. Each entry uses only the score for that day and candles strictly after
   it; exits never consult a bar the trade could not have seen.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .database import connect
from .models import utc_now_iso
from .volatility_stops import volatility_stop_pct

# Measured across 26 real Kraken round trips (0.77% per leg), not the published headline
# rate. Every result this module produces is net of it.
ROUND_TRIP_FEE_PCT = 0.0154

# A trade that never hits stop or target is closed at the last candle it can see, rather
# than being silently discarded. Dropping unresolved trades is a classic way to make a
# backtest look better than the strategy: the ones still open are disproportionately the
# ones going nowhere.
MAX_HOLDING_DAYS = 30


@dataclass(frozen=True)
class Candle:
    date: str
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class BacktestTrade:
    symbol: str
    entry_date: str
    entry_price: float
    stop_price: float
    target_price: float
    exit_date: str
    exit_price: float
    outcome: str          # "target" | "stop" | "timeout"
    r_multiple: float     # net of fees


@dataclass
class BacktestResult:
    strategy_id: str
    symbol: str
    trades: list[BacktestTrade] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float | None:
        if not self.trades:
            return None
        return round(sum(1 for t in self.trades if t.r_multiple > 0) / len(self.trades), 4)

    @property
    def average_r(self) -> float | None:
        if not self.trades:
            return None
        return round(sum(t.r_multiple for t in self.trades) / len(self.trades), 4)

    @property
    def expectancy_r(self) -> float | None:
        # Same definition as expectancy.py deliberately: a backtest number the Founder
        # cannot compare against the live scorecard is not decision-useful.
        return self.average_r

    @property
    def profit_factor(self) -> float | None:
        gains = sum(t.r_multiple for t in self.trades if t.r_multiple > 0)
        losses = -sum(t.r_multiple for t in self.trades if t.r_multiple < 0)
        if losses <= 0:
            return None if gains <= 0 else float("inf")
        return round(gains / losses, 4)

    @property
    def max_drawdown_r(self) -> float | None:
        """Worst peak-to-trough run of the cumulative R curve."""
        if not self.trades:
            return None
        cumulative = peak = 0.0
        worst = 0.0
        for trade in self.trades:
            cumulative += trade.r_multiple
            peak = max(peak, cumulative)
            worst = min(worst, cumulative - peak)
        return round(abs(worst), 4)


def _candles(db_path: Path, symbol: str) -> list[Candle]:
    """Daily candles for one symbol, oldest first.

    Indexes rows by column name via sqlite3.Row rather than unpacking positionally:
    production is Postgres and the tests are SQLite, and the two disagree on row shape
    often enough that positional access here would be a bug no test could catch.
    """
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT observation_time, open, high, low, close
            FROM MARKET_DATA_OBSERVATIONS
            WHERE normalized_symbol = ? AND timeframe = '1d'
              AND open IS NOT NULL AND high IS NOT NULL
              AND low IS NOT NULL AND close IS NOT NULL
            ORDER BY observation_time
            """,
            (symbol.upper(),),
        ).fetchall()
    candles = []
    for row in rows:
        try:
            candles.append(
                Candle(
                    date=str(row["observation_time"])[:10],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                )
            )
        except (TypeError, ValueError):
            continue  # a malformed candle is skipped, never guessed at
    return candles


def atr_pct_from(candles: list[Candle], *, period: int = 14) -> float | None:
    """Average true range over `period` bars, as a share of the last close.

    True range rather than plain high-minus-low, so an overnight gap counts as the
    movement it was. Returns None when there is not enough history to measure, which the
    caller must treat as "size the stop from the fallback", never as "volatility is zero".
    """
    if len(candles) < period + 1:
        return None
    ranges = []
    for previous, current in zip(candles[-(period + 1):-1], candles[-period:]):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    last_close = candles[-1].close
    if last_close <= 0 or not ranges:
        return None
    return (sum(ranges) / len(ranges)) / last_close


def simulate_trade(
    entry_candle: Candle,
    forward: list[Candle],
    *,
    stop_pct: float,
    reward_risk: float,
    symbol: str,
    fee_pct: float = ROUND_TRIP_FEE_PCT,
    max_holding_days: int = MAX_HOLDING_DAYS,
) -> BacktestTrade | None:
    """One long trade, entered at `entry_candle`'s close, walked forward bar by bar.

    Returns None when the trade cannot be modelled at all (a non-positive price), rather
    than substituting a value -- an unmodellable trade must not become a zero-R trade,
    which would dilute the average toward flattery.
    """
    entry = entry_candle.close
    if entry <= 0 or stop_pct <= 0 or not forward:
        return None

    stop_price = entry * (1.0 - stop_pct)
    target_price = entry * (1.0 + stop_pct * reward_risk)
    risk_per_unit = entry - stop_price

    for candle in forward[:max_holding_days]:
        hit_stop = candle.low <= stop_price
        hit_target = candle.high >= target_price
        # Pessimistic ordering: a bar that spans both is recorded as the stop. Daily data
        # cannot say which came first, and assuming the target would inflate every result
        # in exactly the situations where the strategy looked most impressive.
        if hit_stop:
            exit_price, outcome = stop_price, "stop"
        elif hit_target:
            exit_price, outcome = target_price, "target"
        else:
            continue
        return _finish(symbol, entry_candle, candle, entry, exit_price, stop_price,
                       target_price, risk_per_unit, outcome, fee_pct)

    # Never resolved inside the window: closed at the last bar it could see, and counted.
    last = forward[min(len(forward), max_holding_days) - 1]
    return _finish(symbol, entry_candle, last, entry, last.close, stop_price,
                   target_price, risk_per_unit, "timeout", fee_pct)


def _finish(
    symbol: str,
    entry_candle: Candle,
    exit_candle: Candle,
    entry: float,
    exit_price: float,
    stop_price: float,
    target_price: float,
    risk_per_unit: float,
    outcome: str,
    fee_pct: float,
) -> BacktestTrade:
    # Fees are charged against the position, then expressed in units of risk -- the same
    # arithmetic as the live fee gate (fee_R = round-trip fee % / stop %), so a backtest R
    # and a live R mean the same thing and can sit in the same sentence.
    fee_in_price = entry * fee_pct
    net_gain = (exit_price - entry) - fee_in_price
    return BacktestTrade(
        symbol=symbol.upper(),
        entry_date=entry_candle.date,
        entry_price=round(entry, 8),
        stop_price=round(stop_price, 8),
        target_price=round(target_price, 8),
        exit_date=exit_candle.date,
        exit_price=round(exit_price, 8),
        outcome=outcome,
        r_multiple=round(net_gain / risk_per_unit, 4) if risk_per_unit > 0 else 0.0,
    )


def _entry_days(db_path: Path, symbol: str, *, min_confidence: float) -> list[str]:
    """Days on which the live rule would have opened this symbol.

    Reads the stored research scores rather than recomputing them: these are the exact
    values propose_crypto_trades saw, so this is a replay of the real decision and not a
    reconstruction of it. That fidelity is the whole reason the window is short.
    """
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT created_at, overall_due_diligence_score, technical_trend_score
            FROM CRYPTO_RESEARCH_SCORES
            WHERE symbol = ? AND overall_due_diligence_score IS NOT NULL
            ORDER BY created_at
            """,
            (symbol.upper(),),
        ).fetchall()
    days: list[str] = []
    seen: set[str] = set()
    for row in rows:
        try:
            confidence = float(row["overall_due_diligence_score"] or 0.0)
        except (TypeError, ValueError):
            continue
        if confidence < min_confidence:
            continue
        trend = row["technical_trend_score"]
        try:
            if trend is not None and float(trend) < 0:
                continue  # the live rule is buy-only; a negative trend never entered
        except (TypeError, ValueError):
            pass
        day = str(row["created_at"])[:10]
        # One entry per day per symbol, matching the live loop, which proposes a symbol
        # once per cycle rather than once per stored score row.
        if day not in seen:
            seen.add(day)
            days.append(day)
    return days


def backtest_symbol(
    db_path: Path,
    symbol: str,
    *,
    min_confidence: float,
    reward_risk: float = 1.0,
    default_stop_pct: float = 0.02,
    strategy_id: str = "crypto-momentum-v1",
) -> BacktestResult:
    """Replay one symbol. Empty result when there is nothing trustworthy to replay."""
    result = BacktestResult(strategy_id=strategy_id, symbol=symbol.upper())
    candles = _candles(db_path, symbol)
    if len(candles) < 2:
        return result
    by_date = {candle.date: index for index, candle in enumerate(candles)}

    for day in _entry_days(db_path, symbol, min_confidence=min_confidence):
        index = by_date.get(day)
        if index is None or index + 1 >= len(candles):
            continue  # no candle for that day, or nothing after it to walk forward into
        # ATR from candles strictly up to and including the entry bar -- never beyond.
        atr = atr_pct_from(candles[: index + 1])
        stop_pct = volatility_stop_pct(atr, fallback=default_stop_pct)
        trade = simulate_trade(
            candles[index],
            candles[index + 1:],
            stop_pct=stop_pct,
            reward_risk=reward_risk,
            symbol=symbol,
        )
        if trade is not None:
            result.trades.append(trade)
    return result


def summarize(result: BacktestResult) -> str:
    """One line a non-technical reader can act on."""
    if not result.count:
        return f"No {result.symbol} entries in the replayable window; nothing to conclude."
    verdict = "profitable" if (result.expectancy_r or 0) > 0 else "losing"
    return (
        f"{result.symbol}: {result.count} replayed trades, {result.win_rate:.0%} won, "
        f"expectancy {result.expectancy_r:+.2f}R after fees - {verdict} over this window."
    )


def record_backtest_result(
    db_path: Path,
    result: BacktestResult,
    *,
    asset_type: str = "crypto",
    timeframe: str = "1d",
) -> None:
    """Persist into STRATEGY_BACKTEST_RESULTS, the table the AI prompt already reads.

    Nothing else needs changing for this to reach the model: proposal_context already
    selects the most recent row for a symbol, and reports the source as unwired only while
    the table is empty.
    """
    from .trading_intelligence import initialize_trading_intelligence_schema

    initialize_trading_intelligence_schema(db_path)
    trades = result.trades
    payload = {
        "fee_pct_round_trip": ROUND_TRIP_FEE_PCT,
        "intraday_assumption": "stop-first when a bar spans both stop and target",
        "max_holding_days": MAX_HOLDING_DAYS,
        "outcomes": {
            outcome: sum(1 for t in trades if t.outcome == outcome)
            for outcome in ("target", "stop", "timeout")
        },
    }
    with closing(connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO STRATEGY_BACKTEST_RESULTS (
                created_at, strategy_id, symbol, asset_type, timeframe, start_at, end_at,
                trades, win_rate, average_r, expectancy_r, profit_factor, max_drawdown_r,
                sharpe_proxy, sortino_proxy, result_summary, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now_iso(),
                result.strategy_id,
                result.symbol,
                asset_type,
                timeframe,
                trades[0].entry_date if trades else None,
                trades[-1].exit_date if trades else None,
                result.count,
                result.win_rate,
                result.average_r,
                result.expectancy_r,
                # inf is a real profit-factor answer (no losers) but not a storable one.
                None if result.profit_factor in (None, float("inf")) else result.profit_factor,
                result.max_drawdown_r,
                None,
                None,
                summarize(result),
                json.dumps(payload),
            ),
        )
        conn.commit()
