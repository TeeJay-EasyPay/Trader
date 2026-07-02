from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

from .audit import AuditDatabase


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

