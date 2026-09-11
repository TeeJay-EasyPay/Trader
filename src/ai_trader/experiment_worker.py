"""Low priority, bounded experiment work. No broker client imports or order calls.

Dedicated thread avoids blocking protective-exit scheduling. A durable lease
serializes workers; input/output caps and watermarks bound database traffic.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import threading
import time

from . import experiments as exp
from .database import connect, uses_postgres

log = logging.getLogger(__name__)
QUESTION = '''Propose at most one falsifiable Alpaca paper experiment from these completed
outcomes. They are GROSS before unknown fees. Do not claim causation, profitability,
or calibrated probabilities. Supported rule: minimum_target_r, a stricter entry
filter based on planned target distance / stop distance, NOT expected return.
Keep entry/exit generation and safeguards unchanged. Return ONLY JSON:
{"rule_type":"minimum_target_r","threshold":2.5,"hypothesis":"...",
"evidence_ids":[existing attribution ids]} or {"no_change":"reason"}.
No trades, tools, arbitrary code, live activation or settings changes. Propose a
test only if the evidence supports investigating it; do not invent missing data.'''


def _lease(db, now):
    with exp.transaction(db) as conn:
        if uses_postgres():
            conn.execute("SELECT pg_advisory_xact_lock(71911501)")
        lease = exp.control(conn, 'lease', {})
        if lease.get('until', '') > now:
            return False
        exp.put_control(conn, 'lease', {'until': (exp.stamp(now) + timedelta(minutes=10)).isoformat()})
        return True


def propose(db, settings, now, policy, answer=None):
    """At most one billed attempt/day, reserved BEFORE call; timeout is not retried."""
    if not policy.get('model_enabled'):
        return 'model_disabled'
    with exp.transaction(db) as conn:
        attempts = exp.control(conn, 'proposal_attempt', {})
        if attempts.get('day') == now[:10]:
            return 'daily_model_budget_reached'
        if conn.execute("SELECT COUNT(*) FROM RULE_EXPERIMENTS WHERE status='shadow_running'").fetchone()[0]:
            return 'experiment_running'
        rows = conn.execute("SELECT p.attribution_id,p.symbol,p.closed_at,p.profit_loss,p.holding_period_seconds,"
                            "t.intended_entry_price,t.original_stop,t.intended_target "
                            "FROM PERFORMANCE_ATTRIBUTION p JOIN LOGICAL_TRADES t ON t.proposal_id=p.proposal_id AND t.broker='alpaca' "
                            "WHERE p.broker='alpaca' AND p.exit_price IS NOT NULL "
                            "ORDER BY p.attribution_id DESC LIMIT 30").fetchall()
        evidence = [dict(r) for r in rows]
        watermark = exp.control(conn, 'proposal_watermark', 0)
        if sum(r['attribution_id'] > watermark for r in evidence) < policy['min_new_outcomes']:
            return 'insufficient_new_linked_outcomes'
        if len(exp.dump(evidence)) > 10000:
            return 'input_budget_exceeded'
        exp.put_control(conn, 'proposal_attempt', {'day': now[:10], 'status': 'reserved', 'max_output_tokens': 1000})
        previous = conn.execute('SELECT id,version,status,spec_json,report_json FROM RULE_EXPERIMENTS ORDER BY created_at DESC LIMIT 24').fetchall()
        prior = []
        for r in previous:
            spec, report = json.loads(r['spec_json']), json.loads(r['report_json'])
            prior.append(dict(id=r['id'], version=r['version'], status=r['status'], threshold=spec['threshold'],
                              hypothesis=spec['hypothesis'][:200], observations=report.get('observations'),
                              usable=report.get('usable'), paired_mean_usd=report.get('paired_mean_usd'),
                              candidate_net_usd=(report.get('candidate') or {}).get('realised'),
                              candidate_drawdown=(report.get('candidate') or {}).get('max_drawdown')))
    try:
        if answer is None:
            from .ai import OpenAIReadOnlyExplainer
            answer = OpenAIReadOnlyExplainer(settings.openai_api_key, settings.openai_model,
                                            timeout_seconds=20, max_output_tokens=1000).answer
        context = {'outcomes': evidence, 'previous_experiments': prior}
        if len(exp.dump(context)) > 18000:
            raise ValueError('Combined evidence and library input budget reached')
        raw = answer(QUESTION + ' Use prior experiment results, including failures; do not repeat a rejected threshold without new supporting evidence.', context)
        raw = raw.strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
        candidate = json.loads(raw)
        if 'no_change' in candidate:
            result = {'status': 'no_justified_change', 'reason': str(candidate['no_change'])[:800]}
        else:
            if not set(candidate.get('evidence_ids', [])).issubset({r['attribution_id'] for r in evidence}):
                raise ValueError('Model cited evidence it was not supplied')
            row = exp.create_experiment(db, candidate, now=now)
            result = {'status': 'created', 'experiment_id': row['id']}
        with exp.transaction(db) as conn:
            exp.put_control(conn, 'proposal_watermark', max(r['attribution_id'] for r in evidence))
    except Exception as exc:
        result = {'status': 'proposal_failed', 'error_type': type(exc).__name__, 'reason': 'No automatic retry; budget reserved.'}
    with exp.transaction(db) as conn:
        exp.put_control(conn, 'proposal_attempt', {'day': now[:10], **result})
    return result


def _decisions(db, cursor, created_at):
    # Project only the small proposal fields. Never transfer the complete dossier.
    def field(name):
        if uses_postgres():
            return f"payload_json::jsonb #>> '{{proposal,{name}}}'"
        return f"json_extract(payload_json, '$.proposal.{name}')"
    fields = ','.join(field(n) + ' AS ' + n for n in ('entry_price', 'stop_loss', 'take_profit', 'side'))
    with exp.transaction(db) as conn:
        return [dict(r) for r in conn.execute(f'SELECT decision_id,created_at,proposal_id,symbol,execution_eligibility,{fields} '
                 "FROM DECISION_JOURNAL WHERE broker='alpaca' AND decision_id>? AND created_at>=? ORDER BY decision_id LIMIT 20",
                 (cursor, created_at)).fetchall()]


def _bars(db, symbols, since, now):
    if not symbols:
        return []
    with exp.transaction(db) as conn:
        # Existing equity ingestion uses Alpaca raw IEX daily bars in this table.
        # MARKET_DATA_OBSERVATIONS currently contains crypto only in production.
        rows = conn.execute('SELECT symbol AS normalized_symbol,observed_at AS observation_time,open,high,low,close,source '
            'FROM HISTORICAL_CANDLES WHERE symbol IN (' + ','.join('?' for _ in symbols) + ') '
            "AND asset_type='stock' AND timeframe='1d' AND source='alpaca' "
            'AND observed_at>? AND observed_at<? ORDER BY observed_at,symbol LIMIT 200',
            (*symbols, since, now)).fetchall()
    result, seen = [], set()
    for r in rows:
        key = (r['normalized_symbol'], r['observation_time'])
        if key in seen:
            continue
        seen.add(key)
        try:
            start = exp.stamp(r['observation_time'])
            # Daily data considered available only after its whole day has elapsed.
            end = start + timedelta(days=1)
            result.append(dict(symbol=r['normalized_symbol'], start=start.isoformat(), end=end.isoformat(),
                               open=r['open'], high=r['high'], low=r['low'], close=r['close'],
                               quality='verified_unadjusted', source='alpaca_raw_iex_daily'))
        except (ValueError, TypeError):
            continue
    return result


def tick(db, settings, *, now=None, answer=None):
    now = now or exp.now_iso()
    with exp.transaction(db) as conn:
        policy = exp.control(conn, 'policy', exp.DEFAULT_POLICY)
        if not policy['enabled']:
            return {'status': 'disabled'}
        # Global cap includes records and indexes conservatively via payload budget.
        size = conn.execute('SELECT COALESCE(SUM(length(payload_json)),0) AS bytes FROM EXPERIMENT_OPPORTUNITIES').fetchone()[0]
        if size * 3 >= policy['storage_bytes']:
            exp.put_control(conn, 'last_tick', {'status': 'storage_budget_reached', 'at': now})
            return {'status': 'storage_budget_reached'}
    if not _lease(db, now):
        return {'status': 'leased'}
    started = time.monotonic()
    try:
        proposal = propose(db, settings, now, policy, answer=answer)
        with exp.transaction(db) as conn:
            active = conn.execute("SELECT id FROM RULE_EXPERIMENTS WHERE status='shadow_running' LIMIT 1").fetchall()
        processed, invalid = 0, 0
        for r in active:
            row = exp.detail(db, r[0])
            if row['spec']['baseline_fingerprint'] != exp.baseline_fingerprint():
                with exp.transaction(db) as conn:
                    current = exp._load(conn, row['id'])
                    current['status'] = 'insufficient_evidence'
                    current['report'] = {'verdict': 'insufficient_evidence', 'reason': 'Baseline deployment changed; freeze a new comparison.'}
                    exp._event(conn, current, 'baseline_changed', current['report'], 'baseline:' + row['id'])
                    exp._save(conn, current)
                continue
            cursor = row['state']['cursor']
            # Decision ingestion stops at frozen evaluation deadline, not indefinitely.
            deadline = exp.stamp(row['created_at']) + timedelta(days=row['spec']['evaluation_days'])
            for d in _decisions(db, cursor, row['created_at']):
                if time.monotonic() - started > 25:
                    break
                if exp.stamp(d['created_at']) > deadline:
                    cursor = d['decision_id']
                    continue
                try:
                    if d['side'] != 'buy':
                        raise ValueError('Only long equity proposals supported')
                    exp.add_opportunity(db, row['id'], dict(source_id=d['proposal_id'], symbol=d['symbol'], time=d['created_at'],
                        entry=d['entry_price'], stop=d['stop_loss'], target=d['take_profit'], eligible=d['execution_eligibility'] == 'eligible'))
                    processed += 1
                except (ValueError, TypeError):
                    invalid += 1
                cursor = d['decision_id']
            with exp.transaction(db) as conn:
                current = exp._load(conn, row['id'])
                current['state']['cursor'] = cursor
                current['state']['blocked'] += invalid
                exp._save(conn, current)
                # Re-evaluate the full small paired sample at most once per day,
                # not on every 15-minute tick (important for Supabase egress).
                settled_day = exp.control(conn, 'settled:' + row['id'], '')
                if settled_day == now[:10] or exp.stamp(now).hour < 9:
                    continue
                # Only unresolved pairs need new candles; no unbounded history reads.
                unresolved = conn.execute('SELECT payload_json FROM EXPERIMENT_OPPORTUNITIES WHERE experiment_id=? ORDER BY created_at LIMIT 1200', (row['id'],)).fetchall()
            ops = [json.loads(o[0]) for o in unresolved]
            pending = [o for o in ops if any(a['status'] in ('open','awaiting_bar') for a in o['arms'].values())]
            since = min((o.get('last_bar') or o['time'] for o in pending), default=now)
            bars = _bars(db, sorted({o['symbol'] for o in pending}), since, now)
            missing = sorted({o['symbol'] for o in pending} - {b['symbol'] for b in bars})
            if missing:
                from .experiment_market_data import missing_bars
                bars += missing_bars(db, settings, missing, now)
            exp.settle_bars(db, row['id'], bars, now=now)
            with exp.transaction(db) as conn:
                exp.put_control(conn, 'settled:' + row['id'], now[:10])
        status = {'status': 'completed', 'at': now, 'proposal': proposal, 'processed': processed,
                  'invalid': invalid, 'elapsed_seconds': round(time.monotonic() - started, 3), 'broker_orders': 0}
        with exp.transaction(db) as conn:
            exp.put_control(conn, 'last_tick', status)
        return status
    finally:
        with exp.transaction(db) as conn:
            exp.put_control(conn, 'lease', {})


def critical_work(db, now=None):
    """Check this instance, not abandoned rows from an earlier deployment.

    Existing scheduled-job bookkeeping can relabel the same worker row, so its
    mutable worker_type is not a reliable identity filter.
    """
    now = now or exp.now_iso()
    instance = os.getenv('RENDER_INSTANCE_ID')
    with exp.transaction(db) as conn:
        if instance:
            row = conn.execute('SELECT current_job,last_heartbeat_at FROM WORKER_HEARTBEATS WHERE worker_id=?',
                               ('background-worker-' + instance,)).fetchone()
        else:
            row = conn.execute('SELECT current_job,last_heartbeat_at FROM WORKER_HEARTBEATS ORDER BY last_heartbeat_at DESC LIMIT 1').fetchone()
    if not row or exp.stamp(now) - exp.stamp(row[1]) > timedelta(minutes=2):
        return False
    job = str(row[0] or '')
    return job in ('starting', 'kraken-startup-reconciliation', 'managed-exits') or job.startswith('broker-poll')


class ExperimentScheduler:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self.stop = threading.Event()

    def __enter__(self):
        try:
            exp.migrate(self.db)
        except Exception as exc:
            log.error('Experiments unavailable; normal trading startup continues: %s', type(exc).__name__)
            return self
        self.thread = threading.Thread(target=self.run, name='shadow-experiments', daemon=True)
        self.thread.start()
        return self

    def run(self):
        # First review after startup has cleared critical work, then 15-minute cadence.
        # The cheap liveness check never performs research or broker operations.
        next_due = 0.0
        while not self.stop.wait(60):
            if time.monotonic() < next_due:
                continue
            try:
                if critical_work(self.db):
                    continue
                tick(self.db, self.settings)
                next_due = time.monotonic() + 900
            except Exception as exc:
                log.warning('Shadow experiments failed safely: %s', type(exc).__name__)
                next_due = time.monotonic() + 900
                try:
                    with exp.transaction(self.db) as conn:
                        exp.put_control(conn, 'last_tick', {'status': 'failed', 'at': exp.now_iso(), 'error_type': type(exc).__name__})
                except Exception:
                    log.warning('Experiment health write also unavailable')

    def __exit__(self, *args):
        self.stop.set()
