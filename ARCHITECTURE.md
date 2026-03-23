# Confiture Architecture

**Version**: 0.8.9
**Last Updated**: 2026-03-23
**Status**: Production-Ready

---

## Core Philosophy

> **"Build from DDL, not migration history"**

The `db/schema/` directory is the **single source of truth**. Migrations are derived from schema changes, not primary artifacts. The schema you write is what you get — the migration system brings existing databases in line with it.

---

## System Overview

Confiture is a modern PostgreSQL migration tool with **four distinct mediums** for different use cases:

```
┌─────────────────────────────────────────────────────────────────┐
│                      Confiture Mediums                          │
│                                                                 │
│  1. Build from DDL     2. Incremental       3. Production       │
│     (confiture build)     (migrate up)        (sync)            │
│                                                                 │
│  Create fresh DB      Apply migrations      Copy data with      │
│  from schema DDL      incrementally         anonymization       │
│                                                                 │
│                4. Schema-to-Schema                             │
│                (FDW migration)                                 │
│                                                                 │
│            Zero-downtime migrations via                        │
│            Foreign Data Wrapper                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Architecture Layers

### 1. CLI Layer (`python/confiture/cli/`)

**Purpose**: User-facing command interface via the Typer framework, organised into focused modules with shared helpers.

#### 1.1 Entry Point

- **`main.py`** (166 lines) — App setup only. Creates the `app` Typer instance, registers sub-apps (`migrate`, `branch`, `generate`, `coordinate`, `seed`), and attaches all command functions imported from command modules. Contains no business logic.

#### 1.2 Shared Helpers (`helpers.py`, 418 lines)

Central module providing utilities shared across all command modules:
- `console` / `error_console` — Rich consoles for stdout and stderr
- `_output_json()` / `_output_yaml()` — structured output helpers
- `_get_tracking_table()` — safely extracts `migration.tracking_table` from `Environment`, dict, or MagicMock
- `_get_suggestion()` — "Did you mean?" suggestions via difflib
- `_convert_linter_report()` — linter report type conversion
- `_find_orphaned_sql_files()`, `_validate_idempotency()`, `_fix_idempotency()` — migration hygiene helpers
- `_print_duplicate_versions_warning()`, `_print_orphaned_files_warning()` — warning printers

#### 1.3 Command Modules (`commands/`)

Each module registers with `migrate_app` or `app` in `main.py`. No module contains shared state.

| Module | Commands | Lines |
|--------|----------|-------|
| `commands/schema.py` | `init`, `build`, `lint`, `introspect` | 733 |
| `commands/migrate_core.py` | `migrate status`, `migrate up`, `migrate down`, `migrate generate` | 1635 |
| `commands/migrate_state.py` | `migrate baseline`, `migrate reinit`, `migrate rebuild` | 522 |
| `commands/migrate_analysis.py` | `migrate diff`, `migrate validate`, `migrate fix`, `migrate introspect`, `migrate verify` | 860 |
| `commands/admin.py` | `install-helpers`, `validate_profile`, `verify`, `restore` | 379 |

#### 1.4 Additional CLI Modules

- **`branch.py`** — `branch` subcommand group (pgGit integration)
- **`coordinate.py`** — `coordinate` subcommand group (multi-agent coordination)
- **`seed.py`** — `seed` subcommand group (seed validation)
- **`generate.py`** — `generate` subcommand group (migration generation)
- **`dry_run.py`** — Dry-run UI helpers (`display_dry_run_header`, `save_text_report`, `save_json_report`, `ask_dry_run_execute_confirmation`, `extract_sql_statements_from_migration`)
- **`git_validation.py`** — Pre-commit git validation helpers

#### 1.5 Formatters (`formatters/`)

| Module | Purpose |
|--------|---------|
| `build_formatter.py` | Format `confiture build` output |
| `migrate_formatter.py` | Format migration results (`MigrateUpResult`, `MigrateDownResult`, etc.) and `show_migration_error_details()` |
| `seed_formatter.py` | Format seed execution output |
| `common.py` | Shared formatting utilities |

---

### 2. Core Layer (`python/confiture/core/`)

**Purpose**: Business logic and database operations. The CLI layer delegates to this layer; it contains no CLI framework imports.

#### 2.1 Schema & Build

| Module | Description |
|--------|-------------|
| `builder.py` | `SchemaBuilder` — reads SQL files from `db/schema/`, concatenates in deterministic order, builds fresh databases (Medium 1) |
| `differ.py` | `SchemaDiffer` — structural diff between two schema versions |
| `schema_snapshot.py` | `SchemaSnapshotGenerator` — saves schema snapshots to `db/schema_history/` after each migration |
| `schema_analyzer.py` | Schema analysis utilities |
| `linting/` | `SchemaLinter` — SQL linting rules and report generation |

#### 2.2 Migration Execution

| Module | Description |
|--------|-------------|
| `migrator.py` | `Migrator` + `MigratorSession` — core migration engine; tracks state in configurable tracking table (default `public.tb_confiture`); timestamp-based versioning (`YYYYMMDDHHMMSS`) |
| `migration_generator.py` | `MigrationGenerator` — generates migration files; supports external generators via subprocess |
| `migration_verifier.py` | `MigrationVerifier` + `VerifyResult` — runs `.verify.sql` queries post-migration |
| `rollback_generator.py` | Generates rollback SQL for migrations |
| `baseline_detector.py` | `BaselineDetector` — fuzzy schema matching (85% threshold) to find the right baseline snapshot for `--auto-detect-baseline` |

#### 2.3 Introspection Layer (`introspection/`)

A package providing PostgreSQL introspection beyond tables and columns, used as foundation for code generation features (Phase 6):

| Module | Description |
|--------|-------------|
| `introspection/functions.py` | `FunctionIntrospector` — queries `pg_catalog` to retrieve function/procedure definitions, parameters, volatility, language, and source |
| `introspection/type_mapping.py` | `TypeMapper` — maps PostgreSQL types to Python/GraphQL types |
| `introspection/dependency_graph.py` | `DependencyGraph` + `DependencyOrder` — tracks function/view dependencies for safe drop/recreate ordering |
| `introspection/sql_ast.py` | `CTENode`, `JSONBKey` — lightweight SQL AST nodes for structured query analysis |
| `introspector.py` | `SchemaIntrospector` — existing table/column/FK introspection via `pg_catalog` |

#### 2.4 Database Operations

| Module | Description |
|--------|-------------|
| `connection.py` | `create_connection()`, `load_config()` — psycopg3 connection management |
| `syncer.py` | Production data sync with PII anonymization (Medium 3) |
| `schema_to_schema.py` | Zero-downtime migration via Foreign Data Wrapper (Medium 4) |
| `restorer.py` | `pg_restore` wrapper with diagnostics |
| `pool.py` | Connection pooling utilities |
| `dry_run.py` | `DryRunExecutor` — SAVEPOINT-based migration testing with guaranteed rollback |

#### 2.5 Accompaniment & Validation

| Module | Description |
|--------|-------------|
| `grant_accompaniment.py` | `GrantAccompanimentChecker` — detects grant file changes staged without a corresponding `.up.sql` migration |
| `preconditions.py` | `PreconditionError`, `PreconditionValidationError` — pre-migration condition checks |
| `checksum.py` | Migration file checksum computation and comparison |
| `idempotency/` | SQL idempotency analysis and fixing utilities |
| `validators/` | Additional SQL/schema validators |

#### 2.6 Advanced Features

| Module | Description |
|--------|-------------|
| `git.py`, `git_accompaniment.py`, `git_schema.py` | Git integration for schema tracking |
| `anonymization/` | PII anonymization strategies for production sync |
| `seed/`, `seed_executor.py`, `seed_applier.py`, `seed_validation/` | 5-level seed validation system with SAVEPOINT isolation |
| `locking.py` | PostgreSQL advisory locking for safe concurrent operations |
| `hooks/` | Migration lifecycle hooks (pre/post migration) |
| `observability/`, `metrics.py`, `metrics_aggregator.py` | Metrics and observability |
| `blue_green.py` | Blue-green deployment support |
| `risk/` | Migration risk assessment |
| `security/` | Security validation utilities |
| `error_codes.py` | `ErrorCodeDefinition`, `ErrorCodeRegistry` — structured error codes with exit codes |
| `error_handler.py`, `error_context.py` | Error handling utilities |

---

### 3. Configuration Layer (`python/confiture/config/`)

**Purpose**: Pydantic-based environment and configuration management.

**`environment.py`** — Defines the full Pydantic model hierarchy:

- `Environment` — top-level config; loaded from YAML via `load_config()`
- `MigrationConfig` — migration settings including `tracking_table` (default: `public.tb_confiture`), `snapshot_history`, `snapshots_dir`, and external `migration_generators`
- `BuildConfig` — `BuildLintConfig`, `SeparatorConfig`, `CommentValidationConfig`, output path settings
- `SeedConfig` — `execution_mode` (`concatenate` | `sequential`)
- `RebuildConfig` — `threshold`, `backup` toggle
- `LockingConfig` — advisory lock timeout settings
- `MigrationGeneratorConfig` — external generator command with `{from}`, `{to}`, `{output}` placeholder validation

**Example `confiture.yaml`**:

```yaml
name: local
database_url: postgresql://localhost/myapp_local

include_dirs:
  - db/schema

migration:
  tracking_table: public.tb_confiture
  snapshot_history: true
  snapshots_dir: db/schema_history

build:
  linting:
    enabled: true
  output_path: db/generated/schema.sql

seed:
  execution_mode: sequential

rebuild:
  threshold: 5
  backup: true

locking:
  enabled: true
  timeout_ms: 30000
```

All `database_url` values support `${VAR}` environment variable substitution.

---

### 4. Models Layer (`python/confiture/models/`)

**Purpose**: Data structures, result types, and type definitions used across layers.

| Module | Contents |
|--------|---------|
| `results.py` | `MigrationStatus`, `MigrationInfo`, `StatusResult`, `MigrateUpResult`, `MigrateDownResult`, `MigrateReinitResult`, `MigrateRebuildResult`, `MigrationApplied`, `VerifyAllResult` — all with `to_dict()` for JSON serialization; timing keys use `total_duration_ms` / `duration_ms` |
| `function_info.py` | `ParamMode`, `Volatility`, `FunctionParam`, `FunctionInfo`, `FunctionCatalog` — function/procedure introspection data |
| `introspection.py` | `IntrospectedColumn`, `FKReference`, `TableHints`, `IntrospectedTable`, `IntrospectionResult` — table/column/FK models |
| `git.py` | `MigrationAccompanimentReport`, `GrantAccompanimentReport` — git accompaniment check results |
| `lint.py` | `LintSeverity`, `Violation`, `LintConfig`, `LintReport` — linting result models |
| `schema.py` | Schema representation models |
| `migration.py` | `Migration` base class |
| `sql_file_migration.py` | SQL file migration representation |
| `error.py` | `ErrorSeverity` enum |

---

### 5. Exception Hierarchy (`python/confiture/exceptions.py`)

All exceptions inherit from `ConfiturError`. Each carries optional `error_code`, `severity`, `context`, and `resolution_hint` fields, plus a `.to_dict()` method and `.exit_code` property backed by `ErrorCodeRegistry`.

```
ConfiturError (base)
├── ConfigurationError          error_code: CONFIG_001
├── MigrationError              error_code: MIGR_001
│   ├── MigrationConflictError  error_code: MIGR_106
│   └── MigrationOverwriteError error_code: MIGR_004
├── SchemaError                 error_code: SCHEMA_001
├── SyncError                   error_code: SYNC_001
├── DifferError                 error_code: DIFF_001
├── ValidationError             error_code: VALID_001
│   └── VerifyFileError         error_code: VERIFY_001
├── RollbackError               error_code: ROLLBACK_001
├── SQLError                    error_code: SQL_001
├── GitError                    error_code: GIT_001
│   ├── NotAGitRepositoryError  error_code: GIT_002
│   └── GrantAccompanimentError error_code: GRANT_001
├── ExternalGeneratorError      error_code: GEN_001
├── RebuildError                error_code: REBUILD_001
├── RestoreError                error_code: RESTORE_001
└── SeedError                   error_code: SEED_001

# Imported from core modules and re-exported:
PreconditionError (from core.preconditions)
PreconditionValidationError (from core.preconditions)
PreStateSimulationError (from testing.sandbox)
```

Users can catch all Confiture-specific errors with `except ConfiturError`.

---

### 6. Public API (`python/confiture/__init__.py`)

All public symbols are declared in `__all__` and use lazy imports via a `_LAZY_IMPORTS` dict and `__getattr__` to avoid circular dependency issues at module load time.

**Core classes**:
- `Migrator`, `MigratorSession` — migration engine and context manager session
- `Environment` — configuration model
- `SchemaBuilder` — DDL-based schema builder
- `SchemaLinter` — schema linting
- `SchemaSnapshotGenerator`, `BaselineDetector` — snapshot and baseline management

**Introspection layer**:
- `FunctionIntrospector`, `TypeMapper`, `DependencyGraph`
- `FunctionInfo`, `FunctionParam`, `FunctionCatalog`

**Result models**:
- `MigrationStatus`, `MigrationInfo`, `StatusResult`
- `MigrateUpResult`, `MigrateDownResult`, `MigrateReinitResult`, `MigrateRebuildResult`
- `MigrationApplied`, `VerifyAllResult`

**Grant accompaniment & verification**:
- `GrantAccompanimentChecker`, `GrantAccompanimentReport`
- `MigrationVerifier`, `VerifyResult`

**Exceptions** (full list in `__all__`):
- `ConfiturError`, `ConfigurationError`, `MigrationError`, `SchemaError`, `SQLError`, `RollbackError`, `SeedError`, `RestoreError`, `PreconditionError`, `PreconditionValidationError`, `ExternalGeneratorError`, `GrantAccompanimentError`, `RebuildError`, `VerifyFileError`

**Library API example**:
```python
from confiture import Migrator

with Migrator.from_config("db/environments/prod.yaml") as m:
    status = m.status()
    if status.has_pending:
        result = m.up()
```

---

## Technology Stack

### Runtime Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `typer` | >=0.12 | CLI framework |
| `rich` | >=13.7 | Terminal formatting |
| `pydantic` | >=2.5 | Configuration validation |
| `pyyaml` | >=6.0 | YAML parsing |
| `psycopg[binary,pool]` | >=3.1 | PostgreSQL driver (sync + pool) |
| `sqlparse` | >=0.5 | SQL parsing |
| `sqlglot` | >=28.0 | SQL dialect-aware parsing and transformation |
| `cryptography` | >=42.0 | Encryption utilities |

### Optional Dependencies

| Package | Extra | Purpose |
|---------|-------|---------|
| `pglast` | `ast` | PostgreSQL SQL AST parsing (via libpg_query) |

### Dev / Testing Dependencies

`pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-json-report`, `ruff`, `ty` (Astral's type checker), `maturin`

---

## Key Design Decisions

### Decision 1: DDL as Source of Truth

**Choice**: Keep `db/schema/` as primary; derive migrations from schema changes.

**Rationale**: Schema is easier to understand than a migration sequence. New developers can read the DDL directory to understand the full current state without replaying history. Migration history is a consequence, not a primary artifact.

**Alternative considered**: Migration history as primary (Alembic style) — requires analyzing full history to understand current state; more complex for new contributors.

---

### Decision 2: Timestamp-Based Migration Versioning

**Choice**: Migration files use `YYYYMMDDHHMMSS` format (e.g., `20260310102415_add_users_table.up.sql`).

**Rationale**: Eliminates merge conflicts in multi-developer environments. Sequential numbers (001, 002, ...) require coordination to avoid collisions and impose a 999-migration limit. Old 001-style migrations sort first and remain valid (backwards compatible).

---

### Decision 3: Exception Hierarchy with Error Codes

**Choice**: All exceptions inherit `ConfiturError` and carry `error_code`, `severity`, `context`, and `resolution_hint`.

**Rationale**: Enables structured error handling for automation (CI/CD, agents) via `e.to_dict()` and `e.exit_code`. Resolution hints provide actionable guidance without requiring users to look up documentation.

---

### Decision 4: Lazy Imports in `__init__.py`

**Choice**: Public API uses `_LAZY_IMPORTS` dict + `__getattr__` instead of direct top-level imports.

**Rationale**: Avoids circular dependency issues at module load time. The package is importable without incurring the cost of loading every submodule. Editors and type checkers still see the full `__all__` list.

---

### Decision 5: CLI Split — Thin `main.py` + Focused Command Modules

**Choice**: `main.py` is 166 lines of registration only; business-facing command code lives in `commands/` modules; shared helpers are in `helpers.py`.

**Rationale**: A single monolithic `main.py` (was >4000 lines) becomes untestable and hard to navigate. Focused modules allow co-locating related commands, make mock patch targets stable, and reduce merge conflicts when multiple features are developed in parallel.

---

### Decision 6: SAVEPOINT-Based Dry-Run Testing

**Choice**: `--dry-run-execute` uses PostgreSQL SAVEPOINTs for safe migration testing.

**Rationale**: Guaranteed rollback regardless of interrupt. Works with synchronous psycopg3 connections. Clear semantics — users see real execution timings and row counts, then confirm or abort.

---

### Decision 7: Introspection Layer as Shared Foundation

**Choice**: `core/introspection/` provides `FunctionIntrospector`, `TypeMapper`, `DependencyGraph`, and `sql_ast` as a reusable package.

**Rationale**: Multiple CLI commands (`migrate introspect`, code generation features) need PostgreSQL function and type metadata. A shared layer avoids duplicating `pg_catalog` queries and provides a stable API for future code generation features (GraphQL resolver stubs, type-safe wrappers, etc.).

---

## Testing Architecture

### Test Counts (2026-03-10)

- **Total collected**: 5,583
- **Unit tests passing**: 4,518
- **Skipped**: 13
- **Python versions**: 3.11, 3.12, 3.13

### Test Pyramid

```
        ┌──────────────┐
        │    E2E       │  ~10% - Full CLI workflows
        ├──────────────┤
        │Integration   │  ~20% - Real database operations
        ├──────────────┤
        │   Unit       │  ~70% - Fast, isolated, mocked
        └──────────────┘
```

### Test Organisation

- **`tests/unit/`** — Fast tests with mocked database connections. No PostgreSQL required.
- **`tests/integration/`** — Require a live PostgreSQL instance. Test real query execution, schema introspection, and migration apply/rollback.
- **`tests/e2e/`** — Full CLI workflow tests via Typer's `CliRunner`.
- **`tests/fixtures/`** — SQL fixtures, schema files, migration stubs.

### Patch Targets

When mocking in tests, use these module-level targets:

| Symbol | Patch target |
|--------|-------------|
| `Migrator` in CLI | `confiture.core.migrator.Migrator` |
| `create_connection` | `confiture.core.migrator.create_connection` |
| `load_config` | `confiture.core.connection.load_config` |
| `SchemaBuilder` snapshot | `confiture.core.schema_snapshot.SchemaBuilder` |
| `BaselineDetector` introspector | `confiture.core.baseline_detector.SchemaIntrospector` |

---

## Related Documentation

- **[README.md](./README.md)** — Quick start and overview
- **[CLAUDE.md](./CLAUDE.md)** — AI-assisted development guide
- **[CHANGELOG.md](./CHANGELOG.md)** — Release notes by version
- **[docs/guides/](./docs/guides/)** — User guides for each medium and feature

---

**Last Updated**: 2026-03-23
**Version**: 0.8.9
**Status**: Production-Ready
