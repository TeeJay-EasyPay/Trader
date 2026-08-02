import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.persistence.query_executor import QueryExecutor


class QueryExecutorTests(unittest.TestCase):
    def _seeded_db(self, tmp: str) -> Path:
        db_path = Path(tmp) / "test.sqlite3"
        with closing(sqlite3.connect(db_path)) as conn:
            with conn:
                conn.execute("CREATE TABLE CRYPTO_MASTER (symbol TEXT NOT NULL)")
                conn.execute("INSERT INTO CRYPTO_MASTER (symbol) VALUES ('BTC')")
                conn.execute("INSERT INTO CRYPTO_MASTER (symbol) VALUES ('ETH')")
        return db_path

    def test_connect_returns_a_row_factory_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = QueryExecutor(self._seeded_db(tmp))
            with closing(executor.connect()) as conn:
                row = conn.execute("SELECT symbol FROM CRYPTO_MASTER WHERE symbol = 'BTC'").fetchone()
                self.assertEqual(row["symbol"], "BTC")

    def test_row_returns_none_when_nothing_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = QueryExecutor(self._seeded_db(tmp))
            self.assertIsNone(executor.row("SELECT symbol FROM CRYPTO_MASTER WHERE symbol = ?", ("DOGE",)))

    def test_row_returns_the_matching_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = QueryExecutor(self._seeded_db(tmp))
            row = executor.row("SELECT symbol FROM CRYPTO_MASTER WHERE symbol = ?", ("ETH",))
            self.assertEqual(row["symbol"], "ETH")

    def test_rows_returns_every_match_in_insertion_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = QueryExecutor(self._seeded_db(tmp))
            rows = executor.rows("SELECT symbol FROM CRYPTO_MASTER ORDER BY symbol")
            self.assertEqual([row["symbol"] for row in rows], ["BTC", "ETH"])

    def test_scalar_returns_the_first_column_of_the_first_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = QueryExecutor(self._seeded_db(tmp))
            self.assertEqual(executor.scalar("SELECT COUNT(*) FROM CRYPTO_MASTER"), 2)

    def test_scalar_returns_none_when_nothing_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = QueryExecutor(self._seeded_db(tmp))
            self.assertIsNone(executor.scalar("SELECT symbol FROM CRYPTO_MASTER WHERE symbol = ?", ("DOGE",)))

    def test_count_on_an_allowlisted_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = QueryExecutor(self._seeded_db(tmp))
            self.assertEqual(executor.count("CRYPTO_MASTER"), 2)

    def test_count_with_a_where_clause(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = QueryExecutor(self._seeded_db(tmp))
            self.assertEqual(executor.count("CRYPTO_MASTER", where="symbol = 'BTC'"), 1)

    def test_count_rejects_a_table_outside_the_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = QueryExecutor(self._seeded_db(tmp))
            with self.assertRaises(ValueError):
                executor.count("sqlite_master")


if __name__ == "__main__":
    unittest.main()
