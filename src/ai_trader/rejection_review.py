from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .broker_adapters import _kraken_pair
from .database import connect
from .experience_engine import record_experience
from .models import utc_now_iso
from .operational import safe_float

REJECTION_REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS CRYPTO_REJECTION_REVIEWS (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    review_date TEXT NOT NULL,
    broker TEXT NOT NULL,
    symbol TEXT NOT NULL,
    rejection_count INTEGER NOT NULL,
    dominant_reason TEXT,
    reference_price REAL,
    reference_at TEXT,
    price_now REAL,
    priced_at TEXT,
    pct_change REAL,
    verdict TEXT NOT NULL,
    UNIQUE(review_date, broker, symbol)
);

CREATE TABLE IF NOT EXISTS CRYPTO_REJECTION_REVIEW_SUMMARIES (
    summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    period TEXT NOT NULL,
    broker TEXT NOT NULL,
    symbol TEXT NOT NULL,
    days_reviewed INTEGER NOT NULL,
    favourable_count INTEGER NOT NULL,
    unfavourable_count INTEGER NOT NULL,
    neutral_count INTEGER NOT NULL,
    avg_pct_change REAL,
    note TEXT NOT NULL,
    UNIQUE(period, broker, symbol)
);
"""

# A rejected buy is judged "favourable" if price fell afterward (not buying was the
# right call) and "unfavourable" if it rose (not buying missed a gain). This is
# deliberately a single, honest, generic threshold -- not a per-gate scoring model --
# because the point is a lightweight sanity check across many small samples, not a
# statistically rigorous verdict on any one rejection.
_FAVOURABLE_THRESHOLD_PCT = -0.01
_UNFAVOURABLE_THRESHOLD_PCT = 0.01

# How long to wait before judging a rejection, and how far back to look. A rejection
# needs at least a day to have a real "what happened next" answer; the window's upper
# bound stops the job from re-scanning the same old rows forever.
_REVIEW_LOOKBACK_START_HOURS = 48
_REVIEW_LOOKBACK_END_HOURS = 24

# Raw per-day rows older than this are rolled into CRYPTO_REJECTION_REVIEW_SUMMARIES
# and deleted -- keeps the detailed table's size bounded to roughly a month's worth
# of rows (~9 crypto symbols/day) no matter how long the app has been running, per
# the Founder's explicit ask that this not grow without bound.
_ROLLUP_CUTOFF_DAYS = 35


def initialize_rejection_review_schema(db_path: Path) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(REJECTION_REVIEW_SCHEMA)


def _price_for_pair(prices: dict[str, Any], pair: str) -> float | None:
    # Deliberately does NOT fall back to "any price in the dict" the way
    # broker_adapters.py's _kraken_last_price does for its single-pair callers --
    # that fallback would be a real correctness bug here, silently attributing a
    # different symbol's price to a pair that's missing from a multi-symbol batch
    # response (e.g. a pair Kraken didn't return this cycle).
    payload = prices.get(pair) if isinstance(prices, dict) else None
    if not isinstance(payload, dict):
        return None
    last = payload.get("c")
    if isinstance(last, list) and last:
        return safe_float(last[0])
    return safe_float(last)


def _verdict_for(pct_change: float | None) -> str:
    if pct_change is None:
        return "unknown"
    if pct_change <= _FAVOURABLE_THRESHOLD_PCT:
        return "favourable"
    if pct_change >= _UNFAVOURABLE_THRESHOLD_PCT:
        return "unfavourable"
    return "neutral"


def run_crypto_rejection_review(db_path: Path, adapter: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Nightly job: for every Kraken crypto symbol that was rejected by the
    guardrail check (trade_audit event_type='agent_proposal',
    execution_guardrails_passed=0) 24-48h ago, check what price actually did since
    and record one compact verdict per symbol per day.

    Deliberately scoped to the guardrail-check rejections (a fully priced proposal
    that reached validate_trade_proposal and failed) rather than the earlier entry
    gates (entry_too_extended/btc_weak_regime/recently_stopped_out, which `continue`
    before a Proposal with an entry price is ever built and recorded as
    'agent_no_trade' -- see agent.py's propose_crypto_trades). Those gates are
    already understood and working as intended; this job exists to answer the open
    question of whether the *other* rejections (Founder's "is BTC/XLM stuck a bug or
    correct caution?" question, 2026-08-16) are reasonable.

    Also writes one EXPERIENCE_RECORDS row per reviewed symbol (via the existing
    record_experience/find_historical_analogues machinery already wired into every
    crypto proposal's reasoning text through build_proposal_context) -- no new
    plumbing needed for a future proposal on the same symbol to see "the last time
    this was rejected, price did X afterward" as part of its own context.
    """
    initialize_rejection_review_schema(db_path)
    now = now or datetime.now(timezone.utc)
    window_end = now - timedelta(hours=_REVIEW_LOOKBACK_END_HOURS)
    window_start = now - timedelta(hours=_REVIEW_LOOKBACK_START_HOURS)
    review_date = window_start.date().isoformat()

    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT symbol, entry, created_at, validation_result
            FROM trade_audit
            WHERE event_type = 'agent_proposal' AND broker = 'kraken'
              AND execution_guardrails_passed = 0
              AND created_at >= ? AND created_at < ?
            ORDER BY symbol, created_at ASC
            """,
            (window_start.isoformat(), window_end.isoformat()),
        ).fetchall()
    if not rows:
        return {"status": "no_action", "message": "No rejected Kraken proposals in the review window.", "symbols_reviewed": 0}

    by_symbol: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_symbol.setdefault(str(row["symbol"]).upper(), []).append(row)

    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        already_reviewed = {
            str(r["symbol"]).upper()
            for r in conn.execute(
                "SELECT symbol FROM CRYPTO_REJECTION_REVIEWS WHERE review_date = ? AND broker = 'kraken'",
                (review_date,),
            ).fetchall()
        }
    pending_symbols = [symbol for symbol in by_symbol if symbol not in already_reviewed]
    if not pending_symbols:
        return {"status": "no_action", "message": f"Already reviewed for {review_date}.", "symbols_reviewed": 0}

    pairs = [_kraken_pair(symbol) for symbol in pending_symbols]
    try:
        prices = adapter.current_prices(pairs) if hasattr(adapter, "current_prices") else {}
    except Exception:  # noqa: BLE001 - a failed price lookup must never abort the review job
        prices = {}
    priced_at = utc_now_iso()

    reviewed: list[dict[str, Any]] = []
    for symbol in pending_symbols:
        group = by_symbol[symbol]
        first = group[0]
        reference_price = safe_float(first["entry"])
        price_now = _price_for_pair(prices, _kraken_pair(symbol))

        reason_counts: dict[str, int] = {}
        for record in group:
            try:
                failures = json.loads(record["validation_result"] or "{}").get("failures") or []
            except (TypeError, ValueError):
                failures = []
            for failure in failures:
                reason_counts[failure] = reason_counts.get(failure, 0) + 1
        dominant_reason = max(reason_counts, key=reason_counts.get) if reason_counts else None

        pct_change = None
        if reference_price and price_now and reference_price > 0:
            pct_change = (price_now - reference_price) / reference_price
        verdict = _verdict_for(pct_change)

        with closing(connect(db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO CRYPTO_REJECTION_REVIEWS (
                        created_at, review_date, broker, symbol, rejection_count,
                        dominant_reason, reference_price, reference_at, price_now,
                        priced_at, pct_change, verdict
                    ) VALUES (?, ?, 'kraken', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(review_date, broker, symbol) DO NOTHING
                    """,
                    (
                        utc_now_iso(),
                        review_date,
                        symbol,
                        len(group),
                        dominant_reason,
                        reference_price,
                        first["created_at"],
                        price_now,
                        priced_at,
                        pct_change,
                        verdict,
                    ),
                )

        if pct_change is not None:
            record_experience(
                db_path,
                symbol=symbol,
                broker="kraken",
                asset_type="crypto",
                strategy_id="crypto_rejection_review",
                decision_context={
                    "record_type": "rejection_review",
                    "review_date": review_date,
                    "rejection_count": len(group),
                    "dominant_reason": dominant_reason,
                    "reference_price": reference_price,
                },
                result_context={"outcome": f"reject_{verdict}({pct_change:+.1%})", "pnl": None},
            )

        reviewed.append({"symbol": symbol, "verdict": verdict, "pct_change": pct_change, "dominant_reason": dominant_reason})

    return {"status": "completed", "review_date": review_date, "symbols_reviewed": len(reviewed), "reviews": reviewed}


def run_crypto_rejection_rollup(db_path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Monthly job: summarize CRYPTO_REJECTION_REVIEWS rows older than
    _ROLLUP_CUTOFF_DAYS into one compact per-(period, broker, symbol) row, then
    delete the raw rows that fed it. Keeps the detailed table's size bounded
    regardless of how long the app has been running; the summary table itself grows
    by only a handful of rows a month, forever."""
    initialize_rejection_review_schema(db_path)
    now = now or datetime.now(timezone.utc)
    cutoff_date = (now - timedelta(days=_ROLLUP_CUTOFF_DAYS)).date().isoformat()

    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM CRYPTO_REJECTION_REVIEWS WHERE review_date < ?",
            (cutoff_date,),
        ).fetchall()
    if not rows:
        return {"status": "no_action", "message": "Nothing old enough to roll up yet.", "rows_summarized": 0}

    groups: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
    for row in rows:
        period = str(row["review_date"])[:7]
        key = (period, str(row["broker"]), str(row["symbol"]))
        groups.setdefault(key, []).append(row)

    for (period, broker, symbol), items in groups.items():
        counts = {"favourable": 0, "unfavourable": 0, "neutral": 0, "unknown": 0}
        pct_changes: list[float] = []
        for item in items:
            counts[item["verdict"] or "unknown"] = counts.get(item["verdict"] or "unknown", 0) + 1
            if item["pct_change"] is not None:
                pct_changes.append(float(item["pct_change"]))
        avg_pct_change = sum(pct_changes) / len(pct_changes) if pct_changes else None
        note = (
            f"{len(items)} review day(s) in {period}: {counts['favourable']} favourable, "
            f"{counts['unfavourable']} unfavourable, {counts['neutral']} neutral rejection(s)."
        )
        with closing(connect(db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO CRYPTO_REJECTION_REVIEW_SUMMARIES (
                        created_at, period, broker, symbol, days_reviewed,
                        favourable_count, unfavourable_count, neutral_count, avg_pct_change, note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(period, broker, symbol) DO UPDATE SET
                        days_reviewed = excluded.days_reviewed,
                        favourable_count = excluded.favourable_count,
                        unfavourable_count = excluded.unfavourable_count,
                        neutral_count = excluded.neutral_count,
                        avg_pct_change = excluded.avg_pct_change,
                        note = excluded.note
                    """,
                    (
                        utc_now_iso(),
                        period,
                        broker,
                        symbol,
                        len(items),
                        counts["favourable"],
                        counts["unfavourable"],
                        counts["neutral"],
                        avg_pct_change,
                        note,
                    ),
                )

    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute("DELETE FROM CRYPTO_REJECTION_REVIEWS WHERE review_date < ?", (cutoff_date,))

    return {"status": "completed", "rows_summarized": len(rows), "symbol_periods_summarized": len(groups)}
