import json
import sqlite3
from contextlib import closing
import pytest
from ai_trader.production_spine import complete_insufficient_evidence_learning, run_closed_loop_learning


def test_replay_preserves_prior_evidence_and_is_idempotent(tmp_path):
    db=tmp_path/'replay.sqlite'
    complete_insufficient_evidence_learning(db,logical_trade_id='legacy',broker='kraken',symbol='ABC',
        missing=['decision_context'],payload={'original':'preserve'})
    kwargs=dict(logical_trade_id='legacy',broker='kraken',symbol='ABC',
        attribution={'proposal_id':'original','quantity':1,'side':'buy','entry_price':10,'exit_price':11,
                     'profit_loss':1,'net_realized_pnl':0.8,'broker_fee':0,'exchange_fee':0.2,'fees_status':'recorded'},
        decision_context={'proposal':{'entry_price':10,'stop_loss':9,'take_profit':12,'side':'buy'}},
        repair_evidence={'broker_fill_ids':['entry','exit'],'original_proposal_id':'original'})
    result=run_closed_loop_learning(db,**kwargs)
    assert result['status']=='completed'
    assert result['experience']['experience_id'] is not None
    assert run_closed_loop_learning(db,**kwargs)['status']=='duplicate'
    with closing(sqlite3.connect(db)) as c:
        rows=c.execute('SELECT status,payload_json FROM CLOSED_LOOP_LEARNING_RUNS').fetchall()
    assert len(rows)==1
    assert json.loads(rows[0][1])['prior_insufficient_evidence']['source_payload']=={'original':'preserve'}


def test_replay_rejects_missing_exact_identities(tmp_path):
    db=tmp_path/'reject.sqlite'
    complete_insufficient_evidence_learning(db,logical_trade_id='legacy',broker='kraken',symbol='ABC',missing=['decision'],payload={})
    with pytest.raises(ValueError):
        run_closed_loop_learning(db,logical_trade_id='legacy',broker='kraken',symbol='ABC',
            attribution={},decision_context={},repair_evidence={'attempt':True})
