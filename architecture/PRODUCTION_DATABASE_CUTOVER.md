# Production Database Cutover

## Target state

Supabase Postgres is the sole hosted runtime database for API, worker and scheduled jobs. SQLite is local/test only. The hosted service must define:

```text
AI_TRADER_DATABASE_BACKEND=postgres
AI_TRADER_REQUIRE_POSTGRES_IN_HOSTED=true
DATABASE_URL=<Supabase session-pooler URI>
```

`SUPABASE_DATABASE_URL` is accepted as a transitional alias, but `DATABASE_URL` is the preferred production name. Password special characters must be percent-encoded in the URI.

## Startup behaviour

Hosted startup fails instead of opening SQLite when:

- Postgres is not selected;
- neither Postgres URL variable is present;
- the Postgres driver is unavailable;
- the database cannot be reached;
- schema initialization fails.

This is intentional. A temporarily unavailable system is safer than API and worker processes writing different local histories.

## Historical cutover command

After the current Postgres schemas have initialized, migrate an existing SQLite history with:

```powershell
python -m ai_trader migrate-sqlite-to-postgres --source data/audit.sqlite3
```

The command:

1. fingerprints the source database;
2. records the run in `PRODUCTION_DATABASE_MIGRATIONS`;
3. inventories all non-system SQLite tables;
4. copies common columns into initialized Postgres tables;
5. uses `ON CONFLICT DO NOTHING`, preserving newer target truth;
6. fails if a source table has no initialized target table;
7. records examined tables and read/inserted row counts;
8. returns `already_completed` when the same source fingerprint is retried.

The command does not delete or modify the source SQLite file. A successful run should be followed by row-count and sample-record reconciliation before the source is archived.

## Schema ownership

Domain repositories continue to own additive schema initialization. They all connect through the same provider. This avoids a second ORM model becoming another competing source, but it is a transitional constraint: a future migration framework should version DDL in one ordered ledger.

## Cutover procedure

1. Back up the current Supabase database and local SQLite file.
2. Stop the worker or disable autonomous entries while migrating.
3. Deploy the Postgres-only application revision.
4. Confirm API startup and schema initialization.
5. Run the migration command from a trusted environment with the session-pooler URL.
6. Review `PRODUCTION_DATABASE_MIGRATIONS` for `completed`.
7. Compare critical counts: recommendations, broker history, audit, reports, lifecycle, experience and learning.
8. Start the worker.
9. Confirm both API and worker report the same backend and revision.
10. Observe one research, broker-poll and learning cycle.

## Rollback

Rollback means stopping worker/API, restoring the Supabase backup and redeploying the prior revision. It does not mean enabling hosted SQLite. New Postgres writes after cutover must be reconciled before any database restore.

## Remaining limitations

- The DB compatibility layer has complete local regression coverage but has not been exercised by this task against the Founderâ€™s hosted Supabase instance.
- Historical data can be migrated only if the old SQLite file still exists and is accessible.
- The application currently initializes many schemas at startup rather than through one numbered migration tool.
- SQL types retain compatibility-oriented `TEXT`, `REAL` and integer booleans. They are functional but not a fully normalized institutional schema.
