"""Why a position ended must be recorded, and must never be dressed up as more than it is.

2026-09-06, Founder-reported: he asked the app why it sold XRP at a loss and it could only
answer that no exit trigger was documented. It genuinely did not know.

The cause was narrow. When this system places the closing order it records the reason at that
moment. But a stop can rest AT KRAKEN from the moment the position opens and fill hours later
with nothing here watching; reconciliation then finds the position gone, marks it closed, and
recorded no reason at all. Measured: 15 of 28 closed managed exits, and 40 of 67 Kraken
attribution rows.

The real XRP numbers are used below on purpose, so a future reader can check the sentence
against the trade that prompted it.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.trade_reasons import infer_exit_reason

# XRP, opened 2026-09-05 01:31 UTC, closed 23:38 UTC at a 33p net loss.
XRP = dict(entry_price=1.03547, stop_loss=0.98848969, take_profit=1.24565, side="buy")
NATIVE_STOP_ID = "OYYFKT-3JDLB-WAV3IM"


class ExitReasonCertaintyTests(unittest.TestCase):
    def test_the_native_stop_filling_is_stated_as_fact_not_inference(self):
        """Identity, not deduction: the order that filled IS the stop we placed."""
        reason = infer_exit_reason(
            exit_price=1.04, native_stop_order_id=NATIVE_STOP_ID,
            filled_exit_order_id=NATIVE_STOP_ID, **XRP
        )
        self.assertIn("resting at Kraken", reason)
        self.assertNotIn("inferred", reason)

    def test_a_price_based_call_says_it_is_inferred(self):
        for price, expect in ((0.97, "Stop loss"), (1.30, "Target reached")):
            reason = infer_exit_reason(exit_price=price, **XRP)
            self.assertIn(expect, reason)
            self.assertIn("inferred from the fill price", reason,
                          "a deduction must never read like a recorded fact")

    def test_the_real_xrp_exit_is_honest_when_nothing_identifies_it(self):
        """Without the order-id match, 1.04 sits between stop and target: say exactly that,
        with the numbers, rather than inventing a trigger."""
        reason = infer_exit_reason(exit_price=1.04, **XRP)
        self.assertIn("Exit trigger not recorded", reason)
        self.assertIn("neither of them fired", reason)
        self.assertIn("0.98849", reason)
        self.assertIn("1.24565", reason)

    def test_a_different_order_filling_is_not_credited_to_the_native_stop(self):
        reason = infer_exit_reason(
            exit_price=1.04, native_stop_order_id=NATIVE_STOP_ID,
            filled_exit_order_id="SOMETHING-ELSE", **XRP
        )
        self.assertNotIn("resting at Kraken", reason)

    def test_nothing_is_said_when_nothing_is_known(self):
        """A blank is better than a sentence that carries no information."""
        self.assertIsNone(infer_exit_reason(exit_price=1.04, stop_loss=None, take_profit=None))
        self.assertIsNone(infer_exit_reason(exit_price=None, stop_loss=0.9, take_profit=1.2))

    def test_a_short_position_reads_the_levels_the_other_way_round(self):
        short = dict(entry_price=100.0, stop_loss=110.0, take_profit=80.0, side="sell")
        self.assertIn("Stop loss", infer_exit_reason(exit_price=112.0, **short))
        self.assertIn("Target reached", infer_exit_reason(exit_price=78.0, **short))


if __name__ == "__main__":
    unittest.main()
