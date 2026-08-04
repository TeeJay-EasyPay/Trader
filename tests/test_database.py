import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader import database


_ENV_KEYS = (
    "AI_TRADER_DATABASE_BACKEND",
    "DATABASE_URL",
    "SUPABASE_DATABASE_URL",
    "RENDER",
    "RENDER_SERVICE_ID",
    "RENDER_INSTANCE_ID",
)


class BackendSelectionTests(unittest.TestCase):
    """database.py:selected_backend() is the one authoritative backend decision (see
    architectural clarification and hardening covered in governance/IMPLEMENTATION_LOG.md's
    2026-07-29 backend-selection hardening entry). Every scenario here previously risked being
    computed differently by always_on.py's now-removed independent _use_postgres()/_database_url()
    implementation."""

    def setUp(self):
        import os

        self._previous = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        import os

        for key, value in self._previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_explicit_postgres_backend_with_url_is_selected(self):
        import os

        os.environ["AI_TRADER_DATABASE_BACKEND"] = "postgres"
        os.environ["DATABASE_URL"] = "postgresql://example.invalid/db"

        self.assertEqual(database.requested_backend(), "postgres")
        self.assertEqual(database.selected_backend(), "postgres")
        self.assertTrue(database.uses_postgres())

    def test_postgres_is_selected_from_database_url_alone(self):
        # The exact bug being fixed: AI_TRADER_DATABASE_BACKEND is never set, only DATABASE_URL.
        # Before this hardening, always_on.py's independent backend check defaulted to "sqlite"
        # in this scenario and disagreed with database.py's selected_backend().
        import os

        os.environ["DATABASE_URL"] = "postgresql://example.invalid/db"

        self.assertEqual(database.requested_backend(), "postgres")
        self.assertEqual(database.selected_backend(), "postgres")
        self.assertTrue(database.uses_postgres())

    def test_postgres_is_selected_from_supabase_database_url_alone(self):
        import os

        os.environ["SUPABASE_DATABASE_URL"] = "postgresql://example.invalid/db"

        self.assertEqual(database.requested_backend(), "postgres")
        self.assertTrue(database.uses_postgres())

    def test_local_sqlite_with_nothing_configured(self):
        self.assertEqual(database.requested_backend(), "sqlite")
        self.assertEqual(database.selected_backend(), "sqlite")
        self.assertFalse(database.uses_postgres())

    def test_hosted_runtime_refuses_sqlite(self):
        import os

        os.environ["RENDER"] = "true"

        with self.assertRaises(RuntimeError) as ctx:
            database.selected_backend()
        self.assertIn("Hosted AI Trader requires Postgres", str(ctx.exception))

    def test_hosted_runtime_with_postgres_configured_succeeds(self):
        import os

        os.environ["RENDER"] = "true"
        os.environ["AI_TRADER_DATABASE_BACKEND"] = "postgres"
        os.environ["DATABASE_URL"] = "postgresql://example.invalid/db"

        self.assertEqual(database.selected_backend(), "postgres")

    def test_postgres_requested_without_url_raises_even_when_not_hosted(self):
        import os

        os.environ["AI_TRADER_DATABASE_BACKEND"] = "postgres"

        with self.assertRaises(RuntimeError) as ctx:
            database.selected_backend()
        self.assertIn("DATABASE_URL or SUPABASE_DATABASE_URL is not configured", str(ctx.exception))
        # uses_postgres() never raises - it is the non-raising diagnostic counterpart.
        self.assertFalse(database.uses_postgres())

    def test_postgresql_and_supabase_aliases_normalize_to_postgres(self):
        import os

        for alias in ("postgresql", "supabase"):
            with self.subTest(alias=alias):
                os.environ["AI_TRADER_DATABASE_BACKEND"] = alias
                os.environ["DATABASE_URL"] = "postgresql://example.invalid/db"
                self.assertEqual(database.requested_backend(), "postgres")
                self.assertEqual(database.selected_backend(), "postgres")


class PostgresCompatibilityExceptionTranslationTests(unittest.TestCase):
    """AT-ED-011.7: dozens of call sites across this codebase (founder_experience_service.py,
    trading_intelligence.py, foundation.py, always_on.py, autonomous_activity.py, and more)
    catch sqlite3.OperationalError specifically to treat "this table/column doesn't exist yet"
    as no-data-available rather than a hard failure - a pattern that only ever worked under a
    real sqlite3 connection. PostgresConnection.execute() must translate the two psycopg
    conditions that mean the same thing (UndefinedTable/UndefinedColumn) into
    sqlite3.OperationalError so every one of those existing except blocks keeps working
    unchanged under Postgres, without touching each call site individually. Constructs
    PostgresConnection via __new__ (bypassing __init__, which opens a real network connection)
    and substitutes a fake underlying connection so no real Postgres server is required.
    """

    def _connection_raising(self, exc):
        import psycopg

        from ai_trader.database import PostgresConnection

        class _FakeConn:
            def execute(self, *_args, **_kwargs):
                raise exc

        conn = PostgresConnection.__new__(PostgresConnection)
        conn._psycopg = psycopg
        conn._conn = _FakeConn()
        conn._row_factory = None
        return conn

    def test_undefined_table_becomes_sqlite_operational_error(self):
        import sqlite3

        import psycopg.errors

        conn = self._connection_raising(psycopg.errors.UndefinedTable('relation "strategy_lab_runs" does not exist'))
        with self.assertRaises(sqlite3.OperationalError) as ctx:
            conn.execute("SELECT * FROM STRATEGY_LAB_RUNS")
        # The real Postgres message is preserved (this is what engineers need in logs) - only
        # the exception *type* changes, to match what the existing call sites already catch.
        self.assertIn("strategy_lab_runs", str(ctx.exception))

    def test_undefined_column_becomes_sqlite_operational_error(self):
        import sqlite3

        import psycopg.errors

        conn = self._connection_raising(psycopg.errors.UndefinedColumn('column "foo" does not exist'))
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("SELECT foo FROM bar")

    def test_integrity_error_translation_is_unchanged(self):
        # Regression guard: the new except clause must not shadow or alter the existing,
        # already-relied-upon IntegrityError -> sqlite3.IntegrityError translation.
        import sqlite3

        import psycopg

        conn = self._connection_raising(psycopg.IntegrityError("duplicate key value violates unique constraint"))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO x VALUES (1)")

    def test_unrelated_postgres_errors_are_not_translated(self):
        # A genuine connection/timeout failure must keep propagating as a real error, not be
        # silently reinterpreted as "table doesn't exist, treat as empty" - only the two
        # missing-structure conditions above are in scope for this translation.
        import psycopg

        conn = self._connection_raising(psycopg.OperationalError("server closed the connection unexpectedly"))
        with self.assertRaises(psycopg.OperationalError):
            conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
