from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .models import utc_now_iso


EXPERIENCE_ENGINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS EXPERIENCE_RECORDS (
    experience_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT,
    recommendation_id TEXT,
    broker TEXT,
    symbol TEXT NOT NULL,
    asset_type TEXT,
    strategy_id TEXT,
    regime_id TEXT,
    decision_context_json TEXT NOT NULL,
    execution_context_json TEXT NOT NULL,
    result_context_json TEXT NOT NULL,
    immutable_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS POST_TRADE_REVIEWS (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    experience_id INTEGER,
    proposal_id TEXT,
    broker TEXT,
    symbol TEXT NOT NULL,
    outcome_classification TEXT NOT NULL,
    what_happened TEXT NOT NULL,
    decision_quality TEXT NOT NULL,
    execution_quality TEXT NOT NULL,
    lessons_json TEXT NOT NULL,
    questions_json TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS HISTORICAL_ANALOGUES (
    analogue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    query_json TEXT NOT NULL,
    comparable_cases INTEGER NOT NULL,
    average_r REAL,
    win_rate REAL,
    major_differences_json TEXT NOT NULL,
    confidence TEXT NOT NULL,
    result_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS LEARNING_PROPOSALS (
    proposal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_type TEXT NOT NULL,
    current_value TEXT,
    proposed_value TEXT,
    evidence_json TEXT NOT NULL,
    sample_size INTEGER NOT NULL,
    expected_impact TEXT NOT NULL,
    risks TEXT NOT NULL,
    rollback_plan TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def initialize_experience_engine_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.executescript(EXPERIENCE_ENGINE_SCHEMA)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_experience_symbol ON EXPERIENCE_RECORDS(symbol, strategy_id, regime_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_symbol ON POST_TRADE_REVIEWS(symbol, created_at)")


def record_experience(
    db_path: Path,
    *,
    symbol: str,
    proposal_id: str | None = None,
    recommendation_id: str | None = None,
    broker: str | None = None,
    asset_type: str | None = None,
    strategy_id: str | None = None,
    regime_id: str | None = None,
    decision_context: dict[str, Any],
    execution_context: dict[str, Any] | None = None,
    result_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_experience_engine_schema(db_path)
    execution_context = execution_context or {}
    result_context = result_context or {}
    immutable_payload = {
        "proposal_id": proposal_id,
        "recommendation_id": recommendation_id,
        "broker": broker,
        "symbol": symbol.upper(),
        "asset_type": asset_type,
        "strategy_id": strategy_id,
        "regime_id": regime_id,
        "decision_context": decision_context,
        "execution_context": execution_context,
        "result_context": result_context,
    }
    immutable_hash = _hash(immutable_payload)
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO EXPERIENCE_RECORDS (
                        created_at, proposal_id, recommendation_id, broker, symbol,
                        asset_type, strategy_id, regime_id, decision_context_json,
                        execution_context_json, result_context_json, immutable_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now_iso(),
                        proposal_id,
                        recommendation_id,
                        broker.lower() if broker else None,
                        symbol.upper(),
                        asset_type,
                        strategy_id,
                        regime_id,
                        json.dumps(decision_context, sort_keys=True, default=str),
                        json.dumps(execution_context, sort_keys=True, default=str),
                        json.dumps(result_context, sort_keys=True, default=str),
                        immutable_hash,
                    ),
                )
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT experience_id FROM EXPERIENCE_RECORDS WHERE immutable_hash = ?", (immutable_hash,)).fetchone()
                return {"status": "duplicate", "experience_id": row[0] if row else None, "immutable_hash": immutable_hash}
    return {"status": "recorded", "experience_id": cursor.lastrowid, "immutable_hash": immutable_hash}


def generate_post_trade_review(db_path: Path, attribution: dict[str, Any], decision_context: dict[str, Any] | None = None) -> dict[str, Any]:
    initialize_experience_engine_schema(db_path)
    decision_context = decision_context or {}
    pnl = _float(attribution.get("profit_loss")) or 0.0
    expected_r = _float(decision_context.get("expected_r") or decision_context.get("expected_return_r"))
    actual_r = _float(attribution.get("actual_r") or attribution.get("net_r"))
    good_decision = bool(decision_context.get("guardrails_passed", True)) and bool(decision_context.get("strongest_argument_for")) and bool(decision_context.get("strongest_argument_against"))
    good_outcome = pnl > 0 or (actual_r is not None and actual_r > 0)
    if good_decision and good_outcome:
        classification = "Good decision, good outcome"
    elif good_decision and not good_outcome:
        classification = "Good decision, poor outcome"
    elif not good_decision and good_outcome:
        classification = "Poor decision, good outcome"
    else:
        classification = "Poor decision, poor outcome" if decision_context else "Insufficient evidence to judge"
    lessons = [
        "Do not treat the result alone as proof of skill.",
        "Compare expected R with actual R before changing strategy.",
    ]
    if expected_r is not None and actual_r is not None:
        lessons.append(f"Expected R was {expected_r:.2f}; actual R was {actual_r:.2f}.")
    if attribution.get("fees_status") == "unavailable":
        lessons.append("Fee impact is unavailable, so net performance confidence is limited.")
    review = {
        "outcome_classification": classification,
        "what_happened": _what_happened(attribution),
        "decision_quality": "Decision evidence was complete enough to review." if decision_context else "Historical decision context is missing.",
        "execution_quality": "Execution quality is measurable when fill price, fees, and slippage are available.",
        "lessons": lessons,
        "questions": [
            "Was the selected strategy appropriate for the regime?",
            "Were fees or slippage material?",
            "Would doing nothing have been better?",
        ],
    }
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO POST_TRADE_REVIEWS (
                    created_at, experience_id, proposal_id, broker, symbol,
                    outcome_classification, what_happened, decision_quality,
                    execution_quality, lessons_json, questions_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    attribution.get("experience_id"),
                    attribution.get("proposal_id"),
                    attribution.get("broker"),
                    str(attribution.get("symbol") or "unknown").upper(),
                    review["outcome_classification"],
                    review["what_happened"],
                    review["decision_quality"],
                    review["execution_quality"],
                    json.dumps(review["lessons"], sort_keys=True),
                    json.dumps(review["questions"], sort_keys=True),
                    json.dumps({"attribution": attribution, "decision_context": decision_context}, sort_keys=True, default=str),
                ),
            )
    return {**review, "review_id": cursor.lastrowid}


def find_historical_analogues(db_path: Path, query: dict[str, Any], *, minimum_cases: int = 5) -> dict[str, Any]:
    initialize_experience_engine_schema(db_path)
    symbol = str(query.get("symbol") or "").upper()
    strategy_id = query.get("strategy_id")
    regime_id = query.get("regime_id")
    clauses = []
    params: list[Any] = []
    if strategy_id:
        clauses.append("strategy_id = ?")
        params.append(strategy_id)
    if regime_id:
        clauses.append("regime_id = ?")
        params.append(regime_id)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM EXPERIENCE_RECORDS {where} ORDER BY experience_id DESC LIMIT 50", tuple(params)).fetchall()
    cases = [dict(row) for row in rows]
    comparable = len(cases)
    confidence = "low" if comparable < minimum_cases else "medium"
    result = {
        "similar_historical_situations": cases[:10],
        "comparable_cases": comparable,
        "average_r": None,
        "win_rate": None,
        "major_differences": ["Small sample; do not treat this as reliable precedent."] if comparable < minimum_cases else [],
        "confidence": confidence,
    }
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO HISTORICAL_ANALOGUES (
                    created_at, query_json, comparable_cases, average_r, win_rate,
                    major_differences_json, confidence, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    json.dumps(query, sort_keys=True, default=str),
                    comparable,
                    result["average_r"],
                    result["win_rate"],
                    json.dumps(result["major_differences"], sort_keys=True),
                    confidence,
                    json.dumps(result, sort_keys=True, default=str),
                ),
            )
    return result


def create_learning_proposal(
    db_path: Path,
    *,
    proposal_type: str,
    current_value: Any,
    proposed_value: Any,
    evidence: dict[str, Any],
    sample_size: int,
    expected_impact: str,
    risks: str,
    rollback_plan: str,
) -> dict[str, Any]:
    initialize_experience_engine_schema(db_path)
    status = "Suggested"
    if sample_size < 30:
        risks = f"{risks} Minimum sample gate not met; proposal must remain research-only."
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO LEARNING_PROPOSALS (
                    created_at, proposal_type, current_value, proposed_value,
                    evidence_json, sample_size, expected_impact, risks,
                    rollback_plan, approval_status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    proposal_type,
                    str(current_value),
                    str(proposed_value),
                    json.dumps(evidence, sort_keys=True, default=str),
                    sample_size,
                    expected_impact,
                    risks,
                    rollback_plan,
                    status,
                    json.dumps({"no_silent_production_change": True}, sort_keys=True),
                ),
            )
    return {"proposal_id": cursor.lastrowid, "approval_status": status, "sample_size": sample_size}


def _what_happened(attribution: dict[str, Any]) -> str:
    symbol = attribution.get("symbol") or "unknown"
    pnl = _float(attribution.get("profit_loss"))
    if pnl is None:
        return f"{symbol} closed, but realised profit/loss is unavailable."
    return f"{symbol} closed with profit/loss of {pnl:.2f}."


def _float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _hash(payload: dict[str, Any]) -> str:
    import hashlib

    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
