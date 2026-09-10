import json
import sqlite3
from contextlib import closing
from ai_trader.alpaca_learning import capture_outcome_evidence
from ai_trader.proposal_context import reference_provenance


def test_outcomes_are_idempotent_and_do_not_invent_costs_or_decisions(tmp_path):
    db = tmp_path / 'outcomes.sqlite'
    with closing(sqlite3.connect(db)) as c:
        c.executescript('''CREATE TABLE PERFORMANCE_ATTRIBUTION
            (attribution_id INTEGER,proposal_id,symbol,side,entry_price,exit_price,
             quantity,profit_loss,opened_at,closed_at,holding_period_seconds,exit_reason,broker);
            INSERT INTO PERFORMANCE_ATTRIBUTION VALUES
            (1,NULL,'ABC','buy',10,11,1,1,'2026-09-01','2026-09-02',86400,'not recorded','alpaca');''')
    assert capture_outcome_evidence(db)['outcome_only_experiences'] == 1
    assert capture_outcome_evidence(db)['outcome_only_experiences'] == 0
    with closing(sqlite3.connect(db)) as c:
        decision,result = c.execute('SELECT decision_context_json,result_context_json FROM EXPERIENCE_RECORDS').fetchone()
    assert json.loads(decision)['original_stop'] is None
    result = json.loads(result)
    assert result['record_kind'] == 'outcome_only'
    assert result['net_realized_pnl'] is None
    assert result['gross_realized_pnl'] == 1
    from ai_trader.experience_engine import find_historical_analogues
    assert find_historical_analogues(db, {'symbol': 'ABC'})['comparable_cases'] == 0


def test_reference_identity_versions_the_supplied_passage_without_copying_it():
    entry = {'file_path': 'knowledge/sizing.md', 'title': 'Sizing', 'excerpt': 'x' * 1300}
    first = reference_provenance([entry])[0]
    second = reference_provenance([{**entry, 'excerpt': 'x' * 1300 + 'changed'}])[0]
    assert first['document'] == 'sizing.md'
    assert first['document_sha256'] != second['document_sha256']
    assert first['passage_sha256'] == second['passage_sha256']
    assert 'excerpt' not in first


def test_exit_evidence_requires_exact_order_and_unambiguous_stop_type(tmp_path):
    from ai_trader.alpaca_reconciliation import recorded_exit_evidence
    with closing(sqlite3.connect(tmp_path / 'exit.sqlite')) as c:
        c.execute('CREATE TABLE BROKER_TRADE_HISTORY (broker, external_id, payload_json)')
        c.executemany('INSERT INTO BROKER_TRADE_HISTORY VALUES (?,?,?)', [
            ('alpaca', 'stop', '{"type":"stop"}'),
            ('alpaca', 'limit', '{"type":"limit"}'),
            ('alpaca', 'mixed', '{"type":"stop"}'),
            ('alpaca', 'mixed', '{"type":"market"}'),
            ('kraken', 'foreign', '{"type":"stop"}')])
        result = recorded_exit_evidence(c, ['stop', 'limit', 'mixed', 'foreign', 'absent'])
    assert set(result) == {'stop'}
    assert result['stop']['reason'] == 'Broker stop order filled.'


def test_linked_reporting_review_keeps_net_and_canonical_closure_unknown(tmp_path):
    from ai_trader.canonical_trades import register_execution_intent
    from ai_trader.multi_broker import initialize_multi_broker_schema
    from ai_trader.alpaca_learning import review_linked_outcomes
    from test_sprint6_institutional_spine import proposal
    db=tmp_path/'linked.sqlite'
    p=proposal()
    initialize_multi_broker_schema(db)
    register_execution_intent(db,proposal=p,broker='alpaca',decision_context={'proposal':p.to_dict()})
    with closing(sqlite3.connect(db)) as c:
        with c:
            c.execute('''INSERT INTO PERFORMANCE_ATTRIBUTION
                (created_at,proposal_id,broker,symbol,asset_type,side,entry_price,exit_price,
                 quantity,profit_loss,opened_at,closed_at,primary_factors_json)
                VALUES ('2026-09-01',?,'alpaca','AAPL','stock','buy',100,105,1,5,'2026-08-31','2026-09-01','{}')''',(p.proposal_id,))
    assert review_linked_outcomes(db)['queued_reporting_reviews']==1
    assert review_linked_outcomes(db)['queued_reporting_reviews']==0
    from ai_trader.sprint6 import process_learning_outbox
    assert process_learning_outbox(db,worker_id='test')['processed']==1
    with closing(sqlite3.connect(db)) as c:
        result=json.loads(c.execute('SELECT result_context_json FROM EXPERIENCE_RECORDS').fetchone()[0])
        assert c.execute('SELECT terminal FROM LOGICAL_TRADES').fetchone()[0]==0
    assert result['net_realized_pnl'] is None
    assert result['fees_status']=='unavailable'
    assert result['canonical_closure_verified'] is False
