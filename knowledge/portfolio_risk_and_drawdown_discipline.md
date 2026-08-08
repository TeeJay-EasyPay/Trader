---
title: "Portfolio-Level Risk Management and Drawdown Discipline"
topics: [risk_management, drawdown, correlation, position_sizing]
applies_to: [stock, crypto]
sectors: []
---

Per-trade risk control (stop-losses, position sizing) is necessary but not
sufficient — a portfolio can be destroyed by risks that only exist at the
portfolio level, even when every individual position was sized correctly on
its own terms.

**Correlation risk.** Risk does not add up the way position count suggests.
Five positions each risking 1% of the account is not "5% total risk" if the
five positions are correlated — several momentum longs in the same sector,
several crypto assets that move together in a broad risk-off event, or
several trades all implicitly betting on the same macro outcome (e.g. rates
falling). In a correlated adverse move, several stops can be hit
simultaneously, and the realized loss is much closer to the sum of the
individual risks than the diversified figure the position count implies.
Portfolio construction has to ask not just "how much am I risking on this
trade" but "how much am I risking on this *kind* of trade, across everything
currently open."

**Concentration risk.** A single position sized within the per-trade rule can
still represent an outsized fraction of the portfolio if too much of the
account's capital sits in one name, one sector, or one asset class at the
same time — even without a correlated group of separate trades. A hard cap
on maximum single-position exposure, independent of the stop-loss-derived
risk calculation, is a second, separate control that catches this case.

**Drawdown recovery math is not intuitive, and this is the single most
important number to internalize**: a loss requires a *larger* percentage
gain to recover, and the relationship is not linear —
- a 10% loss needs an 11% gain to recover
- a 25% loss needs a 33% gain to recover
- a 50% loss needs a 100% gain to recover
- a 75% loss needs a 300% gain to recover

This is why avoiding large drawdowns matters more than maximizing the size
of individual winners: the deeper the drawdown, the disproportionately
larger the recovery required, and very deep drawdowns (50%+) are recovered
from far less often in practice than the arithmetic alone suggests, because
capital, confidence, and time horizon are all simultaneously damaged.

**Practical implications for an automated system:**
- A running check of aggregate risk across all currently-open positions
  (not just the risk of the trade being newly proposed) should gate new
  entries — a new trade that is individually well-sized can still be the
  one that pushes total correlated exposure past a sane limit.
- Drawdown-based de-risking (reducing position size or pausing new entries
  after a defined drawdown threshold is reached) is a legitimate, common
  risk-management technique — it trades some upside in a recovery for a
  meaningfully reduced chance of the much harder-to-recover deep drawdown.
- Recovery math means a strategy's edge should be evaluated on
  risk-adjusted terms (e.g. how large its worst realistic drawdown is
  relative to its average return), not on average return alone — two
  strategies with the same average return are not equivalent if one of them
  achieves it with a much deeper worst-case drawdown.
