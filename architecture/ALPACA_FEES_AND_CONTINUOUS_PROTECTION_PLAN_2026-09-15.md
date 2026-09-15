# Alpaca Fees and Continuous Protection Implementation Plan

Date: 2026-09-15  
Status: Approved for implementation; not yet implemented

## Objective

Make Alpaca paper results reflect realistic costs and prove that the risk protection assumed
by each strategy remained present throughout the trade. Neither workstream may loosen trading
guardrails, activate live trading, or manufacture evidence that Alpaca does not provide.

## Production evidence behind the plan

- The configured Alpaca paper API returned 44 `FEE` activities from 2 July through
  11 September 2026, totalling USD 3.67: 16 CAT, 15 TAF and 13 REG entries.
- These are simulated paper-account ledger charges, not real-money charges and not proof of
  future live costs.
- The existing integration retrieves `FILL` activities but does not ingest `FEE` activities.
- Alpaca's returned aggregate fee records do not contain an order ID. They can support exact
  account/period net performance but must not be assigned to individual trades by guesswork.
- The application records planned Alpaca stops and verified stop-order exits, but does not yet
  persist evidence that the expected stop stayed active and correctly sized for the complete
  lifetime of every open position.

## Workstream 1 — Fee-aware Alpaca paper trading

### 1. Ingest actual paper-ledger fees

- Fetch bounded, paginated `FEE` activities during the existing Alpaca broker poll.
- Persist only the stable activity ID, date, subtype, amount, currency, description and source;
  avoid duplicating full broker payloads.
- Upsert idempotently so an unchanged poll creates no database write.
- Maintain a durable cursor/watermark and backfill the currently visible 44 records once.

### 2. Report net account and period performance

- Add fee totals by day, week, month and requested reporting period.
- Calculate `account_net_pnl = gross_realised_pnl - recorded_account_fees` for matching periods.
- Keep individual trade results labelled `gross before unallocated account fees` whenever a
  fee activity has no broker order identity.
- Display recorded fee amount, fee coverage dates and whether the source is Alpaca paper or an
  estimate. Never present a paper fee as a real-money charge.

### 3. Apply a realistic pre-trade cost hurdle

- Add an Alpaca-specific cost estimator; never reuse Kraken's fee rate.
- Prefer the rolling effective rate derived from this account's recorded Alpaca fee activities
  and eligible sell notional when coverage is sufficient.
- When measured coverage is insufficient, use Alpaca's current published equity schedule for
  applicable REG, TAF and CAT charges. Record the schedule date and parameters so a future rate
  change is visible rather than silently hard-coded.
- Treat commission as zero only for the configured self-directed commission-free account
  arrangement; fail to `unknown` if that account assumption cannot be verified.
- Pass the estimate to the final Alpaca pre-execution economics check. A trade fails only when
  its planned reward after estimated costs falls below the existing minimum reward/risk policy.
- Replace estimates with recorded paper fees in period reporting. Never subtract both an
  estimate and an actual fee from the same result.
- Measure spread and slippage separately from broker fees. Use actual decision and fill prices
  where available; do not stack an arbitrary flat spread penalty on top of observed slippage.

### Acceptance criteria

- The 44 current API activities reconcile to USD 3.67 without duplication.
- Daily/monthly Alpaca reports expose gross P&L, recorded paper fees and account-level net P&L.
- A fee without an order link does not alter any individual trade's stored P&L.
- Pre-trade evidence records the estimated fee rate, source, schedule/evidence date and net
  reward/risk calculation.
- Tests prove actual-versus-estimated fees are mutually exclusive and Kraken economics are
  unchanged.

## Workstream 2 — Continuous broker-side protection evidence

### 1. Reuse existing polling data

- Use the Alpaca positions and nested order/leg responses already fetched by broker polling.
- Do not introduce a second high-frequency broker request or a per-position Supabase query.
- Build one in-memory map of open positions and one map of active protective stop legs per poll.

### 2. Verify the protection contract

For each AI-managed open position, compare the expected protection recorded at entry with the
broker response:

- an active stop order exists at Alpaca;
- the stop belongs to the correct entry/bracket and symbol;
- protected quantity covers the current open quantity, including partial fills;
- stop status is not rejected, cancelled, expired or replaced without a valid successor;
- recorded stop price and side match the approved protection contract within explicit rounding
  tolerance.

### 3. Persist changes and raise actionable incidents

- Record a compact protection state only when its digest changes, plus one bounded periodic
  confirmation. Normal unchanged polls perform no write.
- Immediately create/update one deduplicated critical incident when protection is missing,
  undersized or invalid. Resolve that incident only after broker evidence proves protection is
  restored.
- Record `unknown` rather than `protected` when Alpaca is unavailable or the order relationship
  cannot be established.
- Keep remediation fail-safe and separate: this workstream observes and alerts first. It must
  not place, cancel or replace an order without a separately reviewed recovery design.

### Acceptance criteria

- Tests cover active protection, missing stop, rejected/cancelled stop, partial-fill quantity,
  replacement chains, broker unavailability and recovery.
- An unchanged healthy poll adds no database row and no additional Alpaca request.
- A genuine protection gap produces one deduplicated critical incident with position, expected
  stop and broker evidence.
- Historical strategy reports can distinguish continuously verified protection, a known gap and
  unknown coverage. Performance is never called risk-controlled for an unverified interval.

## Sequence and release controls

1. Implement fee schema, ingestion, summaries and backfill with read-only broker access.
2. Add Alpaca pre-trade cost evidence and regression tests without changing existing reward/risk
   thresholds.
3. Implement protection comparison from already-fetched poll data and change-only persistence.
4. Run focused fee, reconciliation, order lifecycle, protection and egress tests, then the
   broker/execution regression suite.
5. Deploy to paper services, verify exact Render revisions and run one bounded Alpaca poll.
6. Reconcile fee totals to USD 3.67, verify no duplicate rows, and verify healthy protection
   checks create no extra broker request.
7. Update the implementation log with measured results. Any live-trading decision remains a
   separate Founder approval.

## Egress budget

- One additional bounded `FEE` endpoint call may be folded into the existing Alpaca poll until
  a cursor/stream is established; database reads and writes must remain batched.
- No raw recurring payload snapshots.
- Unchanged protection state writes zero rows.
- The release report must measure requests, returned rows and bytes over a clean window and
  compare them with the current baseline before claiming negligible egress.
