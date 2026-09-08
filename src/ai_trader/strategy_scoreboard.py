"""What every strategy has actually done, on this coin and overall, as one compact table.

Founder-directed 2026-09-05, Phase 5 of the learning work.

WHY THIS EXISTS. The model is used at the wrong end. Today a strategy is chosen by arithmetic
scoring in `trading_intelligence._score_strategy_candidate`, and only then is the model shown
the single surviving candidate and asked yes or no. It never sees the field, so it can never
do the thing it is there for: weigh which approach fits this coin, in this market, given what
has happened before.

The Founder's framing: "shouldn't the AI be able to look at the strategies for a specific
trade and say, in the past these strategies worked, these didn't work for this specific coin,
and therefore I will employ this trade." That requires handing it the evidence, and the
evidence has to be per coin -- settled shadow trades put crypto_trend_following_2r at -0.15R
on BCH and -1.77R on XRP, a tenfold spread that any per-strategy average destroys.

COST DISCIPLINE, which is a design constraint here rather than an afterthought. Measured
2026-09-05: about 163 LLM calls a day (148 equity proposals, 15 crypto reviews), roughly $10 a
month at gpt-4.1-mini. Prompt size is cheap; what is expensive is Supabase egress, and this
project has already been bitten twice by queries that pulled whole tables.

So this module:

  * adds NO new model calls -- the scoreboard rides along in prompts that already happen;
  * reads the two outcome sources ONCE per cycle and caches, rather than per candidate. At
    148 proposals a day the difference between one read and 148 is the whole point;
  * emits a compact ranked table, tens of tokens, not raw rows.

HONESTY RULES. Real money and simulation are labelled and never blended -- a shadow result is
what would have happened, and presenting it as a trading record would be the same error as
the fabricated 0.62 trend score that hid this app's real behaviour for a fortnight. A strategy
with no evidence is reported as having none, never as average.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .shadow_outcomes import shadow_strategy_records, shadow_symbol_records
from .expectancy import expectancy_summary
from .strategy_performance import strategy_records, strategy_symbol_records

# One cycle's worth. Long enough that a research run over 19 coins reads the outcome tables
# once instead of 19 times, short enough that a demotion or a newly settled trade shows up in
# the next run rather than tomorrow.
CACHE_SECONDS = 300

# Per-coin evidence below this is named but explicitly marked thin, so the model can weigh it
# as an anecdote rather than a finding.
THIN_SAMPLE = 10

_cache: dict[str, tuple[float, Any]] = {}


@dataclass(frozen=True)
class StrategyEvidence:
    strategy_id: str
    coin_sample: int = 0
    coin_expectancy_r: float | None = None
    coin_basis: str | None = None          # "real_money" | "shadow_simulation"
    overall_sample: int = 0
    overall_expectancy_r: float | None = None
    overall_basis: str | None = None
    notes: list[str] = field(default_factory=list)
    # The count the R average is genuinely over. 2026-09-08: the line used to pair an average
    # computed from 13 trades with a headcount of 22, because trades that risked pennies carry
    # no R but were still counted. Defaults to 0, meaning "use the plain sample" -- so an older
    # caller that has not been updated reads exactly as it did before.
    coin_r_sample: int = 0
    overall_r_sample: int = 0

    def as_line(self) -> str:
        """One row of the table the model reads. Deliberately terse.

        The count beside each average is the number of trades that average is over, not the
        number of trades linked to the strategy. Those differ whenever a trade was too small
        to have a meaningful R, and quoting the larger one made a 13-trade finding look like a
        22-trade one.
        """
        coin_over = self.coin_r_sample or self.coin_sample
        overall_over = self.overall_r_sample or self.overall_sample
        if self.coin_sample:
            here = f"on this coin {self.coin_expectancy_r:+.2f}R over {coin_over} ({self.coin_basis})"
            if coin_over < THIN_SAMPLE:
                here += " [thin]"
        else:
            here = "no record on this coin"
        if self.overall_sample:
            everywhere = f"overall {self.overall_expectancy_r:+.2f}R over {overall_over} ({self.overall_basis})"
        else:
            everywhere = "no record anywhere"
        return f"- {self.strategy_id}: {here}; {everywhere}"


def _sources(db_path: Path) -> dict[str, Any]:
    """The four outcome views, read once per cycle and cached."""
    now = time.monotonic()
    cached = _cache.get("sources")
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]
    sources = {
        "real_overall": strategy_records(db_path),
        "real_by_coin": strategy_symbol_records(db_path),
        "shadow_overall": shadow_strategy_records(db_path),
        "shadow_by_coin": shadow_symbol_records(db_path),
    }
    _cache["sources"] = (now, sources)
    return sources


def trading_cost_note(db_path: Path, *, broker: str = "kraken") -> str | None:
    """One sentence telling the reviewer what trading has been COSTING, not just returning.

    2026-09-08, and the reason it exists is worth stating plainly. Measured directly against
    production: the 27 closed Kraken trades made +GBP 0.17 before fees and -GBP 5.41 after
    them. Every fill was charged 0.800% by Kraken, entry and exit alike -- a 1.60% round trip
    against a 1.5% stop, so a trade was being asked to predict a move smaller than the cost of
    making it. The reviewer saw only the after-fees number, concluded the approach loses money,
    and marked down every new candidate on the strength of it. It was being told the truth
    about the outcome and nothing at all about the cause.

    Returns None when there is nothing measured to say. Silence is correct there: inventing a
    cost figure would be the same mistake in the other direction.
    """

    try:
        summary = expectancy_summary(db_path, broker=broker)
    except Exception:  # noqa: BLE001 - context is additive; its failure must not block a trade
        return None
    fee_r = summary.get("average_fee_cost_r")
    expectancy_r = summary.get("expectancy_r")
    if fee_r is None or fee_r <= 0:
        return None
    note = (
        f"COST CONTEXT, and read it before judging the records below: fees alone have cost "
        f"{fee_r:.2f}R on the average closed trade. A strategy showing a negative R here is "
        f"therefore not necessarily selecting badly -- subtract the fee and you have what the "
        f"selection actually achieved."
    )
    if expectancy_r is not None:
        before_costs = round(expectancy_r + fee_r, 2)
        note += (
            f" On the overall record that is {expectancy_r:+.2f}R after costs and about "
            f"{before_costs:+.2f}R before them. Judge the setup in front of you on its own "
            f"merits and on whether its target clears the round trip, not on a past loss that "
            f"was mostly toll."
        )
    # 2026-09-08, Founder-directed: "tell it straight that the rate is the rate in Kraken."
    # He has checked the account: this is the entry fee tier and it only falls with 30-day
    # volume far beyond anything this account will trade. Saying so stops every reviewer and
    # every standup re-opening a question that has an answer, which is what has been happening.
    note += (
        " This fee rate is fixed: it is the account's Kraken tier, it is not a setting anyone "
        "can change, and it will not fall at this trading volume. Do not treat it as something "
        "to be solved or as a reason to hold back on its own. The only thing that answers it is "
        "a trade aimed at a move several times larger than the round trip."
    )
    return note


def clear_cache() -> None:
    """For tests, and for a caller that has just changed the outcome record."""
    _cache.clear()


def strategy_evidence_for(db_path: Path, *, symbol: str, candidates: list[str]) -> list[StrategyEvidence]:
    """Per-strategy evidence for one coin, best on this coin first.

    Real money is preferred over simulation wherever it exists, and the source is always
    named. Candidates with no evidence at all are still listed -- the model should know the
    option exists and is unproven, rather than silently never seeing it.
    """
    sources = _sources(db_path)
    coin = str(symbol or "").upper()
    evidence: list[StrategyEvidence] = []
    for strategy_id in candidates:
        notes: list[str] = []
        coin_sample, coin_r, coin_basis = 0, None, None
        coin_r_sample = overall_r_sample = 0
        real_coin = sources["real_by_coin"].get((strategy_id, coin))
        if real_coin and real_coin.expectancy_r is not None:
            coin_sample, coin_r, coin_basis = real_coin.sample_size, real_coin.expectancy_r, "real_money"
            coin_r_sample = getattr(real_coin, "r_sample_size", 0)
        else:
            shadow_coin = sources["shadow_by_coin"].get((strategy_id, coin))
            if shadow_coin:
                coin_sample = shadow_coin["sample_size"]
                coin_r = shadow_coin["expectancy_r"]
                coin_basis = "shadow_simulation"

        overall_sample, overall_r, overall_basis = 0, None, None
        real_all = sources["real_overall"].get(strategy_id)
        if real_all and real_all.expectancy_r is not None:
            overall_sample, overall_r, overall_basis = real_all.sample_size, real_all.expectancy_r, "real_money"
            overall_r_sample = getattr(real_all, "r_sample_size", 0)
        else:
            shadow_all = sources["shadow_overall"].get(strategy_id)
            if shadow_all:
                overall_sample = shadow_all["sample_size"]
                overall_r = shadow_all["expectancy_r"]
                overall_basis = "shadow_simulation"

        if coin_r is not None and overall_r is not None and coin_r - overall_r > 0.5:
            notes.append("does better on this coin than it does generally")
        if coin_r is not None and overall_r is not None and overall_r - coin_r > 0.5:
            notes.append("does worse on this coin than it does generally")
        evidence.append(StrategyEvidence(
            strategy_id=strategy_id, coin_sample=coin_sample, coin_expectancy_r=coin_r,
            coin_basis=coin_basis, overall_sample=overall_sample,
            overall_expectancy_r=overall_r, overall_basis=overall_basis, notes=notes,
            coin_r_sample=coin_r_sample, overall_r_sample=overall_r_sample,
        ))

    # Best on this coin first; anything with no coin evidence sorts last but is still shown.
    evidence.sort(key=lambda e: (e.coin_expectancy_r is None, -(e.coin_expectancy_r or 0.0)))
    return evidence


def serialize_strategy_evidence(
    evidence: list[StrategyEvidence], *, cost_note: str | None = None
) -> str:
    """The prompt block. Compact by design -- this rides in ~163 calls a day.

    `cost_note` says what trading has been COSTING, alongside what it has been returning.
    2026-09-08, and it is the correction that matters most here: measured against production,
    the 27 closed Kraken trades made +GBP 0.17 before fees and lost GBP 5.41 after them. The
    reviewer was seeing only the after-fees figure, concluding the approach loses money, and
    marking every new candidate down for it. "Flat before costs, losing after" is a completely
    different instruction from "losing", and only one of them is true.
    """
    if not evidence:
        return (
            "STRATEGY EVIDENCE UNAVAILABLE: no closed trades and no settled shadow trades exist "
            "yet, so nothing can be said about which approach has worked. Treat this as a "
            "missing input, not as evidence that all strategies are equal."
        )
    measured = [e for e in evidence if e.coin_sample or e.overall_sample]
    if not measured:
        return (
            "No strategy in this candidate list has a recorded result yet, on this coin or "
            "anywhere. They are unproven rather than equal; prefer the one whose stated logic "
            "best fits the evidence in front of you, and size accordingly."
        )
    lines = [
        "How each candidate strategy has actually performed, best on this coin first. "
        "R is profit or loss per pound risked, after fees. real_money is this system's own "
        "closed trades; shadow_simulation is what would have happened to candidates it "
        "recorded but did not take -- informative, but not a trading record.",
    ]
    if cost_note:
        lines.append(cost_note)
    lines.extend(item.as_line() for item in evidence)
    flagged = [e for e in evidence if e.notes]
    if flagged:
        lines.append("Worth noting: " + "; ".join(
            f"{e.strategy_id} {', '.join(e.notes)}" for e in flagged
        ) + ".")
    return "\n".join(lines)
