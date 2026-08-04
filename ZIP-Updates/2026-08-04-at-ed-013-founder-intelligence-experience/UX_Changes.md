# UX Changes — AT-ED-013

## Dashboard

**Before:** `CommandSummaryCard` — a status pill, a joined 2-3 sentence summary, and a flat list
of metrics (Market, Portfolio, Brokers, Research, Learning).

**After:** `CIOBriefingCard` — opens with a time-of-day CIO greeting ("Good morning Tarik."),
then: Executive Investment Summary (same underlying sentences, now via `cioExecutiveSummary`),
Overnight Activity (new — a real sentence naming what happened since the last visit, or honestly
reporting a quiet period), Market Outlook (new — the same market-health fields as a paragraph),
Portfolio Health, Brokers, Founder Decisions Required (new — count of outstanding
recommendations), Confidence (new — a real average across current recommendations, honestly
"not enough data" when there's nothing to average), and Portfolio Trajectory (new — the honest
forecasting-gap explanation, not a number).

## Activity

**Before:** Notifications card, then straight into the status/period-filter summary card and
grouped timeline.

**After:** A new "Trading Narrative" card sits between Notifications and the status summary — a
plain-English paragraph (what AI Trader did) followed by up to 10 recent trades, each showing
entry price, current price (or "Closed"), target exit, P&L, and confidence where a recommendation
links to the trade. Everything else on this screen is unchanged.

## Market

**Before:** Summary card led with a static, unchanging question: "What kind of market are we in,
what matters right now, and where is AI Trader focused?"

**After:** That question is replaced with a real paragraph built from the same market-health/
regime/crypto-health/upcoming-risks fields shown as metrics directly below it. The metrics
themselves, and every other section (Alpaca/Kraken Intelligence, Benchmark Traders, Themes,
Companies), are unchanged.

## Portfolio

**Before:** "Portfolio Value", "Cash Available", "Deployed Capital", "Today's P&L" shown as plain
metrics with no explicit Fact/Forecast framing.

**After:** Same four metrics, now labelled "(Fact)" to make explicit that they're observed, not
predicted. A new "Portfolio Projection (Forecast — 7/30/90 Day)" line sits directly beneath them,
honestly stating that no portfolio-value forecasting model exists yet rather than showing a
number. No other content or calculation on this screen changed.

## Learning

**Before:** Summary card led with a static question: "Is AI Trader learning, and what needs
Founder approval before behaviour changes?"

**After:** That question is replaced with a real narrative — how many closed trades were
reviewed and the most recent lesson, or an honest statement that there isn't enough evidence yet
— framed as a CIO quarterly performance review. The metrics below (Completed Trades Reviewed,
Strategies Evaluated, etc.) and every other section are unchanged. Separately, Ask AI Trader's
error-message fallback no longer echoes a raw exception string on non-timeout failures.

## App-wide: Visual Status Language

**Before:** `displayStateBadge()` returned a plain-text label ("Live", "Cached", "Refresh
Failed", …) with a colour tone.

**After:** Every such label is now prefixed with one of 🟢 (Live), 🔵 (Refreshing), 🟡 (Cached /
Backend Snapshot Stale), or 🔴 (Refresh Failed / No Data Available) — the same emoji everywhere
this badge is shown, derived directly from each state's existing colour tone so the mapping can
never drift out of sync.

## App-wide: No More Raw Error Text

**Before:** The app-header "refresh failed" banner and cached-data banner both interpolated the
raw error string from the network layer directly into the Founder-facing text — e.g. `"Live
refresh failed: Request failed: 500"` or `"...Request timed out after 18s: /founder-evidence"`.

**After:** Both now show one of two honest, plain-English reasons — "the backend took too long to
respond" or "AI Trader could not reach the backend" — with the raw HTTP status, path, and timeout
detail no longer reaching the screen.

## New Document

**`AI_TRADER_CONSTITUTION.md`** (repo root) — did not exist before this pass. A ~800-word,
Founder-facing statement of AI Trader's mission and the eleven principles it operates under,
explicitly cross-referencing rather than duplicating the existing engineering constitution.
