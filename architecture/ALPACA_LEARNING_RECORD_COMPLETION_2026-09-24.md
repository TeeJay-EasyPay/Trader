# Alpaca learning-record completion — 24 September 2026

## Production finding

Trader's concern was valid. Production held 25 terminal Alpaca trades with completed
learning workflows and recorded gross results, but zero individual canonical net results.
The compact packet therefore used the word "complete" for workflow completion while the
evidence needed to judge trading improvement was incomplete. Separately, 120 newer Alpaca
shadow candidates were pending because the settlement path read database candles while
the equity history already downloaded for research deliberately lived in the bounded Render
host cache. The 870 older unrecoverable simulations remain excluded; they are not relabelled
as measured results.

## Implemented boundary

- `workflow completed`, `review completed`, and `evidence-complete learning loop` are now
  separate counters. Only a trade with an individual canonical net result enters the last
  counter or supports an improvement claim.
- The 25 gross-known Alpaca records receive a compact, explicitly provisional estimate using
  Alpaca's published regulatory formula per trade. This is not broker-attributed actual cost,
  does not allocate account-level fee ledger rows, and cannot prove an edge.
- Alpaca's equity settlement adapter now accepts the historical `stock` alias as well as
  `equity`, and consumes verified daily bars from the same bounded host cache as historical
  screening. No bulk bars are copied into Supabase.
- Unresolved shadow symbols are prioritised inside the existing 20-symbol Alpaca download
  budget. After the scheduled cache refresh, settlement runs immediately from the warm cache;
  it creates evidence only and has no broker-order capability.
- Trader's assessment prompt must distinguish configured code, measured production outcomes,
  provisional estimates, and actual after-cost results.

## Expected production proof

Before the first post-deployment refresh, the packet must honestly show zero evidence-complete
Alpaca loops, 25 provisional per-trade estimates, 120 pending newer simulations and 870 excluded
legacy simulations. After the cache refresh and settlement run, `adapter_v2_settled_outcomes`
must increase before Trader may say the new Alpaca simulation path is proven operational.
