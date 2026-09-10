"""Bounded outcome-only evidence; never pretend FIFO reporting is a governed trade.

Canonical completed trades still use the full learning outbox. This path preserves
otherwise-unlinked reporting outcomes without inventing stops, fees, or decisions.
"""
from contextlib import closing
import sqlite3
from .database import connect, uses_postgres
from .experience_engine import initialize_experience_engine_schema, record_experience


def review_linked_outcomes(db_path, *, limit=10):
    """Review reporting outcomes with exact decisions; never claim canonical closure.

Fee and broker-stop verification remain unknown. No rule or order is changed.
"""
    import json
    from .production_spine import initialize_production_spine_schema
    from .sprint6 import _ensure_sprint6_schema, enqueue_learning_workflow
    initialize_production_spine_schema(db_path)
    _ensure_sprint6_schema(db_path)
    prefix = "'alpaca-reporting:' || CAST(p.attribution_id AS TEXT)"
    def context_field(path):
        if uses_postgres():
            return "t.decision_context_json::jsonb#>'{" + ','.join(path) + "}'"
        return "json_extract(t.decision_context_json, '$." + '.'.join(path) + "')"
    with closing(connect(db_path)) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(f'''SELECT p.attribution_id,p.proposal_id,p.symbol,p.side,p.quantity,
            p.entry_price,p.exit_price,p.profit_loss,p.opened_at,p.closed_at,p.holding_period_seconds,
            p.exit_reason,p.primary_factors_json,t.intended_entry_price AS intended_entry,t.original_stop,t.intended_target AS target_price,
            {context_field(['intelligence','decision_economics'])} AS decision_economics,
            {context_field(['intelligence','committee'])} AS committee,
            {context_field(['guardrails'])} AS guardrails
            FROM PERFORMANCE_ATTRIBUTION p JOIN LOGICAL_TRADES t
              ON t.proposal_id=p.proposal_id AND t.broker='alpaca'
            WHERE p.broker='alpaca' AND t.original_stop IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM CLOSED_LOOP_LEARNING_RUNS l WHERE l.logical_trade_id={prefix})
              AND NOT EXISTS (SELECT 1 FROM CLOSED_LOOP_LEARNING_RUNS l WHERE l.logical_trade_id=t.logical_trade_id)
              AND NOT EXISTS (SELECT 1 FROM SPRINT6_WORKFLOW_OUTBOX o WHERE o.entity_id={prefix} AND o.workflow_type='closed_loop_learning')
            ORDER BY p.attribution_id LIMIT ?''',(max(1,min(int(limit),100)),)).fetchall()
    completed=[]
    for source in rows:
        r=dict(source)
        factors=json.loads(r['primary_factors_json'] or '{}')
        if factors.get('incomplete_fill_record') or not r['quantity'] or not r['intended_entry']:
            continue
        logical=f"alpaca-reporting:{r['attribution_id']}"
        attribution={k:r[k] for k in ['proposal_id','symbol','side','quantity','entry_price','exit_price','profit_loss','exit_reason']}
        attribution.update(record_kind='reconciled_reporting_review',source_attribution_id=str(r['attribution_id']),
            entry_time=r['opened_at'],exit_time=r['closed_at'],holding_seconds=r['holding_period_seconds'],
            gross_realized_pnl=r['profit_loss'],net_realized_pnl=None,fees_status='unavailable',
            broker_fee=None,exchange_fee=None,canonical_closure_verified=False,
            exit_evidence=factors.get('exit_evidence'))
        decision={'proposal':{'proposal_id':r['proposal_id'],'entry_price':r['intended_entry'],
                  'stop_loss':r['original_stop'],'take_profit':r['target_price'],'side':r['side'],'asset_type':'stock'},
                  'evidence_basis':'exact broker-order decision link; FIFO reporting result',
                  'historical_fee_expectation':'unavailable','stop_activation_verified':False}
        def decoded(value):
            return json.loads(value) if isinstance(value,str) else value
        decision['intelligence']={'decision_economics':decoded(r['decision_economics']),
                                  'committee':decoded(r['committee'])}
        decision['guardrails']=decoded(r['guardrails'])
        result=enqueue_learning_workflow(db_path,logical_trade_id=logical,broker='alpaca',
            payload={'broker':'alpaca','symbol':r['symbol'],'attribution':attribution,'decision_context':decision})
        completed.append({'logical_trade_id':logical,'status':result['status']})
    return {'queued_reporting_reviews':len(completed),'results':completed,'canonical_closure_verified':False,
            'after_cost_improvement':'not_established'}


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
