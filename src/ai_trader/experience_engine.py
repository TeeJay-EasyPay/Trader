from __future__ import annotations

import json
import sqlite3
from .database import connect
from contextlib import closing
from pathlib import Path
from typing import Any

from .models import utc_now_iso
from .persistence.schema_once import ensure_schema_once


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
    asset_type TEXT,
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
    """Create schema once per process.

    record_experience, generate_post_trade_review, find_historical_analogues, and
    create_learning_proposal are all called once per workflow inside
    production_spine.run_closed_loop_learning, which sprint6.process_learning_outbox
    loops over up to 10 times per call -- same hot-path repetition risk already fixed
    for operational_truth and portfolio_intelligence.
    """

    def _init() -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(db_path)) as conn:
            with conn:
                conn.executescript(EXPERIENCE_ENGINE_SCHEMA)
                # 2026-08-22: added after LEARNING_PROPOSALS already existed in production,
                # so it must be an ensure-column migration, not just a schema edit -- a
                # CREATE TABLE IF NOT EXISTS never alters a table that is already there.
                existing = {row[1] for row in conn.execute("PRAGMA table_info(LEARNING_PROPOSALS)")}
                if "asset_type" not in existing:
                    conn.execute("ALTER TABLE LEARNING_PROPOSALS ADD COLUMN asset_type TEXT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_experience_symbol ON EXPERIENCE_RECORDS(symbol, strategy_id, regime_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_symbol ON POST_TRADE_REVIEWS(symbol, created_at)")

    ensure_schema_once(db_path, "experience_engine", _init)


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
    with closing(connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO EXPERIENCE_RECORDS (
                    created_at, proposal_id, recommendation_id, broker, symbol,
                    asset_type, strategy_id, regime_id, decision_context_json,
                    execution_context_json, result_context_json, immutable_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(immutable_hash) DO NOTHING
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
            status = 'recorded' if cursor.rowcount else 'duplicate'
            # INSERT ... ON CONFLICT has no portable lastrowid on PostgreSQL.
            # The immutable unique key identifies both new and existing records.
            row = conn.execute("SELECT experience_id FROM EXPERIENCE_RECORDS WHERE immutable_hash = ?", (immutable_hash,)).fetchone()
            if row is None:
                raise RuntimeError('Experience insert did not resolve its immutable key')
            experience_id = row[0]
    return {"status": status, "experience_id": experience_id, "immutable_hash": immutable_hash}


def classify_trade_review(attribution: dict[str, Any], decision_context: dict[str, Any]) -> dict[str, Any]:
    """Separate evidence completeness, decision process and net outcome; never guess costs."""
    intelligence = decision_context.get("intelligence") or {}
    committee = intelligence.get("committee") if isinstance(intelligence, dict) else None
    committee = committee if isinstance(committee, dict) else {}
    stored_guardrails = decision_context.get("guardrails") or {}
    guardrails = decision_context.get("guardrails_passed", stored_guardrails.get("passed") if isinstance(stored_guardrails, dict) else None)
    arguments_complete = all(
        isinstance(decision_context.get(key) or committee.get(key), str) and (decision_context.get(key) or committee.get(key)).strip()
        for key in ("strongest_argument_for", "strongest_argument_against")
    )
    decision = "poor" if guardrails is False else "good" if guardrails is True and arguments_complete else "unknown"
    net_pnl = _float(attribution.get("net_realized_pnl"))
    net_r = _float(attribution.get("net_r"))
    fees_unknown = attribution.get("fees_status") in {"unavailable", "unknown", "estimated"}
    result = None if fees_unknown else net_pnl if net_pnl is not None else net_r
    outcome = "unknown" if result is None else "good" if result > 0 else "poor" if result < 0 else "breakeven"
    classification = (
        f"{decision.title()} decision, {outcome} outcome"
        if decision != "unknown" and outcome in {"good", "poor"}
        else "Insufficient evidence to judge" if decision == "unknown" or outcome == "unknown"
        else f"{decision.title()} decision, breakeven outcome"
    )
    return {"outcome_classification": classification, "decision_assessment": decision,
            "net_outcome_assessment": outcome, "classification_version": "net-evidence-v2"}


def generate_post_trade_review(db_path: Path, attribution: dict[str, Any], decision_context: dict[str, Any] | None = None) -> dict[str, Any]:
    initialize_experience_engine_schema(db_path)
    decision_context = decision_context or {}
    expected_r = _float(decision_context.get("expected_r") or decision_context.get("expected_return_r"))
    actual_r = _float(attribution.get("net_r"))
    assessment = classify_trade_review(attribution, decision_context)
    lessons = [
        "Do not treat the result alone as proof of skill.",
        "Compare expected R with actual R before changing strategy.",
    ]
    if expected_r is not None and actual_r is not None:
        lessons.append(f"Expected R was {expected_r:.2f}; actual R was {actual_r:.2f}.")
    if attribution.get("fees_status") == "unavailable":
        lessons.append("Fee impact is unavailable, so net performance confidence is limited.")
    review = {
        **assessment,
        "what_happened": _what_happened(attribution),
        "decision_quality": "Decision evidence is insufficient to judge quality." if assessment["decision_assessment"] == "unknown" else "Recorded decision-process evidence assessed separately from its outcome.",
        "execution_quality": "Execution quality is measurable when fill price, fees, and slippage are available.",
        "lessons": lessons,
        "questions": [
            "Was the selected strategy appropriate for the regime?",
            "Were fees or slippage material?",
            "Would doing nothing have been better?",
        ],
    }
    with closing(connect(db_path)) as conn:
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
                    json.dumps({"attribution": attribution, "decision_context": decision_context, "assessment": assessment}, sort_keys=True, default=str),
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
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM EXPERIENCE_RECORDS {where} ORDER BY experience_id DESC LIMIT 50", tuple(params)).fetchall()
    # Reporting-only outcomes lack the decision evidence required for precedent.
    cases = [dict(row) for row in rows
             if json.loads(row["result_context_json"] or "{}").get("record_kind") != "outcome_only"]
    # A reporting review and its later canonical repair are not two independent
    # trades. Prefer canonical evidence for the same broker/decision identity.
    canonical_keys = {(c.get('broker'), c.get('proposal_id')) for c in cases
        if c.get('proposal_id') and json.loads(c['result_context_json']).get('canonical_closure_verified')}
    cases = [c for c in cases if not (json.loads(c['result_context_json']).get('record_kind') == 'reconciled_reporting_review'
             and (c.get('broker'), c.get('proposal_id')) in canonical_keys)]
    ids = {str(json.loads(c['result_context_json']).get('source_attribution_id')) for c in cases if c.get('broker') == 'alpaca'} - {'None'}
    if ids:
        # Append newly recovered order evidence without altering immutable experiences.
        try:
            with closing(connect(db_path)) as conn:
                updates = conn.execute('SELECT attribution_id,exit_reason FROM PERFORMANCE_ATTRIBUTION WHERE broker=? AND attribution_id IN ('
                    + ','.join('?' for _ in ids) + ')', ('alpaca', *sorted(ids))).fetchall()
            by_id = {str(r[0]): r[1] for r in updates}
            for case in cases:
                source = str(json.loads(case['result_context_json']).get('source_attribution_id'))
                if case.get('broker') == 'alpaca' and source in by_id:
                    case['latest_recorded_exit_reason'] = by_id[source]
                    case['exit_evidence_source'] = 'PERFORMANCE_ATTRIBUTION:' + source
        except Exception:
            # Explicitly retain the original evidence, never invent an update.
            for case in cases:
                case['exit_evidence_refresh_status'] = 'unavailable'
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
    with closing(connect(db_path)) as conn:
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
    asset_type: str | None = None,
) -> dict[str, Any]:
    """asset_type scopes a proposal to one learning track (Founder-directed 2026-08-22).

    Crypto (Kraken) and equities (Alpaca) learn separately -- Alpaca builds equities
    competence for future Asia/Middle East/Africa exchanges and will run leverage that
    crypto does not, so a lesson drawn from one must not silently rewrite policy for the
    other. None means genuinely cross-cutting, not "unknown".
    """
    initialize_experience_engine_schema(db_path)
    status = "Suggested"
    if sample_size < 30:
        risks = f"{risks} Minimum sample gate not met; proposal must remain research-only."
    with closing(connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO LEARNING_PROPOSALS (
                    created_at, proposal_type, asset_type, current_value, proposed_value,
                    evidence_json, sample_size, expected_impact, risks,
                    rollback_plan, approval_status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    proposal_type,
                    asset_type,
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
    gross = _float(attribution.get("gross_realized_pnl"))
    net = _float(attribution.get("net_realized_pnl"))
    if attribution.get("fees_status") in {"unknown", "unavailable", "estimated"}:
        net = None
    gross_text = 'unavailable' if gross is None else f'{gross:.2f}'
    net_text = 'unavailable' if net is None else f'{net:.2f}'
    return f"{symbol} closed; before-fee result {gross_text}; net after recorded fees {net_text}."


def _float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        import math
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _hash(payload: dict[str, Any]) -> str:
    import hashlib

    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
