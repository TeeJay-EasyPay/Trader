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
                SELECT symbol, side, status, exit_time, net_pnl, gross_pnl, net_r
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
    return {
        "generated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "day": buckets["day"],
        "week": buckets["week"],
        "month": buckets["month"],
        "lessons": deterministic_lessons_line(buckets),
        "lessons_source": "counts",
        "closed_trades_considered": len(trades),
    }
