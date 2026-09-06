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


def requested_backend() -> str:
    """The backend the current environment asks for, before validating whether it can actually
    be used.

    This is the one place backend precedence is decided: an explicit `AI_TRADER_DATABASE_BACKEND`
    wins; otherwise a configured `DATABASE_URL`/`SUPABASE_DATABASE_URL` implies Postgres. Every
    other backend check in the codebase should be built on this function (or on
    `selected_backend()`/`uses_postgres()` below), not reimplement this precedence independently -
    a second implementation that used a different default when `AI_TRADER_DATABASE_BACKEND` was
    unset previously caused `always_on.py` to silently disagree with this module about whether
    Postgres was active.
    """
    configured = os.getenv("AI_TRADER_DATABASE_BACKEND", "").strip().lower()
    if configured:
        return "postgres" if configured in POSTGRES_BACKENDS else configured
    return "postgres" if database_url() else "sqlite"


def selected_backend() -> str:
    """The one authoritative, *validated* backend decision. Raises if a hosted runtime would
    silently fall back to SQLite, or if Postgres was requested but no connection URL is
    configured. This is what `connect()` uses to fail closed."""
    backend = requested_backend()
    if is_hosted_runtime() and backend != "postgres":
        raise RuntimeError(
            "Hosted AI Trader requires Postgres. SQLite is supported only for local development and isolated tests."
        )
    if backend == "postgres" and not database_url():
        raise RuntimeError("Postgres was selected but DATABASE_URL or SUPABASE_DATABASE_URL is not configured.")
    if backend not in {"sqlite", "postgres"}:
        raise RuntimeError(f"Unsupported AI Trader database backend: {backend}")
    return backend


def uses_postgres() -> bool:
    """Whether Postgres is both requested and actually usable (a connection URL is configured)
    right now.

    Unlike `selected_backend()`, this never raises - it exists for status/diagnostic reporting
    and internal SQL-dialect branching, where crashing on a misconfiguration would be worse than
    describing the (safe) SQLite fallback state. `connect()`/`selected_backend()` are what
    actually enforce the fail-closed rule for real database access.
    """
    return requested_backend() == "postgres" and bool(database_url())


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


# ---------------------------------------------------------------------------
# 2026-09-03, Founder-reported: Supabase egress running at 1-1.9 GB per DAY on a free plan.
#
# pg_stat_statements named the culprits, and they were not trading data at all:
#
#     611,816 calls   SELECT ... FROM information_schema.columns ...   700 seconds
#   5,731,823 calls   SELECT pg_get_serial_sequence(...) ...           596 seconds
#
# 6.3 million round trips asking the database to describe its own structure. The
# SQLite/Postgres compatibility layer re-derived a table's columns and its primary-key
# sequence on EVERY query and EVERY insert, rather than once. A schema does not change
# between two inserts a millisecond apart, so essentially all of that work was repeated
# for an answer it already had.
#
# Cached per (database, table). Two rules make the cache safe:
#
#   * ONLY SUCCESSFUL LOOKUPS ARE CACHED. A table that does not exist yet returns nothing,
#     and caching that "nothing" would make a table created later permanently invisible --
#     which matters here because schema creation and use are interleaved all over this
#     codebase (initialize_*_schema is called lazily from dozens of places).
#   * KEYED BY DATABASE, not just table name, so two different databases in one process
#     cannot read each other's schema. The test suite runs many temporary databases in a
#     single process, which is exactly how that would have gone unnoticed.
# ---------------------------------------------------------------------------
_TABLE_INFO_CACHE: dict[tuple[str, str], list[dict[str, Any]]] = {}
_SEQUENCE_NAME_CACHE: dict[tuple[str, str], str] = {}
# The auto-numbered primary-key column per (database, table), for RETURNING. Same
# positive-only rule as the two caches above: a table that does not exist yet must never
# be remembered as "has no key".
_PRIMARY_KEY_CACHE: dict[tuple[str, str], str] = {}


def row_values(row: Any) -> list[Any]:
    """Every value of one result row, in column order, whatever the row factory is.

    2026-09-06: rows reach callers in three different shapes depending on backend and caller
    -- a plain tuple from a bare sqlite3 connection, a sqlite3.Row where one has been set, and
    a dict from psycopg's dict_row, which is what the hosted Postgres path always uses. Code
    that reads a COUNT by name works on Postgres and raises TypeError on a bare SQLite tuple;
    code that reads row[0] does the reverse. A guard written either way therefore passes its
    own tests on one backend and silently fails closed on the other -- which is exactly how a
    seeding guard added to cut egress could have gone on re-seeding in production forever
    while every test agreed it worked.

    dict and psycopg's dict_row both preserve column order, so positional access after this
    is safe on all three shapes.
    """

    if row is None:
        return []
    if isinstance(row, dict):
        return list(row.values())
    keys = getattr(row, "keys", None)
    if callable(keys):
        try:
            return [row[key] for key in keys()]
        except Exception:  # noqa: BLE001 - fall through to sequence handling
            pass
    try:
        return list(row)
    except TypeError:
        return []


def clear_schema_cache() -> None:
    """Forget cached table structure. Call after creating or altering tables."""
    _TABLE_INFO_CACHE.clear()
    _SEQUENCE_NAME_CACHE.clear()
    _PRIMARY_KEY_CACHE.clear()


class PostgresConnection:
    def __init__(self, url: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - exercised by hosted startup validation
            raise RuntimeError("Postgres runtime requires the psycopg package.") from exc
        self._psycopg = psycopg
        connect_timeout = max(1, int(os.getenv("AI_TRADER_DB_CONNECT_TIMEOUT_SECONDS", "5")))
        statement_timeout = max(1000, int(os.getenv("AI_TRADER_DB_STATEMENT_TIMEOUT_MS", "8000")))
        self._conn = psycopg.connect(
            url,
            row_factory=dict_row,
            connect_timeout=connect_timeout,
            options=f"-c statement_timeout={statement_timeout}",
        )
        self._row_factory = None
        # Identity for the schema cache: two databases in one process must never share it.
        try:
            self._schema_key = str(self._conn.info.dbname or "") + "@" + str(self._conn.info.host or "")
        except Exception:  # noqa: BLE001 - identity is an optimisation, never a hard requirement
            self._schema_key = url

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, value):
        # psycopg is configured with dict rows; callers may continue assigning sqlite3.Row.
        self._row_factory = value

    # AT-ED-011.7: dozens of call sites across this codebase (founder_experience_service.py,
    # trading_intelligence.py, foundation.py, always_on.py, autonomous_activity.py, and more)
    # were written against sqlite3's DB-API and catch `sqlite3.OperationalError` specifically
    # to treat "this table/column doesn't exist yet" (a table not yet migrated, or a schema
    # not yet initialized) as "no data available" rather than a hard failure. Only
    # `IntegrityError` was translated below, so under Postgres those `except
    # sqlite3.OperationalError` blocks were dead code - psycopg raises its own
    # `UndefinedTable`/`UndefinedColumn` (a different exception hierarchy entirely), which
    # propagated uncaught instead of being gracefully treated as empty, silently breaking
    # whichever payload sections queried a not-yet-migrated table. Deliberately narrow: only
    # the two "missing structure" conditions are translated, not psycopg's broader
    # `OperationalError` (connection failures, timeouts) - those are real, transient failures
    # that must keep surfacing as errors, not be silently swallowed as "no data".
    def execute(self, sql: str, params: Iterable[Any] | Mapping[str, Any] | None = None):
        pragma = _pragma_table(sql)
        if pragma:
            return self._table_info(pragma)
        statement = _postgres_sql(sql)
        try:
            returning_column = self._returning_column(statement)
            if returning_column is not None:
                cursor = self._conn.execute(
                    f'{statement.rstrip().rstrip(";")} RETURNING "{returning_column}"',
                    params or (),
                )
                return PostgresCursor(cursor, lastrowid=_returned_id(cursor))
            cursor = self._conn.execute(statement, params or ())
            lastrowid = self._last_insert_id(statement)
            return PostgresCursor(cursor, lastrowid=lastrowid)
        except self._psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError(str(exc)) from exc
        except (self._psycopg.errors.UndefinedTable, self._psycopg.errors.UndefinedColumn) as exc:
            raise sqlite3.OperationalError(str(exc)) from exc

    def executemany(self, sql: str, params_seq: Iterable[Iterable[Any]]):
        statement = _postgres_sql(sql)
        try:
            cursor = self._conn.cursor()
            cursor.executemany(statement, params_seq)
            return PostgresCursor(cursor)
        except self._psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError(str(exc)) from exc
        except (self._psycopg.errors.UndefinedTable, self._psycopg.errors.UndefinedColumn) as exc:
            raise sqlite3.OperationalError(str(exc)) from exc

    def executescript(self, script: str):
        for statement in _split_sql_script(script):
            self.execute(statement)
        return MemoryCursor()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def set_autocommit(self, value: bool) -> None:
        # Narrow escape hatch for statements Postgres refuses to run inside a transaction
        # block (VACUUM being the motivating case -- see db_diagnostics.py). Every other call
        # site in this codebase relies on the default (autocommit off, explicit commit/rollback)
        # and should keep doing so; only flip this on a connection dedicated to one such
        # statement, and set it back to False before returning the connection to normal use.
        self._conn.autocommit = value

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
        cache_key = (self._schema_key, table.lower())
        cached = _TABLE_INFO_CACHE.get(cache_key)
        if cached is not None:
            return MemoryCursor(dict(row) for row in cached)
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
        described = [
            {
                "cid": index,
                "name": row["column_name"],
                "type": row["data_type"],
                "notnull": 0 if row["is_nullable"] == "YES" else 1,
                "dflt_value": row["column_default"],
                "pk": 1 if row["column_name"] in primary else 0,
            }
            for index, row in enumerate(rows)
        ]
        # Positive results only -- see the note above the cache.
        if described:
            _TABLE_INFO_CACHE[cache_key] = described
        return MemoryCursor(dict(row) for row in described)

    def _returning_column(self, statement: str) -> str | None:
        """The auto-numbered primary key to append RETURNING for, or None to use the old path.

        2026-09-06 Supabase egress finding. SQLite hands back a new row's id for free via
        lastrowid; Postgres has no equivalent, so this layer emulated it by asking TWO further
        questions after every single INSERT -- pg_get_serial_sequence ("which sequence?") then
        currval ("what value?"). Three round trips where Postgres offers one. Measured on
        production: 42,320 and 32,995 calls a day respectively, and 5.8 MILLION and 2.8 million
        cumulative. It ran unconditionally, including for the great majority of INSERTs whose
        caller never reads .lastrowid at all.

        RETURNING is not merely cheaper, it is more correct. currval answers "what did THIS
        SESSION last put in that sequence", which is a fact about the connection rather than
        about the row just written -- two inserts landing close together on one connection can
        hand back the wrong number. RETURNING is answered by the insert itself and cannot.

        DELIBERATELY DECLINED for ON CONFLICT statements, which is what INSERT OR IGNORE and
        INSERT OR REPLACE translate into. There, RETURNING yields no row when the conflict
        fires, so lastrowid would become None where today it returns whatever currval held.
        None is arguably the truer answer -- nothing was inserted -- but it is a behaviour
        change, and there are fourteen call sites reading .lastrowid. Those statements keep the
        old path exactly; this change is strictly an optimisation, not a semantics edit.
        """

        if not re.match(r"^\s*INSERT\s+INTO\b", statement, flags=re.IGNORECASE):
            return None
        if re.search(r"\bRETURNING\b", statement, flags=re.IGNORECASE):
            return None
        if re.search(r"\bON\s+CONFLICT\b", statement, flags=re.IGNORECASE):
            return None
        table_match = re.match(r"^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", statement, flags=re.IGNORECASE)
        if not table_match:
            return None
        table = table_match.group(1)
        cache_key = (getattr(self, "_schema_key", ""), table.lower())
        cached = _PRIMARY_KEY_CACHE.get(cache_key)
        if cached:
            return cached
        # Requiring a serial sequence keeps this exactly as selective as the currval path it
        # replaces: a table whose primary key is not auto-numbered returned None before and
        # still does, rather than RETURNING some unrelated text column.
        # A failure here must never abort the INSERT it was about to help with -- this whole
        # path is an optimisation. Falling back to the old currval route (or to no id at all)
        # is always safe; letting a lookup error escape would turn a working write into an
        # outage. This is also what keeps a stub or partly-built connection working.
        try:
            row = self._conn.execute(
                """
                SELECT a.attname AS pk_column
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = to_regclass(%s) AND i.indisprimary
                  AND pg_get_serial_sequence(%s, a.attname) IS NOT NULL
                ORDER BY a.attnum
                LIMIT 1
                """,
                (table, table.lower()),
            ).fetchone()
        except Exception:  # noqa: BLE001 - see above; never break the write
            return None
        column = row.get("pk_column") if isinstance(row, dict) else (row_values(row)[0] if row_values(row) else None)
        if not column:
            return None
        _PRIMARY_KEY_CACHE[cache_key] = str(column)
        return str(column)

    def _last_insert_id(self, statement: str) -> int | None:
        if not re.match(r"^\s*INSERT\s+INTO\b", statement, flags=re.IGNORECASE):
            return None
        # 2026-09-06: ON CONFLICT statements -- what INSERT OR IGNORE and INSERT OR REPLACE
        # translate into -- get no id at all, and pay for no lookup. They cannot use RETURNING
        # (it yields nothing when the conflict fires), so they were the only inserts still
        # paying the two-question currval tax: ~57,000 pg_get_serial_sequence and ~30,000
        # currval calls a day after the RETURNING change landed.
        #
        # Returning None is also the honest answer. After a conflict nothing was written, yet
        # currval would happily report whatever number that sequence last reached in this
        # session -- an id belonging to some other row entirely. Verified before changing it:
        # all fourteen call sites that read .lastrowid sit on plain INSERT INTO statements, so
        # none of them can observe this. Checked one by one, not by pattern -- six of them do
        # int(cursor.lastrowid) with no fallback and would raise on a None.
        if re.search(r"\bON\s+CONFLICT\b", statement, flags=re.IGNORECASE):
            return None
        table_match = re.match(r'^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)', statement, flags=re.IGNORECASE)
        if not table_match:
            return None
        table = table_match.group(1)
        cache_key = (self._schema_key, table.lower())
        sequence_name = _SEQUENCE_NAME_CACHE.get(cache_key)
        if sequence_name:
            row = self._conn.execute("SELECT currval(%s) AS id", (sequence_name,)).fetchone()
            return int(row["id"]) if row and row.get("id") is not None else None
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
        _SEQUENCE_NAME_CACHE[cache_key] = sequence_name
        row = self._conn.execute("SELECT currval(%s) AS id", (sequence_name,)).fetchone()
        return int(row["id"]) if row and row.get("id") is not None else None


def _returned_id(cursor) -> int | None:
    """The id from a RETURNING clause, matching sqlite3's lastrowid semantics.

    sqlite reports the LAST row inserted, so a multi-row INSERT takes the last returned value.
    Consuming the cursor here is safe: these are INSERTs whose RETURNING this layer added
    itself, so no caller is expecting to read rows off them.
    """

    try:
        rows = cursor.fetchall()
    except Exception:  # noqa: BLE001 - never let an id lookup break the write it followed
        return None
    if not rows:
        return None
    values = row_values(rows[-1])
    if not values or values[0] is None:
        return None
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return None


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
