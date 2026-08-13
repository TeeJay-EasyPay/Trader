import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.audit import AuditDatabase
from ai_trader.config import Settings
from ai_trader.database import connect
from ai_trader.models import AutoTradeConfig, GuardrailConfig, TradeProposal, ValidationResult
from ai_trader.multi_broker import set_broker_auto_trading


def settings_for(tmp: str) -> Settings:
    root = Path(tmp)
    return Settings(
        alpaca_api_key="paper-key",
        alpaca_secret_key="paper-secret",
        alpaca_paper_base_url="https://paper-api.alpaca.markets",
        alpaca_data_base_url="https://data.alpaca.markets",
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
        db_path=root / "audit.sqlite3",
        output_dir=root,
        trading_log_path=root / "TRADING_LOG.md",
        guardrails=GuardrailConfig(),
        auto_trade=AutoTradeConfig(enabled=True),
    )


def _proposal(symbol: str, asset_type: str) -> TradeProposal:
    return TradeProposal(
        symbol=symbol, side="buy", entry_price=100, stop_loss=98, take_profit=106,
        position_size=1, risk_percentage=0.01, confidence_score=0.95,
        news_summary="No material news.", market_sentiment_summary="Neutral.",
        technical_summary="Setup available.",
        plain_english_reasoning=(
            "Strongest argument for: the trend is constructive. "
            "Strongest argument against: volatility could invalidate the setup."
        ),
        ai_guardrails_passed=True, asset_type=asset_type,
        exchange="NASDAQ" if asset_type == "stock" else "KRAKEN",
    ).normalized()


class TradeAuditBrokerColumnTests(unittest.TestCase):
    def test_new_writes_populate_broker_from_asset_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            audit.record_trade_event("agent_proposal", _proposal("AAPL", "stock"), validation=ValidationResult(passed=True))
            audit.record_trade_event("agent_proposal", _proposal("BTC", "crypto"), validation=ValidationResult(passed=True))
            with closing(connect(settings.db_path)) as conn:
                rows = {row[0]: row[1] for row in conn.execute("SELECT symbol, broker FROM trade_audit")}
        self.assertEqual(rows["AAPL"], "alpaca")
        self.assertEqual(rows["BTC"], "kraken")

    def test_existing_rows_without_broker_are_backfilled_on_next_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            audit.record_trade_event("agent_proposal", _proposal("ETH", "crypto"), validation=ValidationResult(passed=True))
            # Simulate a pre-migration row: clear the column exactly as it would be for data
            # written before this column existed.
            with closing(connect(settings.db_path)) as conn:
                with conn:
                    conn.execute("UPDATE trade_audit SET broker = NULL WHERE symbol = 'ETH'")

            # Re-opening AuditDatabase (as every job/request does) must backfill it.
            AuditDatabase(settings.db_path, settings.trading_log_path)
            with closing(connect(settings.db_path)) as conn:
                broker = conn.execute("SELECT broker FROM trade_audit WHERE symbol = 'ETH'").fetchone()[0]
        self.assertEqual(broker, "kraken")

    def test_alpaca_auto_execution_is_not_starved_by_a_kraken_dominated_pool(self):
        # 2026-08-10 hosted incident, reproduced directly: Kraken generates candidates far more
        # frequently than Alpaca. Before broker was a real, SQL-filterable column, the shared
        # LIMIT-50 candidate query could be entirely crowded out by one broker, silently
        # starving the other's auto-execution job every cycle. 60 fresh Kraken candidates here
        # deliberately exceed the LIMIT-50 window on their own; a single Alpaca candidate must
        # still be found and evaluated.
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            for i in range(60):
                audit.record_trade_event(
                    "agent_proposal", _proposal(f"CRYPTO{i}", "crypto"), validation=ValidationResult(passed=True)
                )
            audit.record_trade_event("agent_proposal", _proposal("AAPL", "stock"), validation=ValidationResult(passed=True))
            set_broker_auto_trading(settings.db_path, "alpaca", True)

            evaluated_symbols: list[str] = []

            def fake_evaluate(proposal, context, auto_execute=True):
                evaluated_symbols.append(proposal.symbol)
                from types import SimpleNamespace
                return SimpleNamespace(
                    decision="rejected", rejection_reason="test_short_circuit", notes=None,
                    symbol=proposal.symbol, to_dict=lambda: {},
                )

            service = LocalApiService(settings)
            with (
                patch.object(service.orchestrator, "evaluate_recommendation", side_effect=fake_evaluate),
                patch.object(LocalApiService, "_account_context_for_broker", return_value=None),
            ):
                service.auto_execute_recommendations(broker_filter="alpaca")

        self.assertIn("AAPL", evaluated_symbols)
        self.assertNotIn("CRYPTO0", evaluated_symbols)

if __name__ == "__main__":
    unittest.main()
