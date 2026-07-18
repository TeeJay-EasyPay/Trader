# Always-On Testing Report

## Focused Tests Added

`tests/test_always_on_operations.py`

Coverage:

- scheduled jobs are idempotent;
- duplicate job claims are skipped;
- completed job counts persist;
- fresh worker heartbeat is healthy;
- stale worker heartbeat is attention-needed;
- research funnel stores no-trade reasons;
- shadow trade outcomes remain separate from broker orders;
- `/operations-health` is exposed;
- scheduler status lists supported jobs;
- Alpaca inactivity reports an operational fault when no research exists.

## Verification Run

Command:

```text
python -m unittest tests.test_always_on_operations
```

Result:

```text
Ran 9 tests
OK
```

## Not Yet Proven In This Session

- Live Render worker heartbeat after deployment.
- Cron job execution while mobile app is closed.
- Alpaca fresh market-data retrieval from Render.
- A full fresh Alpaca cycle to either paper order or persisted no-trade reason on the hosted service.

