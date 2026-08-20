import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.kraken_market_data import fetch_kraken_ohlc


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FetchKrakenOhlcTests(unittest.TestCase):
    def test_parses_real_kraken_ohlc_shape_and_drops_the_forming_candle(self):
        # Real Kraken /0/public/OHLC response shape: [time, open, high, low, close, vwap, volume, count].
        payload = {
            "error": [],
            "result": {
                "XXBTZGBP": [
                    [1700000000, "40000.0", "40500.0", "39800.0", "40200.0", "40100.0", "12.5", 300],
                    [1700086400, "40200.0", "41000.0", "40100.0", "40900.0", "40600.0", "15.1", 350],
                    [1700172800, "40900.0", "41200.0", "40850.0", "41050.0", "41000.0", "3.2", 40],  # still-forming, must be dropped
                ],
                "last": 1700172800,
            },
        }
        with patch("ai_trader.kraken_market_data.request.urlopen", return_value=_FakeResponse(payload)):
            candles = fetch_kraken_ohlc("XXBTZGBP", interval_minutes=1440)

        self.assertEqual(len(candles), 2, "The still-forming last candle must be dropped, not treated as settled data.")
        self.assertEqual(candles[0]["open"], "40000.0")
        self.assertEqual(candles[0]["close"], "40200.0")
        self.assertEqual(candles[1]["close"], "40900.0")
        self.assertTrue(candles[0]["observation_time"].startswith("2023-11-14"))

    def test_raises_on_a_real_kraken_error_response(self):
        payload = {"error": ["EQuery:Unknown asset pair"], "result": {}}
        with patch("ai_trader.kraken_market_data.request.urlopen", return_value=_FakeResponse(payload)):
            with self.assertRaises(RuntimeError):
                fetch_kraken_ohlc("NOTAPAIR")

    def test_a_single_row_response_is_entirely_the_forming_candle_and_returns_empty(self):
        payload = {"error": [], "result": {"XXBTZGBP": [[1700172800, "40900.0", "41200.0", "40850.0", "41050.0", "41000.0", "3.2", 40]], "last": 1700172800}}
        with patch("ai_trader.kraken_market_data.request.urlopen", return_value=_FakeResponse(payload)):
            candles = fetch_kraken_ohlc("XXBTZGBP")
        self.assertEqual(candles, [])

    def test_since_parameter_is_included_in_the_request(self):
        payload = {"error": [], "result": {"XXBTZGBP": [], "last": 1700000000}}
        with patch("ai_trader.kraken_market_data.request.urlopen", return_value=_FakeResponse(payload)) as mock_urlopen:
            fetch_kraken_ohlc("XXBTZGBP", since=1700000000)
        called_url = mock_urlopen.call_args[0][0]
        self.assertIn("since=1700000000", called_url)


if __name__ == "__main__":
    unittest.main()
