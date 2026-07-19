# Render and Expo Deployment Contract

## Production Evidence Activation contract

- Render API: serves authenticated APIs and does not own critical recurring schedules.
- Render worker: runs `python -m ai_trader run-worker --sleep-seconds 60`.
- Shared state: `AI_TRADER_DATABASE_BACKEND=postgres` and the same `DATABASE_URL` on API and worker.
- API scheduler: `RESEARCH_SCHEDULER_ENABLED=false`.
- Worker research: `AI_TRADER_WORKER_RESEARCH_ENABLED=true`.
- Evidence snapshots: `AI_TRADER_PRODUCTION_SNAPSHOT_INTERVAL_SECONDS=300` by default.
- Expo startup: loads cached Founder evidence, then requests `/founder-evidence`; it does not block on `/status`.
- Credentials and API tokens remain environment variables and are never written to the mobile evidence cache except for the existing public command-token build contract.

Date: 2026-07-17

## Render Startup Contract

Render startup must:

- initialize all SQLite schemas additively;
- never log secrets;
- reconcile Alpaca and Kraken broker history into the canonical lifecycle;
- report disconnected future brokers honestly;
- expose `/healthz`, `/status`, `/recommendations`, `/portfolio`, `/performance-attribution`, `/daily-learning-update`, `/ask-ai-trader`, `/operational-truth`, and `/world-class-evidence`.

## Expo Contract

The Expo app must:

- send `Authorization: Bearer ${EXPO_PUBLIC_AI_TRADER_API_TOKEN}`;
- treat Ask AI as read-only;
- prioritise Alpaca and Kraken;
- show disconnected brokers only in a compact future section;
- tolerate partial API payloads;
- explain missing values.

## Mobile Refresh Contract

The mobile app must not block the Founder interface on every optional endpoint.

Refresh is split into:

- primary refresh: `/operations-health`, `/activity/summary`, `/activity/why-no-trade`, `/portfolio`, and `/recommendations`;
- secondary background refresh: full `/status`, full `/autonomous-activity`, Founder brief, benchmark brief, intelligence themes, companies, notifications, performance attribution, and daily learning.

Primary refresh calls have bounded timeouts so the app can fail visibly instead of spinning indefinitely. Secondary calls hydrate their cards after the main screen is usable.

This does not remove Render cold-start latency. If the web service uses a plan that spins down after inactivity, the first request can still take tens of seconds while the API wakes. Continuous worker activity proves backend autonomy but does not by itself keep the HTTP API process warm.

The mobile app must not treat a slow `/status` response as proof that the whole backend is unavailable. If `/status` times out during refresh, the app should display a degraded status explanation and keep the interface usable. Protected command failures may still show explicit alerts because those actions require confirmation of authenticated backend control.

The mobile app must also avoid treating the full `/autonomous-activity` payload as a first-load dependency. The Dashboard and Activity summary should be able to prove basic autonomy from lightweight persisted evidence first, then hydrate the full timeline and broker-level details in the background.

## OTA vs Rebuild

JavaScript-only UI and API-contract changes can normally ship by EAS OTA if the native runtime is unchanged. Icon/native metadata changes require an EAS rebuild.
