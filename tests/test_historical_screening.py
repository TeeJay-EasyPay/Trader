from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import pytest
from test_experiments import db, create, op, bar
from ai_trader import experiments as e
from ai_trader import historical_screening as h
from ai_trader import learning_measurement as m


def spec():
    return e.validate_spec(dict(broker='alpaca',rule_type='minimum_target_r',threshold=2.5,
        evidence_ids=[1],hypothesis='Test larger target distances on recorded opportunities.'))


def test_replay_uses_next_bar_and_costs_without_mutation():
    signal=op(target=130)
    bars=[bar(2)]
    original=deepcopy((signal,bars))
    result=h.replay(spec(),[signal],bars,cutoff=bars[0]['end'])
    assert result['unresolved']==1 and result['open_positions']['baseline']==1
    assert result['estimated_costs']['baseline']>0
    assert (signal,bars)==original
    assert h.replay(spec(),[signal],bars,cutoff=signal['time'])['opportunities']==0
    assert h.replay(spec(),[signal],bars,cutoff=bars[0]['start'])['estimated_costs']['baseline']==0


def test_replay_is_deterministic_and_conservative():
    bars=[{**bar(2),'low':85,'high':135}]
    result=h.replay(spec(),[op(target=130)],bars,cutoff=bars[0]['end'])
    assert result==h.replay(spec(),[op(target=130)],list(reversed(bars)),cutoff=bars[0]['end'])
    assert result['baseline_net']<0 and result['uncertain']==1
    assert result['completed_trade_pairs']==0
    stress=h.replay(spec(),[op(target=130)],bars,cutoff=bars[0]['end'],cost_multiplier=2)
    assert stress['estimated_costs']['baseline']>result['estimated_costs']['baseline']


def test_no_fake_history_or_reference_reconstruction():
    result=h.screen(spec(),dict(signals=[],bars=[]),'2026-09-16T12:00:00+00:00')
    assert result['status']=='data_required'
    reference={**spec(),'rule_type':'reference_set_filter'}
    assert h.screen(reference,dict(signals=[],bars=[]),'2026-09-16T12:00:00+00:00')['status']=='unsupported'
    with pytest.raises(ValueError):
        h.replay(reference,[op()],[],cutoff='2026-10-01T00:00:00+00:00')


def test_skip_not_counted_as_completed_trade():
    result=h.replay(spec(),[{**op(),'eligible':False}],[],cutoff='2026-10-01T00:00:00+00:00')
    assert result['resolved']==1 and result['completed_trade_pairs']==0


def test_dataset_and_daily_batch_read_once_no_live_mutation(db,monkeypatch):
    row=create(db)
    e.add_opportunity(db,row['id'],op(target=130))
    e.settle_bars(db,row['id'],[bar(2)],now='2026-09-04T00:00:00+00:00')
    before=e.detail(db,row['id'])
    calls=[]
    original=h.dataset
    def load(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(h,'dataset',load)
    result=h.screen_batch(db,[spec(),{**spec(),'threshold':3}], '2026-09-16T00:00:00+00:00')
    assert result['status']=='completed' and len(calls)==1
    assert all(t['status']=='data_required' for t in result['trials'])
    assert result==h.screen_batch(db,[spec()], '2026-09-16T12:00:00+00:00')
    assert len(calls)==1
    assert e.detail(db,row['id'])==before


def test_dataset_accepts_identical_provider_bar_with_provenance(db, monkeypatch):
    signal = op()
    recorded = bar(2)
    monkeypatch.setattr(h, 'recorded_signals', lambda *args: [signal])
    monkeypatch.setattr(h, 'recorded_bars', lambda *args: [recorded])
    provider = {**recorded, 'source': 'kraken_public_exact_gbp_pair'}

    with e.transaction(db) as conn:
        result = h.dataset(conn, 'kraken', '2026-09-16T00:00:00+00:00', [provider])

    assert len(result['signals']) == 1
    assert len(result['bars']) == 1
    assert result.get('reason') is None


def test_dataset_rejects_genuinely_conflicting_provider_price(db, monkeypatch):
    signal = op()
    recorded = bar(2)
    monkeypatch.setattr(h, 'recorded_signals', lambda *args: [signal])
    monkeypatch.setattr(h, 'recorded_bars', lambda *args: [recorded])
    provider = {**recorded, 'close': recorded['close'] + 1,
                'source': 'kraken_public_exact_gbp_pair'}

    with e.transaction(db) as conn:
        result = h.dataset(conn, 'kraken', '2026-09-16T00:00:00+00:00', [provider])

    assert result['signals'] == [] and result['bars'] == []
    assert result['reason'] == 'Conflicting provider-cache bars'


def test_force_refresh_replays_same_day_without_model_budget(db, monkeypatch):
    create(db)
    calls=[]
    monkeypatch.setattr(h, 'screen_batch', lambda database, candidates, now, force=False:
        calls.append((len(candidates), force)) or {'status':'completed','trials':[]})
    result=h.refresh_active_screening(db, object(), '2026-09-18T03:20:00+00:00')
    assert result['status']=='completed' and result['model_calls']==0
    assert calls==[(1, True)]


def test_temporal_split_purges_and_never_force_closes(monkeypatch):
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    signals=[op(source=str(i),time=(start+timedelta(days=i)).isoformat()) for i in range(60)]
    windows=[]
    def replay(s, records, bars, **kw):
        windows.append((records,kw))
        return dict(completed_trade_pairs=0,independent_days=0,unresolved=len(records),uncertain=0)
    monkeypatch.setattr(h,'replay',replay)
    result=h.screen(spec(),dict(signals=signals,bars=[]),'2026-04-01T00:00:00+00:00')
    split=e.stamp(result['split_at'])
    assert all(e.stamp(s['time'])<split-timedelta(days=11) for s in windows[0][0])
    assert all(e.stamp(s['time'])>=split for s in windows[1][0])
    assert result['status']=='data_required' and windows[2][1]['cost_multiplier']==2


def test_daily_weekly_measurement_keeps_versions_and_currency_separate(db):
    row=create(db)
    with e.transaction(db) as c:
        c.execute('UPDATE RULE_EXPERIMENTS SET report_json=? WHERE id=?',
            (e.dump(dict(completed=2,baseline={'realised':-5},candidate={'realised':-3})),row['id']))
    first=m.refresh(db,'2026-09-01T00:00:00+00:00')
    assert first['periods']['weekly']['status']=='collecting_baseline'
    with e.transaction(db) as c:
        c.execute('UPDATE RULE_EXPERIMENTS SET report_json=? WHERE id=?',
            (e.dump(dict(completed=4,baseline={'realised':-6},candidate={'realised':-2})),row['id']))
    later=m.refresh(db,'2026-09-08T00:00:00+00:00')
    comparison=later['periods']['weekly']['comparisons'][0]
    assert comparison['delta_change']==2 and comparison['new_resolved_pairs']==2
    assert comparison['status']=='not_established'
    assert m.differences({**later,'experiments':[{**later['experiments'][0],'version':'changed'}]},first)==[]
    assert m.refresh(db,'2026-09-08T12:00:00+00:00')==later


def test_budget_limit(db):
    with pytest.raises(ValueError,match='limit'):
        h.screen_batch(db,[spec()]*11,'2026-09-01T00:00:00+00:00')


def test_cache_content_addressing_and_capacity(tmp_path,monkeypatch):
    data=dict(signals=[],bars=[])
    version=h.freeze_dataset(tmp_path/'db',data)
    assert h.freeze_dataset(tmp_path/'db',data)==version
    assert len(list((tmp_path/'research-cache').glob('*.json')))==1
    monkeypatch.setattr(h,'MAX_CACHE_BYTES',1)
    with pytest.raises(ValueError,match='capacity'):
        h.freeze_dataset(tmp_path/'db',dict(signals=[],bars=[{'x':1}]))


def test_identical_signals_do_not_multiply_samples():
    signal=op(target=130)
    bars=[{**bar(2),'low':85}]
    one=h.replay(spec(),[signal],bars,cutoff=bars[0]['end'])
    two=h.replay(spec(),[signal,deepcopy(signal)],bars,cutoff=bars[0]['end'])
    assert one==two


def test_screening_requires_all_frozen_checks(monkeypatch):
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    data=dict(signals=[op(source=str(i),time=(start+timedelta(days=i)).isoformat()) for i in range(60)],bars=[])
    good=dict(completed_trade_pairs=12,independent_days=6,unresolved=0,uncertain=0,
              delta=2,candidate_net=4,drawdown=dict(candidate=.01,baseline=.02))
    monkeypatch.setattr(h,'replay',lambda *args,**kwargs:deepcopy(good))
    assert h.screen(spec(),data,'2026-04-01T00:00:00+00:00')['status']=='promising'
    def stressed(*args,**kwargs):
        return {**good,'delta':-1 if kwargs.get('cost_multiplier')==2 else 2}
    monkeypatch.setattr(h,'replay',stressed)
    assert h.screen(spec(),data,'2026-04-01T00:00:00+00:00')['status']=='not_supported'


def test_weak_historical_candidate_never_enters_forward_queue(db,monkeypatch):
    from ai_trader.experiment_batch import propose_batch
    monkeypatch.setattr(h,'screen',lambda *args:dict(status='not_supported',reason='After-cost result negative',broker='alpaca'))
    result=propose_batch(db,None,'2026-09-16T01:00:00+00:00',
        {**e.DEFAULT_POLICY,'model_enabled':True},lambda *args:json.dumps({'proposals':[spec()]}))
    assert result['accepted']==[]
    assert 'After-cost result negative' in result['rejected'][0]['reason']
    with e.transaction(db) as c:
        assert c.execute('SELECT COUNT(*) FROM RULE_EXPERIMENTS').fetchone()[0]==0
        assert e.control(c,'historical_screening_history')[0]['trials'][0]['status']=='not_supported'


def test_failed_freeze_does_not_allow_next_candidate_to_bypass_cache(db,monkeypatch):
    monkeypatch.setattr(h,'freeze_dataset',lambda *args:(_ for _ in ()).throw(ValueError('cache full')))
    result=h.screen_batch(db,[spec(),{**spec(),'threshold':3}], '2026-09-16T00:00:00+00:00')
    assert [t['status'] for t in result['trials']]==['invalid','invalid']


def test_measurement_api_reads_compact_views_without_refresh(db,monkeypatch):
    from ai_trader import experiment_api
    m.refresh(db,'2026-09-16T00:00:00+00:00')
    monkeypatch.setattr('ai_trader.strategy_intake.list_sources',lambda db:[])
    monkeypatch.setattr(m,'refresh',lambda *args:pytest.fail('Read endpoint refreshed measurements'))
    code,result=experiment_api.get(db,'/experiments',{})
    assert code==200 and 'experiments' not in result['learning_measurement']
    code,result=experiment_api.get(db,'/experiment-notifications',{})
    assert code==200 and result['learning_measurement'] is None
