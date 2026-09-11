import json
from copy import deepcopy
from datetime import timedelta
import pytest
from test_experiments import db, create, op, bar
from ai_trader import experiments as e
from ai_trader import experiment_assurance as a


def test_replacement_can_shadow_a_rejected_strategy_but_not_safety(db):
    spec = dict(rule_type='replace_target_r_gate', threshold=1.1, evidence_ids=[1],
                hypothesis='Test a lower target risk threshold in shadow only.')
    row = e.create_experiment(db, spec, now='2026-09-01T00:00:00+00:00')
    for i, reasons in enumerate([['reward_risk_below_minimum'], ['reward_risk_below_minimum','fees_unknown'], None]):
        item = op('p' + str(i), symbol='XYZ' + str(i), target=115)
        item.update(eligible=False, rejection_reasons=reasons)
        e.add_opportunity(db, row['id'], item)
    ops = sorted(e.detail(db, row['id'])['opportunities'], key=lambda x: x['symbol'])
    assert ops[0]['arms']['baseline']['status'] == 'skipped'
    assert ops[0]['arms']['candidate']['status'] == 'awaiting_bar'
    assert all(o['arms']['candidate']['status'] == 'skipped' for o in ops[1:])


def test_queue_freezes_start_and_cursor_when_slot_opens(db):
    first = create(db)
    queued = e.create_experiment(db, first['spec'], queue=True, now='2026-09-02T00:00:00+00:00')
    a.start_queued(db, '2026-09-03T00:00:00+00:00')
    assert e.detail(db, queued['id'])['status'] == 'queued'
    e.decide(db, first['id'], version=first['version'], revision=0, action='suspend', key='suspend-first')
    a.start_queued(db, '2026-09-04T00:00:00+00:00')
    started = e.detail(db, queued['id'])
    assert started['created_at'] == '2026-09-04T00:00:00+00:00'
    assert started['state']['queued_at'] == queued['created_at']
    assert started['version'] != queued['version']
    assert started['status'] == 'shadow_running'


def test_kraken_separate_currency_costs_and_fractional_virtual_quantity(db):
    with e.transaction(db) as c:
        c.execute("UPDATE PERFORMANCE_ATTRIBUTION SET broker='kraken' WHERE attribution_id=1")
    row = e.create_experiment(db, dict(rule_type='minimum_target_r', threshold=2, broker='kraken',
        evidence_ids=[1], hypothesis='Test a GBP crypto rule without broker orders.'), now='2026-09-01T00:00:00+00:00')
    assert row['spec']['currency'] == 'GBP' and row['spec']['cost_bps_per_leg'] == 80
    item = op(symbol='BTCGBP'); item.update(entry=100000,stop=90000,target=130000)
    e.add_opportunity(db, row['id'], item)
    candle = bar(); candle.update(symbol='BTCGBP',open=100000,high=105000,low=95000,close=102000)
    result = e.settle_bars(db, row['id'], [candle], now='2026-09-03T01:00:00+00:00')
    assert 0 < result['state']['baseline']['positions']['BTCGBP']['quantity'] < 1
    assert result['report']['currency'] == 'GBP'


def paired():
    ops, actual = [], {}
    for i in range(20):
        item = op(str(i)); item['uncertain'] = False
        item['arms'] = {'baseline':dict(status='closed', entry=100, exit=110, quantity=1, cost=1,
            entered_at='2026-09-02T00:00:00+00:00', exited_at='2026-09-03T00:00:00+00:00')}
        ops.append(item)
        actual[str(i)] = [dict(attribution_id=i,quantity=1,entry_price=100,exit_price=110,
            opened_at='2026-09-02T00:00:00+00:00',closed_at='2026-09-03T00:00:00+00:00',fees=1,fees_status='reconciled')]
    return ops, actual


def test_comparison_requires_costs_and_exact_identity():
    ops, actual = paired()
    assert a.compare(ops, actual)['status'] == 'within_tolerance'
    for values in actual.values():
        values[0]['fees_status'] = 'unknown'
    result = a.compare(ops, actual)
    assert result['status'] == 'divergent' and result['missing_costs'] == 20
    actual['0'] *= 2
    assert a.compare(ops, actual)['ambiguous_matches'] == 1


def test_entry_exit_and_duration_disagreement_are_reported():
    ops, actual = paired()
    actual['0'][0]['entry_price'] = 90
    actual['0'][0]['closed_at'] = '2026-09-06T00:00:00+00:00'
    result = a.compare(ops, actual)
    assert result['within_tolerance'] == 19


def test_unvalidated_simulator_cannot_activate(db, monkeypatch):
    monkeypatch.setenv('EXPERIMENT_PAPER_ADOPTION_ENABLED', 'true')
    row = create(db)
    with e.transaction(db) as c:
        c.execute("UPDATE RULE_EXPERIMENTS SET status='library_approved' WHERE id=?", (row['id'],))
    with pytest.raises(ValueError, match='comparison'):
        e.decide(db,row['id'],version=row['version'],revision=0,action='enable_paper',key='activate-test',scope={})


def test_monitor_suspends_expired_version_without_orders(db):
    row = create(db)
    with e.transaction(db) as c:
        row['status'] = 'paper_active'
        row['state']['activation'] = dict(version=row['version'], expires_at='2026-09-02T00:00:00+00:00', max_notional_usd=100)
        e._save(c, row)
    a.monitor_adoptions(db, '2026-09-03T00:00:00+00:00')
    row = e.detail(db, row['id'])
    assert row['status'] == 'suspended'
    assert row['state']['adoption_monitor']['reason'] == 'Approval expired'
    assert e.list_experiments(db, attention=True)['items'][0]['id'] == row['id']


def test_kraken_data_endpoint_is_public_bounded_and_excludes_current_bar(db, monkeypatch):
    from ai_trader import experiment_market_data as m
    from io import BytesIO
    calls = []
    def request(req, timeout):
        assert req.method == 'GET' and '/0/public/OHLC?' in req.full_url
        assert not req.has_header('Authorization')
        calls.append(req.full_url)
        time = int(e.stamp('2026-09-02T00:00:00+00:00').timestamp())
        return BytesIO(json.dumps({'error':[], 'result':{'XXBTZGBP':[[time,100,110,90,105],[time+86400,105,110,100,105]],'last':time}}).encode())
    monkeypatch.setattr(m,'urlopen',request)
    bars = m.kraken_bars(db,['BTCGBP','ETHGBP','ATOMGBP'],'2026-09-03T01:00:00+00:00')
    assert len(calls) == 2 and len(bars) == 2
    m.kraken_bars(db,['BTCGBP'],'2026-09-03T02:00:00+00:00')
    assert len(calls) == 2


def test_latest_exit_evidence_is_retrieved_without_rewriting_experience(db):
    from ai_trader.experience_engine import record_experience, find_historical_analogues
    from ai_trader.proposal_context import _serialize_historical_analogues
    with e.transaction(db) as c:
        c.execute('ALTER TABLE PERFORMANCE_ATTRIBUTION ADD COLUMN exit_reason TEXT')
        c.execute("UPDATE PERFORMANCE_ATTRIBUTION SET exit_reason='Broker stop order filled.' WHERE attribution_id=1")
    original = dict(record_kind='reconciled_reporting_review',source_attribution_id='1',exit_reason='Exit trigger was not recorded')
    record_experience(db,symbol='ABC',broker='alpaca',proposal_id='p1',decision_context={},result_context=original)
    result = find_historical_analogues(db,{'symbol':'ABC'})
    assert 'Broker stop order filled' in _serialize_historical_analogues(result)
    assert json.loads(result['similar_historical_situations'][0]['result_context_json']) == original
    record_experience(db,symbol='ABC',broker='alpaca',proposal_id='p1',decision_context={},result_context={'canonical_closure_verified':True})
    assert find_historical_analogues(db,{'symbol':'ABC'})['comparable_cases'] == 1
