"""2026-08-23: three Kraken trades landed at GBP 6.03, GBP 25.00 and GBP 3.86 within two
hours. CAPITAL_ALLOCATION_HISTORY already recorded the account_equity, requested_notional
and approved_notional behind each, but nothing exposed it -- so explaining the differences
meant reconstructing arithmetic from qty x entry_price and guessing which limb of the min()
had bound. Same "cannot see the live value" problem that hid four inert settings the day
before.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.foundation import calculate_capital_allocation, list_capital_allocations, load_trading_policy
from ai_trader.models import AutoTradeConfig, GuardrailConfig, TradeProposal


def proposal(symbol="XLM", entry=0.144, stop=0.14184, size=347.0):
    return TradeProposal(
        symbol=symbol, side="buy", entry_price=entry, stop_loss=stop,
        take_profit=entry * 1.12, position_size=size, risk_percentage=0.01,
        confidence_score=1.0, news_summary="x", market_sentiment_summary="x",
        technical_summary="x", plain_english_reasoning="x",
        asset_type="crypto", exchange="KRAKEN",
    )


class CapitalAllocationVisibilityTests(unittest.TestCase):
    def _allocate(self, db_path, item, equity):
        policy = load_trading_policy(db_path, auto_trade=AutoTradeConfig(), guardrails=GuardrailConfig())
        return calculate_capital_allocation(db_path, item, policy, account_equity=equity, available_cash=equity)

    def test_a_sizing_decision_is_readable_afterwards(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            self._allocate(db_path, proposal(), equity=500.0)

            rows = list_capital_allocations(db_path)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            for field in ("account_equity", "requested_notional", "approved_notional", "approved_quantity", "symbol"):
                self.assertIn(field, row, f"{field} is what makes an odd trade size explainable")
            self.assertEqual(row["account_equity"], 500.0)

    def test_it_exposes_the_share_of_capital_the_trade_actually_took(self):
        """The percentage is the figure the ceilings are expressed in, so it is the one that
        makes 'why GBP 25 and not GBP 50' answerable at a glance."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            self._allocate(db_path, proposal(), equity=500.0)
            row = list_capital_allocations(db_path)[0]
            expected = row["approved_notional"] / 500.0
            self.assertAlmostEqual(row["approved_pct_of_equity"], round(expected, 6), places=6)

    def test_the_policy_ceilings_in_force_are_decoded_not_raw_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            self._allocate(db_path, proposal(), equity=500.0)
            row = list_capital_allocations(db_path)[0]
            self.assertNotIn("policy_snapshot_json", row, "Raw JSON string is not readable evidence.")
            self.assertIsInstance(row["policy_snapshot"], dict)

    def test_the_two_real_equity_values_produce_visibly_different_records(self):
        """The GBP 100 vs GBP 500 allocation bug, made diagnosable: same proposal, different
        equity, and the record shows exactly which one was in force."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            self._allocate(db_path, proposal(symbol="AAA"), equity=100.0)
            self._allocate(db_path, proposal(symbol="BBB"), equity=500.0)

            by_symbol = {r["symbol"]: r for r in list_capital_allocations(db_path)}
            self.assertEqual(by_symbol["AAA"]["account_equity"], 100.0)
            self.assertEqual(by_symbol["BBB"]["account_equity"], 500.0)
            self.assertGreater(by_symbol["BBB"]["approved_notional"], by_symbol["AAA"]["approved_notional"])

    def test_it_can_be_filtered_by_symbol_and_is_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            self._allocate(db_path, proposal(symbol="LTC", entry=38.5686, stop=37.9901, size=1.0), equity=500.0)
            self._allocate(db_path, proposal(symbol="XLM"), equity=500.0)

            only_ltc = list_capital_allocations(db_path, symbol="ltc")
            self.assertEqual([r["symbol"] for r in only_ltc], ["LTC"], "Filter must be case-insensitive.")
            self.assertEqual(list_capital_allocations(db_path)[0]["symbol"], "XLM", "Newest first.")

    def test_an_empty_history_returns_an_empty_list_rather_than_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(list_capital_allocations(Path(tmp) / "audit.sqlite3"), [])


if __name__ == "__main__":
    unittest.main()
