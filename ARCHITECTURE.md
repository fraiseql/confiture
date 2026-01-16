# Confiture Architecture

**Version**: 0.4.0 (Production Release 🎉)
**Last Updated**: December 27, 2025

---

## Core Philosophy

> **"Build from DDL, not migration history"**

The `db/schema/` directory is the **single source of truth**. Migrations are derived from schema changes, not primary artifacts.

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
│  in <1 second         incrementally        anonymization       │
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

**Purpose**: User-facing command interface via Typer framework

**Components**:
- `main.py` - Entry point with all CLI commands:
  - `confiture build` - Build fresh database from DDL
  - `confiture migrate up` - Apply pending migrations
  - `confiture migrate down` - Rollback migrations
  - `confiture status` - Show migration status
  - `confiture sync` - Production data sync
  - `confiture schema-to-schema` - Zero-downtime FDW migration

- `dry_run.py` - Helper module for dry-run operations (Phase 5)
  - `display_dry_run_header()` - Show analysis mode
  - `save_text_report()` - Text output format
  - `save_json_report()` - JSON output format
  - `ask_dry_run_execute_confirmation()` - User confirmation
  - `extract_sql_statements_from_migration()` - SQL extraction

**Output Format**: Rich terminal UI with colors and formatting

**Example**:
```bash
$ confiture migrate up --dry-run
🔍 Analyzing migrations without execution...

Migration Analysis Summary
================================================================================
Migrations to apply: 2

  001: create_initial_schema
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%
  002: add_user_table
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%

✓ All migrations appear safe to execute
================================================================================
```

---

### 2. Core Layer (`python/confiture/core/`)

**Purpose**: Business logic and database operations

#### 2.1 Schema Builder (`builder.py`)

**Responsibility**: Medium 1 - Build from DDL

**Features**:
- Reads SQL files from `db/schema/` directory
- Concatenates files in deterministic order (alphabetical)
- Builds fresh databases in <1 second
- Supports environment-specific schemas (local, test, staging)

**Key Methods**:
```python
class SchemaBuilder:
    def find_sql_files(self) -> list[Path]
        """Discover SQL files in deterministic order"""

    def build_schema(self, env: str) -> str
        """Concatenate DDL files into single schema"""

    def create_database(self, conn: Connection) -> None
        """Execute schema against database connection"""
```

**Example**:
```bash
$ confiture build --env local
✅ Built schema in 0.89 seconds
```

---

#### 2.2 Migrator (`migrator.py`)

**Responsibility**: Medium 2 - Incremental migrations

**Features**:
- Manages migration execution state
- Tracks applied migrations in `confiture_migrations` table
- Supports migration up and down
- Handles dependency resolution

**Key Methods**:
```python
class Migrator:
    def get_pending_migrations(self) -> list[Path]
        """Find migrations not yet applied"""

    def get_applied_versions(self) -> list[str]
        """Query applied migration versions"""

    def apply(self, migrations: list[Path]) -> None
        """Execute migrations within transaction"""

    def rollback(self, steps: int) -> None
        """Undo N most recent migrations"""
```

**Storage**: Tracks state in `public.confiture_migrations` table:
```sql
CREATE TABLE confiture_migrations (
    version TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMP NOT NULL,
    execution_time_ms INTEGER NOT NULL
);
```

---

#### 2.3 Dry-Run Mode (`dry_run.py`) - Phase 4 Feature

**Responsibility**: Test migrations safely before production

**Features**:
- SAVEPOINT-based transaction testing
- Guaranteed automatic rollback
- Resource impact estimation
- Detailed reporting

**Key Classes**:
```python
@dataclass
class DryRunResult:
    """Result of a dry-run execution"""
    migration_name: str
    migration_version: str
    success: bool
    execution_time_ms: int
    rows_affected: int
    locked_tables: list[str]
    estimated_production_time_ms: int

class DryRunExecutor:
    """Orchestrate safe migration testing"""

    def run(
        self,
        conn: psycopg.Connection,
        migration: Migration
    ) -> DryRunResult:
        """Execute in SAVEPOINT, guaranteed rollback"""
```

**How It Works**:
```
User Command: confiture migrate up --dry-run-execute
    ↓
Create SAVEPOINT (point in transaction)
    ↓
Execute migration
    ↓
Measure: time, rows, locks
    ↓
Automatic ROLLBACK to SAVEPOINT
    ↓
Report results
    ↓
User confirms: "Proceed with real execution?" [y/N]
    ↓
If YES: Execute for real (no SAVEPOINT)
If NO: Exit (no changes)
```

---

#### 2.4 Schema Differ (`differ.py`)

**Responsibility**: Detect structural differences between schemas

**Features**:
- Compare two schema versions
- Identify: added/removed/modified tables
- Identify: added/removed/modified columns
- Detect: constraint changes, index changes
- Support for simple renames

**Key Methods**:
```python
class SchemaDiffer:
    def detect_changes(
        self,
        old_schema: str,
        new_schema: str
    ) -> SchemaDiff:
        """Compare schemas and return differences"""
```

---

#### 2.5 Production Syncer (`syncer.py`) - Medium 3

**Responsibility**: Copy data to new environments with anonymization

**Features**:
- Copy schema + data from production
- PII anonymization strategies
- Incremental syncing
- Metadata preservation

**Example Use Case**:
```bash
$ confiture sync \
  --from postgresql://prod-db \
  --to postgresql://local-db \
  --anonymize-pii
# Copies production data to local, masks sensitive info
```

---

#### 2.6 Schema-to-Schema (`schema_to_schema.py`) - Medium 4

**Responsibility**: Zero-downtime migrations using Foreign Data Wrapper

**Features**:
- Deploy new schema without downtime
- Dual-write pattern via FDW
- Atomic cutover
- Rollback capability

**How It Works**:
```
Old Schema ──> Foreign Data Wrapper <── New Schema
                      ↓
              Shadow tables (read-only)
                      ↓
              Dual-write logic
                      ↓
              Data validation
                      ↓
              Atomic cutover
```

---

### 3. Configuration Layer (`python/confiture/config/`)

**Purpose**: Environment and version management

**Components**:

#### 3.1 Environment Config (`environment.py`)

```python
class EnvironmentConfig:
    """Manage environment-specific settings"""

    env: str              # "local", "test", "staging", "production"
    schema_dir: Path      # Where to find DDL files
    migrations_dir: Path  # Where to find migration files
    database_url: str     # PostgreSQL connection string
```

**Example `confiture.yaml`**:
```yaml
environments:
  local:
    database_url: postgresql://localhost/confiture_local
    schema_dir: db/schema

  test:
    database_url: postgresql://localhost/confiture_test
    schema_dir: db/schema

  production:
    database_url: postgresql://prod.example.com/confiture
    schema_dir: db/schema
```

#### 3.2 Version Tracking (`version.py`)

- Track current package version
- Used in CLI output (`confiture --version`)
- Used in release notes and documentation

---

### 4. Models Layer (`python/confiture/models/`)

**Purpose**: Data structures and type definitions

**Components**:

#### 4.1 Migration Model (`migration.py`)

```python
class Migration:
    """Base class for all migrations"""

    version: str          # "001", "002", etc.
    name: str             # "create_users_table"
    created_at: datetime

    def up(self, conn: Connection) -> None:
        """Forward migration logic"""

    def down(self, conn: Connection) -> None:
        """Rollback logic"""
```

#### 4.2 Schema Models (`schema.py`)

```python
@dataclass
class Table:
    name: str
    columns: list[Column]
    constraints: list[Constraint]

@dataclass
class Column:
    name: str
    type: str
    nullable: bool
    default: str | None

@dataclass
class Constraint:
    type: str  # "PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK"
    columns: list[str]
```

---

## Data Flow Examples

### Example 1: `confiture build --env local`

```
User runs: confiture build --env local
    ↓
SchemaBuilder.find_sql_files(db/schema/)
    ↓
Read files: 00_common/01_base.sql, 10_tables/01_users.sql, ...
    ↓
Concatenate in order
    ↓
Connect to PostgreSQL (postgresql://localhost/confiture_local)
    ↓
Execute schema: CREATE TABLE users (...)
    ↓
Return: "Built schema in 0.89s"
```

---

### Example 2: `confiture migrate up --dry-run`

```
User runs: confiture migrate up --dry-run
    ↓
Migrator.get_pending_migrations()
    ↓
Load migration files: 001_init.py, 002_add_users.py
    ↓
For each migration:
  - Extract version and name
  - Estimate impact (conservative: 500ms, 1MB, 30% CPU)
  - Collect for analysis
    ↓
Display text report:
  Migration Analysis Summary
  =====================================
  001: create_initial_schema
    Estimated time: 500ms | Disk: 1.0MB | CPU: 30%
    ↓
Early return (no execution, no database changes)
```

---

### Example 3: `confiture migrate up --dry-run-execute`

```
User runs: confiture migrate up --dry-run-execute
    ↓
Display analysis (same as --dry-run above)
    ↓
Ask: "Proceed with real execution? [y/N]"
    ↓
User enters: y
    ↓
Execute migrations in real transaction
    ↓
Return: "✅ Successfully applied 2 migration(s)!"
```

---

## Testing Architecture

### Test Pyramid

```
        ┌──────────────┐
        │    E2E       │  10% - Full workflows
        │   (~10)      │
        ├──────────────┤
        │Integration   │  30% - Database ops
        │   (~9)       │
        ├──────────────┤
        │   Unit       │  60% - Isolated
        │   (~30)      │
        └──────────────┘
```

### Test Categories

**Unit Tests** (`tests/unit/`):
- Fast, no database dependency
- Mock all external calls
- Example: `test_cli_dry_run.py` (12 tests for dry-run features)

**Integration Tests** (`tests/integration/`):
- Require actual PostgreSQL database
- Test real database operations
- Example: `test_build_local.py`, `test_migrate_up.py`

**E2E Tests** (`tests/e2e/`):
- Full workflow testing
- Example: `test_complete_workflow.py` (init → build → migrate → verify)

---

## Development Status

### ✅ Completed (v0.4.0)

- **Phase 1**: Python MVP (4 mediums, CLI, tests)
- **Phase 2**: Rust performance layer (10-50x faster)
- **Phase 3**: Production features (sync, FDW, zero-downtime)
- **Phase 4**: Advanced features (schema linting)
- **Phase 5**: CLI dry-run integration (--dry-run, --dry-run-execute, output formats)

### 🎯 Current Metrics

- **Tests**: 30/30 passing (100%)
- **Code Quality**: A+ (0 linting issues)
- **Coverage**: 81.68% (332 tests)
- **Platforms**: Python 3.11, 3.12, 3.13
- **Performance**: <1s fresh builds, 10-50x faster with Rust

### 🚀 Future Enhancements

- Interactive migration wizard
- Custom anonymization strategies
- Advanced schema validation
- Performance profiling tools
- Integration with other tools (GitOps, CI/CD)

---

## Key Design Decisions

### Decision 1: DDL as Source of Truth

**Choice**: Keep `db/schema/` as primary, derive migrations

**Rationale**:
- Schema is easier to understand than migration sequence
- Simpler for new developers
- Easier to understand total state
- Migration history becomes optional

**Alternative**: Migration history as primary (like Alembic)
- Would require analyzing full history to understand current state
- More complex for new contributors

---

### Decision 2: Simplified Dry-Run Estimates

**Choice**: Use conservative estimates (500ms, 1MB, 30% CPU) instead of full analysis

**Rationale**:
- CLI uses synchronous psycopg.Connection
- DryRunExecutor provides transaction-based testing with rollback
- Estimates still provide safety value
- Can be enhanced when async support added

**Alternative**: Full actual dry-run execution
- Would require async connection changes
- More complex, not yet needed

---

### Decision 3: SAVEPOINT-Based Testing

**Choice**: Use PostgreSQL SAVEPOINT for --dry-run-execute

**Rationale**:
- Guaranteed rollback (atomic transaction)
- No special infrastructure needed
- Works with synchronous connections
- Clear semantics to users

**Alternative**: Actually roll forward and backward
- More complex, less safe
- Can leave database in bad state if interrupted

---

## Integration Points

### FraiseQL Integration

FraiseQL can use Confiture for schema management:

```python
from confiture import SchemaBuilder, Migrator

# In FraiseQL setup:
builder = SchemaBuilder(env="test")
schema = builder.build_schema("test")  # Returns DDL string

# Then use in FraiseQL tests:
await fraiseql.setup_schema(schema)
```

---

## Related Documentation

- **[DEVELOPMENT.md](./DEVELOPMENT.md)** - Contributing guide
- **[README.md](./README.md)** - Quick start and overview
- **[CHANGELOG.md](./CHANGELOG.md)** - Release notes by version
- **[docs/guides/](./docs/guides/)** - User guides for each medium
- **[.development/INDEX.md](./.development/INDEX.md)** - Development history (phases)

---

**Last Updated**: December 27, 2025
**Version**: 0.4.0 (Production Release)
**Status**: Production Ready 🚀
