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

# Every feed, the column that dates a row, what it is for, and -- decisively -- WHETHER A
# TRADING DECISION ACTUALLY READS IT.
#
# 2026-09-06: that last field exists because of what the first honest census produced. Three
# of the AI's four "what is actually wrong" findings were artefacts of THIS LIST rather than
# defects in the system:
#
#   * It reported that decisions might be using six-day-old crypto prices. Nothing anywhere
#     SELECTs from CRYPTO_MARKET_DATA. Every crypto entry calls adapter.current_prices() for a
#     live Kraken Ticker read at the moment it decides. The table is genuinely stale and it
#     prices nothing -- but the census described it as "crypto prices and ranges", so the only
#     reasonable inference was the wrong one.
#   * It reported no Alpaca quote/bar or execution feed. MARKET_DATA_OBSERVATIONS,
#     PRODUCTION_BROKER_SNAPSHOTS and BROKER_TRADE_HISTORY all exist and hold thousands of
#     rows. The census simply did not list them.
#   * It reported that realised P&L lacked broker attribution. PERFORMANCE_ATTRIBUTION.broker
#     exists and is populated; the census summed across brokers and threw the split away, and
#     the AI then rightly refused to state a combined figure.
#
# It hedged every one of them -- "I cannot tell whether those inputs are absent from the system
# or simply absent from the census" -- and it was right to. A wrong census produces confident,
# specific, wrong findings, which is the exact opposite of this job's purpose. So: list what
# exists, and say plainly whether a decision depends on it, because "stale" means everything
# for an input a trade reads and nothing for one nothing consumes.
_FEEDS: tuple[tuple[str, str, str, bool], ...] = (
    ("CRYPTO_NEWS", "created_at", "coin news used to judge a crypto entry", True),
    ("NEWS_CATALYST_EVIDENCE", "created_at", "news catalysts attached to a symbol", True),
    ("MARKET_REGIME_EVIDENCE", "created_at", "market regime an entry is judged against", True),
    ("CRYPTO_SENTIMENT_SCORES", "created_at", "per-coin behavioural score", True),
    # observed_at, not created_at. Getting this wrong is what cascaded on the first real
    # run -- see _scalar. test_every_feed_column_exists is the guard against it drifting again.
    ("CRYPTO_MARKET_DATA", "observed_at",
     "CoinGecko market-cap universe snapshot. NOT a decision input: nothing reads this table, "
     "and crypto entries price from a live Kraken Ticker call instead", False),
    # observation_time, not observed_at -- caught by test_every_feed_column_exists before
    # this ever reached production, which is the second time that guard has paid for itself.
    ("MARKET_DATA_OBSERVATIONS", "observation_time", "stored candles/observations behind indicators", True),
    ("BROKER_TRADE_HISTORY", "updated_at", "real broker orders and fills, both brokers", True),
    ("PRODUCTION_BROKER_SNAPSHOTS", "captured_at", "account state: cash, positions, buying power", True),
    ("LOGICAL_TRADES", "updated_at", "the canonical trade record, entries through exits", True),
    ("EXECUTION_EVENTS", "created_at",
     "why each candidate was dropped -- the agent_no_trade reasons", True),
    ("RESEARCH_FUNNELS", "created_at", "per-cycle funnel from symbols examined to proposals", True),
    ("PERFORMANCE_ATTRIBUTION", "closed_at", "completed trades the learning loop reads", True),
    ("SHADOW_TRADES", "created_at",
     "simulated candidates settled against real candles -- the out-of-sample record", True),
    ("STRATEGY_BACKTEST_RESULTS", "created_at", "backtest evidence behind a strategy", True),
    ("PRODUCTION_RESEARCH_EVIDENCE", "completed_at", "research runs", True),
    ("PRODUCTION_RECOMMENDATION_EVIDENCE", "created_at", "recommendations produced", True),
    ("MACRO_EVENT_EVIDENCE", "created_at", "macro events", True),
    ("FUNDAMENTAL_EVIDENCE", "created_at", "fundamentals", True),
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
        for table, column, purpose, decision_input in _FEEDS:
            total = _scalar(conn, "SELECT COUNT(*) FROM " + table)
            if total is None:
                feeds.append({
                    "feed": table, "purpose": purpose,
                    "read_by_a_trading_decision": decision_input, "status": "table_missing",
                })
                continue
            feeds.append({
                "feed": table,
                "purpose": purpose,
                # Says outright whether staleness here can change a trade. Without it the only
                # reasonable inference from "six days old" is that decisions are using six-day
                # -old data, which is what happened on 2026-09-06 and was wrong.
                "read_by_a_trading_decision": decision_input,
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
    return {
        "generated_at": utc_now_iso(),
        "feeds": feeds,
        "realised_record": record,
        "realised_record_by_broker": _record_by_broker(db_path),
        "how_a_decision_is_priced": _PRICING_NOTE,
    }


# 2026-09-06: the AI refused to state a combined P&L -- "I cannot responsibly label it pounds
# or dollars, or use it as a combined account result" -- and it was exactly right to. Alpaca
# trades in dollars and Kraken in pounds, so a single summed figure is not a number at all.
#
# The irony is that PERFORMANCE_ATTRIBUTION.broker exists and is populated. The census was
# summing across brokers and discarding the split, then presenting the meaningless total. The
# system knew; the census hid it.
def _record_by_broker(db_path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute(
                """
                SELECT broker, COUNT(*) AS trades,
                       SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) AS wins,
                       SUM(profit_loss) AS net
                FROM PERFORMANCE_ATTRIBUTION GROUP BY broker
                """
            ).fetchall()
    except Exception:  # noqa: BLE001 - a census gap is a finding, not a crash
        return out
    for row in rows:
        values = row_values(row)
        if len(values) < 4:
            continue
        broker = str(values[0] or "unknown")
        out.append({
            "broker": broker,
            # Named per broker rather than left to be inferred. Kraken is a GBP account and
            # Alpaca a USD paper account, and the AI cannot know that from a number.
            "currency": "GBP" if broker.lower() == "kraken" else "USD",
            "closed_trades": values[1],
            "wins": values[2],
            "net_pnl": values[3],
        })
    return out


_PRICING_NOTE = (
    "A crypto entry is priced from a LIVE Kraken Ticker call made at the moment of the "
    "decision (adapter.current_prices), not from any stored table. CRYPTO_MARKET_DATA is a "
    "CoinGecko universe snapshot that nothing reads. So its age does not affect entry prices "
    "or stop placement, and staleness there is a housekeeping problem rather than a trading "
    "one. Equity decisions read stored observations, where age does matter."
)


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
