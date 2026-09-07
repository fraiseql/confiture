# Error-code codebook

> **Frozen at 1.0.0.** The error codes, their exit codes and the envelope shape below are a stability contract. A change here is a breaking change: it needs a major version and a CHANGELOG entry.

When a `confiture` command fails in `--format json` mode, it emits a structured
**error envelope** on stdout (the process still exits with the
[exit code](exit-codes.md) for that error):

```json
{
  "ok": false,
  "error": {
    "severity": "error",
    "code": "MIGR_106",
    "message": "Duplicate migration versions detected: 20260101000001",
    "actionable": "Rename files to use unique version prefixes.",
    "details": { "conflicting_files": ["a.up.sql", "b.up.sql"] },
    "migration": null,
    "file": null,
    "line": null
  }
}
```

The `error` value is the **unified inner issue object** shared with
`validate-config` (#144) and the preflight report (#148): every one carries the
same `{severity, code, message, actionable, details, migration, file, line}`
shape, so downstream tooling parses one structure everywhere. `severity`,
`code`, and `message` are always present; the rest are present-but-nullable.
`CRITICAL`-severity errors serialize as `"error"` in the public contract.

The JSON Schemas are published under
[`docs/reference/json-schemas/`](json-schemas/) — `error-envelope.schema.json`
(`$ref`s `issue-object.schema.json`).

## Codebook

Every registered symbolic code, its exit code (see [exit-codes.md](exit-codes.md)
for the convention), severity, message template, and the `actionable`
resolution hint surfaced in the envelope.

<!-- BEGIN GENERATED: codebook -->
| Code | Exit | Severity | Message | Actionable |
|------|:----:|----------|---------|------------|
| `ANON_1400` | 5 | error | Invalid anonymization rule | Check anonymization rule syntax |
| `CONFIG_001` | 5 | error | Missing required field '{field}' in {file} | Add the field to your config file or set the corresponding environment variable |
| `CONFIG_002` | 5 | error | Invalid YAML syntax in {file} | Check the YAML syntax in your configuration file |
| `CONFIG_003` | 5 | error | Invalid database URL format | Use format: postgresql://user:password@host:port/database |
| `CONFIG_004` | 5 | error | Environment config not found: {env} | Create configuration file for this environment or use an existing one |
| `CONFIG_006` | 3 | error | Database connection failed | Check database URL, host, port, and credentials |
| `CONFIG_007` | 5 | error | Conflicting explicit DSN sources: an explicit --config/--env and CONFITURE_DATABASE_URL are both set | Pass exactly one explicit source: drop --config/--env, unset CONFITURE_DATABASE_URL, or pass --no-config to make the env var authoritative. |
| `CONFIG_008` | 5 | error | Invalid migration.tracking_table: {value} | Use letters, digits and underscores only, optionally schema-qualified (e.g. public.tb_confiture) |
| `CONFIG_009` | 5 | error | Anonymization secret not set ({env_var}) | Export ANONYMIZATION_SECRET to a long random string kept out of version control before running an anonymizing sync or a keyed hash strategy |
| `CONFIG_010` | 5 | error | Database URL not set in environment '{env}' | Set database_url in db/environments/{env}.yaml or DATABASE_URL environment variable |
| `CONFIG_011` | 5 | error | pglast {version} does not expose {members}; confiture cannot walk DDL with it | Install a pglast release confiture supports (pglast>=6.0, current major) |
| `CONFIG_012` | 5 | error | Lint baseline file is missing or malformed: {file} | Create or regenerate it with `confiture lint --baseline <file> --write-baseline` |
| `DDL_001` | 4 | error | Destructive DDL operation refused without --force: {operation} | Re-run with --force if the destructive change is intended |
| `DIFF_001` | 5 | error | Schema diff error | Check SQL DDL for parsing issues |
| `DIFFER_400` | 5 | error | Cannot parse SQL DDL | Fix the SQL syntax in your schema files |
| `DIFFER_401` | 5 | error | Destructive change forbidden by policy | Re-run with --allow-destructive, or set migration.destructive to gated or allow |
| `GEN_001` | 3 | error | External generator error | Check the external generator command and its output |
| `GIT_001` | 7 | error | Git operation error | Check git repository status |
| `GIT_002` | 7 | error | Not a git repository | Initialize a git repository or use a valid repository path |
| `GIT_003` | 7 | error | Base ref unreachable in this checkout | In CI, set fetch-depth: 0 (actions/checkout) or run 'git fetch --unshallow origin <branch>' |
| `GRANT_001` | 7 | error | Grant accompaniment error | Stage a migration file alongside grant changes |
| `LOCK_1300` | 6 | error | Cannot acquire database lock | Wait for other operations to complete |
| `MIGR_001` | 3 | error | Migration error | Check migration files and database state |
| `MIGR_004` | 3 | error | Migration file already exists | Use --force flag to overwrite existing file |
| `MIGR_100` | 3 | error | Migration {version} not found | Check the migration version and ensure the file exists |
| `MIGR_101` | 0 | warning | Migration {version} already applied | This migration has already been applied to the database |
| `MIGR_102` | 3 | error | Migration file corrupted: {file} | Regenerate or restore the migration file |
| `MIGR_106` | 3 | error | Duplicate migration version: {version} | Multiple migration files share the same version number. Rename files to use unique version prefixes. Run 'confiture migrate validate' to see all duplicates. |
| `MIGR_107` | 3 | error | Migration {version} ({name}) issued an explicit COMMIT or ROLLBACK in its body, breaking confiture's transaction envelope | Remove any explicit COMMIT or ROLLBACK from the migration body. Confiture manages the outer transaction; embedded transaction control leaves the database in an unrecoverable state if a subsequent statement fails. If you need autocommit semantics, set transactional = False on the migration. |
| `MIGR_108` | 3 | error | Migration {version} is non-transactional and cannot run with commit=False (inside a SAVEPOINT) | A non-transactional migration commits the current transaction and runs in autocommit, so it cannot be tested inside a SAVEPOINT. `session.up(dry_run_execute=True)` skips such migrations; apply them for real with `migrate up`. |
| `PGGIT_900` | 7 | error | pgGit command failed | Check pgGit is installed and configured |
| `PRECON_1000` | 5 | error | Precondition not met: {condition} | Ensure the precondition is satisfied before retrying |
| `PRECON_1001` | 2 | error | Database not initialized | Run 'confiture init' to initialize the database |
| `REBUILD_001` | 4 | error | Schema rebuild error | Check schema DDL and database state |
| `RESTORE_001` | 5 | error | Restore error | Check backup format and pg_restore availability |
| `ROLLBACK_001` | 8 | critical | Rollback error | Check rollback SQL and database state |
| `ROLLBACK_600` | 8 | critical | Cannot rollback: irreversible change | Manual intervention required; cannot automatically rollback |
| `SCHEMA_001` | 4 | error | Schema error | Check SQL DDL files for errors |
| `SCHEMA_201` | 4 | error | Schema directory not found: {directory} | Create the schema directory or check the path |
| `SCHEMA_202` | 4 | error | Circular dependency detected | Break the circular dependency between schema files |
| `SCHEMA_205` | 4 | error | psql meta-command in {file} at line {line} | Remove the backslash commands; only SQL statements and inline COPY … FROM stdin data blocks are applied |
| `SEED_001` | 5 | error | Seed execution error | Check seed file syntax and database state |
| `SQL_001` | 1 | error | SQL execution error | Check the SQL statement for errors |
| `SYNC_001` | 5 | error | Sync error | Check source and target database connections |
| `VALID_001` | 5 | error | Validation error | Check validation rules and data integrity |
| `VALID_002` | 5 | error | Destructive migration refused: data is lost when it applies | Review the migration, then run migrate up --allow-destructive |
| `VERIFY_001` | 5 | error | Verify file contains forbidden SQL | Verify files must only contain SELECT queries |
<!-- END GENERATED -->

> The table above is generated from `ERROR_CODE_REGISTRY`. Regenerate with
> `python -c "from confiture.error_codes import render_error_codebook;
> print(render_error_codebook())"`; the codebook test
> (`tests/unit/test_error_codebook.py`) fails if it drifts.

## `LOCK_1300` — lock-holder identity (`details.holder`)

When `migrate up`/`down`/`down-to` cannot acquire the migration lock, the
`LOCK_1300` envelope carries the current holder under `details.holder` (issue
#147):

```json
{ "ok": false, "error": { "code": "LOCK_1300",
  "message": "Could not acquire migration lock within 30.0s. Held by pid 12345 on deploy-1 running \"confiture migrate up\"; acquired 47s ago.",
  "details": { "holder": {
    "pid": 12345, "hostname": "deploy-1", "user": "deploy",
    "command": "confiture migrate up",
    "acquired_at": "2026-05-31T14:30:00+00:00", "held_for_seconds": 47 } },
  "actionable": "Wait for the current migration to finish, then retry." } }
```

Identity is recorded best-effort in a `confiture_lock_holder` metadata table
written *under* the advisory lock. The advisory lock remains the source of truth
for "is it held" — if the holder crashes, the advisory lock auto-releases and
the lingering row is reported as stale. `held_for_seconds > 300` adds a
stale-lock hint to `actionable`. When no identity is available (older holder, or
the metadata table is absent), `details.holder` is `null` and the message says
so — diagnostics never block a migration.

## `PFLIGHT_*` — preflight report issue codes (#148)

`migrate preflight --format json` returns a *report* (`{ok, summary, issues[]}`),
not the error envelope above — in **both** the default and `--against` modes
(unified in 0.21.0, #151). Each `issues[]` element is the same unified issue
object, carrying a `PFLIGHT_*` code. These are report codes (not `ConfiturError`
registry codes); the command's exit comes from the summary — any error → 7,
warnings → 0 unless `--strict`.

| Code | Default severity | Meaning |
|------|------------------|---------|
| `PFLIGHT_MISSING_DOWN` | error | Migration has no matching `.down.sql` (not reversible) |
| `PFLIGHT_NON_TRANSACTIONAL` | warning | Migration contains a statement that can't run in a transaction (e.g. `CREATE INDEX CONCURRENTLY`) |
| `PFLIGHT_DUPLICATE_VERSION` | error | Two migration files share a version prefix |
| `PFLIGHT_CHECKSUM_MISMATCH` | error | An applied migration's file changed after it was applied |
| `PFLIGHT_REPLAY_FAILED` | error | A migration failed to replay against the `--against` DB (the DB error is in `details.error`) |
| `PFLIGHT_LIVE_DEPENDENTS` | warning | (reserved) live dependents found for a replaced object |

### Replica-safety codes (`PFLIGHT_REPLICA_*`, lint `replica_001`, #139)

The replica-aware forward-compatibility lint emits these (severity per the
[policy](../guides/replica-safe-migrations.md#default-severity-policy): warning by
default, error when replicas are declared, downgraded by
`allow_unsafe_under_replication`):

| Code | Operation | Multi-step fix |
|------|-----------|----------------|
| `PFLIGHT_REPLICA_ADD_COLUMN` | `ADD COLUMN` NOT NULL / DEFAULT | add nullable → backfill → `SET NOT NULL` later |
| `PFLIGHT_REPLICA_DROP_COLUMN` | `DROP COLUMN` | deprecate → wait one release → drop |
| `PFLIGHT_REPLICA_RENAME_COLUMN` | `RENAME COLUMN` | add new → dual-write → migrate readers → drop old |
| `PFLIGHT_REPLICA_CHANGE_TYPE` | `ALTER COLUMN ... TYPE` | add new column → backfill → swap readers → drop old |
| `PFLIGHT_REPLICA_ADD_CONSTRAINT` | `ADD CONSTRAINT` (immediate) | `NOT VALID` → backfill → `VALIDATE` |
| `PFLIGHT_REPLICA_CREATE_INDEX` | non-concurrent `CREATE INDEX` | `CREATE INDEX CONCURRENTLY` |
| `PFLIGHT_REPLICA_UNCLASSIFIED` | dynamic / unparseable DDL, or a non-SQL `.py` migration the classifier cannot read | review manually (always a warning) |

See the [replica-safe migrations guide](../guides/replica-safe-migrations.md) for the full
rationale. This `PFLIGHT_REPLICA_*` set is also a **cross-repo wire contract**:
fraisier's blue-green window-safety gate blocks on the presence of any of these
codes in `migrate preflight`'s `issues[]`, so the set is pinned by the
[fraisier-adapter contract](fraisier-adapter-contract.md#replica-forward-compatibility-namespace-window-safety-seam)
(renames are breaking, additions are allowed).

## Library consumers: `str(exc)` carries the `actionable` hint

The envelope's `actionable` field is the exception's `resolution_hint`. Outside
`--format json` — a pytest fixture, orchestration code, a log line — nothing
renders it for you, so it is part of `str(exc)`:

```
<message>
Hint: <resolution_hint>
```

`exc.message` is the message alone and `exc.resolution_hint` the hint alone; use
those (not `str(exc)`) if you render the hint yourself or keyword-match the
message. The envelope's `message` is always hint-free. See
[the library API notes](../api/migrator.md#error-handling).

## Stability contract

Symbolic error codes are **public API**:

- **Additive only** — new codes may be added; existing codes are not renamed.
- A code's meaning is stable. Its integer exit code follows the
  [exit-code convention](exit-codes.md) and is likewise frozen.
- Removing or renaming a code requires a **major version bump** and a CHANGELOG
  note.
- The one exception was 0.51.0, which removed 36 codes that had been registered
  but were never emitted by any command (the list is in the CHANGELOG). Every
  code in the table above is one the package can produce; a test keeps it so.

Some codes (`PGGIT_*`, `GIT_*`) are internal and unlikely to surface in the
`--format json` output of the migrate family — depend on the codes the migrate
commands actually emit (the connection / migration / lock / rollback families).

## See also

- [Exit-code convention](exit-codes.md)
- [Error Reference Guide](../error-reference.md) — human-facing fix-it walkthroughs
- [JSON output schemas](json-schemas.md)
