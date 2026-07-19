# Render and Expo Deployment Contract

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

- primary refresh: `/status`, `/portfolio`, `/recommendations`, and `/autonomous-activity`;
- secondary background refresh: Founder brief, benchmark brief, intelligence themes, companies, notifications, performance attribution, and daily learning.

Primary refresh calls have bounded timeouts so the app can fail visibly instead of spinning indefinitely. Secondary calls hydrate their cards after the main screen is usable.

This does not remove Render cold-start latency. If the web service uses a plan that spins down after inactivity, the first request can still take tens of seconds while the API wakes. Continuous worker activity proves backend autonomy but does not by itself keep the HTTP API process warm.

The mobile app must not treat a slow `/status` response as proof that the whole backend is unavailable. If `/status` times out during refresh, the app should display a degraded status explanation and keep the interface usable. Protected command failures may still show explicit alerts because those actions require confirmation of authenticated backend control.

## OTA vs Rebuild

JavaScript-only UI and API-contract changes can normally ship by EAS OTA if the native runtime is unchanged. Icon/native metadata changes require an EAS rebuild.
