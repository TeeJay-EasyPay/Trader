"""Plain-English Founder scorecard derived only from verified learning evidence."""
from __future__ import annotations

import json

from . import experiments as e


def build(conn, *, now: str) -> dict:
    statuses = {str(r[0]): int(r[1]) for r in conn.execute(
        "SELECT status,COUNT(*) FROM RULE_EXPERIMENTS WHERE owner=? GROUP BY status", ("founder",)
    ).fetchall()}
    baseline_changes = int(conn.execute(
        "SELECT COUNT(*) FROM EXPERIMENT_EVENTS WHERE owner=? AND action='baseline_changed'", ("founder",)
    ).fetchone()[0])
    measurement = e.control(conn, "learning_measurement", {})
    historical = e.control(conn, "historical_screening_view", {})
    comparisons = [item for period in (measurement.get("periods") or {}).values()
                   for item in period.get("comparisons", [])]
    supported = [item for item in comparisons if item.get("status") == "forward_checks_supported"]
    adopted = sum(statuses.get(k, 0) for k in ("paper_active", "ready_for_activation"))
    verified = bool(adopted and supported)
    candidate = bool(statuses.get("recommended", 0) or supported)
    finding_rows = conn.execute(
        "SELECT broker,COUNT(*) FROM LEARNING_FINDINGS "
        "WHERE source_type IN ('historical_screening','experiment_review','trade_review') GROUP BY broker"
    ).fetchall()
    provisional_by_broker = {str(row[0]): int(row[1]) for row in finding_rows}
    provisional_findings = sum(provisional_by_broker.values())
    validated_lesson = bool(statuses.get("recommended", 0) or statuses.get("rejected", 0))
    headline = "Improvement verified" if verified else (
        "Candidate improvement detected" if candidate else "Learning activity only"
    )
    history_trials = historical.get("trials") or []
    broker_progress = {}
    experiment_rows = conn.execute(
        "SELECT status,spec_json FROM RULE_EXPERIMENTS WHERE owner=?", ("founder",)
    ).fetchall()
    for broker in ("alpaca", "kraken"):
        own = []
        for experiment_row in experiment_rows:
            status, spec_json = experiment_row[0], experiment_row[1]
            try:
                if json.loads(spec_json).get("broker") == broker:
                    own.append(str(status))
            except (TypeError, ValueError):
                continue
        own_supported = [item for item in supported if item.get("broker") == broker]
        own_adopted = sum(status in ("paper_active", "ready_for_activation") for status in own)
        own_verified = bool(own_adopted and own_supported)
        own_findings = provisional_by_broker.get(broker, 0)
        broker_progress[broker] = {
            "status": "improvement_verified" if own_verified else (
                "candidate_detected" if own_supported or "recommended" in own else "not_proven"
            ),
            "plain_english": (
                f"Yes—{broker.title()} has a supported comparison and controlled adopted version; after-cost monitoring continues."
                if own_verified else
                f"Not proven yet for {broker.title()}. {own_findings} provisional research finding(s) "
                f"are recorded and {sum(status == 'shadow_running' for status in own)} broker-specific "
                "experiment(s) are running, but no adopted after-cost improvement is verified."
            ),
            "running": sum(status == "shadow_running" for status in own),
            "supported_comparisons": len(own_supported),
            "adopted": own_adopted,
            "provisional_findings": own_findings,
        }
    scorecard = dict(
        day=now[:10], at=now, headline=headline,
        more_capable=bool(history_trials or measurement.get("at")),
        learned_something=bool(validated_lesson or provisional_findings),
        lesson_status="validated" if validated_lesson else "provisional" if provisional_findings else "none",
        provisional_findings=provisional_findings,
        trading_better=verified,
        experiments=dict(running=statuses.get("shadow_running", 0), queued=statuses.get("queued", 0),
            recommended=statuses.get("recommended", 0), rejected=statuses.get("rejected", 0),
            insufficient=statuses.get("insufficient_evidence", 0), superseded=baseline_changes,
            adopted=adopted),
        historical=dict(status=historical.get("status", "awaiting_first_screen"),
            candidates=len(history_trials), promising=sum(t.get("status") == "promising" for t in history_trials),
            data_required=sum(t.get("status") == "data_required" for t in history_trials)),
        supported_forward_comparisons=len(supported),
        brokers=broker_progress,
        evidence_note=("Trading improvement is shown only after a frozen candidate beats its baseline after costs "
                       "and remains supported after controlled paper adoption."),
    )
    if verified:
        reflection = (f"I have verified improvement in {len(supported)} forward comparison(s), with "
                      f"{adopted} controlled adopted version(s). I am still monitoring after-cost results and risk.")
    elif candidate:
        reflection = (f"I found {len(supported) + statuses.get('recommended', 0)} candidate improvement signal(s), "
                      "but I have not yet proved that I am trading better. Forward and adoption evidence is still required.")
    elif history_trials or statuses.get("shadow_running", 0) or provisional_findings:
        reflection = (f"I have recorded {provisional_findings} provisional research finding(s) and I am tracking "
                      f"{statuses.get('shadow_running', 0)} forward experiment(s). These findings help focus testing, "
                      "but I have not yet proved better trading performance on either Alpaca or Kraken; each is "
                      "measured separately.")
    else:
        reflection = "I have not collected enough comparable evidence to claim a new lesson or better trading performance yet."
    return {**scorecard, "reflection": reflection}


def refresh(conn, *, now: str, force: bool = False) -> dict:
    prior = e.control(conn, "founder_learning_scorecard", {})
    if prior.get("day") == now[:10] and not force:
        return prior
    result = build(conn, now=now)
    e.put_control(conn, "founder_learning_scorecard", result)
    history = e.control(conn, "founder_learning_history", [])
    e.put_control(conn, "founder_learning_history", (history + [result])[-35:])
    return result


def fallback(db, *, now: str) -> str:
    with e.transaction(db) as conn:
        return build(conn, now=now)["reflection"]
