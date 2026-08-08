---
title: "Position Sizing Discipline"
topics: [position_sizing, risk_management]
applies_to: [stock, crypto]
sectors: []
---

Position size is the single lever that determines whether a wrong trade is a
non-event or an account-threatening loss. A correct thesis with the wrong
size still loses money; an average thesis with disciplined size survives
being wrong repeatedly. Sizing discipline is not about maximizing the size of
winners — it is about making sure no single loss can force a decision under
duress.

**Fixed-fractional risk beats fixed-dollar risk.** A fixed-dollar approach
("I always risk $200 per trade") ignores account growth and drawdown state:
the same $200 is a trivial fraction of a healthy account and a dangerous
fraction of an account that has already taken losses. Fixed-fractional
sizing — risking a constant percentage of *current* equity (typically
0.5%-2% per idea for a systematic account) — automatically shrinks position
size after losses and grows it after gains. This is the mechanism that
prevents a losing streak from compounding into ruin: ten consecutive losses
at a fixed 1% risk leaves roughly 90% of the account intact and still
capable of participating in the recovery; ten consecutive losses at a fixed
dollar amount that started as 1% of equity can represent a much larger
fraction of the *remaining* equity by the tenth trade, because the dollar
amount never adjusted downward as the base shrank.

Position size should be derived, not chosen. The correct order of operations
is: (1) decide the stop-loss level from where the thesis is invalidated, (2)
decide how much of the account you are willing to lose if that stop is hit
(the risk fraction), (3) divide risk-in-currency by the per-unit distance to
the stop to get position size. Choosing a position size first and then
picking a stop that "fits" inverts this and quietly turns a risk decision
into an arbitrary one.

**Common sizing mistakes:**

- *Sizing to conviction instead of to risk.* "I'm very confident" is not a
  risk control — confidence and correctness are only loosely correlated, and
  every trader's most confident trades include some of their worst losses.
  Conviction can justify taking the trade; it should not be used to justify
  a larger fraction of the account at risk than the standard sizing rule
  allows, because the market does not know how confident the trader is.
- *Averaging down without a sizing rule.* Adding to a losing position to
  improve the average entry price is only sound if it was planned in advance
  as part of the original risk budget. Unplanned averaging down is usually
  an attempt to avoid admitting the original thesis was wrong, and it
  increases size exactly when the thesis is failing.
- *Ignoring correlated exposure across concurrent positions.* Five separate
  positions each sized at 1% risk is not 5% total risk if the positions are
  correlated (e.g. five momentum longs in the same sector, or several crypto
  assets that move together in a risk-off event) — a single adverse move can
  hit several stops simultaneously. Position sizing has to account for the
  portfolio, not just the individual trade.
- *Re-sizing after the fact to justify a trade already taken.* Sizing
  decisions made retroactively to make a trade "feel" proportionate are a
  sign the original process was skipped.
- *Confusing position size with leverage.* A large position size funded by
  leverage carries a different risk profile than the same notional size
  funded by cash, because leverage compounds losses through margin calls and
  forced liquidation, not just through the underlying price move.

For an automated proposal, the sizing decision should always be checkable
independently of the narrative: given the stop distance and the account's
risk budget, does the position size match what the rule would produce? If a
proposal's size cannot be derived from stop distance and a stated risk
percentage, that is itself a red flag before the trade thesis is even
evaluated.
