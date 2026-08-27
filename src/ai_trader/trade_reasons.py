"""Record WHY a trade opened and closed, instead of a constant that says nothing.

2026-08-27 audit finding. PERFORMANCE_ATTRIBUTION is the table every learning and reporting
path reads to answer "what did winning trades have in common" -- reporting_service.py builds
its lessons by grouping wins by entry_reason and losses by exit_reason. In production all 38
rows carried this, for both fields:

    entry_reason = "Reconciled from Kraken fills."
    exit_reason  = "Reconciled from Kraken fills."

That is provenance, not a reason. Grouping 38 trades by it yields one bucket of 38 and no
lesson, so the learning loop was running over a field with zero information in it -- the same
disease as the fabricated research scores: a column that exists, is populated, and means
nothing. holding_period_seconds was NULL on all 38 rows on top of that, so "how long do our
winners run" had no answer either.

None of this needed new data collection. The real reasons were already being written, just
never joined to the trade:

  entry   DUE_DILIGENCE_ASSESSMENTS.reasoning_json, keyed by proposal_id -- the six-dimension
          rationale (technical, market, macro, behavioural, fundamental, investment policy)
          that actually gated the trade. 2,118 rows in production; 30 of the 38 closed trades
          join straight to one, and every future trade will.
  exit    MANAGED_TRADE_EXITS.exit_reason -- the real trigger, already recorded:
          take_profit_triggered (13), stop_loss_triggered (3).

So this module joins what exists rather than inventing anything. Where a reason genuinely
cannot be recovered it says so plainly and stays NULL-ish rather than substituting a
plausible sentence -- a fabricated reason would be worse than the constant it replaced,
because it would look like evidence.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import connect

# The placeholder this module exists to replace. Backfill treats a row carrying it as
# unrecorded rather than as a reason worth keeping.
LEGACY_PLACEHOLDER = "Reconciled from Kraken fills."

# Said when the rationale genuinely was not recorded. Deliberately not a reason: anything
# that reads like one would corrupt the very analysis this field feeds.
UNRECORDED_ENTRY = "Entry rationale was not recorded for this trade."
UNRECORDED_EXIT = "Exit trigger was not recorded for this trade."

# Ordered by how much a Founder reading a trade review actually learns from them. The first
# three carry live numbers; the rest are largely fixed boilerplate.
_DILIGENCE_DIMENSIONS = (
    ("technical", "Technical"),
    ("market", "Market"),
    ("investment_policy", "Policy"),
    ("macro", "Macro"),
    ("behavioural", "Behavioural"),
    ("fundamental", "Fundamental"),
)

_MAX_REASON_CHARS = 400
_QUOTE_SUFFIXES = ("GBP", "USDT", "USDC", "USD", "EUR")

_COIN_ALIASES = {"XBT": "BTC", "XDG": "DOGE"}


def is_placeholder(reason: Any) -> bool:
    """Whether a stored reason carries no information and should be replaced.

    The UNRECORDED_* markers count as placeholders too, so a later backfill retries them.
    The first production run proved why: it wrote "not recorded" for every exit because the
    timestamps it needed to match on were still in the wrong format, and without this the
    honest fallback would have been frozen in permanently by the very run that gave up.
    """
    text = str(reason or "").strip()
    return not text or text in {LEGACY_PLACEHOLDER, UNRECORDED_ENTRY, UNRECORDED_EXIT}


def normalise(symbol: Any) -> str:
    """Bare coin from a Kraken pair. Local rather than imported from kraken_reconciliation,
    which imports this module -- and the rule is simple enough not to warrant the cycle."""
    text = str(symbol or "").upper().strip()
    for suffix in _QUOTE_SUFFIXES:
        if len(text) > len(suffix) + 1 and text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    # Kraken's own ticker for Bitcoin. Stripping the quote currency off XBTGBP leaves XBT,
    # which matches nothing -- every other table in this codebase calls it BTC.
    return _COIN_ALIASES.get(text, text)


def _is_informative(text: str) -> bool:
    """A diligence line earns its place if it carries a measured number.

    "Momentum 0.6, volatility None, liquidity 0.75" tells a reader what the trade was built
    on. "Macro review matched against tracked market themes" is boilerplate that appears on
    every single trade and would crowd the useful lines out of a length-capped summary.
    """
    return any(char.isdigit() for char in text)


def summarise_entry_reason(reasoning: dict[str, Any] | None) -> str | None:
    """One compact line describing what the due-diligence gate actually saw.

    Returns None when there is nothing real to summarise, so the caller can record the
    honest "not recorded" rather than an empty-looking reason.
    """
    if not isinstance(reasoning, dict) or not reasoning:
        return None
    informative: list[str] = []
    boilerplate: list[str] = []
    for key, label in _DILIGENCE_DIMENSIONS:
        value = str(reasoning.get(key) or "").strip()
        if not value:
            continue
        line = f"{label}: {value.rstrip('.')}"
        (informative if _is_informative(value) else boilerplate).append(line)
    # Prefer the lines carrying numbers; fall back to boilerplate only if nothing else
    # exists, since a trade explained solely by boilerplate is still better than silence.
    chosen = informative or boilerplate
    if not chosen:
        return None
    summary = " | ".join(chosen)
    if len(summary) > _MAX_REASON_CHARS:
        summary = summary[: _MAX_REASON_CHARS - 1].rstrip() + "…"
    return summary


def _json_loads(raw: Any) -> dict[str, Any] | None:
    import json

    if isinstance(raw, dict):
        return raw
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def entry_reasons_for_proposals(conn: Any, proposal_ids: list[str]) -> dict[str, str]:
    """Real entry reasons for many proposals in ONE query.

    Batched deliberately: the per-symbol-loop-with-its-own-connection pattern is a cost
    class already found and fixed repeatedly in this codebase against remote Postgres.
    """
    wanted = [str(pid) for pid in proposal_ids if pid]
    if not wanted:
        return {}
    placeholders = ",".join(["?"] * len(wanted))
    try:
        rows = conn.execute(
            f"""
            SELECT proposal_id, reasoning_json, created_at FROM DUE_DILIGENCE_ASSESSMENTS
            WHERE proposal_id IN ({placeholders})
            ORDER BY created_at ASC
            """,
            tuple(wanted),
        ).fetchall()
    except Exception:  # noqa: BLE001 - the diligence table belongs to another schema module
        # A caller whose database never initialised the foundation schema must fall back to
        # the honest "not recorded", not crash the reconciliation that owns this connection.
        return {}
    reasons: dict[str, str] = {}
    for row in rows:
        proposal_id = str(row[0])
        summary = summarise_entry_reason(_json_loads(row[1]))
        if summary:
            # Ascending order means the newest assessment for a proposal wins.
            reasons[proposal_id] = summary
    return reasons


# Epoch seconds inside this range are treated as timestamps rather than as an ISO string.
# Roughly 2001-09-09 to 2033-05-18 -- wide enough for any real trade, narrow enough that a
# stray small number is not silently read as a date in 1970.
_EPOCH_MIN = 1_000_000_000.0
_EPOCH_MAX = 2_000_000_000.0


def _parse(value: Any) -> datetime | None:
    """Parse a stored timestamp, in either of the two formats production actually holds.

    2026-08-27: PERFORMANCE_ATTRIBUTION.opened_at/closed_at turned out to carry Kraken epoch
    floats as strings ('1787162315.152785'), not ISO -- the same split already found and
    fixed in BROKER_TRADE_HISTORY. Every row therefore had a NULL holding period and no
    matchable close time, because an ISO-only parser rejected all of them.
    """
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        epoch = float(text)
    except (TypeError, ValueError):
        pass
    else:
        if _EPOCH_MIN <= epoch <= _EPOCH_MAX:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def holding_seconds(opened_at: Any, closed_at: Any) -> float | None:
    """Seconds a position was held, or None if either end is unusable.

    The reconciliation result already carries a holding_seconds key, but it arrived NULL on
    every production row, so this recomputes from the two timestamps that ARE reliably
    present rather than trusting the field that demonstrably was not.
    """
    opened, closed = _parse(opened_at), _parse(closed_at)
    if opened is None or closed is None:
        return None
    if opened.tzinfo is None or closed.tzinfo is None:
        # Mixed awareness would raise; a naive pair is still comparable to itself.
        if opened.tzinfo is not None or closed.tzinfo is not None:
            return None
    seconds = (closed - opened).total_seconds()
    # A negative span means the two timestamps came from different clocks or were swapped;
    # recording it would poison every "how long do winners run" statistic.
    return seconds if seconds >= 0 else None


def exit_reasons_by_symbol(conn: Any, broker: str = "kraken") -> dict[str, list[tuple[datetime | None, str]]]:
    """Every recorded exit trigger for a broker, grouped by bare coin.

    MANAGED_TRADE_EXITS has no proposal_id column of its own (proposal_id lives inside
    payload_json), so a closed trade is matched to its trigger by coin and timing rather
    than by key -- see nearest_exit_reason.
    """
    rows = conn.execute(
        """
        SELECT symbol, exit_reason, updated_at FROM MANAGED_TRADE_EXITS
        WHERE broker = ? AND exit_reason IS NOT NULL AND status = 'closed'
        """,
        (broker.lower(),),
    ).fetchall()
    grouped: dict[str, list[tuple[datetime | None, str]]] = {}
    for row in rows:
        coin = normalise(row[0])
        reason = str(row[1] or "").strip()
        if coin and reason:
            grouped.setdefault(coin, []).append((_parse(row[2]), reason))
    return grouped


def nearest_exit_reason(
    grouped: dict[str, list[tuple[datetime | None, str]]],
    symbol: Any,
    closed_at: Any,
    *,
    tolerance_seconds: float = 6 * 3600,
) -> str | None:
    """The exit trigger recorded closest in time to when this trade actually closed.

    Bounded by tolerance_seconds on purpose. Matching on coin alone would happily attach
    March's stop-loss to August's take-profit for the same coin, which is worse than
    recording nothing: it would look like evidence while being fiction. Outside the window,
    this returns None and the caller records the honest "not recorded".
    """
    candidates = grouped.get(normalise(symbol)) or []
    closed = _parse(closed_at)
    if not candidates or closed is None:
        return None
    best_reason, best_gap = None, None
    for stamp, reason in candidates:
        # Parenthesised deliberately: `a is None != b` chains into `a is None and None != b`,
        # which is not the mixed-awareness check this needs.
        if stamp is None or (stamp.tzinfo is None) != (closed.tzinfo is None):
            continue
        try:
            gap = abs((stamp - closed).total_seconds())
        except TypeError:
            continue
        if best_gap is None or gap < best_gap:
            best_reason, best_gap = reason, gap
    if best_gap is None or best_gap > tolerance_seconds:
        return None
    return best_reason


def backfill_trade_reasons(db_path: Path, *, broker: str = "kraken") -> dict[str, Any]:
    """Repair rows already written with the placeholder and a NULL holding period.

    Idempotent: rows already carrying a real reason are left alone, so this is safe to run
    repeatedly. Only ever fills a field in -- it never overwrites a recorded reason with a
    recovered one.
    """
    from .multi_broker import initialize_multi_broker_schema

    initialize_multi_broker_schema(db_path)
    outcome = {
        "examined": 0, "entry_reasons_set": 0, "exit_reasons_set": 0,
        "holding_periods_set": 0, "timestamps_converted": 0, "symbols_normalised": 0,
    }
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT attribution_id, proposal_id, symbol, opened_at, closed_at,
                   entry_reason, exit_reason, holding_period_seconds
            FROM PERFORMANCE_ATTRIBUTION WHERE broker = ?
            """,
            (broker.lower(),),
        ).fetchall()
        if not rows:
            return outcome
        records = [
            {
                "id": row[0], "proposal_id": row[1], "symbol": row[2], "opened_at": row[3],
                "closed_at": row[4], "entry_reason": row[5], "exit_reason": row[6],
                "holding": row[7],
            }
            for row in rows
        ]
        outcome["examined"] = len(records)
        entry_reasons = entry_reasons_for_proposals(
            conn, [record["proposal_id"] for record in records if record["proposal_id"]]
        )
        exits = exit_reasons_by_symbol(conn, broker=broker)

        updates: list[tuple[Any, ...]] = []
        for record in records:
            new_entry = record["entry_reason"]
            new_exit = record["exit_reason"]
            new_holding = record["holding"]
            changed = False
            if is_placeholder(new_entry):
                recovered = entry_reasons.get(str(record["proposal_id"] or ""))
                new_entry = recovered or UNRECORDED_ENTRY
                if recovered:
                    outcome["entry_reasons_set"] += 1
                changed = True
            if is_placeholder(new_exit):
                recovered = nearest_exit_reason(exits, record["symbol"], record["closed_at"])
                new_exit = recovered or UNRECORDED_EXIT
                if recovered:
                    outcome["exit_reasons_set"] += 1
                changed = True
            if new_holding is None:
                new_holding = holding_seconds(record["opened_at"], record["closed_at"])
                if new_holding is not None:
                    outcome["holding_periods_set"] += 1
                    changed = True

            # Same two-formats-in-one-column bug already fixed in BROKER_TRADE_HISTORY:
            # these arrived as Kraken epoch floats ('1787162315.152785') rather than ISO,
            # so anything reading them as dates saw nothing. Converted on the way through
            # so the stored record is right, not merely corrected by whichever reader
            # remembers to.
            new_opened, new_closed = record["opened_at"], record["closed_at"]
            for key in ("opened_at", "closed_at"):
                parsed = _parse(record[key])
                if parsed is not None and str(record[key]) != parsed.isoformat():
                    if key == "opened_at":
                        new_opened = parsed.isoformat()
                    else:
                        new_closed = parsed.isoformat()
                    outcome["timestamps_converted"] += 1
                    changed = True

            # PERFORMANCE_ATTRIBUTION held both XRP and XRPGBP for the same coin; anything
            # grouping by symbol split one coin's record in two.
            new_symbol = normalise(record["symbol"])
            if new_symbol and new_symbol != str(record["symbol"] or ""):
                outcome["symbols_normalised"] += 1
                changed = True
            else:
                new_symbol = record["symbol"]

            # Compare against what is actually stored rather than trusting the flags above:
            # a row whose reason genuinely cannot be recovered re-derives the same
            # "not recorded" marker on every run, and re-writing it identically forever
            # would make this non-idempotent for no gain.
            if changed and (
                new_entry != record["entry_reason"]
                or new_exit != record["exit_reason"]
                or new_holding != record["holding"]
                or new_opened != record["opened_at"]
                or new_closed != record["closed_at"]
                or new_symbol != record["symbol"]
            ):
                updates.append(
                    (new_entry, new_exit, new_holding, new_opened, new_closed, new_symbol, record["id"])
                )
        if updates:
            with conn:
                conn.executemany(
                    """
                    UPDATE PERFORMANCE_ATTRIBUTION
                    SET entry_reason = ?, exit_reason = ?, holding_period_seconds = ?,
                        opened_at = ?, closed_at = ?, symbol = ?
                    WHERE attribution_id = ?
                    """,
                    updates,
                )
    return outcome
