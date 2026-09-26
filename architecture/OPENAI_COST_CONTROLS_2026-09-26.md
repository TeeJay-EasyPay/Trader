# OpenAI cost controls — 26 September 2026

## Release status

Implemented locally; **not deployed or activated**. No paid provider calls made for
this implementation. The founder's screenshot shows September spend of $105.43,
already above the newly requested $30 monthly allowance. Deployment requires an
explicit decision on the opening month/balance. Do not initialize September at $0
or silently authorize another $30. An October-only policy would block September
requests, not grant an unspecified bridging allowance.

## Changes

- Routine read-only explanations use GPT-6 Luna, no reasoning, at most 1,200 output
  tokens. Experiment proposals/review summaries use GPT-6 Sol. Existing live
  proposal, crypto review, forecast and paired-reference assessment models remain
  pinned to their existing configuration until representative quality evaluation.
- Stable chat instructions have an explicit 30-minute cache breakpoint; current
  evidence and history stay outside that prefix. No evidence was removed, and no
  cache-hit/savings claim has been measured yet.
- Standup defaults to zero extra peer replies on both client and server. Explicit
  exchanges are capped at two extras. Failed/budget-limited replies and short
  agreement-only responses do not trigger another paid follow-up.
- A PostgreSQL advisory-lock-protected monthly ledger reserves money before each
  request. Limits are $30 overall, $18 trading, $7 conversation (including voice),
  $5 research. Calendar months use UTC. Reservations include concurrent work.
  Timeouts, process crashes and missing usage retain conservative charges; no
  automatic paid retry or upgrade to Astra. Unknown models/context mechanisms
  are refused until their cost is bounded. No prompts or trade histories stored.
- Web-grounded benchmark research keeps its existing model and real search,
  limited to one tool call per request; its reservation covers expanded context
  and a conservative tool fee. It is not replaced with ungrounded generated facts.
- Legacy speech uses character-priced `tts-1` to bound charges; live conversational
  voice remains `gpt-realtime`. File transcription validates recording duration
  (maximum two minutes) with mutagen before calling Whisper. Realtime replies
  reserve shared money before response creation; transcription headroom covers
  the provider's 60-minute maximum, then shrinks after confirmed normal hangup.
- Budget denial or failure to verify the shared ledger refuses a new crypto
  candidate; it must not use the existing unreviewed-request fallback. Existing
  protective exits, broker reconciliation and deterministic simulation logic do
  not acquire AI budget reservations.
- Usage response/mobile view adds a labelled conservative app allowance. It is
  **not** a prepaid balance or an organization invoice. Other apps and Anthropic
  costs are outside this OpenAI ledger. Price changes and usage outside this app
  still require billing reconciliation. Client/provider misuse is not controlled
  by the app ledger; retain provider-level restrictions as defense in depth.

## Activation and verification

1. Obtain the founder's current-month spending decision. Initialize the existing
   private `EXPERIMENT_CONTROL` row `openai_budget_policy` with `start_month`
   (`YYYY-MM`) and `opening_micro_usd` (nonnegative integer dollars × 1,000,000).
   This requires no schema bootstrap, history export or trading-setting change.
   In later months the opening balance is zero; the activation month must use a
   confirmed opening amount. Missing policy fails closed on hosted requests.
2. Commit/release backend and worker together; publish the mobile OTA. No native
   Android rebuild is required. Confirm both services use the intended revision.
3. Within the confirmed allowance, run small representative Luna conversation and
   Sol structured-proposal checks: currencies, unknown fees, no invented actions,
   valid research receipts, no claims that activity proves profitability. Offline
   tests establish wiring, not real-model quality or account availability.
4. Check app budget status and safe budget-exhaustion behavior. Compare actual
   provider billing with conservative accounted usage, including input cache
   writes, reasoning output, tool calls and voice. Do not promise a percentage
   reduction or call the new configuration profitable.
5. Evaluate Sol on frozen live-assessment examples before any future change to
   live decision models. No live-model migration is included in this release.

## Verification completed locally

- 252 focused Python tests passed in the combined regression run (budget,
  concurrency, timeouts, model routing, conversations, experiments, forecasts,
  voice, existing protective controls and learning/egress regressions).
- Five mobile Standup flow tests passed. Their fixture now accounts for existing
  foreground recovery and the separate voice component.
- Both changed mobile components compile with the Expo Babel preset.
- `git diff --check` passed. Unrelated `unused.sqlite3` and prior test/build
  artifacts were preserved and excluded from the change.
- No production database mutations, paid model evaluations, live voice sessions,
  deployment or measured billing savings are claimed by these offline checks.

## Sources used

- [GPT-6 migration guidance](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra)
- [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [Sol](https://developers.openai.com/api/docs/models/gpt-6-sol)
- [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Pricing](https://developers.openai.com/api/docs/pricing)
- [Realtime maximum session length](https://developers.openai.com/api/docs/guides/realtime-conversations)
- [Whisper](https://developers.openai.com/api/docs/models/whisper-1), [TTS-1](https://developers.openai.com/api/docs/models/tts-1)

OpenAI Docs guided model/API compatibility and cache configuration. Standard
prices were checked on this date. Reservations deliberately do not depend on
achieving cache hits. No deployment, provider billing limit, broker order, capital
allocation or risk-setting mutation has been performed during this implementation.
