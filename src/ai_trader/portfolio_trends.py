"""Bounded, read-only chart projection. No broker calls, new tables or trading writes."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import math
import threading
import time

from .database import connect, uses_postgres, database_url

_cache = {}
_lock = threading.Lock()
CACHE_SECONDS = 600


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _json_field(path):
    if uses_postgres():
        return "payload_json::jsonb #>> '{" + ','.join(path.split('.')) + "}'"
    return "json_extract(CASE WHEN json_valid(payload_json) THEN payload_json ELSE '{}' END, '$." + path + "')"


def _day(column):
    # Existing outcomes contain both ISO dates and Unix timestamps. Normalize in
    # SQL so an entire trade history never leaves the database for chart grouping.
    if uses_postgres():
        return f"""CASE WHEN {column} ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' THEN substr({column},1,10)
            WHEN {column} ~ '(^[0-9]{{9,10}}$|^[0-9]{{9,10}}[.][0-9]+$)'
            THEN to_char(to_timestamp(CAST({column} AS DOUBLE PRECISION)) AT TIME ZONE 'UTC','YYYY-MM-DD') END"""
    return f"""CASE WHEN substr({column},5,1) = '-' THEN substr({column},1,10)
        ELSE date({column}, 'unixepoch') END"""


def build_portfolio_trends(db_path, *, now=None, value_scope='ai_capital'):
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=89)).date().isoformat()
    until = now.date().isoformat()
    result = {'as_of': now.isoformat(), 'timezone': 'UTC', 'days': 90, 'brokers': []}
    brokers = {name: {'broker': name, 'currency': currency, 'values': [], 'outcomes': [],
                     'value_status': 'unavailable', 'outcome_status': 'unavailable',
                     'pnl_basis': 'net_after_fees' if name == 'kraken' else 'recorded_before_unreconciled_fees',
                     'value_scope': 'whole_account' if name != 'kraken' or value_scope == 'whole_account' else 'ai_capital',
                     'cash_flows': 'allocation_changes' if name == 'kraken' and value_scope != 'whole_account' else 'unavailable'}
               for name, currency in [('kraken', 'GBP'), ('alpaca', 'USD')]}
    fields = ', '.join(_json_field('trading_permissions.ai_capital_ledger.' + key) + ' AS ' + key
                       for key in ['available_cash_gbp', 'deployed_capital_gbp', 'unrealized_pnl_gbp', 'allocation_gbp'])
    if value_scope == 'whole_account':
        # Unique aliases are required by the PostgreSQL dictionary-row adapter.
        # Repeated unnamed NULL columns collapse to one key and lose positional fields.
        fields = ', '.join('NULL AS ' + key for key in
                          ['available_cash_gbp', 'deployed_capital_gbp', 'unrealized_pnl_gbp', 'allocation_gbp'])
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute(f"""
                WITH ranked AS (
                    SELECT snapshot_id, broker, account_mode, captured_at, currency,
                           portfolio_value, error, payload_json,
                           ROW_NUMBER() OVER (PARTITION BY broker, substr(captured_at,1,10)
                               ORDER BY captured_at DESC, snapshot_id DESC) AS day_rank,
                           FIRST_VALUE(account_mode) OVER (PARTITION BY broker
                               ORDER BY captured_at DESC, snapshot_id DESC) AS latest_mode
                    FROM PRODUCTION_BROKER_SNAPSHOTS
                    WHERE captured_at >= ? AND substr(captured_at,1,10) <= ?
                      AND broker IN ('kraken','alpaca')
                )
                SELECT broker, substr(captured_at,1,10) AS day, captured_at, account_mode,
                       currency, portfolio_value, error, {fields}
                FROM ranked WHERE day_rank = 1 AND COALESCE(account_mode,'') = COALESCE(latest_mode,'')
                ORDER BY broker, captured_at LIMIT 180
            """, (since, until)).fetchall()
        for row in rows:
            item = brokers[row[0]]
            item['account_mode'] = row[3]
            value = _number(row[5])
            allocation = _number(row[10])
            if row[0] == 'kraken' and value_scope != 'whole_account':
                parts = [_number(row[i]) for i in (7, 8, 9)]
                value = sum(parts) if all(part is not None for part in parts) else None
            if row[6] or row[4] != item['currency']:
                value = None
            item['values'].append({'date': row[1], 'captured_at': row[2],
                                   'value': round(value, 8) if value is not None else None,
                                   'allocation': allocation if row[0] == 'kraken' else None})
        for item in brokers.values():
            item['value_status'] = 'ok'
    except Exception:
        # Missing/invalid historical data is explicitly unavailable, never a flat zero line.
        for item in brokers.values():
            item['values'] = []
    for broker, table, stamp, pnl, predicate in (
        ('kraken', 'KRAKEN_RECONCILED_RESULTS', 'exit_time', 'net_pnl', "status = 'closed'"),
        ('alpaca', 'PERFORMANCE_ATTRIBUTION', 'closed_at', 'profit_loss',
         "broker = 'alpaca' AND exit_price IS NOT NULL AND attribution_id IN "
         "(SELECT MAX(attribution_id) FROM PERFORMANCE_ATTRIBUTION WHERE broker = 'alpaca' GROUP BY symbol, closed_at)"),
    ):
        try:
            with closing(connect(db_path)) as conn:
                rows = conn.execute(f"""
                    WITH dated AS (SELECT {_day(stamp)} AS day, {pnl} AS net_pnl FROM {table}
                        WHERE {predicate} AND {stamp} IS NOT NULL)
                    SELECT day, SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                        SUM(CASE WHEN net_pnl < 0 THEN 1 ELSE 0 END) AS losses,
                        SUM(CASE WHEN net_pnl = 0 THEN 1 ELSE 0 END) AS breakeven,
                        SUM(CASE WHEN net_pnl IS NULL THEN 1 ELSE 0 END) AS unknown,
                        SUM(net_pnl) AS net_pnl
                    FROM dated WHERE day >= ? AND day <= ? GROUP BY day ORDER BY day LIMIT 90
                """, (since, until)).fetchall()
            brokers[broker]['outcomes'] = [dict(zip(
                ['date', 'wins', 'losses', 'breakeven', 'unknown', 'net_pnl'],
                [row[i] for i in range(6)])) for row in rows]
            brokers[broker]['outcome_status'] = 'ok'
        except Exception:
            pass
    result['brokers'] = list(brokers.values())
    return result


def portfolio_trends(db_path, *, value_scope='ai_capital'):
    # Single-flight and two bounded scope entries per process. Navigation doesn't
    # refetch history every time, and errors retry without a permanent empty cache.
    value_scope = 'whole_account' if value_scope == 'whole_account' else 'ai_capital'
    key = (str(db_path), database_url(), value_scope)
    with _lock:
        entry = _cache.get(key)
        if entry and time.monotonic() - entry[0] < CACHE_SECONDS:
            return entry[1]
        result = build_portfolio_trends(db_path, value_scope=value_scope)
        if len(_cache) >= 2 and key not in _cache:
            del _cache[min(_cache, key=lambda k: _cache[k][0])]
        _cache[key] = (time.monotonic(), result)
        return result
