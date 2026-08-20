"""Bounded technical discretion within existing guardrails -- Phase 5.5 of the
CIO-level forecasting build (2026-08-20, Founder-requested).

The Founder asked whether the AI should eventually decide which guardrails to follow.
The agreed answer, and the principle this whole module encodes: **discretion within a
mandate, never authority to rewrite the mandate.** Hard ceilings -- max risk per trade,
max position size, max stop distance, the kill switch, loss circuit breakers -- stay
fixed policy and are never overridable by AI judgment, for the same reason a real fund
never lets a portfolio manager override firm-wide risk limits: overconfidence in a wrong
call is exactly when the large losses happen.

What a real portfolio manager DOES have discretion over, and what this module provides,
is using better information inside those limits:
  - place a stop at a real support level rather than a flat percentage
  - size a high-conviction trade nearer the top of the allowed range, a weak one lower
  - target a real resistance level rather than a fixed multiple

Every function here is a pure function, clamped so its output can never be riskier than
what today's flat-percentage logic would have produced, and falls back to exactly that
flat logic when technical levels are unavailable. That makes each one provable in
isolation -- the same reason _kraken_min_order_floor_notional was written this way.
"""

from __future__ import annotations


def technical_stop_loss(
    *,
    entry_price: float,
    side: str,
    support: float | None,
    resistance: float | None,
    atr: float | None,
    max_stop_loss_pct: float,
    default_stop_loss_pct: float,
    min_stop_loss_pct: float = 0.005,
) -> float:
    """A stop placed just beyond a real technical level, clamped to policy.

    Rationale (knowledge/stop_loss_and_take_profit_mechanics.md): a stop sitting just
    inside an obvious support level gets taken out by ordinary noise that the level
    itself would have absorbed; placing it just beyond that level means the stop is hit
    only when the level genuinely fails, which is the actual thesis-invalidation event.

    Clamped at BOTH ends, and this is the safety property that matters:
      - never further than max_stop_loss_pct from entry (policy ceiling -- a technical
        level far away must never widen real risk beyond what policy allows)
      - never tighter than min_stop_loss_pct (a stop a hair from entry is noise-triggered
        and would churn the account)
    Falls back to default_stop_loss_pct whenever no usable level exists.
    """
    if entry_price <= 0:
        return 0.0
    is_buy = str(side or "").lower() == "buy"
    level = support if is_buy else resistance
    buffer = atr * 0.25 if atr and atr > 0 else entry_price * 0.002
    candidate: float | None = None
    if level and level > 0:
        candidate = (level - buffer) if is_buy else (level + buffer)
        # A "support" above entry (or resistance below it) is not a stop level for this
        # side at all -- fall through to the flat default rather than inverting the trade.
        if is_buy and candidate >= entry_price:
            candidate = None
        elif not is_buy and candidate <= entry_price:
            candidate = None
    if candidate is None:
        candidate = entry_price * (1 - default_stop_loss_pct) if is_buy else entry_price * (1 + default_stop_loss_pct)
    widest = entry_price * (1 - max_stop_loss_pct) if is_buy else entry_price * (1 + max_stop_loss_pct)
    tightest = entry_price * (1 - min_stop_loss_pct) if is_buy else entry_price * (1 + min_stop_loss_pct)
    if is_buy:
        return round(min(max(candidate, widest), tightest), 8)
    return round(max(min(candidate, widest), tightest), 8)


def technical_take_profit(
    *,
    entry_price: float,
    stop_loss: float,
    side: str,
    resistance: float | None,
    support: float | None,
    min_reward_risk: float = 2.0,
) -> float:
    """A target at a real technical level, floored at the policy-required reward:risk.

    A target set just beyond heavy resistance frequently never fills; one set at the
    level captures the move that actually happened. But a technical level that would
    produce a worse-than-required reward:risk ratio is rejected in favour of the
    ratio-derived target -- the risk/reward discipline is policy, not discretion.
    """
    if entry_price <= 0:
        return 0.0
    is_buy = str(side or "").lower() == "buy"
    risk_per_unit = abs(entry_price - stop_loss)
    ratio_target = entry_price + risk_per_unit * min_reward_risk if is_buy else entry_price - risk_per_unit * min_reward_risk
    level = resistance if is_buy else support
    if not level or level <= 0:
        return round(ratio_target, 8)
    if is_buy:
        # Only take the technical level when it is at least as far as the required ratio.
        return round(level if level >= ratio_target else ratio_target, 8)
    return round(level if level <= ratio_target else ratio_target, 8)


def conviction_scaled_notional(
    *,
    approved_notional: float,
    confidence: float,
    min_confidence: float,
    min_fraction: float = 0.5,
) -> float:
    """Scale size within the already-approved ceiling by how strong the case actually is.

    Strictly risk-reducing by construction: the result is always between min_fraction and
    1.0 of `approved_notional`, so it can never exceed what every existing policy check
    already approved -- it only declines to use the full allowance when conviction is
    weak. A marginal candidate at exactly the minimum confidence bar gets min_fraction of
    the allowance; a maximally-confident one gets the full amount it would have received
    today.
    """
    if approved_notional <= 0:
        return 0.0
    ceiling = float(approved_notional)
    span = 1.0 - min_confidence
    if span <= 0:
        return ceiling
    position = (float(confidence) - min_confidence) / span
    position = max(0.0, min(1.0, position))
    fraction = min_fraction + (1.0 - min_fraction) * position
    return round(ceiling * fraction, 8)
