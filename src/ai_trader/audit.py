from __future__ import annotations

import json
import sqlite3
from .database import connect
from contextlib import closing
from pathlib import Path
from typing import Any

from .models import TradeProposal, ValidationResult, utc_now_iso


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _broker_for_proposal(proposal: TradeProposal) -> str:
    # Matches orchestrator.py's real _select_adapter resolution (proposal.asset_type in
    # adapter.get_supported_assets()) for the only two configured adapters: Kraken handles
    # crypto, Alpaca handles everything else. If a third broker/asset type is ever added, this
    # must be revisited alongside _select_adapter itself.
    return "kraken" if proposal.asset_type == "crypto" else "alpaca"


SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    symbol TEXT,
    broker TEXT,
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
    def __init__(
        self,
        path: Path,
        trading_log_path: Path | None = None,
        *,
        initialize_schema: bool = True,
    ):
        self.path = path
        self.trading_log_path = trading_log_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if initialize_schema:
            self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with closing(self.connect()) as conn:
            with conn:
                conn.executescript(SCHEMA)
                _ensure_column(conn, "trade_audit", "broker", "TEXT")
        self._backfill_missing_broker()

    def _backfill_missing_broker(self) -> None:
        # 2026-08-10 hosted incident: auto_execute_recommendations_alpaca/_kraken share one
        # candidate query with no way to filter by broker in SQL (this column did not exist),
        # and Kraken's much higher candidate-generation frequency completely crowded Alpaca
        # out of the shared LIMIT-50 window -- confirmed via live evidence (the 50 most recent
        # trade_audit proposals were 100% Kraken), meaning Alpaca's auto-execution job silently
        # evaluated nothing at all, every cycle, for as long as this had been true. One-time,
        # cheap backfill (trade_audit is a few thousand rows) for rows written before this
        # column existed; every new row gets broker set directly by record_trade_event going
        # forward. Derived from the proposal's own asset_type, matching orchestrator.py's real
        # _select_adapter resolution (the only two configured adapters are Kraken for crypto
        # and Alpaca for everything else).
        with closing(self.connect()) as conn:
            with conn:
                rows = conn.execute("SELECT id, payload_json FROM trade_audit WHERE broker IS NULL").fetchall()
                for row in rows:
                    try:
                        payload = json.loads(row["payload_json"])
                        asset_type = str((payload.get("proposal") or {}).get("asset_type") or "").lower()
                    except (TypeError, ValueError, json.JSONDecodeError):
                        asset_type = ""
                    broker = "kraken" if asset_type == "crypto" else "alpaca"
                    conn.execute("UPDATE trade_audit SET broker = ? WHERE id = ?", (broker, row["id"]))

    def record_trade_event(
        self,
        event_type: str,
        proposal: TradeProposal,
        *,
        validation: ValidationResult | None = None,
        execution_result: dict[str, Any] | None = None,
        trade_outcome: str | None = None,
        lessons_learned: str | None = None,
        intelligence: dict[str, Any] | None = None,
    ) -> int:
        payload = {
            "proposal": proposal.to_dict(),
            "validation": validation.to_dict() if validation else None,
            "execution_result": execution_result,
            "intelligence": intelligence,
        }
        created_at = utc_now_iso()
        with closing(self.connect()) as conn:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO trade_audit (
                        created_at, proposal_id, event_type, symbol, broker, side, entry, exit,
                        profit_loss, ai_reasoning, news_summary, sentiment_summary,
                        technical_summary, ai_confidence, ai_guardrails_passed,
                        execution_guardrails_passed, position_size, stop_loss, take_profit,
                        validation_result, execution_result, trade_outcome, lessons_learned,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        created_at,
                        proposal.proposal_id,
                        event_type,
                        proposal.symbol,
                        _broker_for_proposal(proposal),
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
