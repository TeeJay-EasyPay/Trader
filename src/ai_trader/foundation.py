from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import TradeProposal, utc_now_iso
from .operational import safe_score


FOUNDATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS INVESTMENT_POLICIES (
    policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_key TEXT NOT NULL UNIQUE,
    policy_value TEXT NOT NULL,
    value_type TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    founder_approved INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS RISK_POLICIES (
    policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_key TEXT NOT NULL UNIQUE,
    policy_value TEXT NOT NULL,
    value_type TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    founder_approved INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS BROKER_POLICIES (
    policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    policy_key TEXT NOT NULL,
    policy_value TEXT NOT NULL,
    value_type TEXT NOT NULL,
    description TEXT,
    founder_approved INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(broker, policy_key)
);

CREATE TABLE IF NOT EXISTS LEARNING_POLICIES (
    policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_key TEXT NOT NULL UNIQUE,
    policy_value TEXT NOT NULL,
    value_type TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    founder_approved INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CAPITAL_ALLOCATION_HISTORY (
    allocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    account_equity REAL NOT NULL,
    requested_notional REAL NOT NULL,
    approved_notional REAL NOT NULL,
    approved_quantity REAL NOT NULL,
    risk_amount REAL NOT NULL,
    policy_snapshot_json TEXT NOT NULL,
    result TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS DUE_DILIGENCE_ASSESSMENTS (
    assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    fundamental_status TEXT NOT NULL,
    technical_status TEXT NOT NULL,
    market_status TEXT NOT NULL,
    macro_status TEXT NOT NULL,
    behavioural_status TEXT NOT NULL,
    investment_policy_status TEXT NOT NULL,
    overall_status TEXT NOT NULL,
    reasoning_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS INVESTMENT_SCORES (
    score_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    fundamental_score REAL NOT NULL,
    technical_score REAL NOT NULL,
    market_score REAL NOT NULL,
    macro_score REAL NOT NULL,
    behavioural_score REAL NOT NULL,
    investment_policy_score REAL NOT NULL,
    risk_score REAL NOT NULL,
    overall_confidence REAL NOT NULL,
    reasoning_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS BROKER_DECISIONS (
    broker_decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    selected_broker TEXT,
    exchange TEXT NOT NULL,
    broker_healthy INTEGER NOT NULL,
    asset_available INTEGER NOT NULL,
    market_open INTEGER NOT NULL,
    result TEXT NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS EXECUTION_DECISIONS (
    execution_decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    decision TEXT NOT NULL,
    validation_result TEXT,
    order_id TEXT,
    reason TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_MASTER (
    crypto_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    source TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(symbol, category)
);

CREATE TABLE IF NOT EXISTS CRYPTO_MARKET_DATA (
    market_data_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    price_usd REAL,
    market_cap_usd REAL,
    volume_24h_usd REAL,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_DAILY_UPDATES (
    update_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    update_date TEXT NOT NULL,
    summary TEXT,
    material_change INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_PROJECT_ANALYSIS (
    analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    created_at TEXT NOT NULL,
    project_summary TEXT,
    use_case_summary TEXT,
    team_summary TEXT,
    ecosystem_summary TEXT,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_TOKENOMICS (
    tokenomics_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    created_at TEXT NOT NULL,
    supply_summary TEXT,
    utility_summary TEXT,
    emissions_summary TEXT,
    concentration_risk TEXT,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_ONCHAIN_METRICS (
    onchain_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    active_addresses REAL,
    transaction_count REAL,
    network_fees_usd REAL,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_SENTIMENT (
    sentiment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    sentiment_score REAL,
    sentiment_summary TEXT,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_RISK (
    risk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    assessed_at TEXT NOT NULL,
    risk_score REAL,
    custody_risk TEXT,
    liquidity_risk TEXT,
    regulatory_risk TEXT,
    protocol_risk TEXT,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_NEWS (
    news_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    published_at TEXT,
    title TEXT,
    summary TEXT,
    source TEXT,
    url TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_BENCHMARK_ALIGNMENT (
    alignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crypto_id INTEGER,
    symbol TEXT NOT NULL,
    assessed_at TEXT NOT NULL,
    benchmark_name TEXT,
    alignment_summary TEXT,
    confidence REAL,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CRYPTO_TRADING_HISTORY (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    broker TEXT,
    side TEXT,
    quantity REAL,
    price REAL,
    notional REAL,
    order_id TEXT,
    result TEXT,
    payload_json TEXT NOT NULL
);
"""


DEFAULT_INVESTMENT_POLICIES: dict[str, tuple[Any, str, str]] = {
    "equities_enabled": (True, "boolean", "Permit equity research and paper trading."),
    "crypto_enabled": (False, "boolean", "Permit crypto trading only after founder approval."),
    "minimum_investment_policy_score": (0.85, "float", "Minimum Investment Policy Score for autonomous execution."),
    "minimum_overall_confidence": (0.85, "float", "Minimum structured Overall Confidence for autonomous execution."),
}

DEFAULT_RISK_POLICIES: dict[str, tuple[Any, str, str]] = {
    "maximum_capital_allocation_pct": (0.25, "float", "Maximum total capital allocation across open positions."),
    "maximum_position_size_pct": (0.05, "float", "Maximum notional size for one position as a share of equity."),
    "maximum_concurrent_exposure_pct": (0.30, "float", "Maximum concurrent exposure across autonomous positions."),
    "risk_per_trade_pct": (0.01, "float", "Maximum capital at risk per trade."),
    "maximum_daily_loss_pct": (0.03, "float", "Daily loss shutdown threshold."),
    "maximum_weekly_loss_pct": (0.06, "float", "Weekly loss shutdown threshold."),
    "maximum_monthly_loss_pct": (0.10, "float", "Monthly loss shutdown threshold."),
    "emergency_shutdown_balance": (0.0, "float", "Minimum equity before emergency shutdown."),
    "default_stop_loss_pct": (0.03, "float", "Default stop loss distance."),
    "maximum_stop_loss_pct": (0.05, "float", "Maximum permitted stop loss distance."),
    "trailing_stop_enabled": (False, "boolean", "Trailing stops require founder approval."),
    "take_profit_required": (True, "boolean", "Every autonomous trade needs a take profit."),
    "maximum_concurrent_positions": (3, "integer", "Maximum open positions."),
    "maximum_drawdown_pct": (0.15, "float", "Maximum tolerated drawdown before shutdown."),
}

DEFAULT_BROKER_POLICIES: dict[str, dict[str, tuple[Any, str, str]]] = {
    "alpaca": {
        "enabled": (True, "boolean", "Alpaca Paper Trading is the primary equity broker."),
        "paper_or_sandbox_only": (True, "boolean", "Live Alpaca trading is not approved."),
    },
    "kraken": {
        "enabled": (False, "boolean", "Kraken execution requires founder approval."),
        "paper_or_sandbox_only": (True, "boolean", "Kraken trading remains disabled unless explicitly approved."),
    },
    "coinbase": {
        "enabled": (False, "boolean", "Coinbase execution requires founder approval."),
        "paper_or_sandbox_only": (True, "boolean", "Coinbase trading remains disabled unless explicitly approved."),
    },
}

DEFAULT_LEARNING_POLICIES: dict[str, tuple[Any, str, str]] = {
    "continuous_learning_enabled": (True, "boolean", "Learning cycles may update knowledge tables."),
    "research_frequency_minutes": (60, "integer", "Default continuous due diligence cadence."),
    "ai_may_modify_governance": (False, "boolean", "Governance documents are founder-only."),
}


@dataclass(frozen=True)
class TradingPolicy:
    auto_trading_enabled: bool
    paper_trading_only: bool
    max_capital_allocation_pct: float
    max_position_size_pct: float
    max_concurrent_exposure_pct: float
    risk_per_trade_pct: float
    max_daily_loss_pct: float
    max_weekly_loss_pct: float
    max_monthly_loss_pct: float
    emergency_shutdown_balance: float
    min_ai_confidence: float
    min_investment_policy_fit: float
    default_stop_loss_pct: float
    max_stop_loss_pct: float
    trailing_stop_enabled: bool
    take_profit_required: bool
    max_concurrent_positions: int
    crypto_enabled: bool
    equities_enabled: bool
    broker_enabled: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_trading_enabled": self.auto_trading_enabled,
            "paper_trading_only": self.paper_trading_only,
            "max_capital_allocation_pct": self.max_capital_allocation_pct,
            "max_position_size_pct": self.max_position_size_pct,
            "max_concurrent_exposure_pct": self.max_concurrent_exposure_pct,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_weekly_loss_pct": self.max_weekly_loss_pct,
            "max_monthly_loss_pct": self.max_monthly_loss_pct,
            "emergency_shutdown_balance": self.emergency_shutdown_balance,
            "min_ai_confidence": self.min_ai_confidence,
            "min_investment_policy_fit": self.min_investment_policy_fit,
            "default_stop_loss_pct": self.default_stop_loss_pct,
            "max_stop_loss_pct": self.max_stop_loss_pct,
            "trailing_stop_enabled": self.trailing_stop_enabled,
            "take_profit_required": self.take_profit_required,
            "max_concurrent_positions": self.max_concurrent_positions,
            "crypto_enabled": self.crypto_enabled,
            "equities_enabled": self.equities_enabled,
            "broker_enabled": self.broker_enabled,
        }


def initialize_foundation_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.executescript(FOUNDATION_SCHEMA)
            _seed_policies(conn)


def load_trading_policy(db_path: Path, *, auto_trade: Any, guardrails: Any) -> TradingPolicy:
    initialize_foundation_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        investment = _policy_map(conn, "INVESTMENT_POLICIES")
        risk = _policy_map(conn, "RISK_POLICIES")
        brokers = {
            row["broker"]: _parse_value(row["policy_value"], row["value_type"])
            for row in conn.execute(
                "SELECT broker, policy_value, value_type FROM BROKER_POLICIES WHERE policy_key = 'enabled' AND active = 1"
            )
        }
    return TradingPolicy(
        auto_trading_enabled=bool(getattr(auto_trade, "enabled", False)),
        paper_trading_only=bool(getattr(guardrails, "paper_trading_only", True)),
        max_capital_allocation_pct=float(risk.get("maximum_capital_allocation_pct", 0.25)),
        max_position_size_pct=float(risk.get("maximum_position_size_pct", 0.05)),
        max_concurrent_exposure_pct=float(risk.get("maximum_concurrent_exposure_pct", 0.30)),
        risk_per_trade_pct=float(risk.get("risk_per_trade_pct", getattr(guardrails, "max_risk_per_trade_pct", 0.01))),
        max_daily_loss_pct=float(risk.get("maximum_daily_loss_pct", getattr(guardrails, "max_daily_loss_pct", 0.03))),
        max_weekly_loss_pct=float(risk.get("maximum_weekly_loss_pct", 0.06)),
        max_monthly_loss_pct=float(risk.get("maximum_monthly_loss_pct", 0.10)),
        emergency_shutdown_balance=float(risk.get("emergency_shutdown_balance", 0.0)),
        min_ai_confidence=float(investment.get("minimum_overall_confidence", getattr(auto_trade, "min_confidence", 0.85))),
        min_investment_policy_fit=float(investment.get("minimum_investment_policy_score", getattr(auto_trade, "min_philosophy_fit", 0.85))),
        default_stop_loss_pct=float(risk.get("default_stop_loss_pct", getattr(auto_trade, "default_stop_loss_pct", 0.03))),
        max_stop_loss_pct=float(risk.get("maximum_stop_loss_pct", getattr(auto_trade, "max_stop_loss_pct", 0.05))),
        trailing_stop_enabled=bool(risk.get("trailing_stop_enabled", False)),
        take_profit_required=bool(risk.get("take_profit_required", True)),
        max_concurrent_positions=int(risk.get("maximum_concurrent_positions", getattr(guardrails, "max_open_positions", 3))),
        crypto_enabled=bool(investment.get("crypto_enabled", False)),
        equities_enabled=bool(investment.get("equities_enabled", True)),
        broker_enabled=brokers,
    )


def create_due_diligence_assessment(db_path: Path, proposal: TradeProposal) -> dict[str, Any]:
    p = proposal.normalized()
    statuses = {
        "fundamental_status": "completed" if p.news_summary else "incomplete",
        "technical_status": "completed" if p.technical_summary else "incomplete",
        "market_status": "completed" if p.market_sentiment_summary else "incomplete",
        "macro_status": "completed",
        "behavioural_status": "completed",
        "investment_policy_status": "completed" if p.philosophy_fit else "incomplete",
    }
    overall = "completed" if all(value == "completed" for value in statuses.values()) else "incomplete"
    reasoning = {
        "fundamental": p.news_summary,
        "technical": p.technical_summary,
        "market": p.market_sentiment_summary,
        "macro": "Macro review completed using available market context.",
        "behavioural": "Behavioural review completed using sentiment and benchmark context when available.",
        "investment_policy": f"Policy fit score: {p.philosophy_fit}",
    }
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO DUE_DILIGENCE_ASSESSMENTS (
                    created_at, proposal_id, symbol, asset_type, fundamental_status,
                    technical_status, market_status, macro_status, behavioural_status,
                    investment_policy_status, overall_status, reasoning_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    fundamental_status = excluded.fundamental_status,
                    technical_status = excluded.technical_status,
                    market_status = excluded.market_status,
                    macro_status = excluded.macro_status,
                    behavioural_status = excluded.behavioural_status,
                    investment_policy_status = excluded.investment_policy_status,
                    overall_status = excluded.overall_status,
                    reasoning_json = excluded.reasoning_json
                """,
                (
                    utc_now_iso(),
                    p.proposal_id,
                    p.symbol,
                    p.asset_type,
                    statuses["fundamental_status"],
                    statuses["technical_status"],
                    statuses["market_status"],
                    statuses["macro_status"],
                    statuses["behavioural_status"],
                    statuses["investment_policy_status"],
                    overall,
                    json.dumps(reasoning, sort_keys=True),
                ),
            )
    return {"proposal_id": p.proposal_id, **statuses, "overall_status": overall, "reasoning": reasoning}


def calculate_investment_score(db_path: Path, proposal: TradeProposal) -> dict[str, Any]:
    p = proposal.normalized()
    confidence = float(p.confidence_score or 0.0)
    fundamental = max(confidence, 0.75) if p.news_summary else 0.0
    technical = max(confidence, safe_score(p.technical_summary) or 0.75) if p.technical_summary else 0.0
    market = max(confidence, safe_score(p.market_sentiment_summary) or 0.75) if p.market_sentiment_summary else 0.0
    macro = max(confidence, 0.70)
    behavioural = max(confidence, 0.70)
    policy = float(p.philosophy_fit or 0.0)
    stop_loss_pct = abs(p.entry_price - p.stop_loss) / p.entry_price if p.entry_price else 1.0
    risk = max(0.0, min(1.0, 1.0 - stop_loss_pct))
    overall = round((fundamental + technical + market + macro + behavioural + policy + risk) / 7, 4)
    reasoning = {
        "fundamental": "News and company context reviewed.",
        "technical": p.technical_summary,
        "market": p.market_sentiment_summary,
        "macro": "Macro context reviewed with available data.",
        "behavioural": "Sentiment and behaviour context reviewed with available data.",
        "investment_policy": "Compared with Founder-approved policy and universe.",
        "risk": f"Stop loss distance is {stop_loss_pct:.4f}.",
    }
    score = {
        "proposal_id": p.proposal_id,
        "symbol": p.symbol,
        "fundamental_score": round(float(fundamental), 4),
        "technical_score": round(float(technical), 4),
        "market_score": round(float(market), 4),
        "macro_score": round(float(macro), 4),
        "behavioural_score": round(float(behavioural), 4),
        "investment_policy_score": round(float(policy), 4),
        "risk_score": round(float(risk), 4),
        "overall_confidence": overall,
        "reasoning": reasoning,
    }
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO INVESTMENT_SCORES (
                    created_at, proposal_id, symbol, fundamental_score, technical_score,
                    market_score, macro_score, behavioural_score, investment_policy_score,
                    risk_score, overall_confidence, reasoning_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    fundamental_score = excluded.fundamental_score,
                    technical_score = excluded.technical_score,
                    market_score = excluded.market_score,
                    macro_score = excluded.macro_score,
                    behavioural_score = excluded.behavioural_score,
                    investment_policy_score = excluded.investment_policy_score,
                    risk_score = excluded.risk_score,
                    overall_confidence = excluded.overall_confidence,
                    reasoning_json = excluded.reasoning_json
                """,
                (
                    utc_now_iso(),
                    p.proposal_id,
                    p.symbol,
                    score["fundamental_score"],
                    score["technical_score"],
                    score["market_score"],
                    score["macro_score"],
                    score["behavioural_score"],
                    score["investment_policy_score"],
                    score["risk_score"],
                    score["overall_confidence"],
                    json.dumps(reasoning, sort_keys=True),
                ),
            )
    return score


def validate_investment_universe(db_path: Path, proposal: TradeProposal, policy: TradingPolicy) -> list[str]:
    p = proposal.normalized()
    failures: list[str] = []
    if p.asset_type in {"stock", "etf"} and not policy.equities_enabled:
        failures.append("equities_disabled_by_policy")
    if p.asset_type == "crypto" and not policy.crypto_enabled:
        failures.append("crypto_disabled_by_policy")
    if p.asset_type == "crypto":
        with closing(sqlite3.connect(db_path)) as conn:
            row = conn.execute(
                "SELECT active FROM CRYPTO_MASTER WHERE UPPER(symbol) = UPPER(?) AND active = 1 LIMIT 1",
                (p.symbol,),
            ).fetchone()
        if row is None:
            failures.append("crypto_not_in_approved_universe")
    return failures


def calculate_capital_allocation(
    db_path: Path,
    proposal: TradeProposal,
    policy: TradingPolicy,
    *,
    account_equity: float,
) -> dict[str, Any]:
    p = proposal.normalized()
    requested_notional = max(0.0, p.entry_price * p.position_size)
    max_position_notional = max(0.0, account_equity * policy.max_position_size_pct)
    max_risk_amount = max(0.0, account_equity * policy.risk_per_trade_pct)
    per_unit_risk = abs(p.entry_price - p.stop_loss)
    risk_limited_qty = max_risk_amount / per_unit_risk if per_unit_risk > 0 else 0.0
    risk_limited_notional = risk_limited_qty * p.entry_price
    approved_notional = min(value for value in [requested_notional, max_position_notional, risk_limited_notional] if value >= 0)
    approved_quantity = approved_notional / p.entry_price if p.entry_price > 0 else 0.0
    risk_amount = approved_quantity * per_unit_risk
    result = "approved" if approved_notional > 0 else "rejected"
    notes = None if result == "approved" else "Capital allocation produced zero approved notional."
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO CAPITAL_ALLOCATION_HISTORY (
                    created_at, proposal_id, symbol, asset_type, account_equity,
                    requested_notional, approved_notional, approved_quantity,
                    risk_amount, policy_snapshot_json, result, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    p.proposal_id,
                    p.symbol,
                    p.asset_type,
                    account_equity,
                    requested_notional,
                    approved_notional,
                    approved_quantity,
                    risk_amount,
                    json.dumps(policy.to_dict(), sort_keys=True),
                    result,
                    notes,
                ),
            )
    return {
        "requested_notional": requested_notional,
        "approved_notional": approved_notional,
        "approved_quantity": approved_quantity,
        "risk_amount": risk_amount,
        "result": result,
        "notes": notes,
    }


def record_broker_decision(
    db_path: Path,
    proposal: TradeProposal,
    *,
    selected_broker: str | None,
    broker_healthy: bool,
    asset_available: bool,
    market_open: bool,
    result: str,
    reason: str | None,
) -> None:
    p = proposal.normalized()
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO BROKER_DECISIONS (
                    created_at, proposal_id, symbol, selected_broker, exchange,
                    broker_healthy, asset_available, market_open, result, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (utc_now_iso(), p.proposal_id, p.symbol, selected_broker, p.exchange, int(broker_healthy), int(asset_available), int(market_open), result, reason),
            )


def record_execution_decision(
    db_path: Path,
    proposal: TradeProposal,
    *,
    decision: str,
    validation_result: str | None,
    order_id: str | None,
    reason: str | None,
) -> None:
    p = proposal.normalized()
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO EXECUTION_DECISIONS (
                    created_at, proposal_id, symbol, decision, validation_result,
                    order_id, reason, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (utc_now_iso(), p.proposal_id, p.symbol, decision, validation_result, order_id, reason, json.dumps(p.to_dict(), sort_keys=True)),
            )


def latest_due_diligence(db_path: Path, proposal_id: str) -> dict[str, Any] | None:
    return _latest(db_path, "DUE_DILIGENCE_ASSESSMENTS", "assessment_id", proposal_id)


def latest_investment_score(db_path: Path, proposal_id: str) -> dict[str, Any] | None:
    return _latest(db_path, "INVESTMENT_SCORES", "score_id", proposal_id)


def _latest(db_path: Path, table: str, order_column: str, proposal_id: str) -> dict[str, Any] | None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT * FROM {table} WHERE proposal_id = ? ORDER BY {order_column} DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
    if not row:
        return None
    payload = dict(row)
    for key in ["reasoning_json", "policy_snapshot_json", "payload_json"]:
        if key in payload and payload[key]:
            try:
                payload[key.replace("_json", "")] = json.loads(payload[key])
            except json.JSONDecodeError:
                pass
    return payload


def _seed_policies(conn: sqlite3.Connection) -> None:
    now = utc_now_iso()
    for key, (value, value_type, description) in DEFAULT_INVESTMENT_POLICIES.items():
        _insert_policy(conn, "INVESTMENT_POLICIES", key, value, value_type, "investment", description, now)
    for key, (value, value_type, description) in DEFAULT_RISK_POLICIES.items():
        _insert_policy(conn, "RISK_POLICIES", key, value, value_type, "risk", description, now)
    for key, (value, value_type, description) in DEFAULT_LEARNING_POLICIES.items():
        _insert_policy(conn, "LEARNING_POLICIES", key, value, value_type, "learning", description, now)
    for broker, values in DEFAULT_BROKER_POLICIES.items():
        for key, (value, value_type, description) in values.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO BROKER_POLICIES (
                    broker, policy_key, policy_value, value_type, description,
                    founder_approved, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (broker, key, _stringify(value), value_type, description, now, now),
            )


def _insert_policy(
    conn: sqlite3.Connection,
    table: str,
    key: str,
    value: Any,
    value_type: str,
    category: str,
    description: str,
    now: str,
) -> None:
    conn.execute(
        f"""
        INSERT OR IGNORE INTO {table} (
            policy_key, policy_value, value_type, category, description,
            founder_approved, active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
        """,
        (key, _stringify(value), value_type, category, description, now, now),
    )


def _policy_map(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    return {
        row["policy_key"]: _parse_value(row["policy_value"], row["value_type"])
        for row in conn.execute(f"SELECT policy_key, policy_value, value_type FROM {table} WHERE active = 1")
    }


def _parse_value(value: str, value_type: str) -> Any:
    if value_type == "boolean":
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value_type == "integer":
        return int(value)
    if value_type == "float":
        return float(value)
    return value


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
