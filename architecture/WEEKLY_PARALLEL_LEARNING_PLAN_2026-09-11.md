# Weekly parallel learning and meaningful summaries

Status: plan only. Requested 11 September 2026; these refinements are not yet implemented.

## Agreed outcome

Continuously test useful hypotheses without confusing activity with improvement.
Run at most ten active hypotheses across Alpaca and Kraken combined. Each has
separate baseline and candidate virtual books. Ten is a ceiling, not a target.
No new broker orders, live activation, altered protective exits or backup work.

## 1. Parallel experiments and fair opportunity coverage

- Replace the one-active-per-broker restriction with a global hard cap of ten.
  Acquire slots transactionally so overlapping workers cannot exceed the cap.
- Prioritise distinct, evidence-supported hypotheses; queue overflow and deduplicate
  equivalent proposals. Explain the problem, intended benefit and applicable market.
- Capture each suitable timestamped opportunity once and fan it out to all relevant
  experiments, preserving independent portfolio balances and eligibility decisions.
- Include supported rejected/skipped opportunities; never override unrelated risk,
  permission, data or cost safeguards. Missing reasons stay unknown.
- Avoid dividing twenty observations into ten nearly empty tests: separate the
  shared unique-opportunity budget from bounded per-experiment simulation work.
  Initially retain twenty unique opportunities/day and cap fan-out at ten per
  opportunity (at most 200 paired evaluations/day), subject to worker/storage caps.
- Reuse candles and compact decision inputs. Measure before raising any data budget.

## 2. Seven-day review cycles

- All hypotheses receive a first review seven days after actual start, then weekly
  if continued. Queued hypotheses have no invented start date.
- Persist each review: interval, cumulative and new observations, completed trades,
  skips, unresolved positions, after-estimated-cost results, uncertainty and findings.
- Outcomes: continue with reason and next review date; stop with reason; or recommend
  further action when evidence gates pass. A weekly deadline does not imply success.
- Continue without resetting evidence or forcing open trades to close. Freeze rule
  versions; substantive rule/engine changes create a linked new experiment.
- Use fixed weekly statistical checkpoints and a documented repeated-testing policy;
  do not repeatedly check until a favourable result appears. Account for correlated
  opportunities and multiple hypotheses. Existing safety/evidence gates are not
  silently weakened to fit a one-week window.
- Identify stalled or redundant experiments and release slots when stopped. Do not
  extend indefinitely without a stated evidence need and a visible review decision.

## 3. Bounded grouped AI review

- Ordinary Render code performs simulation, accounting and evidence checks.
- Batch only due/meaningfully changed experiment summaries into a compact review;
  do not send full trade histories or make an AI call per shadow trade.
- Keep the existing experiment-wide AI limit of one call/day initially, shared by
  proposals and grouped reviews, with explicit token limits and persisted usage.
  Due reviews take priority; defer proposal generation when the budget is used.
- Validate returned identifiers, versions and permitted recommendations. AI cannot
  change calculated results, bypass gates or activate trading. On timeout/budget
  exhaustion retain the numerical report and show interpretation pending.
- Measure worker time, request/token spend, unique inputs, fan-out, database growth
  and egress. Bound concurrency, retries, result payloads and total storage.

## 4. Experiments card and history

- Main card shows running tests only. Separate buttons expose Queued, Previous tests
  and requests needing attention; history is retained, not deleted.
- Active tests show actual start, current cycle, next weekly review and evidence
  progress. Ended tests show actual end and reason, not an upcoming target date.
- Link predecessor/successor tests and explain engineering restarts versus rejected
  hypotheses. Recover end timestamps from recorded events where available.
- Show completed simulated trades separately from skips and pending observations.

## 5. Make the Learning summary useful while preserving its appearance

Verified current wiring: mobile/screens/Learning.js takes the newest POST_TRADE_REVIEWS
lesson as the period headline. learning_screen.py supplies completed broker outcomes,
reviews, legacy SHADOW_TRADES candidates, lesson proposals and backtest counts.
It does not aggregate the paired RULE_EXPERIMENTS results. The Next test and Decision
rows are hard-coded prose. Review date, trade close date and candidate creation date
are different clocks; counts do not represent unique new lessons.

- Preserve the visual design and daily/weekly/monthly navigation.
- Separate **From executed trades** (Kraken live / Alpaca paper, with known mode and
  cost caveats), **From experiments** (paired evidence and weekly findings), and
  **What happens next** (named test, next review or approval request).
- Show concise supported findings, not merely counts. Link every finding to its
  trade/review or experiment/version/review evidence; distinguish proposed lessons
  from tested findings and demonstrated improvement.
- Replace generic Next test with an exact linked hypothesis and its status, or
  explicitly say no linked experiment. Never infer linkage from similar wording.
- Replace the generic Decision with actual period actions: continued/stopped tests,
  pending approval, approved configuration, or no change. Approval is not activation.
- Keep counts in supporting detail; distinguish newly closed trades from reviews
  written today about older trades. Separate gross/known-net/estimated-net results.
- Lead with **What was learnt**, replacing the generic Decision row. Write in
  plain human language about outcomes, combining lessons from executed trades and
  hypothesis evaluations completed in the selected period. Label their sources.
  Interim experiment observations must not masquerade as completed findings.
- Daily answers "What did I learn today?"; weekly and monthly synthesise all
  relevant recorded findings in the selected week/month, not just the latest
  review or a concatenation of daily messages. Preserve date navigation for last
  week/month and label in-progress periods. Deduplicate recurring lessons and
  explain conflicting evidence, superseded conclusions and uncertainty.
- Keep **Evidence** and an exact linked **Next test** as supporting rows. Include
  **How this affects future decisions** in the narrative: distinguish a proposed
  test, approved-but-inactive rule, currently applied rule, and no justified change.
  Never claim "I will apply this" merely because a review suggested it. If no
  supported new lesson exists, say so plainly rather than manufacturing insight.
- Persist versioned learning findings with source trade/review/experiment IDs,
  evidence period, recorded time, confidence/limitations, proposed action, approval
  and activation state, and supersession links. Record late historical discoveries
  as learned now about earlier trades rather than silently rewriting prior claims.
- Feed relevant findings back into subsequent decision context within a bounded
  retrieval budget, and log which finding/rule versions were supplied and enforced.
  A saved lesson or retrieved passage alone is not proof of application; inspect
  later decision traces. Unsupported behaviour still needs code and live activation
  still requires its existing authorisation gates.
- Generate/cache period narratives from persisted evidence and review outputs;
  opening or changing periods must not trigger extra AI calls. Any AI synthesis
  shares the bounded grouped-review budget and must cite only supplied finding IDs.
- Remove stale static claims elsewhere on Learning that contradict real experiment
  data. Use bounded cached aggregates and paginated detail, with no AI call on open.

## 6. Shared mobile navigation

- Replace the five top-level navigation buttons with a hamburger menu at the top
  right of the shared application header, available on every screen. Preserve the
  current screen's title so location remains clear when the menu is closed.
- Put the existing connection/freshness badge directly beneath the hamburger icon.
  Preserve stale, offline and loading states and refresh/evidence timestamps.
  Label it as application/backend status; a healthy connection must not imply
  that live-money trading is enabled or that every broker is healthy.
- Menu entries retain Executive Briefing, Portfolio, Standup, Run a Cycle and
  Learning, plus existing enabled destinations such as Notifications. Preserve
  existing screen behaviour and navigation links; do not alter Standup conversation
  semantics or enable paused/unreleased workflows just to populate the menu.
- Treat Run a Cycle according to its existing behaviour: opening navigation must
  never itself execute a trading/research cycle or other side effect.
- Highlight the current destination, close after selection, and support outside
  tap, Android Back, screen-reader labels, focus handling and adequate touch targets.
  Respect device safe areas, small screens, long stale-status labels and scrolling.
- Verify all entry points, experiment/report deep links and returning from detail
  screens. Preserve the Learning summary's existing visual design.

## 7. Rollout and acceptance

1. Implement versioned weekly-review records, scheduler and budgeted fan-out first.
2. Add grouped review validation and source-linked summary projections.
3. Update experiment and learning-summary UI, shared hamburger navigation, history
   navigation and approval/notification links.
4. Migrate current active tests to a documented seven-day review schedule without
   rewriting prior observations. Preserve original dates and audit the schedule change.
5. Test global concurrency, both brokers, shared-input isolation, budget exhaustion,
   unknown evidence, due reviews, continuation, early stops, provenance and old UI data.
6. Commit and deploy scoped changes, publish Android, verify API and worker versions,
   then inspect production counts and dates without paid test calls or broker orders.

Success is useful comparisons and evidence-backed findings per week within cost
limits, not filling ten slots or promising profitability. Increasing the ceiling
beyond ten requires a later decision informed by throughput and resource measurements.
