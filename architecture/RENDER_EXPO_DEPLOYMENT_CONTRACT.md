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

## OTA vs Rebuild

JavaScript-only UI and API-contract changes can normally ship by EAS OTA if the native runtime is unchanged. Icon/native metadata changes require an EAS rebuild.
