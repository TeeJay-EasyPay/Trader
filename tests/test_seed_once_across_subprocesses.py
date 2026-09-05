"""The seeding guards must survive a NEW PROCESS, not just a new call.

2026-09-06 Supabase egress finding. Every "seed once" guard in this codebase was an
in-memory set, and cli.py runs each worker job in its own subprocess (see run_jobs'
"own isolated subprocess, own timeout, own status" comment). A fresh process starts
with an empty set, so "once per process" meant "once per job": measured against
production, 88 RISK_POLICIES inserts in 240 seconds -- a full re-seed of all 23 rows
every minute, ~105,000 writes a day across four tables holding 70 unchanging rows.

Clearing the in-memory guard between calls is exactly what a new subprocess does, so
that is how these tests simulate one. They fail against the previous code.
"""

import shutil
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader import foundation
from ai_trader.database import connect, row_values
from ai_trader.foundation import initialize_foundation_schema
from ai_trader.sprint6 import seed_default_strategy_registry
from ai_trader.trading_intelligence import STRATEGIES


def _counting_connection(db_path: Path, counter: list[int]):
    """A connection that tallies INSERT statements without changing their behaviour.

    set_trace_callback rather than wrapping execute: sqlite3.Connection.execute is a
    read-only attribute and cannot be reassigned. The trace callback sees every statement
    the connection actually runs, which is a truer measure anyway.
    """

    conn = connect(db_path)

    def trace(statement: str) -> None:
        if str(statement).strip().upper().startswith("INSERT"):
            counter[0] += 1

    conn.set_trace_callback(trace)
    return conn


class SeedOncePerDatabaseTests(unittest.TestCase):
    def test_foundation_policies_are_not_reseeded_by_a_fresh_process(self):
        # mkdtemp rather than TemporaryDirectory: this test wraps the connection's execute in
        # a counting closure, and on Windows the resulting reference cycle can keep the file
        # handle alive past the block, which fails TemporaryDirectory's strict cleanup for a
        # reason that has nothing to do with what is being asserted.
        tmp = tempfile.mkdtemp()
        try:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)

            with closing(connect(db_path)) as conn:
                seeded = row_values(conn.execute("SELECT COUNT(*) FROM RISK_POLICIES").fetchone())[0]
            self.assertGreater(seeded, 0, "first pass must actually seed")

            # A new subprocess: same database on disk, empty in-memory guard.
            foundation._INITIALIZED_SCHEMA_KEYS.clear()
            counter = [0]
            real_connect = foundation.connect
            foundation.connect = lambda path, *a, **k: _counting_connection(path, counter)
            try:
                initialize_foundation_schema(db_path)
            finally:
                foundation.connect = real_connect

            self.assertEqual(
                counter[0], 0,
                "a fresh process must not re-insert policies that are already there",
            )

            with closing(connect(db_path)) as conn:
                after = row_values(conn.execute("SELECT COUNT(*) FROM RISK_POLICIES").fetchone())[0]
            self.assertEqual(seeded, after)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_newly_added_policy_is_still_seeded(self):
        """The guard counts rows rather than setting a "done" flag, so a default added in a
        later release is not stranded forever. Deleting one row must bring the seed back."""

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            with closing(connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        "DELETE FROM RISK_POLICIES WHERE policy_key = ("
                        "SELECT policy_key FROM RISK_POLICIES LIMIT 1)"
                    )
                short = row_values(conn.execute("SELECT COUNT(*) FROM RISK_POLICIES").fetchone())[0]

            foundation._INITIALIZED_SCHEMA_KEYS.clear()
            initialize_foundation_schema(db_path)

            with closing(connect(db_path)) as conn:
                restored = row_values(conn.execute("SELECT COUNT(*) FROM RISK_POLICIES").fetchone())[0]
            self.assertEqual(restored, short + 1, "a missing default must be re-seeded")

    def test_strategy_maturity_registry_is_not_reseeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_default_strategy_registry(db_path)
            with closing(connect(db_path)) as conn:
                first = row_values(conn.execute(
                    "SELECT COUNT(*) FROM STRATEGY_MATURITY_REGISTRY"
                ).fetchone())[0]
            self.assertEqual(first, 1 + len(STRATEGIES))

            seed_default_strategy_registry(db_path)
            with closing(connect(db_path)) as conn:
                second = row_values(conn.execute(
                    "SELECT COUNT(*) FROM STRATEGY_MATURITY_REGISTRY"
                ).fetchone())[0]
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
