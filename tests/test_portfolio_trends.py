from contextlib import closing
from datetime import datetime, timezone
import json
from unittest.mock import patch

import pytest

from ai_trader.database import connect
from ai_trader.portfolio_trends import build_portfolio_trends, portfolio_trends, _cache

NOW = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / 'charts.db'
    with closing(connect(path)) as conn, conn:
        conn.executescript('''
            CREATE TABLE PRODUCTION_BROKER_SNAPSHOTS (snapshot_id INTEGER PRIMARY KEY,
              broker TEXT, account_mode TEXT, captured_at TEXT, currency TEXT,
              portfolio_value REAL, error TEXT, payload_json TEXT);
            CREATE TABLE KRAKEN_RECONCILED_RESULTS (exit_time TEXT, status TEXT, net_pnl REAL);
            CREATE TABLE PERFORMANCE_ATTRIBUTION (attribution_id INTEGER PRIMARY KEY,
                broker TEXT, symbol TEXT, closed_at TEXT, exit_price REAL, profit_loss REAL);
        ''')
    return path


def snapshot(conn, ident, date, broker='kraken', mode='live', missing=False):
    ledger = {'available_cash_gbp': 80, 'deployed_capital_gbp': 20,
              'unrealized_pnl_gbp': None if missing else 2, 'allocation_gbp': 100}
    conn.execute('INSERT INTO PRODUCTION_BROKER_SNAPSHOTS VALUES (?, ?, ?, ?, ?, ?, NULL, ?)',
                 (ident, broker, mode, date, 'GBP' if broker == 'kraken' else 'USD', 99999,
                  json.dumps({'trading_permissions': {'ai_capital_ledger': ledger}})))


def test_latest_daily_ai_values_never_personal_holdings_and_missing_prices(db):
    with closing(connect(db)) as conn, conn:
        snapshot(conn, 1, '2026-09-08T10:00:00Z')
        snapshot(conn, 2, '2026-09-08T11:00:00Z')
        snapshot(conn, 3, '2026-09-09T10:00:00Z', missing=True)
        snapshot(conn, 4, '2026-01-01T10:00:00Z')
    result = build_portfolio_trends(db, now=NOW)['brokers'][0]
    assert result['value_status'] == 'ok'
    assert len(result['values']) == 2
    assert result['values'][0]['value'] == 102
    assert result['values'][1]['value'] is None
    assert result['values'][0]['allocation'] == 100


def test_account_modes_not_stitched_together(db):
    with closing(connect(db)) as conn, conn:
        snapshot(conn, 1, '2026-09-08T10:00:00Z', 'alpaca', 'paper')
        snapshot(conn, 2, '2026-09-09T10:00:00Z', 'alpaca', 'live')
    result = build_portfolio_trends(db, now=NOW)['brokers'][1]
    assert len(result['values']) == 1
    assert result['values'][0]['value'] == 99999
    assert result['cash_flows'] == 'unavailable'


def test_closed_net_results_unknown_breakeven_epoch_and_broker_isolation(db):
    with closing(connect(db)) as conn, conn:
        for pnl in (2, -3, 0, None):
            conn.execute("INSERT INTO KRAKEN_RECONCILED_RESULTS VALUES ('2026-09-08T12:00:00Z', 'closed', ?)", (pnl,))
        conn.execute("INSERT INTO KRAKEN_RECONCILED_RESULTS VALUES ('1788955200', 'closed', 4)")
        conn.execute("INSERT INTO KRAKEN_RECONCILED_RESULTS VALUES ('2026-09-08', 'open', 200)")
        conn.execute("INSERT INTO PERFORMANCE_ATTRIBUTION VALUES (1,'alpaca','AAPL','2026-09-08',100,-5)")
        conn.execute("INSERT INTO PERFORMANCE_ATTRIBUTION VALUES (2,'kraken','BTC','2026-09-08',100,500)")
        conn.execute("INSERT INTO PERFORMANCE_ATTRIBUTION VALUES (3,'alpaca','SPY','2026-09-08',NULL,300)")
    kraken, alpaca = build_portfolio_trends(db, now=NOW)['brokers']
    assert sum(x['wins'] for x in kraken['outcomes']) == 2
    assert sum(x['net_pnl'] for x in kraken['outcomes']) == 3
    assert kraken['outcomes'][0]['unknown'] == 1
    assert kraken['outcomes'][0]['breakeven'] == 1
    assert alpaca['outcomes'][0]['losses'] == 1
    assert alpaca['outcomes'][0]['net_pnl'] == -5
    assert alpaca['pnl_basis'] == 'recorded_before_unreconciled_fees'


def test_missing_tables_are_unavailable_not_fake_empty_history(tmp_path):
    for broker in build_portfolio_trends(tmp_path / 'missing.db', now=NOW)['brokers']:
        assert broker['value_status'] == broker['outcome_status'] == 'unavailable'


def test_cache_prevents_repeated_database_history_reads(db):
    _cache.clear()
    with patch('ai_trader.portfolio_trends.build_portfolio_trends', return_value={'brokers': []}) as build:
        assert portfolio_trends(db) == portfolio_trends(db)
        build.assert_called_once()


def test_postgres_style_mapping_rows_keep_all_aggregate_columns(db):
    from ai_trader.database import HybridRow
    original = connect
    def mapping_connect(path):
        conn = original(path)
        conn.row_factory = lambda cursor, row: HybridRow(zip([col[0] for col in cursor.description], row))
        return conn
    with closing(original(db)) as conn, conn:
        snapshot(conn, 1, '2026-09-09T10:00:00Z')
        conn.execute("INSERT INTO KRAKEN_RECONCILED_RESULTS VALUES ('2026-09-09', 'closed', 2)")
    with patch('ai_trader.portfolio_trends.connect', side_effect=mapping_connect):
        result = build_portfolio_trends(db, now=NOW)['brokers'][0]
    assert result['values'][0]['value'] == 102
    assert result['outcomes'][0]['wins'] == 1
    assert result['outcomes'][0]['losses'] == 0
    assert result['outcomes'][0]['net_pnl'] == 2


def test_daily_projection_is_bounded_even_with_many_snapshots(db):
    from datetime import timedelta
    with closing(connect(db)) as conn, conn:
        for index in range(100):
            day = (NOW - timedelta(days=index)).date().isoformat()
            for copy in range(3):
                snapshot(conn, index * 3 + copy, day + f'T1{copy}:00:00Z')
    result = build_portfolio_trends(db, now=NOW)
    assert len(result['brokers'][0]['values']) == 90
    assert len(json.dumps(result)) < 20000
