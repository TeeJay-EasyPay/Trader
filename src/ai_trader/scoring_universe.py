"""Which coins the app SCORES, as distinct from which it is allowed to TRADE.

2026-08-31, Founder-directed: "please widen the research, but let's ensure that the coins
that the app looks at meet the classification type that we have set up", and before that,
"we just need to make sure that before we go ahead and make changes to the application, that
it's worth it".

The two lists were the same list, and that was the whole problem. Both scoring and research
took their symbols from KRAKEN_ALLOWED_PAIRS -- the 19 GBP pairs -- so the app could only
ever form an opinion about coins it was already permitted to buy. Asked whether a wider
universe would produce more trades, there was no evidence either way, because nothing outside
those 19 had ever been measured.

Separating them makes that answerable at no risk. Scoring costs API calls and writes a row;
it places no orders and creates no proposals. So the scoring universe widens to everything in
the Founder's own classification that Kraken actually lists, while the trading universe stays
exactly where it was until the evidence justifies moving it.

THE CLASSIFICATION IS HIS, NOT INVENTED HERE. CRYPTO_ASSET_MASTER holds three categories he
set up -- "Top 20 by market cap", "Top 20 AI coins", "Top 20 security/privacy coins" -- and
this reads them rather than substituting a judgement of its own.

Two findings from the audit that produced this module, both worth knowing before reading the
numbers it generates:

  * The universe reports 702 coins and contains 59. Repeated refreshes inserted duplicate
    rows (XMR is stored 22 times), so every count taken from it has been inflated roughly
    twelvefold. Deduplicated here.
  * Of 56 classified coins excluding stablecoins, 24 are not listed on Kraken in ANY
    currency, and 16 of those are the security/privacy category. That part of the
    classification cannot be acted on whatever else changes, so scoring it would burn API
    calls to measure things that can never be bought.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .database import connect
from .operational import is_stablecoin

# Preference order. GBP first because that is the account's currency and needs no conversion;
# USD second because it is where most of the Founder's AI category actually lists, and
# scoring it is how we find out whether converting would be worth it.
QUOTE_PREFERENCE = ("GBP", "USD")

# A ceiling on API calls per cycle, not a view about how many coins are interesting. Each
# symbol costs an OHLC fetch plus an order-book read; the previous hard cap was 30 and the
# classified, listed universe is comfortably inside this.
MAX_SCORING_SYMBOLS = 80


@dataclass(frozen=True)
class ScoringTarget:
    symbol: str
    pair: str
    quote: str
    category: str | None

    @property
    def tradeable_now(self) -> bool:
        """Whether an order in this pair could actually be placed today.

        USD targets are scored for evidence only: the account holds GBP, so nothing can be
        bought in USD until the Founder converts. Keeping the distinction explicit stops a
        USD score being mistaken for a missed trading opportunity.
        """
        return self.quote == "GBP"


def classified_symbols(db_path: Path) -> dict[str, str]:
    """The Founder's classified coins, deduplicated, mapped to their category."""
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute(
                """SELECT symbol, category FROM CRYPTO_ASSET_MASTER
                   WHERE active = 1 AND symbol IS NOT NULL"""
            ).fetchall()
    except Exception:  # noqa: BLE001 - a scoring universe must never break the cycle
        return {}
    out: dict[str, str] = {}
    for row in rows:
        symbol = str(row[0] or "").upper().strip()
        if not symbol or is_stablecoin(symbol):
            continue
        # First category wins; a coin in several categories is still one coin to score.
        out.setdefault(symbol, str(row[1] or "") or "uncategorised")
    return out


def build_scoring_universe(
    db_path: Path,
    known_pairs: set[str] | None,
    *,
    always_include: list[str] | None = None,
    limit: int = MAX_SCORING_SYMBOLS,
) -> list[ScoringTarget]:
    """Classified coins Kraken actually lists, GBP preferred, USD for evidence.

    `known_pairs` is what Kraken reports as tradeable. When it cannot be read the result
    falls back to `always_include` only -- guessing a pair that does not exist wastes a call
    per symbol per cycle and writes nothing, which is how a widened universe would quietly
    become slower rather than better informed.
    """
    classified = classified_symbols(db_path)
    targets: dict[str, ScoringTarget] = {}

    def _add(symbol: str, category: str | None) -> None:
        symbol = symbol.upper().strip()
        if not symbol or symbol in targets or is_stablecoin(symbol):
            return
        base = "XBT" if symbol == "BTC" else symbol
        for quote in QUOTE_PREFERENCE:
            pair = f"{base}{quote}"
            if known_pairs is None or pair.upper() in known_pairs:
                targets[symbol] = ScoringTarget(symbol=symbol, pair=pair, quote=quote,
                                                category=category)
                return

    # The currently-traded pairs come first and are never dropped by the cap: whatever else
    # is measured, the coins the app can actually buy must keep being measured.
    for symbol in always_include or []:
        _add(symbol, classified.get(symbol.upper()))
    for symbol, category in sorted(classified.items()):
        if len(targets) >= limit:
            break
        _add(symbol, category)
    return list(targets.values())[:limit]


def universe_summary(targets: list[ScoringTarget]) -> dict[str, Any]:
    """Counts for the run log, so the widening is visible rather than assumed."""
    tradeable = [t for t in targets if t.tradeable_now]
    evidence = [t for t in targets if not t.tradeable_now]
    by_category: dict[str, int] = {}
    for target in targets:
        by_category[target.category or "uncategorised"] = by_category.get(target.category or "uncategorised", 0) + 1
    return {
        "total": len(targets),
        "tradeable_now": len(tradeable),
        "evidence_only": len(evidence),
        "by_category": by_category,
        "evidence_symbols": sorted(t.symbol for t in evidence),
    }
