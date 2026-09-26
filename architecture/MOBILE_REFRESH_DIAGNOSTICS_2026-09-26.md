# Mobile cached-refresh diagnostic release

The user's Android app remained on September 25 16:07 cached data across Wi-Fi,
5G and VPN removal. The phone browser health check succeeded; authenticated
briefing requests from the development environment succeeded. Render application
logs showed no exception in the interval; request logs were unavailable. These
checks do not identify the phone's underlying refresh error or its installed build.

Changes: classify HTTP status before parsing error bodies; show fixed safe AUTH,
SERVER, REQUEST, RESPONSE, NETWORK, DATA or UNKNOWN messages. Applying a response
is explicitly distinguished from fetching it. No response body, token fragment or
stack trace is interpolated. Timeout remains separately named. Snapshot age is
computed from its timestamp rather than frozen server age, with a local foreground
clock and resume update; no additional network requests. Server stale flags remain
unchanged. No trading, risk, worker, database or voice changes.

Verification: 55 focused tests passed. 51 of 53 mobile lib/API test files passed;
mockupLayout and standupFloor encounter JSX-loading failures in Standup fixtures.
Android runtime 1.0.4 production export succeeded (676 modules). The existing API
credential was supplied from the local secret environment without printing it.

This is a diagnostic release and timestamp fix, not a verified fix for the phone's
underlying failure. Once received, the phone's next Retry should expose its failure
category if the problem persists. No new native APK is required.

Published successfully from source commit cb06e3cacf7230eb8a6daeebd8b5cafb51c12037:
- hosted-preview: f578fc21-23c0-4156-a837-42ea23048360
- preview: f68ca0a6-e1c4-489f-87d2-2146661e65b6

Both updates use Android runtime 1.0.4 and the same verified exported bundle.
Existing unrelated local files were not committed; EAS reports a dirty worktree.
Device receipt and next diagnostic outcome remain unverified. Render deployment
was intentionally skipped; no service restart or production database change.
