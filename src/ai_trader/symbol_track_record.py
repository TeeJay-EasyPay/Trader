"""What this system's own money has actually done, per coin.

2026-08-24, Founder-directed. Every signal driving entries until now -- trend score,
momentum, RSI, price against moving averages -- is the most widely published data that
exists. Everyone trading these coins can see all of it, which is precisely why none of
it can be an edge.

This is the one input nobody else has: the realised outcome of this system's own trades,
at its own fees, on its own fills, per coin. It was already being recorded in
PERFORMANCE_ATTRIBUTION and already aggregated for review -- but only by strategy_id.
Nothing ever asked "how have we actually done on THIS coin", so the system could lose on
SOL five times running and walk into the sixth at full confidence. Confirmed live that
day across 38 closed trades: SOL 0 wins from 5, LINK 0 from 3, ADA 0 from 2 and the
largest single loss, against ETH 6 from 8 and XRP 4 from 5.

Two things this deliberately does NOT do:

- It does not ban a coin permanently. A losing run is not proof a coin is untradeable,
  and a rule learned from five trades is a rule learned from noise. Evidence expires
  (LOOKBACK_DAYS) and the sample floor below is a floor, not a target.
- It does not raise confidence on winners. Rewarding a hot streak is how a small sample
  becomes a large position at the worst possible moment. This can only ever lower
  conviction or stand aside.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .database import connect

# Only the recent past counts. A coin that behaved badly in a different market regime
# should stop being held against it once the evidence ages out.
LOOKBACK_DAYS = 45

# 2026-09-03, Founder-directed: "do the first item please" -- only judge the current rules by
# trades taken under the current rules.
#
# WHY THIS EXISTS. Crypto had stopped trading entirely. Research ran every cycle and ideas were
# generated, but every one was refused with confidence_below_minimum. The cause was this file:
# a coin that has lost money loses up to MAX_CONFIDENCE_PENALTY of confidence, so a coin
# scoring 0.72 arrived at the 0.70 bar on 0.47 and was refused. ADA, LINK and SOL were 0 from
# 2, 0 from 3 and 0 from 6, which is the full penalty each.
#
# Those losses were the FEE PROBLEM, not bad coin selection: trades aiming at moves smaller
# than the 1.54% round trip cost, so they lost whether the call was right or wrong. That defect
# is fixed -- a proposal must now clear its own costs before it can be made. But the penalty
# kept punishing the app for losses made under rules that no longer exist, and it could never
# recover, because the penalty only lifts when a coin wins and a coin cannot win if it is never
# traded. A doom loop with no exit.
#
# THE DATE IS 31 AUGUST, NOT 20 AUGUST, and the difference matters. The fee gate shipped on
# 2026-08-20, but it measures the fee rate from settled trades and defaults to INACTIVE when it
# cannot measure one (see trade_scorecard.estimate_round_trip_fee_pct). The first trade with a
# recorded fee settled 2026-08-31, so the gate could not have refused anything before then. The
# honest boundary is when the rule started working, not when it was written.
#
# Older trades are NOT deleted and still appear everywhere else. They simply stop driving this
# one penalty.
FEE_GATE_EFFECTIVE_FROM = "2026-08-31T00:00:00+00:00"

# Below this, a record is an anecdote. Three losses could be one bad week.
MIN_TRADES_FOR_SIGNAL = 3

# Standing aside entirely needs more than the minimum: a clean sweep of losses over a
# sample that is at least this size, and real money lost.
MIN_TRADES_FOR_AVOID = 4

# The most conviction a bad record may remove. Never 100%: this is one input among many,
# and the technical picture is allowed to disagree with it.
MAX_CONFIDENCE_PENALTY = 0.25


@dataclass(frozen=True)
class SymbolRecord:
    symbol: str
    trades: int
    wins: int
    losses: int
    net_profit_loss: float
    win_rate: float | None
    verdict: str          # "avoid" | "caution" | "neutral" | "insufficient_evidence"
    confidence_penalty: float
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "net_profit_loss": round(self.net_profit_loss, 2),
            "win_rate": self.win_rate,
            "verdict": self.verdict,
            "confidence_penalty": self.confidence_penalty,
            "summary": self.summary,
        }


def normalize_symbol(symbol: str) -> str:
    """Reduce a traded symbol to the coin itself.

    The same coin is recorded under several names depending on which code path wrote the
    row -- confirmed live in PERFORMANCE_ATTRIBUTION on 2026-08-24: SOL and SOLGBP, BTC
    and XBTGBP, XRP and XRPGBP all present, splitting one coin's record into two. Any
    per-coin logic that skips this step reads half a history and quietly learns nothing,
    which is the failure mode this module exists to prevent.
    """
    text = str(symbol or "").upper().strip().replace("/", "").replace("-", "")
    for quote in ("GBP", "USDT", "USDC", "USD", "EUR"):
        # Only strip a quote currency off the end, and never strip a symbol down to
        # nothing (the coin "USD" itself must survive).
        if text.endswith(quote) and len(text) > len(quote):
            text = text[: -len(quote)]
            break
    aliases = {"XBT": "BTC", "XXBT": "BTC", "XETH": "ETH", "XXRP": "XRP", "XLTC": "LTC", "XXLM": "XLM"}
    return aliases.get(text, text)


def _at_or_after(observed_at: Any, cutoff_iso: str) -> bool:
    """Is this trade at or after the cutoff, whatever format its timestamp is stored in?

    NOT a string comparison, and that is deliberate. 26 of the 66 rows in
    PERFORMANCE_ATTRIBUTION store an epoch integer ("1787586949") rather than an ISO date, and
    "1787586949" sorts BEFORE "2026-08-31" because "1" < "2". A plain SQL >= would therefore
    have silently dropped every epoch-stamped trade -- which is most of the recent ones -- and
    the change would have looked like it worked while measuring something else entirely.
    """
    if observed_at is None:
        return False
    text = str(observed_at).strip()
    if not text:
        return False
    try:
        cutoff_dt = datetime.fromisoformat(cutoff_iso)
    except ValueError:
        return True
    # Epoch seconds, stored as a number or a numeric string.
    if text.replace(".", "", 1).isdigit():
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc) >= cutoff_dt
        except (OverflowError, OSError, ValueError):
            return False
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment >= cutoff_dt


def symbol_track_record(db_path: Path, symbol: str, *, now: datetime | None = None) -> SymbolRecord:
    """This system's realised record on one coin, over the recent window."""
    coin = normalize_symbol(symbol)
    moment = now or datetime.now(timezone.utc)
    window_start = (moment - timedelta(days=LOOKBACK_DAYS)).isoformat()
    # Whichever is LATER: the rolling window, or the day the fee rule started working.
    cutoff = max(window_start, FEE_GATE_EFFECTIVE_FROM)
    rows: list[tuple[Any, Any]] = []
    try:
        with closing(connect(db_path)) as conn:
            rows = [
                (row[0], row[1], row[2])
                for row in conn.execute(
                    """
                    SELECT symbol, profit_loss, COALESCE(closed_at, created_at)
                    FROM PERFORMANCE_ATTRIBUTION
                    """,
                ).fetchall()
            ]
    except Exception:  # noqa: BLE001 - a missing history must never block a proposal
        rows = []
    rows = [row for row in rows if _at_or_after(row[2], cutoff)]

    # Matched in Python rather than SQL: the normalisation above is the whole point, and
    # no SQL predicate can express "XBTGBP and BTC are the same coin".
    wins = losses = 0
    net = 0.0
    for row_symbol, profit_loss, _observed_at in rows:
        if normalize_symbol(row_symbol) != coin:
            continue
        try:
            amount = float(profit_loss)
        except (TypeError, ValueError):
            continue
        net += amount
        if amount > 0:
            wins += 1
        else:
            losses += 1

    trades = wins + losses
    if trades == 0:
        return SymbolRecord(coin, 0, 0, 0, 0.0, None, "insufficient_evidence", 0.0,
                            f"No closed {coin} trades in the last {LOOKBACK_DAYS} days.")
    win_rate = round(wins / trades, 4)

    if trades < MIN_TRADES_FOR_SIGNAL:
        return SymbolRecord(
            coin, trades, wins, losses, net, win_rate, "insufficient_evidence", 0.0,
            f"Only {trades} closed {coin} trade(s) in the last {LOOKBACK_DAYS} days - too few to judge.",
        )

    if wins == 0 and trades >= MIN_TRADES_FOR_AVOID and net < 0:
        return SymbolRecord(
            coin, trades, wins, losses, net, win_rate, "avoid", MAX_CONFIDENCE_PENALTY,
            f"{coin} has lost every one of its last {trades} closed trades "
            f"({net:.2f} net). Standing aside until something changes.",
        )

    if net < 0:
        # Scaled by how one-sided the record is, so a 40% win rate is treated more
        # gently than a 0% one, and capped so this can never be the whole decision.
        penalty = round(min(MAX_CONFIDENCE_PENALTY, MAX_CONFIDENCE_PENALTY * (1.0 - win_rate)), 4)
        return SymbolRecord(
            coin, trades, wins, losses, net, win_rate, "caution", penalty,
            f"{coin} is {wins} from {trades} and {net:.2f} net over the last {LOOKBACK_DAYS} days.",
        )

    return SymbolRecord(
        coin, trades, wins, losses, net, win_rate, "neutral", 0.0,
        f"{coin} is {wins} from {trades} and {net:+.2f} net over the last {LOOKBACK_DAYS} days.",
    )


def all_symbol_track_records(db_path: Path, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Every coin with a closed-trade history in the window, worst first.

    Surfaced to Ask AI Trader so the Founder can put the question directly, and so an
    answer about a coin can cite what this system's own money did rather than only what
    the chart says.
    """
    moment = now or datetime.now(timezone.utc)
    cutoff = (moment - timedelta(days=LOOKBACK_DAYS)).isoformat()
    try:
        with closing(connect(db_path)) as conn:
            symbols = {
                normalize_symbol(row[0])
                for row in conn.execute(
                    "SELECT DISTINCT symbol FROM PERFORMANCE_ATTRIBUTION WHERE COALESCE(closed_at, created_at) >= ?",
                    (cutoff,),
                ).fetchall()
                if row[0]
            }
    except Exception:  # noqa: BLE001
        return []
    records = [symbol_track_record(db_path, symbol, now=moment) for symbol in sorted(symbols)]
    return [record.to_dict() for record in sorted(records, key=lambda item: item.net_profit_loss)]
