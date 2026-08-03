# AT-ED-010 Deployment Report

## Backend

Pushed to `origin/master` in 4 stages as issues were found and fixed:

| Push | Commit | Confirmed deployed |
|---|---|---|
| Investigation doc | `96e4cfd7` | Yes |
| Backend perf + mobile fixes | `2b50a9cb`, `23c0733c` | Confirmed after ~unusual delay (see note below) |
| Schema-comment hotfix | `2027c4b5` | Confirmed via `/operations-health` returning healthy |
| Real root-cause fix | `4a1c7ca0` | Confirmed via `/phase5-status` timing dropping from ~60s to ~12s |
| Diagnostic cleanup + docs | `eef7994a`, `01b2a2fc` | Confirmed via `deployment_commit` field |

Both Render services ("Trader" API, "Background AI Trader" worker) auto-deploy from `master`.
Worker deployment was confirmed via its self-reported `deployment_commit` field advancing to
match each pushed commit hash, cross-checked against a new `worker_id` on each restart (proof of
a genuine process restart, not a stale cached value).

**Note on deploy timing**: the `2b50a9cb`/`23c0733c` push took roughly two hours to reflect in
the deployment_commit field — anomalously long compared to every other deploy in this session
(typically 1-10 minutes). No Render platform outage was found (status.render.com showed all
systems operational throughout). Root cause was not conclusively identified; it's possible the
long wait was partly measurement artifact, since `/activity/status` — the endpoint used for that
particular check — was separately proven to serve a periodically-cached snapshot rather than a
live value (this is exactly the class of problem AT-ED-010 addresses on the mobile side; the
backend endpoint itself was not in scope to fix here). Every deploy after that one used
`/operations-health`'s live error state or `/phase5-status`'s actual response time as the
verification signal instead, both of which are not subject to this caching behavior, and
resolved in 1-15 minutes each.

## Mobile

EAS cloud build triggered via `eas-cli build --platform android --profile hosted-preview`.

First attempt failed: the build archiver could not scan a locked `.pytest_cache` directory at the
repository root (a pre-existing, unrelated Windows file-permission issue present throughout this
session's local test runs, not something this work introduced). Worked around by adding a
repository-root `.easignore` excluding `.pytest_cache/` from the build archive — a build-tooling
configuration change only, no application code affected. Retried successfully.

**Build result**: https://expo.dev/artifacts/eas/zIbnM0cNh-w0IN9Yy7NKK3Z8F1ME2qnUEq4WCOFtDE4.apk

Build log: https://expo.dev/accounts/nexuspay/projects/ai-trader-mobile/builds/6d2a66e7-e3b5-40ae-9e14-d08aa86a8222

## Confirmed both services running the latest verified commit

`deployment_commit` on the worker matched `4a1c7ca0` (the real root-cause fix) at time of the
production verification round documented separately. The final two commits (`eef7994a`,
`01b2a2fc`) are documentation/cleanup only with no behavioral change, so re-confirming their
exact deploy timestamp was not treated as blocking.

Render service configuration was not modified at any point.
