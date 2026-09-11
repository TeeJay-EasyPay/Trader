from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import pytest

from ai_trader import experiments as e
from ai_trader import experiment_worker as w
from ai_trader.database import connect


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_TRADER_DATABASE_BACKEND', 'sqlite')
    monkeypatch.delenv('RENDER', raising=False)
    monkeypatch.delenv('RENDER_SERVICE_ID', raising=False)
    monkeypatch.delenv('RENDER_INSTANCE_ID', raising=False)
    path = tmp_path / 'experiments.db'
    e.migrate(path)
    with e.transaction(path) as c:
        c.execute('CREATE TABLE PERFORMANCE_ATTRIBUTION(attribution_id INTEGER PRIMARY KEY,broker TEXT,symbol TEXT,profit_loss REAL,closed_at TEXT,exit_price REAL,proposal_id TEXT,holding_period_seconds REAL)')
        c.execute('CREATE TABLE DECISION_JOURNAL(decision_id INTEGER PRIMARY KEY,created_at TEXT,proposal_id TEXT,symbol TEXT,broker TEXT,execution_eligibility TEXT,payload_json TEXT)')
        c.execute('CREATE TABLE HISTORICAL_CANDLES(symbol TEXT,asset_type TEXT,timeframe TEXT,observed_at TEXT,open REAL,high REAL,low REAL,close REAL,source TEXT)')
        c.execute('CREATE TABLE LOGICAL_TRADES(proposal_id TEXT,broker TEXT,intended_entry_price REAL,original_stop REAL,intended_target REAL)')
        for i in range(1, 16):
            c.execute('INSERT INTO LOGICAL_TRADES VALUES (?,?,?,?,?)', ('p'+str(i), 'alpaca', 100, 90, 120))
            c.execute('INSERT INTO PERFORMANCE_ATTRIBUTION VALUES (?,?,?,?,?,?,?,?)',
                      (i, 'alpaca', 'ABC', -1, '2026-08-01T00:00:00+00:00', 100, 'p' + str(i), 3600))
    return path


def create(db):
    return e.create_experiment(db, dict(rule_type='minimum_target_r', threshold=2.5,
        hypothesis='Test whether larger target to risk distance improves simulated outcomes after costs.', evidence_ids=[1,2]),
        now='2026-09-01T00:00:00+00:00')


def op(source='p1', time='2026-09-01T12:00:00+00:00', symbol='ABC', target=130):
    return dict(entry=100, stop=90, target=target, time=time, eligible=True, symbol=symbol, source_id=source)


def bar(day=2, **kwargs):
    return dict(symbol='ABC', start=f'2026-09-{day:02}T00:00:00+00:00', end=f'2026-09-{day+1:02}T00:00:00+00:00',
                open=100, high=105, low=95, close=102, quality='verified_unadjusted', **kwargs)


def test_immutable_spec_and_evidence(db):
    row = create(db)
    assert row['version'] == e.digest(row['spec'])
    assert row['spec']['evidence'][0]['profit_loss'] == -1
    assert row['spec']['execution_validated'] is False
    assert e.detail(db, row['id'])['events'][0]['action'] == 'created'


def test_rejects_foreign_evidence_and_unsupported_code(db):
    with pytest.raises(ValueError):
        e.create_experiment(db, dict(rule_type='exec_python', threshold=2, evidence_ids=[1], hypothesis='Arbitrary trading code is forbidden'))
    with pytest.raises(ValueError):
        e.create_experiment(db, dict(rule_type='minimum_target_r', threshold=2, evidence_ids=[999], hypothesis='Missing evidence is forbidden'))


def test_concurrency_limit(db):
    create(db)
    with pytest.raises(ValueError, match='Concurrent'):
        create(db)


def test_dedup_and_prospective(db):
    row = create(db)
    first = e.add_opportunity(db, row['id'], op())
    assert e.add_opportunity(db, row['id'], op())['duplicate']
    assert e.add_opportunity(db, row['id'], op('p2'))['id'] == first['id']
    with pytest.raises(ValueError):
        e.add_opportunity(db, row['id'], op(time='2026-08-31T00:00:00+00:00'))


def test_no_same_bar_or_incomplete_bar_fill(db):
    row = create(db)
    e.add_opportunity(db, row['id'], op())
    same = bar(1)
    e.settle_bars(db, row['id'], [same, bar()], now='2026-09-02T12:00:00+00:00')
    outcome = e.detail(db, row['id'])['opportunities'][0]
    assert outcome['arms']['baseline']['status'] == 'awaiting_bar'


def test_costs_fill_and_restart_idempotency(db):
    row = create(db)
    e.add_opportunity(db, row['id'], op())
    e.settle_bars(db, row['id'], [bar()], now='2026-09-03T01:00:00+00:00')
    first = e.detail(db, row['id'])
    e.settle_bars(db, row['id'], [bar()], now='2026-09-03T01:00:00+00:00')
    second = e.detail(db, row['id'])
    assert first['state'] == second['state']
    assert second['opportunities'][0]['arms']['baseline']['entry'] > 100
    assert second['opportunities'][0]['arms']['baseline']['cost'] > 0
    assert second['state']['baseline']['positions']


def test_skipped_candidate_is_in_comparison(db):
    row = create(db)
    e.add_opportunity(db, row['id'], op(target=120))
    e.settle_bars(db, row['id'], [bar()], now='2026-09-03T01:00:00+00:00')
    detail = e.detail(db, row['id'])
    assert detail['opportunities'][0]['arms']['candidate']['status'] == 'skipped'
    assert detail['opportunities'][0]['arms']['baseline']['status'] == 'open'
    assert detail['state']['candidate']['cash'] == 10000


def test_ambiguous_bar_excluded(db):
    row = create(db)
    e.add_opportunity(db, row['id'], op())
    candle = bar(); candle.update(high=140, low=80)
    result = e.settle_bars(db, row['id'], [candle], now='2026-09-03T01:00:00+00:00')
    assert result['report']['uncertain'] == 1
    assert result['report']['usable'] == 0
    assert result['report']['candidate']['realised'] < 0


def test_invalid_ohlc_rolls_back(db):
    row = create(db); e.add_opportunity(db, row['id'], op())
    candle = bar(); candle['low'] = 110
    with pytest.raises(ValueError):
        e.settle_bars(db, row['id'], [candle], now='2026-09-03T01:00:00+00:00')
    assert e.detail(db, row['id'])['state']['baseline']['cash'] == 10000


def test_no_baseline_safeguard_override(db):
    row = create(db); o = op(); o['eligible'] = False
    e.add_opportunity(db, row['id'], o)
    assert all(a['status'] == 'skipped' for a in e.detail(db, row['id'])['opportunities'][0]['arms'].values())


def test_owner_version_and_idempotent_approval(db):
    row = create(db)
    with pytest.raises(ValueError):
        e.detail(db, row['id'], owner='other')
    args = dict(version=row['version'], revision=0, action='suspend', key='suspend-test')
    result = e.decide(db, row['id'], **args)
    assert result['status'] == 'suspended'
    assert e.decide(db, row['id'], **args)['revision'] == result['revision']
    with pytest.raises(ValueError):
        e.decide(db, row['id'], **{**args, 'action': 'approve_library'})


def test_unapproved_library_and_live_rejected(db):
    row = create(db)
    for action in ('approve_library', 'enable_paper', 'enable_live'):
        with pytest.raises(ValueError):
            e.decide(db, row['id'], version=row['version'], revision=0, action=action, key='key-' + action)


def test_model_budget_and_missing_evidence(db):
    calls = []
    def answer(question, context):
        calls.append(context)
        return '{"no_change":"Linked outcomes lack enough cost evidence."}'
    policy = {**e.DEFAULT_POLICY, 'model_enabled': True}
    result = w.propose(db, None, '2026-09-01T00:00:00+00:00', policy, answer)
    assert result['status'] == 'no_justified_change'
    assert w.propose(db, None, '2026-09-01T01:00:00+00:00', policy, answer) == 'daily_model_budget_reached'
    assert len(calls) == 1


def test_model_fabricated_evidence_and_no_retry(db):
    policy = {**e.DEFAULT_POLICY, 'model_enabled': True}
    result = w.propose(db, None, '2026-09-01T00:00:00+00:00', policy, lambda *args: '{"evidence_ids":[999]}')
    assert result['status'] == 'proposal_failed'
    assert not e.list_experiments(db)['items']


def test_disabled_worker_does_nothing(db):
    assert w.tick(db, None)['status'] == 'disabled'


def test_reads_never_run_model(db, monkeypatch):
    monkeypatch.setattr(w, 'propose', lambda *args, **kw: pytest.fail('read triggered paid job'))
    row = create(db)
    assert e.list_experiments(db)['items']
    assert e.detail(db, row['id'])


def test_sparse_results_not_recommended(db):
    row = create(db)
    result = e.settle_bars(db, row['id'], [], now='2026-12-01T00:00:00+00:00')
    assert result['status'] == 'insufficient_evidence'


def test_paper_does_not_apply_to_live_or_kraken(db):
    p = SimpleNamespace(side='buy', entry_price=100, stop_loss=90, take_profit=120, position_size=1)
    assert e.paper_filter(db, p, broker='kraken', mode='live')['allowed']
    assert e.paper_filter(db, p, broker='alpaca', mode='live')['allowed']


def test_worker_end_to_end_without_broker_orders(db):
    row = create(db)
    with e.transaction(db) as c:
        policy = {**e.DEFAULT_POLICY, 'enabled': True}
        e.put_control(c, 'policy', policy)
        c.execute('INSERT INTO DECISION_JOURNAL VALUES (?,?,?,?,?,?,?)', (1, '2026-09-01T12:00:00+00:00', 'p1', 'ABC', 'alpaca', 'eligible',
            json.dumps({'proposal': {'entry_price': 100, 'stop_loss': 90, 'take_profit': 130, 'side': 'buy'}})))
        c.execute('INSERT INTO HISTORICAL_CANDLES VALUES (?,?,?,?,?,?,?,?,?)',
                  ('ABC', 'stock', '1d', '2026-09-02T00:00:00+00:00', 100, 105, 95, 102, 'alpaca'))
    result = w.tick(db, None, now='2026-09-03T10:00:00+00:00')
    assert result['processed'] == 1
    assert result['broker_orders'] == 0
    assert e.detail(db, row['id'])['state']['baseline']['positions']['ABC']['quantity'] > 0
    result = w.tick(db, None, now='2026-09-03T10:30:00+00:00')
    assert result['processed'] == 0
    assert e.detail(db, row['id'])['report']['observations'] == 1


def test_library_approval_is_not_activation(db):
    row = create(db)
    # Fixture stands for a completed evaluation; do not create bogus production evidence.
    with e.transaction(db) as c:
        c.execute("UPDATE RULE_EXPERIMENTS SET status='recommended' WHERE id=?", (row['id'],))
    result = e.decide(db, row['id'], version=row['version'], revision=0, action='approve_library', key='library-accept')
    assert result['status'] == 'library_approved'
    assert 'activation' not in result['state']
    with pytest.raises(ValueError, match='Stale'):
        e.decide(db, row['id'], version=row['version'], revision=0, action='reject', key='library-reject')


def test_paper_approval_limits_and_filter(db, monkeypatch):
    monkeypatch.setenv('EXPERIMENT_PAPER_ADOPTION_ENABLED', 'true')
    row = create(db)
    with e.transaction(db) as c:
        c.execute("UPDATE RULE_EXPERIMENTS SET status='library_approved' WHERE id=?", (row['id'],))
    from datetime import timedelta
    expiry = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    result = e.decide(db, row['id'], version=row['version'], revision=0, action='enable_paper', key='paper-enable',
                      scope={'max_notional_usd': 200, 'expires_at': expiry})
    assert result['status'] == 'paper_active'
    p = SimpleNamespace(side='buy', entry_price=100, stop_loss=90, take_profit=120, position_size=1)
    assert not e.paper_filter(db, p, broker='alpaca', mode='paper')['allowed']
    p.take_profit = 130
    assert e.paper_filter(db, p, broker='alpaca', mode='paper')['allowed']
    p.position_size = 3
    assert not e.paper_filter(db, p, broker='alpaca', mode='paper')['allowed']


def test_implementation_queue_requires_approval(db):
    row = create(db)
    with pytest.raises(ValueError):
        e.implementation_update(db, row['id'], version=row['version'], revision=0, status='ready_for_activation',
                                commit='a'*40, tests='passed', deployment='a'*40)
    with e.transaction(db) as c:
        c.execute("UPDATE RULE_EXPERIMENTS SET status='library_approved' WHERE id=?", (row['id'],))
    row = e.decide(db, row['id'], version=row['version'], revision=0, action='request_development', key='develop-request',
                  scope={'requirements': 'Additional supported execution validation', 'acceptance_tests': 'No live order calls'})
    row = e.decide(db, row['id'], version=row['version'], revision=row['revision'], action='approve_implementation', key='develop-approve')
    row = e.implementation_update(db, row['id'], version=row['version'], revision=row['revision'], status='ready_for_activation',
                                  commit='a'*40, tests='passed', deployment='a'*40)
    assert row['status'] == 'ready_for_activation'
    assert 'activation' not in row['state']


def test_api_owner_input_cannot_override(db):
    from ai_trader import experiment_api
    row = create(db)
    code, payload = experiment_api.get(db, '/experiments/detail', {'id': [row['id']], 'owner': ['intruder']})
    assert code == 200 and payload['owner'] == 'founder'
    code, _ = experiment_api.post(db, '/experiments/decision', {'id': row['id'], 'confirmed': False})
    assert code == 409


def test_missing_market_data_is_get_only_and_budgeted(db, monkeypatch):
    from ai_trader import experiment_market_data as market
    from io import BytesIO
    calls = []
    def fake(request, timeout):
        calls.append(request)
        assert request.method == 'GET'
        assert request.full_url.startswith('https://data.alpaca.markets/v2/stocks/bars?')
        assert timeout == 8
        return BytesIO(json.dumps({'bars': {'ABC': [{'t': '2026-09-02T04:00:00Z', 'o': 100, 'h': 105, 'l': 95, 'c': 102}]}}).encode())
    monkeypatch.setattr(market, 'urlopen', fake)
    settings = SimpleNamespace(alpaca_api_key='test', alpaca_secret_key='test')
    first = market.missing_bars(db, settings, ['ABC'], '2026-09-03T10:00:00+00:00')
    assert len(first) == 1
    assert market.missing_bars(db, settings, ['ABC'], '2026-09-03T11:00:00+00:00') == first
    assert len(calls) == 1


def test_intraday_exit_cannot_free_a_slot_for_earlier_open(db):
    row = create(db)
    row['spec']['max_positions'] = 1
    o1 = op(); o1.update(arms={a: {'status': 'awaiting_bar', 'net': 0, 'cost': 0} for a in ('baseline','candidate')}, last_bar=None, uncertain=False)
    e.step(row['spec'], row['state'], o1, bar(2))
    stop_bar = bar(3); stop_bar['low'] = 89
    e.step(row['spec'], row['state'], o1, stop_bar)
    assert not row['state']['baseline']['positions']
    o2 = op('p2', '2026-09-02T12:00:00+00:00', 'XYZ')
    o2.update(arms={a: {'status': 'awaiting_bar', 'net': 0, 'cost': 0} for a in ('baseline','candidate')}, last_bar=None, uncertain=False)
    e.step(row['spec'], row['state'], o2, bar(3))
    assert o2['arms']['baseline']['status'] == 'skipped'


def test_delayed_entry_is_uncertain(db):
    row = create(db); e.add_opportunity(db, row['id'], op())
    e.settle_bars(db, row['id'], [bar(10)], now='2026-09-12T00:00:00+00:00')
    assert e.detail(db, row['id'])['opportunities'][0]['uncertain']
