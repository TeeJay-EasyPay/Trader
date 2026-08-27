"""2026-08-27 audit finding: the learning loop had never produced a single row.

POST_TRADE_REVIEWS and LEARNING_PROPOSALS were both empty since the app was built, so the
app could not review its own trades -- the capability the whole closed-loop learning chain
exists to provide. Every piece of that chain was written and wired: reconciliation enqueued
the workflow, the outbox processor claimed it, run_closed_loop_learning called
generate_post_trade_review and create_learning_proposal.

Production told the real story:

    20 workflows, status 'failed'
    "Required numeric value missing: intended_entry_price/entry_price"

The price was never missing. A decision context records the whole decision -- account equity,
guardrails, allocation, intelligence -- and the trade's own parameters live in its "proposal"
block. The reader only ever looked at the top level, so every workflow failed, exhausted its
3 retries, and parked itself at 'failed', which the processor's claim query deliberately
ignores. A bug therefore killed the entire loop permanently and silently.

Verified against the 20 real production contexts: all resolve once the reader looks one level
in (entry 95.58 / stop 94.15, entry 1523.80 / stop 1493.32, ...).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from contextlib import closing

from ai_trader.database import connect
from ai_trader.production_spine import (
    _context_value,
    _required_float,
    requeue_failed_learning_workflows,
)
from ai_trader.sprint6 import _ensure_sprint6_schema, enqueue_learning_workflow

# Shaped exactly like the production contexts this bug was found in.
REAL_CONTEXT = {
    "account_equity": 500.0,
    "allocation": {"approved_notional": 10.0, "approved_quantity": 80.34, "risk_amount": 5.0},
    "guardrails": {"passed": True},
    "intelligence": {"confidence": 0.7},
    "production_gate": {"status": "pass"},
    "proposal": {
        "proposal_id": "prop-1", "symbol": "SOL", "side": "buy", "asset_type": "crypto",
        "entry_price": 95.58, "stop_loss": 94.1463, "take_profit": 99.0,
        "strategy_id": "momentum-v2", "confidence_score": 0.71,
    },
}


class ContextReaderTests(unittest.TestCase):
    def test_finds_the_trade_parameters_nested_under_proposal(self):
        """The bug: every one of these returned None, killing all 20 workflows."""
        self.assertEqual(_context_value(REAL_CONTEXT, "entry_price"), 95.58)
        self.assertEqual(_context_value(REAL_CONTEXT, "stop_loss"), 94.1463)
        self.assertEqual(_context_value(REAL_CONTEXT, "side"), "buy")
        self.assertEqual(_context_value(REAL_CONTEXT, "asset_type"), "crypto")
        self.assertEqual(_context_value(REAL_CONTEXT, "strategy_id"), "momentum-v2")

    def test_a_top_level_value_still_wins_over_a_nested_one(self):
        # Newer contexts may carry the field at the top level; that reading is the more
        # specific one and must not be shadowed by the nested block.
        context = {**REAL_CONTEXT, "entry_price": 100.0}
        self.assertEqual(_context_value(context, "entry_price"), 100.0)

    def test_other_nested_blocks_are_searched_too(self):
        self.assertEqual(_context_value(REAL_CONTEXT, "risk_amount"), 5.0)

    def test_a_genuinely_absent_field_is_still_none(self):
        self.assertIsNone(_context_value(REAL_CONTEXT, "no_such_field"))

    def test_an_empty_context_does_not_crash_the_reader(self):
        self.assertIsNone(_context_value({}, "entry_price"))

    def test_required_float_now_resolves_what_it_used_to_raise_on(self):
        self.assertAlmostEqual(_required_float(REAL_CONTEXT, "intended_entry_price", "entry_price"), 95.58)
        self.assertAlmostEqual(_required_float(REAL_CONTEXT, "original_stop", "stop_loss"), 94.1463)

    def test_required_float_still_raises_when_the_value_really_is_absent(self):
        """The guard must keep working: a truly empty context is not a trade to learn from,
        and inventing a price would corrupt every R-multiple computed from it."""
        with self.assertRaises(ValueError):
            _required_float({"proposal": {}}, "intended_entry_price", "entry_price")


class RequeueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        _ensure_sprint6_schema(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def add_workflow(self, trade_id, status, error=None):
        enqueue_learning_workflow(
            self.db_path, logical_trade_id=trade_id, broker="kraken",
            payload={"symbol": "SOL", "decision_context": REAL_CONTEXT},
        )
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "UPDATE SPRINT6_WORKFLOW_OUTBOX SET status = ?, attempts = 3, last_error = ?"
                    " WHERE entity_id = ?",
                    (status, error, trade_id),
                )

    def statuses(self):
        with closing(connect(self.db_path)) as conn:
            return dict(
                conn.execute(
                    "SELECT entity_id, status FROM SPRINT6_WORKFLOW_OUTBOX"
                ).fetchall()
            )

    def test_revives_a_workflow_that_a_bug_killed(self):
        self.add_workflow("trade-1", "failed", "Required numeric value missing: entry_price")
        outcome = requeue_failed_learning_workflows(self.db_path)
        self.assertEqual(outcome["requeued"], 1)
        self.assertEqual(self.statuses()["trade-1"], "pending")

    def test_resets_attempts_so_the_fix_gets_a_full_set_of_retries(self):
        self.add_workflow("trade-1", "failed", "boom")
        requeue_failed_learning_workflows(self.db_path)
        with closing(connect(self.db_path)) as conn:
            attempts = conn.execute(
                "SELECT attempts FROM SPRINT6_WORKFLOW_OUTBOX WHERE entity_id = 'trade-1'"
            ).fetchone()[0]
        self.assertEqual(attempts, 0)

    def test_scoping_by_error_leaves_unrelated_failures_alone(self):
        """A requeue must not blanket-revive failures that are still genuinely broken."""
        self.add_workflow("fixed-bug", "failed", "Required numeric value missing: entry_price")
        self.add_workflow("still-broken", "failed", "Broker credentials rejected")
        outcome = requeue_failed_learning_workflows(self.db_path, error_contains="Required numeric value")
        self.assertEqual(outcome["requeued"], 1)
        statuses = self.statuses()
        self.assertEqual(statuses["fixed-bug"], "pending")
        self.assertEqual(statuses["still-broken"], "failed")

    def test_completed_workflows_are_never_re_run(self):
        # Re-running a completed workflow would duplicate its review and its proposal.
        self.add_workflow("done", "completed")
        self.assertEqual(requeue_failed_learning_workflows(self.db_path)["requeued"], 0)
        self.assertEqual(self.statuses()["done"], "completed")

    def test_nothing_to_requeue_is_handled_cleanly(self):
        self.assertEqual(requeue_failed_learning_workflows(self.db_path), {"requeued": 0, "workflow_ids": []})


if __name__ == "__main__":
    unittest.main()
