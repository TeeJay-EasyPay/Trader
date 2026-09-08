"""Keeping evidence on refused crypto trades, and telling the reviewer the whole truth.

2026-09-08, out of the three-way standup and then verified straight against production.

TWO FAULTS, BOTH FOUND BY READING THE REAL DATA RATHER THAN THE ARGUMENT ABOUT IT.

1. NOTHING WAS BEING RECORDED. The trading AI raised it: "the shadow-trade record hasn't
   updated since 4 September... otherwise we're missing the evidence that could tell us whether
   this caution is protecting you or passing up good trades." True -- the last SHADOW_TRADES row
   is 2026-09-04 23:40, while 271 candidates were refused on 7 September alone. Shadow recording
   lived only in the research service; the crypto path is a different module and never had any.

2. THE REVIEWER WAS BEING MISLED, TWICE OVER.
   - It was told "-1.35R over 22 trades". The average is real and correctly computed, but it is
     over 13 trades; the other nine risked pennies and contribute no R at all. A 13-trade
     finding was wearing a 22-trade headcount.
   - It was shown what trading RETURNED and never what it COST. Measured on production: the 27
     closed Kraken trades made +GBP 0.17 before fees and -GBP 5.41 after them. Every fill was
     charged 0.800% by Kraken, entry and exit, so a 1.60% round trip sat against a 1.5% stop.
     The reviewer read the loss as bad selection and marked down every new candidate for it.

Everything here runs against a temporary database. Nothing calls a broker or a model.
"""

import json
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ai_trader.crypto_shadow import record_crypto_rejection, rejection_evidence
from ai_trader.strategy_scoreboard import (
    StrategyEvidence,
    serialize_strategy_evidence,
    trading_cost_note,
)

AGENT = REPO / "src" / "ai_trader" / "agent.py"


def _shadow_rows(db_path: Path) -> list[sqlite3.Row]:
    # closing(), not `with sqlite3.connect(...)`: the context manager commits but does not
    # close, and on Windows the still-open handle stops the temporary directory being removed.
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM SHADOW_TRADES ORDER BY shadow_trade_id").fetchall()


class RecordingRefusalsTests(unittest.TestCase):
    """The refused trades themselves. Without these rows, every argument about thresholds is
    opinion -- which is exactly how the 7 September standup went."""

    def _db(self, tmp):
        return Path(tmp) / "audit.sqlite3"

    def test_a_refused_candidate_is_written_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            self.assertTrue(record_crypto_rejection(
                db, symbol="fil", reason="ai_review_lowered_confidence_below_minimum",
                entry_price=5.0, stop_loss=4.925, take_profit=5.2, confidence=0.58,
            ))
            rows = _shadow_rows(db)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "FIL")
            self.assertEqual(rows[0]["intended_broker"], "kraken")
            self.assertEqual(rows[0]["asset_type"], "crypto")

    def test_the_reason_travels_with_the_row(self):
        """The useful question later is not "did refusing work" but "did refusing FOR THIS
        REASON work". That can only be answered if the reason is stored."""
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            record_crypto_rejection(
                db, symbol="DOT", reason="fee_hurdle_not_cleared",
                entry_price=4.0, stop_loss=3.94, take_profit=4.2,
            )
            row = _shadow_rows(db)[0]
            self.assertEqual(row["wait_or_rejection_reason"], "fee_hurdle_not_cleared")
            self.assertIn("fee_hurdle_not_cleared", row["market_evidence_json"])

    def test_it_is_written_where_the_existing_readers_look(self):
        """Deliberately the same decision_status the research service uses, so the resolver,
        the strategy records and the scorecard pick these up with no change at all."""
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            record_crypto_rejection(
                db, symbol="KAS", reason="ai_review_declined",
                entry_price=0.1, stop_loss=0.0985, take_profit=0.104,
            )
            self.assertEqual(_shadow_rows(db)[0]["decision_status"], "shadow_candidate")

    def test_the_settlement_fields_are_all_present(self):
        """shadow_outcomes.resolve_shadow_trades needs an entry, a stop and a target. A row
        missing any of them stays pending for ever, which looks like evidence and never
        becomes any."""
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            record_crypto_rejection(
                db, symbol="INJ", reason="liquidity_structure_unfavourable",
                entry_price=20.0, stop_loss=19.7, take_profit=20.6,
            )
            row = _shadow_rows(db)[0]
            self.assertAlmostEqual(row["intended_entry"], 20.0)
            self.assertAlmostEqual(row["stop_loss"], 19.7)
            self.assertAlmostEqual(row["take_profit"], 20.6)
            self.assertEqual(row["outcome_status"], "pending")

    def test_expected_r_is_stored_so_ambition_can_be_told_from_marginality(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            record_crypto_rejection(
                db, symbol="ETH", reason="fee_hurdle_not_cleared",
                entry_price=100.0, stop_loss=98.0, take_profit=104.0,
            )
            self.assertAlmostEqual(_shadow_rows(db)[0]["expected_r"], 2.0)

    def test_a_candidate_with_no_tradeable_shape_is_skipped_not_faked(self):
        """Refusals before a stop and target exist cannot be settled against anything later."""
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            self.assertFalse(record_crypto_rejection(
                db, symbol="BTC", reason="below_threshold",
                entry_price=50000.0, stop_loss=None, take_profit=None,
            ))
            self.assertFalse(record_crypto_rejection(
                db, symbol="BTC", reason="odd", entry_price=100.0,
                stop_loss=110.0, take_profit=120.0,  # stop above entry: not a long
            ))
            self.assertFalse(record_crypto_rejection(
                db, symbol="BTC", reason="odd", entry_price=100.0,
                stop_loss=98.0, take_profit=99.0,  # target below entry
            ))

    def test_the_same_refusal_all_day_writes_one_row_not_hundreds(self):
        """Research runs about 46 times a day over 10-19 symbols. Recording every pass would
        write hundreds of near-identical rows for one setup and put real weight on the Supabase
        egress this project has spent a week cutting."""
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            for _ in range(5):
                record_crypto_rejection(
                    db, symbol="SOL", reason="ai_review_declined",
                    entry_price=150.0, stop_loss=147.75, take_profit=154.5,
                )
            self.assertEqual(len(_shadow_rows(db)), 1)

    def test_a_different_reason_is_a_different_row(self):
        """Refused for fees today and by the reviewer tomorrow are two findings, not one."""
        with tempfile.TemporaryDirectory() as tmp:
            db = self._db(tmp)
            record_crypto_rejection(db, symbol="SOL", reason="ai_review_declined",
                                    entry_price=150.0, stop_loss=147.75, take_profit=154.5)
            record_crypto_rejection(db, symbol="SOL", reason="fee_hurdle_not_cleared",
                                    entry_price=150.0, stop_loss=147.75, take_profit=154.5)
            self.assertEqual(len(_shadow_rows(db)), 2)

    def test_a_recording_failure_never_breaks_the_decision(self):
        """This is bookkeeping beside a decision already made. It must not be able to throw
        into the middle of a trading cycle."""
        with tempfile.TemporaryDirectory() as tmp:
            # A directory where a database file should be: something sqlite genuinely cannot
            # open. A merely missing folder is created for us, so it proves nothing.
            self.assertFalse(record_crypto_rejection(
                Path(tmp),
                symbol="ADA", reason="ai_review_declined",
                entry_price=1.0, stop_loss=0.985, take_profit=1.03,
            ))

    def test_awkward_evidence_is_carried_rather_than_raising(self):
        evidence = rejection_evidence(fine={"a": 1}, awkward=object(), missing=None)
        self.assertEqual(evidence["fine"], {"a": 1})
        self.assertIsInstance(evidence["awkward"], str)
        self.assertNotIn("missing", evidence)
        json.dumps(evidence)  # must survive the trip into the row


class AgentWiringTests(unittest.TestCase):
    """Every refusal that has a tradeable shape must record one. Asserted on the source
    because the crypto path needs a broker, a model and a database to run for real."""

    def _source(self) -> str:
        return AGENT.read_text(encoding="utf-8")

    def test_the_fee_hurdle_records(self):
        self.assertIn('reason="fee_hurdle_not_cleared"', self._source())

    def test_our_own_track_record_refusal_records(self):
        """The one that can become a doom loop: it only lifts when a coin wins, and a coin
        cannot win while it is being stood aside from."""
        self.assertIn('reason="own_track_record_negative"', self._source())

    def test_the_liquidity_refusal_records(self):
        self.assertIn('reason="liquidity_structure_unfavourable"', self._source())

    def test_both_reviewer_refusals_record(self):
        """83 of 7 September's 271 refusals came from the reviewer -- the biggest single
        source, and the one with no evidence behind it at all."""
        source = self._source()
        self.assertIn('reason="ai_review_declined"', source)
        self.assertIn('reason="ai_review_lowered_confidence_below_minimum"', source)

    def test_every_refusal_records_before_it_moves_on(self):
        """A `continue` before the recording would be a silent no-op that still passes the
        assertions above."""
        source = self._source()
        for call in source.split("record_crypto_rejection(")[1:]:
            block = call[: call.index("continue")] if "continue" in call else call
            self.assertNotIn("\n                continue", block[:40],
                             "the refusal moved on before it was recorded")


class TradeCountLabelTests(unittest.TestCase):
    """"-1.35R across 22 trades" -- a real average wearing the wrong headcount, quoted into
    every refusal the reviewer wrote."""

    def test_the_count_is_the_number_the_average_is_over(self):
        line = StrategyEvidence(
            strategy_id="crypto_trend_following_2r",
            overall_sample=22, overall_r_sample=13,
            overall_expectancy_r=-1.342, overall_basis="real_money",
        ).as_line()
        self.assertIn("-1.34R over 13", line)
        self.assertNotIn("over 22", line, "that is the linked-trade count, not the average's")

    def test_an_unset_r_count_falls_back_rather_than_reading_zero(self):
        """An older caller that has not been updated must read exactly as it did before, not
        suddenly claim every average is over nothing."""
        line = StrategyEvidence(
            strategy_id="s", overall_sample=9, overall_expectancy_r=0.4,
            overall_basis="shadow_simulation",
        ).as_line()
        self.assertIn("over 9", line)

    def test_thinness_is_judged_on_the_real_count(self):
        """Nine trades dressed as twenty would escape the [thin] marker it deserves."""
        line = StrategyEvidence(
            strategy_id="s", coin_sample=20, coin_r_sample=4,
            coin_expectancy_r=-0.5, coin_basis="real_money",
        ).as_line()
        self.assertIn("[thin]", line)

    def test_the_record_reports_both_counts(self):
        from ai_trader.strategy_performance import StrategyRecord

        record = StrategyRecord(
            strategy_id="s", sample_size=22, wins=9, win_rate=0.41, average_r=-1.34,
            expectancy_r=-1.34, net_profit_loss=-5.41, verdict="confident", r_sample_size=13,
        )
        stats = record.to_statistics()
        self.assertEqual(stats["sample_size"], 22)
        self.assertEqual(stats["r_sample_size"], 13)


class CostContextTests(unittest.TestCase):
    """The correction that matters most: the reviewer was shown what trading returned and
    never what it cost."""

    def test_the_note_appears_in_the_prompt_block(self):
        block = serialize_strategy_evidence(
            [StrategyEvidence(strategy_id="s", overall_sample=13, overall_r_sample=13,
                              overall_expectancy_r=-1.34, overall_basis="real_money")],
            cost_note="COST CONTEXT: fees alone have cost 0.97R on the average closed trade.",
        )
        self.assertIn("COST CONTEXT", block)
        self.assertIn("0.97R", block)

    def test_the_note_comes_before_the_records_it_explains(self):
        """Read after the table it is meant to qualify, it is just a footnote."""
        block = serialize_strategy_evidence(
            [StrategyEvidence(strategy_id="only_one", overall_sample=13, overall_r_sample=13,
                              overall_expectancy_r=-1.34, overall_basis="real_money")],
            cost_note="COST CONTEXT: fees.",
        )
        self.assertLess(block.index("COST CONTEXT"), block.index("only_one"))

    def test_without_a_note_the_block_is_exactly_what_it_was(self):
        evidence = [StrategyEvidence(strategy_id="s", overall_sample=4, overall_r_sample=4,
                                     overall_expectancy_r=0.2, overall_basis="real_money")]
        self.assertEqual(serialize_strategy_evidence(evidence),
                         serialize_strategy_evidence(evidence, cost_note=None))

    def test_a_database_with_no_measured_fee_says_nothing(self):
        """Inventing a cost figure would be the same mistake pointed the other way."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(trading_cost_note(Path(tmp) / "empty.sqlite3"))

    def test_the_note_states_the_before_costs_figure(self):
        """"Flat before costs, losing after" is a different instruction from "losing", and
        only one of them is true."""
        import ai_trader.strategy_scoreboard as scoreboard

        original = scoreboard.expectancy_summary
        scoreboard.expectancy_summary = lambda *a, **k: {
            "expectancy_r": -1.342, "average_fee_cost_r": 0.971,
        }
        try:
            note = trading_cost_note(Path("unused.sqlite3"))
        finally:
            scoreboard.expectancy_summary = original
        self.assertIn("0.97R", note)
        self.assertIn("-1.34R after costs", note)
        self.assertIn("-0.37R before", note)

    def test_a_zero_or_missing_fee_reading_says_nothing(self):
        import ai_trader.strategy_scoreboard as scoreboard

        original = scoreboard.expectancy_summary
        try:
            scoreboard.expectancy_summary = lambda *a, **k: {"expectancy_r": -1.0,
                                                             "average_fee_cost_r": None}
            self.assertIsNone(trading_cost_note(Path("unused.sqlite3")))
            scoreboard.expectancy_summary = lambda *a, **k: {"expectancy_r": -1.0,
                                                             "average_fee_cost_r": 0.0}
            self.assertIsNone(trading_cost_note(Path("unused.sqlite3")))
        finally:
            scoreboard.expectancy_summary = original


class PromptWiringTests(unittest.TestCase):
    def test_crypto_candidates_get_the_cost_note(self):
        source = (REPO / "src" / "ai_trader" / "proposal_context.py").read_text(encoding="utf-8")
        self.assertIn("trading_cost_note(db_path)", source)
        self.assertIn("cost_note=cost_note", source)

    def test_equities_do_not_get_krakens_fee(self):
        """Handing an Alpaca candidate Kraken's 1.6% round trip would be the same error this
        fixes, pointed the other way."""
        source = (REPO / "src" / "ai_trader" / "proposal_context.py").read_text(encoding="utf-8")
        self.assertIn('if str(asset_type).lower() == "crypto" else None', source)


if __name__ == "__main__":
    unittest.main()
