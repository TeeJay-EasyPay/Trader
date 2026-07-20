# Production Completion Verification

## Repository evidence

Verified on 20 July 2026:

| Check | Result |
|---|---|
| Python compilation | Passed: `python -m compileall -q src` |
| Completion tests | Passed: 5 |
| Focused production tests | Passed: 48 |
| Authoritative Python suite | Passed: 153 in 48.14 seconds |
| Hosted SQLite refusal | Passed |
| Local/test SQLite support | Passed |
| Partial and duplicate fill reconciliation | Passed |
| Weighted prices, fees, gross/net P&L | Passed |
| Exactly-once terminal learning queue | Passed |
| Worker timeout evidence | Passed |

The authoritative command is `python -m pytest -q tests`. Running unrestricted `pytest` at repository root also discovers stale Python copies inside `mobile/inspect-output`; those copies are Expo inspection artifacts, not the test authority.

## Hosted proof still required

The following cannot be asserted from repository tests and must be observed after deployment:

1. Render API and worker both start on the same deployed commit.
2. Both report active Postgres/Supabase and no SQLite path.
3. Postgres initializes every production schema without unsupported SQL.
4. A worker restart preserves job claims, recommendations and broker evidence.
5. One fresh research cycle persists source observations and a reasoned result.
6. Every recommendation reaches either a recorded governance rejection or execution intent.
7. One genuine Alpaca paper order, when a setup qualifies, links intent, broker order and fills under one logical ID.
8. One terminal trade produces dependable net P&L and exactly one learning run.
9. Founder endpoints display those source records without projection-only claims.
10. Phone-closed activity continues through the soak window.

## Soak protocol

Run for at least one complete equity session and one overnight crypto period. During the run:

- close the mobile app;
- restart the API once;
- restart the worker once;
- inspect heartbeats and scheduled-job rows;
- confirm no duplicate idempotency keys or fill rows;
- compare broker order/fill IDs with canonical records;
- verify every no-trade cycle has primary and secondary reasons;
- reopen the app and confirm the persisted evidence appears.

## Release decision

Repository gate: **passed**.

Hosted production-completion gate: **not yet passed in this task**. No Supabase migration, Render deployment, broker order or soak evidence was performed here. The system must remain at current paper/micro-live limits until hosted proof passes.
