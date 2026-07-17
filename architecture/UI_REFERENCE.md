# UI Reference

The mobile app is implemented in `mobile/App.js`. It is a founder-facing operations console. It does not own trading rules; it displays backend state and sends commands to API endpoints.

## Navigation

Current tabs:

- Command
- Trade History
- Recommendations
- Intelligence
- Ask

## Command Screen

Purpose: show operational readiness, executive summary, broker status, controls, risk settings, and reports.

Key areas:

- Connection & Trading Readiness.
- AI executive summary.
- Broker panels.
- Trading permissions and seatbelts.
- Report buttons.
- Emergency controls.

Readiness card shows:

- Mobile command token status.
- Render API status.
- Control action availability.
- OpenAI availability.
- Broker connection status.
- Per-broker auto-trading state.

Broker panels show:

- Connection status.
- Portfolio value.
- Cash.
- Estimated in positions.
- Buying power.
- Open positions.
- Day/week/month P&L.
- Trades today.
- Research status.
- Due diligence status.
- Auto trading status.

Broker controls include:

- Run Analysis.
- Daily Report.
- Enable Auto Trading.
- Disable Auto Trading.

Kraken panels also expose:

- Trading allocation.
- Max order.
- Min order.
- Max open AI-managed trades.
- Remaining AI trade slots.
- Allowed pairs.
- Real order permission switches.

## Trade History Screen

Purpose: show trade history by broker with summary figures.

Filters:

- All
- Alpaca
- Kraken
- Coinbase
- Binance
- Interactive Brokers

Top summary:

- Daily P&L.
- Completed trades today.
- Open positions.
- Rows shown.

Each trade row is collapsible. Expanded fields include:

- Broker.
- Symbol.
- Side.
- Status.
- Quantity.
- Entry price.
- Target price.
- Current live price.
- Stop loss.
- Exit price.
- P&L.
- Entry date and time.
- Exit date and time.
- Time held.
- Entry reason.
- Exit reason.
- Learning factors.
- Technical broker data.

Current limitation: some rows are raw broker rows. When a broker row is not linked to a managed exit or performance attribution record, entry reason, exit reason, target price, and P&L can be unavailable.

## Recommendations Screen

Purpose: display saved recommendation history and allow manual or automatic execution attempts.

Capabilities:

- Load latest recommendation set from SQLite on screen open.
- Refresh existing recommendations.
- Run new analysis.
- Run Kraken analysis.
- Run stock analysis.
- Auto Execute 85%+.
- Filter by broker/exchange.
- Filter by confidence.
- Filter by status/freshness.
- Expand individual recommendation cards.

Recommendation cards show:

- Symbol.
- Confidence.
- Freshness.
- Generated and expiry time.
- Suggested broker.
- Exchange.
- Market open status.
- Auto eligibility.
- Rejection reason.
- Investment score components.
- Suggested stop loss and take profit.
- Position size.
- Due diligence status.
- Passed and failed guardrails.
- Exit plan.
- Manual approval input.

Execution from the screen still goes through the API and orchestrator. A recommendation visible in the UI is not automatically executable.

## Intelligence Screen

Purpose: reassure the founder that the research and knowledge engines are active and provide access to company/theme/crypto/benchmark intelligence.

Displays:

- General intelligence.
- Stock intelligence.
- Crypto intelligence.
- Research health.
- Benchmark learning.
- Latest learning.
- Current research cycle.
- Current broker.
- Current asset.
- Research freshness.
- Research queue.
- Due diligence progress.
- Assets analyzed.
- Active watchlists.

Where possible, intelligence names can link to matching recommendation cards.

## Ask Screen

Purpose: ask read-only natural-language questions about AI Trader data.

Suggested prompts:

- Am I up or down today, and why?
- What open positions do I have?
- Which recent trades made or lost money?
- What has AI Trader learned today?
- Is AI Trader getting better at trading?

Rules:

- Ask AI is read-only.
- It cannot place trades.
- It cannot approve trades.
- It cannot enable auto trading.
- It cannot change guardrails.
- It cannot change broker settings.

The screen calls `POST /ask-ai-trader`. The backend builds evidence from SQLite and current status. If OpenAI is available, it returns a conversational explanation. Otherwise, it returns a local evidence summary or an error.

## Browser Report Views

Report buttons create report rows and open `/reports/{id}`. Reports are rendered as simple HTML from stored Markdown.

## UX Issues To Track

- Long tables are dense on mobile.
- Some values are unavailable because broker normalization is incomplete.
- Raw broker payloads are useful for engineering but too noisy for founder UX.
- Trade History should increasingly show canonical lifecycle records instead of raw fills.
