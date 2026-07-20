from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import connect, selected_backend


MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS PRODUCTION_DATABASE_MIGRATIONS (
    migration_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    tables_examined INTEGER NOT NULL DEFAULT 0,
    tables_migrated INTEGER NOT NULL DEFAULT 0,
    rows_read INTEGER NOT NULL DEFAULT 0,
    rows_inserted INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL
);
"""


def migrate_sqlite_runtime_to_postgres(source_path: Path) -> dict[str, Any]:
    """Copy historical runtime rows into initialized Postgres tables.

    The migration is additive and retry-safe. Existing target rows win, so a
    retry cannot overwrite newer production truth. Tables absent from the
    production schema fail the run instead of being silently ignored.
    """

    if selected_backend() != "postgres":
        raise RuntimeError("The production cutover target must be Postgres.")
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite source database was not found: {source_path}")

    fingerprint = _source_fingerprint(source_path)
    migration_id = f"sqlite-cutover:{fingerprint}"
    started_at = _now()
    result: dict[str, Any] = {
        "migration_id": migration_id,
        "source_path": str(source_path),
        "source_fingerprint": fingerprint,
        "status": "started",
        "tables": [],
        "tables_examined": 0,
        "tables_migrated": 0,
        "rows_read": 0,
        "rows_inserted": 0,
        "missing_target_tables": [],
    }

    with closing(connect()) as target:
        with target:
            target.executescript(MIGRATION_SCHEMA)
            existing = target.execute(
                "SELECT status, result_json FROM PRODUCTION_DATABASE_MIGRATIONS WHERE migration_id = ?",
                (migration_id,),
            ).fetchone()
            if existing and str(existing[0]) == "completed":
                prior = json.loads(str(existing[1]))
                prior["status"] = "already_completed"
                return prior
            target.execute(
                """
                INSERT INTO PRODUCTION_DATABASE_MIGRATIONS (
                    migration_id, source_path, source_fingerprint, started_at,
                    status, result_json
                ) VALUES (?, ?, ?, ?, 'started', ?)
                ON CONFLICT(migration_id) DO UPDATE SET
                    started_at = excluded.started_at,
                    completed_at = NULL,
                    status = 'started',
                    result_json = excluded.result_json
                """,
                (migration_id, str(source_path), fingerprint, started_at, json.dumps(result, sort_keys=True)),
            )

    try:
        with sqlite3.connect(source_path) as source, closing(connect()) as target:
            source.row_factory = sqlite3.Row
            tables = [
                str(row[0])
                for row in source.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                    """
                ).fetchall()
            ]
            result["tables_examined"] = len(tables)
            with target:
                for table in tables:
                    table_result = _copy_table(source, target, table)
                    result["tables"].append(table_result)
                    result["rows_read"] += int(table_result["rows_read"])
                    result["rows_inserted"] += int(table_result["rows_inserted"])
                    if table_result["status"] == "migrated":
                        result["tables_migrated"] += 1
                    elif table_result["status"] == "missing_target_table":
                        result["missing_target_tables"].append(table)

        if result["missing_target_tables"]:
            raise RuntimeError(
                "Postgres schema initialization is incomplete for: "
                + ", ".join(result["missing_target_tables"])
            )
        result["status"] = "completed"
    except Exception as exc:
        result["status"] = "failed"
        result["failure_reason"] = str(exc)
        _finish_migration(result)
        raise

    _finish_migration(result)
    return result


def _copy_table(source: sqlite3.Connection, target, table: str) -> dict[str, Any]:
    identifier = _identifier(table)
    source_columns = [str(row[1]) for row in source.execute(f'PRAGMA table_info("{identifier}")').fetchall()]
    target_columns = [str(row["name"]) for row in target.execute(f"PRAGMA table_info({identifier})").fetchall()]
    if not target_columns:
        return {"table": table, "status": "missing_target_table", "rows_read": 0, "rows_inserted": 0}
    columns = [column for column in source_columns if column in set(target_columns)]
    if not columns:
        return {"table": table, "status": "no_common_columns", "rows_read": 0, "rows_inserted": 0}

    quoted_columns = ", ".join(f'"{_identifier(column)}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    statement = (
        f'INSERT INTO "{identifier}" ({quoted_columns}) VALUES ({placeholders}) '
        "ON CONFLICT DO NOTHING"
    )
    rows = source.execute(f'SELECT {quoted_columns} FROM "{identifier}"').fetchall()
    inserted = 0
    for row in rows:
        cursor = target.execute(statement, tuple(row[column] for column in columns))
        inserted += max(0, int(cursor.rowcount or 0))
    return {
        "table": table,
        "status": "migrated",
        "columns": columns,
        "rows_read": len(rows),
        "rows_inserted": inserted,
    }


def _finish_migration(result: dict[str, Any]) -> None:
    completed_at = _now()
    with closing(connect()) as target:
        with target:
            target.execute(
                """
                UPDATE PRODUCTION_DATABASE_MIGRATIONS
                SET completed_at = ?, status = ?, tables_examined = ?,
                    tables_migrated = ?, rows_read = ?, rows_inserted = ?,
                    result_json = ?
                WHERE migration_id = ?
                """,
                (
                    completed_at,
                    result["status"],
                    result["tables_examined"],
                    result["tables_migrated"],
                    result["rows_read"],
                    result["rows_inserted"],
                    json.dumps(result, sort_keys=True, default=str),
                    result["migration_id"],
                ),
            )


def _source_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Unsafe database identifier: {value!r}")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
