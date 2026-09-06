"""The trading AI's own standing report on whether it has what it needs.

2026-09-06, Founder-directed. He asked the AI in the app whether it was satisfied it had the
inputs to make good and profitable decisions on Alpaca and Kraken. The answer was more useful
than any dashboard: it named two real defects nobody had found -- a track-record discrepancy,
and repeated rows in the attribution table. Both checked out. PERFORMANCE_ATTRIBUTION held 94
rows for 27 real round trips, every trade counted about four times.

So he asked for it on a schedule, twice a day, plus a harder question: what is missing for it
to become the best trader in the world.

THE DESIGN POINT IS TAKEN FROM THE WEAKNESS IN THAT FIRST ANSWER. It began:

    "the system has just restarted, and its research, forecasts, recommendations and crypto
     news haven't loaded into this answer yet... I can't currently assess their freshness,
     coverage or whether they actually informed each trade."

It was being asked to reason about its inputs without being shown them. So this job does not
merely ask the question -- it MEASURES the inputs first and hands over the census. An answer
of "ask me again in a moment" is a wasted assessment; an answer arguing with real freshness
and coverage numbers is evidence.

Read-only by construction: it observes and reports, and can place no trade.
"""

from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .database import connect, row_values
from .models import utc_now_iso

SELF_ASSESSMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS AI_SELF_ASSESSMENTS (
    assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    model TEXT,
    status TEXT NOT NULL,
    inventory_json TEXT NOT NULL,
    answer TEXT
);
"""

# Every feed a trading decision genuinely consults, with the column that dates a row. Held as
# data rather than prose so the census cannot drift from what is actually measured.
_FEEDS: tuple[tuple[str, str, str], ...] = (
    ("CRYPTO_NEWS", "created_at", "coin news used to judge a crypto entry"),
    ("NEWS_CATALYST_EVIDENCE", "created_at", "news catalysts attached to a symbol"),
    ("MARKET_REGIME_EVIDENCE", "created_at", "market regime an entry is judged against"),
    ("CRYPTO_SENTIMENT_SCORES", "created_at", "per-coin behavioural score"),
    # observed_at, not created_at. Getting this wrong is what cascaded on the first real
    # run -- see _scalar. test_every_feed_column_exists is the guard against it drifting again.
    ("CRYPTO_MARKET_DATA", "observed_at", "crypto prices and ranges"),
    ("PERFORMANCE_ATTRIBUTION", "closed_at", "completed trades the learning loop reads"),
    ("STRATEGY_BACKTEST_RESULTS", "created_at", "backtest evidence behind a strategy"),
    ("PRODUCTION_RESEARCH_EVIDENCE", "completed_at", "research runs"),
    ("PRODUCTION_RECOMMENDATION_EVIDENCE", "created_at", "recommendations produced"),
    ("MACRO_EVENT_EVIDENCE", "created_at", "macro events"),
    ("FUNDAMENTAL_EVIDENCE", "created_at", "fundamentals"),
)

QUESTION = (
    "You are the trading intelligence for this account. The attached inventory is a real, "
    "just-measured census of every input you have -- how many rows each feed holds, how fresh "
    "it is, how much arrived in the last 24 hours -- together with your own realised record.\n\n"
    "Answer three questions, using those numbers rather than generalities.\n\n"
    "1. INPUTS. Are you satisfied you have what you need to make good and profitable decisions "
    "on Alpaca, and on Kraken? Answer separately for each. Name any feed that is stale, thin or "
    "missing, and say what decision it would have changed.\n\n"
    "2. PROBLEMS. What is actually wrong right now? Prefer specific, checkable defects over "
    "general concerns. You previously identified duplicated attribution rows this way and you "
    "were right, so name things at that level.\n\n"
    "3. GAPS TO WORLD CLASS. What would you need to become the best trader in the world? Be "
    "concrete and ranked, and separate what would genuinely change outcomes from what would "
    "merely be nice to have.\n\n"
    "Do not pad. If an input is adequate, say so briefly and move on. If you cannot tell from "
    "the inventory, say so plainly rather than guessing: 'I cannot see X' is a useful finding, "
    "an invented reassurance is not."
)


def initialize_self_assessment_schema(db_path: Path) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(SELF_ASSESSMENT_SCHEMA)


def _scalar(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    """One value, or None if the query cannot be answered -- WITHOUT poisoning what follows.

    2026-09-06, caught on the very first real run and worth the scar tissue. Postgres aborts
    the whole transaction on any failed statement, and every later query on that connection
    then fails too until it is rolled back. The census probes eleven feeds in sequence, so a
    single bad probe did not report one missing feed -- it reported EVERY REMAINING FEED as
    missing.

    CRYPTO_MARKET_DATA has no created_at column. That one failure cascaded, and the AI was
    handed a census claiming PERFORMANCE_ATTRIBUTION, the backtests, the research evidence,
    the recommendations, macro and fundamentals were all absent. It then reasoned perfectly
    from that and concluded "the learning-loop attribution table is missing" -- about a table
    holding 27 clean rows verified an hour earlier.

    A wrong census is far worse than no census: it produces confident, specific, wrong
    findings, which is exactly what this job exists to avoid.
    """

    try:
        values = row_values(conn.execute(sql, params).fetchone())
    except Exception:  # noqa: BLE001 - an unanswerable probe is a FINDING, not a crash
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - SQLite needs no rollback here; nothing to recover
            pass
        return None
    return values[0] if values else None


def _hours_ago_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def input_inventory(db_path: Path) -> dict[str, Any]:
    """What the system actually holds right now, per feed, in numbers.

    Measured rather than described, deliberately. The AI's first answer could only say it was
    unable to assess freshness or coverage; handing it these figures is the whole difference
    between a question it can answer and one it has to duck.
    """

    feeds: list[dict[str, Any]] = []
    with closing(connect(db_path)) as conn:
        for table, column, purpose in _FEEDS:
            total = _scalar(conn, "SELECT COUNT(*) FROM " + table)
            if total is None:
                feeds.append({"feed": table, "purpose": purpose, "status": "table_missing"})
                continue
            feeds.append({
                "feed": table,
                "purpose": purpose,
                "rows_total": int(total),
                "newest_at": _scalar(conn, "SELECT MAX(" + column + ") FROM " + table),
                "rows_last_24h": _scalar(
                    conn,
                    "SELECT COUNT(*) FROM " + table + " WHERE " + column + " >= ?",
                    (_hours_ago_iso(24),),
                ),
            })

        record = {
            "closed_trades": _scalar(conn, "SELECT COUNT(*) FROM PERFORMANCE_ATTRIBUTION"),
            "distinct_trades": _scalar(
                conn, "SELECT COUNT(DISTINCT proposal_id) FROM PERFORMANCE_ATTRIBUTION"
            ),
            "wins": _scalar(
                conn, "SELECT COUNT(*) FROM PERFORMANCE_ATTRIBUTION WHERE profit_loss > 0"
            ),
            "total_pnl": _scalar(conn, "SELECT SUM(profit_loss) FROM PERFORMANCE_ATTRIBUTION"),
            "missing_exit_reason": _scalar(
                conn,
                "SELECT COUNT(*) FROM PERFORMANCE_ATTRIBUTION "
                "WHERE exit_reason IS NULL OR exit_reason = ''",
            ),
        }

    # Stated outright rather than left for the model to spot, because it is the exact defect it
    # raised on 2026-09-06 and the exact thing that would make it distrust every other number.
    closed = record.get("closed_trades")
    distinct = record.get("distinct_trades")
    record["duplicate_rows_present"] = bool(
        closed is not None and distinct is not None and int(closed) != int(distinct)
    )
    return {"generated_at": utc_now_iso(), "feeds": feeds, "realised_record": record}


def record_self_assessment(
    db_path: Path, *, answer: str | None, model: str | None, status: str, inventory: dict[str, Any]
) -> dict[str, Any]:
    initialize_self_assessment_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO AI_SELF_ASSESSMENTS (created_at, model, status, inventory_json, answer)
                VALUES (?, ?, ?, ?, ?)
                """,
                (utc_now_iso(), model, status, json.dumps(inventory, default=str), answer),
            )
    return {"status": status, "model": model, "answer": answer, "inventory": inventory}


def latest_self_assessment(db_path: Path) -> dict[str, Any] | None:
    initialize_self_assessment_schema(db_path)
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT created_at, model, status, answer
            FROM AI_SELF_ASSESSMENTS ORDER BY assessment_id DESC LIMIT 1
            """
        ).fetchone()
    if not row:
        return None
    values = row_values(row)
    if len(values) < 4:
        return None
    return {"created_at": values[0], "model": values[1], "status": values[2], "answer": values[3]}


def recent_self_assessments(db_path: Path, *, limit: int = 14) -> list[dict[str, Any]]:
    """The last fortnight or so, so a concern raised twice running is visible as a pattern
    rather than read as a one-off."""

    initialize_self_assessment_schema(db_path)
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT created_at, model, status, answer
            FROM AI_SELF_ASSESSMENTS ORDER BY assessment_id DESC LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        values = row_values(row)
        if len(values) >= 4:
            out.append(
                {"created_at": values[0], "model": values[1], "status": values[2], "answer": values[3]}
            )
    return out
