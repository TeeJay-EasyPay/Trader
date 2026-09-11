"""Versioned, prospective Alpaca experiments. This module cannot submit orders.

One supported intervention: a stricter target/risk entry filter. A target is NOT
an expected return. Baseline eligibility is frozen from the decision journal;
neither arm can override a failed production safeguard. Daily-bar fills are
estimates and cannot qualify a live pilot without separate execution validation.
"""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
import sqlite3
import statistics
from uuid import uuid4
from pathlib import Path

from .database import connect, uses_postgres

SCHEMA = """
CREATE TABLE IF NOT EXISTS RULE_EXPERIMENTS (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL,
 version TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL,
 spec_json TEXT NOT NULL, report_json TEXT NOT NULL, state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS EXPERIMENT_OPPORTUNITIES (
 id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, created_at TEXT NOT NULL,
 symbol TEXT NOT NULL, source_id TEXT NOT NULL, payload_json TEXT NOT NULL,
 UNIQUE(experiment_id, source_id)
);
CREATE INDEX IF NOT EXISTS experiment_opportunities_parent ON EXPERIMENT_OPPORTUNITIES(experiment_id, created_at);
CREATE TABLE IF NOT EXISTS EXPERIMENT_EVENTS (
 id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, owner TEXT NOT NULL,
 created_at TEXT NOT NULL, action TEXT NOT NULL, version TEXT NOT NULL,
 payload_json TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS experiment_events_parent ON EXPERIMENT_EVENTS(experiment_id, created_at);
CREATE TABLE IF NOT EXISTS EXPERIMENT_CONTROL (
 id TEXT PRIMARY KEY, payload_json TEXT NOT NULL
);
"""

DEFAULT_POLICY = dict(enabled=False, max_active=1, opportunities_per_day=20,
                     storage_bytes=20_000_000, max_experiments=24,
                     daily_model_calls=1, interval_seconds=900,
                     min_new_outcomes=10, model_enabled=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def stamp(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return result.astimezone(timezone.utc)


def dump(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def baseline_fingerprint():
    """UI/docs-only deployments must not reset a 60-day experiment."""
    root = Path(__file__).parent
    return hashlib.sha256(b''.join((root / name).read_text(encoding='utf-8').replace('\r\n', '\n').encode() for name in
        ('experiments.py', 'experiment_worker.py', 'experiment_market_data.py', 'experiment_assurance.py',
         'sprint6.py', 'guardrails.py', 'decision_economics.py'))).hexdigest()


@contextmanager
def transaction(db):
    with closing(connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            if uses_postgres():
                conn.execute("SET LOCAL statement_timeout='2000ms'")
                conn.execute("SET LOCAL lock_timeout='500ms'")
            yield conn


def migrate(db):
    with transaction(db) as conn:
        conn.executescript(SCHEMA)
        conn.execute('INSERT INTO EXPERIMENT_CONTROL(id,payload_json) VALUES (?,?) ON CONFLICT(id) DO NOTHING',
                     ('policy', dump(DEFAULT_POLICY)))
        if uses_postgres():
            # Private server-side tables: never expose approval writes through PostgREST.
            for table in ('RULE_EXPERIMENTS', 'EXPERIMENT_OPPORTUNITIES', 'EXPERIMENT_EVENTS', 'EXPERIMENT_CONTROL'):
                conn.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')


def control(conn, key, default=None):
    row = conn.execute('SELECT payload_json FROM EXPERIMENT_CONTROL WHERE id=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put_control(conn, key, value):
    conn.execute('INSERT INTO EXPERIMENT_CONTROL(id,payload_json) VALUES (?,?) '
                 'ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json', (key, dump(value)))


def number(value, low, high):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a numeric rule value')
    v = float(value)
    if not math.isfinite(v) or not low <= v <= high:
        raise ValueError('Rule value outside supported bounds')
    return v


def validate_spec(raw):
    if raw.get('rule_type') not in ('minimum_target_r', 'replace_target_r_gate'):
        raise ValueError('Development required: unsupported rule type')
    ids = raw.get('evidence_ids', [])
    if not isinstance(ids, list) or not 1 <= len(ids) <= 30:
        raise ValueError('One to thirty source outcomes required')
    hypothesis = str(raw.get('hypothesis', '')).strip()
    if not 15 <= len(hypothesis) <= 1000:
        raise ValueError('A specific falsifiable hypothesis is required')
    # Narrow executable DSL, never arbitrary code or model-supplied SQL.
    broker = raw.get('broker', 'alpaca')
    if broker not in ('alpaca', 'kraken'):
        raise ValueError('Unsupported shadow broker')
    return dict(rule_type=raw['rule_type'], threshold=number(raw['threshold'], 1, 4),
                hypothesis=hypothesis, evidence_ids=sorted(set(int(x) for x in ids)),
                problem=str(raw.get('problem') or hypothesis)[:1000],
                expected_benefit=str(raw.get('expected_benefit') or 'Test net improvement at comparable risk; benefit not established.')[:1000],
                priority=int(number(raw.get('priority', 3), 1, 5)),
                broker=broker, currency='GBP' if broker == 'kraken' else 'USD',
                asset_type='crypto' if broker == 'kraken' else 'equity', side='buy',
                baseline='unchanged recorded pre-execution eligibility',
                simulator='daily-bar-paired-v2', initial_cash=10000.0,
                risk_fraction=0.0025, max_notional_fraction=0.10,
                max_positions=5, max_holding_days=10,
                cost_bps_per_leg=80.0 if broker == 'kraken' else 10.0, slippage_bps_per_leg=10.0,
                costs_status='conservative scenario, not reconciled broker costs',
                evaluation_days=60, minimum_opportunities=60,
                minimum_symbol_days=40, max_drawdown_fraction=0.05,
                execution_tolerances=dict(entry_bps=50, exit_bps=50, holding_hours=24, cost_bps=25, minimum_pairs=20),
                execution_validated=False, adoption_environment='paper')


def _load(conn, eid, owner='founder'):
    row = conn.execute('SELECT * FROM RULE_EXPERIMENTS WHERE id=? AND owner=?', (eid, owner)).fetchone()
    if not row:
        raise ValueError('Experiment not found')
    row = dict(row)
    for key in ('spec', 'report', 'state'):
        row[key] = json.loads(row.pop(key + '_json'))
    return row


def _event(conn, row, action, payload, key):
    conn.execute('INSERT INTO EXPERIMENT_EVENTS VALUES (?,?,?,?,?,?,?,?)',
                 (str(uuid4()), row['id'], row['owner'], now_iso(), action, row['version'], dump(payload), key))


def create_experiment(db, raw, *, owner='founder', now=None, queue=False):
    spec = validate_spec(raw)
    now = now or now_iso()
    stamp(now)
    with transaction(db) as conn:
        if uses_postgres():
            conn.execute('SELECT pg_advisory_xact_lock(71911502)')
        policy = control(conn, 'policy', DEFAULT_POLICY)
        if conn.execute('SELECT COUNT(*) FROM RULE_EXPERIMENTS').fetchone()[0] >= policy['max_experiments']:
            raise ValueError('Experiment storage/count budget reached')
        if not queue and conn.execute("SELECT COUNT(*) FROM RULE_EXPERIMENTS WHERE status='shadow_running'").fetchone()[0] >= policy['max_active']:
            raise ValueError('Concurrent experiment limit reached')
        placeholders = ','.join('?' for _ in spec['evidence_ids'])
        count = conn.execute(f"SELECT COUNT(*) FROM PERFORMANCE_ATTRIBUTION WHERE broker=? "
                             f"AND exit_price IS NOT NULL AND attribution_id IN ({placeholders})", [spec['broker'], *spec['evidence_ids']]).fetchone()[0]
        if count != len(spec['evidence_ids']):
            raise ValueError('Evidence must reference existing completed outcomes for the selected broker')
        # Evidence snapshot is compact and immutable; no model-generated P&L.
        evidence = conn.execute(f'SELECT attribution_id,symbol,profit_loss,closed_at FROM PERFORMANCE_ATTRIBUTION '
                                f'WHERE attribution_id IN ({placeholders})', spec['evidence_ids']).fetchall()
        if any(stamp(r['closed_at']) > stamp(now) for r in evidence):
            raise ValueError('Future evidence is not allowed')
        spec['evidence'] = [dict(r) for r in evidence]
        spec['frozen_at'] = now
        spec['baseline_deployment'] = os.getenv('RENDER_GIT_COMMIT', 'unverified')
        spec['baseline_fingerprint'] = baseline_fingerprint()
        spec['sampling'] = 'First 20 distinct symbol-days, chronologically; rejected baseline decisions retained'
        version = digest(spec)
        eid = str(uuid4())
        book = dict(cash=spec['initial_cash'], equity=spec['initial_cash'], peak=spec['initial_cash'],
                    max_drawdown=0, realised=0, positions={})
        cursor = conn.execute('SELECT COALESCE(MAX(decision_id),0) AS latest FROM DECISION_JOURNAL').fetchone()[0]
        state = dict(baseline=book, candidate=book, cursor=cursor, observations=0, blocked=0)
        conn.execute('INSERT INTO RULE_EXPERIMENTS VALUES (?,?,?,?,?,?,?,?,?)',
                     (eid, owner, now, version, 'queued' if queue else 'shadow_running', 0, dump(spec), dump({}), dump(state)))
        row = _load(conn, eid, owner)
        _event(conn, row, 'created', {'simulation_only': True}, 'created:' + eid)
        return row


def passes(rule, opportunity):
    risk = opportunity['entry'] - opportunity['stop']
    return risk > 0 and (opportunity['target'] - opportunity['entry']) / risk >= rule


def add_opportunity(db, eid, opportunity, *, owner='founder'):
    """Freeze a point-in-time decision. Caller never fabricates missing inputs."""
    op = dict(opportunity)
    for key in ('entry', 'stop', 'target'):
        op[key] = number(op[key], 0.000001, 1_000_000)
    if not op['stop'] < op['entry'] < op['target']:
        raise ValueError('Only well-formed long proposals supported')
    stamp(op['time'])
    if not isinstance(op.get('eligible'), bool):
        raise ValueError('Baseline eligibility must be explicit')
    if not str(op.get('symbol', '')).isalnum() or len(op['symbol']) > 16:
        raise ValueError('Unsupported equity symbol')
    reasons = op.get('rejection_reasons')
    if reasons is not None and (not isinstance(reasons, list) or any(not isinstance(r, str) for r in reasons)):
        raise ValueError('Rejection evidence must be a list of recorded reason codes')
    op = {key: op[key] for key in ('entry', 'stop', 'target', 'time', 'eligible', 'symbol', 'source_id')}
    op['rejection_reasons'] = reasons
    with transaction(db) as conn:
        row = _load(conn, eid, owner)
        if row['status'] != 'shadow_running' or stamp(op['time']) < stamp(row['created_at']):
            raise ValueError('Only prospective opportunities in running experiments')
        oid = digest([eid, op['source_id']])
        existing = conn.execute('SELECT payload_json FROM EXPERIMENT_OPPORTUNITIES WHERE id=?', (oid,)).fetchone()
        if existing:
            return {'id': oid, 'duplicate': True}
        policy = control(conn, 'policy', DEFAULT_POLICY)
        day = op['time'][:10]
        count = conn.execute('SELECT COUNT(*) FROM EXPERIMENT_OPPORTUNITIES WHERE created_at>=? AND created_at<?',
                             (day, day + 'Z')).fetchone()[0]
        if count >= policy['opportunities_per_day']:
            raise ValueError('Daily observation budget reached')
        active_count = conn.execute("SELECT COUNT(*) FROM RULE_EXPERIMENTS WHERE status='shadow_running'").fetchone()[0]
        own_count = conn.execute('SELECT COUNT(*) FROM EXPERIMENT_OPPORTUNITIES WHERE experiment_id=? AND created_at>=? AND created_at<?',
                                 (eid, day, day + 'Z')).fetchone()[0]
        if own_count >= max(1, policy['opportunities_per_day'] // max(1, active_count)):
            raise ValueError('Fair-share daily observation budget reached')
        # One symbol/day across decisions prevents repeated signals inflating sample size.
        same = conn.execute('SELECT id FROM EXPERIMENT_OPPORTUNITIES WHERE experiment_id=? AND symbol=? '
                            'AND created_at>=? AND created_at<?', (eid, op['symbol'], day, day + 'Z')).fetchone()
        if same:
            return {'id': same[0], 'duplicate': True}
        # Only an exact, allowlisted strategy rejection can be replaced in shadow.
        # Missing reasons or ANY other failure (costs/risk/permissions/data) block it.
        candidate_eligible = op['eligible'] or (row['spec']['rule_type'] == 'replace_target_r_gate'
            and bool(reasons) and set(reasons) == {'reward_risk_below_minimum'})
        op['arms'] = {arm: dict(status='awaiting_bar' if
                               (op['eligible'] if arm == 'baseline' else candidate_eligible and passes(row['spec']['threshold'], op)) else 'skipped',
                               net=0, cost=0, quantity=0, reason='recorded eligibility / frozen filter')
                      for arm in ('baseline', 'candidate')}
        op['last_bar'] = None
        op['uncertain'] = False
        conn.execute('INSERT INTO EXPERIMENT_OPPORTUNITIES VALUES (?,?,?,?,?,?)',
                     (oid, eid, op['time'], op['symbol'], str(op['source_id']), dump(op)))
        return {'id': oid, 'duplicate': False}


def step(spec, books, op, bar):
    """Pure daily-bar simulation; deterministic entry at NEXT bar open, never signal price.

    Input bar is completed, unadjusted, source-vetted OHLC. Ambiguous intrabar
    ordering or suspicious split-sized gaps invalidate the pair for promotion.
    """
    start, end = stamp(bar['start']), stamp(bar['end'])
    if end <= start or start <= stamp(op['time']) or (op['last_bar'] and start <= stamp(op['last_bar'])):
        return False
    o, h, l, c = (number(bar[k], 0.000001, 1_000_000) for k in ('open', 'high', 'low', 'close'))
    if not l <= min(o, c) <= max(o, c) <= h:
        raise ValueError('Invalid OHLC')
    if abs(o / op.get('last_close', op['entry']) - 1) > .20:
        op['uncertain'] = True
        op['quality'] = 'large gap / possible corporate action requires review'
    if start - stamp(op.get('last_bar') or op['time']) > timedelta(days=4):
        op['uncertain'] = True
        op['quality'] = 'Missing intervening bars / delayed initial observation'
    op['last_bar'], op['last_close'] = bar['start'], c
    if not any(a['status'] in ('open', 'awaiting_bar') for a in op['arms'].values()):
        return False
    op.setdefault('bars', []).append({k: bar[k] for k in ('start', 'end', 'open', 'high', 'low', 'close', 'quality')})
    fee, slip = spec['cost_bps_per_leg'] / 10000, spec['slippage_bps_per_leg'] / 10000
    for arm, outcome in op['arms'].items():
        book = books[arm]
        # Reserve from START-of-day cash and capacity. A later intraday exit
        # must not fund an earlier same-day open in another simulated trade.
        if book.get('budget_day') != bar['start'][:10]:
            book.update(budget_day=bar['start'][:10], entry_cash_remaining=book['cash'],
                        entry_slots_remaining=spec['max_positions'] - len(book['positions']),
                        occupied_at_open=list(book['positions']))
        if outcome['status'] == 'awaiting_bar':
            fill = o * (1 + slip)
            if fill <= op['stop'] or fill >= op['target'] or book['entry_slots_remaining'] <= 0 or op['symbol'] in book['occupied_at_open']:
                outcome.update(status='skipped', reason='gap, occupied symbol or portfolio limit')
                continue
            risk_cash = spec['initial_cash'] * spec['risk_fraction']
            raw_quantity = min(risk_cash / (fill - op['stop'] + fill * fee + op['stop'] * (fee + slip)),
                                      spec['initial_cash'] * spec['max_notional_fraction'] / fill,
                                      max(0, min(book['cash'], book['entry_cash_remaining'])) / (fill * (1 + fee)))
            quantity = math.floor(raw_quantity * 1e8) / 1e8 if spec.get('broker') == 'kraken' else math.floor(raw_quantity)
            if quantity <= 0:
                outcome.update(status='skipped', reason='insufficient virtual cash / risk budget')
                continue
            cost = quantity * fill * fee
            book['cash'] -= quantity * fill + cost
            book['entry_cash_remaining'] -= quantity * fill + cost
            book['entry_slots_remaining'] -= 1
            book['occupied_at_open'].append(op['symbol'])
            outcome.update(status='open', entry=fill, entered_at=bar['start'], quantity=quantity, cost=cost)
            book['positions'][op['symbol']] = dict(quantity=quantity, mark=c)
        if outcome['status'] != 'open':
            continue
        hit_stop, hit_target = l <= op['stop'], h >= op['target']
        if hit_stop and hit_target:
            op['uncertain'] = True
            op['quality'] = 'Both stop and target crossed; conservative stop-first estimate'
        expired = end >= stamp(outcome['entered_at']) + timedelta(days=spec['max_holding_days'])
        exit_price = min(o, op['stop']) if hit_stop else op['target'] if hit_target else c if expired else None
        if exit_price is not None:
            fill = exit_price * (1 - slip)
            qty = outcome['quantity']
            cost = qty * fill * fee
            net = qty * (fill - outcome['entry']) - outcome['cost'] - cost
            book['cash'] += qty * fill - cost
            book['realised'] += net
            book['positions'].pop(op['symbol'], None)
            outcome.update(status='closed', exit=fill, exited_at=bar['end'], net=net,
                           cost=outcome['cost'] + cost, reason='stop' if hit_stop else 'target' if hit_target else 'time_limit')
        else:
            book['positions'][op['symbol']]['mark'] = c
        book['equity'] = book['cash'] + sum(p['quantity'] * p['mark'] for p in book['positions'].values())
        book['peak'] = max(book['peak'], book['equity'])
        book['max_drawdown'] = max(book['max_drawdown'], 1 - book['equity'] / book['peak'])
    return True


def settle_bars(db, eid, bars, *, owner='founder', now=None):
    now = stamp(now or now_iso())
    with transaction(db) as conn:
        row = _load(conn, eid, owner)
        if row['status'] != 'shadow_running':
            return row
        ops = [dict(r) for r in conn.execute('SELECT * FROM EXPERIMENT_OPPORTUNITIES WHERE experiment_id=? ORDER BY created_at,id', (eid,)).fetchall()]
        decoded = [(r, json.loads(r['payload_json'])) for r in ops]
        changed = set()
        # Chronological interleaving across symbols, not settle each trade to completion.
        for bar in sorted(bars, key=lambda b: (b['start'], b['symbol'])):
            if stamp(bar['end']) > now or bar.get('quality') != 'verified_unadjusted':
                continue
            for record, op in decoded:
                if op['symbol'] == bar['symbol'] and step(row['spec'], row['state'], op, bar):
                    changed.add(record['id'])
        for record, op in decoded:
            if record['id'] in changed:
                conn.execute('UPDATE EXPERIMENT_OPPORTUNITIES SET payload_json=? WHERE id=?', (dump(op), record['id']))
        row['report'] = evaluate(row, [op for _, op in decoded], now=now)
        if row['report']['finished']:
            row['status'] = row['report']['verdict']
            _event(conn, row, 'evaluation_finished', {'verdict': row['status']}, 'evaluated:' + eid)
        _save(conn, row)
        return row


def evaluate(row, ops, *, now):
    complete = [o for o in ops if all(a['status'] in ('closed', 'skipped') for a in o['arms'].values())]
    usable = [o for o in complete if not o['uncertain']]
    diff = [o['arms']['candidate']['net'] - o['arms']['baseline']['net'] for o in usable]
    n = len(diff)
    mean = statistics.mean(diff) if diff else None
    # Same-day signals are correlated: aggregate them before estimating uncertainty.
    # Serial dependence can still remain; this is a paper-screening bound, not proof.
    days = {}
    for o in usable:
        days.setdefault(o['time'][:10], []).append(o['arms']['candidate']['net'] - o['arms']['baseline']['net'])
    groups = [statistics.mean(values) for values in days.values()]
    lower = statistics.mean(groups) - 3 * statistics.stdev(groups) / math.sqrt(len(groups)) if len(groups) > 1 else None
    ends = stamp(row['created_at']) + timedelta(days=row['spec']['evaluation_days'])
    finished = now >= ends and (len(complete) == len(ops) or now >= ends + timedelta(days=15))
    verdict = 'insufficient_evidence'
    if finished and len(complete) == len(ops) and n >= row['spec']['minimum_opportunities'] and len(groups) >= 30 and len({(o['symbol'], o['time'][:10]) for o in usable}) >= row['spec']['minimum_symbol_days']:
        positive = [o['arms']['candidate']['net'] for o in usable if o['arms']['candidate']['net'] > 0]
        concentration = max(positive) / sum(positive) if positive else 1
        if lower is not None and lower > 0 and concentration < .25 and row['state']['candidate']['realised'] > 0 and row['state']['candidate']['max_drawdown'] <= min(row['spec']['max_drawdown_fraction'], row['state']['baseline']['max_drawdown']):
            verdict = 'recommended'
        elif mean is not None and mean < 0:
            verdict = 'rejected'
    return dict(finished=finished, verdict=verdict, observations=len(ops), completed=len(complete), usable=n,
                currency=row['spec'].get('currency', 'USD'),
                closed_trades={arm: sum(o['arms'][arm]['status'] == 'closed' for o in ops) for arm in ('baseline', 'candidate')},
                skipped={arm: sum(o['arms'][arm]['status'] == 'skipped' for o in ops) for arm in ('baseline', 'candidate')},
                uncertain=len(complete) - n, paired_mean_usd=mean, descriptive_lower_bound=lower,
                day_clusters=len(groups),
                baseline=row['state']['baseline'], candidate=row['state']['candidate'],
                evaluate_after=ends.isoformat(), costs=row['spec']['costs_status'],
                caveat='Dependent signals and estimated daily-bar fills limit inference. Recommendation is for paper review only; no proven live edge.')


def _save(conn, row):
    updated = conn.execute('UPDATE RULE_EXPERIMENTS SET status=?,revision=revision+1,report_json=?,state_json=? WHERE id=? AND revision=?',
                           (row['status'], dump(row['report']), dump(row['state']), row['id'], row['revision']))
    if updated.rowcount != 1:
        raise ValueError('Concurrent update; reload and retry')
    row['revision'] += 1


def list_experiments(db, *, owner='founder', before='', attention=False):
    with transaction(db) as conn:
        conditions = 'owner=?'
        params = [owner]
        if before:
            conditions += ' AND created_at<?'
            params.append(before)
        if attention:
            conditions += " AND status IN ('recommended','implementation_required','implementation_approved','ready_for_activation','library_approved','suspended')"
        rows = conn.execute(f'SELECT id,created_at,version,status,revision,spec_json,report_json FROM RULE_EXPERIMENTS WHERE {conditions} ORDER BY created_at DESC LIMIT 21', params).fetchall()
        items = []
        for r in rows[:20]:
            r = dict(r)
            spec = json.loads(r.pop('spec_json'))
            r['hypothesis'] = spec['hypothesis']
            r.update(broker=spec['broker'], currency=spec.get('currency', 'USD'), problem=spec.get('problem'),
                     expected_benefit=spec.get('expected_benefit'), priority=spec.get('priority', 3))
            r['report'] = json.loads(r.pop('report_json'))
            items.append(r)
        return dict(items=items, next_cursor=items[-1]['created_at'] if len(rows) > 20 else None,
                    pipeline=[dict(r) for r in conn.execute('SELECT status,COUNT(*) AS count FROM RULE_EXPERIMENTS WHERE owner=? GROUP BY status', (owner,)).fetchall()],
                    policy=control(conn, 'policy', DEFAULT_POLICY), notification_type='strategy_experiment',
                    evidence_coverage=control(conn, 'learning_evidence_coverage', {}),
                    last_review=control(conn, 'proposal_attempt', {}), worker=control(conn, 'last_tick', {}))


def detail(db, eid, owner='founder'):
    with transaction(db) as conn:
        row = _load(conn, eid, owner)
        row['events'] = [dict(r) for r in conn.execute('SELECT created_at,action,payload_json FROM EXPERIMENT_EVENTS WHERE experiment_id=? AND owner=? ORDER BY created_at DESC LIMIT 30', (eid, owner)).fetchall()]
        row['opportunities'] = [json.loads(r[0]) for r in conn.execute('SELECT payload_json FROM EXPERIMENT_OPPORTUNITIES WHERE experiment_id=? ORDER BY created_at DESC LIMIT 20', (eid,)).fetchall()]
        return row


def implementation_update(db, eid, *, version, revision, status, commit, tests, deployment, owner='founder'):
    """Developer queue update. Evidence required before a request becomes ready."""
    with transaction(db) as conn:
        row = _load(conn, eid, owner)
        if row['version'] != version or row['revision'] != int(revision):
            raise ValueError('Stale implementation version')
        if row['status'] not in ('implementation_approved', 'implementing'):
            raise ValueError('Implementation was not approved')
        if status not in ('implementing', 'ready_for_activation'):
            raise ValueError('Unsupported implementation status')
        if status == 'ready_for_activation' and (len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit)
                or not tests or deployment != commit):
            raise ValueError('Exact commit, test evidence and matching verified deployment required')
        row['state']['implementation'] = dict(commit=commit, tests=str(tests)[:2000], deployment=deployment)
        row['status'] = status
        _event(conn, row, 'implementation_' + status, row['state']['implementation'], str(uuid4()))
        _save(conn, row)
        return row


def decide(db, eid, *, version, revision, action, key, owner='founder', scope=None):
    if not 8 <= len(key) <= 150:
        raise ValueError('Idempotency key required')
    scope = scope or {}
    with transaction(db) as conn:
        if action == 'enable_paper' and uses_postgres():
            conn.execute('SELECT pg_advisory_xact_lock(71911504)')
        row = _load(conn, eid, owner)
        previous = conn.execute('SELECT experiment_id,version,action,owner FROM EXPERIMENT_EVENTS WHERE idempotency_key=?', (key,)).fetchone()
        if previous:
            if (previous['experiment_id'], previous['version'], previous['action'], previous['owner']) != (eid, version, action, owner):
                raise ValueError('Idempotency key already belongs to another action')
            return row
        if version != row['version'] or int(revision) != row['revision']:
            raise ValueError('Stale approval; review current version')
        transitions = {'approve_library': ({'recommended'}, 'library_approved'),
                       'approve_implementation': ({'implementation_required'}, 'implementation_approved'),
                       'reject': ({'recommended', 'library_approved', 'implementation_required', 'ready_for_activation'}, 'rejected'),
                       'suspend': ({'paper_active', 'shadow_running', 'live_pilot_active'}, 'suspended')}
        if action == 'request_development':
            if row['status'] != 'library_approved' or not scope.get('requirements') or not scope.get('acceptance_tests'):
                raise ValueError('Accepted library strategy and explicit requirements/tests required')
            row['state']['development_request'] = {k: str(scope[k])[:2000] for k in ('requirements', 'acceptance_tests')}
            row['status'] = 'implementation_required'
        elif action == 'enable_live':
            raise ValueError('Live pilot disabled: separate execution validation and deployment interlocks required')
        elif action == 'enable_paper':
            import os
            if os.getenv('EXPERIMENT_PAPER_ADOPTION_ENABLED') != 'true':
                raise ValueError('Paper activation interlock disabled; developer must verify the paper execution path first')
            if row['status'] not in ('library_approved', 'ready_for_activation'):
                raise ValueError('Accept tested strategy into library first')
            if row['spec']['broker'] != 'alpaca' or row['spec']['rule_type'] != 'minimum_target_r':
                raise ValueError('This rule is shadow-only; production behaviour requires separate development')
            if row['state'].get('execution_validation', {}).get('status') != 'within_tolerance':
                raise ValueError('Broker comparison has not passed the frozen execution tolerances')
            cap = number(scope.get('max_notional_usd'), 1, 1000)
            expiry = stamp(scope.get('expires_at'))
            if not stamp(now_iso()) < expiry <= stamp(now_iso()) + timedelta(days=30):
                raise ValueError('Paper approval must expire within 30 days')
            active = conn.execute("SELECT id FROM RULE_EXPERIMENTS WHERE status='paper_active'").fetchone()
            if active:
                raise ValueError('Only one paper variant may be active')
            row['state']['activation'] = dict(environment='paper', broker='alpaca', max_notional_usd=cap,
                                            expires_at=expiry.isoformat(), version=version, approved_by=owner,
                                            activated_at=now_iso(), max_loss_usd=cap * .05)
            row['status'] = 'paper_active'
        elif action in transitions:
            allowed, target = transitions[action]
            if row['status'] not in allowed:
                raise ValueError('Action not permitted in current state')
            row['status'] = target
        else:
            raise ValueError('Unknown approval action')
        _event(conn, row, action, scope, key)
        _save(conn, row)
        return row


def paper_filter(db, proposal, *, broker, mode):
    """Extra rejection only. Never selects a broker, creates orders or weakens safeguards."""
    if broker.lower() != 'alpaca' or mode.lower() != 'paper' or proposal.side != 'buy':
        return {'allowed': True, 'version': None}
    with transaction(db) as conn:
        rows = conn.execute("SELECT id FROM RULE_EXPERIMENTS WHERE status='paper_active' LIMIT 2").fetchall()
        if not rows:
            return {'allowed': True, 'version': None}
        if len(rows) > 1:
            return {'allowed': False, 'version': None, 'reason': 'Conflicting paper activations; review required'}
        row = _load(conn, rows[0][0])
        activation = row['state']['activation']
        if (stamp(activation['expires_at']) <= stamp(now_iso()) or activation.get('version') != row['version']
                or row['spec']['baseline_fingerprint'] != baseline_fingerprint()):
            return {'allowed': False, 'version': row['version'], 'reason': 'Paper experiment approval expired; suspend or renew'}
        allowed = (proposal.side == 'buy' and passes(row['spec']['threshold'],
                   dict(entry=proposal.entry_price, stop=proposal.stop_loss, target=proposal.take_profit))
                   and proposal.entry_price * proposal.position_size <= activation['max_notional_usd'])
        return {'allowed': allowed, 'version': row['version'], 'experiment_id': row['id'], 'reason': 'Approved paper-only target/risk entry filter'}
