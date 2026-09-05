"""2026-09-04. Kraken executes in micro_live mode; every strategy the crypto path assigns sat
at the Sprint 6 bootstrap default of Paper, so every Kraken trade was refused with
`strategy_entitlement_blocked`. Measured live: LTC and XRP cleared research, the liquidity
markdown, every guardrail, the AI reviewer and capital allocation (GBP 25.00 approved each),
then died at this gate.

These tests pin the Founder-authorised promotion, and -- more importantly -- that it is
idempotent. It runs on every worker boot, so a second run must change nothing and must not
write a duplicate promotion record.
"""

import json
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.database import connect
from ai_trader.sprint6 import initialize_sprint6_schema
from ai_trader.strategy_promotions import (
    FOUNDER_AUTHORISED_CRYPTO_MICRO_LIVE,
    MICRO_LIVE_MODE,
    MICRO_LIVE_STAGE,
    apply_founder_crypto_micro_live_promotions,
)
from ai_trader.trading_intelligence import _candidate_strategy_ids
from ai_trader.models import TradeProposal


def _seed(db_path: Path, strategy_id: str, *, stage: str = "Paper",
          modes: tuple[str, ...] = ("shadow", "paper", "manual")) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO STRATEGY_MATURITY_REGISTRY (
                    strategy_id, version, current_stage, evidence_json, permitted_asset_classes_json,
                    permitted_brokers_json, permitted_modes_json, suspended, approval_authority, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (strategy_id, "1", stage, "{}", json.dumps(["crypto", "stock"]),
                 json.dumps(["alpaca", "kraken"]), json.dumps(list(modes)), "Sprint 6 bootstrap",
                 "2026-09-01T00:00:00+00:00"),
            )


class FounderCryptoPromotionTests(unittest.TestCase):
    def test_a_paper_strategy_is_promoted_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            initialize_sprint6_schema(db)
            _seed(db, "range_trading")

            result = apply_founder_crypto_micro_live_promotions(db)
            self.assertIn("range_trading", result["promoted"])

            with closing(connect(db)) as conn:
                row = conn.execute(
                    "SELECT current_stage, permitted_modes_json, approval_authority "
                    "FROM STRATEGY_MATURITY_REGISTRY WHERE strategy_id = 'range_trading'"
                ).fetchone()
            self.assertEqual(row[0], MICRO_LIVE_STAGE)
            self.assertIn(MICRO_LIVE_MODE, json.loads(row[1]))
            self.assertEqual(row[2], "Founder")

    def test_the_existing_modes_are_kept_so_alpaca_is_not_broken(self):
        """Alpaca runs in `paper` mode against the same registry. Promotion must ADD micro_live,
        never replace the existing modes, or every equity trade would start failing instead."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            initialize_sprint6_schema(db)
            _seed(db, "momentum")
            apply_founder_crypto_micro_live_promotions(db)
            with closing(connect(db)) as conn:
                modes = json.loads(conn.execute(
                    "SELECT permitted_modes_json FROM STRATEGY_MATURITY_REGISTRY WHERE strategy_id='momentum'"
                ).fetchone()[0])
            for mode in ("shadow", "paper", "manual", "micro_live"):
                self.assertIn(mode, modes)

    def test_running_twice_changes_nothing_and_writes_no_duplicate_record(self):
        """This runs on every worker boot. A second pass must be a no-op."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            initialize_sprint6_schema(db)
            _seed(db, "pullback")

            first = apply_founder_crypto_micro_live_promotions(db)
            second = apply_founder_crypto_micro_live_promotions(db)

            self.assertEqual(first["promoted"], ["pullback"])
            self.assertEqual(second["promoted"], [])
            self.assertEqual(second["status"], "no_change")
            self.assertIn("pullback", second["already_micro_live"])

            with closing(connect(db)) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM STRATEGY_PROMOTION_DECISIONS WHERE strategy_id = 'pullback'"
                ).fetchone()[0]
            self.assertEqual(count, 1, "a second boot must not write a second promotion record")

    def test_a_strategy_missing_from_the_registry_is_reported_not_crashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            initialize_sprint6_schema(db)
            result = apply_founder_crypto_micro_live_promotions(db)
            self.assertEqual(result["promoted"], [])
            self.assertEqual(sorted(result["not_registered"]),
                             sorted(FOUNDER_AUTHORISED_CRYPTO_MICRO_LIVE))

    def test_the_promotion_records_that_it_had_no_performance_evidence(self):
        """The whole reason this needed Founder authorisation is that no evidence existed. The
        record must say so, rather than implying a governed promotion took place."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.sqlite3"
            initialize_sprint6_schema(db)
            _seed(db, "breakout")
            apply_founder_crypto_micro_live_promotions(db)
            with closing(connect(db)) as conn:
                row = conn.execute(
                    "SELECT evidence_gate_status, payload_json FROM STRATEGY_PROMOTION_DECISIONS "
                    "WHERE strategy_id = 'breakout'"
                ).fetchone()
            self.assertEqual(row[0], "bypassed_no_recorded_evidence")
            self.assertEqual(json.loads(row[1])["performance_evidence"], "none_recorded")


class CryptoCandidateListTests(unittest.TestCase):
    def test_swing_continuation_and_volatility_expansion_are_offered_to_crypto(self):
        """Both are permitted for crypto in the registry and the catalogue, but the hardcoded
        candidate list never offered them, so they could never be selected however well they fit."""
        proposal = TradeProposal(
            symbol="SOL", side="buy", entry_price=100.0, stop_loss=97.0, take_profit=106.0,
            position_size=1.0, risk_percentage=0.01, confidence_score=0.75,
            news_summary="n", market_sentiment_summary="s", technical_summary="t",
            plain_english_reasoning="r", asset_type="crypto", exchange="KRAKEN",
        )
        candidates = _candidate_strategy_ids(proposal)
        self.assertIn("swing_continuation", candidates)
        self.assertIn("volatility_expansion", candidates)

    def test_every_crypto_candidate_is_authorised_for_micro_live(self):
        """If the crypto path can select a strategy, that strategy must be promoted -- otherwise
        it is selected and then refused at the entitlement gate, which is the exact two-week
        outage this work fixed."""
        proposal = TradeProposal(
            symbol="SOL", side="buy", entry_price=100.0, stop_loss=97.0, take_profit=106.0,
            position_size=1.0, risk_percentage=0.01, confidence_score=0.75,
            news_summary="n", market_sentiment_summary="s", technical_summary="t",
            plain_english_reasoning="r", asset_type="crypto", exchange="KRAKEN",
        )
        for strategy_id in _candidate_strategy_ids(proposal):
            self.assertIn(
                strategy_id, FOUNDER_AUTHORISED_CRYPTO_MICRO_LIVE,
                f"{strategy_id} can be chosen for a coin but is not authorised for micro_live, "
                "so it would be blocked at the entitlement gate",
            )


if __name__ == "__main__":
    unittest.main()
