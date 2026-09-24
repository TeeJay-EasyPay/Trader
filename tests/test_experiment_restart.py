import json
from test_experiments import db, create, op
from ai_trader import experiments as e, experiment_worker as w


def test_deployment_restart_preserves_previous_measurements(db, monkeypatch):
    row = create(db)
    e.add_opportunity(db, row['id'], op())
    with e.transaction(db) as c:
        e.put_control(c, 'policy', {**e.DEFAULT_POLICY, 'enabled': True})
        current = e._load(c, row['id'])
        current['report'] = {'observations':1,'completed':0,'baseline':{'realised':0},'candidate':{'realised':0}}
        e._save(c,current)
    monkeypatch.setattr(e,'baseline_fingerprint',lambda:'changed')
    w.tick(db,None,now='2026-09-03T10:00:00+00:00')
    old = e.detail(db,row['id'])
    assert old['report']['observations'] == 1
    assert old['report']['finished'] is True
    queued = [r for r in e.list_experiments(db)['items'] if r['status']=='queued']
    assert len(queued) == 1
    assert e.detail(db,queued[0]['id'])['state']['supersedes'] == row['id']


def test_legacy_operational_fingerprint_migrates_without_restarting(db):
    row = create(db)
    e.add_opportunity(db, row['id'], op())
    with e.transaction(db) as c:
        current = e._load(c, row['id'])
        current['spec'].pop('baseline_contract_version')
        current['spec']['baseline_fingerprint'] = 'legacy-whole-file-hash'
        current['version'] = e.digest(current['spec'])
        current['report'] = {'observations': 4, 'completed': 1,
                             'baseline': {'realised': 0}, 'candidate': {'realised': 0}}
        c.execute('UPDATE RULE_EXPERIMENTS SET version=?,spec_json=?,report_json=? WHERE id=?',
                  (current['version'], e.dump(current['spec']), e.dump(current['report']), row['id']))
        e.put_control(c, 'policy', {**e.DEFAULT_POLICY, 'enabled': True})

    w.tick(db, None, now='2026-09-03T10:00:00+00:00')

    migrated = e.detail(db, row['id'])
    assert migrated['status'] == 'shadow_running'
    # The normal worker pass recomputes the report from the preserved underlying
    # opportunities; it must not archive/recreate the experiment.
    assert migrated['report']['observations'] == 1
    assert migrated['spec']['baseline_fingerprint'] == e.baseline_fingerprint()
    assert migrated['spec']['baseline_contract_version']
    assert not [r for r in e.list_experiments(db)['items'] if r['status'] == 'queued']
    event = next(event for event in migrated['events']
                 if event['action'] == 'baseline_contract_migrated')
    assert json.loads(event['payload_json'])['preserved_observations'] == 4


def test_ended_review_rechecks_late_broker_evidence_once_daily(db, monkeypatch):
    from ai_trader import experiment_assurance as a
    row = create(db)
    with e.transaction(db) as c:
        c.execute("UPDATE RULE_EXPERIMENTS SET status='library_approved' WHERE id=?", (row['id'],))
    calls = []
    monkeypatch.setattr(a, 'validate_execution', lambda db, row, ops, now: calls.append((row['id'], now)))
    a.refresh_review_validation(db,'2026-09-03T10:00:00+00:00')
    a.refresh_review_validation(db,'2026-09-03T11:00:00+00:00')
    a.refresh_review_validation(db,'2026-09-04T10:00:00+00:00')
    assert len(calls) == 2
