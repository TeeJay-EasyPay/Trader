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


if __name__ == "__main__":
    unittest.main()
