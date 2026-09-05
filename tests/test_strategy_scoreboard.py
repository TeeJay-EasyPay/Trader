"""Phase 5, 2026-09-05: the model gets the field, not one pre-chosen candidate.

Founder's framing: "shouldn't the AI be able to look at the strategies for a specific trade
and say, in the past these strategies worked, these didn't work for this specific coin."

The whole point is the PER-COIN split. Settled shadow trades put crypto_trend_following_2r at
-0.15R on BCH and -1.77R on XRP -- a tenfold spread that any per-strategy average destroys, and
the reason judging a strategy on its overall record removes it from the coin where it works.

These tests also pin the cost discipline, because that is a design constraint here: the
scoreboard rides in calls that already happen, and the outcome tables are read once per cycle
rather than once per candidate. At ~148 equity proposals a day the difference is the point.
"""

import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.audit import AuditDatabase
from ai_trader.database import connect
from ai_trader.foundation import initialize_foundation_schema
from ai_trader.multi_broker import initialize_multi_broker_schema
from ai_trader.always_on import initialize_always_on_schema
from ai_trader.sprint6 import initialize_sprint6_schema
from ai_trader.strategy_scoreboard import (
    THIN_SAMPLE,
    clear_cache,
    serialize_strategy_evidence,
    strategy_evidence_for,
)


def _db(tmp: str) -> Path:
    db = Path(tmp) / "a.sqlite3"
    initialize_foundation_schema(db)
    initialize_multi_broker_schema(db)
    initialize_sprint6_schema(db)
    initialize_always_on_schema(db)   # SHADOW_TRADES lives here
    AuditDatabase(db, None)
    return db


def _shadow(db: Path, *, symbol: str, strategy: str, net_r: float, count: int) -> None:
    now = datetime.now(timezone.utc)
    with closing(connect(db)) as conn:
        with conn:
            for i in range(count):
                conn.execute(
                    """
                    INSERT INTO SHADOW_TRADES (
                        created_at, updated_at, symbol, asset_type, intended_broker, strategy,
                        decision_status, outcome_status, estimated_net_r, idempotency_key
                    ) VALUES (?, ?, ?, 'crypto', 'kraken', ?, 'shadow_candidate', 'stop_hit', ?, ?)
                    """,
                    ((now - timedelta(days=1)).isoformat(), now.isoformat(), symbol, strategy,
                     net_r, f"{symbol}-{strategy}-{i}"),
                )


class ScoreboardTests(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_the_same_strategy_reads_differently_on_different_coins(self):
        """THE POINT OF PHASE 5. One strategy, two coins, two verdicts -- which a per-strategy
        average would have collapsed into one."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _db(tmp)
            _shadow(db, symbol="BCH", strategy="trend_following", net_r=-0.15, count=40)
            _shadow(db, symbol="XRP", strategy="trend_following", net_r=-1.77, count=40)

            bch = strategy_evidence_for(db, symbol="BCH", candidates=["trend_following"])[0]
            clear_cache()
            xrp = strategy_evidence_for(db, symbol="XRP", candidates=["trend_following"])[0]

            self.assertAlmostEqual(bch.coin_expectancy_r, -0.15, places=2)
            self.assertAlmostEqual(xrp.coin_expectancy_r, -1.77, places=2)
            self.assertGreater(bch.coin_expectancy_r, xrp.coin_expectancy_r)

    def test_the_best_strategy_on_this_coin_is_listed_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _db(tmp)
            _shadow(db, symbol="SOL", strategy="range_trading", net_r=0.40, count=20)
            _shadow(db, symbol="SOL", strategy="trend_following", net_r=-1.20, count=20)
            evidence = strategy_evidence_for(
                db, symbol="SOL", candidates=["trend_following", "range_trading"]
            )
            self.assertEqual(evidence[0].strategy_id, "range_trading")

    def test_a_strategy_with_no_record_is_still_offered_and_marked_unproven(self):
        """It must reach the model. Silently withholding an option is the mistake that made
        demotion wrong -- absent evidence is not evidence of absence."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _db(tmp)
            _shadow(db, symbol="SOL", strategy="range_trading", net_r=0.40, count=20)
            ids = [e.strategy_id for e in strategy_evidence_for(
                db, symbol="SOL", candidates=["range_trading", "breakout"])]
            self.assertIn("breakout", ids)
            text = serialize_strategy_evidence(strategy_evidence_for(
                db, symbol="SOL", candidates=["range_trading", "breakout"]))
            self.assertIn("breakout: no record on this coin", text)

    def test_a_thin_sample_is_labelled_as_thin(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _db(tmp)
            _shadow(db, symbol="SOL", strategy="breakout", net_r=2.0, count=THIN_SAMPLE - 5)
            text = serialize_strategy_evidence(
                strategy_evidence_for(db, symbol="SOL", candidates=["breakout"]))
            self.assertIn("[thin]", text,
                          "a handful of trades must not read like a track record")

    def test_simulation_is_never_presented_as_a_trading_record(self):
        """A shadow result is what WOULD have happened. Blending it into real money would be
        the same error as the fabricated trend score that hid this app's behaviour for a
        fortnight."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _db(tmp)
            _shadow(db, symbol="SOL", strategy="breakout", net_r=0.5, count=20)
            text = serialize_strategy_evidence(
                strategy_evidence_for(db, symbol="SOL", candidates=["breakout"]))
            self.assertIn("shadow_simulation", text)
            self.assertIn("not a trading record", text)

    def test_an_empty_record_says_so_rather_than_implying_equality(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _db(tmp)
            text = serialize_strategy_evidence(
                strategy_evidence_for(db, symbol="SOL", candidates=["breakout", "momentum"]))
            self.assertIn("unproven rather than equal", text)

    def test_the_outcome_tables_are_read_once_per_cycle_not_once_per_candidate(self):
        """Cost discipline. At ~148 equity proposals a day, reading the outcome tables per
        candidate instead of per cycle is the difference between one query and 148 -- the same
        N+1 shape that makes broker-poll-kraken time out and drives Supabase egress."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _db(tmp)
            _shadow(db, symbol="SOL", strategy="breakout", net_r=0.5, count=12)
            calls = {"n": 0}
            import ai_trader.strategy_scoreboard as scoreboard
            original = scoreboard.shadow_symbol_records

            def counting(*args, **kwargs):
                calls["n"] += 1
                return original(*args, **kwargs)

            scoreboard.shadow_symbol_records = counting
            try:
                clear_cache()
                for _ in range(10):
                    strategy_evidence_for(db, symbol="SOL", candidates=["breakout"])
            finally:
                scoreboard.shadow_symbol_records = original
            self.assertEqual(calls["n"], 1, "ten candidates must cost one read, not ten")


if __name__ == "__main__":
    unittest.main()
