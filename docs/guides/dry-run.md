# Dry-Run Mode

[← Back to Guides](../index.md) · [Integrations](integrations.md)

Test migrations before execution using analysis or SAVEPOINT-based testing.

---

## Quick Start

```bash
# Analyze without executing
confiture migrate up --dry-run

# Execute in SAVEPOINT (guaranteed rollback)
confiture migrate up --dry-run-execute
```

---

## Three Modes

| Mode | Flag | Effect |
|------|------|--------|
| **Analyze** | `migrate up --dry-run` | Static analysis; no DB connection needed |
| **SAVEPOINT test** | `migrate up --dry-run-execute` | Executes in a SAVEPOINT against the live DB, then rolls back |
| **Preflight against a copy** | `migrate preflight --against <preflight-db>` | Runs every pending migration end-to-end on a parallel database, with structural diff |

For pre-deploy CI gates, `migrate preflight --against` is the strongest check. Use the others for quick local feedback.

---

## Analysis Mode

See what migrations will do before applying:

```bash
confiture migrate up --dry-run
```

**Output**:
```
Analyzing migrations without execution...

Migration Analysis Summary
================================================================================
Migrations to apply: 2

  001: create_initial_schema
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%
  002: add_user_table
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%

All migrations appear safe to execute
================================================================================
```

### Target Specific Version

```bash
confiture migrate up --dry-run --target 005_add_indexes
```

### Rollback Analysis

```bash
confiture migrate down --dry-run --steps 3
```

---

## Need a structural diff?

`migrate up --dry-run` and `--dry-run-execute` answer *"would this run?"*
They print row-count / time / disk estimates and verify the SQL executes
inside a SAVEPOINT — but they don't show **what would change** in
schema terms ("this would add column `users.bio TEXT NULL`, drop index
`idx_legacy_users_email` …").

For that, use `migrate preflight --against <preflight-db>` (covered in
[Preflight against a parallel database](#preflight-against-a-parallel-database)
below). Preflight replays every pending migration on a parallel database,
then emits a structural diff against `db/schema/` — the human-readable
"what's about to change" output that lets you pull the trigger on a prod
apply with confidence.

**Quick decision**:

| You want to … | Use |
|---|---|
| Verify the SQL parses + executes inside a transaction | `migrate up --dry-run-execute` |
| See row-count / time / disk estimates | `migrate up --dry-run` |
| See "this would add table X, drop column Y" | `migrate preflight --against <preflight-db>` |
| Gate a CI pipeline on schema drift | `migrate preflight --against` (exit 7 on drift) |

---

## SAVEPOINT Testing

Execute migrations with guaranteed rollback:

```bash
confiture migrate up --dry-run-execute
```

**How it works**:
```sql
BEGIN;
  SAVEPOINT pre_migration;
    -- Execute migration
  ROLLBACK TO pre_migration;
COMMIT;
```

**Advantages**:
- Catches syntax errors
- Shows real execution metrics
- No permanent changes
- Safe to run on production

**Limitations**:
- `CREATE INDEX CONCURRENTLY` can't run in transactions
- `AUTOCOMMIT` operations will fail

---

## Output Formats

### JSON for CI/CD

```bash
confiture migrate up --dry-run --format json --output report.json
```

```json
{
  "migration_id": "dry_run_local",
  "mode": "analysis",
  "migrations": [
    {
      "version": "001",
      "name": "create_initial_schema",
      "estimated_duration_ms": 500
    }
  ],
  "summary": {
    "unsafe_count": 0,
    "has_unsafe_statements": false
  }
}
```

### CI/CD Integration

```bash
#!/bin/bash
confiture migrate up --dry-run --format json --output analysis.json

unsafe=$(jq '.summary.unsafe_count' analysis.json)
if [ "$unsafe" -gt 0 ]; then
  echo "Unsafe migrations detected"
  exit 1
fi
```

---

## Preflight against a parallel database

`migrate preflight --against <url>` is the strongest dry-run mode confiture ships. It:

1. Reads the live tracking table on `<url>` to determine which migrations are already applied there.
2. Replays every pending `up.sql` (and `down.sql`, if `--include-down`) end-to-end on that database.
3. Diffs the resulting schema against the source-of-truth DDL in `db/schema/`.
4. Reports structural drift, transaction safety, and reversibility — exits non-zero if anything fails.

The intended pattern: provision a throwaway database (RDS snapshot restore, `pg_dump | pg_restore` to a scratch DB, a Neon branch), point `--against` at it, and gate your deploy pipeline on the exit code.

### What does the operator see?

```text
$ confiture migrate preflight --against postgresql://localhost/myapp_preflight

▸ Connecting to preflight database … ok
▸ Reading tracking table from preflight DB … 12 migrations applied
▸ Discovering pending migrations from db/migrations/ … 2 pending

  ► 20260520143015_add_user_bio.up.sql      transactional   reversible   no checksum drift
  ► 20260520151200_add_orders_index.up.sql  non-transactional ⚠           reversible   no checksum drift

▸ Replaying pending migrations on preflight DB …
  ✓ 20260520143015_add_user_bio                 applied in 24 ms
  ✓ 20260520151200_add_orders_index             applied in 1,820 ms (CREATE INDEX CONCURRENTLY)

▸ Comparing resulting schema vs. db/schema/ …

  Structural diff — preflight DB vs source DDL:
    + public.users.bio TEXT NULL                  (new in preflight, matches db/schema/10_tables/users.sql)
    + public.orders.idx_orders_customer_id        (new in preflight, matches db/schema/10_tables/orders.sql)

  ✓ No drift — preflight matches db/schema/

▸ Summary
    Pending:        2
    Applied OK:     2
    Failed:         0
    Drift items:    0
    Non-tx warns:   1 (orders index — confirmed CONCURRENTLY)

✓ Preflight passed. Safe to deploy.
exit 0
```

When something does go wrong, the structural-diff section is where the signal lives. Typical failure modes:

```text
✗ Drift — preflight differs from db/schema/

  - public.users.email VARCHAR(255) NOT NULL    (preflight has this; db/schema/ does not)

  Hint: db/schema/10_tables/users.sql declares 'email TEXT NOT NULL', but the
  migration 20260520143015_change_email_type.up.sql leaves the column as VARCHAR(255).
  Either:
    • Update db/schema/10_tables/users.sql to match the migration outcome, or
    • Add ALTER TABLE public.users ALTER COLUMN email TYPE TEXT; to the migration.

exit 7  (drift detected)
```

The exit code is **semantic** — wire it to your CI gate:

| Exit | Meaning |
|---|---|
| 0 | Preflight passed |
| 2 | Configuration error (bad YAML, unreachable preflight URL) |
| 3 | SQL execution failure during replay |
| 6 | Lock contention (another preflight is running) |
| 7 | Structural drift between preflight DB and `db/schema/` |

### Capturing the report for review

```bash
confiture migrate preflight --against "$PREFLIGHT_URL" \
  --format json --output preflight-report.json
```

`preflight-report.json` is the same data the human transcript is rendered from. It is the canonical artifact to attach to a deploy PR.

---

## Python API

```python
from confiture.core.dry_run import DryRunExecutor

executor = DryRunExecutor()
result = executor.run(conn, migration)

if result.success:
    print(f"Time: {result.execution_time_ms}ms")
    print(f"Rows: {result.rows_affected}")
    print(f"Locked tables: {result.locked_tables}")
else:
    for warning in result.warnings:
        print(f"Warning: {warning}")
```

---

## Best Practices

1. **Always dry-run before production**
2. **Use `--dry-run-execute`** in staging for realistic metrics
3. **Save reports** for audit trails
4. **Automate in CI/CD** to catch issues early
5. **Analyze rollbacks** before emergency rollbacks

---

## Troubleshooting

### "Cannot use both --dry-run and --dry-run-execute"

Choose one mode - they're mutually exclusive.

### "Cannot use --dry-run with --force"

Dry-run is for safety checks; `--force` skips checks. They contradict.

### Estimates seem wrong

Estimates are conservative approximations. Use `--dry-run-execute` for real metrics.

---

## See Also

- [CLI Reference](../reference/cli.md)
- [Transaction & SAVEPOINT Contract](../reference/transaction-contract.md) — the
  rules a migration body must follow for `--dry-run-execute` and
  `preflight --against` to roll back cleanly
- [Incremental Migrations](./02-incremental-migrations.md)
