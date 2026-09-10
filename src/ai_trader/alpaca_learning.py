"""Bounded outcome-only evidence; never pretend FIFO reporting is a governed trade.

Canonical completed trades still use the full learning outbox. This path preserves
otherwise-unlinked reporting outcomes without inventing stops, fees, or decisions.
"""
from contextlib import closing
import sqlite3
from .database import connect, uses_postgres
from .experience_engine import initialize_experience_engine_schema, record_experience


def capture_outcome_evidence(db_path, *, limit=25):
    initialize_experience_engine_schema(db_path)
    source_id = "e.result_context_json::jsonb->>'source_attribution_id'" if uses_postgres() else "json_extract(e.result_context_json, '$.source_attribution_id')"
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"""SELECT p.attribution_id,p.proposal_id,p.symbol,p.side,
            p.entry_price,p.exit_price,p.quantity,p.profit_loss,p.opened_at,p.closed_at,
            p.holding_period_seconds,p.exit_reason
            FROM PERFORMANCE_ATTRIBUTION p WHERE p.broker='alpaca' AND p.exit_price IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM EXPERIENCE_RECORDS e WHERE e.broker='alpaca'
                AND {source_id}=CAST(p.attribution_id AS TEXT))
            ORDER BY p.attribution_id LIMIT ?""", (max(1, min(int(limit), 100)),)).fetchall()
    recorded = []
    for source in rows:
        row = dict(source)
        result = record_experience(db_path, symbol=row['symbol'], broker='alpaca', asset_type='stock',
            proposal_id=row['proposal_id'],
            decision_context={'evidence_status': 'not_supplied', 'expected_return': None, 'original_stop': None},
            execution_context={'evidence_basis': 'reporting_fill_pairing_not_verified_canonical_round_trip'},
            result_context={'source_attribution_id': str(row.pop('attribution_id')),
                **row, 'record_kind': 'outcome_only', 'fees_status': 'unavailable',
                'net_realized_pnl': None, 'gross_realized_pnl': row['profit_loss'],
                'exit_trigger_verified': False})
        recorded.append(result['experience_id'])
    return {'status': 'completed', 'outcome_only_experiences': len(recorded),
            'experience_ids': recorded, 'full_learning_completed': False}
