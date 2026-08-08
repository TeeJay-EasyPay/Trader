"""Real Postgres database-size diagnostics and reclaim tooling.

Added 2026-08-08 during a Supabase quota emergency (egress and database size
both near their plan limits). There is no Supabase Management API token or
direct Postgres connection string available outside the hosted runtime, so
the only way to get real numbers is to ask the already-connected production
process -- this module is that: a thin, read-mostly wrapper around Postgres's
own size-reporting functions, exposed via an admin API route in api/__init__.py.

Deliberately Postgres-only: sqlite has no equivalent concept (a local/test
sqlite file's size is trivially checkable with Path.stat() and is never the
thing under quota pressure), so every function here degrades to an honest
"not applicable" result on sqlite rather than raising.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from .database import connect, uses_postgres


def database_size_report(db_path: Path, *, top_n: int = 15) -> dict[str, Any]:
    """Real total database size plus the largest tables (including TOAST and
    index storage, which is what actually counts against a Postgres/Supabase
    disk-size quota -- pg_relation_size alone undercounts a table with large
    JSON columns, exactly the shape this codebase's payload_json/*_json
    columns have)."""
    if not uses_postgres():
        return {"backend": "sqlite", "note": "Database size quotas apply to the hosted Postgres backend only."}
    with closing(connect(db_path)) as conn:
        total_row = conn.execute("SELECT pg_database_size(current_database()) AS bytes").fetchone()
        total_bytes = int(total_row["bytes"])
        table_rows = conn.execute(
            """
            SELECT
                c.relname AS table_name,
                pg_total_relation_size(c.oid) AS total_bytes,
                pg_relation_size(c.oid) AS table_bytes,
                pg_indexes_size(c.oid) AS index_bytes,
                pg_total_relation_size(c.oid) - pg_relation_size(c.oid) - pg_indexes_size(c.oid) AS toast_bytes,
                n_live_tup AS live_rows,
                n_dead_tup AS dead_rows
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY pg_total_relation_size(c.oid) DESC
            LIMIT ?
            """,
            (top_n,),
        ).fetchall()
    return {
        "backend": "postgres",
        "database_total_bytes": total_bytes,
        "database_total_mb": round(total_bytes / (1024 * 1024), 2),
        "largest_tables": [
            {
                "table": row["table_name"],
                "total_mb": round(int(row["total_bytes"]) / (1024 * 1024), 2),
                "table_mb": round(int(row["table_bytes"]) / (1024 * 1024), 2),
                "index_mb": round(int(row["index_bytes"]) / (1024 * 1024), 2),
                "toast_mb": round(int(row["toast_bytes"]) / (1024 * 1024), 2),
                "live_rows": row["live_rows"],
                "dead_rows": row["dead_rows"],
            }
            for row in table_rows
        ],
    }


def vacuum_table(db_path: Path, table_name: str, *, full: bool = False) -> dict[str, Any]:
    """Run VACUUM (optionally VACUUM FULL) on one explicitly-named table.

    Deliberately single-table and explicitly-named (never "vacuum everything"
    in one call) so a caller can reclaim space from the specific tables the
    diagnostics above identify as bloated, without taking an exclusive lock
    on the whole database at once. VACUUM FULL requires an ACCESS EXCLUSIVE
    lock on the table for its duration -- real writes/reads against that
    specific table will block until it completes. table_name is validated
    against the real pg_class catalog before use (never interpolated from
    unchecked input) since VACUUM does not support parameterized identifiers.
    """
    if not uses_postgres():
        return {"backend": "sqlite", "note": "VACUUM is a no-op on sqlite; use VACUUM manually if ever needed locally."}
    with closing(connect(db_path)) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname = ?",
            (table_name,),
        ).fetchone()
        if not exists:
            return {"status": "refused", "reason": f"{table_name!r} is not a real table in this database."}
        before = conn.execute("SELECT pg_total_relation_size(?::regclass) AS bytes", (table_name,)).fetchone()
        before_bytes = int(before["bytes"])
        verb = "VACUUM (FULL)" if full else "VACUUM"
        # VACUUM refuses to run inside a transaction block, which every connection from
        # connect() is implicitly in (autocommit is off by default so ordinary call sites get
        # explicit commit/rollback control). set_autocommit is the narrow escape hatch added
        # to PostgresConnection specifically for this.
        conn.set_autocommit(True)
        try:
            conn.execute(f'{verb} "{table_name}"')
        finally:
            conn.set_autocommit(False)
        after = conn.execute("SELECT pg_total_relation_size(?::regclass) AS bytes", (table_name,)).fetchone()
        after_bytes = int(after["bytes"])
    return {
        "status": "completed",
        "table": table_name,
        "full": full,
        "before_mb": round(before_bytes / (1024 * 1024), 2),
        "after_mb": round(after_bytes / (1024 * 1024), 2),
        "reclaimed_mb": round((before_bytes - after_bytes) / (1024 * 1024), 2),
    }
