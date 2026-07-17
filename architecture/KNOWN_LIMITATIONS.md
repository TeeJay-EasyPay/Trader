# Known Limitations

## Data And Attribution

1. Trade lifecycle reconstruction is incomplete.
   `BROKER_TRADE_HISTORY` stores raw or near-raw broker rows. Some rows do not contain enough information to show entry reason, exit reason, target price, stop loss, current price, or P&L.

2. P&L can be unavailable without prior snapshots.
   Day/week P&L requires earlier portfolio snapshots. If the service was not running or no snapshot exists for the comparison window, the UI correctly shows unavailable.

3. Closed trade attribution is incomplete.
   `PERFORMANCE_ATTRIBUTION` is reliable only when the system can link entry and exit information. Broker fills that are not matched into round trips may not produce closed-trade P&L.

4. Raw broker payloads are too visible.
   Trade History currently exposes technical broker data. This is useful for debugging but not ideal for founder UX.

## Broker Limitations

1. Alpaca is paper only.
   Live Alpaca trading is not approved.

2. Kraken is live micro-trading only under explicit seatbelts.
   Kraken does not provide a true paper trading account. The system uses real small orders when all switches are enabled.

3. Coinbase, Binance, Interactive Brokers, and Saxo are not complete.
   They are placeholders or future adapter surfaces.

4. Kraken managed exits depend on polling.
   Exit behavior is not exchange-native bracket order behavior. It depends on the hosted service running and checking prices.

## AI And Learning Limitations

1. OpenAI availability is external.
   Ask AI and proposal analysis depend on `OPENAI_API_KEY`, network availability, model availability, and request timeouts.

2. AI memory is only durable if written to SQLite.
   Chat reasoning is not persistent platform wisdom unless saved.

3. AI does not automatically improve strategy.
   It can produce lessons and recommendations. It cannot change strategy, guardrails, or broker settings without founder/engineering action.

4. Benchmark trader learning uses public information only.
   It cannot reliably know private trades or proprietary performance.

## Research Limitations

1. Crypto sentiment, news, and on-chain data are not fully provider-backed.
   Fields are left unavailable rather than fabricated.

2. Public APIs can fail or rate-limit.
   CoinGecko and broker APIs can be unavailable, incomplete, or delayed.

3. Research state needs better worker-level observability.
   The current UI shows status but should expose worker heartbeats and last error by worker.

## UI Limitations

1. `mobile/App.js` is large and monolithic.
   It should be split into screens, API client, formatting helpers, and components.

2. Dense tables are hard on mobile.
   Broker panels and trade history need progressive disclosure and better summary cards.

3. Some values show "Not available" without enough context.
   The UI should distinguish not configured, not fetched, not applicable, missing broker payload, and not yet closed.

## Architecture Concerns

1. SQLite is a single-file operational store.
   This is acceptable for personal use but not suitable for multi-user scale without migration.

2. Schema migrations are ad hoc.
   Modules create tables and add columns, but there is no formal migration framework.

3. Route handling is concentrated in `api.py`.
   The API file is large and should be split after behavior stabilizes.

4. Environment configuration is powerful.
   Broker permissions are controlled by env vars and database rows. Future changes should introduce audited configuration changes.

5. Render config sync should remain limited.
   Allowing the app to mutate cloud env vars is useful but risky. It must stay restricted, audited, and explicit.
