# Error-code codebook

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
| `ANON_1401` | 5 | error | Anonymization function not found: {function} | Define the anonymization function or use a built-in |
| `CONFIG_001` | 5 | error | Missing required field '{field}' in {file} | Add the field to your config file or set the corresponding environment variable |
| `CONFIG_002` | 5 | error | Invalid YAML syntax in {file} | Check the YAML syntax in your configuration file |
| `CONFIG_003` | 5 | error | Invalid database URL format | Use format: postgresql://user:password@host:port/database |
| `CONFIG_004` | 5 | error | Environment config not found: {env} | Create configuration file for this environment or use an existing one |
| `CONFIG_005` | 5 | error | Invalid include/exclude pattern | Check glob patterns in your configuration |
| `CONFIG_006` | 3 | error | Database connection failed | Check database URL, host, port, and credentials |
| `CONFIG_010` | 5 | error | Database URL not set in environment '{env}' | Set database_url in db/environments/{env}.yaml or DATABASE_URL environment variable |
| `DIFF_001` | 5 | error | Schema diff error | Check SQL DDL for parsing issues |
| `DIFFER_400` | 5 | error | Cannot parse SQL DDL | Fix the SQL syntax in your schema files |
| `DIFFER_401` | 5 | error | Schema comparison failed | Verify both schema definitions are valid |
| `DIFFER_402` | 1 | warning | Ambiguous schema changes detected | Review and clarify the schema changes |
| `GEN_001` | 3 | error | External generator error | Check the external generator command and its output |
| `GIT_001` | 7 | error | Git operation error | Check git repository status |
| `GIT_002` | 7 | error | Not a git repository | Initialize a git repository or use a valid repository path |
| `GIT_800` | 7 | error | Git command failed | Check git repository status |
| `GIT_801` | 7 | error | Invalid git reference: {ref} | Check the git reference name |
| `GIT_802` | 7 | error | Not a git repository | Initialize a git repository or use a valid repository path |
| `GRANT_001` | 7 | error | Grant accompaniment error | Stage a migration file alongside grant changes |
| `HOOK_1100` | 1 | error | Pre-migration hook failed | Check hook script and address the failure |
| `HOOK_1101` | 1 | error | Post-migration hook failed | Migration succeeded but hook failed |
| `LINT_1500` | 5 | error | Schema lint error: {message} | Fix the schema linting error |
| `LINT_1501` | 0 | warning | Schema lint warning: {message} | Address the linting warning |
| `LOCK_1300` | 6 | error | Cannot acquire database lock | Wait for other operations to complete |
| `LOCK_1301` | 6 | warning | Lock held by {holder} | Check what operation is holding the lock |
| `MIGR_001` | 3 | error | Migration error | Check migration files and database state |
| `MIGR_004` | 3 | error | Migration file already exists | Use --force flag to overwrite existing file |
| `MIGR_010` | 3 | error | Lock timeout waiting for migration lock | Retry with a higher --lock-timeout value or schedule during low-traffic window |
| `MIGR_011` | 3 | error | Checksum mismatch for migration '{version}' | Migration file was modified after application. Restore the original file or use --force to override. |
| `MIGR_100` | 3 | error | Migration {version} not found | Check the migration version and ensure the file exists |
| `MIGR_101` | 0 | warning | Migration {version} already applied | This migration has already been applied to the database |
| `MIGR_102` | 3 | error | Migration file corrupted: {file} | Regenerate or restore the migration file |
| `MIGR_103` | 3 | error | Migration dependency not met: {version} | Apply prerequisite migrations before this one |
| `MIGR_104` | 3 | error | Migration locked by another process | Wait for other migration to complete or check for stale locks |
| `MIGR_105` | 0 | info | No pending migrations to apply | Your database schema is up to date |
| `MIGR_106` | 3 | error | Duplicate migration version: {version} | Multiple migration files share the same version number. Rename files to use unique version prefixes. Run 'confiture migrate validate' to see all duplicates. |
| `MIGR_107` | 3 | error | Migration {version} ({name}) issued an explicit COMMIT or ROLLBACK in its body, breaking confiture's transaction envelope | Remove any explicit COMMIT or ROLLBACK from the migration body. Confiture manages the outer transaction; embedded transaction control leaves the database in an unrecoverable state if a subsequent statement fails. If you need autocommit semantics, set transactional = False on the migration. |
| `PGGIT_900` | 7 | error | pgGit command failed | Check pgGit is installed and configured |
| `PGGIT_901` | 7 | error | Invalid pgGit configuration | Check pgGit configuration in confiture config |
| `POOL_1200` | 6 | error | Connection pool exhausted | Increase pool size or wait for connections to be released |
| `POOL_1201` | 6 | error | Connection pool initialization failed | Check database connection settings |
| `PRECON_1000` | 5 | error | Precondition not met: {condition} | Ensure the precondition is satisfied before retrying |
| `PRECON_1001` | 2 | error | Database not initialized | Run 'confiture init' to initialize the database |
| `REBUILD_001` | 4 | error | Schema rebuild error | Check schema DDL and database state |
| `RESTORE_001` | 5 | error | Restore error | Check backup format and pg_restore availability |
| `ROLLBACK_001` | 8 | critical | Rollback error | Check rollback SQL and database state |
| `ROLLBACK_600` | 8 | critical | Cannot rollback: irreversible change | Manual intervention required; cannot automatically rollback |
| `ROLLBACK_601` | 8 | critical | Rollback SQL failed | Check rollback script syntax and database state |
| `ROLLBACK_602` | 8 | critical | Database state inconsistent after rollback | Database may be partially rolled back; manual recovery needed |
| `SCHEMA_001` | 4 | error | Schema error | Check SQL DDL files for errors |
| `SCHEMA_200` | 4 | error | SQL syntax error in {file} at line {line} | Fix the SQL syntax error at the specified location |
| `SCHEMA_201` | 4 | error | Schema directory not found: {directory} | Create the schema directory or check the path |
| `SCHEMA_202` | 4 | error | Circular dependency detected | Break the circular dependency between schema files |
| `SCHEMA_203` | 4 | error | Duplicate table definition: {table} | Remove the duplicate table definition |
| `SCHEMA_204` | 4 | error | Schema hash mismatch | Schema definition has changed; rebuild the schema |
| `SEED_001` | 5 | error | Seed execution error | Check seed file syntax and database state |
| `SQL_001` | 1 | error | SQL execution error | Check the SQL statement for errors |
| `SQL_700` | 1 | error | SQL execution failed | Check the SQL statement for errors |
| `SQL_701` | 1 | error | Prepared statement error | Check statement parameters |
| `SQL_702` | 1 | warning | Transaction deadlock detected | Retry the transaction |
| `SQL_703` | 1 | error | Lock timeout exceeded | Wait for locks to be released or reduce query load |
| `SYNC_001` | 5 | error | Sync error | Check source and target database connections |
| `SYNC_300` | 5 | error | Cannot connect to source database | Check source database connection settings |
| `SYNC_301` | 5 | error | Table '{table}' not found in source database | Verify table exists in source database |
| `SYNC_302` | 5 | error | Anonymization rule failed for column '{column}' | Check anonymization rule syntax |
| `SYNC_303` | 5 | error | Data copy operation failed | Check both source and target database connections |
| `VALID_001` | 5 | error | Validation error | Check validation rules and data integrity |
| `VALID_500` | 5 | error | Row count mismatch: expected {expected}, got {actual} | Verify data was copied correctly |
| `VALID_501` | 5 | error | Foreign key constraint violated | Check foreign key relationships in your data |
| `VALID_502` | 5 | error | Custom validation rule failed | Review custom validation rules |
| `VERIFY_001` | 5 | error | Verify file contains forbidden SQL | Verify files must only contain SELECT queries |
<!-- END GENERATED -->

> The table above is generated from `ERROR_CODE_REGISTRY`. Regenerate with
> `python -c "from confiture.core.error_codes import render_error_codebook;
> print(render_error_codebook())"`; the codebook test
> (`tests/unit/test_error_codebook.py`) fails if it drifts.

## Stability contract

Symbolic error codes are **public API**:

- **Additive only** — new codes may be added; existing codes are not renamed.
- A code's meaning is stable. Its integer exit code follows the
  [exit-code convention](exit-codes.md) and is likewise frozen.
- Removing or renaming a code requires a **major version bump** and a CHANGELOG
  note.

Some codes (`PGGIT_*`, `GIT_*`) are internal and unlikely to surface in the
`--format json` output of the migrate family — depend on the codes the migrate
commands actually emit (the connection / migration / lock / rollback families).

## See also

- [Exit-code convention](exit-codes.md)
- [Error Reference Guide](../error-reference.md) — human-facing fix-it walkthroughs
- [JSON output schemas](json-schemas.md)
