# Experiment continuity and faster learning — 24 September 2026

## Completed actions

1. **Protect experiment continuity.** A small explicit behaviour contract now defines what
   makes evidence comparable. Only changes to decision eligibility, risk, prices, costs,
   market-data meaning or simulation outcomes require a new baseline. Operational and UI
   changes no longer restart tests.
2. **Accelerate evidence safely.** The historical cache now produces bounded, deterministic,
   point-in-time market-rule opportunities using prior prices only. They supplement—not
   impersonate—recorded AI decisions. Separate Alpaca and Kraken profiles expose useful
   provisional findings earlier while retaining a larger final gate before recommendation.

## Evidence boundary

- A provisional finding can focus the next experiment; it cannot change a trading rule.
- Historical results cannot approve paper or live activation.
- A final recommendation still requires the unchanged prospective paired simulation,
  after-cost result, independence, concentration and drawdown checks.
- Every generated opportunity carries its rule version and synthetic evidence label.
