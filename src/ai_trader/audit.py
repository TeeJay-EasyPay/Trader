from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .models import TradeProposal, ValidationResult, utc_now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    symbol TEXT,
    side TEXT,
    entry REAL,
    exit REAL,
    profit_loss REAL,
    ai_reasoning TEXT,
    news_summary TEXT,
    sentiment_summary TEXT,
    technical_summary TEXT,
    ai_confidence REAL,
    ai_guardrails_passed INTEGER,
    execution_guardrails_passed INTEGER,
    position_size REAL,
    stop_loss REAL,
    take_profit REAL,
    validation_result TEXT,
    execution_result TEXT,
    trade_outcome TEXT,
    lessons_learned TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_briefings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    briefing_date TEXT NOT NULL,
    report_markdown TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


class AuditDatabase:
    def __init__(self, path: Path, trading_log_path: Path | None = None):
        self.path = path
        self.trading_log_path = trading_log_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with closing(self.connect()) as conn:
            with conn:
                conn.executescript(SCHEMA)

    def record_trade_event(
        self,
        event_type: str,
        proposal: TradeProposal,
        *,
        validation: ValidationResult | None = None,
        execution_result: dict[str, Any] | None = None,
        trade_outcome: str | None = None,
        lessons_learned: str | None = None,
    ) -> int:
        payload = {
            "proposal": proposal.to_dict(),
            "validation": validation.to_dict() if validation else None,
            "execution_result": execution_result,
        }
        created_at = utc_now_iso()
        with closing(self.connect()) as conn:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO trade_audit (
                        created_at, proposal_id, event_type, symbol, side, entry, exit,
                        profit_loss, ai_reasoning, news_summary, sentiment_summary,
                        technical_summary, ai_confidence, ai_guardrails_passed,
                        execution_guardrails_passed, position_size, stop_loss, take_profit,
                        validation_result, execution_result, trade_outcome, lessons_learned,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        created_at,
                        proposal.proposal_id,
                        event_type,
                        proposal.symbol,
                        proposal.side,
                        proposal.entry_price,
                        None,
                        None,
                        proposal.plain_english_reasoning,
                        proposal.news_summary,
                        proposal.market_sentiment_summary,
                        proposal.technical_summary,
                        proposal.confidence_score,
                        int(proposal.ai_guardrails_passed),
                        None if validation is None else int(validation.passed),
                        proposal.position_size,
                        proposal.stop_loss,
                        proposal.take_profit,
                        json.dumps(validation.to_dict() if validation else None, sort_keys=True),
                        json.dumps(execution_result, sort_keys=True),
                        trade_outcome,
                        lessons_learned,
                        json.dumps(payload, sort_keys=True),
                    ),
                )
                row_id = int(cur.lastrowid)
        self.append_trading_log(
            created_at=created_at,
            event_type=event_type,
            proposal=proposal,
            validation=validation,
            execution_result=execution_result,
            trade_outcome=trade_outcome,
            lessons_learned=lessons_learned,
        )
        return row_id

    def append_trading_log(
        self,
        *,
        created_at: str,
        event_type: str,
        proposal: TradeProposal,
        validation: ValidationResult | None,
        execution_result: dict[str, Any] | None,
        trade_outcome: str | None,
        lessons_learned: str | None,
    ) -> None:
        if self.trading_log_path is None:
            return
        self.trading_log_path.parent.mkdir(parents=True, exist_ok=True)
        validation_text = "not_checked"
        if validation is not None:
            validation_text = "passed" if validation.passed else f"failed: {', '.join(validation.failures)}"
        execution_text = "not_submitted"
        if execution_result:
            execution_text = str(execution_result.get("status", "recorded"))
        entry = f"""
## {created_at} - {event_type}

- Proposal ID: {proposal.proposal_id}
- Symbol: {proposal.symbol}
- Side: {proposal.side}
- Entry: {proposal.entry_price}
- Position size: {proposal.position_size}
- Stop loss: {proposal.stop_loss}
- Take profit: {proposal.take_profit}
- Risk percentage: {proposal.risk_percentage}
- AI confidence: {proposal.confidence_score}
- AI guardrails passed: {proposal.ai_guardrails_passed}
- Execution validation: {validation_text}
- Execution result: {execution_text}
- Trade outcome: {trade_outcome or "pending"}
- News summary: {proposal.news_summary}
- Sentiment summary: {proposal.market_sentiment_summary}
- Technical summary: {proposal.technical_summary}
- AI reasoning: {proposal.plain_english_reasoning}
- Lessons learned: {lessons_learned or "pending"}
"""
        with self.trading_log_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)

    def record_execution_event(self, proposal_id: str, event_type: str, payload: dict[str, Any]) -> int:
        with closing(self.connect()) as conn:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO execution_events (created_at, proposal_id, event_type, payload_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (utc_now_iso(), proposal_id, event_type, json.dumps(payload, sort_keys=True)),
                )
                return int(cur.lastrowid)

    def record_briefing(self, briefing_date: str, markdown: str, payload: dict[str, Any]) -> int:
        with closing(self.connect()) as conn:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO daily_briefings (created_at, briefing_date, report_markdown, payload_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (utc_now_iso(), briefing_date, markdown, json.dumps(payload, sort_keys=True)),
                )
                return int(cur.lastrowid)

    def rows_for_date(self, date_prefix: str) -> list[sqlite3.Row]:
        with closing(self.connect()) as conn:
            with conn:
                return list(
                    conn.execute(
                        "SELECT * FROM trade_audit WHERE created_at LIKE ? ORDER BY id ASC",
                        (f"{date_prefix}%",),
                    )
                )
