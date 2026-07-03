from __future__ import annotations

import sqlite3
from collections import Counter
from contextlib import closing
from datetime import date, datetime, time, timezone
from pathlib import Path

from .audit import AuditDatabase
from .models import utc_now_iso
from .orchestrator import ORCHESTRATOR_SCHEMA


def generate_daily_briefing(audit: AuditDatabase, briefing_date: date, output_dir: Path) -> str:
    date_text = briefing_date.isoformat()
    rows = audit.rows_for_date(date_text)
    event_counts = Counter(row["event_type"] for row in rows)
    rejected = [row for row in rows if row["event_type"] == "execution_rejected"]
    executed = [row for row in rows if row["event_type"] == "execution_approved"]
    proposed = [row for row in rows if row["event_type"] == "agent_proposal"]

    guardrail_breaches = []
    for row in rejected:
        guardrail_breaches.append(row["validation_result"] or "Rejected without validation detail")

    markdown = f"""# Daily Founder Trading Brief

Date: {date_text}

## Summary

- Trades proposed: {len(proposed)}
- Trades executed: {len(executed)}
- Trades rejected: {len(rejected)}
- Total P&L: 0.00
- Win rate: N/A
- Largest gain: N/A
- Largest loss: N/A

## Guardrail Breaches

{_list_or_none(guardrail_breaches)}

## Key Observations

- Event counts: {dict(event_counts)}
- Version 1 records proposal and execution lifecycle events for traceability.

## Lessons Learned

- Completed trade learning requires filled and closed trade outcomes.

## Recommendations For Founder Approval

- Review rejected trades before changing any guardrail.
- Keep paper trading only until several daily briefings have been reviewed.
"""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"founder_briefing_{date_text}.md"
    path.write_text(markdown, encoding="utf-8")
    audit.record_briefing(
        date_text,
        markdown,
        {
            "trades_proposed": len(proposed),
            "trades_executed": len(executed),
            "trades_rejected": len(rejected),
            "event_counts": dict(event_counts),
        },
    )
    return markdown


def _list_or_none(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)


def generate_session_brief(
    *,
    db_path: Path,
    output_dir: Path,
    brief_type: str,
    briefing_date: date,
) -> str:
    if brief_type not in {"morning", "evening"}:
        raise ValueError("brief_type must be 'morning' or 'evening'")
    period_start, period_end = _brief_period(brief_type, briefing_date)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            conn.executescript(ORCHESTRATOR_SCHEMA)
            decisions = list(
                conn.execute(
                    """
                    SELECT * FROM ORCHESTRATOR_DECISIONS
                    WHERE created_at >= ? AND created_at <= ?
                    ORDER BY decision_id ASC
                    """,
                    (period_start, period_end),
                )
            )
            events = list(
                conn.execute(
                    """
                    SELECT * FROM AUTO_TRADE_EVENTS
                    WHERE created_at >= ? AND created_at <= ?
                    ORDER BY event_id ASC
                    """,
                    (period_start, period_end),
                )
            )
    executed = [event for event in events if event["result"] == "submitted"]
    rejected = [decision for decision in decisions if decision["decision"] == "rejected"]
    markets = sorted({decision["exchange"] for decision in decisions})
    recommendations = sorted({decision["symbol"] for decision in decisions})
    title = "Morning Brief" if brief_type == "morning" else "Evening Brief"
    if brief_type == "morning":
        purpose = "Summarise overnight research and paper-trading decisions."
        intelligence = "Overnight research reviewed watchlist, themes, benchmark intelligence, and open paper positions."
    else:
        purpose = "Summarise day activity and prepare the next session."
        intelligence = "Day research reviewed watchlist, benchmark observations, theme updates, and paper-trading outcomes."
    summary = f"{len(executed)} paper trade(s) submitted and {len(rejected)} recommendation(s) rejected."
    risk_summary = _list_or_none([row["rejection_reason"] for row in rejected if row["rejection_reason"]])
    markdown = f"""# {title}

Date: {briefing_date.isoformat()}
Period: {period_start} to {period_end}

## Purpose

{purpose}

## Trading Activity

- Trades executed: {len(executed)}
- Trades rejected: {len(rejected)}
- Markets reviewed: {", ".join(markets) if markets else "Not available"}
- New recommendations: {", ".join(recommendations) if recommendations else "Not available"}

## P&L Movement

Not available from closed-trade reconciliation yet.

## Risk Status

{risk_summary}

## Intelligence Updates

{intelligence}

## Lessons Learned

Review orchestrator rejections before changing strategy, guardrails, or execution logic.
"""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{brief_type}_brief_{briefing_date.isoformat()}.md"
    path.write_text(markdown, encoding="utf-8")
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.executescript(ORCHESTRATOR_SCHEMA)
            conn.execute(
                """
                INSERT INTO DAILY_BRIEFS (
                    created_at, brief_type, period_start, period_end, summary,
                    trades_executed, trades_rejected, pnl_summary, risk_summary,
                    intelligence_summary, lessons_learned
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    brief_type,
                    period_start,
                    period_end,
                    summary,
                    len(executed),
                    len(rejected),
                    "Not available from closed-trade reconciliation yet.",
                    risk_summary,
                    intelligence,
                    "Review orchestrator rejections before changing strategy, guardrails, or execution logic.",
                ),
            )
    return markdown


def _brief_period(brief_type: str, briefing_date: date) -> tuple[str, str]:
    if brief_type == "morning":
        start_date = date.fromordinal(briefing_date.toordinal() - 1)
        start = datetime.combine(start_date, time(hour=16), tzinfo=timezone.utc)
        end = datetime.combine(briefing_date, time(hour=9), tzinfo=timezone.utc)
    else:
        start = datetime.combine(briefing_date, time(hour=9), tzinfo=timezone.utc)
        end = datetime.combine(briefing_date, time(hour=23, minute=59, second=59), tzinfo=timezone.utc)
    return start.isoformat(), end.isoformat()
