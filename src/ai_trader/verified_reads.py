"""Lossless conditional transfer for explicitly selected read-only histories.

The database still executes every query. Only unchanged row bodies stay on the
host; changed/deleted rows and ordering always come from the current query.
Never use a time-based cache for trading eligibility or account state.
"""
from .database import HybridRow, PostgresConnection, _postgres_sql


def rows(conn, sql, params=(), *, partition=None):
    if not isinstance(conn, PostgresConnection):
        return conn.execute(sql, params).fetchall()
    from .projection_transfer import read
    from .decision_storage import hydrate_rows
    result = read(conn._conn, _postgres_sql(sql), params, partition=partition)
    return [HybridRow(r) for r in hydrate_rows(result, conn._conn)]
