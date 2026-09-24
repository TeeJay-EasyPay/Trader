from copy import deepcopy
from test_experiments import db, create, op, bar
from ai_trader import experiments as e
from ai_trader.experiment_batch import propose_batch


def test_rollout_preserves_samples_and_is_idempotent(db):
    import importlib.util
    from pathlib import Path
    module_spec = importlib.util.spec_from_file_location('capacity_rollout', Path('tools/learning_capacity_rollout.py'))
    rollout_module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(rollout_module)
    with e.transaction(db) as c:
        c.execute("UPDATE PERFORMANCE_ATTRIBUTION SET broker='kraken'")
        c.execute("UPDATE LOGICAL_TRADES SET broker='kraken'")
    row=e.create_experiment(db,dict(broker='kraken',rule_type='minimum_target_r',threshold=2.5,
        evidence_ids=[1],hypothesis='Test a precise target distance after estimated costs.'),now='2026-09-01T00:00:00+00:00')
    row['spec'].pop('portfolio_basis')
    with e.transaction(db) as c:
        c.execute('UPDATE RULE_EXPERIMENTS SET spec_json=? WHERE id=?',(e.dump(row['spec']),row['id']))
    e.add_opportunity(db,row['id'],dict(op(symbol='BTCGBP'),eligible=False,
                                      rejection_reasons=['maximum_capital_allocation_exceeded']))
    preview=rollout_module.rollout(db,now='2026-09-02T00:00:00+00:00')
    assert preview['experiments'][0]['action']=='replace_prospectively'
    result=rollout_module.rollout(db,apply=True,now='2026-09-02T00:00:00+00:00')
    assert len(e.detail(db,row['id'])['opportunities'])==1
    new=e.detail(db,result['experiments'][0]['replacement'])
    assert new['state']['supersedes']==row['id'] and not new['opportunities']
    assert new['spec']['portfolio_basis']=='independent-shadow-capacity-v1'
    assert rollout_module.rollout(db,apply=True)['status']=='already_applied'


def test_budget_used_does_not_load_research(db):
    with e.transaction(db) as c:
        e.put_control(c, 'proposal_attempt', {'day': '2026-09-01'})
        # These reads must not happen once the budget is reserved.
        c.execute('DROP TABLE RULE_EXPERIMENTS')
        c.execute('DROP TABLE PERFORMANCE_ATTRIBUTION')
    assert propose_batch(db, None, '2026-09-01T12:00:00+00:00',
                         dict(model_enabled=True)) == 'daily_model_budget_reached'


def test_capacity_only_rebases_both_arms_but_never_stop_or_unknown(db):
    row = create(db)
    for i, reasons in enumerate([
        ['maximum_capital_allocation_exceeded'],
        ['maximum_capital_allocation_exceeded', 'stop_loss_too_tight'],
        [], ['unknown'], ['stop_loss_too_tight']]):
        e.add_opportunity(db, row['id'], dict(op(source=str(i), symbol='S'+str(i)),
                          eligible=False, rejection_reasons=reasons))
    ops = e.detail(db, row['id'])['opportunities']
    eligible = [o for o in ops if o['capacity_rebased']]
    assert len(eligible) == 1 and not eligible[0]['recorded_eligible']
    assert all(a['status'] == 'awaiting_bar' for a in eligible[0]['arms'].values())
    assert all(a['status'] == 'skipped' for o in ops if not o['capacity_rebased'] for a in o['arms'].values())


def test_legacy_capacity_stays_blocked(db):
    row = create(db)
    row['spec'].pop('portfolio_basis')
    with e.transaction(db) as c:
        c.execute('UPDATE RULE_EXPERIMENTS SET spec_json=? WHERE id=?', (e.dump(row['spec']), row['id']))
    e.add_opportunity(db, row['id'], dict(op(), eligible=False,
                      rejection_reasons=['maximum_capital_allocation_exceeded']))
    assert not e.detail(db, row['id'])['opportunities'][0]['capacity_rebased']


def test_skips_do_not_count_as_useful_evidence(db):
    row = create(db)
    e.add_opportunity(db, row['id'], dict(op(), eligible=False, rejection_reasons=['stop_loss_too_tight']))
    result = e.settle_bars(db, row['id'], [], now='2026-09-02T12:00:00+00:00')['report']
    assert result['both_skipped'] == result['completed'] == 1
    assert result['usable'] == result['informative_completed'] == 0
    assert result['uncertain'] == 0
    assert result['paired_mean_usd'] is None
    assert result['blocker_counts'] == {'stop_loss_too_tight': 1}


def test_virtual_exposure_never_exceeds_frozen_cap(db):
    row = create(db)
    row['spec']['risk_fraction'] = .1
    books = deepcopy(row['state'])
    outcomes = []
    for i in range(5):
        trade = dict(op(source=str(i), symbol='S'+str(i)), last_bar=None,
                     arms={a: dict(status='awaiting_bar', quantity=0, cost=0, net=0) for a in ('baseline','candidate')})
        e.step(row['spec'], books, trade, bar())
        outcomes.append(trade)
    for arm in ('baseline','candidate'):
        assert sum(o['arms'][arm].get('entry', 0)*o['arms'][arm]['quantity'] for o in outcomes) <= 2500


def test_simulated_end_to_end_both_brokers(db):
    with e.transaction(db) as c:
        c.execute("UPDATE PERFORMANCE_ATTRIBUTION SET broker='kraken' WHERE attribution_id=2")
        c.execute("UPDATE LOGICAL_TRADES SET broker='kraken' WHERE proposal_id='p2'")
    for broker, source, symbol in [('alpaca',1,'ABC'),('kraken',2,'BTCGBP')]:
        row = e.create_experiment(db, dict(broker=broker, rule_type='minimum_target_r',threshold=2.5,
            evidence_ids=[source],hypothesis='Test a precise target distance after realistic estimated costs.'),now='2026-09-01T00:00:00+00:00')
        e.add_opportunity(db,row['id'],dict(op(symbol=symbol),eligible=False,
                          rejection_reasons=['maximum_capital_allocation_exceeded']))
        candle=bar();candle.update(symbol=symbol,high=135,low=95,close=130)
        result=e.settle_bars(db,row['id'],[candle],now='2026-09-03T02:00:00+00:00')
        assert result['report']['informative_completed']==1
        assert result['report']['closed_trades']=={'baseline':1,'candidate':1}
        fingerprint=e.baseline_fingerprint()
        assert fingerprint==e.baseline_fingerprint()
        again=e.settle_bars(db,row['id'],[candle],now='2026-09-03T02:00:00+00:00')
        assert again['report']['candidate']['realised']==result['report']['candidate']['realised']
