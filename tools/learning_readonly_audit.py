"""Validate Learning projections against production without mutations or payload dumps."""
import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

import psycopg
from psycopg.rows import dict_row
from ai_trader.config import load_dotenv
from ai_trader import learning_screen as screen
from ai_trader.database import _postgres_sql

load_dotenv()


def read(_db, sql, params=()):
    with psycopg.connect(os.environ['AUDIT_DATABASE_URL'], connect_timeout=15,
                        options='-c default_transaction_read_only=on -c statement_timeout=20000',
                        row_factory=dict_row) as conn:
        return conn.execute(_postgres_sql(sql), params).fetchall()


with patch.object(screen, '_read', read), patch.object(screen, 'uses_postgres', return_value=True):
    bounds = screen.period_bounds('daily')
    report = screen._summary(None, bounds)
    print(json.dumps({'unavailable': report['unavailable'], 'summary': report['summary'],
                      'outcomes': report['outcomes']}, default=str))
    for kind in ('rejected', 'decisions', 'trades', 'reviews', 'strategies', 'tests', 'proposals'):
        try:
            detail = screen._details(None, kind, bounds, 'all', 0)
            print(json.dumps({'kind': kind, 'rows': len(detail['rows']), 'more': detail['has_more']}))
        except Exception as exc:
            print(json.dumps({'kind': kind, 'error': str(exc)}))
