"""Read-only Learning screen projections. No LLM, settlement or trading side effects.

Aggregate in SQL, cache bounded period reports, page small detail projections.
Historical reports are reconstructed from current evidence, not frozen snapshots.
"""
from collections import OrderedDict
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import json
import sqlite3
import threading
import time

from .database import connect, database_url, uses_postgres

_cache = OrderedDict()
_lock = threading.Lock()
PAGE_SIZE = 20


def period_bounds(period='daily', anchor=None, now=None):
    today = (now or datetime.now(timezone.utc)).date()
    if period not in ('daily', 'weekly', 'monthly'):
        raise ValueError('Choose daily, weekly or monthly')
    chosen = date.fromisoformat(anchor) if anchor else today
    if chosen > today or chosen < date(2020, 1, 1):
        raise ValueError('Choose an available date, not a future date')
    start = chosen
    if period == 'weekly':
        start -= timedelta(days=start.weekday())
        end = start + timedelta(days=7)
    elif period == 'monthly':
        start = chosen.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        end = start + timedelta(days=1)
    return {'kind': period, 'start': start.isoformat(), 'end': end.isoformat(),
            'in_progress': end > today, 'timezone': 'UTC'}


def day(column):
    if uses_postgres():
        return f"""to_char((CASE WHEN {column} ~ '^[0-9]+([.][0-9]+)?$'
            THEN to_timestamp(CAST({column} AS DOUBLE PRECISION))
            ELSE CAST(NULLIF({column}, '') AS TIMESTAMPTZ) END) AT TIME ZONE 'UTC', 'YYYY-MM-DD')"""
    return f"date({column}, 'auto')"


def _read(db, sql, params=()):
    # Separate transactions keep a missing optional table from poisoning other sections.
    with closing(connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def _cached(key, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < 600:
            return hit[1]
        result = fn()
        _cache[key] = (time.monotonic(), result)
        _cache.move_to_end(key)
        while len(_cache) > 24:
            _cache.popitem(last=False)
        return result


def _outcomes():
    return f"""SELECT 'kraken' AS broker, symbol, {day('exit_time')} AS outcome_day,
        net_pnl AS pnl FROM KRAKEN_RECONCILED_RESULTS WHERE status='closed'
        UNION ALL
        SELECT 'alpaca' AS broker, symbol, {day('closed_at')} AS outcome_day,
        profit_loss AS pnl FROM PERFORMANCE_ATTRIBUTION
        WHERE broker='alpaca' AND exit_price IS NOT NULL AND attribution_id IN
        (SELECT MAX(attribution_id) FROM PERFORMANCE_ATTRIBUTION WHERE broker='alpaca'
         GROUP BY symbol, closed_at)"""


def learning_summary(db, period='daily', anchor=None, now=None):
    bounds = period_bounds(period, anchor, now)
    key = (str(db), database_url(), 'summary', bounds['kind'], bounds['start'])
    return _cached(key, lambda: _summary(db, bounds, now))


def _summary(db, bounds, now=None):
    args = (bounds['start'], bounds['end'])
    unavailable = []
    def read(name, sql, params=args):
        try:
            return _read(db, sql, params)
        except Exception:
            unavailable.append(name)
            return []
    outcomes = read('completed trades', f"""WITH outcomes AS ({_outcomes()})
        SELECT broker, COUNT(*) AS total, SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) AS wins,
        SUM(CASE WHEN pnl<0 THEN 1 ELSE 0 END) AS losses,
        SUM(CASE WHEN pnl IS NULL THEN 1 ELSE 0 END) AS unknown, SUM(pnl) AS pnl
        FROM outcomes WHERE outcome_day>=? AND outcome_day<? GROUP BY broker""")
    shadows = read('shadow tracking', f"""SELECT intended_broker AS broker,
        outcome_status, COUNT(*) AS total,
        SUM(CASE WHEN estimated_net_r>0 THEN 1 ELSE 0 END) AS estimated_wins,
        SUM(CASE WHEN estimated_net_r<0 THEN 1 ELSE 0 END) AS estimated_losses
        FROM SHADOW_TRADES WHERE {day('created_at')}>=? AND {day('created_at')}<?
        GROUP BY intended_broker, outcome_status""")
    rejections = read('rejection events', f"""SELECT COALESCE(selected_broker, 'unknown') AS broker,
        COUNT(*) AS events FROM ORCHESTRATOR_DECISIONS
        WHERE decision='rejected' AND {day('created_at')}>=? AND {day('created_at')}<?
        GROUP BY selected_broker""")
    reviews = read('trade reviews', f"""SELECT review_id, created_at, broker, symbol,
        outcome_classification, substr(what_happened,1,500) AS what_happened,
        substr(lessons_json,1,1800) AS lessons_json
        FROM POST_TRADE_REVIEWS WHERE {day('created_at')}>=? AND {day('created_at')}<?
        ORDER BY review_id DESC LIMIT 3""")
    review_counts = read('learning coverage', f"""SELECT COUNT(*) AS total,
        SUM(CASE WHEN experience_id IS NOT NULL THEN 1 ELSE 0 END) AS linked
        FROM POST_TRADE_REVIEWS WHERE {day('created_at')}>=? AND {day('created_at')}<?""")
    proposals = read('lesson proposals', f"""SELECT approval_status, COUNT(*) AS total
        FROM LEARNING_PROPOSALS WHERE {day('created_at')}>=? AND {day('created_at')}<?
        GROUP BY approval_status""")
    tests = read('strategy tests', f"""SELECT COUNT(*) AS total FROM STRATEGY_BACKTEST_RESULTS
        WHERE {day('created_at')}>=? AND {day('created_at')}<?""")
    previews = []
    for broker in ('kraken', 'alpaca'):
        previews += read('opportunity preview ' + broker, f"""SELECT shadow_trade_id AS id,
            symbol, intended_broker AS broker, intended_entry, stop_loss, take_profit,
            outcome_status, estimated_net_r, substr(wait_or_rejection_reason,1,180) AS reason
            FROM SHADOW_TRADES WHERE intended_broker=?
            AND (strategy='crypto_research_refused' OR decision_status='rejected')
            AND {day('created_at')}>=? AND {day('created_at')}<?
            ORDER BY shadow_trade_id DESC LIMIT 1""", (broker, *args))
    strategy_preview = read('strategy preview', """SELECT strategy_id AS id, name,
        substr(purpose,1,180) AS purpose, production_status
        FROM STRATEGY_REGISTRY ORDER BY updated_at DESC, strategy_id LIMIT 1""", ())
    previews.sort(key=lambda row: row['id'], reverse=True)
    for review in reviews:
        try:
            lessons = json.loads(review.pop('lessons_json'))
            review['lessons'] = [str(v)[:250] for v in lessons[:3]] if isinstance(lessons, list) else []
        except (ValueError, TypeError):
            review['lessons'] = []
    total = sum(row['total'] for row in outcomes)
    tracked = sum(row['total'] for row in shadows)
    review_total = review_counts[0]['total'] if review_counts else None
    narrative = ''
    if 'completed trades' not in unavailable:
        narrative += f'{total} completed trade outcomes are recorded. '
    if 'shadow tracking' not in unavailable:
        pending = sum(r['total'] for r in shadows if r['outcome_status'] == 'pending')
        narrative += f'{tracked} shadow candidates were recorded in this period; {pending} are still tracking. '
    if review_total is not None:
        narrative += f'{review_total} trade reviews were written. '
    if 'lesson proposals' not in unavailable:
        narrative += f"{sum(r['total'] for r in proposals)} lesson proposals were recorded. "
    if tests:
        narrative += f"{tests[0]['total']} historical test results were recorded. "
    if unavailable:
        narrative = 'Report incomplete: some evidence could not be loaded. ' + narrative
    narrative += 'Recorded lessons are hypotheses, not proof of improved returns.'
    from .learning_findings import period
    try:
        learning = period(db, bounds['start'], bounds['end'])
    except Exception:
        unavailable.append('learning findings')
        learning = {'findings':[], 'next_tests':[], 'truncated':False}
    return {'generated_at': (now or datetime.now(timezone.utc)).isoformat(), 'period': bounds,
            'unavailable': unavailable, 'summary': narrative, 'outcomes': outcomes, 'learning':learning,
            'shadows': shadows, 'rejections': rejections, 'reviews': reviews,
            'opportunity_previews': previews, 'strategy_preview': strategy_preview[0] if strategy_preview else None,
            'review_count': review_total, 'linked_reviews': review_counts[0]['linked'] if review_counts else None,
            'proposals': proposals, 'backtest_count': tests[0]['total'] if tests else None,
            'assessment': {'status': 'insufficient_evidence', 'validated': None,
                'explanation': 'See the separate Alpaca Experiments report for prospective paired comparisons. Review counts and backtests do not prove improvement.'},
            'next_step': 'Trace each proposed lesson to a named rule test against unchanged decisions before considering adoption.',
            'caveats': [
                'Opening this report does not run research, settle simulations or change trading rules.',
                'Trades are grouped by closing date; reviews by review date; candidates by decision date.',
                'Past periods are reconstructed from current records; late evidence can change their summaries.',
                'Kraken outcomes use recorded net P&L. Alpaca outcomes are before unreconciled fees; historical account mode may vary.',
                'Shadow candidates are not all confirmed rejections. Daily-candle simulations assume entry and use stop-first when both levels are crossed; they do not prove an executable fill.',
                'Rejection events can include repeated checks and are not a unique-opportunity count.']}


def learning_details(db, kind='rejected', period='daily', anchor=None, broker='all', page=0):
    bounds = period_bounds(period, anchor)
    if kind not in ('rejected', 'decisions', 'trades', 'strategies', 'tests', 'reviews', 'proposals'):
        raise ValueError('Unknown learning detail')
    if broker not in ('all', 'kraken', 'alpaca'):
        raise ValueError('Unknown exchange')
    page = int(page)
    if page < 0 or page > 100:
        raise ValueError('Page out of range; narrow the period')
    key = (str(db), database_url(), 'details', kind, bounds['start'], bounds['kind'], broker, page)
    return _cached(key, lambda: _details(db, kind, bounds, broker, page))


def _details(db, kind, bounds, broker, page):
    params = [bounds['start'], bounds['end']]
    if kind == 'rejected':
        sql = f"""SELECT shadow_trade_id AS id, created_at, intended_broker AS broker, symbol,
            strategy, intended_entry, stop_loss, take_profit, outcome_status, final_price,
            estimated_net_r, gross_r, substr(wait_or_rejection_reason,1,500) AS reason,
            CASE WHEN strategy='crypto_research_refused' OR decision_status='rejected'
                 THEN 'recorded rejection' ELSE 'shadow candidate; rejection unconfirmed' END AS provenance
            FROM SHADOW_TRADES WHERE {day('created_at')}>=? AND {day('created_at')}<?"""
        broker_col, order = 'intended_broker', 'shadow_trade_id'
    elif kind == 'decisions':
        sql = f"""SELECT decision_id AS id, created_at, selected_broker AS broker, symbol,
            substr(rejection_reason,1,500) AS reason, 'No exact simulation link' AS provenance
            FROM ORCHESTRATOR_DECISIONS WHERE decision='rejected'
            AND {day('created_at')}>=? AND {day('created_at')}<?"""
        broker_col, order = 'selected_broker', 'decision_id'
    elif kind == 'trades':
        sql = f"""SELECT broker, symbol, outcome_day AS created_at, pnl FROM ({_outcomes()}) o
            WHERE outcome_day>=? AND outcome_day<?"""
        broker_col, order = 'broker', 'outcome_day DESC, broker, symbol'
    elif kind == 'reviews':
        sql = f"""SELECT review_id AS id, created_at, broker, symbol,
            outcome_classification, substr(what_happened,1,700) AS what_happened,
            substr(lessons_json,1,1500) AS lessons_json FROM POST_TRADE_REVIEWS
            WHERE {day('created_at')}>=? AND {day('created_at')}<?"""
        broker_col, order = 'broker', 'review_id'
    elif kind == 'strategies':
        sql = """SELECT strategy_id AS id, name, substr(purpose,1,500) AS purpose,
            production_status, substr(historical_edge,1,500) AS evidence_note,
            updated_at AS created_at FROM STRATEGY_REGISTRY WHERE 1=1"""
        params, broker_col, order = [], None, 'strategy_id'
    elif kind == 'proposals':
        sql = f"""SELECT proposal_id AS id, created_at, proposal_type,
            substr(current_value,1,250) AS current_value, substr(proposed_value,1,250) AS proposed_value,
            sample_size, substr(expected_impact,1,500) AS expected_impact, approval_status
            FROM LEARNING_PROPOSALS WHERE {day('created_at')}>=? AND {day('created_at')}<?"""
        broker_col, order = None, 'proposal_id'
    else:
        sql = f"""SELECT backtest_id AS id, created_at, strategy_id, symbol, trades,
            win_rate, expectancy_r, max_drawdown_r, substr(result_summary,1,700) AS result_summary
            FROM STRATEGY_BACKTEST_RESULTS WHERE {day('created_at')}>=? AND {day('created_at')}<?"""
        broker_col, order = None, 'backtest_id'
    if broker != 'all' and broker_col:
        sql += f' AND {broker_col}=?'
        params.append(broker)
    sql += f" ORDER BY {order}{'' if kind == 'trades' else ' DESC'} LIMIT ? OFFSET ?"
    params += [PAGE_SIZE + 1, page * PAGE_SIZE]
    rows = _read(db, sql, tuple(params))
    return {'kind': kind, 'period': bounds, 'page': page, 'rows': rows[:PAGE_SIZE],
            'has_more': len(rows) > PAGE_SIZE, 'page_size': PAGE_SIZE,
            'note': 'Current strategy catalogue, not period activity.' if kind == 'strategies' else
                    'Recorded evidence only; no new tests or trades are started.'}
