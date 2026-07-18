# Always-On Founder Briefing

## What Changed

AI Trader now has an operations evidence layer.

It can record:

- whether a background worker is alive;
- whether a scheduled job ran;
- what research reviewed;
- why no trade happened;
- what shadow trades were considered;
- whether operational incidents need attention.

## What This Solves

Previously, seeing no Alpaca trades did not clearly tell us whether:

- nothing qualified;
- the scheduler did not run;
- auto trading was disabled;
- the broker failed;
- market data was stale.

The new operations layer is designed to make that visible.

## What Can Be Safely Relied On Today

- The code now persists job runs.
- The code now persists worker heartbeats.
- The code now persists research funnels.
- The code now persists shadow trades.
- The app can show a 24-Hour Operations card.

## What Must Still Be Proven After Deployment

- Supabase/Postgres shared datastore is connected, or another production-safe shared datastore is available.
- Render worker is actually running against the shared datastore.
- Render cron jobs are actually firing against the shared datastore.
- Records survive deployment and restart.
- Alpaca research runs without opening the mobile app.
- If no trade happens, the persisted reason explains why.

## Plain-English Standard

The app should now tell you:

> AI Trader ran and nothing qualified.

or:

> AI Trader did not prove that the background job ran.

Those are very different situations.
