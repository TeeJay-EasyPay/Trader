import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.application.shared_helpers import (
    _broker_label,
    _broker_trade_payload,
    _broker_trade_symbol,
    _csv_env,
    _estimated_in_positions,
    _int_or_default,
    _money_text,
)


class SharedHelpersTests(unittest.TestCase):
    def test_broker_label_maps_known_brokers(self):
        self.assertEqual(_broker_label("alpaca"), "Alpaca")
        self.assertEqual(_broker_label("kraken"), "Kraken")

    def test_broker_label_title_cases_unknown_brokers(self):
        self.assertEqual(_broker_label("some_new_broker"), "Some New Broker")

    def test_money_text_formats_a_number(self):
        self.assertEqual(_money_text(1234.5), "1,234.50")

    def test_money_text_handles_none(self):
        self.assertEqual(_money_text(None), "Not available")

    def test_estimated_in_positions_subtracts_cash_from_portfolio(self):
        self.assertEqual(_estimated_in_positions(1000, 400), 600)

    def test_estimated_in_positions_returns_none_when_either_value_missing(self):
        self.assertIsNone(_estimated_in_positions(None, 400))
        self.assertIsNone(_estimated_in_positions(1000, None))

    def test_broker_trade_payload_parses_json(self):
        row = {"payload_json": '{"symbol": "BTC"}'}
        self.assertEqual(_broker_trade_payload(row), {"symbol": "BTC"})

    def test_broker_trade_payload_returns_empty_dict_on_invalid_json(self):
        self.assertEqual(_broker_trade_payload({"payload_json": "not json"}), {})
        self.assertEqual(_broker_trade_payload({}), {})

    def test_broker_trade_symbol_prefers_the_row_symbol(self):
        row = {"symbol": "eth", "payload_json": '{"symbol": "BTC"}'}
        self.assertEqual(_broker_trade_symbol(row), "ETH")

    def test_broker_trade_symbol_falls_back_to_payload_pair(self):
        row = {"payload_json": '{"pair": "xbtgbp"}'}
        self.assertEqual(_broker_trade_symbol(row), "XBTGBP")

    def test_int_or_default_parses_valid_ints(self):
        self.assertEqual(_int_or_default("42", 0), 42)

    def test_int_or_default_falls_back_on_invalid_input(self):
        self.assertEqual(_int_or_default("not a number", 7), 7)
        self.assertEqual(_int_or_default(None, 7), 7)

    def test_csv_env_splits_and_uppercases(self):
        previous = os.environ.get("__TEST_CSV_ENV__")
        try:
            os.environ["__TEST_CSV_ENV__"] = "btcgbp, ethgbp ,solgbp"
            self.assertEqual(_csv_env("__TEST_CSV_ENV__", ""), ["BTCGBP", "ETHGBP", "SOLGBP"])
        finally:
            if previous is None:
                os.environ.pop("__TEST_CSV_ENV__", None)
            else:
                os.environ["__TEST_CSV_ENV__"] = previous

    def test_csv_env_uses_default_when_unset(self):
        previous = os.environ.pop("__TEST_CSV_ENV_UNSET__", None)
        try:
            self.assertEqual(_csv_env("__TEST_CSV_ENV_UNSET__", "xbtgbp"), ["XBTGBP"])
        finally:
            if previous is not None:
                os.environ["__TEST_CSV_ENV_UNSET__"] = previous


if __name__ == "__main__":
    unittest.main()
