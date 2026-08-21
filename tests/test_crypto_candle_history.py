import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.cli import _due_worker_jobs, _run_named_job
from ai_trader.config import Settings
from ai_trader.market_intelligence_platform import latest_observation_time, latest_observation_times_batch, record_market_observations
from ai_trader.models import AutoTradeConfig, GuardrailConfig, utc_now_iso


def settings_for(tmp: str, **overrides) -> Settings:
    root = Path(tmp)
    base = Settings(
        alpaca_api_key=None,
        alpaca_secret_key=None,
        alpaca_paper_base_url="https://paper-api.alpaca.markets",
        alpaca_data_base_url="https://data.alpaca.markets",
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
        db_path=root / "audit.sqlite3",
        output_dir=root,
        trading_log_path=root / "TRADING_LOG.md",
        guardrails=GuardrailConfig(),
        auto_trade=AutoTradeConfig(),
        database_backend="sqlite",
    )
    return replace(base, **overrides)


class FakeKrakenAdapter:
    name = "kraken"
    configured = True

    def __init__(self, candles_by_pair: dict[str, list[dict]] | None = None):
        self.candles_by_pair = candles_by_pair or {}
        self.requested_since: dict[str, int | None] = {}

    def get_ohlc_candles(self, pair, *, interval_minutes=1440, since=None):
        self.requested_since[pair] = since
        return self.candles_by_pair.get(pair, [])


def _candle(observation_time: str, close: float) -> dict:
    return {"observation_time": observation_time, "open": close - 1, "high": close + 1, "low": close - 2, "close": close, "volume": 10.0}


class LatestObservationTimeTests(unittest.TestCase):
    def test_returns_none_when_nothing_is_recorded_yet(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            self.assertIsNone(latest_observation_time(db_path, provider="kraken", normalized_symbol="BTC", timeframe="1d"))

    def test_returns_the_most_recent_observation_time_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_market_observations(
                db_path, provider="kraken", original_symbol="XXBTZGBP", normalized_symbol="BTC",
                exchange="KRAKEN", asset_type="crypto", timeframe="1d",
                candles=[_candle("2026-08-18T00:00:00+00:00", 40000.0), _candle("2026-08-19T00:00:00+00:00", 41000.0)],
            )
            self.assertEqual(
                latest_observation_time(db_path, provider="kraken", normalized_symbol="BTC", timeframe="1d"),
                "2026-08-19T00:00:00+00:00",
            )

    def test_is_scoped_to_provider_symbol_and_timeframe(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_market_observations(
                db_path, provider="kraken", original_symbol="XXBTZGBP", normalized_symbol="BTC",
                exchange="KRAKEN", asset_type="crypto", timeframe="1d", candles=[_candle("2026-08-19T00:00:00+00:00", 41000.0)],
            )
            self.assertIsNone(latest_observation_time(db_path, provider="kraken", normalized_symbol="ETH", timeframe="1d"))
            self.assertIsNone(latest_observation_time(db_path, provider="kraken", normalized_symbol="BTC", timeframe="1h"))
            self.assertIsNone(latest_observation_time(db_path, provider="coingecko", normalized_symbol="BTC", timeframe="1d"))


class LatestObservationTimesBatchTests(unittest.TestCase):
    # 2026-08-21 Founder-directed egress audit: refresh_crypto_candle_history used to call
    # the single-symbol latest_observation_time once per symbol in its loop -- with the
    # universe cap removed (up to 30 symbols now, was 10), that meant up to 30 fresh
    # remote-Postgres connections every hour just for watermark lookups. This batched
    # version answers the same question for every symbol on one connection.

    def test_empty_symbol_list_returns_empty_dict_without_touching_the_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            self.assertEqual(
                latest_observation_times_batch(db_path, provider="kraken", normalized_symbols=[], timeframe="1d"),
                {},
            )

    def test_returns_none_for_symbols_with_no_recorded_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            result = latest_observation_times_batch(db_path, provider="kraken", normalized_symbols=["BTC", "ETH"], timeframe="1d")
            self.assertEqual(result, {"BTC": None, "ETH": None})

    def test_matches_the_single_symbol_function_for_a_mix_of_known_and_unknown_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_market_observations(
                db_path, provider="kraken", original_symbol="XXBTZGBP", normalized_symbol="BTC",
                exchange="KRAKEN", asset_type="crypto", timeframe="1d",
                candles=[_candle("2026-08-18T00:00:00+00:00", 40000.0), _candle("2026-08-19T00:00:00+00:00", 41000.0)],
            )
            record_market_observations(
                db_path, provider="kraken", original_symbol="XETHZGBP", normalized_symbol="ETH",
                exchange="KRAKEN", asset_type="crypto", timeframe="1d",
                candles=[_candle("2026-08-17T00:00:00+00:00", 1600.0)],
            )
            result = latest_observation_times_batch(db_path, provider="kraken", normalized_symbols=["BTC", "ETH", "SOL"], timeframe="1d")
            self.assertEqual(
                result,
                {
                    "BTC": latest_observation_time(db_path, provider="kraken", normalized_symbol="BTC", timeframe="1d"),
                    "ETH": latest_observation_time(db_path, provider="kraken", normalized_symbol="ETH", timeframe="1d"),
                    "SOL": None,
                },
            )

    def test_is_scoped_to_provider_and_timeframe_like_the_single_symbol_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_market_observations(
                db_path, provider="kraken", original_symbol="XXBTZGBP", normalized_symbol="BTC",
                exchange="KRAKEN", asset_type="crypto", timeframe="1d", candles=[_candle("2026-08-19T00:00:00+00:00", 41000.0)],
            )
            self.assertEqual(
                latest_observation_times_batch(db_path, provider="kraken", normalized_symbols=["BTC"], timeframe="1h"),
                {"BTC": None},
            )
            self.assertEqual(
                latest_observation_times_batch(db_path, provider="coingecko", normalized_symbols=["BTC"], timeframe="1d"),
                {"BTC": None},
            )


class RefreshCryptoCandleHistoryTests(unittest.TestCase):
    def test_writes_real_candles_for_the_kraken_universe(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            adapter = FakeKrakenAdapter({
                "XBTGBP": [_candle(utc_now_iso(), 41000.0)],
                "ETHGBP": [_candle(utc_now_iso(), 1500.0)],
                "SOLGBP": [_candle(utc_now_iso(), 60.0)],
            })
            service.orchestrator.adapters["kraken"] = adapter

            result = service.refresh_crypto_candle_history()

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["candles_written"], 3)
            self.assertEqual(set(result["symbols_with_history"]), {"BTC", "ETH", "SOL"})
            with closing(sqlite3.connect(settings.db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM MARKET_DATA_OBSERVATIONS WHERE provider = 'kraken'").fetchone()[0]
            self.assertEqual(count, 3)

    def test_watermark_lookup_is_one_call_for_the_whole_universe_not_one_per_symbol(self):
        # 2026-08-21 Founder-directed egress audit: pins the actual regression risk -- the
        # call site, not just the batched function's own correctness (already covered by
        # LatestObservationTimesBatchTests above). With the universe cap removed (up to 30
        # symbols now, was 10), a per-symbol call here would have tripled this refresh's
        # connection count for no benefit every single hour.
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            adapter = FakeKrakenAdapter({
                "XBTGBP": [_candle(utc_now_iso(), 41000.0)],
                "ETHGBP": [_candle(utc_now_iso(), 1500.0)],
                "SOLGBP": [_candle(utc_now_iso(), 60.0)],
            })
            service.orchestrator.adapters["kraken"] = adapter

            with patch(
                "ai_trader.application.research_service.latest_observation_times_batch",
                wraps=latest_observation_times_batch,
            ) as batched_lookup:
                service.refresh_crypto_candle_history()

            batched_lookup.assert_called_once()
            _, kwargs = batched_lookup.call_args
            self.assertEqual(set(kwargs["normalized_symbols"]), {"BTC", "ETH", "SOL"})

    def test_a_second_run_only_fetches_candles_newer_than_what_is_already_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            adapter = FakeKrakenAdapter({
                "XBTGBP": [_candle(utc_now_iso(), 41000.0)],
                "ETHGBP": [_candle(utc_now_iso(), 1500.0)],
                "SOLGBP": [_candle(utc_now_iso(), 60.0)],
            })
            service.orchestrator.adapters["kraken"] = adapter

            service.refresh_crypto_candle_history()
            adapter.candles_by_pair = {"XBTGBP": [], "ETHGBP": [], "SOLGBP": []}  # nothing new since last time
            second = service.refresh_crypto_candle_history()

            self.assertEqual(second["candles_written"], 0)
            self.assertIsNotNone(adapter.requested_since["XBTGBP"], "The second call must pass a real since= cursor, not refetch from scratch.")

    def test_a_kraken_since_boundary_that_returns_the_same_candle_again_is_not_rewritten(self):
        # 2026-08-20 hosted finding: Kraken's `since` boundary is inclusive (or at least
        # not reliably exclusive) -- confirmed live, the same "latest" candle kept coming
        # back and being rewritten forever instead of the refresh ever converging to
        # "nothing new". record_market_observations has no dedup of its own, so this must
        # be filtered by the caller.
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            stamp = utc_now_iso()
            adapter = FakeKrakenAdapter({"XBTGBP": [_candle(stamp, 41000.0)], "ETHGBP": [_candle(stamp, 1500.0)], "SOLGBP": [_candle(stamp, 60.0)]})
            service.orchestrator.adapters["kraken"] = adapter

            first = service.refresh_crypto_candle_history()
            # Simulate Kraken's real inclusive-since behavior: it returns the exact same
            # boundary candle again on the very next call, not an empty result.
            second = service.refresh_crypto_candle_history()

            self.assertEqual(first["candles_written"], 3)
            self.assertEqual(second["candles_written"], 0, "The already-stored boundary candle must be filtered out, not rewritten.")
            with closing(sqlite3.connect(settings.db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM MARKET_DATA_OBSERVATIONS WHERE provider = 'kraken'").fetchone()[0]
            self.assertEqual(count, 3, "No duplicate rows should have been written on the second call.")

    def test_blocked_without_kraken_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            result = service.refresh_crypto_candle_history()
            self.assertEqual(result["status"], "not_available")

    def test_one_pairs_fetch_failure_does_not_block_the_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)

            class FlakyAdapter(FakeKrakenAdapter):
                def get_ohlc_candles(self, pair, *, interval_minutes=1440, since=None):
                    if pair == "XBTGBP":
                        raise RuntimeError("network timeout")
                    return super().get_ohlc_candles(pair, interval_minutes=interval_minutes, since=since)

            adapter = FlakyAdapter({"ETHGBP": [_candle(utc_now_iso(), 1500.0)], "SOLGBP": [_candle(utc_now_iso(), 60.0)]})
            service.orchestrator.adapters["kraken"] = adapter

            result = service.refresh_crypto_candle_history()

            self.assertEqual(result["candles_written"], 2)
            self.assertEqual(set(result["symbols_with_history"]), {"ETH", "SOL"})
            self.assertEqual(len(result["quality_issues"]), 1)
            self.assertEqual(result["quality_issues"][0]["symbol"], "BTC")

    def test_run_named_job_dispatches_crypto_candle_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            service.orchestrator.adapters["kraken"] = FakeKrakenAdapter()

            result = _run_named_job(service, "crypto-candle-refresh", limit=0)

            self.assertIn(result["status"], {"completed", "not_available"})

    def test_due_worker_jobs_includes_crypto_candle_refresh_every_hour_including_weekends(self):
        settings = settings_for(tempfile.mkdtemp())
        saturday = datetime(2026, 8, 22, 12, 0, tzinfo=ZoneInfo("UTC"))
        due = _due_worker_jobs(settings, now=saturday)
        self.assertIn("crypto-candle-refresh", [name for name, _ in due])


if __name__ == "__main__":
    unittest.main()
