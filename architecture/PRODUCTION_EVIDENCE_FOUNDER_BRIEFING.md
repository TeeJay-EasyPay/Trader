# Production Evidence Founder Briefing

## What changed

AI Trader's paid Render worker now owns recurring research as well as broker polling, managed exits, execution evaluation and learning. Its useful outputs are copied into shared Supabase/Postgres evidence that the phone can read after being closed.

The app now opens from one compact evidence feed and a local cache. It no longer waits for the old, slow `/status` endpoint before showing its main screens.

## What you should see

- Dashboard: whether the worker is operating, its latest meaningful action, current broker snapshots and the specific reason no trade occurred.
- Activity: research, decisions, broker observations, orders/fills and learning from persisted evidence.
- Recommendations: current saved ideas with arguments for and against.
- Portfolio: current broker value/cash and observable trades, with realized P&L only where proven.
- Market: fresh worker research runs and assets reviewed.
- Learning: completed learning work and honest insufficient-evidence messages.

## What this does not promise

This work does not force trades or loosen governance. The worker can research continuously and still place no order when no strategy passes Portfolio Manager, Risk Engine, maturity and broker permission gates. That is healthy inactivity and the app now explains it.

An open holding is not a realized profit or loss. Exact trade P&L requires a matched entry and exit plus broker/reconciliation evidence. The app must say that rather than guess.

## Production proof

The Render worker is healthy on revision `573c36b3`, its heartbeat advances while long broker work runs, the shared database is Postgres, and the scheduler is active. The latest verified 24-hour evidence contained four research runs, 36 assets analysed and 24 recommendations. No order passed all execution gates; the app now reports that outcome directly.

The Android runtime `1.0.2` update was published to both `hosted-preview` and `preview`. Restart the installed app once, allow it a few seconds to download the update, then close and reopen it. Alpaca paper auto-trading remains a separate explicit permission and was not silently enabled by this sprint.
