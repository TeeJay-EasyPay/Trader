"""2026-08-27, Founder-directed: themes the app maintains itself, for crypto and for shares.

MARKET_THEMES held 14 hand-written share sectors, every one last updated 2 July, because
refreshing them needed a person to hand the app a file and nobody had. A two-month-old outlook
asserted as current is worse than none: it is a systematic bias applied across a whole sector
rather than one bad trade.

The Founder asked whether coins can have themes too. They can, and the app was already
collecting them without using them -- CRYPTO_MASTER carries "Top 20 AI coins" and "Top 20
security/privacy coins". He also asked how this is future-proofed: by deriving the theme list
from what the app actually tracks, so a new sector, narrative or market appears on its own.

His instinct that "there are thousands of cryptos" makes themes harder is the one thing these
tests disprove by construction: ten narratives cover thousands of coins, because judging a
sector covers everything in it.
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from contextlib import closing

from ai_trader.database import connect
from ai_trader.foundation import initialize_foundation_schema
from ai_trader.market_themes import (
    CRYPTO,
    EQUITY,
    MAX_AGE_HOURS,
    current_theme_view,
    discover_themes,
    initialize_market_theme_schema,
    refresh_market_themes,
    theme_for_symbol,
)


def fake_openai(views):
    body = json.dumps({"output": [{"content": [{"text": json.dumps(views)}]}]}).encode()

    class Response:
        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return mock.Mock(return_value=Response())


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        initialize_foundation_schema(self.db_path)
        initialize_market_theme_schema(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def add_coin(self, symbol, category):
        now = datetime.now(timezone.utc).isoformat()
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO CRYPTO_MASTER (symbol, name, category, source, active, created_at, updated_at)"
                    " VALUES (?, ?, ?, 'test', 1, ?, ?)",
                    (symbol, symbol, category, now, now),
                )

    def add_crypto_news(self, symbol, count=3, hours_ago=2):
        when = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
        with closing(connect(self.db_path)) as conn:
            with conn:
                for index in range(count):
                    conn.execute(
                        "INSERT INTO CRYPTO_NEWS (symbol, published_at, title, summary, source, url,"
                        " payload_json, created_at) VALUES (?, ?, ?, 'detail', 'Wire', 'u', '{}', ?)",
                        (symbol, when, f"{symbol} headline {index}", when),
                    )

    # --- discovery: the future-proofing the Founder asked about --------------------------

    def test_themes_are_derived_from_the_tracked_universe_not_hardcoded(self):
        self.add_coin("BTC", "Top 20 by market cap")
        self.add_coin("TAO", "Top 20 AI coins")
        themes = discover_themes(self.db_path, CRYPTO)
        self.assertEqual(sorted(themes), ["Top 20 AI coins", "Top 20 by market cap"])

    def test_a_brand_new_narrative_appears_with_no_code_change(self):
        """The property that future-proofs this: adding an asset in a new category is enough."""
        self.add_coin("ARB", "Layer 2 scaling")
        self.assertIn("Layer 2 scaling", discover_themes(self.db_path, CRYPTO))

    def test_ten_themes_can_cover_any_number_of_coins(self):
        """'There are thousands of cryptos' is an argument FOR themes, not against them."""
        for index in range(300):
            self.add_coin(f"C{index}", f"Narrative {index % 10}")
        themes = discover_themes(self.db_path, CRYPTO)
        self.assertEqual(len(themes), 10)
        self.assertEqual(sum(len(v) for v in themes.values()), 300)

    def test_the_kraken_permissions_list_is_not_a_market_view(self):
        """It says where the app MAY trade, never what it thinks of the sector."""
        self.add_coin("BTC", "Founder approved Kraken pairs")
        self.assertNotIn("Founder approved Kraken pairs", discover_themes(self.db_path, CRYPTO))

    def test_a_coins_theme_is_re_derived_rather_than_stored(self):
        """A coin can change narrative when its team pivots, unlike a mining company."""
        self.add_coin("TAO", "Top 20 AI coins")
        self.assertEqual(theme_for_symbol(self.db_path, "TAO", CRYPTO), "Top 20 AI coins")
        self.assertIsNone(theme_for_symbol(self.db_path, "NOTHELD", CRYPTO))

    # --- refresh -------------------------------------------------------------------------

    def test_a_theme_with_too_little_news_is_left_unwritten(self):
        self.add_coin("BTC", "Top 20 by market cap")
        self.add_crypto_news("BTC", count=1)
        with mock.patch("ai_trader.market_themes.urlopen") as opener:
            result = refresh_market_themes(self.db_path, api_key="k", model="m", asset_class=CRYPTO)
        self.assertEqual(result["status"], "no_evidence")
        opener.assert_not_called()

    def test_no_api_key_writes_nothing_rather_than_a_bland_view(self):
        self.add_coin("BTC", "Top 20 by market cap")
        self.add_crypto_news("BTC", count=3)
        result = refresh_market_themes(self.db_path, api_key=None, model="m", asset_class=CRYPTO)
        self.assertEqual(result["status"], "not_available")

    def test_a_real_view_is_written_and_readable(self):
        self.add_coin("BTC", "Top 20 by market cap")
        self.add_crypto_news("BTC", count=3)
        with mock.patch("ai_trader.market_themes.urlopen", fake_openai({
            "Top 20 by market cap": {"outlook": "Cautious", "confidence": "Medium",
                                     "summary": "ETF inflows offset by inflation concerns.",
                                     "key_drivers": ["ETF inflows"], "key_risks": ["Inflation"]},
        })):
            result = refresh_market_themes(self.db_path, api_key="k", model="m", asset_class=CRYPTO)
        self.assertEqual(result["written"], 1)
        view = current_theme_view(self.db_path, "BTC", CRYPTO)
        assert view is not None
        self.assertEqual(view["outlook"], "Cautious")
        self.assertEqual(view["theme"], "Top 20 by market cap")

    def test_a_theme_the_model_declines_to_judge_is_left_alone(self):
        """Omission must mean 'no view', never a bland neutral one invented to fill a gap."""
        self.add_coin("BTC", "Top 20 by market cap")
        self.add_crypto_news("BTC", count=3)
        with mock.patch("ai_trader.market_themes.urlopen", fake_openai({})):
            result = refresh_market_themes(self.db_path, api_key="k", model="m", asset_class=CRYPTO)
        self.assertEqual(result["written"], 0)
        self.assertIsNone(current_theme_view(self.db_path, "BTC", CRYPTO))

    def test_a_failed_refresh_never_stops_research(self):
        self.add_coin("BTC", "Top 20 by market cap")
        self.add_crypto_news("BTC", count=3)
        with mock.patch("ai_trader.market_themes.urlopen", side_effect=OSError("network down")):
            result = refresh_market_themes(self.db_path, api_key="k", model="m", asset_class=CRYPTO)
        self.assertEqual(result["status"], "failed")

    def test_refreshing_the_same_theme_updates_rather_than_duplicating(self):
        self.add_coin("BTC", "Top 20 by market cap")
        self.add_crypto_news("BTC", count=3)
        for outlook in ("Cautious", "Constructive"):
            with mock.patch("ai_trader.market_themes.urlopen", fake_openai({
                "Top 20 by market cap": {"outlook": outlook, "confidence": "Medium", "summary": "s"},
            })):
                refresh_market_themes(self.db_path, api_key="k", model="m", asset_class=CRYPTO)
        with closing(connect(self.db_path)) as conn:
            count = conn.execute(
                "SELECT count(*) FROM MARKET_THEMES WHERE theme = 'Top 20 by market cap'"
            ).fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(current_theme_view(self.db_path, "BTC", CRYPTO)["outlook"], "Constructive")

    # --- staleness -----------------------------------------------------------------------

    def test_a_stale_view_is_treated_as_no_view(self):
        """The whole reason this module exists: 14 share themes asserted as current while two
        months old. Stale must read as absent, not as fact."""
        self.add_coin("BTC", "Top 20 by market cap")
        self.add_crypto_news("BTC", count=3)
        with mock.patch("ai_trader.market_themes.urlopen", fake_openai({
            "Top 20 by market cap": {"outlook": "Cautious", "confidence": "Medium", "summary": "s"},
        })):
            refresh_market_themes(self.db_path, api_key="k", model="m", asset_class=CRYPTO)
        old = (datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS[CRYPTO] + 5)).isoformat()
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute("UPDATE MARKET_THEMES SET last_updated = ?", (old,))
        self.assertIsNone(current_theme_view(self.db_path, "BTC", CRYPTO))

    def test_crypto_goes_stale_faster_than_shares(self):
        """Narratives rotate in weeks; sector outlooks turn over quarters."""
        self.assertLess(MAX_AGE_HOURS[CRYPTO], MAX_AGE_HOURS[EQUITY])


class MacroGateTests(unittest.TestCase):
    """The crypto macro check used to ask "does a research score exist for this coin?", which
    is circular -- it is checked while scoring the coin, so it always passed. A dimension that
    always passes measures nothing; it was contributing a full mark to every crypto verdict."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        initialize_foundation_schema(self.db_path)
        initialize_market_theme_schema(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def macro_available(self, symbol):
        from ai_trader.foundation import _macro_context_available
        from ai_trader.models import TradeProposal

        p = TradeProposal(
            symbol=symbol, side="buy", entry_price=100.0, stop_loss=98.0, take_profit=104.0,
            position_size=1.0, risk_percentage=0.005, confidence_score=0.79,
            news_summary="x", market_sentiment_summary="y", technical_summary="z",
            plain_english_reasoning="w", asset_type="crypto",
        ).normalized()
        with closing(connect(self.db_path)) as conn:
            return _macro_context_available(conn, p)

    def seed(self, symbol, category, outlook="Cautious", hours_old=1):
        now = datetime.now(timezone.utc)
        stamp = (now - timedelta(hours=hours_old)).isoformat()
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO CRYPTO_MASTER (symbol, name, category, source, active, created_at, updated_at)"
                    " VALUES (?, ?, ?, 'test', 1, ?, ?)",
                    (symbol, symbol, category, now.isoformat(), now.isoformat()),
                )
                conn.execute(
                    "INSERT INTO MARKET_THEMES (theme, asset_class, current_outlook, confidence,"
                    " summary, last_updated, created_at, updated_at)"
                    " VALUES (?, 'crypto', ?, 'Medium', 's', ?, ?, ?)",
                    (category, outlook, stamp, now.isoformat(), now.isoformat()),
                )

    def test_a_coin_with_a_current_theme_view_has_real_macro_context(self):
        self.seed("BTC", "Top 20 by market cap")
        self.assertTrue(self.macro_available("BTC"))

    def test_a_coin_with_no_theme_view_is_not_counted_rather_than_rubber_stamped(self):
        self.assertFalse(self.macro_available("BTC"))

    def test_a_stale_theme_view_does_not_count_as_macro_context(self):
        self.seed("BTC", "Top 20 by market cap", hours_old=MAX_AGE_HOURS[CRYPTO] + 10)
        self.assertFalse(self.macro_available("BTC"))


if __name__ == "__main__":
    unittest.main()
