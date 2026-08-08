import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.config import Settings
from ai_trader.db_diagnostics import database_size_report, vacuum_table
from ai_trader.models import AutoTradeConfig, GuardrailConfig


def _settings(tmp: str) -> Settings:
    root = Path(tmp)
    return Settings(
        alpaca_api_key=None,
        alpaca_secret_key=None,
        alpaca_paper_base_url="https://paper-api.alpaca.markets",
        alpaca_data_base_url="https://data.alpaca.markets",
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
        db_path=root / "audit.sqlite3",
        output_dir=root,
        trading_log_path=root / "TRADING_LOG.md",
        guardrails=GuardrailConfig(),
        auto_trade=AutoTradeConfig(),
    )


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows if isinstance(rows, list) else [rows]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Records every executed statement/params; returns canned results keyed by a
    substring match against the SQL, so tests stay readable without depending on
    the exact query text."""

    def __init__(self, responses):
        self._responses = responses
        self.executed: list[tuple[str, tuple]] = []
        self.autocommit_calls: list[bool] = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        for marker, rows in self._responses.items():
            if marker in sql:
                return _FakeCursor(rows)
        raise AssertionError(f"Unexpected SQL in test fake: {sql}")

    def set_autocommit(self, value):
        self.autocommit_calls.append(value)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DatabaseSizeReportTests(unittest.TestCase):
    def test_sqlite_backend_is_an_honest_not_applicable(self):
        with patch("ai_trader.db_diagnostics.uses_postgres", return_value=False):
            report = database_size_report(Path("unused.sqlite3"))
        self.assertEqual(report["backend"], "sqlite")

    def test_postgres_backend_reports_real_shaped_sizes(self):
        one_mb = 1024 * 1024
        fake = _FakeConn(
            {
                "pg_database_size": {"bytes": 500 * one_mb},
                "pg_total_relation_size(c.oid) DESC": [
                    {
                        "table_name": "PRODUCTION_FOUNDER_EVIDENCE_SNAPSHOTS",
                        "total_bytes": 200 * one_mb,
                        "table_bytes": 20 * one_mb,
                        "index_bytes": 5 * one_mb,
                        "toast_bytes": 175 * one_mb,
                        "live_rows": 100,
                        "dead_rows": 40,
                    }
                ],
            }
        )
        with patch("ai_trader.db_diagnostics.uses_postgres", return_value=True), patch(
            "ai_trader.db_diagnostics.connect", return_value=fake
        ):
            report = database_size_report(Path("unused"), top_n=5)
        self.assertEqual(report["backend"], "postgres")
        self.assertEqual(report["database_total_mb"], 500.0)
        self.assertEqual(len(report["largest_tables"]), 1)
        largest = report["largest_tables"][0]
        self.assertEqual(largest["table"], "PRODUCTION_FOUNDER_EVIDENCE_SNAPSHOTS")
        self.assertEqual(largest["total_mb"], 200.0)
        self.assertEqual(largest["toast_mb"], 175.0)
        self.assertEqual(largest["dead_rows"], 40)
        # top_n reached the query as a real bound, not silently dropped.
        self.assertIn(5, fake.executed[1][1])


class VacuumTableTests(unittest.TestCase):
    def test_sqlite_backend_is_a_documented_no_op(self):
        with patch("ai_trader.db_diagnostics.uses_postgres", return_value=False):
            result = vacuum_table(Path("unused.sqlite3"), "SOME_TABLE")
        self.assertEqual(result["backend"], "sqlite")

    def test_refuses_a_table_name_not_present_in_the_real_catalog(self):
        fake = _FakeConn({"pg_class c JOIN": []})
        with patch("ai_trader.db_diagnostics.uses_postgres", return_value=True), patch(
            "ai_trader.db_diagnostics.connect", return_value=fake
        ):
            result = vacuum_table(Path("unused"), "NOT_A_REAL_TABLE; DROP TABLE foo")
        self.assertEqual(result["status"], "refused")
        # Never reached VACUUM for a table that failed catalog validation.
        self.assertFalse(any("VACUUM" in sql for sql, _ in fake.executed))

    def test_vacuum_full_toggles_autocommit_on_then_off_and_reports_reclaimed_space(self):
        one_mb = 1024 * 1024
        sizes = iter([{"bytes": 300 * one_mb}, {"bytes": 40 * one_mb}])
        fake = _FakeConn({"pg_class c JOIN": [{"?column?": 1}]})

        def execute(sql, params=()):
            fake.executed.append((sql, params))
            if "pg_class c JOIN" in sql:
                return _FakeCursor([{"?column?": 1}])
            if "pg_total_relation_size(?::regclass)" in sql:
                return _FakeCursor(next(sizes))
            if "VACUUM" in sql:
                return _FakeCursor([])
            raise AssertionError(f"Unexpected SQL: {sql}")

        fake.execute = execute
        with patch("ai_trader.db_diagnostics.uses_postgres", return_value=True), patch(
            "ai_trader.db_diagnostics.connect", return_value=fake
        ):
            result = vacuum_table(Path("unused"), "PRODUCTION_FOUNDER_EVIDENCE_SNAPSHOTS", full=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["before_mb"], 300.0)
        self.assertEqual(result["after_mb"], 40.0)
        self.assertEqual(result["reclaimed_mb"], 260.0)
        self.assertEqual(fake.autocommit_calls, [True, False])
        vacuum_statements = [sql for sql, _ in fake.executed if "VACUUM" in sql]
        self.assertEqual(len(vacuum_statements), 1)
        self.assertIn("FULL", vacuum_statements[0])
        self.assertIn('"PRODUCTION_FOUNDER_EVIDENCE_SNAPSHOTS"', vacuum_statements[0])


class ApiRoutingTests(unittest.TestCase):
    def test_get_database_diagnostics_route_is_wired(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(_settings(tmp))
            status, payload = service.get("/database-diagnostics", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["backend"], "sqlite")

    def test_post_vacuum_route_refuses_without_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(_settings(tmp))
            status, payload = service.post("/database-diagnostics/vacuum", {"table_name": "SOME_TABLE"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "refused")

    def test_post_vacuum_route_proceeds_once_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(_settings(tmp))
            status, payload = service.post(
                "/database-diagnostics/vacuum", {"table_name": "SOME_TABLE", "confirmed_by_founder": True}
            )
        self.assertEqual(status, 200)
        # sqlite backend -- honest no-op, but proves the confirmation gate let the call through.
        self.assertEqual(payload["backend"], "sqlite")


if __name__ == "__main__":
    unittest.main()
