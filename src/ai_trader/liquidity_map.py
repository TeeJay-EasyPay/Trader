"""Where the real money is resting, and where it is actually trading.

2026-08-24, Founder-directed. Every entry signal this system had until now -- trend
score, momentum, RSI, price against moving averages -- is published free to every trader
alive. Something everyone can see cannot be an edge.

Two feeds change that, both free from Kraken's public API and almost never read
systematically by retail:

- The order book: real money committed at real prices. It answers "where are the buyers"
  with money rather than with a line drawn on a chart. Measured live on XRPGBP the day
  this was written: over £1m of resting bids between the mid and -3.5%, then a cliff --
  £8.3k at -3.5%, £1.3k at -4%, £416 at -5%. A break below that shelf has nothing
  underneath it, which is a completely different risk to a break that has to eat a wall.

- The executed tape: what actually changed hands, and which side was the aggressor. The
  book is only intent and can be withdrawn; the tape is money that committed.

Read together they catch what neither shows alone -- a wall that disappears before
anything trades through it (spoofing), which is precisely why the book is never trusted
on its own here.

Same discipline as symbol_track_record.py: this may lower conviction or stand aside, and
may never raise conviction. Market structure is a risk input, not an invitation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# How far either side of the mid price is worth mapping. Beyond this the resting orders
# are too far away to matter for a trade measured in hours or days.
DEPTH_RANGE_PCT = 8.0

# Width of each price bucket when clustering resting orders, in percent from mid. Fine
# enough to separate a real wall from its neighbours, coarse enough that one large order
# split across ten ticks still reads as the single wall it actually is.
BUCKET_PCT = 0.5

# A bucket holding at least this multiple of the average bucket is a wall, not noise.
WALL_MULTIPLE = 2.5

# Below this share of the average bucket, a price band is an air pocket: nothing resting
# there to slow a move through it.
AIR_POCKET_FRACTION = 0.15

# The band touching the mid price always holds the tightest orders and so almost always
# clears the wall test -- reporting it as a "ceiling 0.0% above" would fire on nearly
# every pair and penalise everything equally, which is the same as penalising nothing.
# A wall has to be far enough away to be a level rather than the spread.
MIN_WALL_DISTANCE_PCT = 0.5

# The most conviction market structure may remove, matching symbol_track_record.py's cap
# so no single input can dominate the decision.
MAX_CONFIDENCE_PENALTY = 0.20


@dataclass(frozen=True)
class LiquidityMap:
    pair: str
    mid_price: float
    spread_pct: float
    bid_walls: list[dict[str, Any]] = field(default_factory=list)
    ask_walls: list[dict[str, Any]] = field(default_factory=list)
    air_pockets_below: list[dict[str, Any]] = field(default_factory=list)
    support_floor_pct: float | None = None      # how far down real bid support extends
    nearest_ask_wall_pct: float | None = None   # overhead supply between here and target
    buy_notional: float = 0.0
    sell_notional: float = 0.0
    aggressor_buy_share: float | None = None
    large_trades: list[dict[str, Any]] = field(default_factory=list)
    verdict: str = "unknown"                    # "unknown"|"supportive"|"caution"|"avoid"
    confidence_penalty: float = 0.0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair": self.pair,
            "mid_price": self.mid_price,
            "spread_pct": self.spread_pct,
            "bid_walls": self.bid_walls,
            "ask_walls": self.ask_walls,
            "air_pockets_below": self.air_pockets_below,
            "support_floor_pct": self.support_floor_pct,
            "nearest_ask_wall_pct": self.nearest_ask_wall_pct,
            "buy_notional": round(self.buy_notional, 2),
            "sell_notional": round(self.sell_notional, 2),
            "aggressor_buy_share": self.aggressor_buy_share,
            "large_trades": self.large_trades,
            "verdict": self.verdict,
            "confidence_penalty": self.confidence_penalty,
            "summary": self.summary,
        }


def _levels(rows: Any) -> list[tuple[float, float]]:
    """Kraken returns [price, volume, timestamp] as strings; anything unparseable is
    dropped rather than allowed to poison an average."""
    out: list[tuple[float, float]] = []
    for row in rows or []:
        try:
            price = float(row[0])
            volume = float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        if price > 0 and volume > 0:
            out.append((price, volume))
    return out


def _bucket_side(levels: list[tuple[float, float]], mid: float, *, below: bool) -> dict[float, float]:
    """Cluster one side of the book into price bands, valued in quote currency.

    Valued as price*volume, not raw volume: £300k resting is £300k of intent whatever the
    coin's unit price, and it makes walls comparable across pairs.
    """
    buckets: dict[float, float] = {}
    for price, volume in levels:
        distance_pct = (price - mid) / mid * 100.0
        if below and distance_pct > 0:
            continue
        if not below and distance_pct < 0:
            continue
        if abs(distance_pct) > DEPTH_RANGE_PCT:
            continue
        band = round((abs(distance_pct) // BUCKET_PCT) * BUCKET_PCT, 4)
        buckets[band] = buckets.get(band, 0.0) + price * volume
    return buckets


def _walls(buckets: dict[float, float], *, side: str) -> list[dict[str, Any]]:
    if not buckets:
        return []
    average = sum(buckets.values()) / len(buckets)
    if average <= 0:
        return []
    walls = [
        {"distance_pct": band, "notional": round(notional, 2), "multiple_of_average": round(notional / average, 2), "side": side}
        for band, notional in buckets.items()
        if notional >= average * WALL_MULTIPLE and band >= MIN_WALL_DISTANCE_PCT
    ]
    return sorted(walls, key=lambda item: item["distance_pct"])


def _air_pockets(buckets: dict[float, float]) -> list[dict[str, Any]]:
    """Bands with almost nothing resting in them, below the deepest real support.

    Only reported past the point where support genuinely thins out -- an empty band
    sandwiched between two walls is not an air pocket, it is a gap the walls still guard.
    """
    if not buckets:
        return []
    average = sum(buckets.values()) / len(buckets)
    if average <= 0:
        return []
    floor = _support_floor(buckets)
    if floor is None:
        return []
    return [
        {"distance_pct": band, "notional": round(notional, 2)}
        for band, notional in sorted(buckets.items())
        if band > floor and notional < average * AIR_POCKET_FRACTION
    ]


def _support_floor(buckets: dict[float, float]) -> float | None:
    """How far down meaningful bid support actually extends.

    Walks outward from the mid and stops at the first band holding less than the air
    pocket threshold -- the shelf edge in the XRP reading above, where £374k at -3% is
    followed by £8.3k at -3.5%.
    """
    if not buckets:
        return None
    average = sum(buckets.values()) / len(buckets)
    if average <= 0:
        return None
    floor = None
    for band in sorted(buckets):
        if buckets[band] < average * AIR_POCKET_FRACTION:
            break
        floor = band
    return floor


def analyse_order_book(pair: str, bids: Any, asks: Any) -> dict[str, Any]:
    bid_levels = _levels(bids)
    ask_levels = _levels(asks)
    if not bid_levels or not ask_levels:
        return {}
    best_bid = max(price for price, _ in bid_levels)
    best_ask = min(price for price, _ in ask_levels)
    if best_ask <= 0 or best_bid <= 0:
        return {}
    mid = (best_bid + best_ask) / 2.0
    bid_buckets = _bucket_side(bid_levels, mid, below=True)
    ask_buckets = _bucket_side(ask_levels, mid, below=False)
    ask_walls = _walls(ask_buckets, side="ask")
    return {
        "pair": pair,
        "mid_price": round(mid, 8),
        "spread_pct": round((best_ask - best_bid) / mid * 100.0, 4),
        "bid_walls": _walls(bid_buckets, side="bid"),
        "ask_walls": ask_walls,
        "air_pockets_below": _air_pockets(bid_buckets),
        "support_floor_pct": _support_floor(bid_buckets),
        "nearest_ask_wall_pct": ask_walls[0]["distance_pct"] if ask_walls else None,
    }


def analyse_trade_tape(trades: Any, *, large_trade_notional: float = 500.0) -> dict[str, Any]:
    """Which side was the aggressor, and where the size actually went through."""
    buy_notional = sell_notional = 0.0
    large: list[dict[str, Any]] = []
    for row in trades or []:
        try:
            price = float(row[0])
            volume = float(row[1])
            timestamp = float(row[2])
            side = str(row[3])
        except (TypeError, ValueError, IndexError):
            continue
        notional = price * volume
        if side == "b":
            buy_notional += notional
        else:
            sell_notional += notional
        if notional >= large_trade_notional:
            large.append({
                "side": "buy" if side == "b" else "sell",
                "notional": round(notional, 2),
                "price": price,
                "timestamp": timestamp,
            })
    total = buy_notional + sell_notional
    return {
        "buy_notional": buy_notional,
        "sell_notional": sell_notional,
        "aggressor_buy_share": round(buy_notional / total, 4) if total > 0 else None,
        "large_trades": large[-10:],
    }


def liquidity_map(pair: str, *, bids: Any, asks: Any, trades: Any = None) -> LiquidityMap:
    """Combine resting orders and executed trades into one read on a buy entry."""
    book = analyse_order_book(pair, bids, asks)
    if not book:
        return LiquidityMap(pair=pair, mid_price=0.0, spread_pct=0.0, verdict="unknown",
                            summary="No usable order book for this pair.")
    tape = analyse_trade_tape(trades)

    reasons: list[str] = []
    penalty = 0.0
    verdict = "supportive"

    floor = book["support_floor_pct"]
    nearest_ask = book["nearest_ask_wall_pct"]
    buy_share = tape["aggressor_buy_share"]

    # Thin support underneath: a fall has nothing to slow it.
    if floor is not None and floor <= 1.0:
        verdict = "avoid"
        penalty = MAX_CONFIDENCE_PENALTY
        reasons.append(f"real bid support ends {floor:.1f}% below the price - nothing underneath to catch a fall")
    elif floor is not None and floor <= 2.0:
        verdict = "caution"
        penalty = max(penalty, MAX_CONFIDENCE_PENALTY * 0.5)
        reasons.append(f"bid support only extends {floor:.1f}% down")

    # Overhead supply sitting between the entry and any sensible target.
    if nearest_ask is not None and nearest_ask <= 1.0:
        verdict = "avoid" if verdict == "avoid" else "caution"
        penalty = max(penalty, MAX_CONFIDENCE_PENALTY * 0.75)
        reasons.append(f"a sell wall sits just {nearest_ask:.1f}% above - the move has a ceiling before it starts")
    elif nearest_ask is not None and nearest_ask <= 2.0:
        verdict = "caution" if verdict == "supportive" else verdict
        penalty = max(penalty, MAX_CONFIDENCE_PENALTY * 0.4)
        reasons.append(f"a sell wall sits {nearest_ask:.1f}% above and will have to be absorbed on the way up")

    # Sellers doing the hitting. Weak on its own, meaningful stacked on thin support.
    if buy_share is not None and buy_share < 0.4:
        verdict = "caution" if verdict == "supportive" else verdict
        penalty = max(penalty, MAX_CONFIDENCE_PENALTY * 0.4)
        reasons.append(f"sellers are the aggressors in recent trades ({buy_share:.0%} of traded value was buying)")

    if not reasons:
        floor_text = f"{floor:.1f}%" if floor is not None else "an unclear distance"
        reasons.append(f"real bid support extends {floor_text} below the price with no sell wall immediately overhead")

    return LiquidityMap(
        pair=pair,
        mid_price=book["mid_price"],
        spread_pct=book["spread_pct"],
        bid_walls=book["bid_walls"],
        ask_walls=book["ask_walls"],
        air_pockets_below=book["air_pockets_below"],
        support_floor_pct=floor,
        nearest_ask_wall_pct=nearest_ask,
        buy_notional=tape["buy_notional"],
        sell_notional=tape["sell_notional"],
        aggressor_buy_share=buy_share,
        large_trades=tape["large_trades"],
        verdict=verdict,
        confidence_penalty=round(penalty, 4),
        summary="; ".join(reasons),
    )


def liquidity_map_for_pair(adapter: Any, pair: str) -> LiquidityMap | None:
    """Fetch and analyse, tolerating an adapter that cannot supply either feed."""
    book_reader = getattr(adapter, "order_book", None)
    if not callable(book_reader):
        return None
    book = book_reader(pair)
    if not book:
        return None
    tape_reader = getattr(adapter, "recent_trades", None)
    trades = tape_reader(pair) if callable(tape_reader) else None
    return liquidity_map(pair, bids=book.get("bids"), asks=book.get("asks"), trades=trades)
