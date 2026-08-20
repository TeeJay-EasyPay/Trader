"""Founder-facing trade scorecard: how many trades worked, how many didn't, and what
was actually learned -- Founder-requested 2026-08-20.

*"I would like to see a small card on the executive briefing screen with how many trades
each day, week and month were successful and how many were not with them a short ai
summary of one or two sentences on the lessons learned."*

Two honesty rules are baked in rather than left to the caller:

1. A closed trade with no reconciled P&L is counted as `unknown`, never silently folded
   into wins or losses. The Founder has been shown confident-looking numbers built on
   absent data before; a scorecard that quietly rounds unknowns into "successful" is worse
   than no scorecard.
2. The lessons line is short by construction (the Founder asked for one or two sentences),
   and when there is genuinely nothing to learn from it says so plainly instead of
   generating filler. The existing Executive Briefing already suffers from verbose
   generated text crowding out the short high-value sections.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .database import connect


_PERIODS: dict[str, float] = {
    "day": 86_400.0,
    "week": 7 * 86_400.0,
    "month": 30 * 86_400.0,
}


def _as_epoch(value: Any) -> float | None:
    """Accept the several shapes an exit time arrives in without guessing wrongly.

    KRAKEN_RECONCILED_RESULTS stores epoch seconds as a STRING ('1787173950.17846');
    other tables store ISO-8601. Anything unparseable returns None and the trade is
    reported as `unknown` rather than being dated to now (which would silently pull old
    trades into today's count).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        cleaned = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return None


def _empty_bucket() -> dict[str, Any]:
    return {"successful": 0, "unsuccessful": 0, "breakeven": 0, "unknown": 0, "net_pnl": 0.0}


def summarize_trade_outcomes(trades: Iterable[dict[str, Any]], *, now_epoch: float) -> dict[str, Any]:
    """Bucket closed trades into day/week/month win-loss counts.

    Windows are rolling (last 24h / 7d / 30d) rather than calendar-aligned, so the card
    never shows a near-empty "month" simply because the calendar month just turned over.
    A trade inside the day window is also inside the week and month windows.
    """
    buckets = {name: _empty_bucket() for name in _PERIODS}
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        exit_epoch = _as_epoch(trade.get("exit_time") or trade.get("closed_at") or trade.get("updated_at"))
        pnl = trade.get("net_pnl")
        pnl_value: float | None
        try:
            pnl_value = None if pnl is None else float(pnl)
        except (TypeError, ValueError):
            pnl_value = None
        for name, window in _PERIODS.items():
            if exit_epoch is None or now_epoch - exit_epoch > window or exit_epoch > now_epoch + 60:
                continue
            bucket = buckets[name]
            if pnl_value is None:
                bucket["unknown"] += 1
            elif pnl_value > 0:
                bucket["successful"] += 1
                bucket["net_pnl"] += pnl_value
            elif pnl_value < 0:
                bucket["unsuccessful"] += 1
                bucket["net_pnl"] += pnl_value
            else:
                bucket["breakeven"] += 1
    for bucket in buckets.values():
        bucket["net_pnl"] = round(bucket["net_pnl"], 8)
        bucket["settled"] = bucket["successful"] + bucket["unsuccessful"] + bucket["breakeven"]
        bucket["total"] = bucket["settled"] + bucket["unknown"]
        bucket["win_rate"] = (
            round(bucket["successful"] / bucket["settled"], 4) if bucket["settled"] else None
        )
    return buckets


def deterministic_lessons_line(buckets: dict[str, Any]) -> str:
    """An honest one-liner used when no AI summary is available.

    Never invents a lesson. With no settled trades it says exactly that -- which is the
    truthful state for an account that has been correctly declining to trade.
    """
    month = buckets.get("month") or _empty_bucket()
    settled = month.get("settled") or 0
    if not settled:
        unknown = month.get("unknown") or 0
        if unknown:
            return (
                f"No lessons yet: {unknown} trade(s) closed in the last 30 days but none have a "
                "reconciled profit or loss recorded, so none can be judged."
            )
        return "No trades have closed in the last 30 days, so there is nothing to learn from yet."
    wins = month.get("successful") or 0
    losses = month.get("unsuccessful") or 0
    net = month.get("net_pnl") or 0.0
    direction = "ahead" if net > 0 else "behind" if net < 0 else "flat"
    return (
        f"Over the last 30 days {wins} trade(s) made money and {losses} lost money, "
        f"leaving the account {direction} by {abs(net):.2f} overall."
    )


def load_closed_trades(db_path: Path, *, limit: int = 400) -> list[dict[str, Any]]:
    """Closed trades with a real exit time, newest first.

    KRAKEN_RECONCILED_RESULTS is the source of truth for crypto: it is what the AI capital
    ledger itself reconciles against, and it carries a genuine net_pnl including exchange
    fees. Rows still awaiting fill are excluded -- an unfilled exit is not a closed trade.
    Any read failure returns an empty list rather than raising: this powers a Founder
    display card, and a reporting query must never be able to break the briefing.
    """
    try:
        with closing(connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT symbol, side, status, exit_time, net_pnl, gross_pnl, net_r,
                       planned_r, exchange_fee, broker_fee, entry_slippage, exit_slippage,
                       quantity, actual_entry, actual_exit
                FROM KRAKEN_RECONCILED_RESULTS
                WHERE exit_time IS NOT NULL AND status = 'closed'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []


def trade_scorecard(db_path: Path, *, now_epoch: float | None = None) -> dict[str, Any]:
    """The Founder-facing scorecard payload: day/week/month counts plus a lessons line."""
    now = datetime.now(timezone.utc).timestamp() if now_epoch is None else float(now_epoch)
    trades = load_closed_trades(db_path)
    buckets = summarize_trade_outcomes(trades, now_epoch=now)
    # Lead with the CAUSE when one is genuinely identifiable, and fall back to the count
    # line only when no driver clears its threshold. Founder feedback 2026-08-20: the count
    # line alone "is just stating the obvious... It should actually say the why".
    why = explain_trade_outcomes(trades, now_epoch=now, window="month")
    return {
        "generated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "day": buckets["day"],
        "week": buckets["week"],
        "month": buckets["month"],
        "lessons": why or deterministic_lessons_line(buckets),
        "lessons_source": "driver_analysis" if why else "counts",
        "closed_trades_considered": len(trades),
    }


def _num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def explain_trade_outcomes(trades: Iterable[dict[str, Any]], *, now_epoch: float, window: str = "month") -> str | None:
    """Explain WHY the period went the way it did, using real reconciled numbers.

    Founder feedback 2026-08-20: *"I just feel that the AI explanation is just stating the
    obvious. It should actually say the why something was negative or positive, not just
    what the numbers are saying."* Counting wins and losses restates the scoreboard; this
    names the dominant cause and quotes the figure behind it.

    Drivers are checked most-actionable first and only ONE is reported, because the Founder
    asked for one or two sentences and a list of every contributing factor is exactly the
    wall-of-text that already buries the good sections of this briefing.

    Every driver is derived arithmetically from reconciled fields -- never inferred, never
    generated. Returns None when no driver clears its threshold, so the caller falls back
    to the plain count line rather than this inventing a narrative.
    """
    window_seconds = _PERIODS.get(window, _PERIODS["month"])
    recent: list[dict[str, Any]] = []
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        exit_epoch = _as_epoch(trade.get("exit_time") or trade.get("closed_at") or trade.get("updated_at"))
        if exit_epoch is None or now_epoch - exit_epoch > window_seconds or exit_epoch > now_epoch + 60:
            continue
        recent.append(trade)
    if not recent:
        return None

    fees = 0.0
    gross_wins = 0.0
    net_total = 0.0
    overruns: list[str] = []
    for trade in recent:
        fee = (_num(trade.get("exchange_fee")) or 0.0) + (_num(trade.get("broker_fee")) or 0.0)
        fees += fee
        gross = _num(trade.get("gross_pnl"))
        if gross is not None and gross > 0:
            gross_wins += gross
        net = _num(trade.get("net_pnl"))
        if net is not None:
            net_total += net
        # net_r below -1 means the trade lost MORE than the risk it was sized for, which can
        # only happen if the exit filled past the stop. That is a slippage/execution problem,
        # not a bad-thesis problem, and the two need very different fixes.
        net_r = _num(trade.get("net_r"))
        if net_r is not None and net_r < -1.25:
            symbol = str(trade.get("symbol") or "").upper() or "a position"
            overruns.append(f"{symbol} lost {abs(net_r):.1f}x the risk it was sized for")

    # 1. Fee drag. The clearest and most fixable cause when trade sizes are small: a fee
    #    that is a fixed-ish cost per round trip consumes a far larger share of a tiny
    #    position's move than of a normal one.
    if fees > 0 and gross_wins > 0 and fees >= gross_wins * 0.5:
        return (
            f"The trades themselves were not the main problem: fees of {fees:.2f} came to more than "
            f"{fees / gross_wins:.1f}x everything the winners made before costs ({gross_wins:.2f}), "
            "so position sizes were too small for the moves captured to survive the cost of trading."
        )
    # 2. Exits filling past the stop.
    if overruns:
        return (
            f"The damage came from exits filling past their stop rather than from bad entries: "
            f"{overruns[0]}. Tightening how exits are placed matters more here than picking different trades."
        )
    # 3. Fees material but not dominant.
    if fees > 0 and abs(net_total) > 0 and fees >= abs(net_total) * 0.3:
        return (
            f"Trading costs are a meaningful drag: {fees:.2f} of fees against a net result of "
            f"{net_total:+.2f}, so a large share of the outcome is the cost of trading rather than the calls themselves."
        )
    return None


def estimate_round_trip_fee_pct(trades: Iterable[dict[str, Any]], *, default: float = 0.0) -> float:
    """The fee rate actually being paid, measured from settled trades.

    Measured rather than assumed, because the assumption would have been wrong. Kraken's
    published taker fee is 0.26%, but every one of the first eight settled trades paid
    1.56-1.62% of notional -- roughly six times that, and remarkably consistent, which rules
    out a fixed minimum charge diluting on small orders. Whatever the cause, the strategy
    has to be judged against the rate being paid, not the rate on the fee schedule.

    Uses the median so a single odd fill cannot move the estimate.

    Defaults to 0.0 (meaning "unknown", which leaves the fee gate inactive) rather than to
    the observed 1.6%. Carrying one account's measured rate over to a system with no trade
    history would block every trade on an assumption instead of on evidence -- caught by a
    real test failure, where a fresh database inherited the punitive rate and produced zero
    proposals. The gate should act on what this account actually pays, or not at all.
    """
    rates: list[float] = []
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        fee = (_num(trade.get("exchange_fee")) or 0.0) + (_num(trade.get("broker_fee")) or 0.0)
        quantity = _num(trade.get("quantity"))
        price = _num(trade.get("actual_exit")) or _num(trade.get("actual_entry"))
        if fee <= 0 or not quantity or not price:
            continue
        notional = abs(quantity * price)
        if notional <= 0:
            continue
        rates.append(fee / notional)
    if not rates:
        return float(default)
    rates.sort()
    middle = len(rates) // 2
    median = rates[middle] if len(rates) % 2 else (rates[middle - 1] + rates[middle]) / 2
    return round(median, 6)
