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

from .alpaca_costs import estimate_alpaca_round_trip_cost
from .database import connect, row_values, uses_postgres

PACKET_SCHEMA_VERSION = 2


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
                  SUM(CASE WHEN l.status='completed' THEN 1 ELSE 0 END) AS workflows_completed,
                  SUM(CASE WHEN l.status='completed' AND l.experience_id IS NOT NULL
                               AND l.review_id IS NOT NULL THEN 1 ELSE 0 END) AS reviews_completed,
                  SUM(CASE WHEN l.status='completed' AND l.experience_id IS NOT NULL
                               AND l.review_id IS NOT NULL AND t.net_pnl IS NOT NULL
                           THEN 1 ELSE 0 END) AS complete_loops,
                  SUM(CASE WHEN t.net_pnl>0 THEN 1 ELSE 0 END) AS net_wins,
                  SUM(CASE WHEN t.net_pnl<0 THEN 1 ELSE 0 END) AS net_losses,
                  SUM(t.gross_pnl) AS gross_pnl,
                  SUM(t.broker_fee+t.exchange_fee) AS recorded_costs,
                  SUM(t.net_pnl) AS net_pnl,
                  SUM(CASE WHEN t.gross_pnl IS NOT NULL AND t.net_pnl IS NOT NULL
                            AND ABS(t.gross_pnl-COALESCE(t.broker_fee,0)-COALESCE(t.exchange_fee,0)-t.net_pnl)>0.01
                           THEN 1 ELSE 0 END) AS accounting_mismatches,
                  MIN(CASE WHEN l.status='completed' AND l.experience_id IS NOT NULL
                               AND l.review_id IS NOT NULL AND t.net_pnl IS NOT NULL
                           THEN t.closed_at END) AS modern_cohort_start,
                  MAX(t.closed_at) AS latest_close, MAX(l.created_at) AS latest_learning
                FROM LOGICAL_TRADES t
                LEFT JOIN CLOSED_LOOP_LEARNING_RUNS l ON l.logical_trade_id=t.logical_trade_id
                WHERE t.broker=? AND t.terminal=1""", (broker,)).fetchone()
            values = row_values(row) if row else (0,) * 17
            columns = ("terminal_trades", "net_known", "gross_known", "costs_known", "linked_learning",
                       "workflows_completed", "reviews_completed", "complete_loops",
                       "net_wins", "net_losses", "gross_pnl", "recorded_costs",
                       "net_pnl", "accounting_mismatches", "modern_cohort_start", "latest_close", "latest_learning")
            facts = {name: values[index] if index < len(values) else None for index, name in enumerate(columns)}
            total, complete = int(facts.get("terminal_trades") or 0), int(facts.get("complete_loops") or 0)
            age_hours = _age_hours(facts.get("latest_learning") or facts.get("latest_close"), generated)
            packets[broker] = {
                "schema_version": PACKET_SCHEMA_VERSION, "broker": broker,
                "asset_class": asset_class, "currency": currency,
                "cohort": {"modern_learning_start": facts.get("modern_cohort_start"),
                    "rule": "Only complete canonical decision-to-net-outcome learning loops support improvement claims.",
                    "legacy_trades_retained_for_account_history": max(0, total-int(facts.get("linked_learning") or 0)),
                    "records_excluded_from_improvement_claims": max(0, total-complete)},
                "coverage": {"terminal_trades": total, "net_results_known": int(facts.get("net_known") or 0),
                    "gross_results_known": int(facts.get("gross_known") or 0),
                    "recorded_cost_results": int(facts.get("costs_known") or 0),
                    "learning_runs_linked": int(facts.get("linked_learning") or 0),
                    "workflows_completed": int(facts.get("workflows_completed") or 0),
                    "reviews_completed": int(facts.get("reviews_completed") or 0),
                    "evidence_complete_learning_loops": complete,
                    # Compatibility alias, now deliberately evidence-complete rather than
                    # merely a finished workflow.
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
                "limitations": ["A finished workflow is not labelled an evidence-complete learning loop unless its individual net result is known.",
                                "Legacy incomplete rows are not used to claim learning progress.",
                                "A linked result proves recorded evidence, not strategy improvement."],
            }
            packets[broker]["estimated_after_cost_results"] = (
                _alpaca_estimated_results(conn) if broker == "alpaca" else {
                    "status": "not_needed", "reason": "Kraken canonical rows already carry individually recorded costs."
                }
            )
            packets[broker]["simulation_evidence"] = _simulation_evidence(conn, broker, asset_class, currency)
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


def _alpaca_estimated_results(conn: Any) -> dict[str, Any]:
    """Estimate each missing-net Alpaca result separately, then aggregate compactly.

    This is decision-quality research evidence, not an allocation of account-level FEE
    ledger entries and not a replacement for broker-attributed actual costs.
    """
    try:
        rows = conn.execute(
            """SELECT t.logical_trade_id,t.gross_pnl,t.average_exit_price,
                      t.exit_filled_quantity,t.closed_at
               FROM LOGICAL_TRADES t
               JOIN CLOSED_LOOP_LEARNING_RUNS l ON l.logical_trade_id=t.logical_trade_id
               WHERE t.broker='alpaca' AND t.terminal=1 AND t.gross_pnl IS NOT NULL
                 AND t.net_pnl IS NULL AND l.status='completed'
                 AND l.experience_id IS NOT NULL AND l.review_id IS NOT NULL
               ORDER BY t.closed_at DESC LIMIT 200"""
        ).fetchall()
    except Exception:
        return {"status": "unavailable", "reason": "Per-trade estimate inputs are unavailable."}
    estimates = []
    for row in rows:
        values = row_values(row)
        try:
            gross, exit_price, quantity = float(values[1]), float(values[2]), float(values[3])
            cost = estimate_alpaca_round_trip_cost(
                sell_notional=exit_price * quantity, quantity=quantity
            )["estimated_round_trip_fee_usd"]
        except (TypeError, ValueError, IndexError):
            continue
        estimates.append((gross, float(cost), gross-float(cost)))
    return {
        "status": "estimated_not_broker_attributed" if estimates else "inputs_incomplete",
        "individual_results_estimated": len(estimates),
        "wins": sum(net > 0 for _gross, _cost, net in estimates),
        "losses": sum(net < 0 for _gross, _cost, net in estimates),
        "gross_pnl": round(sum(gross for gross, _cost, _net in estimates), 6) if estimates else None,
        "estimated_regulatory_costs": round(sum(cost for _gross, cost, _net in estimates), 6) if estimates else None,
        "estimated_net_pnl": round(sum(net for _gross, _cost, net in estimates), 6) if estimates else None,
        "currency": "USD", "actual_costs_known": False,
        "cost_basis": "Alpaca published regulatory formula applied separately to each completed trade",
        "excludes": ["account-level FEE allocation", "spread", "slippage"],
        "learning_use": "provisional comparison only; never proof of an actual after-cost edge",
    }


def _simulation_evidence(conn: Any, broker: str, asset_class: str, currency: str) -> dict[str, Any]:
    """Show whether the broker adapter is merely configured or has produced live evidence."""
    statuses: dict[str, int] = {}
    adapter_settled = legacy_unrecoverable = 0
    try:
        rows = conn.execute(
            """SELECT outcome_status,benchmark_outcome,COUNT(*)
               FROM SHADOW_TRADES WHERE intended_broker=?
               GROUP BY outcome_status,benchmark_outcome""", (broker,)
        ).fetchall()
        for row in rows:
            values = row_values(row)
            status, marker, count = str(values[0]), str(values[1] or ""), int(values[2] or 0)
            statuses[status] = statuses.get(status, 0) + count
            if marker.startswith(f"schema:v2:{broker}:"):
                adapter_settled += count
            if marker == "schema:v2:legacy_unrecoverable":
                legacy_unrecoverable += count
    except Exception:
        pass
    active = observations = 0
    try:
        if uses_postgres():
            rows = conn.execute(
                "SELECT id,spec_json::jsonb->>'broker' FROM RULE_EXPERIMENTS "
                "WHERE status='shadow_running' LIMIT 24"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,spec_json FROM RULE_EXPERIMENTS WHERE status='shadow_running' LIMIT 24"
            ).fetchall()
        import json
        broker_experiment_ids = []
        for row in rows:
            values = row_values(row)
            row_broker = values[1] if uses_postgres() else json.loads(values[1]).get("broker")
            if row_broker == broker:
                active += 1
                broker_experiment_ids.append(str(values[0]))
        if broker_experiment_ids:
            placeholders = ",".join("?" for _ in broker_experiment_ids)
            observation_row = conn.execute(
                f"SELECT COUNT(*) FROM EXPERIMENT_OPPORTUNITIES WHERE experiment_id IN ({placeholders})",
                tuple(broker_experiment_ids),
            ).fetchone()
            observations = int(row_values(observation_row)[0] or 0) if observation_row else 0
    except Exception:
        pass
    proof = "adapter_settled_outcomes" if adapter_settled else (
        "modern_forward_observations" if observations else
        "configured_waiting_for_new_outcomes" if active else "no_current_simulation_evidence"
    )
    return {
        "schema_version": 2, "broker": broker, "asset_class": asset_class, "currency": currency,
        "legacy_status_counts": statuses, "legacy_unrecoverable": legacy_unrecoverable,
        "adapter_v2_settled_outcomes": adapter_settled,
        "modern_forward_experiments": active, "modern_forward_observations": observations,
        "modern_observation_definition": "recorded paired-simulation opportunities",
        "production_proof": proof,
        "plain_english": (
            "Old unrecoverable rows remain excluded. New simulations use the broker-specific adapter; "
            "the proof field distinguishes configured code from measured outcomes."
        ),
    }
