"""2026-08-15 (Founder-requested, following observed buy-high/sell-low entries):
four deterministic gates layered onto propose_crypto_trades's entry heuristic.
See agent.py's module-level comment for why these are plain constants rather
than settings-plumbed config, and the four CRYPTO_* constants themselves."""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.agent import propose_crypto_trades
from ai_trader.audit import AuditDatabase
from ai_trader.foundation import initialize_foundation_schema
from ai_trader.models import AccountContext, GuardrailConfig
from ai_trader.multi_broker import close_managed_exit, record_crypto_research_score, record_managed_trade_exit


def _seed_score(db_path: Path, symbol: str = "BTC", *, volatility: float = 0.2) -> None:
    record_crypto_research_score(
        db_path,
        symbol=symbol,
        category="Top 20 by market cap",
        metrics={
            "technical_trend_score": 0.75,
            "momentum_score": 0.6,
            "volatility": volatility,
            "liquidity": 0.8,
            "risk_score": 0.8,
            "overall_due_diligence_score": 0.9,
            "confidence_score": 0.9,
        },
        source="test",
    )


def _account() -> AccountContext:
    return AccountContext(equity=1000, daily_realized_pnl=0, open_positions=[], is_paper=False)


class RangePositionGateTests(unittest.TestCase):
    class _AdapterAtRangePosition:
        """Fixed 24h range [90, 110]; `current` decides where price sits in it."""

        def __init__(self, current: float):
            self.current = current

        def current_prices(self, pairs):
            return {pairs[0]: {"c": [str(self.current), "1.0"], "h": ["105.0", "110.0"], "l": ["95.0", "90.0"], "o": "100.0"}}

    def test_entry_near_the_24h_high_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            _seed_score(db_path)

            proposals = propose_crypto_trades(
                db_path,
                self._AdapterAtRangePosition(109.0),  # range_position = (109-90)/(110-90) = 0.95
                ["BTC"],
                _account(),
                GuardrailConfig(),
                audit,
                min_confidence=0.85,
                requested_notional=5.0,
                default_stop_loss_pct=0.02,
            )

            self.assertEqual(proposals, [])

    def test_entry_mid_range_is_not_skipped_by_this_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            _seed_score(db_path)

            proposals = propose_crypto_trades(
                db_path,
                self._AdapterAtRangePosition(100.0),  # range_position = (100-90)/(110-90) = 0.5
                ["BTC"],
                _account(),
                GuardrailConfig(),
                audit,
                min_confidence=0.85,
                requested_notional=5.0,
                default_stop_loss_pct=0.02,
            )

            self.assertEqual(len(proposals), 1)


class BtcRegimeGateTests(unittest.TestCase):
    class _AdapterWithBtcChange:
        """BTC's own ticker reflects btc_change_pct; any other pair returns a flat price
        with no h/l/o (so the range-position gate never fires in these tests)."""

        def __init__(self, btc_change_pct: float):
            self.btc_change_pct = btc_change_pct

        def current_prices(self, pairs):
            pair = pairs[0]
            if pair == "XBTGBP":
                open_price = 100.0
                current = open_price * (1 + self.btc_change_pct)
                return {pair: {"c": [str(current), "1.0"], "o": str(open_price)}}
            return {pair: {"c": ["50.0", "1.0"]}}

    def test_altcoin_entry_skipped_when_btc_is_weak(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            _seed_score(db_path, symbol="SOL")

            proposals = propose_crypto_trades(
                db_path,
                self._AdapterWithBtcChange(-0.05),  # BTC down 5%, below the -3% threshold
                ["SOL"],
                _account(),
                GuardrailConfig(),
                audit,
                min_confidence=0.85,
                requested_notional=5.0,
                default_stop_loss_pct=0.02,
            )

            self.assertEqual(proposals, [])

    def test_altcoin_entry_allowed_when_btc_is_flat_or_strong(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            _seed_score(db_path, symbol="SOL")

            proposals = propose_crypto_trades(
                db_path,
                self._AdapterWithBtcChange(0.01),
                ["SOL"],
                _account(),
                GuardrailConfig(),
                audit,
                min_confidence=0.85,
                requested_notional=5.0,
                default_stop_loss_pct=0.02,
            )

            self.assertEqual(len(proposals), 1)

    def test_btc_itself_is_not_gated_against_its_own_regime(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            _seed_score(db_path, symbol="BTC")

            proposals = propose_crypto_trades(
                db_path,
                self._AdapterWithBtcChange(-0.05),
                ["BTC"],
                _account(),
                GuardrailConfig(),
                audit,
                min_confidence=0.85,
                requested_notional=5.0,
                default_stop_loss_pct=0.02,
            )

            self.assertEqual(len(proposals), 1)


class ReEntryCooldownGateTests(unittest.TestCase):
    class _FlatAdapter:
        def current_prices(self, pairs):
            return {pairs[0]: {"c": ["50.0", "1.0"]}}

    def _stop_out(self, db_path: Path, *, symbol: str, minutes_ago: float) -> None:
        entry = record_managed_trade_exit(
            db_path,
            broker="kraken",
            symbol=symbol,
            side="buy",
            quantity=1.0,
            entry_order_id="entry-1",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            payload={},
        )
        close_managed_exit(db_path, int(entry["managed_exit_id"]), exit_order_id="exit-1", exit_reason="stop_loss_triggered")
        # close_managed_exit always stamps "now" -- backdate updated_at directly so the
        # cooldown window has something real to compare against.
        from ai_trader.database import connect
        from contextlib import closing

        backdated = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
        with closing(connect(db_path)) as conn:
            with conn:
                conn.execute(
                    "UPDATE MANAGED_TRADE_EXITS SET updated_at = ? WHERE managed_exit_id = ?",
                    (backdated, int(entry["managed_exit_id"])),
                )

    def test_symbol_stopped_out_recently_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            _seed_score(db_path, symbol="BCH")
            self._stop_out(db_path, symbol="BCH", minutes_ago=30)  # well inside the 4h cooldown

            proposals = propose_crypto_trades(
                db_path,
                self._FlatAdapter(),
                ["BCH"],
                _account(),
                GuardrailConfig(),
                audit,
                min_confidence=0.85,
                requested_notional=5.0,
                default_stop_loss_pct=0.02,
            )

            self.assertEqual(proposals, [])

    def test_symbol_stopped_out_long_ago_is_not_skipped_by_this_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            _seed_score(db_path, symbol="BCH")
            self._stop_out(db_path, symbol="BCH", minutes_ago=600)  # 10h ago, outside the 4h cooldown

            proposals = propose_crypto_trades(
                db_path,
                self._FlatAdapter(),
                ["BCH"],
                _account(),
                GuardrailConfig(),
                audit,
                min_confidence=0.85,
                requested_notional=5.0,
                default_stop_loss_pct=0.02,
            )

            self.assertEqual(len(proposals), 1)


class VolatilityScaledStopTests(unittest.TestCase):
    class _FlatAdapter:
        def current_prices(self, pairs):
            return {pairs[0]: {"c": ["100.0", "1.0"]}}

    def test_higher_volatility_widens_the_stop_distance(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            _seed_score(db_path, symbol="CALM", volatility=0.0)
            _seed_score(db_path, symbol="WILD", volatility=1.0)

            proposals = propose_crypto_trades(
                db_path,
                self._FlatAdapter(),
                ["CALM", "WILD"],
                _account(),
                GuardrailConfig(),
                audit,
                min_confidence=0.85,
                requested_notional=5.0,
                default_stop_loss_pct=0.02,
            )

            self.assertEqual(len(proposals), 2)
            calm = next(p for p in proposals if p.symbol == "CALM")
            wild = next(p for p in proposals if p.symbol == "WILD")
            calm_stop_distance = calm.entry_price - calm.stop_loss
            wild_stop_distance = wild.entry_price - wild.stop_loss
            # volatility=0.0 -> multiplier 1.0 (base 2% stop); volatility=1.0 -> multiplier
            # 2.0 (4% stop) -- the volatile coin's stop must be exactly twice as wide.
            self.assertAlmostEqual(wild_stop_distance, calm_stop_distance * 2, places=6)


if __name__ == "__main__":
    unittest.main()
