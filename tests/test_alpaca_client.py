import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.alpaca import AlpacaCredentials, AlpacaPaperClient, AlpacaError


def _fake_response(payload: dict) -> BytesIO:
    body = json.dumps(payload).encode("utf-8")

    class _Resp(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    resp = _Resp(body)
    return resp


class AlpacaDailyBarsTests(unittest.TestCase):
    def _client(self) -> AlpacaPaperClient:
        return AlpacaPaperClient(
            AlpacaCredentials(
                api_key="key",
                secret_key="secret",
                base_url="https://paper-api.alpaca.markets",
                data_base_url="https://data.alpaca.markets",
            )
        )

    def test_get_daily_bars_requests_one_symbol_at_a_time_and_returns_bars(self):
        client = self._client()
        calls: list[str] = []

        def fake_urlopen(request, timeout=20):
            calls.append(request.full_url)
            symbol = request.full_url.split("/v2/stocks/")[1].split("/bars")[0]
            return _fake_response({"bars": [{"t": "2026-07-01T00:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100}], "symbol": symbol})

        with patch("ai_trader.alpaca.urlopen", side_effect=fake_urlopen):
            result = client.get_daily_bars(["AAPL", "MSFT"], days=30)

        self.assertEqual(len(calls), 2)
        self.assertIn("AAPL", calls[0])
        self.assertIn("MSFT", calls[1])
        self.assertEqual(set(result["bars"].keys()), {"AAPL", "MSFT"})
        self.assertEqual(result["bars"]["AAPL"][0]["c"], 1.5)
        self.assertEqual(result["unavailable_symbols"], [])

    def test_get_daily_bars_skips_unavailable_symbol_without_failing_the_batch(self):
        client = self._client()

        def fake_urlopen(request, timeout=20):
            if "BADSYM" in request.full_url:
                raise __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
                    request.full_url, 404, "asset not found", {}, BytesIO(b'{"message": "asset not found"}')
                )
            return _fake_response({"bars": [{"t": "2026-07-01T00:00:00Z", "c": 10}]})

        with patch("ai_trader.alpaca.urlopen", side_effect=fake_urlopen):
            result = client.get_daily_bars(["AAPL", "BADSYM"], days=30)

        self.assertEqual(list(result["bars"].keys()), ["AAPL"])
        self.assertEqual(result["unavailable_symbols"], ["BADSYM"])

    def test_get_daily_bars_skips_symbol_rejected_with_a_different_error_phrasing(self):
        """Alpaca doesn't only say "asset not found" -- a foreign share class like
        NOVO-B came back as 400 "invalid symbol: NOVO-B", which previously fell
        through the narrow message-matching and crashed the whole batch (and with
        it, strategy-lab-refresh, silently, for 3+ consecutive days). Any per-symbol
        failure here must be isolated, not just the one phrasing seen first."""

        client = self._client()

        def fake_urlopen(request, timeout=20):
            if "NOVO-B" in request.full_url:
                raise __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
                    request.full_url, 400, "invalid symbol: NOVO-B", {}, BytesIO(b'{"message": "invalid symbol: NOVO-B"}')
                )
            return _fake_response({"bars": [{"t": "2026-07-01T00:00:00Z", "c": 10}]})

        with patch("ai_trader.alpaca.urlopen", side_effect=fake_urlopen):
            result = client.get_daily_bars(["AAPL", "NOVO-B"], days=30)

        self.assertEqual(list(result["bars"].keys()), ["AAPL"])
        self.assertEqual(result["unavailable_symbols"], ["NOVO-B"])


if __name__ == "__main__":
    unittest.main()
