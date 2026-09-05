"""Phases 0-2 of the learning work, 2026-09-05.

The app recorded a great deal about what it did and changed nothing as a result. Every
learning table was read only by the display layer, and the one slot where past results could
have influenced strategy choice -- `historical_statistics` -- was wired to a constant, so the
`sample_size >= 30` check could never pass and every strategy scored the neutral 0.5 forever.

These tests cover the three pieces that close that loop, and in particular the two ways it
could go wrong quietly: learning from a record that is not trustworthy, and reporting a
confident-looking number built from small change.
"""

import json
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
from ai_trader.sprint6 import initialize_sprint6_schema
from ai_trader.learning_readiness import (
    MINIMUM_CLOSED_TRADES,
    STALENESS_LIMIT_DAYS,
    assess_learning_readiness,
)
from ai_trader.strategy_demotion import (
    CATASTROPHIC_SAMPLE,
    DEMOTION_EXPECTANCY_R,
    EVALUATION_WINDOW_DAYS,
    MINIMUM_LIVE_STRATEGIES,
    review_strategies_for_demotion,
)
from ai_trader.strategy_performance import MINIMUM_RISK_FOR_R, strategy_records


def _new_db(tmp: str) -> Path:
    """Every schema the learning path touches: outcomes live in PERFORMANCE_ATTRIBUTION
    (multi_broker), the strategy and stop in trade_audit (audit), and the maturity registry
    in sprint6."""
    db = Path(tmp) / "a.sqlite3"
    initialize_foundation_schema(db)
    initialize_multi_broker_schema(db)
    initialize_sprint6_schema(db)
    AuditDatabase(db, None)
    return db


def _iso(days_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _seed_trade(db: Path, *, proposal_id: str, strategy_id: str, pnl: float,
                entry: float = 100.0, stop: float = 98.0, quantity: float = 1.0,
                days_ago: float = 1.0) -> None:
    """One closed trade, recorded the way production records them: the outcome in
    PERFORMANCE_ATTRIBUTION and the strategy/stop only in the TRADE_AUDIT payload."""
    with closing(connect(db)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO PERFORMANCE_ATTRIBUTION (
                    created_at, proposal_id, broker, symbol, asset_type, side,
                    entry_price, exit_price, quantity, profit_loss, opened_at, closed_at,
                    primary_factors_json
                ) VALUES (?, ?, 'kraken', 'TEST', 'crypto', 'buy', ?, ?, ?, ?, ?, ?, '{}')
                """,
                (_iso(days_ago), proposal_id, entry, entry + pnl / max(quantity, 1e-9),
                 quantity, pnl, _iso(days_ago + 1), _iso(days_ago)),
            )
            conn.execute(
                """
                INSERT INTO TRADE_AUDIT (
                    created_at, proposal_id, event_type, symbol, broker, side, entry,
                    ai_reasoning, news_summary, sentiment_summary, technical_summary,
                    ai_confidence, ai_guardrails_passed, position_size, stop_loss,
                    take_profit, payload_json
                ) VALUES (?, ?, 'agent_proposal', 'TEST', 'kraken', 'buy', ?, '', '', '', '',
                          0.75, 1, ?, ?, ?, ?)
                """,
                (_iso(days_ago), proposal_id, entry, quantity, stop, entry * 1.05,
                 json.dumps({"proposal": {"strategy_id": strategy_id, "stop_loss": stop}})),
            )


class LearningReadinessTests(unittest.TestCase):
    def test_an_empty_record_refuses_rather_than_reporting_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            readiness = assess_learning_readiness(db)
            self.assertFalse(readiness.ready)
            self.assertIn("no closed trades", readiness.plain_english)

    def test_too_few_trades_is_a_blocker_not_a_small_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            for i in range(MINIMUM_CLOSED_TRADES - 1):
                _seed_trade(db, proposal_id=f"p{i}", strategy_id="momentum", pnl=1.0)
            self.assertFalse(assess_learning_readiness(db).ready)

    def test_a_stale_record_refuses_because_the_numbers_describe_the_past(self):
        """The dangerous case: the maths still works, it is just describing last month."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            for i in range(10):
                _seed_trade(db, proposal_id=f"p{i}", strategy_id="momentum", pnl=1.0,
                            days_ago=STALENESS_LIMIT_DAYS + 5)
            readiness = assess_learning_readiness(db)
            self.assertFalse(readiness.ready)
            self.assertTrue(any("days old" in b for b in readiness.blockers))

    def test_epoch_timestamps_are_read_not_discarded(self):
        """26 of 66 production rows stored a raw epoch, and '1787586949' sorts before
        '2026-08-31' as text -- a plain date filter would silently drop the newest trades."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            for i in range(10):
                _seed_trade(db, proposal_id=f"p{i}", strategy_id="momentum", pnl=1.0)
            with closing(connect(db)) as conn:
                with conn:
                    conn.execute("UPDATE PERFORMANCE_ATTRIBUTION SET closed_at = ?, created_at = ?",
                                 (str(datetime.now(timezone.utc).timestamp()),
                                  str(datetime.now(timezone.utc).timestamp())))
            readiness = assess_learning_readiness(db)
            self.assertEqual(readiness.unparseable_timestamps, 0)
            self.assertTrue(readiness.ready)


class StrategyPerformanceTests(unittest.TestCase):
    def test_results_are_grouped_by_the_strategy_that_took_the_trade(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            for i in range(6):
                _seed_trade(db, proposal_id=f"w{i}", strategy_id="momentum", pnl=4.0)
            for i in range(6):
                _seed_trade(db, proposal_id=f"l{i}", strategy_id="range_trading", pnl=-4.0)
            records = strategy_records(db)
            self.assertEqual(records["momentum"].wins, 6)
            self.assertEqual(records["range_trading"].wins, 0)
            self.assertGreater(records["momentum"].expectancy_r, 0)
            self.assertLess(records["range_trading"].expectancy_r, 0)

    def test_trades_risking_small_change_contribute_no_R(self):
        """THE TRAP. Measured on production before this floor existed: 53 trades averaged
        +1.78R against a NET LOSS of GBP 7.64, because nine trades from the GBP 2-5 era risked
        about four pence each and scored up to +19.8R. The median was -0.45R."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            # Six ordinary losers, risking GBP 2 each.
            for i in range(6):
                _seed_trade(db, proposal_id=f"real{i}", strategy_id="momentum", pnl=-1.0,
                            entry=100.0, stop=98.0, quantity=1.0)
            # One tiny winner risking a fraction of a penny, which would otherwise score +1000R.
            _seed_trade(db, proposal_id="tiny", strategy_id="momentum", pnl=0.60,
                        entry=100.0, stop=99.9999, quantity=0.006)
            record = strategy_records(db)["momentum"]
            self.assertLess(record.expectancy_r, 0,
                            "a losing strategy must not be rescued by small change")
            self.assertEqual(record.sample_size, 7, "the tiny trade still counts as a trade")

    def test_nothing_is_reported_when_the_record_cannot_be_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            _seed_trade(db, proposal_id="only", strategy_id="momentum", pnl=1.0)
            self.assertEqual(strategy_records(db), {},
                             "one trade is not evidence; returning a number here is the bug")


class StrategyDemotionTests(unittest.TestCase):
    def _registry(self, db: Path, strategy_id: str) -> None:
        with closing(connect(db)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO STRATEGY_MATURITY_REGISTRY (
                        strategy_id, version, current_stage, evidence_json,
                        permitted_asset_classes_json, permitted_brokers_json,
                        permitted_modes_json, suspended, approval_authority, updated_at
                    ) VALUES (?, '1', 'Micro Live', '{}', '["crypto"]', '["kraken"]',
                              '["manual","micro_live","paper","shadow"]', 0, 'Founder', ?)
                    """,
                    (strategy_id, _iso()),
                )

    def test_a_strategy_losing_money_on_a_real_sample_loses_its_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            self._registry(db, "momentum")
            # Enough other live strategies that the erosion floor is not what stops this.
            for spare in range(MINIMUM_LIVE_STRATEGIES):
                self._registry(db, f"spare{spare}")
            # Catastrophic, not merely weak: -3.0 against GBP 2.00 of risk is -1.5R, i.e.
            # losing more than the trade said it would risk. That is the risk model failing to
            # hold, which is the only case this backstop exists for.
            for i in range(CATASTROPHIC_SAMPLE + 5):
                _seed_trade(db, proposal_id=f"bad{i}", strategy_id="momentum", pnl=-3.0,
                            entry=100.0, stop=98.0, quantity=1.0)
            result = review_strategies_for_demotion(db)
            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["demoted"][0]["strategy_id"], "momentum")
            with closing(connect(db)) as conn:
                row = conn.execute(
                    "SELECT current_stage, permitted_modes_json FROM STRATEGY_MATURITY_REGISTRY "
                    "WHERE strategy_id='momentum'").fetchone()
            self.assertEqual(row[0], "Paper")
            self.assertNotIn("micro_live", json.loads(row[1]))
            self.assertIn("paper", json.loads(row[1]), "it must keep running in paper")

    def test_a_profitable_strategy_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            self._registry(db, "momentum")
            for i in range(CATASTROPHIC_SAMPLE + 5):
                _seed_trade(db, proposal_id=f"good{i}", strategy_id="momentum", pnl=3.0,
                            entry=100.0, stop=98.0, quantity=1.0)
            result = review_strategies_for_demotion(db)
            self.assertEqual(result["status"], "no_change")
            self.assertEqual(result["demoted"], [])

    def test_a_merely_unprofitable_strategy_is_no_longer_demoted(self):
        """Founder challenge 2026-09-05: demotion should fire only on a catastrophic failure,
        not on underperformance. Losing 0.5R per trade is weak, and weakness is a reason for
        the model to choose something else -- not a reason to take the option away."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            self._registry(db, "momentum")
            for spare in range(MINIMUM_LIVE_STRATEGIES):
                self._registry(db, f"spare{spare}")
            for i in range(CATASTROPHIC_SAMPLE + 5):
                _seed_trade(db, proposal_id=f"weak{i}", strategy_id="momentum", pnl=-1.0,
                            entry=100.0, stop=98.0, quantity=1.0)
            self.assertEqual(review_strategies_for_demotion(db)["demoted"], [])

    def test_a_small_sample_never_demotes_however_bad(self):
        """Three bad trades is a bad week, not a verdict. Demoting on it would recreate the
        doom loop: a strategy that cannot trade can never prove itself again."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            self._registry(db, "momentum")
            for i in range(8):
                _seed_trade(db, proposal_id=f"few{i}", strategy_id="momentum", pnl=-5.0,
                            entry=100.0, stop=98.0, quantity=1.0)
            self.assertEqual(review_strategies_for_demotion(db)["demoted"], [])

    def test_an_untrustworthy_record_demotes_nothing(self):
        """No record means no demotion -- the opposite of reading an absent input as a
        negative finding, which is how the per-coin doom loop worked."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            self._registry(db, "momentum")
            result = review_strategies_for_demotion(db)
            self.assertEqual(result["status"], "stood_down")
            self.assertEqual(result["demoted"], [])

    def test_demotion_is_recorded_with_the_evidence_behind_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            self._registry(db, "momentum")
            for spare in range(MINIMUM_LIVE_STRATEGIES):
                self._registry(db, f"spare{spare}")
            for i in range(CATASTROPHIC_SAMPLE + 5):
                _seed_trade(db, proposal_id=f"bad{i}", strategy_id="momentum", pnl=-3.0)
            review_strategies_for_demotion(db)
            with closing(connect(db)) as conn:
                row = conn.execute(
                    "SELECT decision, evidence_gate_status, payload_json FROM "
                    "STRATEGY_PROMOTION_DECISIONS WHERE strategy_id='momentum'").fetchone()
            self.assertEqual(row[0], "demote")
            self.assertEqual(row[1], "failed_on_live_evidence")
            payload = json.loads(row[2])
            self.assertLessEqual(payload["expectancy_r"], DEMOTION_EXPECTANCY_R)
            self.assertGreaterEqual(payload["sample_size"], 30)


    def test_the_app_is_never_eroded_below_a_minimum_of_live_strategies(self):
        """Founder challenge, 2026-09-05: "otherwise we end up having just one or two
        strategies, which then makes the app weaker at trading anyway." An app down to one or
        two cannot adapt when the regime turns, which is the larger risk. The worst performer
        is demoted first, and the rest are recorded as held rather than silently ignored."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            for n in range(MINIMUM_LIVE_STRATEGIES):
                self._registry(db, f"bad{n}")
                for i in range(CATASTROPHIC_SAMPLE + 5):
                    _seed_trade(db, proposal_id=f"s{n}t{i}", strategy_id=f"bad{n}", pnl=-3.0)
            result = review_strategies_for_demotion(db)
            self.assertEqual(result["demoted"], [],
                             "demoting any of them would breach the floor")
            with closing(connect(db)) as conn:
                held = conn.execute(
                    "SELECT COUNT(*) FROM STRATEGY_PROMOTION_DECISIONS WHERE decision='hold'"
                ).fetchone()[0]
            self.assertEqual(held, MINIMUM_LIVE_STRATEGIES,
                             "each withheld demotion must still be recorded as a concern")

    def test_a_strategy_is_judged_on_the_recent_market_not_its_whole_history(self):
        """Regimes rotate. A strategy that lost money in a flat market months ago should not be
        condemned for it once that evidence ages out of the window."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            self._registry(db, "momentum")
            for i in range(CATASTROPHIC_SAMPLE + 5):
                _seed_trade(db, proposal_id=f"old{i}", strategy_id="momentum", pnl=-5.0,
                            days_ago=EVALUATION_WINDOW_DAYS + 30)
            for i in range(CATASTROPHIC_SAMPLE + 5):
                _seed_trade(db, proposal_id=f"new{i}", strategy_id="momentum", pnl=3.0,
                            days_ago=2)
            self.assertEqual(review_strategies_for_demotion(db)["demoted"], [],
                             "recent profitable trades must outweigh an aged-out bad patch")

    def test_the_one_way_ratchet_is_declared_on_every_run(self):
        """Nothing here can restore a permission it removes, and that must stay visible rather
        than being rediscovered later."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _new_db(tmp)
            self.assertIn("one-way", review_strategies_for_demotion(db)["re_promotion"])


if __name__ == "__main__":
    unittest.main()
