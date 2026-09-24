import ast
import inspect
import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from test_experiments import db, create
from ai_trader import experiments as e, experiment_worker as w
from ai_trader.canonical_trades import _precise_kraken_fill
from ai_trader.conversation_learning import daily_summary
from ai_trader.symbol_track_record import _symbol_totals, symbol_history_packet


def test_postgres_query_has_no_literal_percent_comments(tmp_path, monkeypatch):
    import ai_trader.symbol_track_record as s
    from ai_trader.database import _postgres_sql
    captured = []
    class Conn:
        def execute(self, sql, args):
            converted = _postgres_sql(sql)
            assert '%' not in converted.replace('%s', '')
            assert "broker='kraken'" in sql and 'GROUP BY symbol' in sql
            captured.append(sql)
            return self
        def fetchall(self): return [('XBTGBP', 1, 0, 2.0), ('BTC', 0, 1, -1.0)]
        def close(self): pass
    monkeypatch.setattr(s, 'connect', lambda _: Conn())
    monkeypatch.setattr(s, 'uses_postgres', lambda: True)
    assert _symbol_totals(tmp_path/'unused')['BTC'] == (1,1,1.0)
    assert len(captured) == 1


def test_readonly_daily_separates_currency_and_gross_basis(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_TRADER_DATABASE_BACKEND','sqlite')
    p=tmp_path/'daily.db'
    with sqlite3.connect(p) as c:
        c.execute('CREATE TABLE PERFORMANCE_ATTRIBUTION(broker TEXT,created_at TEXT,profit_loss REAL)')
        c.executemany('INSERT INTO PERFORMANCE_ATTRIBUTION VALUES(?,?,?)',[
            ('kraken','2026-09-24T12:00:00+00:00',-1.196),('alpaca','2026-09-24T13:00:00+00:00',-21.56)])
    result=daily_summary(p,'2026-09-24')
    assert result['total_profit_loss'] is None
    assert {r['currency'] for r in result['by_broker']} == {'GBP','USD'}
    assert result['by_broker'][0]['cost_basis']=='gross_before_unverified_costs'
    with sqlite3.connect(p) as c:
        assert c.execute('SELECT COUNT(*) FROM PERFORMANCE_ATTRIBUTION').fetchone()[0]==2


def test_full_and_fast_context_cannot_call_daily_maintenance():
    from ai_trader.api import LocalApiService
    tree=ast.parse(inspect.getsource(LocalApiService).strip())
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_build_ask_ai_context')
    called={getattr(n.func,'attr',getattr(n.func,'id','')) for n in ast.walk(method) if isinstance(n,ast.Call)}
    assert 'daily_learning_update' not in called
    assert 'daily_summary' in called
    assert not {'resolve_shadow_trades','review_strategies_for_demotion','update_calibration_from_attribution'} & called


def test_original_fill_precision_is_not_a_dust_tolerance():
    def fill(q, original, role='trade_fill'):
        return dict(broker='kraken',quantity=q,payload_json=json.dumps(dict(record_type=role,filled_quantity=original)))
    entries=[_precise_kraken_fill(fill(.0367573983967304,'0.0367574')),
             _precise_kraken_fill(fill(.201700001955032,'0.2017'))]
    exit=_precise_kraken_fill(fill(.238457396626472,'0.2384574'))
    assert abs(sum(x['quantity'] for x in entries)-exit['quantity'])<1e-12
    assert _precise_kraken_fill(fill(2,'1'))['quantity']==2
    assert _precise_kraken_fill(fill(2,'1.9999999','order_snapshot'))['quantity']==2


def test_pooler_short_text_is_not_mistaken_for_corrupt_fill():
    from ai_trader.canonical_trades import _refresh_trade_aggregate
    # Observed on production: REAL text 19.9322, actual float32 cast to float64
    # 19.932243347168. Do not widen the guard to accept the shortened text.
    row=dict(broker='kraken',quantity=19.932243347168,
             payload_json=json.dumps(dict(record_type='trade_fill',filled_quantity='19.93224263')))
    assert _precise_kraken_fill(row)['quantity']==19.93224263
    assert 'CAST(quantity AS DOUBLE PRECISION)' in inspect.getsource(_refresh_trade_aggregate)


def test_blocked_reference_cursor_does_not_pin_other_test(db, monkeypatch):
    row=create(db)
    with e.transaction(db) as c:
        e.put_control(c,'policy',{**e.DEFAULT_POLICY,'enabled':True})
        base=e._load(c,row['id'])
        base['state']['cursor']=20
        e._save(c,base)
        spec=deepcopy(base['spec']);spec['rule_type']='reference_set_filter'
        state=deepcopy(base['state']);state['cursor']=0
        c.execute('INSERT INTO RULE_EXPERIMENTS VALUES(?,?,?,?,?,?,?,?,?)',
            ('waiting','founder',base['created_at'],e.digest(spec),'shadow_running',0,e.dump(spec),'{}',e.dump(state)))
        for i in range(1,22):
            c.execute('INSERT INTO DECISION_JOURNAL VALUES(?,?,?,?,?,?,?)',
                (i,'2026-09-01T12:00:00+00:00',f'p{i}','ABC','alpaca','eligible',json.dumps({'proposal':{'entry_price':100,'stop_loss':90,'take_profit':130,'side':'buy'}})))
    monkeypatch.setattr('ai_trader.reference_sets.pair',lambda *a,**k: None)
    w.tick(db,None,now='2026-09-01T08:00:00+00:00')
    result=e.detail(db,row['id'])
    assert result['state']['cursor']==21
    assert result['opportunities'][0]['source_id']=='p21'
    assert e.detail(db,'waiting')['state']['cursor']==0


def test_rejections_do_not_spend_comparison_slots(db):
    row=create(db)
    with e.transaction(db) as c:
        e.put_control(c,'policy',{**e.DEFAULT_POLICY,'enabled':True,'opportunities_per_day':1})
        for i in range(1,3):
            payload={'proposal':{'entry_price':100,'stop_loss':90,'take_profit':130,'side':'buy'},
                     'reasons':['stop_loss_too_tight'] if i==1 else []}
            c.execute('INSERT INTO DECISION_JOURNAL VALUES(?,?,?,?,?,?,?)',
                (i,'2026-09-01T12:00:00+00:00',f'p{i}','ABC','alpaca','blocked' if i==1 else 'eligible',json.dumps(payload)))
    w.tick(db,None,now='2026-09-01T08:00:00+00:00')
    result=e.detail(db,row['id'])
    assert len(result['opportunities'])==1 and result['opportunities'][0]['source_id']=='p2'
    assert result['state']['admission_rejections']['stop_loss_too_tight']==1
    assert not e.admissible(row['spec'],False,['stop_loss_too_tight'])


def load_tool(name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,Path('tools')/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_admission_rollout_preserves_old_observations_and_budget(db):
    from test_experiments import op
    row=create(db)
    e.add_opportunity(db,row['id'],op())
    with e.transaction(db) as c:
        old=e._load(c,row['id']);old['spec'].pop('admission_policy')
        c.execute('UPDATE RULE_EXPERIMENTS SET spec_json=? WHERE id=?',(e.dump(old['spec']),row['id']))
        e.put_control(c,'proposal_attempt',{'day':'2026-09-02','status':'used'})
    tool=load_tool('readiness_rollout')
    assert len(tool.rollout(db,now='2026-09-02T00:00:00+00:00')['experiments'])==1
    result=tool.rollout(db,apply=True,now='2026-09-02T00:00:00+00:00')
    new=e.detail(db,result['experiments'][0]['replacement'])
    assert new['spec']['admission_policy']=='informative-first-v1' and not new['opportunities']
    assert len(e.detail(db,row['id'])['opportunities'])==1
    with e.transaction(db) as c:assert e.control(c,'proposal_attempt')['status']=='used'
    assert tool.rollout(db,apply=True)['status']=='already_applied'


def test_exact_closure_repair_is_bounded_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_TRADER_DATABASE_BACKEND','sqlite')
    from test_kraken_reconciliation import trade_fill
    from ai_trader.kraken_reconciliation import initialize_kraken_reconciliation_schema, register_kraken_order_ownership, replay_kraken_evidence
    p=tmp_path/'repair.db';initialize_kraken_reconciliation_schema(p);e.migrate(p)
    for order,role in [('entry','entry'),('exit','exit')]:
        register_kraken_order_ownership(p,broker_order_id=order,logical_trade_id='owned',order_role=role,
            symbol='XRPGBP',side='buy' if role=='entry' else 'sell')
    replay_kraken_evidence(p,events=[trade_fill('entry','f1','buy',1,'2026-09-01T10:00:00Z'),
        trade_fill('exit','f2','sell',1.1,'2026-09-02T10:00:00Z')])
    with e.transaction(p) as c:
        c.execute("UPDATE LOGICAL_TRADES SET terminal=0,state='open',remaining_quantity=.0000004 WHERE logical_trade_id='owned'")
    tool=load_tool('repair_verified_kraken_closures')
    assert tool.repair(p)['items'][0]['status']=='verified_exact_fill_balance'
    result=tool.repair(p,apply=True)
    assert result['items'][0]['status']=='repaired_and_learning_queued_or_existing'
    assert tool.repair(p,apply=True)['items']==[]
    with e.transaction(p) as c:
        assert c.execute('SELECT COUNT(*) FROM LOGICAL_TRADE_FILLS').fetchone()[0]==2
        assert c.execute('SELECT COUNT(*) FROM SPRINT6_WORKFLOW_OUTBOX').fetchone()[0]==1
        assert c.execute("SELECT closed_at FROM LOGICAL_TRADES WHERE logical_trade_id='owned'").fetchone()[0].startswith('2026-09-02')
