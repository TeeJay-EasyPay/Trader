---
title: "Stop-Loss and Take-Profit Mechanics"
topics: [stop_loss_discipline, risk_management, position_sizing]
applies_to: [stock, crypto]
sectors: []
---

A stop-loss is not a comfort setting — it is the price at which the original
thesis is proven wrong. Confusing "where I'd feel bad" with "where I'm wrong"
is the single most common stop-placement error. A stop placed too close to
entry (to limit the dollar loss on a position that was sized too large) gets
hit by ordinary noise regardless of whether the thesis was correct, producing
a string of losses that says nothing about whether the underlying idea was
good. A stop placed at the actual invalidation level — a support/resistance
break, a trend-line failure, a level where the setup's logic no longer holds
— gets hit only when the thesis is genuinely wrong, which is the only time it
should be hit.

**The correct ordering**: find the invalidation level first, then size the
position so that the loss at that level equals the intended risk fraction of
the account (see position sizing). Never do it in the other order — deciding
the position size first and then moving the stop closer or further to make
the dollar risk "fit" quietly turns a technical decision into an arbitrary
one and disconnects the stop from the thing it is supposed to measure.

**R-multiple thinking.** "R" is the initial risk per unit (entry price minus
stop price for a long). Expressing targets and outcomes in R rather than in
absolute currency makes trades comparable regardless of size: a trade risking
$50 to make $150 and a trade risking $500 to make $1,500 are both "2R"
opportunities, and a system's edge is best evaluated by its distribution of R
outcomes (win rate combined with average winning R vs. average losing R), not
by the currency amounts of any single trade. A strategy can be profitable
with a below-50% win rate if average winners are large enough in R terms
relative to average losers — and can lose money with a high win rate if
losers are occasionally very large in R terms. Never evaluate a strategy on
win rate alone.

**Take-profit placement** should follow the same "derived, not arbitrary"
principle: a target set at a real resistance level, a prior high, a
measured-move projection, or a fixed R-multiple consistent with the
strategy's tested edge — not a round number chosen because it "feels right."
A common mistake is setting a take-profit far enough away that it is rarely
reached, which understates a strategy's true win rate and overstates its
patience; the opposite mistake — a take-profit so close it is reached by
noise — caps genuine winners short of their real move.

**Trailing stops** move the stop in the direction of a favorable move to lock
in partial profit while leaving room for the trade to keep working, but they
introduce a real trade-off: too tight, and ordinary volatility on the way to
the real target stops the trade out early, converting what would have been a
full winner into a small one; too loose, and a trailing stop gives back most
of an open gain before triggering. There is no universally correct trailing
distance — it should be set relative to the instrument's normal volatility
(e.g. a multiple of its average true range), not a fixed percentage applied
uniformly across very different assets.

**Never move a stop further away once it is set**, except as part of a
pre-planned, rules-based trailing mechanism. Moving a stop away from price
after entry, in response to the position moving against the original thesis,
converts a defined, bounded risk into an undefined one — this is one of the
most reliable ways an otherwise disciplined process produces an outsized
loss.
