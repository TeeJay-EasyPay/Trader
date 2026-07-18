# Render Deployment Evidence

Date: 2026-07-18

## Repository Evidence

Implemented files:

- `render.yaml`
- `src/ai_trader/config.py`
- `src/ai_trader/api.py`
- `src/ai_trader/cli.py`
- `src/ai_trader/sprint6.py`

Local validation:

- `python -m py_compile src\ai_trader\config.py src\ai_trader\api.py src\ai_trader\cli.py src\ai_trader\sprint6.py` passed.
- Focused operations/Sprint 6 tests passed: 23/23.
- Full Python test suite passed: 137/137.
- `npx expo-doctor` passed: 17/17.
- `https://trader-no0f.onrender.com/healthz` returned HTTP 200 at 2026-07-18 with payload status `ok`.
- Supabase CLI available locally: `2.101.0`.
- Current local branch: `master`.
- Current pre-commit local HEAD: `feda92364345e04f29840ea67d9310edf0abdefe`.

## Hosted Evidence

Hosted deployment evidence is not complete from this environment.

Missing evidence:

- Render CLI is not available in this environment;
- Render deployment ID;
- deployed commit hash confirmed by Render;
- live worker heartbeat from Render worker service;
- live cron job record from Render cron service;
- `/operations-health` proving Postgres is active;
- `/scheduler-status` proving scheduled jobs are visible;
- phone-closed verification window.

## External Activation Required

The Founder or operator must:

1. Add `DATABASE_URL` or `SUPABASE_DATABASE_URL` in Render.
2. Confirm `AI_TRADER_DATABASE_BACKEND=postgres`.
3. Deploy the updated `render.yaml`.
4. Confirm the API starts without hosted SQLite fail-close errors.
5. Confirm the worker service starts and writes `WORKER_HEARTBEATS`.
6. Wait for at least one cron schedule and confirm `SCHEDULED_JOB_RUNS`.

Do not mark hosted autonomy complete until those records exist.
