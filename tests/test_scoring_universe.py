"""Scoring wider than trading, without ever widening what can be bought.

2026-08-31, Founder-directed: "please widen the research, but let's ensure that the coins
that the app looks at meet the classification type that we have set up", and before that,
"we just need to make sure that before we go ahead and make changes to the application, that
it's worth it".

Both halves matter and they pull in opposite directions. The point is to measure coins the
account cannot currently buy -- that is the only way to learn whether converting to USD would
be worth it -- while nothing about what may actually be traded changes. So the tests below
check that the universe grows AND that everything in it is either already tradeable or
explicitly marked as evidence only.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from ai_trader.operational import initialize_operational_schema
from ai_trader.scoring_universe import (
    build_scoring_universe,
    classified_symbols,
    universe_summary,
)

# A realistic slice of the Founder's own classification, including the duplication that is
# actually in production (the universe reports 702 rows for 59 coins).
CLASSIFIED = [
    ("BTC", "Top 20 by market cap"),
    ("BTC", "Top 20 by market cap"),
    ("BTC", "Top 20 by market cap"),
    ("ETH", "Top 20 by market cap"),
    ("SOL", "Top 20 by market cap"),
    ("TAO", "Top 20 AI coins"),
    ("RENDER", "Top 20 AI coins"),
    ("FET", "Top 20 AI coins"),
    ("XMR", "Top 20 security/privacy coins"),
    ("ARRR", "Top 20 security/privacy coins"),
    ("USDT", "Top 20 by market cap"),
    ("USDC", "Top 20 by market cap"),
]

# What Kraken lists: BTC/ETH/SOL in GBP, the AI coins and XMR in USD only, ARRR nowhere.
KNOWN_PAIRS = {
    "XBTGBP", "XBTUSD", "ETHGBP", "ETHUSD", "SOLGBP", "SOLUSD",
    "TAOUSD", "RENDERUSD", "FETUSD", "XMRUSD",
}


def _db(tmp: str) -> Path:
    db_path = Path(tmp) / "universe.db"
    initialize_operational_schema(db_path)
    # closing() as well as the transaction context: `with sqlite3.connect(...)` commits but
    # does NOT close, and an open handle makes Windows refuse to delete the temp directory --
    # which failed all eight of these tests before it failed anything real.
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for symbol, category in CLASSIFIED:
                conn.execute(
                    """INSERT INTO CRYPTO_ASSET_MASTER
                           (symbol, name, category, source, active, notes, last_updated)
                       VALUES (?, ?, ?, 'test', 1, '', '2026-08-31')""",
                    (symbol, symbol, category),
                )
    finally:
        conn.close()
    return db_path


def test_duplicate_rows_collapse_to_one_coin():
    """Production stores XMR 22 times. Every count taken from that table was inflated."""
    with tempfile.TemporaryDirectory() as tmp:
        classified = classified_symbols(_db(tmp))
        assert classified["BTC"] == "Top 20 by market cap"
        assert len([s for s in classified if s == "BTC"]) == 1
        assert len(classified) == 8, classified  # 10 distinct minus the two stablecoins


def test_stablecoins_are_never_scored():
    """A coin engineered not to move cannot produce a trade, so measuring it is waste."""
    with tempfile.TemporaryDirectory() as tmp:
        classified = classified_symbols(_db(tmp))
        assert "USDT" not in classified
        assert "USDC" not in classified


def test_gbp_is_preferred_when_a_coin_lists_in_both():
    """The account holds pounds. A coin available in GBP must never be scored in USD."""
    with tempfile.TemporaryDirectory() as tmp:
        targets = {t.symbol: t for t in build_scoring_universe(_db(tmp), KNOWN_PAIRS)}
        assert targets["BTC"].quote == "GBP"
        assert targets["BTC"].pair == "XBTGBP"
        assert targets["BTC"].tradeable_now is True


def test_usd_only_coins_are_scored_but_marked_as_evidence():
    """The whole point: measure what cannot be bought, without pretending it can be.

    A USD score being mistaken for a missed trading opportunity is the failure mode here --
    the account cannot buy it until the Founder converts.
    """
    with tempfile.TemporaryDirectory() as tmp:
        targets = {t.symbol: t for t in build_scoring_universe(_db(tmp), KNOWN_PAIRS)}
        assert targets["TAO"].quote == "USD"
        assert targets["TAO"].tradeable_now is False
        assert targets["XMR"].pair == "XMRUSD"


def test_a_coin_kraken_does_not_list_is_skipped_entirely():
    """16 of the 20 security/privacy coins are on no Kraken market in any currency.

    Guessing a pair that does not exist costs one wasted API call per symbol per cycle and
    writes nothing -- which is how a widened universe becomes slower rather than better
    informed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        symbols = {t.symbol for t in build_scoring_universe(_db(tmp), KNOWN_PAIRS)}
        assert "ARRR" not in symbols


def test_currently_traded_pairs_are_always_kept():
    """Whatever else is measured, the coins the app can actually buy must keep being
    measured -- even if the cap would otherwise crowd them out."""
    with tempfile.TemporaryDirectory() as tmp:
        targets = build_scoring_universe(
            _db(tmp), KNOWN_PAIRS, always_include=["SOL", "ETH"], limit=3
        )
        symbols = [t.symbol for t in targets]
        assert symbols[:2] == ["SOL", "ETH"], symbols
        assert len(targets) == 3


def test_an_unreadable_pair_list_falls_back_to_what_is_already_traded():
    """If Kraken cannot be asked what it lists, keep scoring the known-good pairs rather
    than inventing pairs that may not exist."""
    with tempfile.TemporaryDirectory() as tmp:
        targets = build_scoring_universe(_db(tmp), None, always_include=["SOL"])
        assert any(t.symbol == "SOL" for t in targets)


def test_the_summary_separates_tradeable_from_evidence():
    """The run log must show the widening, or it is indistinguishable from nothing changing."""
    with tempfile.TemporaryDirectory() as tmp:
        summary = universe_summary(build_scoring_universe(_db(tmp), KNOWN_PAIRS))
        assert summary["tradeable_now"] == 3          # BTC, ETH, SOL
        assert summary["evidence_only"] == 4          # TAO, RENDER, FET, XMR
        assert summary["total"] == 7
        assert "TAO" in summary["evidence_symbols"]
        assert "BTC" not in summary["evidence_symbols"]
