# Confiture Architecture

**Version**: 0.8.10
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

- **`main.py`** — App setup only. Creates the `app` Typer instance, registers sub-apps (`migrate`, `branch`, `generate`, `coordinate`, `seed`), and attaches all command functions imported from command modules. Contains no business logic.

#### 1.2 Shared Helpers (`helpers.py`, ≤600 lines, guarded)

Central module providing utilities shared across all command modules:
- `console` / `error_console` — Rich consoles for stdout and stderr
- `_output_json()` / `_output_yaml()` — structured output helpers; `is_json()` collapses the varied `--format` parameter names to the one boolean the error boundary needs
- `_get_tracking_table()` — safely extracts `migration.tracking_table` from `Environment`, dict, or MagicMock
- `_resolve_config()`, `_emit_hint()`, `_get_suggestion()` — config path resolution, stderr hints, "Did you mean?" suggestions
- `_convert_linter_report()` — linter report type conversion
- `_find_orphaned_sql_files()`, `_print_duplicate_versions_warning()`, `_print_orphaned_files_warning()` — migration hygiene printers
- `_query_applied_versions()` — best-effort read of the ledger for the idempotency fixer

The heavier concerns live beside it, each a leaf that imports *from* `helpers.py`:
- **`options.py`** — `format_option(*allowed)`: the one `--format` validator (Click callback → `fail(ValidationError)`, exit 5, stderr)
- **`error_json.py`** — `fail()` and `@cli_boundary`: the one error boundary (`typer.Exit` crosses it; everything else becomes a `ConfiturError` envelope)
- **`dsn.py`** — `resolve_database_url()`, `param_is_explicit()`, `config_is_explicit()`, `has_intentional_dsn_source()` and the option help: the #152 DSN precedence contract
- **`idempotency.py`** — `migrate validate --idempotent` / `migrate fix --idempotent`: git scoping, reporting, fixing
- **`ownership.py`** — `migrate fix --ownership`
- **`dry_run_summary.py`** — the dry-run payload built from the real change-set classification and PostgreSQL's row statistics

#### 1.3 Command Modules (`commands/`)

Each module registers with `migrate_app` or `app` in `main.py`. No module contains shared state. Two AST guards
hold the shape: no CLI function body exceeds 150 lines (`tests/unit/cli/test_function_size_budget.py`) and no
CLI module reaches into a `_private` attribute of a core object (`tests/unit/cli/test_no_private_reach_in.py`).

| Module | Commands |
|--------|----------|
| `commands/schema.py` | `init`, `build`, `lint`, `introspect` |
| `commands/migrate/{up,down,status,generate,current,estimate}.py` | `migrate up/down/status/generate/current/estimate` |
| `commands/migrate/{baseline,reinit,rebuild}.py` | `migrate baseline/reinit/rebuild` |
| `commands/migrate/{diff,validate,fix,fix_signatures,introspect,verify,preflight}.py` | `migrate diff/validate/fix/fix-signatures/introspect/verify/preflight` |
| `commands/migrate/_settings.py`, `_dry_run_render.py` | shared by the `migrate` commands: validated `migration:` settings, dry-run rendering |
| `commands/admin.py` | `install-helpers`, `validate_profile`, `verify-checksums`, `restore` |

#### 1.4 Additional CLI Modules

- **`branch.py`** — `branch` subcommand group (pgGit integration)
- **`coordinate.py`** — `coordinate` subcommand group (multi-agent coordination)
- **`seed.py`** — `seed` subcommand group (seed validation)
- **`generate.py`** — `generate` subcommand group (migration generation)
- **`dry_run.py`** — Dry-run UI helpers (`display_dry_run_header`, `save_text_report`, `save_json_report`, `ask_dry_run_execute_confirmation`)
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
| `blue_green.py` | Blue-green deployment support |
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
| `sqlglot` | >=28.0 | SQL dialect-aware parsing and transformation |

### Optional Dependencies

| Package | Extra | Purpose |
|---------|-------|---------|
| `pglast` | `ast` | PostgreSQL SQL AST parsing (via libpg_query) |
| `fraiseql-uuid` | `seed-uuid` | Canonical structured pattern-UUID convention for seed-validation (see Decision 8) |

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

### Decision 8: Confiture's place in the FraiseQL stack — Python 1.x, a planned Rust 2.x port, and an ops-path-only role

Confiture is the **migration engine** of the FraiseQL stack. Three facts about its
position are easy to conflate, so they are pinned here:

**1. The 1.x line is Python; a Rust 2.x port is a planned, *scoped* milestone.**
The current Confiture is the stable **1.x** Python line. The eventual Rust port
becomes **2.x**: a planned, scoped milestone for **Q3–Q4 2027** (a focused 2–3
month project, *not* v1.0-blocking), per
[`fraise-stack/ROADMAP.md`](https://github.com/fraiseql/fraise-stack) (2026-05-31
decision log). The port's intended shape is a **standalone Confiture Rust crate
that `fraisier-core` embeds as a library** — the fraisier adapter is already
designed for that eventual library embed — *not* folding migration logic into
`fraisier-core`. Confiture keeps its identity and ownership across the port.

**2. The optional `confiture-core` PyO3 crate is a perf accelerator, NOT the port.**
The repo ships a small optional Rust extension (`confiture-core`, a `cdylib` PyO3
module exposing `build_schema` + `hash_files` for a file-IO speedup). It is a
**performance accelerator for the Python package** and has nothing to do with the
2.x port — different purpose, different scope. Contributors must not treat it as
the start of the Rust port or begin divergent Rust migration-engine work in it.

**3. Confiture is an ops-path concern, reached via fraisier — not the data path.**
Confiture runs at deploy/migration time. It is invoked by **fraisier** (the deploy
engine) through the native in-process
[`fraisier-adapter-confiture`](./docs/reference/fraisier-adapter-contract.md), and
is also an optional `fraiseql-data` extra. There is deliberately **no**
`fraiseql`-core dependency on confiture: the GraphQL engine's request path never
touches it. This ops-path-only coupling is the intended end state.

> The stack-wide map in `fraiseql-ecosystem/README.md` (2026-01-01) predates the
> Rust reshape and omits fraisier + SpecQL; `fraise-stack/ROADMAP.md` (2026-05-31)
> is the current source of truth and supersedes it.

### Decision 9: Risk classification lives on the preflight seam, not in a scoring engine

**Choice**: `core/risk_tier.py` (a pure five-value taxonomy) and
`core/change_set.py` (a statement-level classifier) emit a per-change risk tier
in `migrate preflight --format json`, wired into the adapter seam from the first
commit.

**Rationale**: Confiture previously had a risk engine — `core/risk/`, a
`DowntimePredictor` with numeric scoring — deleted at `2bf38f1` (−2043 lines) as
a never-wired parallel implementation with zero production importers. That
deletion was correct and this decision does not reverse it. Two things are
different:

- **It is consumed.** The tier crosses the migration-adapter seam as typed data
  under a ratified cross-repo contract (#197 / fraisier-core#44), tested from
  both sides against the same golden fixtures. The deleted engine answered a
  question nobody asked.
- **It is a taxonomy, not a score.** Five named tiers with documented boundaries,
  derived from the parsed statement by a pure function. A predicted downtime in
  seconds cannot be validated against reality; "this `DROP COLUMN` is
  irreversible" can. Resist reconstituting a score.

**Why a second parser**: the change set does *not* reuse
`core/replica/classifier.py`. That classifier feeds the pinned `window_safe`
verdict (#154) and reports only the operations in its safety matrix — anything
outside it degrades to `depends`, which flips `window_safe` to false. Widening it
to the change-set vocabulary would move a cross-repo contract as a side effect,
so `change_set.py` walks the statements itself and the two verdicts stay
independent. The cost is one extra parse per migration file, filesystem-bound and
measured in milliseconds; the alternative was a false verdict on a safety gate.

---

### Decision 10: One apply loop — the session owns orchestration

**Choice**: `MigratorSession` (`core/_migrator/session.py` and its `apply_loop`,
`rollback_loop`, `replay` modules) is the only place migrations are iterated,
locked, applied and recorded. The CLI commands call the session; they do not
loop over migrations themselves.

**Rationale**: two loops (one in the CLI, one in the library) drifted — dry-run
semantics, lock ordering and checksum verification differed by entry point. A
guard test (`tests/unit/test_cli_has_no_apply_loop.py`) fails on any `for … in
pending` in `cli/`, and the function-length and complexity budgets in
`tests/budgets.json` only shrink, so a second loop cannot grow back quietly.

---

### Decision 11: One SQL lexer, one parser

**Choice**: `core/sql_lexer.py` is the single tokeniser of SQL text
(libpq_query's scanner, nothing hand-written): statement boundaries, comments,
what is code on a line (`code_text`, the `psql` applier's meta-command scan),
the data rows of an inline `COPY`, and the `-- confiture:<name>` directives the
lint rules read. pglast is the one parser, a hard dependency. There is no regex
fallback and no switch to one.

**Rationale**: five splitters disagreed on `"a;b"` identifiers, `E'\';'`
literals and dollar-quoted bodies, and four rules each walked lines for their
own directive; an analyzer that fell back to regex when pglast was absent
reported a clean result it had not earned. A file pglast rejects is a
*finding* (`IDEM_UNPARSEABLE`, `PFLIGHT_UNPARSEABLE`, lint's `UNPARSEABLE`,
`DIFFER_400`), never a pass. `tests/unit/test_single_parser.py` fails on any
`FORCE_REGEX`, `_HAS_PGLAST` or `is_pglast_available` probe;
`tests/unit/test_one_sql_lexer.py` fails on any regex outside the lexer whose
pattern carries a lexical marker (a comment opener, a dollar quote, a literal
shape, `stdin`, `\.`), and the regexes that match a statement's *shape*
(`^CREATE\s+TABLE`) are the shrink-only `sql_keyword_regex` budget in
`tests/budgets.json`.

---

### Decision 12: Analyzers fail closed

**Choice**: when an analyzer cannot decide, the verdict is the unsafe one:
`window_safe` is false unless every operation is in the replica safety matrix;
an unparseable migration counts as unanalyzed and blocks with
`--fail-on-unanalyzable`; a static-evaluator refusal is a refusal, not a pass.

**Rationale**: a deploy gate that answers "safe" when it does not know is worse
than no gate. The fixtures under `tests/fixtures/idempotency_shapes/` pin what
each argument shape resolves to; narrowing the reach by refactor fails the row
that regressed.

---

### Decision 13: Injected factories instead of patch seams

**Choice**: `MigratorSession(connection_factory=…, migration_loader=…)`. The CLI
passes its one connection seam (`confiture.cli.helpers.create_connection`); tests
inject doubles through the constructor (`tests/unit/_doubles.py`).
`confiture.core.migrator` re-exports nothing for patching.

**Rationale**: `patch("confiture.core.migrator.create_connection")` at 46 sites
meant the engine's real import path was never exercised and a rename broke every
test at once. A constructor parameter is a documented contract; a patch target is
an accident of module layout.

---

### Decision 14: The native extension hashes files and nothing else

**Choice**: `confiture._core.hash_files` is the only compiled entry point. It
computes byte-for-byte the digest the Python path computes (a parity test holds
it, with `HAS_RUST` patched both ways); an sdist or editable install without a
Rust toolchain runs the Python path and says so once at INFO. Building the
schema is pure Python.

**Rationale**: the Rust builder produced a different schema hash from the Python
builder (per-file digests versus one stream), so a wheel install and a source
install disagreed on whether a template was stale, and a missing file panicked
through the `except Exception` fallback. One function with a parity test is a
contract; a second implementation of the build is not. See Decision 8 for why
the crate is not the start of a port.

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
**Version**: 0.8.10
**Status**: Production-Ready
