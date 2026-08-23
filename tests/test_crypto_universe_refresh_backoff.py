"""2026-08-23: crypto-universe-refresh ran hourly, made three CoinGecko calls per run, and
the free public API answered every one with "HTTP Error 429: Too Many Requests". The
retrying then consumed the worker's whole 180s budget -- confirmed live as a recurring
"Worker job timed out: crypto-universe-refresh". A starved worker loop is the documented
cause of earlier production incidents, so the damage was not confined to this job.

Market-cap rankings barely move within a day, so the fix is to refresh at most every N
hours rather than hourly.
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from contextlib import closing

from ai_trader.database import connect
from ai_trader.operational import initialize_operational_schema, seed_crypto_universe


def seed_row(db_path, age_hours):
    stamp = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    # closing() matters on Windows: sqlite3's context manager commits but does NOT close,
    # so the file stays locked and TemporaryDirectory cleanup fails.
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                "INSERT INTO CRYPTO_ASSET_MASTER (symbol, name, category, market_cap_rank, source, active, notes, last_updated)"
                " VALUES ('BTC','Bitcoin','Top 20 by market cap',1,'test',1,'seed',?)",
                (stamp,),
            )


class UniverseRefreshBackoffTests(unittest.TestCase):
    def test_a_recent_refresh_makes_no_network_call_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_operational_schema(db_path)
            seed_row(db_path, age_hours=2)

            with mock.patch("ai_trader.operational.urlopen") as net:
                result = seed_crypto_universe(db_path, fetch_live=True)

            net.assert_not_called()
            self.assertTrue(result["skipped"])
            self.assertEqual(result["source"], "Cached")
            self.assertIn("rate limiting", result["notes"])

    def test_a_stale_universe_still_refreshes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_operational_schema(db_path)
            seed_row(db_path, age_hours=48)

            with mock.patch("ai_trader.operational.urlopen", side_effect=RuntimeError("network off")) as net:
                result = seed_crypto_universe(db_path, fetch_live=True)

            self.assertTrue(net.called, "Past the interval it must actually try again.")
            self.assertFalse(result.get("skipped"))

    def test_an_empty_universe_always_refreshes_regardless_of_interval(self):
        """A brand-new deployment has no rows, so there is nothing to be 'fresh' -- it must
        not sit behind the backoff waiting for data it has never had."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_operational_schema(db_path)

            with mock.patch("ai_trader.operational.urlopen", side_effect=RuntimeError("network off")) as net:
                seed_crypto_universe(db_path, fetch_live=True)

            self.assertTrue(net.called)

    def test_the_interval_is_configurable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_operational_schema(db_path)
            seed_row(db_path, age_hours=6)

            with mock.patch.dict(os.environ, {"CRYPTO_UNIVERSE_MIN_REFRESH_HOURS": "3"}), \
                 mock.patch("ai_trader.operational.urlopen", side_effect=RuntimeError("network off")) as net:
                seed_crypto_universe(db_path, fetch_live=True)
            self.assertTrue(net.called, "6h old against a 3h interval must refresh.")

            with mock.patch.dict(os.environ, {"CRYPTO_UNIVERSE_MIN_REFRESH_HOURS": "24"}), \
                 mock.patch("ai_trader.operational.urlopen") as net2:
                seed_crypto_universe(db_path, fetch_live=True)
            net2.assert_not_called()

    def test_fetch_live_false_is_unaffected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_operational_schema(db_path)
            with mock.patch("ai_trader.operational.urlopen") as net:
                result = seed_crypto_universe(db_path, fetch_live=False)
            net.assert_not_called()
            self.assertNotIn("skipped", result)


if __name__ == "__main__":
    unittest.main()
