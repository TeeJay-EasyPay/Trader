from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .database import connect
from .models import utc_now_iso

DAILY_TRADING_PLAN_DECISIONS = {"seek_trades", "stand_aside"}

DAILY_TRADING_PLAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS DAILY_TRADING_PLANS (
    plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    plan_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decision TEXT NOT NULL,
    market_assessment TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    symbols_scanned INTEGER NOT NULL,
    candidates_found INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(broker, plan_date)
);
"""


def initialize_daily_plan_schema(db_path: Path) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(DAILY_TRADING_PLAN_SCHEMA)


def trading_day_for(broker: str, *, now: datetime | None = None) -> str:
    """The broker's own "today" for daily-plan bucketing.

    Alpaca (the only broker with a daily-plan concept so far -- crypto research
    already runs continuously, with no single "morning") trades on the NYSE
    calendar. Reuses the exact America/New_York day-bucketing convention cli.py's
    _due_worker_jobs already uses to schedule premarket-equity, so a plan's date
    always matches the trading-day boundary the app already schedules that
    morning's research against.
    """
    moment = now or datetime.now(timezone.utc)
    if broker.lower() == "alpaca":
        return moment.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    return moment.astimezone(timezone.utc).date().isoformat()


def record_daily_trading_plan(
    db_path: Path,
    *,
    broker: str,
    decision: str,
    market_assessment: str,
    reasoning: str,
    symbols_scanned: int,
    candidates_found: int,
    payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record the day's one-time trading decision. Idempotent: a second call for the
    same (broker, plan_date) -- e.g. a retried premarket-equity job under this
    deployment's idempotency-key scheduling -- leaves the first decision standing
    rather than overwriting it with a re-run's possibly-different outcome."""
    if decision not in DAILY_TRADING_PLAN_DECISIONS:
        raise ValueError(f"Unsupported daily trading plan decision: {decision!r}")
    initialize_daily_plan_schema(db_path)
    plan_date = trading_day_for(broker, now=now)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                INSERT INTO DAILY_TRADING_PLANS (
                    broker, plan_date, created_at, decision, market_assessment,
                    reasoning, symbols_scanned, candidates_found, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(broker, plan_date) DO NOTHING
                """,
                (
                    broker.lower(),
                    plan_date,
                    utc_now_iso(),
                    decision,
                    market_assessment,
                    reasoning,
                    int(symbols_scanned),
                    int(candidates_found),
                    json.dumps(payload or {}, sort_keys=True, default=str),
                ),
            )
        row = conn.execute(
            "SELECT * FROM DAILY_TRADING_PLANS WHERE broker = ? AND plan_date = ?",
            (broker.lower(), plan_date),
        ).fetchone()
    return dict(row) if row else {}


def _count_trades_since(db_path: Path, *, broker: str, since: str) -> int:
    # PRODUCTION_TRADE_EVIDENCE (production_evidence.py) is initialized elsewhere in every
    # real runtime path this function is reachable from; the OperationalError guard only
    # covers a genuinely fresh/uninitialized database (e.g. an isolated test), matching the
    # same "missing structure means no data yet, not a hard failure" convention already
    # established across this codebase's Postgres/SQLite dual-backend call sites.
    # 2026-08-27, Founder-reported: this said "13 share trades placed today" on a day with 6.
    # It counted evidence ROWS, and a broker records one row per order event -- a single
    # bracketed buy produces new/held/partial_fill/fill/filled. Including 'new' also counted
    # the protective stop-loss and take-profit legs a bracket attaches automatically, which
    # are not trades the app decided to place. Now counts distinct broker orders that actually
    # filled, the one definition in trade_counting.py that every surface shares.
    from .trade_counting import count_trades

    try:
        with closing(connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT broker_order_id, broker_trade_id, symbol, side, status, payload_json
                FROM PRODUCTION_TRADE_EVIDENCE
                WHERE broker = ? AND observed_at >= ?
                """,
                (broker.lower(), since),
            ).fetchall()
    except sqlite3.OperationalError:
        return 0
    return count_trades([dict(row) for row in rows])


def daily_trading_plan_status(db_path: Path, *, broker: str, now: datetime | None = None) -> dict[str, Any]:
    """The day's plan plus a live-computed outcome -- reconciled fresh on every read
    against actual trade evidence, not written once and left to go stale. Mirrors
    production_evidence.py's _why_no_trade: a plain-English state derived from real
    data, never a second persisted "outcome" write path to drift out of sync."""
    initialize_daily_plan_schema(db_path)
    plan_date = trading_day_for(broker, now=now)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM DAILY_TRADING_PLANS WHERE broker = ? AND plan_date = ?",
            (broker.lower(), plan_date),
        ).fetchone()
    if not row:
        return {
            "broker": broker.lower(),
            "plan_date": plan_date,
            "status": "not_yet_generated",
            "plain_english": "Today's trading plan has not been generated yet -- it is decided each morning before market open.",
        }
    plan = dict(row)
    trades_today = _count_trades_since(db_path, broker=broker, since=plan["created_at"])
    if plan["decision"] == "stand_aside":
        if trades_today:
            # 2026-08-27, Founder-reported: this read "Planned to stand aside, but 13 trade(s)
            # were recorded today -- worth reviewing" directly above a plan whose stated
            # reasoning was that nothing passed. Two faults in one sentence.
            #
            # "worth reviewing" and the outcome key "plan_broken" framed an ordinary sequence
            # as a fault. The plan is written BEFORE the market opens, when every candidate is
            # correctly rejected for market_closed; the market then opens and intraday scans
            # find ideas the pre-market scan could not. The plan was right when written and
            # simply superseded -- which is what a trader does, not a malfunction. Sending the
            # Founder off to "review" a normal day trains him to ignore the line.
            #
            # And the sentence never said WHY both halves were true at once, so the card read
            # as self-contradicting: stood aside, yet traded. Saying the plan was revised
            # intraday makes one coherent story out of two true facts.
            outcome, outcome_text = (
                "revised_intraday",
                f"The pre-market plan was to stand aside, because nothing cleared the bar before "
                f"the open. {trades_today} trade(s) have been placed since, as intraday scans "
                f"found opportunities the pre-market scan could not see.",
            )
        else:
            outcome, outcome_text = ("as_planned", "Stood aside as planned -- no trades attempted today.")
    else:
        if trades_today:
            outcome, outcome_text = (
                "as_planned",
                f"{trades_today} trade(s) executed today, consistent with this morning's plan to seek opportunities.",
            )
        else:
            outcome, outcome_text = ("no_trades_yet", "Still seeking -- no trade has executed yet today.")
    return {
        "broker": plan["broker"],
        "plan_date": plan["plan_date"],
        "status": "generated",
        "decision": plan["decision"],
        "market_assessment": plan["market_assessment"],
        "reasoning": plan["reasoning"],
        "symbols_scanned": plan["symbols_scanned"],
        "candidates_found": plan["candidates_found"],
        "created_at": plan["created_at"],
        "trades_today": trades_today,
        "outcome": outcome,
        "outcome_plain_english": outcome_text,
    }
