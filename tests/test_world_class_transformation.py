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

    def test_broker_reconciliation_flags_manual_review_instead_of_fabricating_a_symbol(self) -> None:
        # Stage 0.4 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md):
        # reconcile_broker_trade_rows must classify/create lifecycle events from broker
        # rows "without fabricating data it doesn't have." A row with no symbol/pair
        # field must be flagged for manual review with symbol left genuinely None, not
        # guessed at, and the row must still be recorded (never silently dropped).
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            rows = [{"id": "unmatched-1", "type": "buy", "status": "filled", "vol": "0.1", "price": "50"}]

            result = reconcile_broker_trade_rows(db_path, "kraken", rows)

            self.assertEqual(result["rows_seen"], 1)
            self.assertTrue(result["manual_review_required"])
            self.assertEqual(result["status"], "Manual review required")
            self.assertEqual(result["lifecycle_events_created"], 1, "The row must still be recorded, just flagged, not dropped.")

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

    def test_single_asset_class_portfolio_is_never_flagged_as_concentrated_in_itself(self) -> None:
        # 2026-08-08 fix: a crypto-only book (e.g. Kraken's AI-managed sleeve, which never
        # holds anything but crypto) proposing another crypto trade must not be treated as
        # "concentrated" -- there is no other asset class it could be crowding out. This is the
        # same root cause as the already-fixed total<=0 case just above, one trade later: once
        # a first position exists, total is no longer 0, but if every existing position is
        # already the same asset class as the proposal, concentration is still not a meaningful
        # comparison. Deliberately uses only ONE existing asset class (unlike the mixed-book
        # test above, which must keep rejecting).
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            exposure = calculate_portfolio_exposure(db_path, [{"symbol": "BCHGBP", "asset_type": "crypto", "market_value": 2}])
            impact = proposed_trade_portfolio_impact(exposure, symbol="XRPGBP", proposed_notional=2, proposed_asset_class="crypto")
            self.assertEqual(impact["decision"], "Acceptable portfolio impact")
            self.assertIsNone(impact["new_asset_class_weight"])

    def test_portfolio_intelligence_schema_still_initializes_per_db_path_after_schema_once_fix(self) -> None:
        # Stage 0.2 (2026-08-02) moved initialize_portfolio_intelligence_schema onto the
        # shared ensure_schema_once cache, since it used to re-run its full CREATE
        # TABLE/index sequence on every single evaluate_recommendation call. This proves
        # that fix didn't accidentally make the schema a one-time-ever event: two
        # completely fresh sqlite db_path values used later in the SAME process must
        # each still get correctly initialized, and a first-ever trade against each
        # must still get "Acceptable portfolio impact" (not the pre-2026-08-01 bug
        # where an empty portfolio's 0-value denominator made every first trade look
        # 100% concentrated and get auto-rejected).
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "test.db"
                exposure = calculate_portfolio_exposure(db_path, [])
                impact = proposed_trade_portfolio_impact(
                    exposure, symbol="BTCGBP", proposed_notional=50, proposed_asset_class="Crypto"
                )
                self.assertEqual(impact["decision"], "Acceptable portfolio impact")
                self.assertIsNone(impact["new_asset_class_weight"])

    def test_record_trading_report_does_not_reinitialize_schema_on_every_call(self) -> None:
        # Phase 9 (2026-08-02, architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md):
        # record_trading_report used to run REPORT_SCHEMA's executescript on every single
        # persisted report -- flagged as a known bug in Phase 3's log entry, deliberately
        # left unfixed at the time. Now both record_trading_report and initialize_schema()
        # go through the same ensure_schema_once guard, so the underlying executescript
        # must run at most once per process for a given db_path, no matter how many
        # reports are persisted, or how initialize_schema()/record_trading_report are
        # interleaved.
        from unittest.mock import patch

        from ai_trader.application.reporting_service import ReportingService
        from ai_trader.config import Settings
        from ai_trader.models import GuardrailConfig
        from ai_trader.persistence.query_executor import QueryExecutor
        from ai_trader.persistence.schema_once import reset_for_tests

        reset_for_tests()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                settings = Settings(
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
                )
                query_executor = QueryExecutor(settings.db_path)
                service = ReportingService(
                    settings=settings,
                    audit=None,
                    query_executor=query_executor,
                    portfolio_lookup=lambda broker: {},
                    daily_learning_lookup=lambda date: {},
                )
                service.initialize_schema()

                # initialize_schema()'s _init() closure is the only thing in either
                # record_trading_report or initialize_schema() that calls
                # self._query_executor.connect() -- the INSERT itself uses a separate,
                # direct sqlite3 connection. So once the schema-once cache is warm (from
                # the call above), QueryExecutor.connect must never be called again by
                # either method for this db_path in this process.
                with patch.object(QueryExecutor, "connect", wraps=query_executor.connect) as mocked_connect:
                    service.record_trading_report(
                        report_date="2026-08-02", broker="all", report_type="daily",
                        summary="s1", markdown="m1", path=None,
                    )
                    service.record_trading_report(
                        report_date="2026-08-03", broker="all", report_type="daily",
                        summary="s2", markdown="m2", path=None,
                    )
                    self.assertEqual(
                        mocked_connect.call_count, 0,
                        "record_trading_report must not re-run schema initialization when "
                        "initialize_schema() already ran for this db_path in this process.",
                    )
        finally:
            reset_for_tests()

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
