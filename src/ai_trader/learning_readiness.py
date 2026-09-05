"""Whether the outcome record is complete enough to learn from.

Founder-directed 2026-09-05: "the learning should refuse to run on incomplete outcomes."

WHY THIS EXISTS. Learning from a corrupted record is worse than not learning, because it
looks like it is working. This project has hit that failure mode repeatedly: an empty
evidence source read as a finding; a hardcoded 0.62 trend score read as a real signal for a
fortnight; a crashing query whose swallowed exception was indistinguishable from "this coin
has no history". Every one of those produced confident output from absent input.

So nothing in the learning path computes a number without first asking this module whether
the data underneath it is trustworthy, and the honest answer when it is not is to refuse --
not to substitute a neutral default. A neutral default is how `historical_statistics` came to
report win_rate 0.5 for every strategy forever.

WHAT IT CHECKS.

  1. Are there any closed trades at all, and enough of them to say anything?
  2. Do the closed trades carry the fields learning actually reads (a P&L, an exit)?
  3. Are the timestamps parseable? 26 of 66 PERFORMANCE_ATTRIBUTION rows stored a raw epoch,
     and "1787586949" sorts before "2026-08-31" as text, so a plain date filter silently
     drops the most recent trades.
  4. Is the record fresh, or has broker reconciliation stopped writing? A stale record is the
     dangerous case: the numbers still compute, they are just describing last month.

The thresholds are deliberately low. This is a gate against LEARNING FROM NOTHING, not a
statistical significance test -- 26 closed trades will not support a confident per-strategy
expectancy either way, and pretending otherwise is the other half of the same mistake.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .database import connect

# Below this, any per-group statistic is an anecdote. Reported, never acted on.
MINIMUM_CLOSED_TRADES = 5

# A record nothing has added to for this long means reconciliation has stopped, and every
# number computed from it is describing the past while presenting as the present.
STALENESS_LIMIT_DAYS = 14

# Above this share of unparseable timestamps the window filters cannot be trusted at all.
MAX_UNPARSEABLE_TIMESTAMP_SHARE = 0.5


@dataclass(frozen=True)
class LearningReadiness:
    ready: bool
    closed_trades: int
    usable_trades: int
    unparseable_timestamps: int
    newest_outcome: str | None
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "closed_trades": self.closed_trades,
            "usable_trades": self.usable_trades,
            "unparseable_timestamps": self.unparseable_timestamps,
            "newest_outcome": self.newest_outcome,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }

    @property
    def plain_english(self) -> str:
        if self.ready:
            note = f"Learning can run: {self.usable_trades} usable closed trades."
            return note + (f" Caveats: {'; '.join(self.warnings)}." if self.warnings else "")
        return "Learning is standing down: " + "; ".join(self.blockers) + "."


def _parse(value: Any) -> datetime | None:
    """A timestamp in either of the two formats this database actually holds."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.replace(".", "", 1).isdigit():
        try:
            return datetime.fromtimestamp(float(text), timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def assess_learning_readiness(db_path: Path, *, now: datetime | None = None) -> LearningReadiness:
    """Can anything be learned from the outcome record as it currently stands?

    Never raises: a readiness check that crashes would itself have to be wrapped in a bare
    `except`, which is the pattern that hid the last three defects.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    blockers: list[str] = []
    warnings: list[str] = []
    rows: list[Any] = []
    try:
        with closing(connect(db_path)) as conn:
            rows = conn.execute(
                """
                SELECT symbol, profit_loss, exit_price, closed_at, created_at
                FROM PERFORMANCE_ATTRIBUTION
                """
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - an unreadable record is itself a blocker, not a crash
        return LearningReadiness(
            ready=False, closed_trades=0, usable_trades=0, unparseable_timestamps=0,
            newest_outcome=None,
            blockers=[f"the outcome record could not be read ({type(exc).__name__})"],
        )

    closed_trades = len(rows)
    usable = 0
    unparseable = 0
    newest: datetime | None = None
    for row in rows:
        stamp = _parse(row[3]) or _parse(row[4])
        if stamp is None:
            unparseable += 1
        elif newest is None or stamp > newest:
            newest = stamp
        # "Usable" means the fields learning actually reads are present. A row with no
        # profit_loss cannot contribute to an expectancy however well-formed it looks.
        if row[1] is not None and row[2] is not None:
            usable += 1

    if closed_trades == 0:
        blockers.append("there are no closed trades to learn from")
    elif usable < MINIMUM_CLOSED_TRADES:
        blockers.append(
            f"only {usable} closed trade(s) carry both a profit/loss and an exit price, "
            f"below the {MINIMUM_CLOSED_TRADES} needed to say anything"
        )

    if closed_trades and unparseable / closed_trades > MAX_UNPARSEABLE_TIMESTAMP_SHARE:
        blockers.append(
            f"{unparseable} of {closed_trades} outcomes have an unreadable date, so no time "
            "window can be trusted"
        )
    elif unparseable:
        warnings.append(f"{unparseable} outcome(s) have an unreadable date and are excluded")

    if newest is None:
        if closed_trades:
            blockers.append("no outcome carries a readable date")
    else:
        age_days = (moment - newest).days
        if age_days > STALENESS_LIMIT_DAYS:
            blockers.append(
                f"the newest outcome is {age_days} days old, so broker reconciliation has "
                "stopped and these numbers describe the past"
            )
        elif age_days > STALENESS_LIMIT_DAYS // 2:
            warnings.append(f"the newest outcome is {age_days} days old")

    if usable and usable < 30:
        warnings.append(
            f"{usable} trades is too few for a confident per-strategy figure; treat results as "
            "provisional"
        )

    return LearningReadiness(
        ready=not blockers,
        closed_trades=closed_trades,
        usable_trades=usable,
        unparseable_timestamps=unparseable,
        newest_outcome=newest.isoformat() if newest else None,
        blockers=blockers,
        warnings=warnings,
    )
