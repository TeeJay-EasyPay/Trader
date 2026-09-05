"""2026-08-15 (Founder-requested, following observed buy-high/sell-low entries):
four deterministic gates layered onto propose_crypto_trades's entry heuristic.
See agent.py's module-level comment for why these are plain constants rather
than settings-plumbed config, and the four CRYPTO_* constants themselves."""

import json
import sys
import tempfile
import unittest
from contextlib import closing
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


class RangePositionIsEvidenceNotAGateTests(unittest.TestCase):
    """2026-09-05, Founder-directed: where a coin sits in its 24h range stopped being a gate.

    It used to refuse any entry above 0.75 of the day's range. His objection, made for the
    third time about a hardcoded threshold and correct each time: "the AI itself should be
    looking at the movement, looking at the candles that have been returned from Kraken, and
    deciding itself whether that trade is worth taking, and not necessarily relying on a gate."

    A percentage cannot tell a breakout from an exhausted spike; it refuses both. On the day it
    was removed it was the last thing between the app and a trade -- DOT was the only coin to
    clear the score bar and was refused twice purely for having risen.

    He also declined a softer backstop at 0.98: "how do we know what point nine eight of a
    range is? That's just a guess." So there is no hard limit at all, and no mechanical
    markdown either -- the reviewer can only lower confidence, and position size is scaled from
    confidence, so a model that judges an entry stretched shrinks the position by saying so.
    """

    class _AdapterAtRangePosition:
        """Fixed 24h range [90, 110]; `current` decides where price sits in it."""

        def __init__(self, current: float):
            self.current = current

        def current_prices(self, pairs):
            return {pairs[0]: {"c": [str(self.current), "1.0"], "h": ["105.0", "110.0"], "l": ["95.0", "90.0"], "o": "100.0"}}

    def _propose(self, current: float):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            _seed_score(db_path)
            return propose_crypto_trades(
                db_path,
                self._AdapterAtRangePosition(current),
                ["BTC"],
                _account(),
                GuardrailConfig(),
                audit,
                min_confidence=0.85,
                requested_notional=5.0,
                default_stop_loss_pct=0.02,
            )

    def test_an_entry_near_the_24h_high_is_no_longer_refused(self):
        """THE CHANGE. 0.95 of the range was an automatic refusal; it is now a judgement."""
        self.assertEqual(len(self._propose(109.0)), 1)

    def test_an_entry_mid_range_is_unaffected(self):
        self.assertEqual(len(self._propose(100.0)), 1)

    def test_the_range_reading_reaches_the_reviewer_as_evidence(self):
        """Removing the gate is only safe if the model is actually given what the gate used to
        act on. Position in range, plus the levels it was measured against."""
        from ai_trader.agent import _kraken_day_range, _kraken_range_position, _review_candidate

        prices = self._AdapterAtRangePosition(109.0).current_prices(["XBTGBP"])
        position = _kraken_range_position(prices, "XBTGBP")
        day_range = _kraken_day_range(prices, "XBTGBP")
        self.assertAlmostEqual(position, 0.95, places=2)
        self.assertEqual(day_range["high_24h"], 110.0)
        self.assertEqual(day_range["low_24h"], 90.0)
        self.assertIsNotNone(day_range["range_width_pct"])
        self.assertIsNotNone(day_range["change_from_open_pct"])

        proposals = self._propose(109.0)
        candidate = _review_candidate(
            proposals[0], {"technical_trend_score": 0.75, "momentum_score": 0.6, "volatility": 0.2,
                           "liquidity": 0.8, "risk_score": 0.8, "overall_due_diligence_score": 0.9},
            range_position=position, day_range=day_range,
        )
        self.assertAlmostEqual(candidate["position_in_24h_range"], 0.95, places=2)
        self.assertEqual(candidate["day_range"]["high_24h"], 110.0)


class KrakenCanonicalPairNameTests(unittest.TestCase):
    """Kraken answers under ITS name, not the one you asked for.

    You request XBTGBP / ETHGBP / XLMGBP and the Ticker result comes back keyed
    XXBTZGBP / XETHZGBP / XXLMZGBP, while newer listings echo the altname unchanged.
    Measured against live Kraken on 2026-09-05: exactly three of the nineteen tradable
    coins miss on a plain dict lookup, and they are BTC, ETH and XLM.

    Both range helpers read the requested key, so the 24h evidence was blank for those
    three - and so, before it was removed, was the 0.75 gate that read the same number.
    It never applied to BTC, ETH or XLM at all.

    broker_adapters already records this trap twice (order_book's comment, and
    _kraken_last_price's next(iter(...)) fallback), which is why the price still worked
    while the range did not.
    """

    LEGACY = {
        "XXBTZGBP": {"c": ["109.0", "1"], "h": ["105.0", "110.0"], "l": ["95.0", "90.0"], "o": "100.0"},
    }

    def test_a_canonical_reply_resolves_to_the_altname_that_was_requested(self):
        from ai_trader.agent import _kraken_day_range, _kraken_range_position

        self.assertAlmostEqual(_kraken_range_position(self.LEGACY, "XBTGBP"), 0.95, places=2)
        self.assertEqual(_kraken_day_range(self.LEGACY, "XBTGBP")["high_24h"], 110.0)

    def test_an_exact_key_still_wins_over_the_fallback(self):
        from ai_trader.agent import _kraken_range_position

        prices = {
            "DOTGBP": {"c": ["91.0", "1"], "h": ["105.0", "110.0"], "l": ["95.0", "90.0"], "o": "100.0"},
            "XXBTZGBP": self.LEGACY["XXBTZGBP"],
        }
        self.assertAlmostEqual(_kraken_range_position(prices, "DOTGBP"), 0.05, places=2)

    def test_an_unrelated_batch_does_not_borrow_another_coins_range(self):
        """The sole-payload fallback must not fire when several pairs came back."""
        from ai_trader.agent import _kraken_range_position

        prices = {
            "DOTGBP": {"c": ["91.0", "1"], "h": ["105.0", "110.0"], "l": ["95.0", "90.0"], "o": "100.0"},
            "SOLGBP": {"c": ["99.0", "1"], "h": ["105.0", "110.0"], "l": ["95.0", "90.0"], "o": "100.0"},
        }
        self.assertIsNone(_kraken_range_position(prices, "XLMGBP"))


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

    def _seed_candles(self, db_path, symbol, daily_range_pct):
        """Daily candles with a controlled swing, so ATR comes out where the test wants it."""
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(db_path)) as conn:
            with conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS MARKET_DATA_OBSERVATIONS (
                    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL, provider TEXT NOT NULL,
                    original_symbol TEXT NOT NULL, normalized_symbol TEXT NOT NULL,
                    exchange TEXT, asset_type TEXT NOT NULL, timeframe TEXT NOT NULL,
                    observation_time TEXT NOT NULL, retrieval_time TEXT NOT NULL,
                    freshness TEXT NOT NULL, completeness TEXT NOT NULL,
                    adjusted_status TEXT NOT NULL, source_quality_status TEXT NOT NULL,
                    payload_provenance TEXT NOT NULL,
                    open REAL, high REAL, low REAL, close REAL, volume REAL, payload_json TEXT NOT NULL)""")
                for day in range(1, 41):
                    stamp = f"2026-07-{day:02d}T00:00:00Z" if day <= 31 else f"2026-08-{day - 31:02d}T00:00:00Z"
                    close = 100.0
                    half = close * daily_range_pct / 2
                    conn.execute(
                        """INSERT INTO MARKET_DATA_OBSERVATIONS
                           (created_at, provider, original_symbol, normalized_symbol, exchange,
                            asset_type, timeframe, observation_time, retrieval_time, freshness,
                            completeness, adjusted_status, source_quality_status,
                            payload_provenance, open, high, low, close, volume, payload_json)
                           VALUES (?,'kraken',?,?,'KRAKEN','crypto','1d',?,?,'fresh','complete',
                                   'unadjusted','pass','test',?,?,?,?,0,'{}')""",
                        (stamp, symbol, symbol, stamp, stamp, close, close + half, close - half, close),
                    )

    def test_a_more_volatile_coin_gets_a_wider_stop(self):
        """2026-09-03, Founder-directed: "it also will vary from coin to coin. The smaller cap
        coins will fluctuate much harder and broader than the large cap coins."

        This test previously asserted the OLD formula -- default stop times a 1.0-2.0 multiplier
        taken from a stored "volatility" score. That formula could only ever produce 1.5%-3.0%
        however the coin behaved, and it scaled on a score that rated BTC as more volatile than
        ADA. The stop is now sized from ATR measured on the coin's own candles.

        What the test asserts is unchanged in spirit: a wilder coin must get more room.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            _seed_score(db_path, symbol="CALM", volatility=0.0)
            _seed_score(db_path, symbol="WILD", volatility=1.0)
            self._seed_candles(db_path, "CALM", 0.02)   # 2% daily range
            self._seed_candles(db_path, "WILD", 0.08)   # 8% daily range

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
            calm_distance = (calm.entry_price - calm.stop_loss) / calm.entry_price
            wild_distance = (wild.entry_price - wild.stop_loss) / wild.entry_price
            self.assertGreater(wild_distance, calm_distance,
                               "the coin that swings four times as far must get more room")
            self.assertGreaterEqual(calm_distance, 0.015,
                                    "no stop may sit inside the noise floor -- a 0.4% stop is what "
                                    "blocked crypto for a week")


class ConfidenceJudgedOnceTests(unittest.TestCase):
    """2026-09-04: the confidence bar must be applied ONCE, on the final score.

    No Kraken position opened between 25 August and 4 September. The bar was being
    checked before the track-record/liquidity penalties and again after, so a coin
    passed on its raw research score, was marked down, and then failed the same bar --
    surfacing as `confidence_below_minimum`, which reads as "the research score was too
    low" when it was fine. Live on 4 September: FIL scored 0.7479 in research, took a
    0.10 markdown for thin bid support, and was refused at 0.6479 against a 0.70 bar.

    This is the third time this shape has shipped (philosophy_fit=confidence was the
    same bug, fixed 29 August), hence a test rather than only a fix.
    """

    PRICE = 100.0

    class _Adapter:
        """Mid-range price so the 24h-range gate stays out of the way."""

        def __init__(self, price: float, *, with_book: bool, broken_book: bool = False):
            self.price = price
            self.broken_book = broken_book
            if with_book:
                self.order_book = self._order_book

        def current_prices(self, pairs):
            return {pairs[0]: {"c": [str(self.price), "1.0"], "h": ["105.0", "110.0"],
                               "l": ["95.0", "90.0"], "o": "100.0"}}

        def _order_book(self, pair):
            """Real support to 2.0% down and a cliff beneath it -> 'caution', 0.10 penalty.
            broken_book instead leaves nothing under the price at all -> 'avoid'."""
            if self.broken_book:
                return {
                    "bids": [[str(self.price * 0.999), "0.01", 0]],
                    "asks": [[str(self.price * (1 + d / 100.0)), "100.0", 0] for d in (0.5, 1.0, 1.5)],
                }
            bids = [[str(self.price * (1 - d / 100.0)), "100.0", 0] for d in (0.5, 1.0, 1.5, 2.0)]
            bids += [[str(self.price * (1 - d / 100.0)), "0.01", 0] for d in (2.5, 3.0, 3.5, 4.0)]
            asks = [[str(self.price * (1 + d / 100.0)), "100.0", 0] for d in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0)]
            return {"bids": bids, "asks": asks}

    def _run(self, *, with_book: bool, raw_score: float = 0.7479, bar: float = 0.70,
             guardrail_bar: float | None = None, broken_book: bool = False):
        """Returns (proposals, no_trade_reasons, proposal_rows_recorded)."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            record_crypto_research_score(
                db_path,
                symbol="BTC",
                category="Top 20 by market cap",
                metrics={
                    "technical_trend_score": 0.75,
                    "momentum_score": 0.6,
                    "volatility": 0.2,
                    "liquidity": 0.8,
                    "risk_score": 0.8,
                    "overall_due_diligence_score": raw_score,
                    "confidence_score": raw_score,
                },
                source="test",
            )
            proposals = propose_crypto_trades(
                db_path,
                self._Adapter(self.PRICE, with_book=with_book, broken_book=broken_book),
                ["BTC"],
                AccountContext(equity=1000, daily_realized_pnl=0, open_positions=[], is_paper=False),
                GuardrailConfig(
                    min_confidence_score=bar if guardrail_bar is None else guardrail_bar,
                    paper_trading_only=False,
                ),
                audit,
                min_confidence=bar,
                requested_notional=50.0,
                default_stop_loss_pct=0.02,
            )
            with closing(audit.connect()) as conn:
                reasons = [
                    json.loads(row[0]).get("reason")
                    for row in conn.execute(
                        "SELECT payload_json FROM execution_events "
                        "WHERE event_type IN ('agent_no_trade', 'agent_position_sized_down')"
                    )
                ]
                recorded = conn.execute(
                    "SELECT COUNT(*) FROM trade_audit "
                    "WHERE symbol = 'BTC' AND event_type = 'agent_proposal'"
                ).fetchone()[0]
            return proposals, reasons, recorded

    def test_a_coin_clearing_the_bar_with_no_penalty_still_proposes(self):
        """The control: without an order book there is no markdown, so it must trade."""
        proposals, _, _ = self._run(with_book=False)
        self.assertEqual(len(proposals), 1)

    def test_a_markdown_that_crosses_the_bar_now_sizes_down_instead_of_refusing(self):
        """Option B, Founder-directed 2026-09-04. 0.7479 - 0.10 = 0.6479 is under the 0.70
        bar, and until today that refused the trade outright -- which is what stopped every
        Kraken entry between 25 August and 4 September.

        A thin order book is a reason to risk LESS, not a reason to skip a good idea: the
        stop loss already covers direction, and thin liquidity costs money on the exit. So
        the coin must now trade, and its sizing confidence must be floored at the bar rather
        than dropped below it.
        """
        proposals, reasons, _ = self._run(with_book=True)
        self.assertEqual(len(proposals), 1, f"markdown must size down, not veto; reasons={reasons}")
        self.assertAlmostEqual(proposals[0].confidence_score, 0.70, places=6,
                               msg="a marked-down coin sizes at the floor, not below it")
        self.assertNotIn("penalised_below_confidence_bar", reasons)

    def test_the_markdown_is_recorded_even_though_it_no_longer_refuses(self):
        """The discount must stay visible. It changes how much real money is committed, so
        it cannot become an invisible adjustment inside the sizing maths."""
        _, reasons, _ = self._run(with_book=True)
        self.assertIn("marked_down_for_execution_risk", reasons)

    def test_a_genuinely_broken_order_book_is_still_refused_outright(self):
        """Option B widens what may be traded; it does not remove the hard veto. A book with
        no real bid support beneath the price at all is still a no."""
        proposals, reasons, _ = self._run(with_book=True, broken_book=True)
        self.assertEqual(proposals, [])
        self.assertIn("liquidity_structure_unfavourable", reasons)

    def test_a_penalty_that_does_not_cross_the_bar_still_proposes(self):
        """The penalty must lower conviction, not act as a veto. 0.85 - 0.10 = 0.75 is still
        over the bar, so the coin must survive its markdown -- MAX_CONFIDENCE_PENALTY is
        capped precisely so a markdown can never be the whole decision."""
        proposals, _, _ = self._run(with_book=True, raw_score=0.85)
        self.assertEqual(len(proposals), 1)

    def test_the_guardrail_is_given_the_same_bar_the_research_gate_used(self):
        """The guardrail used to fall back to GuardrailConfig.min_confidence_score -- the
        Render environment variable -- while the research gate read the database-first policy
        value (decision_registry's min_ai_confidence). Where the two disagreed, a coin over
        the policy bar was silently refused by a stricter copy of the same threshold.

        Here the policy bar is 0.70 and the environment bar is 0.85. A 0.72 coin is over the
        bar the app actually shows the Founder, so it must trade.
        """
        proposals, reasons, _ = self._run(with_book=False, raw_score=0.72, bar=0.70,
                                          guardrail_bar=0.85)
        self.assertEqual(len(proposals), 1,
                         f"refused by a second copy of the bar; reasons={reasons}")


if __name__ == "__main__":
    unittest.main()
