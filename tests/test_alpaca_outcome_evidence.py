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
