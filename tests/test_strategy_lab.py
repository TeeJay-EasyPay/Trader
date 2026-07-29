import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.cli import _due_worker_jobs, _run_named_job
from ai_trader.config import Settings
from ai_trader.models import AutoTradeConfig, GuardrailConfig
from ai_trader.trading_intelligence import STRATEGIES
from datetime import datetime
from zoneinfo import ZoneInfo


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


def _seed_company(db_path: Path, ticker: str) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO COMPANY_MASTER (company_name, ticker, exchange, sector, industry, last_updated, created_at, updated_at)
                VALUES (?, ?, 'NASDAQ', 'Technology', 'Software', datetime('now'), datetime('now'), datetime('now'))
                """,
                (ticker, ticker),
            )


class FakeAlpacaBars:
    def __init__(self, symbols: list[str], days: int = 60):
        self.symbols = symbols
        self.days = days

    def get_daily_bars(self, symbols, *, days=120):
        bars = {}
        for symbol in symbols:
            price = 100.0
            series = []
            for i in range(self.days):
                # A mild uptrend with oscillation so some strategies can find signals.
                price += 0.4 if i % 5 else -0.8
                series.append({
                    "t": f"2026-{(i // 28) + 4:02d}-{(i % 28) + 1:02d}T00:00:00Z",
                    "o": price - 0.3,
                    "h": price + 0.5,
                    "l": price - 0.5,
                    "c": price,
                    "v": 1_000_000,
                })
            bars[symbol] = series
        return {"bars": bars, "unavailable_symbols": []}


class StrategyLabTests(unittest.TestCase):
    def test_refresh_strategy_lab_ingests_candles_and_evaluates_every_stock_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp, alpaca_api_key="key", alpaca_secret_key="secret")
            service = LocalApiService(settings)
            _seed_company(settings.db_path, "AAPL")
            _seed_company(settings.db_path, "MSFT")
            service._broker = lambda: FakeAlpacaBars(["AAPL", "MSFT"])

            result = service.refresh_strategy_lab()

            self.assertEqual(result["status"], "completed")
            self.assertGreater(result["candles_written"], 0)
            self.assertEqual(set(result["symbols_with_history"]), {"AAPL", "MSFT"})
            stock_strategy_count = sum(1 for definition in STRATEGIES.values() if "stock" in definition["supported_assets"])
            self.assertEqual(result["strategies_evaluated"], stock_strategy_count)
            for item in result["strategy_results"]:
                maturity = item["maturity"]
                self.assertIn(maturity["status"], {"evaluated", "pending_founder_approval"})
                # No strategy should silently jump to real-capital entitlement from this job alone:
                # an *applied* stage change (stage_changed=True) must never land on Micro Live/Production.
                if maturity.get("stage_changed"):
                    self.assertNotIn(maturity["promotion"]["proposed_stage"], {"Micro Live", "Production"})

            with closing(sqlite3.connect(settings.db_path)) as conn:
                candle_count = conn.execute("SELECT COUNT(*) FROM HISTORICAL_CANDLES").fetchone()[0]
            self.assertGreater(candle_count, 0)

    def test_refresh_strategy_lab_blocked_without_alpaca_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            result = service.refresh_strategy_lab()
            self.assertEqual(result["status"], "not_available")

    def test_run_named_job_dispatches_strategy_lab_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp, alpaca_api_key="key", alpaca_secret_key="secret")
            service = LocalApiService(settings)
            service._broker = lambda: FakeAlpacaBars(["AAPL"])
            _seed_company(settings.db_path, "AAPL")

            result = _run_named_job(service, "strategy-lab-refresh", limit=0)
            self.assertEqual(result["status"], "completed")

    def test_due_worker_jobs_includes_strategy_lab_refresh_after_market_close(self):
        settings = settings_for(tempfile.mkdtemp())
        weekday_after_close = datetime(2026, 7, 29, 21, 45, tzinfo=ZoneInfo("UTC"))  # 17:45 America/New_York
        due = _due_worker_jobs(settings, now=weekday_after_close)
        self.assertIn("strategy-lab-refresh", [name for name, _ in due])


if __name__ == "__main__":
    unittest.main()
