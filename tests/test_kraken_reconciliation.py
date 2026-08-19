import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.canonical_trades import canonical_trade, register_execution_intent
from ai_trader.kraken_reconciliation import (
    backfill_missing_managed_exits,
    initialize_kraken_reconciliation_schema,
    kraken_capital_ledger_summary,
    reconciliation_control,
    register_kraken_order_ownership,
    replay_kraken_evidence,
    replay_persisted_kraken_evidence,
    resume_kraken_entries_after_verification,
    verify_kraken_reconciliation,
)
from ai_trader.models import TradeProposal
from ai_trader.multi_broker import initialize_multi_broker_schema, open_managed_exits
from ai_trader.sprint6 import process_learning_outbox


def proposal(proposal_id: str = "kraken-proposal-1") -> TradeProposal:
    return TradeProposal(
        proposal_id=proposal_id,
        symbol="XRPGBP",
        side="buy",
        entry_price=1.0,
        stop_loss=0.9,
        take_profit=1.2,
        position_size=10.0,
        risk_percentage=0.01,
        confidence_score=0.9,
        news_summary="Test evidence.",
        market_sentiment_summary="Test evidence.",
        technical_summary="Test evidence.",
        plain_english_reasoning="Test evidence.",
        ai_guardrails_passed=True,
        asset_type="crypto",
        exchange="KRAKEN",
    )


def trade_fill(order_id: str, fill_id: str, side: str, price: float, when: str) -> dict:
    return {
        "kraken_record_type": "trade_fill",
        "ordertxid": order_id,
        "trade_id": fill_id,
        "pair": "XRPGBP",
        "type": side,
        "vol": "10",
        "price": str(price),
        "fee": "0.10",
        "time": when,
        "status": "filled",
    }


class KrakenReconciliationTests(unittest.TestCase):
    def test_default_control_pauses_entries_and_failed_verification_cannot_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_kraken_reconciliation_schema(db_path)

            self.assertTrue(reconciliation_control(db_path)["hold_new_entries"])
            resumed = resume_kraken_entries_after_verification(db_path)
            self.assertEqual(resumed["status"], "rejected")
            self.assertTrue(reconciliation_control(db_path)["hold_new_entries"])

    def test_closed_order_is_not_a_fill_or_closed_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_kraken_reconciliation_schema(db_path)
            register_kraken_order_ownership(
                db_path,
                broker_order_id="kraken-entry-1",
                logical_trade_id="trade-1",
                order_role="entry",
                symbol="XRPGBP",
                side="buy",
            )

            replay_kraken_evidence(
                db_path,
                events=[
                    {
                        "kraken_record_type": "closed_order",
                        "id": "kraken-entry-1",
                        "status": "closed",
                        "vol_exec": "10",
                        "price": "1.00",
                        "closetm": "2026-07-10T10:00:00+00:00",
                        "descr": {"pair": "XRPGBP", "type": "buy"},
                    }
                ],
            )

            trade = canonical_trade(db_path, "trade-1")
            self.assertIsNotNone(trade)
            self.assertEqual(trade["entry_filled_quantity"], 0)
            self.assertEqual(trade["terminal"], 0)
            with closing(sqlite3.connect(db_path)) as conn:
                fills = conn.execute("SELECT COUNT(*) FROM LOGICAL_TRADE_FILLS").fetchone()[0]
            self.assertEqual(fills, 0)

    def test_explicit_round_trip_reconciles_ledger_and_learning_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_kraken_reconciliation_schema(db_path)
            p = proposal()
            register_execution_intent(
                db_path,
                proposal=p,
                broker="kraken",
                decision_context={
                    "proposal_id": p.proposal_id,
                    "asset_type": "crypto",
                    "strategy_id": "crypto_trend",
                    "regime_id": "trend",
                    "side": "buy",
                    "entry_price": p.entry_price,
                    "intended_entry_price": p.entry_price,
                    "stop_loss": p.stop_loss,
                    "original_stop": p.stop_loss,
                    "take_profit": p.take_profit,
                    "expected_r": 2.0,
                    "strongest_argument_for": "Trend evidence supported entry.",
                    "strongest_argument_against": "Crypto volatility can reverse quickly.",
                },
            )
            register_kraken_order_ownership(
                db_path,
                broker_order_id="entry-1",
                logical_trade_id=p.proposal_id,
                proposal_id=p.proposal_id,
                order_role="entry",
                symbol=p.symbol,
                side="buy",
            )
            register_kraken_order_ownership(
                db_path,
                broker_order_id="exit-1",
                logical_trade_id=p.proposal_id,
                proposal_id=p.proposal_id,
                order_role="exit",
                symbol=p.symbol,
                side="sell",
            )
            events = [
                trade_fill("entry-1", "fill-entry-1", "buy", 1.0, "2026-07-10T10:00:00+00:00"),
                trade_fill("exit-1", "fill-exit-1", "sell", 1.2, "2026-07-10T11:00:00+00:00"),
                trade_fill("personal-order", "personal-fill", "buy", 5.0, "2026-07-10T12:00:00+00:00"),
            ]

            first = replay_kraken_evidence(db_path, events=events)
            second = replay_kraken_evidence(db_path, events=events)
            trade = canonical_trade(db_path, p.proposal_id)
            ledger = kraken_capital_ledger_summary(db_path)

            self.assertEqual(first["terminal_trades"], 1)
            self.assertEqual(first["learning_queued"], 1)
            self.assertEqual(first["unmanaged_excluded"], 1)
            self.assertEqual(second["learning_queued"], 0)
            self.assertAlmostEqual(trade["average_entry_price"], 1.0)
            self.assertAlmostEqual(trade["average_exit_price"], 1.2)
            self.assertAlmostEqual(trade["gross_pnl"], 2.0)
            self.assertAlmostEqual(trade["net_pnl"], 1.8)
            self.assertEqual(trade["terminal"], 1)
            self.assertAlmostEqual(ledger["available_cash_gbp"], 101.8)
            self.assertAlmostEqual(ledger["realized_net_pnl_gbp"], 1.8)
            self.assertFalse(ledger["personal_holdings_included"])

            with closing(sqlite3.connect(db_path)) as conn:
                outbox_count = conn.execute(
                    "SELECT COUNT(*) FROM SPRINT6_WORKFLOW_OUTBOX WHERE entity_id = ?",
                    (p.proposal_id,),
                ).fetchone()[0]
                ledger_fill_count = conn.execute(
                    "SELECT COUNT(*) FROM KRAKEN_AI_CAPITAL_LEDGER WHERE broker_fill_id IS NOT NULL"
                ).fetchone()[0]
            self.assertEqual(outbox_count, 1)
            self.assertEqual(ledger_fill_count, 2)

            learning = process_learning_outbox(db_path, worker_id="test-worker")
            duplicate_learning = process_learning_outbox(db_path, worker_id="test-worker")
            self.assertEqual(learning["processed"], 1)
            self.assertEqual(duplicate_learning["processed"], 0)

    def test_one_orders_id_mismatch_does_not_block_every_other_trades_learning(self):
        # 2026-08-19 hosted finding, reproduced live via /kraken-reconciliation/replay: an
        # exit order whose logical_trade_id and proposal_id had drifted apart (see
        # _merge_managed_exit_payload's docstring in multi_broker.py) made every reconcile
        # attempt for it raise "duplicate key value violates unique constraint
        # 'logical_trades_proposal_id_key'" -- a DIFFERENT logical_trade_id row trying to
        # claim a proposal_id another row already owns. Uncaught, that aborted the entire
        # batch before the terminals loop ever ran, so learning_queued stayed 0 for every
        # trade in the cycle, not just the poisoned one. This reproduces that exact
        # mismatched-ownership shape directly (bypassing however it originally arose) and
        # proves a healthy trade folded into the SAME batch still reconciles and gets its
        # learning workflow queued.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_kraken_reconciliation_schema(db_path)

            trade_a = proposal("trade-A")
            register_execution_intent(db_path, proposal=trade_a, broker="kraken", decision_context={"proposal_id": trade_a.proposal_id})
            register_kraken_order_ownership(
                db_path, broker_order_id="entry-a", logical_trade_id=trade_a.proposal_id,
                proposal_id=trade_a.proposal_id, order_role="entry", symbol=trade_a.symbol, side="buy",
            )
            register_kraken_order_ownership(
                db_path, broker_order_id="exit-a", logical_trade_id=trade_a.proposal_id,
                proposal_id=trade_a.proposal_id, order_role="exit", symbol=trade_a.symbol, side="sell",
            )
            # Trade A closes cleanly first, so LOGICAL_TRADES already owns proposal_id
            # "trade-A" under logical_trade_id "trade-A" before the mismatch below is created.
            first = replay_kraken_evidence(
                db_path,
                events=[
                    trade_fill("entry-a", "fill-entry-a", "buy", 1.0, "2026-07-10T10:00:00+00:00"),
                    trade_fill("exit-a", "fill-exit-a", "sell", 1.2, "2026-07-10T11:00:00+00:00"),
                ],
            )
            self.assertEqual(first["learning_queued"], 1)

            # A different order pair, registered with a synthetic logical_trade_id but the
            # SAME proposal_id as trade A -- the exact corrupted shape this session found.
            register_kraken_order_ownership(
                db_path, broker_order_id="poison-entry", logical_trade_id="kraken-managed-exit:99",
                proposal_id=trade_a.proposal_id, order_role="entry", symbol="BCHGBP", side="buy",
            )
            register_kraken_order_ownership(
                db_path, broker_order_id="poison-exit", logical_trade_id="kraken-managed-exit:99",
                proposal_id=trade_a.proposal_id, order_role="exit", symbol="BCHGBP", side="sell",
            )

            trade_b = proposal("trade-B")
            register_execution_intent(db_path, proposal=trade_b, broker="kraken", decision_context={"proposal_id": trade_b.proposal_id})
            register_kraken_order_ownership(
                db_path, broker_order_id="entry-b", logical_trade_id=trade_b.proposal_id,
                proposal_id=trade_b.proposal_id, order_role="entry", symbol=trade_b.symbol, side="buy",
            )
            register_kraken_order_ownership(
                db_path, broker_order_id="exit-b", logical_trade_id=trade_b.proposal_id,
                proposal_id=trade_b.proposal_id, order_role="exit", symbol=trade_b.symbol, side="sell",
            )

            # No exception -- the poisoned events must not abort the whole batch.
            result = replay_kraken_evidence(
                db_path,
                events=[
                    trade_fill("poison-entry", "fill-poison-entry", "buy", 100.0, "2026-07-11T10:00:00+00:00"),
                    trade_fill("poison-exit", "fill-poison-exit", "sell", 110.0, "2026-07-11T11:00:00+00:00"),
                    trade_fill("entry-b", "fill-entry-b", "buy", 1.0, "2026-07-11T12:00:00+00:00"),
                    trade_fill("exit-b", "fill-exit-b", "sell", 1.2, "2026-07-11T13:00:00+00:00"),
                ],
            )

            self.assertEqual(result["reconciliation_errors"], 2, "Both poisoned events must be recorded as errors, not silently dropped.")
            self.assertEqual(result["terminal_trades"], 1, "Trade B must still reach terminal despite the poisoned events earlier in the same batch.")
            self.assertEqual(result["learning_queued"], 1, "Trade B's learning workflow must still be queued.")

            trade_b_canonical = canonical_trade(db_path, trade_b.proposal_id)
            self.assertEqual(trade_b_canonical["terminal"], 1)

            with closing(sqlite3.connect(db_path)) as conn:
                error_cases = conn.execute(
                    "SELECT COUNT(*) FROM KRAKEN_RECONCILIATION_CASES WHERE classification = 'reconciliation_error'"
                ).fetchone()[0]
            self.assertEqual(error_cases, 2)

    def test_holding_position_missing_a_managed_exit_gets_backfilled(self):
        # 2026-08-13 hosted incident: BCH and XRP were both confirmed open on Kraken (real
        # stop/target recorded, status='holding') but neither had a MANAGED_TRADE_EXITS row --
        # monitor_managed_exits only ever reads open_managed_exits(), so neither position's
        # stop-loss/take-profit was actually being watched, and the capacity gate that reads the
        # same table under-counted real open exposure as 0. Reproduces that exact shape: an
        # entry-only fill (no exit) reconciled through the live ownership/replay path, exactly
        # as if the process crashed after Kraken confirmed the order but before
        # record_managed_trade_exit ran -- then asserts replay_kraken_evidence's own reconciliation
        # cycle recovers it without any extra caller action.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_kraken_reconciliation_schema(db_path)
            p = proposal(proposal_id="kraken-holding-1")
            register_execution_intent(
                db_path,
                proposal=p,
                broker="kraken",
                decision_context={
                    "proposal_id": p.proposal_id,
                    "asset_type": "crypto",
                    "strategy_id": "crypto_trend",
                    "regime_id": "trend",
                    "side": "buy",
                    "entry_price": p.entry_price,
                    "intended_entry_price": p.entry_price,
                    "stop_loss": p.stop_loss,
                    "original_stop": p.stop_loss,
                    "take_profit": p.take_profit,
                    "expected_r": 2.0,
                    "strongest_argument_for": "Trend evidence supported entry.",
                    "strongest_argument_against": "Crypto volatility can reverse quickly.",
                },
            )
            register_kraken_order_ownership(
                db_path,
                broker_order_id="holding-entry-1",
                logical_trade_id=p.proposal_id,
                proposal_id=p.proposal_id,
                order_role="entry",
                symbol=p.symbol,
                side="buy",
            )

            # No MANAGED_TRADE_EXITS row exists yet -- the live order path that would normally
            # create one (orchestrator.py, right after order submission) never ran here.
            self.assertEqual(open_managed_exits(db_path, "kraken"), [])

            result = replay_kraken_evidence(
                db_path,
                events=[trade_fill("holding-entry-1", "fill-holding-1", "buy", 1.0, "2026-07-10T10:00:00+00:00")],
            )

            self.assertEqual(result["managed_exits_backfilled"], 1)
            managed = open_managed_exits(db_path, "kraken")
            self.assertEqual(len(managed), 1)
            self.assertEqual(managed[0]["symbol"], "XRPGBP")
            self.assertAlmostEqual(managed[0]["stop_loss"], 0.9)
            self.assertAlmostEqual(managed[0]["take_profit"], 1.2)
            self.assertAlmostEqual(managed[0]["entry_price"], 1.0)

            # Idempotent: a second replay (e.g. the next broker-poll cycle) must not duplicate it.
            second = backfill_missing_managed_exits(db_path)
            self.assertEqual(second["backfilled"], 0)
            self.assertEqual(len(open_managed_exits(db_path, "kraken")), 1)

    def test_open_ai_owned_trade_reports_unrealized_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_kraken_reconciliation_schema(db_path)
            register_kraken_order_ownership(
                db_path,
                broker_order_id="entry-open",
                logical_trade_id="open-trade",
                order_role="entry",
                symbol="XRPGBP",
                side="buy",
            )
            replay_kraken_evidence(
                db_path,
                events=[trade_fill("entry-open", "fill-open", "buy", 1.0, "2026-07-10T10:00:00+00:00")],
            )

            unmarked = kraken_capital_ledger_summary(db_path)
            marked = kraken_capital_ledger_summary(db_path, current_prices={"XRPGBP": 1.1})

            self.assertIsNone(unmarked["unrealized_pnl_gbp"])
            self.assertAlmostEqual(marked["unrealized_pnl_gbp"], 1.0)
            self.assertAlmostEqual(marked["available_cash_gbp"], 89.9)
            self.assertAlmostEqual(marked["realized_net_pnl_gbp"], 0.0)

    def test_persisted_replay_is_read_only_and_submits_no_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_multi_broker_schema(db_path)
            initialize_kraken_reconciliation_schema(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO BROKER_TRADE_HISTORY (
                            broker, external_id, symbol, side, quantity, price,
                            status, opened_at, closed_at, updated_at, payload_json
                        ) VALUES ('kraken', 'personal-order', 'XRPGBP', 'buy', 10, 1,
                                  'closed', ?, ?, ?, ?)
                        """,
                        (
                            "2026-07-10T10:00:00+00:00",
                            "2026-07-10T10:01:00+00:00",
                            "2026-07-10T10:01:00+00:00",
                            '{"kraken_record_type":"closed_order","id":"personal-order","status":"closed","descr":{"pair":"XRPGBP","type":"buy"}}',
                        ),
                    )

            result = replay_persisted_kraken_evidence(db_path)

            self.assertEqual(result["broker_orders_submitted"], 0)
            self.assertEqual(result["persisted_rows_read"], 1)
            self.assertEqual(result["unmanaged_excluded"], 1)

    def test_verification_passes_only_with_complete_owned_terminal_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_kraken_reconciliation_schema(db_path)
            p = proposal("verified-trade")
            register_execution_intent(db_path, proposal=p, broker="kraken", decision_context={"proposal_id": p.proposal_id})
            for order_id, role, side in (("entry-v", "entry", "buy"), ("exit-v", "exit", "sell")):
                register_kraken_order_ownership(
                    db_path,
                    broker_order_id=order_id,
                    logical_trade_id=p.proposal_id,
                    proposal_id=p.proposal_id,
                    order_role=role,
                    symbol=p.symbol,
                    side=side,
                )
            replay_kraken_evidence(
                db_path,
                events=[
                    trade_fill("entry-v", "fill-entry-v", "buy", 1.0, "2026-07-10T10:00:00+00:00"),
                    trade_fill("exit-v", "fill-exit-v", "sell", 1.2, "2026-07-10T11:00:00+00:00"),
                ],
            )

            verification = verify_kraken_reconciliation(db_path)

            self.assertTrue(verification["passed"])
            self.assertTrue(reconciliation_control(db_path)["hold_new_entries"])


if __name__ == "__main__":
    unittest.main()
