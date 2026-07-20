from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any


POSTGRES_BACKENDS = {"postgres", "postgresql", "supabase"}


def is_hosted_runtime() -> bool:
    return bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID") or os.getenv("RENDER_INSTANCE_ID"))


def database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL")


def selected_backend() -> str:
    configured = os.getenv("AI_TRADER_DATABASE_BACKEND", "").strip().lower()
    if configured:
        backend = "postgres" if configured in POSTGRES_BACKENDS else configured
    else:
        backend = "postgres" if database_url() else "sqlite"
    if is_hosted_runtime() and backend != "postgres":
        raise RuntimeError(
            "Hosted AI Trader requires Postgres. SQLite is supported only for local development and isolated tests."
        )
    if backend == "postgres" and not database_url():
        raise RuntimeError("Postgres was selected but DATABASE_URL or SUPABASE_DATABASE_URL is not configured.")
    if backend not in {"sqlite", "postgres"}:
        raise RuntimeError(f"Unsupported AI Trader database backend: {backend}")
    return backend


def connect(db_path: str | Path | None = None, **sqlite_options: Any):
    """Open the only configured runtime database.

    Hosted processes fail closed unless Postgres is available. SQLite remains a
    deliberately local/test backend and keeps the existing DB-API contract.
    """

    if selected_backend() == "sqlite":
        path = Path(db_path or os.getenv("AI_TRADER_DB_PATH", "data/audit.sqlite3"))
        path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(path, **sqlite_options)
    if sqlite_options:
        unsupported = ", ".join(sorted(sqlite_options))
        raise TypeError(f"SQLite-only connection options are not supported by Postgres: {unsupported}")
    return PostgresConnection(database_url() or "")


class HybridRow(dict[str, Any]):
    """Mapping row that also preserves sqlite3.Row integer indexing."""

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class MemoryCursor:
    def __init__(self, rows: Iterable[Mapping[str, Any]] = (), *, lastrowid: int | None = None):
        self._rows = [HybridRow(row) for row in rows]
        self._offset = 0
        self.lastrowid = lastrowid
        self.rowcount = len(self._rows)

    def fetchone(self):
        if self._offset >= len(self._rows):
            return None
        row = self._rows[self._offset]
        self._offset += 1
        return row

    def fetchall(self):
        rows = self._rows[self._offset :]
        self._offset = len(self._rows)
        return rows

    def __iter__(self) -> Iterator[HybridRow]:
        return iter(self.fetchall())


class PostgresCursor:
    def __init__(self, cursor, *, lastrowid: int | None = None):
        self._cursor = cursor
        self.lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def fetchone(self):
        row = self._cursor.fetchone()
        return _hybrid(row)

    def fetchall(self):
        return [_hybrid(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        for row in self._cursor:
            yield _hybrid(row)


class PostgresConnection:
    def __init__(self, url: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - exercised by hosted startup validation
            raise RuntimeError("Postgres runtime requires the psycopg package.") from exc
        self._psycopg = psycopg
        self._conn = psycopg.connect(url, row_factory=dict_row)
        self._row_factory = None

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, value):
        # psycopg is configured with dict rows; callers may continue assigning sqlite3.Row.
        self._row_factory = value

    def execute(self, sql: str, params: Iterable[Any] | Mapping[str, Any] | None = None):
        pragma = _pragma_table(sql)
        if pragma:
            return self._table_info(pragma)
        statement = _postgres_sql(sql)
        try:
            cursor = self._conn.execute(statement, params or ())
            lastrowid = self._last_insert_id(statement)
            return PostgresCursor(cursor, lastrowid=lastrowid)
        except self._psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError(str(exc)) from exc

    def executemany(self, sql: str, params_seq: Iterable[Iterable[Any]]):
        statement = _postgres_sql(sql)
        try:
            cursor = self._conn.cursor()
            cursor.executemany(statement, params_seq)
            return PostgresCursor(cursor)
        except self._psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError(str(exc)) from exc

    def executescript(self, script: str):
        for statement in _split_sql_script(script):
            self.execute(statement)
        return MemoryCursor()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def cursor(self):
        return PostgresCursor(self._conn.cursor())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def _table_info(self, table: str) -> MemoryCursor:
        rows = self._conn.execute(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND lower(table_name) = lower(%s)
            ORDER BY ordinal_position
            """,
            (table,),
        ).fetchall()
        primary = {
            row["column_name"]
            for row in self._conn.execute(
                """
                SELECT a.attname AS column_name
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = to_regclass(%s) AND i.indisprimary
                """,
                (table.lower(),),
            ).fetchall()
        }
        return MemoryCursor(
            {
                "cid": index,
                "name": row["column_name"],
                "type": row["data_type"],
                "notnull": 0 if row["is_nullable"] == "YES" else 1,
                "dflt_value": row["column_default"],
                "pk": 1 if row["column_name"] in primary else 0,
            }
            for index, row in enumerate(rows)
        )

    def _last_insert_id(self, statement: str) -> int | None:
        if not re.match(r"^\s*INSERT\s+INTO\b", statement, flags=re.IGNORECASE):
            return None
        table_match = re.match(r'^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)', statement, flags=re.IGNORECASE)
        if not table_match:
            return None
        table = table_match.group(1)
        sequence_row = self._conn.execute(
            """
            SELECT pg_get_serial_sequence(%s, a.attname) AS sequence_name
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = to_regclass(%s) AND i.indisprimary
            ORDER BY a.attnum
            LIMIT 1
            """,
            (table, table.lower()),
        ).fetchone()
        sequence_name = sequence_row.get("sequence_name") if sequence_row else None
        if not sequence_name:
            return None
        row = self._conn.execute("SELECT currval(%s) AS id", (sequence_name,)).fetchone()
        return int(row["id"]) if row and row.get("id") is not None else None


def _hybrid(row):
    if row is None or isinstance(row, HybridRow):
        return row
    if isinstance(row, Mapping):
        return HybridRow(row)
    return row


def _pragma_table(sql: str) -> str | None:
    match = re.match(r"^\s*PRAGMA\s+table_info\s*\(\s*([A-Za-z0-9_]+)\s*\)\s*;?\s*$", sql, re.IGNORECASE)
    return match.group(1) if match else None


def _postgres_sql(sql: str) -> str:
    statement = sql.strip().rstrip(";")
    statement = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "BIGSERIAL PRIMARY KEY",
        statement,
        flags=re.IGNORECASE,
    )
    statement = re.sub(r"\bAUTOINCREMENT\b", "", statement, flags=re.IGNORECASE)
    if re.match(r"^INSERT\s+OR\s+REPLACE\b", statement, flags=re.IGNORECASE):
        raise RuntimeError("INSERT OR REPLACE is not permitted in production; use an explicit ON CONFLICT upsert.")
    if re.match(r"^INSERT\s+OR\s+IGNORE\b", statement, flags=re.IGNORECASE):
        statement = re.sub(r"^INSERT\s+OR\s+IGNORE", "INSERT", statement, count=1, flags=re.IGNORECASE)
        statement += " ON CONFLICT DO NOTHING"
    return _replace_qmark_parameters(statement)


def _replace_qmark_parameters(sql: str) -> str:
    output: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote:
            output.append(char)
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    output.append(sql[index + 1])
                    index += 1
                else:
                    quote = None
        elif char in {"'", '"'}:
            quote = char
            output.append(char)
        elif char == "?":
            output.append("%s")
        else:
            output.append(char)
        index += 1
    return "".join(output)


def _split_sql_script(script: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in script:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
            current.append(char)
        elif char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements
