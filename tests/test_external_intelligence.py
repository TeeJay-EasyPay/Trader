import sys
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.config import Settings
from ai_trader.database import connect
from ai_trader.external_intelligence import (
    derive_macro_signal,
    fetch_alpaca_equities_news,
    fetch_cryptopanic_news,
    fetch_fred_series,
    record_crypto_news,
    record_fundamental_evidence,
    record_macro_event_evidence,
    record_market_regime_evidence,
    record_multi_timeframe_intelligence,
    record_news_catalyst_evidence,
    run_external_intelligence_refresh,
)
from ai_trader.intelligence import InvestmentIntelligenceDatabase
from ai_trader.market_intelligence_platform import multi_timeframe_conclusion
from ai_trader.models import AutoTradeConfig, GuardrailConfig, utc_now_iso


def _settings(tmp: str, **overrides) -> Settings:
    root = Path(tmp)
    base = dict(
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
        external_intelligence_enabled=False,
        cryptopanic_api_key=None,
        fred_api_key=None,
    )
    base.update(overrides)
    return Settings(**base)


def _fake_response(payload: dict) -> BytesIO:
    import json

    body = json.dumps(payload).encode("utf-8")

    class _Resp(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return _Resp(body)


class ExternalIntelligenceWriterTests(unittest.TestCase):
    """Each writer inserts a correctly-shaped row into its real table -- columns
    verified against the actual CREATE TABLE statements in foundation.py and
    market_intelligence_platform.py, not assumed."""

    def test_record_crypto_news_inserts_row_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            post = {
                "title": "Bitcoin rallies on ETF inflows",
                "url": "https://cryptopanic.com/news/12345/bitcoin-rallies",
                "published_at": "2026-08-05T10:00:00Z",
                "body": "Bitcoin gained 5% today.",
                "currencies": [{"code": "btc"}],
            }
            result = record_crypto_news(db_path, posts=[post], source="CryptoPanic")
            self.assertEqual(result["inserted"], 1)
            with closing(connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT symbol, title, url, source, published_at, summary FROM CRYPTO_NEWS"
                ).fetchone()
            self.assertEqual(row[0], "BTC")
            self.assertEqual(row[1], post["title"])
            self.assertEqual(row[2], post["url"])
            self.assertEqual(row[3], "CryptoPanic")
            self.assertEqual(row[4], post["published_at"])
            self.assertEqual(row[5], post["body"])

            # Re-fetching the exact same article is a genuine no-op.
            repeat = record_crypto_news(db_path, posts=[post], source="CryptoPanic")
            self.assertEqual(repeat["inserted"], 0)
            self.assertEqual(repeat["skipped_duplicates"], 1)
            with closing(connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM CRYPTO_NEWS").fetchone()[0]
            self.assertEqual(count, 1)

    def test_record_crypto_news_falls_back_to_market_symbol_when_untagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            post = {"title": "General crypto market update", "url": "https://cryptopanic.com/news/1"}
            record_crypto_news(db_path, posts=[post])
            with closing(connect(db_path)) as conn:
                symbol = conn.execute("SELECT symbol FROM CRYPTO_NEWS").fetchone()[0]
            self.assertEqual(symbol, "MARKET")

    def test_record_news_catalyst_evidence_inserts_row_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            article = {
                "id": 555666,
                "headline": "Company X beats earnings",
                "summary": "Detailed quarterly summary.",
                "created_at": "2026-08-05T09:30:00Z",
                "symbols": ["AAPL"],
            }
            result = record_news_catalyst_evidence(db_path, articles=[article])
            self.assertEqual(result["inserted"], 1)
            with closing(connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT normalized_symbol, source, source_timestamp, credibility_level, "
                    "catalyst_type, confirmed_fact, market_commentary, cluster_key FROM NEWS_CATALYST_EVIDENCE"
                ).fetchone()
            self.assertEqual(row[0], "AAPL")
            self.assertEqual(row[1], "Alpaca news API")
            self.assertEqual(row[2], article["created_at"])
            self.assertEqual(row[3], "wire_source")
            self.assertEqual(row[4], "news_article")
            self.assertEqual(row[5], article["headline"])
            self.assertEqual(row[6], article["summary"])
            self.assertEqual(row[7], "alpaca-news-555666")

            repeat = record_news_catalyst_evidence(db_path, articles=[article])
            self.assertEqual(repeat["inserted"], 0)
            with closing(connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM NEWS_CATALYST_EVIDENCE").fetchone()[0]
            self.assertEqual(count, 1)

    def test_record_macro_event_evidence_inserts_row_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            series_observations = {"FEDFUNDS": [{"date": "2026-07-01", "value": "5.25"}]}
            result = record_macro_event_evidence(db_path, series_observations=series_observations)
            self.assertEqual(result["inserted"], 1)
            with closing(connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT event_type, affected_asset, event_time, uncertainty_level, source, potential_impact "
                    "FROM MACRO_EVENT_EVIDENCE"
                ).fetchone()
            self.assertEqual(row[0], "FEDFUNDS")
            self.assertEqual(row[1], "ALL")
            self.assertEqual(row[2], "2026-07-01")
            self.assertEqual(row[3], "low")
            self.assertEqual(row[4], "FRED")
            self.assertIn("5.25", row[5])

            repeat = record_macro_event_evidence(db_path, series_observations=series_observations)
            self.assertEqual(repeat["inserted"], 0)
            with closing(connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM MACRO_EVENT_EVIDENCE").fetchone()[0]
            self.assertEqual(count, 1)

    def test_record_fundamental_evidence_inserts_row_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            filing = {"_source": {"form": "10-Q", "file_date": "2026-07-15"}}
            result = record_fundamental_evidence(db_path, normalized_symbol="aapl", filings=[filing])
            self.assertEqual(result["inserted"], 1)
            with closing(connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT normalized_symbol, source, metric_name, metric_value, source_timestamp, confidence "
                    "FROM FUNDAMENTAL_EVIDENCE"
                ).fetchone()
            self.assertEqual(row[0], "AAPL")
            self.assertEqual(row[1], "SEC EDGAR full-text search")
            self.assertEqual(row[2], "sec_filing")
            self.assertEqual(row[3], "10-Q")
            self.assertEqual(row[4], "2026-07-15")
            self.assertEqual(row[5], "high")

            repeat = record_fundamental_evidence(db_path, normalized_symbol="AAPL", filings=[filing])
            self.assertEqual(repeat["inserted"], 0)
            with closing(connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM FUNDAMENTAL_EVIDENCE").fetchone()[0]
            self.assertEqual(count, 1)

    def test_record_market_regime_evidence_uses_real_regime_math(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            multi_timeframe = multi_timeframe_conclusion(
                {"1h": {"trend": "up", "momentum": "steady", "data_quality": "pass"}}
            )
            regime = record_market_regime_evidence(
                db_path, scope="global", multi_timeframe=multi_timeframe, macro="supportive"
            )
            self.assertEqual(regime["primary_regime"], "Strong upward trend")
            with closing(connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT scope, primary_regime, confidence, plain_english, supporting_evidence_json "
                    "FROM MARKET_REGIME_EVIDENCE"
                ).fetchone()
            self.assertEqual(row[0], "global")
            self.assertEqual(row[1], "Strong upward trend")
            self.assertEqual(row[2], regime["confidence"])
            self.assertEqual(row[3], regime["plain_english"])
            self.assertIn("Macro backdrop is supportive.", row[4])

    def test_record_multi_timeframe_intelligence_uses_real_conclusion_math(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            timeframes = {
                "1h": {"trend": "up", "momentum": "steady", "data_quality": "pass"},
                "1d": {"trend": "down", "momentum": "weakening", "data_quality": "warn"},
            }
            conclusion = record_multi_timeframe_intelligence(
                db_path, normalized_symbol="btc", asset_type="crypto", timeframes=timeframes
            )
            self.assertEqual(
                conclusion["conclusion"],
                "Timeframes disagree: longer or shorter horizons are not pointing the same way.",
            )
            with closing(connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT normalized_symbol, asset_type, conclusion FROM MULTI_TIMEFRAME_INTELLIGENCE"
                ).fetchone()
            self.assertEqual(row[0], "BTC")
            self.assertEqual(row[1], "crypto")
            self.assertEqual(row[2], conclusion["conclusion"])


class ExternalIntelligenceFetcherSkipTests(unittest.TestCase):
    """Missing an optional API key is a clean skip, never an error."""

    def test_fetch_cryptopanic_news_skips_without_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = _settings(tmp, cryptopanic_api_key=None)

            def fail_urlopen(*args, **kwargs):
                raise AssertionError("must not call urlopen without CRYPTOPANIC_API_KEY configured")

            with patch("ai_trader.external_intelligence.urlopen", side_effect=fail_urlopen):
                self.assertEqual(fetch_cryptopanic_news(settings), [])

    def test_fetch_fred_series_skips_without_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = _settings(tmp, fred_api_key=None)

            def fail_urlopen(*args, **kwargs):
                raise AssertionError("must not call urlopen without FRED_API_KEY configured")

            with patch("ai_trader.external_intelligence.urlopen", side_effect=fail_urlopen):
                self.assertEqual(fetch_fred_series(settings), {})

    def test_fetch_alpaca_equities_news_skips_without_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = _settings(tmp, alpaca_api_key=None, alpaca_secret_key=None)

            def fail_urlopen(*args, **kwargs):
                raise AssertionError("must not call urlopen without Alpaca credentials configured")

            with patch("ai_trader.external_intelligence.urlopen", side_effect=fail_urlopen):
                self.assertEqual(fetch_alpaca_equities_news(settings), [])

    def test_fetch_cryptopanic_news_returns_empty_list_on_http_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = _settings(tmp, cryptopanic_api_key="cp-key")

            def raising_urlopen(*args, **kwargs):
                raise URLError("network unreachable")

            with patch("ai_trader.external_intelligence.urlopen", side_effect=raising_urlopen):
                self.assertEqual(fetch_cryptopanic_news(settings), [])


class DeriveMacroSignalTests(unittest.TestCase):
    def test_rate_cut_is_supportive(self):
        self.assertEqual(
            derive_macro_signal({"FEDFUNDS": [{"value": "5.00"}, {"value": "5.25"}]}),
            "supportive",
        )

    def test_rate_hike_is_hostile(self):
        self.assertEqual(
            derive_macro_signal({"FEDFUNDS": [{"value": "5.50"}, {"value": "5.25"}]}),
            "hostile",
        )

    def test_missing_data_is_unknown(self):
        self.assertEqual(derive_macro_signal({}), "unknown")
        self.assertEqual(derive_macro_signal({"FEDFUNDS": [{"value": "5.25"}]}), "unknown")


class ExternalIntelligenceScheduledJobTests(unittest.TestCase):
    def test_master_flag_disabled_is_a_true_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            settings = _settings(
                tmp,
                external_intelligence_enabled=False,
                alpaca_api_key="key",
                alpaca_secret_key="secret",
                cryptopanic_api_key="cp-key",
                fred_api_key="fred-key",
            )

            def fail_urlopen(*args, **kwargs):
                raise AssertionError("urlopen must never be called while external_intelligence_enabled is False")

            with patch("ai_trader.external_intelligence.urlopen", side_effect=fail_urlopen):
                result = run_external_intelligence_refresh(db_path, settings)

            self.assertEqual(result["status"], "disabled")
            # No schema was ever created and no file was ever written -- confirms
            # this is a true no-op, not merely "wrote nothing while touching the db".
            self.assertFalse(db_path.exists())

    def test_partial_source_failure_does_not_block_other_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            intel_db = InvestmentIntelligenceDatabase(db_path)
            now = utc_now_iso()
            with closing(intel_db.connect()) as conn:
                with conn:
                    conn.execute(
                        "INSERT INTO COMPANY_MASTER (company_name, ticker, exchange, last_updated, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        ("Apple Inc", "AAPL", "NASDAQ", now, now, now),
                    )

            settings = _settings(
                tmp,
                external_intelligence_enabled=True,
                alpaca_api_key="key",
                alpaca_secret_key="secret",
                cryptopanic_api_key="cp-key",
                fred_api_key="fred-key",
            )

            def fake_urlopen(request, timeout=20):
                url = request.full_url
                if "cryptopanic.com" in url:
                    raise URLError("cryptopanic is down")
                if "data.alpaca.markets" in url:
                    return _fake_response(
                        {
                            "news": [
                                {
                                    "id": 111,
                                    "headline": "Apple beats on earnings",
                                    "summary": "Strong quarter.",
                                    "created_at": "2026-08-05T09:00:00Z",
                                    "symbols": ["AAPL"],
                                }
                            ]
                        }
                    )
                if "stlouisfed.org" in url:
                    if "series_id=FEDFUNDS" in url:
                        return _fake_response(
                            {
                                "observations": [
                                    {"date": "2026-07-01", "value": "5.25"},
                                    {"date": "2026-06-01", "value": "5.50"},
                                ]
                            }
                        )
                    return _fake_response({"observations": [{"date": "2026-07-01", "value": "3.1"}]})
                if "efts.sec.gov" in url:
                    return _fake_response({"hits": {"hits": [{"_source": {"form": "10-Q", "file_date": "2026-07-20"}}]}})
                raise AssertionError(f"unexpected URL requested: {url}")

            with patch("ai_trader.external_intelligence.urlopen", side_effect=fake_urlopen):
                result = run_external_intelligence_refresh(db_path, settings)

            self.assertEqual(result["status"], "completed")
            # CryptoPanic's failure was caught inside the fetcher (empty list, not
            # a raised exception) -- confirm it did not stop any other source.
            self.assertEqual(result["sources"]["cryptopanic"]["inserted"], 0)
            self.assertGreaterEqual(result["sources"]["alpaca_news"]["inserted"], 1)
            self.assertGreaterEqual(result["sources"]["fred"]["inserted"], 1)
            self.assertGreaterEqual(result["sources"]["sec_edgar"]["inserted"], 1)
            self.assertIn(
                result["sources"]["market_regime"]["primary_regime"],
                {
                    "Insufficient evidence",
                    "Strong upward trend",
                    "Transition and uncertainty",
                    "Sideways and volatile",
                    "Risk-off decline",
                },
            )

            with closing(connect(db_path)) as conn:
                news_catalyst_count = conn.execute("SELECT COUNT(*) FROM NEWS_CATALYST_EVIDENCE").fetchone()[0]
                macro_count = conn.execute("SELECT COUNT(*) FROM MACRO_EVENT_EVIDENCE").fetchone()[0]
                fundamental_count = conn.execute("SELECT COUNT(*) FROM FUNDAMENTAL_EVIDENCE").fetchone()[0]
                regime_count = conn.execute("SELECT COUNT(*) FROM MARKET_REGIME_EVIDENCE").fetchone()[0]
                crypto_news_count = conn.execute("SELECT COUNT(*) FROM CRYPTO_NEWS").fetchone()[0]
            self.assertEqual(news_catalyst_count, 1)
            self.assertGreaterEqual(macro_count, 1)
            self.assertEqual(fundamental_count, 1)
            self.assertEqual(regime_count, 1)
            self.assertEqual(crypto_news_count, 0)


if __name__ == "__main__":
    unittest.main()
