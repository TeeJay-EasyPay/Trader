---
title: "Short-Selling Mechanics"
topics: [short_selling, risk_management]
applies_to: [stock]
sectors: []
---

Shorting is not simply "the opposite of going long" — its risk profile is
structurally asymmetric and it depends on mechanics that a long position
never has to deal with.

**The asymmetry that matters most: unlimited loss, capped gain.** A long
position's maximum loss is the entry price (it can only go to zero); its
maximum gain is theoretically unbounded. A short position's maximum gain is
capped at the entry price (the stock can only go to zero); its maximum loss
is theoretically unbounded, because there is no ceiling on how high a price
can rise before a short is closed out. This alone means a short position
sized the same way as a long position (same currency risk budget) needs a
tighter stop or smaller size to keep the *realistic* worst case bounded,
because the tail risk on the loss side is structurally worse.

**Borrow risk.** Shorting requires borrowing shares from a broker or another
holder, and that borrow is not guaranteed to remain available. If the lender
recalls the shares (common in a heavily-shorted, hard-to-borrow name) the
short can be forced to close — "bought in" — at the prevailing market price
regardless of the trader's own stop-loss level or thesis. Borrow cost itself
is also a real, ongoing cost of holding a short (a daily fee, higher for
hard-to-borrow names) that a hold-to-target long position does not have; a
short thesis that is correct but slow to play out can still lose money to
carrying cost.

**Short squeezes.** A short squeeze is a self-reinforcing price spike caused
by short sellers being forced to buy back shares to close losing positions,
which pushes the price higher, forcing more shorts to cover, in a feedback
loop. Squeezes are most violent in names with high short interest relative
to float (a large fraction of available shares are already sold short) and
low liquidity (a modest amount of forced buying moves the price a lot). A
short thesis that is fundamentally correct can still produce a severe,
fast, account-threatening loss if it is expressed in a name with these
characteristics, purely from crowding, independent of the thesis's ultimate
correctness.

**Timing asymmetry vs. going long.** Prices tend to fall faster than they
rise — declines are frequently driven by fear and forced selling (margin
calls, redemptions), which compress into shorter, sharper moves than the
grinding, sentiment-driven climbs that build most uptrends. This means a
correct short thesis can resolve faster than a correct long thesis, which is
a genuine edge-timing consideration — but it cuts both ways: it also means a
short seller has less time to react if the position moves against them
before the position is stopped out, compared to the more gradual give-back
that usually precedes a long position's stop being hit.

**Borrow availability and squeeze risk should be treated as first-class
inputs to whether a short is put on at all**, not just to how it is sized —
a fundamentally sound short thesis in a name that is hard to borrow or has
extreme short interest may not be a good short *trade*, even if it would be
a good short thesis in a more liquid, easier-to-borrow name.
