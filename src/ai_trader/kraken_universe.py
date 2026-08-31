"""Build the tradeable universe from the exchange, not from a coin database.

2026-08-31, Founder-directed: "rebuild the universe kraken first anyway... whenever a new
exchange is added, its broker should look at that exchange first. not sure what the benefit
of coingecko is."

He is right, and the old order was backwards. The universe was assembled from three CoinGecko
category endpoints (top 20 by market cap, top 20 AI, top 20 privacy) and then filtered against
what Kraken lists -- so 24 of 56 classified coins were discarded because the exchange does not
carry them, including 16 of the 20 privacy coins. We were asking a directory what exists and
then discovering we could not buy most of it.

Asking the exchange first inverts that: everything returned here is, by construction,
something an order could be placed for. CoinGecko keeps a job -- labelling a coin as AI or
privacy is genuinely useful and Kraken does not publish it -- but as enrichment on a list the
exchange already vouched for, never as the source of the list.

WHY TURNOVER RATHER THAN MARKET CAP. Kraken lists 638 USD pairs, and most are thin. Measured
on a 226-pair sample: 14 pairs above $1m of 24h turnover, 57 above $100k. Market cap says how
large a project is; turnover says whether this exchange can fill an order in it without the
spread eating the trade. With a round trip already costing about 1.6%, a wide spread is not a
detail -- it is the difference between a setup that clears the fee hurdle and one that cannot.
So the ranking is Kraken's own traded volume, which is also the only liquidity number that
describes the venue actually being used.

Note for whoever adds the next exchange: this module is deliberately Kraken-specific rather
than a general abstraction. One exchange is not a pattern. When Alpaca or a third venue needs
the same treatment, the shared shape will be obvious from two real implementations and can be
extracted then, rather than guessed at now.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

KRAKEN_PUBLIC = "https://api.kraken.com/0/public"

# Fiat and stablecoin quote assets, in the order the account prefers them. GBP first because
# that is what the account holds and needs no conversion; USD second because that is where
# Kraken's depth actually is (638 pairs against 26).
QUOTE_ASSETS = {"ZGBP": "GBP", "ZUSD": "USD"}

# Bases that are themselves fiat or stablecoins. A pair like USDCGBP is a currency
# conversion, not a trade idea, and scoring it wastes a call on something that cannot move.
NON_TRADEABLE_BASES = {
    "ZUSD", "ZGBP", "ZEUR", "ZAUD", "ZCAD", "ZJPY", "CHF",
    "USDC", "USDT", "USDS", "USDG", "DAI", "PYUSD", "RLUSD", "EURT", "EURC", "TUSD",
}

# Kraken's legacy X-prefixed asset codes.
_ALIAS = {
    "XXBT": "BTC", "XBT": "BTC", "XETH": "ETH", "XXRP": "XRP", "XXLM": "XLM",
    "XXDG": "DOGE", "XLTC": "LTC", "XXMR": "XMR", "XZEC": "ZEC", "XREP": "REP",
    "XETC": "ETC", "XMLN": "MLN", "XICN": "ICN",
}


def normalise_asset(code: Any) -> str:
    text = str(code or "").upper().strip()
    return _ALIAS.get(text, text)


@dataclass(frozen=True)
class KrakenMarket:
    symbol: str
    pair: str
    quote: str
    turnover_24h: float

    @property
    def tradeable_in_account_currency(self) -> bool:
        """GBP markets can be bought today; USD needs a conversion first."""
        return self.quote == "GBP"


def _get(url: str, timeout: float) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "ai-trader"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError(f"Kraken error: {payload['error']}")
    return payload.get("result") or {}


def fetch_kraken_markets(*, timeout: float = 45.0, quotes: dict[str, str] | None = None,
                         batch_size: int = 100) -> list[KrakenMarket]:
    """Every online Kraken market in the wanted quote currencies, with 24h turnover.

    Returns [] rather than raising if Kraken cannot be reached. The universe refresh runs
    hourly and an empty result leaves the previous universe in place, which is the right
    failure: trading on a stale-but-real list beats trading on nothing.
    """
    quotes = quotes or QUOTE_ASSETS
    try:
        pairs = _get(f"{KRAKEN_PUBLIC}/AssetPairs", timeout)
    except (URLError, RuntimeError, ValueError, OSError):
        return []

    wanted: dict[str, tuple[str, str]] = {}
    for name, info in pairs.items():
        if str(info.get("status")) != "online":
            continue
        quote_code = str(info.get("quote") or "")
        if quote_code not in quotes:
            continue
        base = normalise_asset(info.get("base"))
        if not base or base in NON_TRADEABLE_BASES:
            continue
        wanted[str(name)] = (base, quotes[quote_code])

    # Ticker is batched: one call per 100 pairs rather than one per pair, because this runs
    # hourly against a public endpoint and a per-pair loop would be several hundred calls.
    markets: list[KrakenMarket] = []
    names = list(wanted)
    for start in range(0, len(names), batch_size):
        chunk = names[start:start + batch_size]
        try:
            ticker = _get(f"{KRAKEN_PUBLIC}/Ticker?pair={','.join(chunk)}", timeout)
        except (URLError, RuntimeError, ValueError, OSError):
            continue
        for name, data in ticker.items():
            if name not in wanted:
                continue
            base, quote = wanted[name]
            markets.append(KrakenMarket(
                symbol=base, pair=name, quote=quote,
                turnover_24h=_turnover(data),
            ))
    return markets


def _turnover(ticker_row: Any) -> float:
    """24h volume valued at the 24h VWAP, in the quote currency.

    Volume alone is not comparable across coins -- a million DOGE and a million BTC are not
    the same market -- so it is multiplied by the average traded price to give a figure that
    can be ranked.
    """
    try:
        volume = float(ticker_row["v"][1])
        vwap = float(ticker_row["p"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0
    value = volume * vwap
    return value if value > 0 else 0.0


def select_universe(
    markets: list[KrakenMarket],
    *,
    min_turnover: float = 100_000.0,
    limit: int = 80,
    always_include: set[str] | None = None,
) -> list[KrakenMarket]:
    """The most liquid market per coin, ranked by turnover.

    One market per symbol: a coin listed in both GBP and USD is one trade idea, and the
    account's own currency wins ties even when the USD book is deeper, because buying it
    needs no conversion.
    """
    always_include = {s.upper() for s in (always_include or set())}
    best: dict[str, KrakenMarket] = {}
    for market in markets:
        current = best.get(market.symbol)
        if current is None:
            best[market.symbol] = market
            continue
        # Prefer the account currency; otherwise the deeper book.
        if market.tradeable_in_account_currency and not current.tradeable_in_account_currency:
            best[market.symbol] = market
        elif market.tradeable_in_account_currency == current.tradeable_in_account_currency \
                and market.turnover_24h > current.turnover_24h:
            best[market.symbol] = market

    ranked = sorted(best.values(), key=lambda m: m.turnover_24h, reverse=True)
    kept = [m for m in ranked if m.turnover_24h >= min_turnover or m.symbol in always_include]
    # Anything explicitly required stays even if the cap would drop it: the coins the app is
    # already permitted to trade must never fall out of its own universe.
    required = [m for m in kept if m.symbol in always_include]
    rest = [m for m in kept if m.symbol not in always_include]
    return (required + rest)[:max(limit, len(required))]


def universe_rows(markets: list[KrakenMarket], *, category_by_symbol: dict[str, str] | None = None,
                  source: str = "Kraken public AssetPairs/Ticker") -> list[dict[str, Any]]:
    """Rows shaped for CRYPTO_ASSET_MASTER.

    `category_by_symbol` is CoinGecko's remaining job: it labels a coin as AI or privacy,
    which Kraken does not publish and which the Founder's classification is built on. A coin
    Kraken lists but CoinGecko has not categorised is still included -- the exchange listing
    it is what makes it tradeable, and an unlabelled tradeable coin beats a labelled one that
    cannot be bought.
    """
    category_by_symbol = category_by_symbol or {}
    rows: list[dict[str, Any]] = []
    for rank, market in enumerate(markets, start=1):
        rows.append({
            "symbol": market.symbol,
            "name": market.symbol,
            "category": category_by_symbol.get(market.symbol, f"Kraken {market.quote} market"),
            "market_cap_rank": rank,
            "source": source,
            "notes": (
                f"{market.pair} - 24h turnover {market.turnover_24h:,.0f} {market.quote}"
                f"{'' if market.tradeable_in_account_currency else ' (needs USD conversion)'}"
            ),
        })
    return rows
