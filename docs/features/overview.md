# Feature Overview

The full feature laundry list — for the 30-second pitch and quick-start, see [the README](../../README.md).

## Migration Management
- **`migrate preflight`** — pre-deploy safety gate: checks reversibility, non-transactional statements, duplicate versions, and checksum tampering. JSON output for CI/CD.
- **`migrate preflight --against`** — replay pending migrations end-to-end against a parallel database and structurally diff the result. See [the dry-run guide](../guides/dry-run.md#preflight-against-a-parallel-database).
- **Semantic exit codes** — `0` success, `2` validation error, `3` SQL failure, `6` lock contention, `7` structural drift. Script with confidence.
- **`migrate baseline`** — adopt Confiture on databases that already have migrations applied. See [the legacy-bootstrap guide](../guides/legacy-bootstrap.md).
- **`migrate rebuild`** — drop and recreate from DDL + replay migrations in one command. Fast environment reset.
- **`migrate validate`** — naming convention checks, schema drift detection, function signature and body drift.
- **`migrate fix-signatures`** — detect and atomically fix stale function overloads and body drift.
- **Dry-run with SAVEPOINT testing** — `--dry-run-execute` runs migrations inside a savepoint, then rolls back.
- **Checksum verification** — detect tampered migration files before applying.
- **Distributed locking** — safe concurrent deployments via PostgreSQL advisory locks.
- **Migration hooks** — run custom logic before/after each migration.

## Schema Intelligence
- **Schema diff detection** — two-tier parser: pglast (PostgreSQL's C parser) primary, sqlparse fallback.
- **Schema linting** — configurable rules to catch common DDL mistakes.
- **Function introspection** — `FunctionIntrospector`, `TypeMapper`, and `DependencyGraph` for deep schema analysis.
- **Grant accompaniment checker** — detect permission changes without corresponding migrations.
- **Named-schema support** — `metrics.events`, `auth.users`, multi-schema projects. See [the named-schemas guide](../guides/named-schemas.md).

## Seed Data
- **Sequential execution** — handles PostgreSQL parser limits on large seed files.
- **Per-file savepoint isolation** — one bad seed file doesn't ruin the batch.
- **5-level prep-seed validation** — static analysis through full execution, pre-commit safe at levels 1-3.

## Multi-Agent Coordination
- **Intent registration** — declare which tables you're changing before you start.
- **Conflict detection** — automatic alerts when agents touch overlapping tables.
- **JSON output** — machine-readable for CI/CD pipelines.

## Developer Experience
- **Structured output** — JSON, CSV, and YAML for all commands.
- **Exception hierarchy** — typed errors with error codes and resolution hints.
- **Git-aware validation** — detect schema drift vs. main branch, enforce migrations for DDL changes.
- **PII anonymization** — built-in strategies for production sync.
- **Optional Rust extension** — drop-in performance boost for SQL parsing and hashing.
- **Python 3.11, 3.12, 3.13** — tested across all supported versions.
