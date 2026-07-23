from __future__ import annotations

import hashlib
import json
import sqlite3
from .database import connect
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .always_on import uses_postgres
from .canonical_trades import reconcile_canonical_broker_event
from .guardrails import validate_trade_proposal
from .models import AccountContext, GuardrailConfig, TradeProposal, utc_now_iso
from .operational import safe_float
from .production_spine import (
    complete_insufficient_evidence_learning,
    portfolio_manager_decision,
    reconcile_logical_trade,
    run_closed_loop_learning,
)


SPRINT6_SCHEMA = """
CREATE TABLE IF NOT EXISTS OPERATIONAL_EVENTS (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    component TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    summary TEXT NOT NULL,
    details_json TEXT NOT NULL,
    proposal_id TEXT,
    logical_trade_id TEXT,
    broker TEXT,
    duration_ms REAL,
    success INTEGER NOT NULL,
    correlation_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS DECISION_JOURNAL (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    broker TEXT,
    strategy_id TEXT,
    regime_id TEXT,
    confidence REAL,
    evidence_for TEXT NOT NULL,
    evidence_against TEXT NOT NULL,
    market_data_quality TEXT NOT NULL,
    portfolio_decision_json TEXT NOT NULL,
    strategy_entitlement_json TEXT NOT NULL,
    risk_sentinel_decision_json TEXT NOT NULL,
    final_decision TEXT NOT NULL,
    execution_eligibility TEXT NOT NULL,
    execution_outcome TEXT,
    learning_reference TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS STRATEGY_MATURITY_REGISTRY (
    strategy_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    current_stage TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    sample_size INTEGER NOT NULL DEFAULT 0,
    expectancy REAL,
    avg_net_r REAL,
    median_net_r REAL,
    profit_factor REAL,
    max_drawdown REAL,
    win_rate REAL,
    calibration_error REAL,
    permitted_asset_classes_json TEXT NOT NULL,
    permitted_brokers_json TEXT NOT NULL,
    permitted_modes_json TEXT NOT NULL,
    max_capital_allocation REAL,
    max_risk_allocation REAL,
    qualification_date TEXT,
    next_review_date TEXT,
    suspended INTEGER NOT NULL DEFAULT 0,
    demotion_reason TEXT,
    approval_authority TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS STRATEGY_ENTITLEMENT_DECISIONS (
    entitlement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT,
    strategy_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    broker TEXT,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS PRODUCTION_RISK_SENTINEL_DECISIONS (
    sentinel_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT,
    broker TEXT,
    symbol TEXT,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS KILL_SWITCH_STATE (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    active INTEGER NOT NULL,
    state TEXT NOT NULL,
    activated_at TEXT,
    activated_by TEXT,
    reason TEXT,
    resume_required INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS SPRINT6_WORKFLOW_OUTBOX (
    workflow_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    workflow_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS BROKER_EVENT_MAPPINGS (
    mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    broker TEXT NOT NULL,
    logical_trade_id TEXT NOT NULL,
    raw_event_hash TEXT NOT NULL,
    normalized_stage TEXT NOT NULL,
    confidence REAL NOT NULL,
    source_endpoint TEXT NOT NULL,
    raw_payload_json TEXT NOT NULL,
    canonical_payload_json TEXT NOT NULL,
    UNIQUE(broker, raw_event_hash)
);

CREATE TABLE IF NOT EXISTS INCIDENT_LIFECYCLE (
    incident_key TEXT PRIMARY KEY,
    first_detected_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL,
    severity TEXT NOT NULL,
    component TEXT NOT NULL,
    affected_entity TEXT,
    status TEXT NOT NULL,
    recovery_attempts_json TEXT NOT NULL,
    resolution_timestamp TEXT,
    explanation TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS FOUNDER_OPERATIONAL_REPORTS (
    report_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    report_type TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    summary TEXT NOT NULL,
    report_markdown TEXT NOT NULL,
    file_path TEXT,
    payload_json TEXT NOT NULL
);
"""


STAGE_ORDER = {
    "research": 0,
    "backtest": 1,
    "walk forward": 2,
    "shadow": 3,
    "paper": 4,
    "micro live": 5,
    "production": 6,
    "retired": -1,
}

MODE_MINIMUM_STAGE = {
    "shadow": "shadow",
    "paper": "paper",
    "manual": "paper",
    "micro_live": "micro live",
    "production": "production",
}


def initialize_sprint6_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(SPRINT6_SCHEMA)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_operational_events_created ON OPERATIONAL_EVENTS(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_journal_proposal ON DECISION_JOURNAL(proposal_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_incident_status ON INCIDENT_LIFECYCLE(status, last_observed_at)")
            conn.execute(
                """
                INSERT OR IGNORE INTO KILL_SWITCH_STATE (
                    id, active, state, activated_at, activated_by, reason, resume_required, updated_at
                ) VALUES (1, 0, 'clear', NULL, NULL, NULL, 1, ?)
                """,
                (utc_now_iso(),),
            )


def _ensure_sprint6_schema(db_path: Path) -> None:
    if not uses_postgres():
        initialize_sprint6_schema(db_path)


def seed_default_strategy_registry(db_path: Path) -> None:
    _ensure_sprint6_schema(db_path)
    now = utc_now_iso()
    next_review = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO STRATEGY_MATURITY_REGISTRY (
                    strategy_id, version, current_stage, evidence_json, sample_size,
                    expectancy, avg_net_r, median_net_r, profit_factor, max_drawdown,
                    win_rate, calibration_error, permitted_asset_classes_json,
                    permitted_brokers_json, permitted_modes_json, max_capital_allocation,
                    max_risk_allocation, qualification_date, next_review_date, suspended,
                    demotion_reason, approval_authority, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "current_recommendation_process",
                    "1",
                    "Paper",
                    json.dumps(
                        {
                            "source": "Sprint 6 bootstrap",
                            "plain_english": (
                                "The current recommendation process is allowed for paper/manual testing only. "
                                "Micro-live and production promotion require governed evidence."
                            ),
                        },
                        sort_keys=True,
                    ),
                    0,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    json.dumps(["stock", "crypto"], sort_keys=True),
                    json.dumps(["alpaca", "kraken"], sort_keys=True),
                    json.dumps(["shadow", "paper", "manual"], sort_keys=True),
                    0.05,
                    0.01,
                    now,
                    next_review,
                    0,
                    None,
                    "founder-governance-default",
                    now,
                ),
            )


def record_operational_event(
    db_path: Path,
    *,
    component: str,
    event_type: str,
    summary: str,
    severity: str = "info",
    details: dict[str, Any] | None = None,
    proposal_id: str | None = None,
    logical_trade_id: str | None = None,
    broker: str | None = None,
    duration_ms: float | None = None,
    success: bool = True,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    _ensure_sprint6_schema(db_path)
    correlation = correlation_id or str(uuid4())
    with closing(connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO OPERATIONAL_EVENTS (
                    created_at, component, event_type, severity, summary, details_json,
                    proposal_id, logical_trade_id, broker, duration_ms, success, correlation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    component,
                    event_type,
                    severity,
                    summary,
                    json.dumps(details or {}, sort_keys=True, default=str),
                    proposal_id,
                    logical_trade_id,
                    broker.lower() if broker else None,
                    duration_ms,
                    int(success),
                    correlation,
                ),
            )
            event_id = cursor.lastrowid
    return {"event_id": event_id, "correlation_id": correlation, "status": "recorded"}


def pre_execution_decision_packet(
    db_path: Path,
    *,
    proposal: TradeProposal,
    broker: str,
    mode: str,
    account: AccountContext,
    positions: list[dict[str, Any]] | None = None,
    market_data_quality: str | None = None,
    guardrails: GuardrailConfig | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    _ensure_sprint6_schema(db_path)
    seed_default_strategy_registry(db_path)
    proposal_payload = proposal.to_dict()
    proposal_payload["broker"] = broker.lower()
    proposal_payload["notional"] = proposal.entry_price * proposal.position_size
    strategy = strategy_entitlement_decision(db_path, proposal=proposal, broker=broker, mode=mode)
    portfolio = portfolio_manager_decision(db_path, proposal=proposal_payload, positions=positions or _positions_from_account(account, broker))
    risk_validation = (
        validate_trade_proposal(proposal, account, guardrails, now=now)
        if guardrails is not None
        else None
    )
    risk_result = (
        risk_validation.to_dict()
        if risk_validation is not None
        else {
            "passed": True,
            "failures": [],
            "note": "Risk Engine evaluation is owned by the Orchestrator; no standalone guardrail configuration was supplied.",
        }
    )
    sentinel = production_risk_sentinel_decision(
        db_path,
        proposal=proposal,
        broker=broker,
        account=account,
        market_data_quality=market_data_quality,
    )
    reasons: list[str] = []
    approved = True
    if portfolio["decision"] not in {"approve", "approve_smaller"}:
        approved = False
        reasons.append(f"portfolio_manager_{portfolio['decision']}: {portfolio['reason']}")
    if strategy["decision"] != "approved":
        approved = False
        reasons.append(f"strategy_entitlement_blocked: {strategy['reason']}")
    if risk_validation is not None and not risk_validation.passed:
        approved = False
        reasons.extend(f"risk_engine_blocked: {reason}" for reason in risk_validation.failures)
    if sentinel["decision"] != "approved":
        approved = False
        reasons.append(f"risk_sentinel_blocked: {sentinel['reason']}")
    final_decision = "approved" if approved else "blocked"
    execution_eligibility = "eligible" if approved else "not_eligible"
    approved_notional = portfolio.get("approved_notional")
    if approved and portfolio["decision"] == "approve_smaller":
        reasons.append("Portfolio Manager approved a smaller notional amount.")
    evidence_for, evidence_against = _arguments(proposal)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO DECISION_JOURNAL (
                    created_at, proposal_id, symbol, broker, strategy_id, regime_id, confidence,
                    evidence_for, evidence_against, market_data_quality, portfolio_decision_json,
                    strategy_entitlement_json, risk_sentinel_decision_json, final_decision,
                    execution_eligibility, execution_outcome, learning_reference, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    proposal.proposal_id,
                    proposal.symbol,
                    broker.lower(),
                    strategy["strategy_id"],
                    strategy.get("regime_id"),
                    proposal.confidence_score,
                    evidence_for,
                    evidence_against,
                    market_data_quality or "Unknown - no market data gateway run was attached to this proposal.",
                    json.dumps(portfolio, sort_keys=True, default=str),
                    json.dumps(strategy, sort_keys=True, default=str),
                    json.dumps(sentinel, sort_keys=True, default=str),
                    final_decision,
                    execution_eligibility,
                    None,
                    None,
                    json.dumps({"proposal": proposal_payload, "reasons": reasons}, sort_keys=True, default=str),
                ),
            )
    record_operational_event(
        db_path,
        component="pre-execution",
        event_type="decision_packet",
        broker=broker,
        proposal_id=proposal.proposal_id,
        severity="info" if approved else "warning",
        success=approved,
        summary=f"{proposal.symbol} {final_decision} by Sprint 6 pre-execution packet.",
        details={
            "strategy": strategy,
            "portfolio": portfolio,
            "risk_engine": risk_result,
            "sentinel": sentinel,
            "reasons": reasons,
        },
    )
    return {
        "approved": approved,
        "final_decision": final_decision,
        "execution_eligibility": execution_eligibility,
        "reasons": reasons,
        "approved_notional": approved_notional,
        "portfolio_manager": portfolio,
        "strategy_entitlement": strategy,
        "risk_engine": risk_result,
        "risk_sentinel": sentinel,
        "plain_english": (
            "The trade may proceed to the Investment Orchestrator."
            if approved
            else "The trade was blocked before broker submission: " + "; ".join(reasons)
        ),
    }


def strategy_entitlement_decision(db_path: Path, *, proposal: TradeProposal, broker: str, mode: str) -> dict[str, Any]:
    _ensure_sprint6_schema(db_path)
    strategy_id = _strategy_id(proposal)
    row = _row(db_path, "SELECT * FROM STRATEGY_MATURITY_REGISTRY WHERE strategy_id = ?", (strategy_id,))
    if row is None:
        decision = "blocked"
        reason = f"Strategy '{strategy_id}' is not registered in the maturity registry."
        evidence = {"missing_registry_record": True}
    else:
        permitted_modes = _json_list(row["permitted_modes_json"])
        permitted_brokers = _json_list(row["permitted_brokers_json"])
        permitted_assets = _json_list(row["permitted_asset_classes_json"])
        stage = str(row["current_stage"])
        suspended = bool(row["suspended"])
        required_stage = MODE_MINIMUM_STAGE.get(mode, "production")
        decision = "approved"
        reason = "Strategy is entitled for this broker, asset type and execution mode."
        evidence = {
            "strategy_id": strategy_id,
            "stage": stage,
            "required_stage": required_stage,
            "permitted_modes": permitted_modes,
            "permitted_brokers": permitted_brokers,
            "permitted_asset_classes": permitted_assets,
            "suspended": suspended,
        }
        if suspended:
            decision = "blocked"
            reason = row["demotion_reason"] or "Strategy is suspended."
        elif broker.lower() not in [item.lower() for item in permitted_brokers]:
            decision = "blocked"
            reason = f"Strategy is not permitted for broker {broker.lower()}."
        elif proposal.asset_type.lower() not in [item.lower() for item in permitted_assets]:
            decision = "blocked"
            reason = f"Strategy is not permitted for asset type {proposal.asset_type.lower()}."
        elif mode not in permitted_modes:
            decision = "blocked"
            reason = f"Strategy is not permitted for {mode} execution."
        elif _stage_rank(stage) < _stage_rank(required_stage):
            decision = "blocked"
            reason = f"Strategy stage {stage} is below the {required_stage} gate required for {mode}."
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO STRATEGY_ENTITLEMENT_DECISIONS (
                    created_at, proposal_id, strategy_id, mode, broker, decision, reason, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    proposal.proposal_id,
                    strategy_id,
                    mode,
                    broker.lower(),
                    decision,
                    reason,
                    json.dumps(evidence, sort_keys=True, default=str),
                ),
            )
    return {"decision": decision, "strategy_id": strategy_id, "mode": mode, "broker": broker.lower(), "reason": reason, "evidence": evidence}


def production_risk_sentinel_decision(
    db_path: Path,
    *,
    proposal: TradeProposal,
    broker: str,
    account: AccountContext,
    market_data_quality: str | None = None,
) -> dict[str, Any]:
    _ensure_sprint6_schema(db_path)
    kill = _row(db_path, "SELECT * FROM KILL_SWITCH_STATE WHERE id = 1", ())
    issues: list[str] = []
    evidence = {
        "kill_switch_active": bool(kill and kill["active"]),
        "account_equity": account.equity,
        "proposal_risk_percentage": proposal.risk_percentage,
        "market_data_quality": market_data_quality,
        "open_positions": len(account.open_positions),
    }
    if kill and kill["active"]:
        issues.append(f"kill_switch_active: {kill['reason'] or 'manual resume required'}")
    if proposal.stop_loss <= 0:
        issues.append("stop_loss_missing")
    if proposal.take_profit <= 0:
        issues.append("take_profit_missing")
    if account.equity <= 0:
        issues.append("account_equity_unavailable_or_zero")
    if proposal.risk_percentage > 0.02:
        issues.append("risk_percentage_above_sentinel_limit")
    if market_data_quality and market_data_quality.lower().startswith(("blocked", "stale", "reject")):
        issues.append(f"market_data_quality_{market_data_quality}")
    incident = _latest_open_incident(db_path, components={"broker", "reconciliation", "database", "market-data"})
    if incident:
        issues.append(f"open_incident_{incident['component']}: {incident['explanation']}")
        evidence["open_incident"] = incident
    decision = "approved" if not issues else "blocked"
    reason = "Risk Sentinel clear." if not issues else "; ".join(issues)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO PRODUCTION_RISK_SENTINEL_DECISIONS (
                    created_at, proposal_id, broker, symbol, decision, reason, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    proposal.proposal_id,
                    broker.lower(),
                    proposal.symbol,
                    decision,
                    reason,
                    json.dumps(evidence, sort_keys=True, default=str),
                ),
            )
    return {"decision": decision, "reason": reason, "evidence": evidence}


def set_kill_switch(db_path: Path, *, active: bool, reason: str, activated_by: str = "system") -> dict[str, Any]:
    _ensure_sprint6_schema(db_path)
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO KILL_SWITCH_STATE (
                    id, active, state, activated_at, activated_by, reason, resume_required, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(id) DO UPDATE SET
                    active = excluded.active,
                    state = excluded.state,
                    activated_at = excluded.activated_at,
                    activated_by = excluded.activated_by,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (int(active), "active" if active else "clear", now if active else None, activated_by, reason, now),
            )
    return {"active": active, "state": "active" if active else "clear", "reason": reason, "updated_at": now}


def normalize_broker_events(
    db_path: Path,
    *,
    broker: str,
    events: list[dict[str, Any]],
    source_endpoint: str,
) -> dict[str, Any]:
    _ensure_sprint6_schema(db_path)
    canonical_events: list[dict[str, Any]] = []
    terminal_trades: dict[str, dict[str, Any]] = {}
    inserted = 0
    duplicates = 0
    for event in events:
        canonical = _canonical_broker_event(broker, event)
        canonical_result = reconcile_canonical_broker_event(
            db_path,
            broker=broker,
            event=canonical,
            source=source_endpoint,
        )
        canonical["logical_trade_id"] = canonical_result["logical_trade_id"]
        if canonical_result["terminal"] and canonical_result.get("trade"):
            terminal_trades[canonical_result["logical_trade_id"]] = canonical_result["trade"]
        raw_hash = _stable_hash(event)
        try:
            with closing(connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO BROKER_EVENT_MAPPINGS (
                            created_at, broker, logical_trade_id, raw_event_hash,
                            normalized_stage, confidence, source_endpoint,
                            raw_payload_json, canonical_payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            utc_now_iso(),
                            broker.lower(),
                            canonical["logical_trade_id"],
                            raw_hash,
                            canonical["stage"],
                            canonical["confidence"],
                            source_endpoint,
                            json.dumps(event, sort_keys=True, default=str),
                            json.dumps(canonical, sort_keys=True, default=str),
                        ),
                    )
                    inserted += 1
        except sqlite3.IntegrityError:
            duplicates += 1
        canonical_events.append(canonical)
    reconciliation = reconcile_logical_trade(db_path, broker=broker, events=canonical_events) if canonical_events else {"count": 0, "logical_trades": []}
    learning_workflows = [
        enqueue_learning_workflow(
            db_path,
            logical_trade_id=logical_trade_id,
            broker=broker,
            payload=_learning_payload_from_canonical_trade(trade),
        )
        for logical_trade_id, trade in terminal_trades.items()
    ]
    record_operational_event(
        db_path,
        component="broker-reconciliation",
        event_type="broker_events_normalized",
        broker=broker,
        summary=f"{broker.title()} broker poll normalized {inserted} new event(s), {duplicates} duplicate(s).",
        details={
            "inserted": inserted,
            "duplicates": duplicates,
            "reconciliation": reconciliation,
            "terminal_learning": learning_workflows,
        },
        success=True,
    )
    return {
        "status": "completed",
        "inserted": inserted,
        "duplicates": duplicates,
        "reconciliation": reconciliation,
        "terminal_learning": learning_workflows,
    }


def enqueue_learning_workflow(db_path: Path, *, logical_trade_id: str, broker: str, payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_sprint6_schema(db_path)
    key = f"closed-loop-learning:{broker.lower()}:{logical_trade_id}"
    workflow_id = str(uuid4())
    try:
        with closing(connect(db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO SPRINT6_WORKFLOW_OUTBOX (
                        workflow_id, created_at, workflow_type, entity_id, status,
                        attempts, next_attempt_at, last_error, payload_json, idempotency_key
                    ) VALUES (?, ?, 'closed_loop_learning', ?, 'pending', 0, ?, NULL, ?, ?)
                    """,
                    (
                        workflow_id,
                        utc_now_iso(),
                        logical_trade_id,
                        utc_now_iso(),
                        json.dumps({"broker": broker.lower(), **payload}, sort_keys=True, default=str),
                        key,
                    ),
                )
        return {"status": "queued", "workflow_id": workflow_id, "idempotency_key": key}
    except sqlite3.IntegrityError:
        return {"status": "duplicate", "idempotency_key": key}


def process_learning_outbox(
    db_path: Path,
    *,
    worker_id: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Claim and process pending learning workflows.

    Complete evidence runs the full learning chain. Irrecoverably incomplete
    historical evidence is closed explicitly as insufficient; it is never guessed
    and never left in an indefinite manual-review queue.
    """

    _ensure_sprint6_schema(db_path)
    now = utc_now_iso()
    claimed: list[dict[str, Any]] = []
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            rows = conn.execute(
                """
                SELECT * FROM SPRINT6_WORKFLOW_OUTBOX
                WHERE workflow_type = 'closed_loop_learning'
                  AND (
                    (status IN ('pending', 'retry') AND (next_attempt_at IS NULL OR next_attempt_at <= ?))
                    OR (status = 'claimed' AND next_attempt_at <= ?)
                  )
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (now, now, max(1, int(limit))),
            ).fetchall()
            for row in rows:
                cursor = conn.execute(
                    """
                    UPDATE SPRINT6_WORKFLOW_OUTBOX
                    SET status = 'claimed',
                        attempts = attempts + 1,
                        next_attempt_at = ?,
                        last_error = NULL
                    WHERE workflow_id = ?
                      AND (
                        status IN ('pending', 'retry')
                        OR (status = 'claimed' AND next_attempt_at <= ?)
                      )
                    """,
                    (
                        (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
                        row["workflow_id"],
                        now,
                    ),
                )
                if cursor.rowcount:
                    claimed.append(dict(row))

    processed = 0
    manual_review = 0
    failed = 0
    results: list[dict[str, Any]] = []
    for row in claimed:
        workflow_id = str(row["workflow_id"])
        try:
            payload = json.loads(row["payload_json"] or "{}")
            logical_trade_id = str(row["entity_id"] or payload.get("logical_trade_id") or "")
            broker = str(payload.get("broker") or "")
            symbol = str(payload.get("symbol") or payload.get("attribution", {}).get("symbol") or "")
            attribution = payload.get("attribution")
            decision_context = payload.get("decision_context")
            observations = payload.get("observations") or []
            missing = [
                name
                for name, value in {
                    "logical_trade_id": logical_trade_id,
                    "broker": broker,
                    "symbol": symbol,
                    "attribution": attribution,
                    "decision_context": decision_context,
                }.items()
                if not value
            ]
            if missing:
                learning = complete_insufficient_evidence_learning(
                    db_path,
                    logical_trade_id=logical_trade_id,
                    broker=broker or "unknown",
                    symbol=symbol or "UNKNOWN",
                    missing=missing,
                    payload=payload,
                )
                _complete_learning_workflow(
                    db_path,
                    workflow_id,
                    status="completed_insufficient_evidence",
                )
                processed += 1
                results.append({"workflow_id": workflow_id, "status": "completed_insufficient_evidence", "learning": learning})
                continue
            learning = run_closed_loop_learning(
                db_path,
                logical_trade_id=logical_trade_id,
                broker=broker,
                symbol=symbol,
                attribution=attribution,
                decision_context=decision_context,
                observations=observations,
            )
            _complete_learning_workflow(db_path, workflow_id, status="completed")
            processed += 1
            results.append({"workflow_id": workflow_id, "status": "completed", "learning": learning})
        except Exception as exc:  # noqa: BLE001 - processor must persist failure evidence
            failed += 1
            attempts = int(row.get("attempts") or 0) + 1
            retry = "failed" if attempts >= 3 else "retry"
            next_attempt = None if retry == "failed" else (datetime.now(timezone.utc) + timedelta(minutes=5 * attempts)).isoformat()
            _complete_learning_workflow(db_path, workflow_id, status=retry, error=str(exc), next_attempt_at=next_attempt)
            results.append({"workflow_id": workflow_id, "status": retry, "error": str(exc)})

    record_operational_event(
        db_path,
        component="learning-processor",
        event_type="learning_outbox_processed",
        severity="info" if failed == 0 else "warning",
        success=failed == 0,
        summary=f"Learning processor claimed {len(claimed)} workflow(s): {processed} completed, {manual_review} manual review, {failed} failed.",
        details={"worker_id": worker_id, "processed": processed, "manual_review": manual_review, "failed": failed, "results": results},
    )
    return {
        "status": "completed",
        "claimed": len(claimed),
        "processed": processed,
        "manual_review": manual_review,
        "failed": failed,
        "results": results,
    }


def _complete_learning_workflow(
    db_path: Path,
    workflow_id: str,
    *,
    status: str,
    error: str | None = None,
    next_attempt_at: str | None = None,
) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                UPDATE SPRINT6_WORKFLOW_OUTBOX
                SET status = ?,
                    next_attempt_at = ?,
                    last_error = ?
                WHERE workflow_id = ?
                """,
                (
                    status,
                    next_attempt_at,
                    error,
                    workflow_id,
                ),
            )


def upsert_incident(
    db_path: Path,
    *,
    incident_key: str,
    severity: str,
    component: str,
    explanation: str,
    recommended_action: str,
    affected_entity: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_sprint6_schema(db_path)
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO INCIDENT_LIFECYCLE (
                    incident_key, first_detected_at, last_observed_at, occurrence_count,
                    severity, component, affected_entity, status, recovery_attempts_json,
                    resolution_timestamp, explanation, recommended_action, payload_json
                ) VALUES (?, ?, ?, 1, ?, ?, ?, 'open', '[]', NULL, ?, ?, ?)
                ON CONFLICT(incident_key) DO UPDATE SET
                    last_observed_at = excluded.last_observed_at,
                    occurrence_count = occurrence_count + 1,
                    severity = excluded.severity,
                    explanation = excluded.explanation,
                    recommended_action = excluded.recommended_action,
                    payload_json = excluded.payload_json,
                    status = 'open'
                """,
                (
                    incident_key,
                    now,
                    now,
                    severity,
                    component,
                    affected_entity,
                    explanation,
                    recommended_action,
                    json.dumps(payload or {}, sort_keys=True, default=str),
                ),
            )
    record_operational_event(
        db_path,
        component=component,
        event_type="incident_observed",
        severity=severity,
        summary=explanation,
        details={"incident_key": incident_key, "recommended_action": recommended_action, "payload": payload or {}},
        broker=affected_entity if affected_entity in {"alpaca", "kraken"} else None,
        success=False,
    )
    return {"incident_key": incident_key, "status": "open", "explanation": explanation}


def generate_founder_operational_report(
    db_path: Path,
    *,
    output_dir: Path,
    report_type: str = "daily",
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, Any]:
    _ensure_sprint6_schema(db_path)
    now = datetime.now(timezone.utc)
    end = period_end or now.isoformat()
    if period_start:
        start = period_start
    elif report_type == "weekly":
        start = (now - timedelta(days=7)).isoformat()
    elif report_type == "monthly":
        start = (now - timedelta(days=30)).isoformat()
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    events = _rows(db_path, "SELECT * FROM OPERATIONAL_EVENTS WHERE created_at >= ? AND created_at <= ? ORDER BY created_at DESC LIMIT 100", (start, end))
    decisions = _rows(db_path, "SELECT * FROM DECISION_JOURNAL WHERE created_at >= ? AND created_at <= ? ORDER BY created_at DESC LIMIT 100", (start, end))
    incidents = _rows(db_path, "SELECT * FROM INCIDENT_LIFECYCLE WHERE last_observed_at >= ? AND last_observed_at <= ? ORDER BY last_observed_at DESC LIMIT 50", (start, end))
    blocked = [row for row in decisions if row["final_decision"] != "approved"]
    summary = (
        f"{len(events)} operational event(s), {len(decisions)} decision packet(s), "
        f"{len(blocked)} blocked trade attempt(s), {len(incidents)} incident record(s)."
    )
    markdown = "\n".join(
        [
            f"# AI Trader {report_type.title()} Operational Report",
            "",
            f"Period: {start} to {end}",
            "",
            "## Executive Answer",
            "",
            summary,
            "",
            "## What AI Trader Can Prove",
            "",
            f"- Decision packets recorded: {len(decisions)}",
            f"- Approved before orchestrator: {len(decisions) - len(blocked)}",
            f"- Blocked before broker submission: {len(blocked)}",
            f"- Incidents observed: {len(incidents)}",
            "",
            "## Latest Decisions",
            "",
            *_markdown_decisions(decisions[:10]),
            "",
            "## Current Limits Of Evidence",
            "",
            "- Hosted Render/Supabase soak evidence must come from deployed runtime records, not local tests.",
            "- Learning proposals remain suggestions only and do not change production parameters.",
        ]
    )
    reports_dir = output_dir / "operational_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    file_path = reports_dir / f"{report_type}-{now.strftime('%Y%m%d-%H%M%S')}.md"
    file_path.write_text(markdown, encoding="utf-8")
    with closing(connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO FOUNDER_OPERATIONAL_REPORTS (
                    created_at, report_type, period_start, period_end, summary,
                    report_markdown, file_path, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    report_type,
                    start,
                    end,
                    summary,
                    markdown,
                    str(file_path),
                    json.dumps({"events": len(events), "decisions": len(decisions), "incidents": len(incidents)}, sort_keys=True),
                ),
            )
            report_id = cursor.lastrowid
    return {"status": "generated", "report_id": report_id, "summary": summary, "file_path": str(file_path), "markdown": markdown}


def sprint6_status(db_path: Path, *, database_backend: str = "sqlite") -> dict[str, Any]:
    _ensure_sprint6_schema(db_path)
    seed_default_strategy_registry(db_path)
    strategies = _rows(db_path, "SELECT strategy_id, current_stage, suspended, permitted_modes_json FROM STRATEGY_MATURITY_REGISTRY ORDER BY updated_at DESC", ())
    latest_events = _rows(db_path, "SELECT created_at, component, event_type, severity, summary FROM OPERATIONAL_EVENTS ORDER BY event_id DESC LIMIT 5", ())
    open_incidents = _rows(db_path, "SELECT * FROM INCIDENT_LIFECYCLE WHERE status = 'open' ORDER BY last_observed_at DESC LIMIT 10", ())
    kill = _row(db_path, "SELECT * FROM KILL_SWITCH_STATE WHERE id = 1", ())
    decisions = _rows(db_path, "SELECT final_decision, COUNT(*) AS count FROM DECISION_JOURNAL GROUP BY final_decision", ())
    backend_ready = database_backend in {"postgres", "postgresql", "supabase"}
    blocked = bool(open_incidents) or bool(kill and kill["active"])
    overall = "ready_for_controlled_operation" if backend_ready and not blocked else "attention_needed"
    if backend_ready and not blocked:
        plain = (
            "Production control gates are active. AI Trader can operate autonomously inside the approved broker, "
            "portfolio, strategy, and risk limits."
        )
    elif backend_ready:
        plain = "Production control gates are installed, but an open incident or kill switch currently requires attention."
    else:
        plain = "Production control gates are installed, but shared Supabase/Postgres runtime truth is not active."
    return {
        "generated_at": utc_now_iso(),
        "overall": overall,
        "database_backend": database_backend,
        "shared_runtime_truth": (
            "Postgres/Supabase configured for shared production truth."
            if backend_ready
            else "SQLite is active; acceptable for local/test/offline use but not enough for multi-process production truth."
        ),
        "kill_switch": {"active": bool(kill and kill["active"]), "state": kill["state"] if kill else "unknown", "reason": kill["reason"] if kill else None},
        "strategy_registry": [dict(row) for row in strategies],
        "decision_journal_counts": {row["final_decision"]: row["count"] for row in decisions},
        "open_incidents": [dict(row) for row in open_incidents],
        "latest_operational_events": [dict(row) for row in latest_events],
        "plain_english": plain,
    }


def execution_mode_for_broker(*, broker: str, can_submit_real_orders: bool, manual: bool = False) -> str:
    broker_key = broker.lower()
    if broker_key == "alpaca":
        return "manual" if manual else "paper"
    if broker_key == "kraken" and can_submit_real_orders:
        return "micro_live"
    if manual:
        return "manual"
    return "paper"


def _positions_from_account(account: AccountContext, broker: str) -> list[dict[str, Any]]:
    return [
        {
            "symbol": item.symbol,
            "broker": broker.lower(),
            "market_value": item.market_value,
            "asset_class": "crypto" if broker.lower() == "kraken" else "stock",
            "risk_amount": abs(item.unrealized_pl) if item.unrealized_pl else 0,
        }
        for item in account.open_positions
    ]


def _strategy_id(proposal: TradeProposal) -> str:
    payload = proposal.to_dict()
    raw = payload.get("strategy_id") or payload.get("strategy") or payload.get("selected_strategy")
    return str(raw or "current_recommendation_process").strip() or "current_recommendation_process"


def _stage_rank(stage: str) -> int:
    return STAGE_ORDER.get(stage.lower().replace("_", " "), 0)


def _arguments(proposal: TradeProposal) -> tuple[str, str]:
    for_text = proposal.plain_english_reasoning or proposal.technical_summary or "No explicit positive thesis was recorded."
    against = "No explicit strongest argument against was recorded; Sprint 6 treats this as a decision-quality weakness."
    for marker in ["strongest argument against", "argument against", "why not"]:
        lower = for_text.lower()
        if marker in lower:
            index = lower.find(marker)
            against = for_text[index:].strip()
            for_text = for_text[:index].strip() or proposal.plain_english_reasoning
            break
    return for_text, against


def _canonical_broker_event(broker: str, event: dict[str, Any]) -> dict[str, Any]:
    symbol = str(event.get("symbol") or event.get("pair") or event.get("asset") or "").upper()
    order_id = str(event.get("order_id") or event.get("ordertxid") or event.get("id") or "")
    trade_id = str(event.get("trade_id") or event.get("tradeid") or "")
    logical_trade_id = str(event.get("logical_trade_id") or order_id or trade_id or f"{broker}:{symbol}:{event.get('time') or event.get('created_at') or utc_now_iso()}")
    status = str(event.get("status") or event.get("type") or event.get("event") or "unknown").lower()
    stage = _stage_from_status(status, event)
    confidence = 0.95 if order_id or trade_id else 0.70
    return {
        "logical_trade_id": logical_trade_id,
        "order_id": order_id,
        "trade_id": trade_id,
        "id": event.get("id") or trade_id or order_id,
        "status": status,
        "stage": stage,
        "symbol": symbol,
        "pair": symbol,
        "side": event.get("side") or event.get("type"),
        "asset_type": event.get("asset_type") or ("crypto" if broker.lower() == "kraken" else "stock"),
        "price": event.get("price"),
        "average_fill_price": event.get("average_fill_price") or event.get("filled_avg_price") or event.get("avg_price") or event.get("price"),
        "quantity": event.get("quantity") or event.get("qty") or event.get("vol") or event.get("vol_exec"),
        "filled_quantity": event.get("filled_quantity") or event.get("filled_qty") or event.get("vol_exec"),
        "remaining_quantity": event.get("remaining_quantity") or event.get("remaining"),
        "broker_fee": event.get("broker_fee"),
        "exchange_fee": event.get("exchange_fee") or event.get("fee"),
        "fill_id": event.get("fill_id") or event.get("trade_id") or event.get("tradeid") or event.get("id"),
        "proposal_id": event.get("proposal_id") or event.get("client_order_id"),
        "recommendation_id": event.get("recommendation_id"),
        "fill_role": event.get("fill_role"),
        "timestamp": event.get("updated_at") or event.get("transaction_time") or event.get("time") or event.get("created_at") or utc_now_iso(),
        "confidence": confidence,
        "raw_status": status,
    }


def _learning_payload_from_canonical_trade(trade: dict[str, Any]) -> dict[str, Any]:
    try:
        stored_context = json.loads(trade.get("decision_context_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        stored_context = {}
    proposal_context = stored_context.get("proposal") if isinstance(stored_context.get("proposal"), dict) else {}
    intelligence = stored_context.get("intelligence") if isinstance(stored_context.get("intelligence"), dict) else {}
    committee = intelligence.get("committee") if isinstance(intelligence.get("committee"), dict) else {}
    probability = intelligence.get("probability") if isinstance(intelligence.get("probability"), dict) else {}
    decision_context = {
        **proposal_context,
        "intended_entry_price": trade.get("intended_entry_price"),
        "entry_price": trade.get("intended_entry_price"),
        "original_stop": trade.get("original_stop"),
        "stop_loss": trade.get("original_stop"),
        "take_profit": trade.get("intended_target"),
        "strategy_id": committee.get("strategy_id") or probability.get("strategy_id") or proposal_context.get("strategy_id"),
        "asset_type": trade.get("asset_type"),
        "side": trade.get("side"),
        "reconciliation_confidence": trade.get("reconciliation_confidence"),
    }
    return {
        "symbol": trade.get("symbol"),
        "attribution": {
            "proposal_id": trade.get("proposal_id"),
            "symbol": trade.get("symbol"),
            "side": trade.get("side"),
            "quantity": trade.get("entry_filled_quantity"),
            "actual_average_entry_price": trade.get("average_entry_price"),
            "actual_average_exit_price": trade.get("average_exit_price"),
            "entry_price": trade.get("average_entry_price"),
            "exit_price": trade.get("average_exit_price"),
            "broker_fee": trade.get("broker_fee"),
            "exchange_fee": trade.get("exchange_fee"),
            "gross_realized_pnl": trade.get("gross_pnl"),
            "profit_loss": trade.get("gross_pnl"),
            "net_realized_pnl": trade.get("net_pnl"),
        },
        "decision_context": decision_context,
        "observations": [],
    }


def _stage_from_status(status: str, event: dict[str, Any]) -> str:
    if status in {"submitted", "new"}:
        return "submitted"
    if status in {"accepted", "open", "pending", "acknowledged"}:
        return "broker_acknowledged"
    remaining = safe_float(event.get("remaining_quantity") or event.get("remaining"))
    filled = safe_float(event.get("filled_quantity") or event.get("filled_qty") or event.get("vol_exec"))
    if status in {"partial", "partially_filled"} or (remaining and filled):
        return "partially_filled"
    if status in {"filled", "closed", "complete"} or filled:
        return "fully_filled"
    if status in {"cancelled", "canceled"}:
        return "cancelled"
    if status == "rejected":
        return "risk_rejected"
    return "broker_acknowledged"


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _latest_open_incident(db_path: Path, *, components: set[str]) -> dict[str, Any] | None:
    rows = _rows(db_path, "SELECT * FROM INCIDENT_LIFECYCLE WHERE status = 'open' ORDER BY last_observed_at DESC LIMIT 25", ())
    for row in rows:
        if any(str(row["component"]).startswith(component) for component in components):
            return dict(row)
    return None


def _row(db_path: Path, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def _rows(db_path: Path, sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()


def _json_list(value: Any) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _markdown_decisions(decisions: list[sqlite3.Row]) -> list[str]:
    if not decisions:
        return ["- No decision packets were recorded in this period."]
    lines = []
    for row in decisions:
        lines.append(f"- {row['symbol']} via {row['broker']}: {row['final_decision']} ({row['execution_eligibility']}).")
    return lines
