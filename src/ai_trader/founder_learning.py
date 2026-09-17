"""Plain-English Founder scorecard derived only from verified learning evidence."""
from __future__ import annotations

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
    headline = "Improvement verified" if verified else (
        "Candidate improvement detected" if candidate else "Learning activity only"
    )
    history_trials = historical.get("trials") or []
    scorecard = dict(
        day=now[:10], at=now, headline=headline,
        more_capable=bool(history_trials or measurement.get("at")),
        learned_something=bool(statuses.get("recommended", 0) or statuses.get("rejected", 0)),
        trading_better=verified,
        experiments=dict(running=statuses.get("shadow_running", 0), queued=statuses.get("queued", 0),
            recommended=statuses.get("recommended", 0), rejected=statuses.get("rejected", 0),
            insufficient=statuses.get("insufficient_evidence", 0), superseded=baseline_changes,
            adopted=adopted),
        historical=dict(status=historical.get("status", "awaiting_first_screen"),
            candidates=len(history_trials), promising=sum(t.get("status") == "promising" for t in history_trials),
            data_required=sum(t.get("status") == "data_required" for t in history_trials)),
        supported_forward_comparisons=len(supported),
        evidence_note=("Trading improvement is shown only after a frozen candidate beats its baseline after costs "
                       "and remains supported after controlled paper adoption."),
    )
    if verified:
        reflection = (f"I have verified improvement in {len(supported)} forward comparison(s), with "
                      f"{adopted} controlled adopted version(s). I am still monitoring after-cost results and risk.")
    elif candidate:
        reflection = (f"I found {len(supported) + statuses.get('recommended', 0)} candidate improvement signal(s), "
                      "but I have not yet proved that I am trading better. Forward and adoption evidence is still required.")
    elif history_trials or statuses.get("shadow_running", 0):
        reflection = (f"I am more capable because I can screen recorded ideas against cached market history and I am "
                      f"tracking {statuses.get('shadow_running', 0)} forward experiment(s). I have not yet proved better trading performance.")
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
