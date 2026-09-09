"""Compact read-only learning coverage. Job completion is not proof of trading skill."""
from contextlib import closing
from pathlib import Path

from .database import connect


def learning_health_snapshot(db_path: Path, *, connection_factory=connect, placeholder="?") -> dict:
    """Two grouped reads; no schema bootstrap, history payload export, or trading action."""
    if placeholder not in {"?", "%s"}:
        raise ValueError("Unsupported SQL placeholder")
    with closing(connection_factory(db_path)) as conn:
        rows = conn.execute(f"""
            SELECT t.broker, COUNT(*) AS terminal_trades,
                   SUM(CASE WHEN l.learning_run_id IS NOT NULL THEN 1 ELSE 0 END) AS learning_runs,
                   SUM(CASE WHEN l.status = 'completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN l.experience_id IS NOT NULL AND r.review_id IS NOT NULL THEN 1 ELSE 0 END) AS linked_reviews,
                   SUM(CASE WHEN r.payload_json LIKE {placeholder} THEN 1 ELSE 0 END) AS corrected_reviews,
                   SUM(CASE WHEN t.net_pnl IS NOT NULL THEN 1 ELSE 0 END) AS known_net_results,
                   SUM(CASE WHEN t.net_pnl > 0 THEN 1 ELSE 0 END) AS net_wins,
                   SUM(CASE WHEN t.net_pnl < 0 THEN 1 ELSE 0 END) AS net_losses,
                   MAX(t.closed_at) AS last_close, MAX(l.created_at) AS last_learning
            FROM LOGICAL_TRADES t
            LEFT JOIN CLOSED_LOOP_LEARNING_RUNS l ON l.logical_trade_id = t.logical_trade_id
            LEFT JOIN POST_TRADE_REVIEWS r ON r.review_id = l.review_id
            WHERE t.terminal = 1 GROUP BY t.broker
        """, ('%"classification_version": "net-evidence-v2"%',)).fetchall()
        columns = ['broker','terminal_trades','learning_runs','completed','linked_reviews','corrected_reviews',
                   'known_net_results','net_wins','net_losses','last_close','last_learning']
        brokers = [{key: row[index] for index, key in enumerate(columns)} for row in rows]
        queued = conn.execute("""
            SELECT COALESCE(t.broker, 'unknown'), o.status, COUNT(*)
            FROM SPRINT6_WORKFLOW_OUTBOX o
            LEFT JOIN LOGICAL_TRADES t ON t.logical_trade_id = o.entity_id
            WHERE o.workflow_type = 'closed_loop_learning'
            GROUP BY COALESCE(t.broker, 'unknown'), o.status
        """).fetchall()
    return {'brokers': brokers, 'workflow_counts': [{key: row[index] for index, key in enumerate(['broker','status','count'])} for row in queued],
            'improvement_status': 'not_established',
            'explanation': 'Coverage shows whether closed trades reached learning. Improved trading requires a prospective baseline comparison; these counts do not prove it.'}
