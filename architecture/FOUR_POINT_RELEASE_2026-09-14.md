# Four-point release and cost evidence — 14 September 2026

## Scope

1. Reconcile earlier work: preserve the original working tree; integrate the tested fail-closed protected-record lookup safeguard. Retention approval UI, maintenance scheduling, archive tools and their reports remain uncommitted in the original workspace and deliberately excluded. They are not enabled, deleted, or claimed deployed. Existing runtime before release: API and worker e4d7d2bd; master 55c428af adds documentation only.
2. Reduce unnecessary transfers and attribute OpenAI activity: exact conditional candle reads, SQL ledger totals, compact JSON prompts, daily bounded usage aggregates. No protective-exit/reconciliation frequency, trading thresholds, model choice or live permission changes.
3. Proactive learning: shared durable chat/voice research requests feed the existing evidence-gated daily batch, not an extra model call. Model proposals carry a sustainable after-cost improvement objective, validated request links and author/trigger provenance. Unsupported or unselected requests receive an explicit explanation. Request receipts are not running experiments. Queue appears under Experiments → Queued; actual experiments link to their reports. Existing five-per-broker limits, daily reservation, simulation engine and weekly substantive review remain; no forced one-day verdicts or resetting accumulated evidence.
4. Trader-only conversational voice: native WebRTC, interruptible audio, transcript, server grounding and safe research-request tool. Five-minute sessions, one-minute inactivity limit, explicit start/end/mute, stop on background/navigation, and conservative $10/month voice allowance. Group Standup/Claude unchanged. Native APK 1.0.4/version 5 required; old installed APK cannot gain WebRTC through OTA alone.

## Egress: evidence versus inference

The supplied quiet-day screenshots show roughly 400–500 MB/day. Earlier billing tooltip identifies shared pooler traffic; those are database results leaving Supabase, not a count of executed trades. No development does not mean no reads: assessment, refresh, reconciliation and worker jobs continue even when no order is placed.

Available counters over approximately 51 hours (reset 11 September 19:33 UTC, captured 13 September 22:31 UTC) included:

| Repeated read | Calls | Returned rows |
| --- | ---: | ---: |
| Candle history | 2,916 | 349,920 |
| Schema columns | 13,109 | 203,989 |
| Timezone catalogue | 216 | 258,336 |
| Kraken capital ledger | 721 | 72,163 |
| Owned logical trades | 721 | 36,318 |

These are cumulative query counters, **not exact billed bytes or precise daily attribution**. Trade count therefore cannot explain total bandwidth by itself. Timezone caller is not established; do not attribute it to Trader without evidence.

Changes preserve inputs:

- Candle history: Postgres recomputes a digest of the selected rows on every read. An unchanged history returns a digest and null instead of the entire JSON. Changed/corrected/deleted candles invalidate immediately. Bounded local cache is only a transfer optimisation, not a stale-price TTL. Production read-only sample: 120 FORTH rows matched exactly; former JSON payload 15,567 bytes. This is not a claim of total daily savings.
- Kraken totals: SUM/conditional SUM in SQL instead of downloading all ledger and closed logical rows to sum in Python. Detailed reconciled/open-trade records remain available. Existing reconciliation tests preserve output semantics.
- OpenAI: compact JSON preserves information; counters show model/category/calls/tokens going forward. Existing forecast reuse and longer crypto research intervals were already deployed and are not counted as new savings. Tokens are not dollars; not all account traffic originates in this app.

Follow-up measurement should compare full-day pooler egress after release with the quiet-day baseline, allowing dashboard reporting delay. Use query deltas rather than historical totals. No measured percentage reduction is available at release time. Next priorities if traffic remains high: identify timezone-catalogue caller; consolidate schema discovery across short-lived workers; profile repeated dashboard/reconciliation payloads before changing cadence. Keep fresh broker safety checks and detailed drill-down; do not reduce evidence to meet an arbitrary byte target.

## Credit visibility

Trader mode shows tracked daily calls/input/output tokens, existing conversation reply estimates, and conservative voice allowance accounting refreshed during a call. Those figures are provided in Trader's evidence context too. OpenAI's documented organization usage/cost APIs are different from a prepaid balance; no supported prepaid balance endpoint is configured here. The display explicitly says unavailable and links to the billing dashboard, rather than fabricating zero or treating the $10 allowance as purchased credits. No admin key is requested or placed in the client. Voice accounting deliberately overestimates mixed/cached tokens and includes transcription headroom; it is a safety allowance, not an invoice.

## Verification

- Funded provider smoke test completed a synthetic text-to-audio response, with no microphone/broker data. Fixed final-usage/end race and verified the allowance unlocks after accounting; final conservative sample $0.072944, not actual provider charge.
- 105 chat/learning/forecast/cost/voice-budget tests passed; 19 cache/usage/reconciliation tests passed. Further release checks and deployment IDs recorded below when verified.
- Earlier local maintenance work has not been silently rolled into this release. The protected-record safeguard is the only integrated retention-related change and prevents deletion on lookup failure; it does not schedule or execute retention.

## Publication and final checks

- Runtime release: f0dc169375578e2242c949ad3a4d20d190b174db (includes 12fed936 and a4ade42e). Hosted API and latest worker heartbeat both verified on this revision at 00:45 UTC on 14 September.
- Android APK 1.0.4/version 5 built successfully: https://expo.dev/artifacts/eas/NY7liw0PitZnKeov0OCmx69Cb0D9pawuMvfNICUNcPY.apk . Build ID a61a651f-a9cf-4f3e-9d9d-c61138fbcd15. Built from checkpoint plus then-current uncommitted UI edits; the final reviewed JavaScript is published as hosted-preview runtime 1.0.4 update group ba1ff1b7-2445-4b4a-b6cf-18f617326af6. Install APK, allow update download and reopen if needed for final research queue UI.
- Deployed voice end-to-end smoke test completed with actual backend grounding, synthetic text and audio reply, no microphone or broker orders. Returned 6,019 input / 46 output tokens; backend accounted $0.245552 conservatively including transcription headroom and released the session. This is not a billed-dollar figure. It is visible in the production voice allowance.
- API `/model-usage` and `/trader-voice/budget` returned valid authenticated responses. Credit balance remains explicitly unavailable, not zero.
- Three additional production candle samples (KAS, JUP, JTO) matched 120 rows each; old JSON 16,831 / 16,631 / 16,601 bytes respectively. Daily savings remain unmeasured.
- Additional assurance/voice-action/API tests: 96 passed plus one import-order failure in a test; fixed explicit unittest.mock import and reran all 21 API tests successfully, including 19 subtests. Retention/experiment set: 45 passed. Final usage-context/batch set: 11 passed. These selections overlap; counts are not a unique-test total.
- Main laptop checkout fast-forwarded with prior changes preserved. One API route conflict was resolved by retaining both the released voice/usage routes and the uncommitted maintenance route. Four local maintenance files remain modified; their untracked supporting files remain. Recoverable autostash 9534f882 retained as an additional safety copy. No paused cleanup was run.
- Phone microphone/audio routing still requires the owner's installation/device check; the successful native build and hosted transport check are not a claim that a physical phone was tested here.
