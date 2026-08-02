import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.persistence.schema_once import ensure_schema_once, reset_for_tests, schema_key


class SchemaOnceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_for_tests()

    def tearDown(self) -> None:
        reset_for_tests()

    def test_init_fn_runs_exactly_once_for_the_same_namespace_and_db_path(self):
        calls = []
        db_path = Path("test.sqlite3")

        ensure_schema_once(db_path, "example_module", lambda: calls.append(1))
        ensure_schema_once(db_path, "example_module", lambda: calls.append(1))
        ensure_schema_once(db_path, "example_module", lambda: calls.append(1))

        self.assertEqual(len(calls), 1)

    def test_different_namespaces_each_get_their_own_first_call(self):
        calls = []
        db_path = Path("test.sqlite3")

        ensure_schema_once(db_path, "module_a", lambda: calls.append("a"))
        ensure_schema_once(db_path, "module_b", lambda: calls.append("b"))
        ensure_schema_once(db_path, "module_a", lambda: calls.append("a-again"))

        self.assertEqual(calls, ["a", "b"])

    def test_different_sqlite_db_paths_do_not_share_a_cache_entry(self):
        calls = []

        ensure_schema_once(Path("one.sqlite3"), "same_module", lambda: calls.append("one"))
        ensure_schema_once(Path("two.sqlite3"), "same_module", lambda: calls.append("two"))

        self.assertEqual(calls, ["one", "two"])

    def test_schema_key_is_stable_for_the_same_inputs(self):
        db_path = Path("test.sqlite3")
        self.assertEqual(schema_key(db_path, "example_module"), schema_key(db_path, "example_module"))

    def test_reset_for_tests_clears_the_cache(self):
        calls = []
        db_path = Path("test.sqlite3")
        ensure_schema_once(db_path, "example_module", lambda: calls.append(1))
        reset_for_tests()
        ensure_schema_once(db_path, "example_module", lambda: calls.append(1))

        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
