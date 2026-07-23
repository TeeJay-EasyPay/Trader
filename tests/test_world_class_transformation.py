from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_trader.experience_engine import (
    create_learning_proposal,
    find_historical_analogues,
    generate_post_trade_review,
    record_experience,
)
from ai_trader.market_intelligence_platform import (
    infer_regime_2_0,
    multi_timeframe_conclusion,
    record_market_observations,
    validate_candles,
)
from ai_trader.operational_truth import (
    calculate_mae_mfe,
    calculate_r_multiple,
    record_lifecycle_event,
    reconcile_broker_trade_rows,
    reconciliation_health,
)
from ai_trader.portfolio_intelligence import (
    calculate_portfolio_exposure,
    correlation_warning,
    proposed_trade_portfolio_impact,
    upsert_asset_metadata,
)


class WorldClassTransformationTests(unittest.TestCase):
    def test_canonical_lifecycle_is_idempotent_and_rejects_illegal_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            first = record_lifecycle_event(
                db_path,
                proposal_id="p1",
                broker="kraken",
                symbol="XRPGBP",
                stage="idea_discovered",
                payload={"source": "test"},
            )
            duplicate = record_lifecycle_event(
                db_path,
                proposal_id="p1",
                broker="kraken",
                symbol="XRPGBP",
                stage="idea_discovered",
                payload={"source": "test"},
            )
            illegal = record_lifecycle_event(
                db_path,
                proposal_id="p1",
                broker="kraken",
                symbol="XRPGBP",
                stage="fully_filled",
                payload={"source": "test"},
            )
            self.assertEqual(first["status"], "recorded")
            self.assertEqual(duplicate["status"], "duplicate")
            self.assertEqual(illegal["status"], "rejected")
            self.assertEqual(illegal["reason"], "illegal_lifecycle_transition")

    def test_broker_reconciliation_partial_full_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            rows = [
                {"id": "1", "pair": "SOLGBP", "type": "buy", "status": "open", "vol": "0.1", "price": "50"},
                {"id": "2", "pair": "SOLGBP", "type": "buy", "status": "filled", "vol": "0.1", "price": "51"},
            ]
            result = reconcile_broker_trade_rows(db_path, "kraken", rows)
            again = reconcile_broker_trade_rows(db_path, "kraken", rows)
            self.assertEqual(result["lifecycle_events_created"], 2)
            self.assertEqual(again["duplicate_events"], 2)
            self.assertTrue(reconciliation_health(db_path, "kraken"))

    def test_r_multiple_and_excursions_are_not_currency_pnl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            r = calculate_r_multiple(
                db_path,
                proposal_id="p1",
                broker="alpaca",
                symbol="AAPL",
                intended_entry_price=100,
                original_stop=95,
                filled_quantity=10,
                gross_realized_pnl=100,
                total_cost=10,
                expected_r=1.5,
                planned_take_profit=110,
            )
            self.assertEqual(r["initial_monetary_risk"], 50)
            self.assertEqual(r["gross_r"], 2)
            self.assertEqual(r["net_r"], 1.8)
            mfe = calculate_mae_mfe(
                db_path,
                proposal_id="p1",
                broker="alpaca",
                symbol="AAPL",
                side="buy",
                entry_price=100,
                quantity=10,
                original_stop=95,
                observations=[
                    {"high": 104, "low": 98, "observed_at": "2026-07-17T10:00:00+00:00"},
                    {"high": 108, "low": 96, "observed_at": "2026-07-17T11:00:00+00:00"},
                ],
                data_granularity="1h",
            )
            self.assertEqual(mfe["mae_r"], 0.8)
            self.assertEqual(mfe["mfe_r"], 1.6)

    def test_market_data_quality_and_regime_contradiction(self) -> None:
        now = datetime.now(timezone.utc)
        good = [
            {"time": (now - timedelta(minutes=10)).isoformat(), "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
            {"time": now.isoformat(), "open": 11, "high": 13, "low": 10, "close": 12, "volume": 150},
        ]
        bad = [{"time": now.isoformat(), "open": 10, "high": 8, "low": 9, "close": 11, "volume": -1}]
        self.assertEqual(validate_candles(good)["severity"], "pass")
        self.assertEqual(validate_candles(bad)["severity"], "reject")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            quality = record_market_observations(
                db_path,
                provider="unit",
                original_symbol="BTC/GBP",
                normalized_symbol="BTCGBP",
                exchange="KRAKEN",
                asset_type="crypto",
                timeframe="1h",
                candles=good,
            )
            self.assertEqual(quality["severity"], "pass")
        mtf = multi_timeframe_conclusion({"daily": {"trend": "positive"}, "1h": {"trend": "negative", "momentum": "weakening"}})
        regime = infer_regime_2_0(multi_timeframe=mtf, volatility="high")
        self.assertIn("uncertainty", regime["primary_regime"].lower())
        self.assertTrue(regime["contradictory_evidence"])

    def test_portfolio_exposure_and_correlation_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            upsert_asset_metadata(db_path, symbol="BTCGBP", source="test", payload={"asset_class": "Crypto", "trading_currency": "GBP", "crypto_category": "Layer 1"})
            exposure = calculate_portfolio_exposure(
                db_path,
                [{"symbol": "BTCGBP", "asset_type": "crypto", "market_value": 80}, {"symbol": "AAPL", "asset_type": "stock", "market_value": 20}],
            )
            self.assertTrue(exposure["warnings"])
            impact = proposed_trade_portfolio_impact(exposure, symbol="ETHGBP", proposed_notional=20, proposed_asset_class="Crypto")
            self.assertIn(impact["decision"], {"Reject due to concentration", "Buy smaller"})
            corr = correlation_warning(["A", "B"], {"A": [0.01] * 30, "B": [0.01] * 30})
            self.assertEqual(corr["status"], "complete")

    def test_experience_engine_governed_learning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            experience = record_experience(
                db_path,
                proposal_id="p1",
                broker="kraken",
                symbol="SOLGBP",
                asset_type="crypto",
                strategy_id="trend",
                regime_id="transition",
                decision_context={"strongest_argument_for": "trend", "strongest_argument_against": "volatility"},
            )
            self.assertEqual(experience["status"], "recorded")
            duplicate = record_experience(
                db_path,
                proposal_id="p1",
                broker="kraken",
                symbol="SOLGBP",
                asset_type="crypto",
                strategy_id="trend",
                regime_id="transition",
                decision_context={"strongest_argument_for": "trend", "strongest_argument_against": "volatility"},
            )
            self.assertEqual(duplicate["status"], "duplicate")
            self.assertEqual(duplicate["experience_id"], experience["experience_id"])
            review = generate_post_trade_review(
                db_path,
                {"proposal_id": "p1", "broker": "kraken", "symbol": "SOLGBP", "profit_loss": -1.0, "net_r": -0.5},
                {"strongest_argument_for": "trend", "strongest_argument_against": "volatility", "guardrails_passed": True},
            )
            self.assertEqual(review["outcome_classification"], "Good decision, poor outcome")
            analogue = find_historical_analogues(db_path, {"symbol": "SOLGBP", "strategy_id": "trend"})
            self.assertEqual(analogue["confidence"], "low")
            proposal = create_learning_proposal(
                db_path,
                proposal_type="adjust_signal_weight",
                current_value="0.2",
                proposed_value="0.15",
                evidence={"reason": "test"},
                sample_size=3,
                expected_impact="Research only",
                risks="Could overfit.",
                rollback_plan="Keep current value.",
            )
            self.assertEqual(proposal["approval_status"], "Suggested")


if __name__ == "__main__":
    unittest.main()
