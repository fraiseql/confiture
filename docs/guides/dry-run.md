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
| **Preflight against a copy** | `migrate preflight --against <preflight-db>` | Replays every pending migration end-to-end on a parallel database inside SAVEPOINTs, then rolls back |

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

## "Will it run?" vs "what will change?"

`migrate up --dry-run`, `--dry-run-execute`, and `migrate preflight --against`
all answer *"will these migrations run?"* — they execute the SQL (statically
estimated, or for real inside a SAVEPOINT / replay) and report success, timing,
and safety. None of them emits a schema-level diff of what the migrations change.

For a **structural** comparison — *"this would add column `users.bio`, drop
index `idx_legacy_users_email`"* — diff two schema files with `migrate diff`:

```bash
confiture migrate diff old_schema.sql new_schema.sql
```

**Quick decision**:

| You want to … | Use |
|---|---|
| Verify the SQL parses + executes inside a transaction | `migrate up --dry-run-execute` |
| See row-count / time / disk estimates | `migrate up --dry-run` |
| Replay every pending migration end-to-end on a real DB copy | `migrate preflight --against <preflight-db>` |
| See a structural diff ("would add table X, drop column Y") | `migrate diff <old.sql> <new.sql>` |
| Gate CI on whether pending migrations replay cleanly | `migrate preflight --against` (exit 7 on replay failure) |

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

The `migration_id` is `dry_run_<config-stem>` — `dry_run_local` here is derived
from `local.yaml`.

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

1. Reads the live tracking table on `<url>` to determine which migrations are already applied there (or uses `--config` / `--env` / `--since` to pick the pending set).
2. Replays every pending migration end-to-end on that database, each inside a SAVEPOINT.
3. Rolls the replay back, leaving the preflight database in its original state — unless a non-transactional migration was run with `--allow-non-transactional`, which commits and consumes the DB.
4. Reports per-migration replay success/failure, plus transaction safety and reversibility — exits non-zero if any pending migration fails to replay.

The intended pattern: provision a throwaway database (RDS snapshot restore, `pg_dump | pg_restore` to a scratch DB, a Neon branch), point `--against` at it, and gate your deploy pipeline on the exit code.

### What does the operator see?

```text
$ confiture migrate preflight --against postgresql://localhost/myapp_preflight

▸ Connecting to preflight database … ok
▸ Reading tracking table from preflight DB … 12 migrations applied
▸ Discovering pending migrations from db/migrations/ … 2 pending

  ► 20260520143015_add_user_bio.up.sql      transactional       reversible
  ► 20260520151200_add_orders_index.up.sql  non-transactional ⚠  reversible

▸ Replaying pending migrations on preflight DB (inside SAVEPOINTs) …
  ✓ 20260520143015_add_user_bio                 replayed in 24 ms
  ⊘ 20260520151200_add_orders_index             skipped — non-transactional
        (CREATE INDEX CONCURRENTLY; re-run with --allow-non-transactional to replay it)

▸ Rolling back the SAVEPOINT — preflight DB left unchanged.

▸ Summary
    Pending:        2
    Replayed OK:    1
    Skipped:        1 (non-transactional)
    Failed:         0

✓ Preflight passed. Safe to deploy.
exit 0
```

When something goes wrong, a pending migration fails to replay. The failing
statement and its database error are the signal:

```text
✗ Replay failed — a pending migration errored on the preflight DB

  ► 20260520143015_change_email_type.up.sql
      PFLIGHT_REPLAY_FAILED: column "email" cannot be cast automatically
      to type integer
      (the SAVEPOINT was rolled back; the preflight DB is unchanged)

  Hint: fix the migration SQL and re-run preflight before deploying.

exit 7  (replay failed)
```

The exit code is **semantic** — wire it to your CI gate (codes as of 0.21.0, #151):

| Exit | Meaning |
|---|---|
| 0 | Preflight passed — no error-severity issues |
| 3 | Connection failure — unreachable `--against` URL or tracking DB (`CONFIG_006`) |
| 5 | Configuration error — bad YAML, or conflicting DSN sources (`CONFIG_007` / `CONFIG_010`) |
| 6 | Lock contention (another migration holds the advisory lock) |
| 7 | One or more error-severity findings — a migration failed to replay (`PFLIGHT_REPLAY_FAILED`), a missing `.down.sql`, a duplicate version, or a checksum mismatch |

In `--format json`, the report is the unified `{ok, summary, issues[]}` envelope (#151) — each failed replay is a `PFLIGHT_REPLAY_FAILED` entry in `issues[]`, with the database error under `details.error`.

### Capturing the report for review

```bash
confiture migrate preflight --against "$PREFLIGHT_URL" \
  --format json --output preflight-report.json
```

`preflight-report.json` is the same data the human transcript is rendered from. It is the canonical artifact to attach to a deploy PR.

---

## Python API

```python
import psycopg
from confiture.core.dry_run import DryRunExecutor

with psycopg.connect("postgresql://localhost/mydb") as conn:
    executor = DryRunExecutor(conn)
    result = executor.run(
        migration_name="20260520143015_add_user_bio",
        statements=["ALTER TABLE users ADD COLUMN bio TEXT"],
    )

    if result.success:
        print(f"OK in {result.total_time_ms} ms (confidence {result.confidence_pct}%)")
        for stmt in result.statements:
            print(f"  {stmt.rows_affected} rows in {stmt.execution_time_ms} ms")
    else:
        print(f"Failed: {result.error}")
```

See the [dry-run API reference](../reference/dry-run-api.md) for the full surface.

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
