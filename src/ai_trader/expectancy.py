"""One honest number: does this system make money over time?

2026-09-03, Founder-directed: "Please go ahead and fix it then."

TRADE_R_MULTIPLES has been written for weeks and read by nothing. When it was finally read,
it said the average trade returned +1.30R -- while the scorecard, drawn from the same 22
trades, said the month was down 5.08 pounds on 10 wins and 16 losses. Both cannot be true, and
until they agree every decision made from either is a guess wearing the clothes of evidence.

WHAT AN R-MULTIPLE IS, for whoever reads this next. R is the money put at risk on one trade:
the distance from entry to stop, times quantity. The R-multiple is the outcome divided by that.
-1R means the stop did exactly its job. +2R means the trade made twice what it risked. The
point is comparability: a 2-pound trade and a 50-pound trade become the same scale, so they can
be averaged into an expectancy -- the average R per trade, which is positive for a system that
makes money and negative for one that does not.

WHY THE +1.30 WAS WRONG, and it is not a coding bug. Three of the 22 trades risked FOUR PENCE
each and returned +21R, +15R and +9.4R. Twenty-one R on a 4p risk is 84 pence. The arithmetic
is right and the meaning is nonsense: divide anything by a tiny number and you get a large one.
Those three carried the whole average. The other nineteen average -0.88R, which is what the
scorecard was saying all along.

So this module fixes the READING, not the writing:

  * trades risking less than a floor are excluded from expectancy -- a 4p bet should not
    influence a conclusion about whether the strategy works;
  * a RISK-WEIGHTED average is reported alongside the plain one, because one-trade-one-vote
    lets the smallest positions shout loudest;
  * both are reported, never just the flattering one, along with how many trades were set
    aside and why.

AND THE NUMBER THAT MATTERS MOST. Every trade carries a fee cost of roughly 1.0R -- the fees
alone consume the entire amount risked. That is the plainest statement of the crypto problem
anywhere in this app, and it has been sitting in an unread table the whole time.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .database import connect

# Below this, a trade tells you nothing about whether the strategy works. Kraken's own order
# minimum let positions through at roughly 2 pounds, and a 1.5% stop on 2 pounds risks 3p --
# noise as a numerator and noise as a denominator. Real positions at the Founder's current
# sizing (25-50 pounds) risk 0.38-0.75, comfortably clear of this.
DEFAULT_MINIMUM_RISK = 0.25

# Fewer than this and an average is a story about one or two trades.
MEANINGFUL_SAMPLE = 8


def load_r_multiples(db_path: Path, *, broker: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    """Raw rows. Returns [] rather than raising: a missing measurement must never break a page."""
    sql = """SELECT symbol, broker, initial_monetary_risk, planned_r, gross_r, net_r,
                    fee_impact_r, created_at
             FROM TRADE_R_MULTIPLES"""
    params: list[Any] = []
    if broker:
        sql += " WHERE LOWER(broker) = LOWER(?)"
        params.append(broker)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(int(limit))
    try:
        with closing(connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, tuple(params)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for row in rows:
        out.append({
            "symbol": row[0], "broker": row[1], "risk": _f(row[2]), "planned_r": _f(row[3]),
            "gross_r": _f(row[4]), "net_r": _f(row[5]), "fee_r": _f(row[6]), "created_at": row[7],
        })
    return out


def _f(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def expectancy(
    rows: list[dict[str, Any]], *, minimum_risk: float = DEFAULT_MINIMUM_RISK
) -> dict[str, Any]:
    """Average R per trade, computed two ways, with everything excluded accounted for.

    Reports BOTH the plain and the risk-weighted average. They diverge exactly when position
    sizes are uneven, which is precisely when the plain one misleads -- so showing only one
    would recreate the problem this module exists to fix.
    """
    usable = [r for r in rows if r["net_r"] is not None and r["risk"] is not None]
    counted = [r for r in usable if r["risk"] >= minimum_risk]
    excluded = [r for r in usable if r["risk"] < minimum_risk]

    result: dict[str, Any] = {
        "trades_counted": len(counted),
        "trades_excluded_as_too_small": len(excluded),
        "minimum_risk_applied": round(float(minimum_risk), 4),
        "expectancy_r": None,
        "risk_weighted_expectancy_r": None,
        "average_fee_cost_r": None,
        "win_rate": None,
        "sample_is_meaningful": len(counted) >= MEANINGFUL_SAMPLE,
        "plain_english": "",
    }
    if not counted:
        result["plain_english"] = (
            f"No trade risked more than {minimum_risk:.2f} of the account, so there is nothing "
            "to measure yet. Positions this small tell you about rounding, not about strategy."
        )
        return result

    nets = [r["net_r"] for r in counted]
    risks = [r["risk"] for r in counted]
    total_risk = sum(risks) or 1.0
    result["expectancy_r"] = round(sum(nets) / len(nets), 3)
    result["risk_weighted_expectancy_r"] = round(
        sum(n * w for n, w in zip(nets, risks)) / total_risk, 3
    )
    fees = [r["fee_r"] for r in counted if r["fee_r"] is not None]
    if fees:
        result["average_fee_cost_r"] = round(sum(fees) / len(fees), 3)
    result["win_rate"] = round(sum(1 for n in nets if n > 0) / len(nets), 4)
    result["plain_english"] = _verdict(result)
    return result


def _verdict(r: dict[str, Any]) -> str:
    """Said the way the Founder would say it, not the way a report would."""
    e = r["expectancy_r"]
    weighted = r["risk_weighted_expectancy_r"]
    fee = r["average_fee_cost_r"]
    parts: list[str] = []

    if e is not None and e < 0:
        parts.append(
            f"Across {r['trades_counted']} trades big enough to mean anything, the average trade "
            f"lost {abs(e):.2f} times what it risked. On these numbers the strategy does not pay "
            "for itself."
        )
    elif e is not None:
        parts.append(
            f"Across {r['trades_counted']} trades big enough to mean anything, the average trade "
            f"made {e:.2f} times what it risked."
        )

    if fee is not None and fee >= 0.5:
        parts.append(
            f"Fees alone cost {fee:.2f} times the amount risked on the average trade, so a trade "
            "must clear that before it earns anything. That is the single biggest thing standing "
            "between these trades and a profit, and it is a function of position size, not of "
            "how good the ideas are."
        )

    if e is not None and weighted is not None and abs(e - weighted) >= 0.4:
        bigger = "better" if weighted > e else "worse"
        parts.append(
            f"Weighted by money actually risked the figure is {weighted:+.2f}, notably {bigger} "
            "than the simple average -- the bigger positions behaved differently from the small "
            "ones, so the simple average flatters or punishes unfairly."
        )

    if r["trades_excluded_as_too_small"]:
        parts.append(
            f"{r['trades_excluded_as_too_small']} trade(s) were left out for risking less than "
            f"{r['minimum_risk_applied']:.2f}. Dividing a real gain by a few pence produces a "
            "spectacular-looking multiple out of small change, which is how this measure came to "
            "read +1.30 while the month was down."
        )

    if not r["sample_is_meaningful"]:
        parts.append(
            f"Only {r['trades_counted']} trades qualify, so treat this as an early reading rather "
            "than a verdict."
        )
    return " ".join(parts)


def expectancy_summary(
    db_path: Path, *, broker: str | None = None, minimum_risk: float = DEFAULT_MINIMUM_RISK
) -> dict[str, Any]:
    """What the scorecard shows the Founder."""
    return expectancy(load_r_multiples(db_path, broker=broker), minimum_risk=minimum_risk)
