"""2026-08-26 audit finding: the crypto universe bootstrap was fabricating research.

_bootstrap_crypto_universe_from_kraken_permissions exists to seed the UNIVERSE -- which
coins are worth looking at. It was also writing a research score per symbol, with invented
identical values: trend 0.62, momentum 0.6, risk 0.72, and confidence_score set to
max(min_confidence, 0.85) -- exactly the auto-trade threshold, so a coin with no data at all
sat precisely at the bar for trading real money.

Measured on production: 1,074 such rows against 31 genuine CoinGecko rows in one day, 97% of
the day's "research", with 32 distinct score combinations across 32 symbols. That is why the
funnel reported "19 assets examined, 0 interesting ideas" every hour -- no coin could look
different from any other because the numbers were the same numbers.

And this is not an emergency path: it is the default symbol source for every scheduled cycle.
Since every reader takes the newest score row per symbol, hourly placeholders permanently
shadowed the twice-daily real market data underneath them.
"""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.config import Settings
from ai_trader.models import GuardrailConfig
from ai_trader.multi_broker import record_crypto_research_score


def settings_for(tmp):
    root = Path(tmp)
    return Settings(
        alpaca_api_key=None, alpaca_secret_key=None,
        alpaca_paper_base_url="https://paper-api.alpaca.markets",
        alpaca_data_base_url="https://data.alpaca.markets",
        openai_api_key=None, openai_model="gpt-4.1-mini",
        db_path=root / "audit.sqlite3", output_dir=root,
        trading_log_path=root / "TRADING_LOG.md", guardrails=GuardrailConfig(),
    )


class UniverseBootstrapTests(unittest.TestCase):
    def test_seeding_the_universe_writes_no_research_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            with mock.patch.dict("os.environ", {"KRAKEN_ALLOWED_PAIRS": "XBTGBP,ETHGBP,SOLGBP"}):
                symbols = service._research_service._bootstrap_crypto_universe_from_kraken_permissions(limit=10)

            self.assertEqual(sorted(symbols), ["BTC", "ETH", "SOL"], "the universe must still be seeded")
            with closing(sqlite3.connect(settings.db_path)) as conn:
                scores = conn.execute("SELECT count(*) FROM CRYPTO_RESEARCH_SCORES").fetchone()[0]
                universe = conn.execute("SELECT count(*) FROM CRYPTO_MASTER WHERE active = 1").fetchone()[0]

            self.assertEqual(scores, 0, "seeding the universe must not invent research about it")
            self.assertEqual(universe, 3)

    def test_a_real_score_is_not_shadowed_by_a_later_bootstrap(self):
        """The reason None was not good enough: every reader takes the newest row per symbol,
        so ANY row written hourly hides the real measurement underneath it."""
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            record_crypto_research_score(
                settings.db_path, symbol="BTC", category="crypto",
                source="CoinGecko public markets API",
                metrics={"technical_trend_score": 0.91, "momentum_score": 0.88, "confidence_score": 0.9,
                         "reasoning": {"source": "CoinGecko public markets API"}},
            )
            with mock.patch.dict("os.environ", {"KRAKEN_ALLOWED_PAIRS": "XBTGBP"}):
                service._research_service._bootstrap_crypto_universe_from_kraken_permissions(limit=10)

            with closing(sqlite3.connect(settings.db_path)) as conn:
                row = conn.execute(
                    "SELECT source, technical_trend_score FROM CRYPTO_RESEARCH_SCORES "
                    "WHERE symbol='BTC' ORDER BY score_id DESC LIMIT 1"
                ).fetchone()

            self.assertEqual(row[0], "CoinGecko public markets API",
                             "the newest score for a coin must be its last real measurement")
            self.assertAlmostEqual(row[1], 0.91)


if __name__ == "__main__":
    unittest.main()
