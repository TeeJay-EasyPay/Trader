"""Reads that fetch far more than anyone uses.

2026-09-07, Founder-directed: "before I commit to 25 a month we need to ensure we are running as
lean and efficient as possible... currently we are burning money and not making any."

Measured against production over four hours, then RE-measured over a six-hour window containing
no deploys -- because the first measurement was inflated roughly threefold by my own restarts,
and acting on it would have meant slowing jobs that were already running hourly.

What survived that second check is what is tested here: three reads that were wasteful
regardless of how often anything ran.
"""

import sys
import unittest
from contextlib import closing
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


class WorkerHeartbeatReadTests(unittest.TestCase):
    """393 rows came back on every call. Sixteen workers had a heartbeat in the last hour, and
    classify_worker_presence can only ever mark the FIRST row Live -- the rest were shipped
    across the wire in order to be labelled Historical.
    """

    def test_the_read_is_bounded(self):
        from ai_trader import always_on

        source = (REPO / "src" / "ai_trader" / "always_on.py").read_text(encoding="utf-8")
        block = source[source.index("def list_worker_heartbeats"):]
        block = block[: block.index("\ndef ", 1)]
        self.assertIn("LIMIT", block.upper())
        self.assertGreater(always_on.WORKER_HEARTBEAT_HISTORY_LIMIT, 1)
        self.assertLessEqual(always_on.WORKER_HEARTBEAT_HISTORY_LIMIT, 50)

    def test_it_still_returns_the_newest_first(self):
        """Only the freshest row can be Live, so the ordering is what makes a limit safe. A
        limit on an unordered read would be a coin toss over which worker looks alive."""
        source = (REPO / "src" / "ai_trader" / "always_on.py").read_text(encoding="utf-8")
        block = source[source.index("def list_worker_heartbeats"):]
        self.assertIn("ORDER BY last_heartbeat_at DESC", block[:900])

    def test_a_caller_cannot_ask_for_an_unbounded_read(self):
        import tempfile

        from ai_trader.always_on import initialize_always_on_schema, list_worker_heartbeats

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            initialize_always_on_schema(db)
            self.assertEqual(list_worker_heartbeats(db, limit=10000), [])


class EvidenceRescanTests(unittest.TestCase):
    """A finished backfill that never noticed it had finished: 500 rows re-read on every
    broker-poll cycle -- 13,629 rows across 21 calls in four hours -- finding nothing.
    """

    def test_only_rows_that_could_need_fixing_are_read(self):
        source = (REPO / "src" / "ai_trader" / "production_evidence.py").read_text(encoding="utf-8")
        start = source.index("iso_marker = ")
        self.assertIn("NOT LIKE", source[start : start + 1200])

    def test_the_filter_matches_the_normalisers_own_rule(self):
        """It rewrites a value only when the whole string parses as a bare number. A real
        ISO-8601 timestamp always contains a dash; a raw Kraken epoch never does. If those two
        facts ever diverge, the filter starts skipping rows that genuinely need repair."""
        from ai_trader.production_evidence import _normalize_broker_timestamp

        epoch = "1787154660.049352"
        self.assertNotIn("-", epoch)
        self.assertNotEqual(_normalize_broker_timestamp(epoch), epoch, "an epoch must change")

        already_iso = "2026-09-07T12:00:00+00:00"
        self.assertIn("-", already_iso)
        self.assertEqual(
            _normalize_broker_timestamp(already_iso),
            already_iso,
            "anything containing a dash must pass through untouched",
        )

    def test_the_like_pattern_is_a_bound_value_not_a_literal(self):
        """A literal percent sign in SQL raises on Postgres: psycopg reads it as a placeholder
        even with no parameters bound. That exact trap silently emptied the category lookup in
        operational.py on 2026-09-04."""
        source = (REPO / "src" / "ai_trader" / "production_evidence.py").read_text(encoding="utf-8")
        start = source.index("iso_marker = ")
        block = source[start : start + 1400]
        self.assertIn("(iso_marker, iso_marker, iso_marker)", block)
        sql = block[block.index("SELECT trade_evidence_id") : block.index("ORDER BY")]
        self.assertNotIn("%", sql, "no percent sign may appear in the SQL itself")

    def test_the_python_check_is_still_the_decider(self):
        """The SQL only narrows the candidates. A row that slips through the filter must still
        be compared properly before anything is written."""
        source = (REPO / "src" / "ai_trader" / "production_evidence.py").read_text(encoding="utf-8")
        start = source.index("iso_marker = ")
        block = source[start : start + 2600]
        self.assertIn("new_observed_at == row.get(", block)
        self.assertIn("continue", block)


class StartupReplaySkipTests(unittest.TestCase):
    """"if you deploy why does that cause so much egress?"

    Because a deploy restarts the worker, and every start re-read up to 1,000 historical Kraken
    trades WITH their full payloads and replayed all of them. Roughly 1 MB per restart; six
    deploys in four hours made it about 17% of that window's database egress.
    """

    def _fresh_db(self, tmp: str, last_replay_at: str) -> Path:
        from ai_trader.database import connect
        from ai_trader.kraken_reconciliation import _ensure_schema

        db = Path(tmp) / "audit.sqlite3"
        _ensure_schema(db)
        with closing(connect(db)) as conn:
            with conn:
                conn.execute(
                    "UPDATE KRAKEN_RECONCILIATION_CONTROL SET last_replay_at = ? WHERE id = 1",
                    (last_replay_at,),
                )
        return db

    def test_a_recent_replay_is_not_repeated(self):
        import tempfile

        from ai_trader.kraken_reconciliation import replay_persisted_kraken_evidence
        from ai_trader.models import utc_now_iso

        with tempfile.TemporaryDirectory() as tmp:
            db = self._fresh_db(tmp, utc_now_iso())
            result = replay_persisted_kraken_evidence(db, skip_if_replayed_within_seconds=1800)
            self.assertEqual(result["status"], "skipped_recently_replayed")
            self.assertEqual(result["persisted_rows_read"], 0)

    def test_an_old_replay_still_runs(self):
        """A restart after real downtime must catch up. The skip is about deploy storms, not
        about avoiding the work."""
        import tempfile

        from ai_trader.kraken_reconciliation import replay_persisted_kraken_evidence

        with tempfile.TemporaryDirectory() as tmp:
            db = self._fresh_db(tmp, "2020-01-01T00:00:00+00:00")
            result = replay_persisted_kraken_evidence(db, skip_if_replayed_within_seconds=1800)
            self.assertNotEqual(result["status"], "skipped_recently_replayed")

    def test_skipping_is_off_unless_asked_for(self):
        """Default behaviour is unchanged, so nothing that calls this today quietly stops
        catching up."""
        import tempfile

        from ai_trader.kraken_reconciliation import replay_persisted_kraken_evidence
        from ai_trader.models import utc_now_iso

        with tempfile.TemporaryDirectory() as tmp:
            db = self._fresh_db(tmp, utc_now_iso())
            result = replay_persisted_kraken_evidence(db)
            self.assertNotEqual(result["status"], "skipped_recently_replayed")

    def test_the_manual_endpoint_never_skips(self):
        """The Founder presses that button precisely to force a full replay. A skip he did not
        ask for would make it lie."""
        api = (REPO / "src" / "ai_trader" / "api" / "__init__.py").read_text(encoding="utf-8")
        block = api[api.index('if path == "/kraken-reconciliation/replay":') :]
        self.assertNotIn("skip_if_replayed_within_seconds", block[:400])

    def test_the_startup_path_does_skip(self):
        cli = (REPO / "src" / "ai_trader" / "cli.py").read_text(encoding="utf-8")
        block = cli[cli.index('if job_name == "kraken-startup-reconciliation":') :]
        self.assertIn("skip_if_replayed_within_seconds", block[:900])

    def test_an_unreadable_timestamp_means_do_the_work(self):
        """"Cannot tell" must never be the reason a catch-up is skipped."""
        from ai_trader.kraken_reconciliation import _seconds_since

        for bad in ("", None, "not a date", "  "):
            self.assertIsNone(_seconds_since(bad))

    def test_the_skip_window_is_configurable_and_sane(self):
        from ai_trader.config import Settings

        field = Settings.__dataclass_fields__["kraken_startup_replay_skip_seconds"]
        self.assertGreater(field.default, 0)
        self.assertLessEqual(
            field.default, 3600, "longer than an hour and a real gap goes unnoticed"
        )


if __name__ == "__main__":
    unittest.main()
