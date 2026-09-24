"""Bounded, descriptive historical screening using the forward engine's pure step.

No broker, network, model, SQL supplied by a model, or live-adoption capability.
Recorded signals and explicitly labelled point-in-time market-rule opportunities are
replayable over source-vetted bars. Historical results are development evidence, NOT an
untouched holdout, reconstructed AI opinion or forecast.
"""
from copy import deepcopy
from datetime import timedelta
import inspect
import json
from pathlib import Path
import os
import tempfile

from . import experiments as e
from .experiment_assurance import json_field

VERSION = 'point-in-time-opportunity-replay-v2'
SUPPORTED = {'minimum_target_r', 'minimum_target_move_bps', 'replace_target_r_gate'}
MAX_ROWS = 64
MAX_ROW_BYTES = 8192
MAX_TRIALS = 10
MAX_CACHE_BYTES = 10 * 1024 * 1024


def _same_bar(left, right):
    """Compare replay semantics while ignoring optional provenance metadata."""
    fields = ('symbol', 'start', 'end', 'open', 'high', 'low', 'close', 'quality')
    return all(left.get(field) == right.get(field) for field in fields)


def recorded_signals(conn, broker, now):
    """One recorded buy assessment/day, at most 64 days; no historical AI recreation."""
    names = ('entry_price','stop_loss','take_profit','side','quote_currency','pre_experiment_eligibility')
    columns = ','.join(json_field('payload_json',['proposal',n])+' AS '+n for n in names)
    side = json_field('payload_json',['proposal','side'])
    entry = json_field('payload_json',['proposal','entry_price'])
    reason = json_field('payload_json',['reasons'],text=False)
    start = (e.stamp(now)-timedelta(days=120)).isoformat()
    # Choose IDs using small indexed fields BEFORE parsing any large JSON dossier.
    # Four sampled records/day avoids scanning all payloads to find a buy.
    rows = conn.execute('WITH sampled AS MATERIALIZED (SELECT decision_id FROM '
        '(SELECT decision_id,created_at,ROW_NUMBER() OVER (PARTITION BY SUBSTRING(created_at,1,10) ORDER BY decision_id) AS day_rank '
        'FROM DECISION_JOURNAL WHERE broker=? AND created_at>=? AND created_at<?) ranked '
        'WHERE day_rank<=4 ORDER BY created_at DESC LIMIT 256), '
        'records AS MATERIALIZED (SELECT j.* FROM DECISION_JOURNAL j JOIN sampled s ON j.decision_id=s.decision_id) '
        'SELECT proposal_id,symbol,created_at,execution_eligibility,'+columns+','+reason+' AS reasons FROM records '
        f'WHERE {side}=? AND {entry} IS NOT NULL ORDER BY created_at DESC LIMIT 64',(broker,start,now,'buy')).fetchall()
    signals=[]
    seen_days=set()
    for row in rows:
        try:
            symbol=str(row['symbol']).replace('/','').upper()
            currency=row['quote_currency']
            if broker=='kraken':
                if currency!='GBP' or symbol.endswith(('USD','EUR','USDT')):
                    continue
                if not symbol.endswith('GBP'):
                    symbol+='GBP'
            elif currency not in (None,'USD'):
                continue
            eligible=row['pre_experiment_eligibility'] or row['execution_eligibility']
            if eligible not in ('eligible','ineligible','rejected','blocked'):
                continue
            if not symbol.isalnum() or len(symbol)>16 or not row['proposal_id']:
                continue
            prices=[e.number(row[n],.000001,1_000_000) for n in ('entry_price','stop_loss','take_profit')]
            if not prices[1]<prices[0]<prices[2]:
                continue
            if row['created_at'][:10] in seen_days:
                continue
            seen_days.add(row['created_at'][:10])
            reasons=json.loads(row['reasons']) if isinstance(row['reasons'],str) else row['reasons']
            signals.append(dict(source_id=row['proposal_id'],symbol=symbol,time=row['created_at'],
                entry=prices[0],stop=prices[1],target=prices[2],eligible=eligible=='eligible',rejection_reasons=reasons))
        except (ValueError,TypeError):
            continue
    return signals


def recorded_bars(conn, broker, signals, now):
    """Read only existing, source-qualified prices; strict broker/currency separation."""
    symbols=sorted({s['symbol'] for s in signals})[:8]
    if not symbols:
        return []
    start=min(s['time'] for s in signals)
    placeholders=','.join('?' for _ in symbols)
    if broker=='alpaca':
        sql='SELECT symbol,observed_at AS time,open,high,low,close FROM HISTORICAL_CANDLES '
        sql+=f"WHERE symbol IN ({placeholders}) AND asset_type='stock' AND timeframe='1d' AND source='alpaca' AND observed_at>? AND observed_at<? ORDER BY observed_at,symbol LIMIT 640"
    else:
        # These symbols explicitly include GBP; never mix generic USD research candles.
        sql='SELECT normalized_symbol AS symbol,observation_time AS time,open,high,low,close FROM MARKET_DATA_OBSERVATIONS '
        sql+=f"WHERE normalized_symbol IN ({placeholders}) AND provider='kraken' AND timeframe='1d' AND adjusted_status='unadjusted' AND source_quality_status='pass' AND observation_time>? AND observation_time<? ORDER BY observation_time,normalized_symbol LIMIT 640"
    rows=conn.execute(sql,(*symbols,start,now)).fetchall()
    bars=[]
    for row in rows:
        try:
            begin=e.stamp(row['time']); end=begin+timedelta(days=1)
            if end>e.stamp(now):
                continue
            bars.append(dict(symbol=row['symbol'],start=begin.isoformat(),end=end.isoformat(),
                **{n:e.number(row[n],.000001,1_000_000) for n in ('open','high','low','close')},quality='verified_unadjusted'))
        except (ValueError,TypeError):
            continue
    return bars


def dataset(conn, broker, now, cached_bars=None):
    """One shared bounded read per broker/batch, not one history read per variation.

    Reuse bars already paid for by the shadow worker; never download market data.
    Oversized records are excluded explicitly, not silently treated as complete.
    Duplicate signals across experiments do not multiply the evidence.
    """
    broker_sql = json_field('r.spec_json', ['broker'])
    kind_sql = json_field('r.spec_json', ['rule_type'])
    rows = conn.execute(
        'SELECT payload_json FROM (SELECT o.payload_json,o.created_at,o.id,'
        'ROW_NUMBER() OVER(PARTITION BY o.source_id ORDER BY length(o.payload_json) DESC,o.id DESC) AS copy_rank '
        'FROM EXPERIMENT_OPPORTUNITIES o '
        'JOIN RULE_EXPERIMENTS r ON r.id=o.experiment_id '
        f'WHERE {broker_sql}=? AND {kind_sql}<>? AND o.created_at<? '
        'AND length(o.payload_json)<=?) copies WHERE copy_rank=1 ORDER BY created_at DESC,id DESC LIMIT ?',
        (broker, 'reference_set_filter', now, MAX_ROW_BYTES, MAX_ROWS)).fetchall()
    signals, bars, conflicts = {}, {}, set()
    fields = ('time', 'symbol', 'entry', 'stop', 'target', 'eligible', 'source_id', 'rejection_reasons')
    for row in rows:
        value = json.loads(row[0])
        signal = {k: value.get(k) for k in fields}
        key = str(signal['source_id'])
        if key in signals and signals[key] != signal:
            conflicts.add(key)
        signals[key] = signal
        for raw in value.get('bars', []):
            if raw.get('quality') != 'verified_unadjusted' or e.stamp(raw['end']) > e.stamp(now):
                continue
            bar = {**raw, 'symbol': signal['symbol']}
            identity = (bar['symbol'], bar['start'])
            if identity in bars and not _same_bar(bars[identity], bar):
                # Conflicting market history invalidates the dataset, not just one winner.
                return dict(signals=[], bars=[], reason='Conflicting recorded bars', broker=broker)
            bars[identity] = bar
    for signal in recorded_signals(conn,broker,now):
        key=str(signal['source_id'])
        if key in signals and signals[key]!=signal:
            conflicts.add(key)
        signals.setdefault(key,signal)
    signals = {k:v for k,v in signals.items() if k not in conflicts}
    signal_list = sorted(signals.values(), key=lambda s: (s['time'], s['symbol'], str(s['source_id'])))
    for bar in recorded_bars(conn,broker,signal_list,now):
        key=(bar['symbol'],bar['start'])
        if key in bars and not _same_bar(bars[key], bar):
            return dict(signals=[],bars=[],reason='Conflicting recorded bars',broker=broker)
        bars[key]=bar
    for bar in cached_bars or []:
        if bar.get('quality') != 'verified_unadjusted' or bar.get('symbol') not in {s['symbol'] for s in signal_list}:
            continue
        key=(bar['symbol'],bar['start'])
        if key in bars and not _same_bar(bars[key], bar):
            return dict(signals=[],bars=[],reason='Conflicting provider-cache bars',broker=broker)
        bars[key]=bar
    recorded_count = len(signals)
    from .historical_opportunities import generate, RULE_VERSION
    synthetic = generate(list(bars.values()), broker, limit=240)
    for signal in synthetic:
        signals.setdefault(str(signal['source_id']), signal)
    result = dict(broker=broker, signals=sorted(signals.values(), key=lambda s: (s['time'],s['symbol'],str(s['source_id']))),
                  bars=sorted(bars.values(), key=lambda b: (b['start'], b['symbol'])),
                  fetched_rows=len(rows), row_limit=MAX_ROWS, conflicting_signals=len(conflicts),
                  recorded_signal_count=recorded_count,
                  synthetic_signal_count=len(signals)-recorded_count,
                  historical_opportunity_rule=RULE_VERSION,
                  scope=('Recorded decisions plus explicitly labelled, point-in-time market-rule opportunities. '
                         'Synthetic opportunities use only prior prices and never claim to reconstruct an AI opinion, '
                         'another trader, news or fundamentals. Fresh forward evidence remains mandatory.'))
    result['dataset_version'] = e.digest(result)
    return result


def _semantic_frozen_dataset(data):
    """Return only content that contributes to the dataset version.

    Provider refresh metadata (request time, cache hit counters, and similar operational
    fields) can change while the actual signals and bars remain identical.  It must not be
    written beneath the same content-addressed filename and then mistaken for corruption.
    """
    return {key: value for key, value in data.items() if key != 'provider_cache'}


def freeze_dataset(db, data):
    """Content-addressed host cache; one copy per dataset, no database duplication.

    A persistent research volume can be configured. An ephemeral host may lose
    this cache on redeployment, so results never promise permanent reproducibility.
    Fail closed at the byte cap rather than silently deleting research evidence.
    """
    root = Path(os.getenv('AI_TRADER_RESEARCH_CACHE_DIR') or (Path(db).parent / 'research-cache'))
    root.mkdir(parents=True, exist_ok=True)
    frozen = _semantic_frozen_dataset(data)
    version = frozen.get('dataset_version') or e.digest(frozen)
    target = root / (version+'.json')
    raw = e.dump(frozen).encode('utf-8')
    if target.exists():
        try:
            existing = _semantic_frozen_dataset(json.loads(target.read_text(encoding='utf-8')))
            existing_raw = e.dump(existing).encode('utf-8')
        except (OSError, ValueError, TypeError):
            existing_raw = target.read_bytes()
        if existing_raw != raw:
            raise ValueError('Cached historical dataset differs from its frozen version')
        return version
    if sum(p.stat().st_size for p in root.glob('*.json')) + len(raw) > MAX_CACHE_BYTES:
        raise ValueError('Historical cache capacity reached; archive evidence before further screening')
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, suffix='.tmp', delete=False) as handle:
            temp = Path(handle.name)
            handle.write(raw)
        os.replace(temp, target)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()
    return version


def replay(spec, signals, bars, *, cutoff, cost_multiplier=1):
    """Chronological portfolio replay, using precisely the existing fill/risk engine."""
    spec = deepcopy(spec)
    if spec['rule_type'] not in SUPPORTED:
        raise ValueError('Unsupported historical rule; no invented historical AI assessment')
    spec['cost_bps_per_leg'] *= cost_multiplier
    spec['slippage_bps_per_leg'] *= cost_multiplier
    books = {a: dict(cash=spec['initial_cash'], equity=spec['initial_cash'], peak=spec['initial_cash'],
                    realised=0., max_drawdown=0., positions={}) for a in ('baseline', 'candidate')}
    ops, seen = [], set()
    for signal in sorted(signals, key=lambda s: (s['time'], s['symbol'], str(s['source_id']))):
        op = deepcopy(signal)
        if e.stamp(op['time']) >= e.stamp(cutoff):
            continue
        identity = (op['symbol'], op['time'][:10])
        if identity in seen:
            continue
        seen.add(identity)
        if not isinstance(op['eligible'], bool) or not 0 < op['stop'] < op['entry'] < op['target']:
            raise ValueError('Missing or invalid recorded eligibility/prices')
        candidate = op['eligible'] or (spec['rule_type'] == 'replace_target_r_gate'
            and op.get('rejection_reasons') == ['reward_risk_below_minimum'])
        passes = ((op['target']/op['entry']-1)*10000 >= spec['threshold']
                  if spec['rule_type'] == 'minimum_target_move_bps' else e.passes(spec['threshold'], op))
        op.update(last_bar=None, uncertain=False, arms={a: dict(status='awaiting_bar' if allow else 'skipped',
                  net=0., cost=0., quantity=0., reason='frozen historical rule')
                  for a, allow in [('baseline', op['eligible']), ('candidate', candidate and passes)]})
        ops.append(op)
    for bar in sorted(bars, key=lambda b: (b['start'], b['symbol'])):
        if bar.get('quality') != 'verified_unadjusted' or e.stamp(bar['end']) > e.stamp(cutoff):
            continue
        for op in ops:
            if op['symbol'] == bar['symbol']:
                e.step(spec, books, op, bar)
    completed = [o for o in ops if all(a['status'] in ('closed', 'skipped') for a in o['arms'].values())]
    useful = [o for o in completed if not o['uncertain'] and any(a['status'] == 'closed' for a in o['arms'].values())]
    return dict(opportunities=len(ops), resolved=len(completed), completed_trade_pairs=len(useful),
                independent_days=len({o['time'][:10] for o in useful}),
                unresolved=len(ops)-len(completed), uncertain=sum(o['uncertain'] for o in ops),
                baseline_net=round(books['baseline']['realised'], 4), candidate_net=round(books['candidate']['realised'], 4),
                delta=round(books['candidate']['realised']-books['baseline']['realised'], 4),
                drawdown={a: b['max_drawdown'] for a,b in books.items()},
                estimated_costs={a: round(sum(o['arms'][a]['cost'] for o in ops), 4) for a in books},
                open_positions={a: len(b['positions']) for a,b in books.items()})


def screen(spec, data, now):
    """Two chronological development partitions, purged for the holding horizon.

    The later partition is a robustness check, never advertised as independent
    final validation: model proposals may already have seen historical outcomes.
    Untouched evidence comes from the subsequent frozen forward experiment.
    """
    result = dict(engine=VERSION, engine_version=e.digest(inspect.getsource(e.step)+inspect.getsource(replay)+inspect.getsource(screen)),
                  spec_version=e.digest(spec),
                  frozen_spec=deepcopy(spec), deployment=os.getenv('RENDER_GIT_COMMIT','local-unverified'),
                  dataset_version=data.get('dataset_version'), at=now, broker=spec['broker'],
                  currency=spec['currency'], rule_type=spec['rule_type'], threshold=spec['threshold'],
                  status='data_required', reason='Not enough recorded history for chronological screening.',
                  scope=data.get('scope', data.get('reason')), validation='Historical development only; untouched forward evidence still required.')
    if spec['rule_type'] not in SUPPORTED:
        return {**result, 'status':'unsupported', 'reason':'Historical reference assessments cannot be reconstructed from prices.'}
    days = sorted({s['time'][:10] for s in data['signals']})
    result['coverage'] = dict(recorded_signals=data.get('recorded_signal_count', len(data['signals'])),
                              synthetic_opportunities=data.get('synthetic_signal_count', 0),
                              total_opportunities=len(data['signals']), bars=len(data['bars']),
                              first_day=days[0] if days else None, last_day=days[-1] if days else None,
                              signal_days=len(days),
                              opportunity_rule=data.get('historical_opportunity_rule'))
    if len(days) < 20:
        return result
    split = days[int(len(days)*.6)] + 'T00:00:00+00:00'
    purge = e.stamp(split)-timedelta(days=spec['max_holding_days']+1)
    training = [s for s in data['signals'] if e.stamp(s['time']) < purge]
    later = [s for s in data['signals'] if e.stamp(s['time']) >= e.stamp(split)]
    result['split_at'] = split
    result['purge_days'] = spec['max_holding_days']+1
    result['early'] = replay(spec, training, data['bars'], cutoff=split)
    result['later'] = replay(spec, later, data['bars'], cutoff=now)
    result['cost_stress'] = replay(spec, later, data['bars'], cutoff=now, cost_multiplier=2)
    # Frozen nearby settings are robustness checks, not a search for a winning setting.
    maximum = 5000 if spec['rule_type']=='minimum_target_move_bps' else 4
    thresholds = sorted({max(1,min(maximum,spec['threshold']*factor)) for factor in (.9,1.1)}-{spec['threshold']})
    result['nearby_settings'] = [dict(threshold=t, result=replay({**spec,'threshold':t},later,data['bars'],cutoff=now)) for t in thresholds]
    runs = [result[k] for k in ('early', 'later', 'cost_stress')]
    runs += [r['result'] for r in result['nearby_settings']]
    result['replay_count'] = len(runs)
    if any(r['completed_trade_pairs'] < 10 or r['independent_days'] < 5 or r['unresolved'] or r['uncertain'] for r in runs):
        return {**result, 'reason':'Insufficient completed, unambiguous comparisons; open trades are not force-closed.'}
    passed = all(r['delta'] > 0 and r['candidate_net'] > 0 and
                 r['drawdown']['candidate'] <= min(spec['max_drawdown_fraction'], r['drawdown']['baseline']) for r in runs)
    return {**result, 'status':'promising' if passed else 'not_supported',
            'reason':'Historical checks passed; requires fresh shadow evidence.' if passed else 'Historical after-cost or risk checks did not support this candidate.'}


def screen_batch(db, candidates, now, *, force=False):
    """One deterministic batch/day, shared datasets, no extra model requests."""
    if len(candidates) > MAX_TRIALS:
        raise ValueError('Historical batch limit exceeded')
    with e.transaction(db) as conn:
        from .database import uses_postgres
        if uses_postgres():
            conn.execute('SELECT pg_advisory_xact_lock(71911504)')
        prior = e.control(conn, 'historical_screening', {})
        if prior.get('day') == now[:10] and not force:
            return prior
        # Reserve before computation: restart/error cannot repeat the daily work.
        e.put_control(conn, 'historical_screening', dict(day=now[:10], status='reserved', trials=[]))
    try:
        datasets, trials = {}, []
        for candidate in candidates:
            try:
                spec = e.validate_spec(candidate)
                if spec['broker'] not in datasets:
                    with e.transaction(db) as conn:
                        signals = recorded_signals(conn, spec['broker'], now)
                    from .config import load_settings
                    from .historical_market_cache import refresh
                    provider = refresh(db, load_settings(), spec['broker'], [s['symbol'] for s in signals], now)
                    with e.transaction(db) as conn:
                        loaded = dataset(conn, spec['broker'], now, provider['bars'])
                    loaded['provider_cache'] = {k:v for k,v in provider.items() if k != 'bars'}
                    freeze_dataset(db, loaded)
                    datasets[spec['broker']] = loaded
                trial = screen(spec, datasets[spec['broker']], now)
                trial.update(hypothesis=spec['hypothesis'], candidate_key=e.digest(candidate))
                trial['cache_scope'] = 'Content-addressed research-host cache; persistence depends on the host volume.'
                trials.append(trial)
            except (ValueError, TypeError, KeyError) as exc:
                trials.append(dict(status='invalid', reason=str(exc)[:200], candidate_key=e.digest(candidate)))
        result = dict(day=now[:10], at=now, status='completed', trials=trials,
                      max_shadow_history_characters=2*MAX_ROWS*MAX_ROW_BYTES,
                      scope=('Recorded and labelled point-in-time opportunity replay using a bounded '
                             'provider-to-Render daily-bar cache. No additional AI calls; bulk bars are not stored in Supabase.'))
    except Exception as exc:
        result = dict(day=now[:10], at=now, status='failed', trials=[], error_type=type(exc).__name__)
    with e.transaction(db) as conn:
        e.put_control(conn, 'historical_screening', result)
        e.put_control(conn, 'historical_screening_view', {k:result[k] for k in ('day','at','status')} | {
            'trials':[{k:t.get(k) for k in ('hypothesis','broker','currency','status','reason','coverage','later')}
                      for t in result['trials']]})
        history = e.control(conn, 'historical_screening_history', [])
        e.put_control(conn, 'historical_screening_history', (history+[result])[-30:])
        from .learning_findings import save
        for broker in ('alpaca', 'kraken'):
            own = [t for t in result['trials'] if t.get('broker') == broker]
            if own:
                counts = {s:sum(t['status']==s for t in own) for s in ('promising','not_supported','data_required','unsupported')}
                save(conn, source_type='historical_screening', source_id=now[:10]+':'+broker,
                     recorded_at=now, broker=broker, symbol=None, payload=dict(
                     what_was_learnt=f"Screened {len(own)} historical candidates: {counts['promising']} promising, {counts['not_supported']} unsupported by results, {counts['data_required']} need more data.",
                     future_use='Promising candidates still require unchanged forward comparisons. Missing history is not a pass.',
                     evidence_status='Historical development, not proven improvement', action='research', activation='not_activated'))
        from .founder_learning import refresh as refresh_founder_learning
        refresh_founder_learning(conn, now=now, force=True)
    return result


def refresh_active_screening(db, settings, now):
    """Refresh provider history and replay active experiments without an AI call.

    This is intentionally independent of the once-daily proposal/model budget.  The former
    implementation put the market-data import behind successful candidate generation, so a
    reference-set refresh could consume the shared budget first and leave the historical
    cache empty indefinitely.  Existing frozen specs are sufficient to exercise the importer
    and replay engine; this job cannot create, promote, or trade an experiment.
    """
    with e.transaction(db) as conn:
        rows = conn.execute(
            "SELECT spec_json FROM RULE_EXPERIMENTS WHERE status IN ('queued','shadow_running') "
            "ORDER BY created_at DESC LIMIT ?", (MAX_TRIALS,)
        ).fetchall()
    candidates = []
    for row in rows:
        try:
            value = json.loads(row[0])
            e.validate_spec(value)
            candidates.append(value)
        except (ValueError, TypeError, KeyError):
            continue
    if not candidates:
        return dict(status='no_active_experiments', at=now, trials=[],
                    message='No frozen active experiment specs were available to replay.')
    result = screen_batch(db, candidates, now, force=True)
    result['trigger'] = 'scheduled_historical_market_refresh'
    result['model_calls'] = 0
    return result
