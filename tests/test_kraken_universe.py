"""The universe comes from the exchange, not from a coin database.

2026-08-31, Founder-directed: "rebuild the universe kraken first anyway... whenever a new
exchange is added, its broker should look at that exchange first. not sure what the benefit
of coingecko is."

The old order asked CoinGecko what exists, then discarded 24 of 56 answers because Kraken
does not list them -- including 16 of the 20 privacy coins. Asking the exchange first means
everything selected is, by construction, something an order could be placed for.
"""

from __future__ import annotations

from ai_trader.kraken_universe import (
    KrakenMarket,
    normalise_asset,
    select_universe,
    universe_rows,
)


def _m(symbol, quote, turnover, pair=None):
    return KrakenMarket(symbol=symbol, pair=pair or f"{symbol}{quote}", quote=quote,
                        turnover_24h=turnover)


def test_krakens_legacy_asset_codes_are_normalised():
    # XXBT and XBT are both Bitcoin. Treating them as different coins would double-count the
    # single most liquid market on the exchange.
    assert normalise_asset("XXBT") == "BTC"
    assert normalise_asset("XXDG") == "DOGE"
    assert normalise_asset("SOL") == "SOL"


def test_the_account_currency_wins_even_when_the_dollar_book_is_deeper():
    """A GBP market needs no conversion, so it is preferred on a tie of usefulness.

    Measured live: BTC has a GBP book at ~2.4m and a far deeper USD one. Buying the USD
    market would mean converting first, which is a second fee on a strategy already losing
    to costs.
    """
    chosen = select_universe([_m("BTC", "USD", 50_000_000), _m("BTC", "GBP", 2_376_733)])
    assert len(chosen) == 1
    assert chosen[0].quote == "GBP"


def test_the_deeper_book_wins_between_two_markets_in_the_same_currency():
    chosen = select_universe([_m("ZEC", "USD", 1_000), _m("ZEC", "USD", 23_199_700, pair="XZECZUSD")])
    assert chosen[0].pair == "XZECZUSD"


def test_illiquid_markets_are_excluded():
    """GRT's GBP book turns over 135 a day. A 50 order is a third of daily volume.

    With a round trip already costing ~1.6%, a book this thin cannot produce a trade that
    pays for itself -- the spread alone would take the rest.
    """
    chosen = select_universe([_m("BTC", "GBP", 2_376_733), _m("GRT", "GBP", 135)],
                             min_turnover=100_000)
    assert [m.symbol for m in chosen] == ["BTC"]


def test_currently_permitted_coins_survive_the_liquidity_filter():
    """Whatever else changes, the coins the app may already trade stay in its own universe.

    Dropping them would silently shrink what it can buy, which is a trading change disguised
    as a data change -- exactly the kind of thing that has gone unnoticed here before.
    """
    chosen = select_universe([_m("BTC", "GBP", 2_376_733), _m("GRT", "GBP", 135)],
                             min_turnover=100_000, always_include={"GRT"})
    assert {m.symbol for m in chosen} == {"BTC", "GRT"}


def test_required_coins_are_never_crowded_out_by_the_cap():
    markets = [_m(f"C{i}", "USD", 1_000_000 - i) for i in range(10)] + [_m("GRT", "GBP", 135)]
    chosen = select_universe(markets, min_turnover=1_000, limit=3, always_include={"GRT"})
    assert "GRT" in {m.symbol for m in chosen}


def test_ranking_is_by_turnover_not_alphabet_or_market_cap():
    chosen = select_universe([_m("AAA", "USD", 1_000), _m("ZZZ", "USD", 9_000_000)],
                             min_turnover=100)
    assert [m.symbol for m in chosen] == ["ZZZ", "AAA"]


def test_rows_keep_the_coingecko_label_where_one_exists():
    """CoinGecko's remaining job is labelling, applied to a list Kraken already vouched for."""
    rows = universe_rows([_m("TAO", "USD", 5_000_000)],
                         category_by_symbol={"TAO": "Top 20 AI coins"})
    assert rows[0]["category"] == "Top 20 AI coins"
    assert "needs USD conversion" in rows[0]["notes"]


def test_an_unlabelled_but_tradeable_coin_is_still_included():
    """A coin the exchange lists but CoinGecko has not categorised is still tradeable, and a
    tradeable unlabelled coin beats a labelled one that cannot be bought."""
    rows = universe_rows([_m("PEPE", "GBP", 500_000)], category_by_symbol={})
    assert rows[0]["symbol"] == "PEPE"
    assert rows[0]["category"].startswith("Kraken")
    assert "needs USD conversion" not in rows[0]["notes"]
