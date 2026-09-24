"""Compact, broker-separated evidence handed to Trader.

Trader needs a trustworthy chain from decision to after-cost outcome and learning
record; it does not need thousands of raw audit, lifecycle, fill or experience JSON
documents on every assessment.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import connect, row_values

PACKET_SCHEMA_VERSION = 1


def broker_learning_packets(db_path: Path) -> dict[str, Any]:
    generated = datetime.now(timezone.utc)
    packets: dict[str, Any] = {}
    with closing(connect(db_path)) as conn:
        for broker, asset_class, currency in (("alpaca", "equity", "USD"), ("kraken", "crypto", "GBP")):
            row = conn.execute(
                """SELECT COUNT(*) AS terminal_trades,
                  SUM(CASE WHEN t.net_pnl IS NOT NULL THEN 1 ELSE 0 END) AS net_known,
                  SUM(CASE WHEN t.gross_pnl IS NOT NULL THEN 1 ELSE 0 END) AS gross_known,
                  SUM(CASE WHEN t.gross_pnl IS NOT NULL AND t.net_pnl IS NOT NULL
                            AND t.broker_fee IS NOT NULL AND t.exchange_fee IS NOT NULL
                           THEN 1 ELSE 0 END) AS costs_known,
                  SUM(CASE WHEN l.learning_run_id IS NOT NULL THEN 1 ELSE 0 END) AS linked_learning,
                  SUM(CASE WHEN l.status='completed' AND l.experience_id IS NOT NULL
                               AND l.review_id IS NOT NULL THEN 1 ELSE 0 END) AS complete_loops,
                  SUM(CASE WHEN t.net_pnl>0 THEN 1 ELSE 0 END) AS net_wins,
                  SUM(CASE WHEN t.net_pnl<0 THEN 1 ELSE 0 END) AS net_losses,
                  SUM(t.gross_pnl) AS gross_pnl,
                  SUM(t.broker_fee+t.exchange_fee) AS recorded_costs,
                  SUM(t.net_pnl) AS net_pnl,
                  SUM(CASE WHEN t.gross_pnl IS NOT NULL AND t.net_pnl IS NOT NULL
                            AND ABS(t.gross_pnl-COALESCE(t.broker_fee,0)-COALESCE(t.exchange_fee,0)-t.net_pnl)>0.01
                           THEN 1 ELSE 0 END) AS accounting_mismatches,
                  MIN(CASE WHEN l.status='completed' AND l.experience_id IS NOT NULL
                               AND l.review_id IS NOT NULL THEN t.closed_at END) AS modern_cohort_start,
                  MAX(t.closed_at) AS latest_close, MAX(l.created_at) AS latest_learning
                FROM LOGICAL_TRADES t
                LEFT JOIN CLOSED_LOOP_LEARNING_RUNS l ON l.logical_trade_id=t.logical_trade_id
                WHERE t.broker=? AND t.terminal=1""", (broker,)).fetchone()
            values = row_values(row) if row else (0,) * 15
            columns = ("terminal_trades", "net_known", "gross_known", "costs_known", "linked_learning",
                       "complete_loops", "net_wins", "net_losses", "gross_pnl", "recorded_costs",
                       "net_pnl", "accounting_mismatches", "modern_cohort_start", "latest_close", "latest_learning")
            facts = {name: values[index] if index < len(values) else None for index, name in enumerate(columns)}
            total, complete = int(facts.get("terminal_trades") or 0), int(facts.get("complete_loops") or 0)
            age_hours = _age_hours(facts.get("latest_learning") or facts.get("latest_close"), generated)
            packets[broker] = {
                "schema_version": PACKET_SCHEMA_VERSION, "broker": broker,
                "asset_class": asset_class, "currency": currency,
                "cohort": {"modern_learning_start": facts.get("modern_cohort_start"),
                    "rule": "Only complete canonical decision-to-net-outcome learning loops support improvement claims.",
                    "legacy_trades_retained_for_account_history": max(0, total-complete)},
                "coverage": {"terminal_trades": total, "net_results_known": int(facts.get("net_known") or 0),
                    "gross_results_known": int(facts.get("gross_known") or 0),
                    "recorded_cost_results": int(facts.get("costs_known") or 0),
                    "learning_runs_linked": int(facts.get("linked_learning") or 0),
                    "complete_learning_loops": complete},
                "after_cost_results": {"wins": int(facts.get("net_wins") or 0),
                    "losses": int(facts.get("net_losses") or 0), "gross_pnl": facts.get("gross_pnl"),
                    "recorded_costs": facts.get("recorded_costs"), "net_pnl": facts.get("net_pnl"),
                    "currency": currency, "complete": bool(total and int(facts.get("net_known") or 0)==total),
                    "accounting_mismatches": int(facts.get("accounting_mismatches") or 0),
                    "cost_basis": "canonical broker and exchange fees; no cross-broker estimate"},
                "freshness": {"latest_trade_close": facts.get("latest_close"),
                    "latest_learning": facts.get("latest_learning"), "age_hours": age_hours,
                    "status": "fresh" if age_hours is not None and age_hours <= 36 else "stale_or_no_recent_closure"},
                "limitations": ["Legacy incomplete rows are not used to claim learning progress.",
                                "A linked result proves recorded evidence, not strategy improvement."],
            }
    return {"schema_version": PACKET_SCHEMA_VERSION, "generated_at": generated.isoformat(),
            "brokers": packets, "separation": "Alpaca/USD/equity and Kraken/GBP/crypto are never pooled."}


def _age_hours(value: Any, now: datetime) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return round(max(0.0, (now-parsed.astimezone(timezone.utc)).total_seconds()/3600), 2)
    except (TypeError, ValueError):
        return None
