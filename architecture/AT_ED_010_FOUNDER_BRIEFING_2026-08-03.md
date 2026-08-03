# AT-ED-010 Founder Briefing — UI Data Freshness and Evidence Alignment

**2026-08-03. Deployed to production, including a mobile app update.**

## The headline

The "Not available" / stale-data problem you've been reporting for weeks was **not the backend
failing to produce data**. It was the mobile app silently showing you old cached information
whenever a live refresh failed for any reason — with no way to tell the difference. That's fixed
now, deployed as a new APK build.

While verifying the fix in production, I also found and fixed two real, separate backend bugs —
one I introduced myself in this same round of work, one much older. Both are explained below.

## What changed in the app itself

The app now clearly shows one of six states at all times, visible in the header on every screen:
**Live**, **Refreshing**, **Cached**, **Backend Snapshot Stale**, **Refresh Failed**, or **No
Data Available**. When you're looking at cached data, you'll see exactly when it was captured,
how old it is, and why the live refresh failed — with a retry button. Before, a failed refresh
looked identical to a successful one.

If a refresh fails, the app now automatically retries once before falling back to cache. And a
new background refresh every 2 minutes means the app recovers to Live on its own the next time a
refresh succeeds — you shouldn't need to manually pull-to-refresh to get unstuck from a cached
state.

**New APK to install**: https://expo.dev/artifacts/eas/zIbnM0cNh-w0IN9Yy7NKK3Z8F1ME2qnUEq4WCOFtDE4.apk

## The two backend bugs found during verification

**Bug 1 (my own mistake, caught and fixed within the hour).** A code comment I approved earlier
in this same session accidentally contained a semicolon inside a sentence. A pre-existing (not
new) piece of schema-setup code splits its SQL script on semicolons without understanding
comments — so that one semicolon broke the comment in half, and the second half got executed as
if it were a real command, failing every single time. This was actively breaking a chunk of
backend functionality (though not anything trading-related) until I found and fixed it by
directly inspecting the production error message.

**Bug 2 (a genuine, much older bug, unrelated to anything done in this session).** Two backend
status pages (`/status` and `/phase5-status`) have been hanging for about a minute instead of
responding, for reasons that turned out to have nothing to do with slow database queries. Every
time your app has been redeployed — dozens of times over the life of this project — a permanent
record of that worker process was kept, by design, as history. A separate piece of code was
treating every one of those old, dead worker records as if it were currently having a problem,
and writing a new "incident" to the database for each one, every single time those two pages were
loaded. That's now fixed to only ever look at the current worker.

Neither of these bugs touched trading logic, risk controls, or your Kraken/Alpaca connections in
any way — confirmed directly: your Kraken £100 allocation is untouched (still fully available,
zero open positions), and the reconciliation hold is exactly as you left it.

## What's still not fully resolved

One more backend page (`/brokers`) is still slow — it improved from reliably timing out to just
barely completing, but not fast. **This one does not affect the mobile app** — I checked, and the
app only ever calls one endpoint (`/founder-evidence`), which has been fast and reliable
throughout this entire investigation (consistently 3-4 seconds). This remaining slowness is
documented as a known follow-up, not something urgent.

## Tests and verification

- Full backend test suite: 310 passed, 0 failed, run clean multiple times across every change.
- New tests specifically proving both bugs are fixed and won't silently regress.
- Mobile: 43 tests passed (19 new, 24 pre-existing unchanged), plus the project's standard
  `expo-doctor` check (17/17) and a direct compile check against the real build toolchain.
- No real Kraken order was submitted at any point, by any test, or during any part of this
  investigation.

## Status

All fixes are deployed to production and confirmed working via direct testing against the live
API. The mobile APK is built and ready for you to install. Nothing was pushed without passing
tests first, and every fix is documented with the evidence behind it.
