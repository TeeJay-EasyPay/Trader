"""Founder-requested cash-based sizing guardrails and the AI capital ledger top-up
(2026-08-20).

Two separate real-money problems, both found by reading LIVE production rather than tests:

1. The Kraken AI capital ledger seeds its opening balance exactly once. It was seeded at
   the GBP 100 default; KRAKEN_TRADING_ALLOCATION_GBP was later raised to GBP 500 and the
   seeded row was never revisited, so every trade was sized off a fifth of the real
   capital. `record_founder_allocation` is the missing top-up writer.
2. There was no cap tied to *available cash* -- only `max_position_size_pct`, a share of
   total equity, which does not tighten as capital gets deployed.

Every test below that concerns sizing asserts the same safety property: the new cap can
only ever REDUCE an approved size, never raise one.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.kraken_reconciliation import (
    initialize_kraken_reconciliation_schema,
    kraken_capital_ledger_summary,
    record_founder_allocation,
)
from ai_trader.technical_discretion import cash_capped_notional


class CashCappedNotionalTests(unittest.TestCase):
    def test_caps_at_the_configured_share_of_available_cash(self):
        capped = cash_capped_notional(
            approved_notional=100.0, available_cash=200.0, max_pct_of_available_cash=0.20,
        )
        self.assertAlmostEqual(capped, 40.0, places=6)

    def test_leaves_a_size_already_inside_the_cap_untouched(self):
        capped = cash_capped_notional(
            approved_notional=10.0, available_cash=500.0, max_pct_of_available_cash=0.20,
        )
        self.assertAlmostEqual(capped, 10.0, places=6, msg="Must not RAISE a size that is already compliant.")

    def test_tightens_as_capital_gets_deployed(self):
        """The whole reason this exists alongside max_position_size_pct.

        A share of equity stays flat as the book fills up; a share of available cash
        correctly shrinks, which is what stops the last trades over-committing.
        """
        early = cash_capped_notional(approved_notional=100.0, available_cash=500.0, max_pct_of_available_cash=0.20)
        late = cash_capped_notional(approved_notional=100.0, available_cash=50.0, max_pct_of_available_cash=0.20)
        self.assertGreater(early, late)
        self.assertAlmostEqual(late, 10.0, places=6)

    def test_absolute_cap_binds_when_it_is_the_tighter_of_the_two(self):
        capped = cash_capped_notional(
            approved_notional=100.0, available_cash=1000.0,
            max_pct_of_available_cash=0.20, max_absolute_gbp=25.0,
        )
        self.assertAlmostEqual(capped, 25.0, places=6)

    def test_zero_absolute_cap_disables_only_the_absolute_cap(self):
        capped = cash_capped_notional(
            approved_notional=100.0, available_cash=200.0,
            max_pct_of_available_cash=0.20, max_absolute_gbp=0.0,
        )
        self.assertAlmostEqual(capped, 40.0, places=6, msg="Percentage cap must still apply when the absolute cap is off.")

    def test_negative_or_zero_cash_caps_at_zero_rather_than_inverting(self):
        for cash in (0.0, -50.0):
            capped = cash_capped_notional(
                approved_notional=100.0, available_cash=cash, max_pct_of_available_cash=0.20,
            )
            self.assertEqual(capped, 0.0, f"Nothing free to deploy must mean zero, not a negative size (cash={cash}).")

    def test_never_increases_an_approved_size_under_any_configuration(self):
        # THE safety property. No combination of inputs may return more than was approved.
        for cash in (0.0, 10.0, 1_000_000.0):
            for pct in (0.0, 0.2, 5.0):
                for absolute in (0.0, 1.0, 10_000.0):
                    capped = cash_capped_notional(
                        approved_notional=50.0, available_cash=cash,
                        max_pct_of_available_cash=pct, max_absolute_gbp=absolute,
                    )
                    self.assertLessEqual(capped, 50.0, f"cash={cash} pct={pct} abs={absolute}")

    def test_a_rejected_zero_allocation_stays_zero(self):
        self.assertEqual(
            cash_capped_notional(approved_notional=0.0, available_cash=500.0, max_pct_of_available_cash=0.20),
            0.0,
        )


class FounderAllocationTopUpTests(unittest.TestCase):
    def test_top_up_raises_both_allocation_and_available_cash(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db_from(tmp)
            before = kraken_capital_ledger_summary(db_path)
            self.assertAlmostEqual(before["allocation_gbp"], 100.0, places=6)

            result = record_founder_allocation(
                db_path, amount_gbp=400.0, reference="founder-topup-2026-08-20", note="raise to 500",
            )
            self.assertEqual(result["status"], "recorded")
            self.assertAlmostEqual(result["previous_allocation_gbp"], 100.0, places=6)
            self.assertAlmostEqual(result["allocation_gbp"], 500.0, places=6)
            # available_cash sums ALL ledger rows, so it must rise by the same amount.
            self.assertAlmostEqual(
                result["available_cash_gbp"] - result["previous_available_cash_gbp"], 400.0, places=6,
            )

    def test_the_original_seeded_deposit_is_preserved_not_rewritten(self):
        """A capital ledger must stay append-only -- the first deposit remains auditable."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db_from(tmp)
            record_founder_allocation(db_path, amount_gbp=400.0, reference="topup-1")
            import sqlite3
            from ai_trader.database import connect
            from contextlib import closing
            with closing(connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT amount_gbp FROM KRAKEN_AI_CAPITAL_LEDGER WHERE idempotency_key = 'kraken-founder-allocation-v1'"
                ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertAlmostEqual(float(rows[0]["amount_gbp"]), 100.0, places=6)

    def test_the_same_reference_cannot_double_credit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db_from(tmp)
            first = record_founder_allocation(db_path, amount_gbp=400.0, reference="same-ref")
            second = record_founder_allocation(db_path, amount_gbp=400.0, reference="same-ref")
            self.assertEqual(first["status"], "recorded")
            self.assertEqual(second["status"], "already_recorded")
            self.assertAlmostEqual(kraken_capital_ledger_summary(db_path)["allocation_gbp"], 500.0, places=6)

    def test_rejects_a_non_positive_amount(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db_from(tmp)
            for amount in (0.0, -100.0):
                result = record_founder_allocation(db_path, amount_gbp=amount, reference=f"bad-{amount}")
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["reason"], "amount_must_be_positive")
            self.assertAlmostEqual(kraken_capital_ledger_summary(db_path)["allocation_gbp"], 100.0, places=6)

    def test_rejects_a_missing_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._db_from(tmp)
            result = record_founder_allocation(db_path, amount_gbp=400.0, reference="   ")
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["reason"], "reference_required")

    def _db_from(self, tmp: str) -> Path:
        db_path = Path(tmp) / "ledger.sqlite3"
        initialize_kraken_reconciliation_schema(db_path, allocation_gbp=100.0)
        return db_path


if __name__ == "__main__":
    unittest.main()
