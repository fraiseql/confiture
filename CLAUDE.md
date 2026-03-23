# Confiture Development Guide

**Project**: Confiture - PostgreSQL Migrations, Sweetly Done 🍓
**Version**: 0.8.9
**Last Updated**: 2026-03-23
**Current Status**: Beta (Not Yet Production-Tested)

> **⚠️ Important**: This project has comprehensive tests and documentation but has **never been used in production**. All features are implemented but not battle-tested.

---

## 🎯 Project Overview

**Confiture** is a modern PostgreSQL migration tool for Python with a **build-from-scratch philosophy** and **4 migration strategies**. This document guides AI-assisted development.

### Core Philosophy

> **"Build from DDL, not migration history"**

The `db/schema/` directory is the **single source of truth**. Migrations are derived, not primary.

### The Four Mediums

1. **Build from DDL** (`confiture build`) - Fresh databases in <1s
2. **Incremental Migrations** (`confiture migrate up`) - ALTER for simple changes
3. **Production Sync** (`confiture sync`) - Copy data with anonymization
4. **Schema-to-Schema** (`confiture migrate schema-to-schema`) - Zero-downtime via FDW

---

## 📚 Essential Reading

Before coding, read these documents in order:

1. **[PRD.md](./PRD.md)** - Product requirements, user stories, success metrics
2. **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Technical architecture and design decisions
3. **[docs/](./docs/)** - User guides and API documentation

---

## 🏗️ Development Methodology

### TDD Approach

Confiture follows **disciplined TDD cycles**:

```
┌─────────────────────────────────────────────────────────┐
│                    TDD CYCLE                            │
│                                                         │
│ ┌─────────┐  ┌─────────┐  ┌─────────────┐  ┌─────────┐ │
│ │   RED   │─▶│ GREEN   │─▶│  REFACTOR   │─▶│   QA    │ │
│ │ Failing │  │ Minimal │  │ Clean &     │  │ Verify  │ │
│ │ Test    │  │ Code    │  │ Optimize    │  │ Quality │ │
│ └─────────┘  └─────────┘  └─────────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────┘
```

### TDD Discipline

**RED**: Write specific failing test
```bash
uv run pytest tests/unit/test_builder.py::test_build_schema_local -v
# Expected: FAILED (not implemented yet)
```

**GREEN**: Minimal implementation to pass
```bash
uv run pytest tests/unit/test_builder.py::test_build_schema_local -v
# Expected: PASSED (minimal working code)
```

**REFACTOR**: Clean up, optimize
```bash
uv run pytest tests/unit/test_builder.py -v
# All tests still pass after refactoring
```

**QA**: Full validation
```bash
uv run pytest --cov=confiture --cov-report=term-missing
uv run ruff check .
uv run mypy confiture/
```

---

## 🛠️ Technology Stack

### Core Dependencies

```toml
# pyproject.toml dependencies
[project.dependencies]
python = ">=3.11"
typer = ">=0.12"          # CLI framework
pydantic = ">=2.5"        # Configuration validation
pyyaml = ">=6.0"          # YAML parsing
psycopg = {version = ">=3.1", extras = ["binary", "pool"]}  # PostgreSQL driver
rich = ">=13.7"           # Terminal formatting
sqlparse = ">=0.5"        # SQL parsing — fallback when pglast unavailable
sqlglot = ">=28.0"        # SQL dialect-aware parsing (transpilation)
cryptography = ">=42.0"   # Encryption utilities

[project.optional-dependencies]
ast = [
    "pglast>=6.0",         # PostgreSQL's own C parser (libpg_query) — no token limits
]

dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "pytest-json-report>=1.5",
    "ruff>=0.6",
    "ty>=0.0.7",           # Astral's type checker (replaces mypy)
    "maturin>=1.7",
]
```

### SQL Parsing Architecture

`SchemaDiffer` uses a two-tier parsing strategy:

1. **Primary — pglast** (`[ast]` extra, `pip install "fraiseql-confiture[ast]"`):
   Uses PostgreSQL's own C parser via `libpg_query`. No token/recursion limits,
   full PostgreSQL syntax support, handles schemas of any size including bulk seed data.

2. **Fallback — sqlparse**: Used when pglast is not installed. Splits SQL into
   individual statements before parsing (avoids `MAX_GROUPING_TOKENS = 10000` crash)
   and filters to DDL-only, so non-DDL content (INSERT, COPY, GRANT) is ignored.

Both paths share the same regex pass for `CREATE INDEX`, `CREATE TYPE AS ENUM`,
`CREATE SEQUENCE`, and `ALTER TABLE ADD CONSTRAINT`.

### Rust Extension (Optional Performance)

Confiture includes an optional Rust extension for improved performance:

```toml
# Cargo.toml
[dependencies]
pyo3 = "0.22"             # Python bindings
sqlparser = "0.52"        # SQL parsing (Rust)
tokio = "1"               # Async runtime
tokio-postgres = "0.7"    # PostgreSQL driver
sha2 = "0.10"             # Hashing
```

---

## 📁 Project Structure

```
confiture/
├── python/confiture/
│   ├── __init__.py              # Public API (lazy imports via _LAZY_IMPORTS)
│   ├── exceptions.py            # Full exception hierarchy (ConfiturError tree)
│   │
│   ├── cli/
│   │   ├── main.py              # Entry point: app setup + command registration (166 lines)
│   │   ├── helpers.py           # Shared helpers: console, _output_json, _get_tracking_table, etc.
│   │   ├── commands/
│   │   │   ├── schema.py        # init, build, lint, introspect
│   │   │   ├── migrate_core.py  # migrate status/up/down/generate
│   │   │   ├── migrate_state.py # migrate baseline/reinit/rebuild
│   │   │   ├── migrate_analysis.py  # migrate diff/validate/fix/introspect/verify
│   │   │   └── admin.py         # install-helpers, validate_profile, verify, restore
│   │   ├── formatters/
│   │   │   ├── build_formatter.py
│   │   │   ├── migrate_formatter.py
│   │   │   ├── seed_formatter.py
│   │   │   └── common.py
│   │   ├── branch.py            # branch subcommand group (pgGit)
│   │   ├── coordinate.py        # coordinate subcommand group (multi-agent)
│   │   ├── seed.py              # seed subcommand group
│   │   ├── generate.py          # generate subcommand group
│   │   ├── dry_run.py           # Dry-run UI helpers
│   │   └── git_validation.py    # Pre-commit git validation helpers
│   │
│   ├── core/
│   │   ├── builder.py           # SchemaBuilder — Medium 1: build from DDL
│   │   ├── migrator.py          # Migrator + MigratorSession — Medium 2
│   │   ├── differ.py            # SchemaDiffer — schema diff detection
│   │   ├── syncer.py            # Production sync — Medium 3
│   │   ├── schema_to_schema.py  # FDW migration — Medium 4
│   │   ├── migration_generator.py  # Migration file generation (+ external generators)
│   │   ├── migration_verifier.py   # MigrationVerifier + VerifyResult
│   │   ├── grant_accompaniment.py  # GrantAccompanimentChecker
│   │   ├── baseline_detector.py    # BaselineDetector (fuzzy snapshot matching)
│   │   ├── schema_snapshot.py      # SchemaSnapshotGenerator
│   │   ├── introspector.py         # SchemaIntrospector (tables/columns/FKs)
│   │   ├── introspection/          # Phase 6 introspection package
│   │   │   ├── functions.py        # FunctionIntrospector
│   │   │   ├── type_mapping.py     # TypeMapper
│   │   │   ├── dependency_graph.py # DependencyGraph
│   │   │   └── sql_ast.py          # CTENode, JSONBKey
│   │   ├── connection.py        # create_connection, load_config
│   │   ├── error_codes.py       # ErrorCodeDefinition, ErrorCodeRegistry
│   │   ├── linting/             # SchemaLinter and rules
│   │   ├── seed/                # Seed validation system (5 levels)
│   │   ├── seed_validation/     # PrepSeedOrchestrator and validators
│   │   ├── anonymization/       # PII anonymization strategies
│   │   ├── hooks/               # Migration lifecycle hooks
│   │   ├── idempotency/         # Idempotency analysis and fixing
│   │   ├── risk/                # Migration risk assessment
│   │   └── security/            # Security validation
│   │
│   ├── config/
│   │   └── environment.py       # Environment + all nested Pydantic config models
│   │
│   └── models/
│       ├── results.py           # MigrateUpResult, StatusResult, VerifyAllResult, etc.
│       ├── function_info.py     # FunctionParam, FunctionInfo, FunctionCatalog
│       ├── introspection.py     # IntrospectedTable, IntrospectedColumn, FKReference
│       ├── git.py               # MigrationAccompanimentReport, GrantAccompanimentReport
│       ├── lint.py              # LintReport, Violation, LintSeverity
│       ├── error.py             # ErrorSeverity enum
│       ├── migration.py         # Migration base class
│       ├── schema.py            # Schema representation models
│       └── sql_file_migration.py
│
├── tests/
│   ├── unit/                    # Fast, isolated tests (no database required)
│   ├── integration/             # Database-dependent tests
│   ├── e2e/                     # Full CLI workflow tests
│   ├── fixtures/                # SQL fixtures and migration stubs
│   └── conftest.py              # Pytest configuration
│
├── db/
│   ├── schema/                  # Source-of-truth DDL files
│   ├── migrations/              # Migration files (YYYYMMDDHHMMSS_name.up.sql)
│   └── schema_history/          # Schema snapshots after each migration
│
├── docs/
│   ├── guides/                  # User guides per medium and feature
│   ├── reference/               # CLI and configuration reference
│   └── api/                     # API documentation
│
├── .github/
│   └── workflows/
│       ├── quality-gate.yml     # Linting, type checking, unit tests
│       └── release.yml          # Build wheels + publish
│
├── pyproject.toml               # Python packaging (fraiseql-confiture)
├── uv.lock                      # Dependency lock file
├── ARCHITECTURE.md              # This document
├── CLAUDE.md                    # AI-assisted development guide
├── CHANGELOG.md                 # Release notes
└── README.md
```

---

## 🧪 Testing Strategy

### Test Pyramid

```
        ┌─────────────┐
        │     E2E     │  10% - Full workflows
        │   (slow)    │
        ├─────────────┤
        │ Integration │  30% - Database operations
        │  (medium)   │
        ├─────────────┤
        │    Unit     │  60% - Fast, isolated
        │   (fast)    │
        └─────────────┘
```

### Test Categories

**Unit Tests** (60% of tests):
```python
# tests/unit/test_builder.py
def test_find_sql_files():
    """Test file discovery without database"""
    builder = SchemaBuilder(env="test")
    files = builder.find_sql_files()
    assert len(files) > 0
    assert all(f.suffix == ".sql" for f in files)
```

**Integration Tests** (30% of tests):
```python
# tests/integration/test_build_local.py
@pytest.mark.asyncio
async def test_build_creates_database(test_db):
    """Test actual database creation"""
    builder = SchemaBuilder(env="test")
    await builder.build()

    # Verify tables exist
    async with test_db.connection() as conn:
        result = await conn.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'")
        assert result.scalar() > 0
```

**E2E Tests** (10% of tests):
```python
# tests/e2e/test_complete_workflow.py
def test_full_migration_cycle():
    """Test: init -> build -> migrate -> verify"""
    runner = CliRunner()

    # Initialize
    result = runner.invoke(cli, ["init"])
    assert result.exit_code == 0

    # Build
    result = runner.invoke(cli, ["build", "--env", "test"])
    assert result.exit_code == 0

    # Migrate
    result = runner.invoke(cli, ["migrate", "up"])
    assert result.exit_code == 0
```

### Running Tests

```bash
# All tests
uv run pytest

# Unit tests only (fast)
uv run pytest tests/unit/ -v

# Integration tests (requires PostgreSQL)
uv run pytest tests/integration/ -v

# With coverage
uv run pytest --cov=confiture --cov-report=html

# Watch mode (during development)
uv run pytest-watch

# Specific test
uv run pytest tests/unit/test_builder.py::test_find_sql_files -v
```

---

## 🌱 Prep-Seed Validation

Confiture includes a comprehensive **5-level prep-seed validation system** for catching data transformation issues before deployment.

### Overview

The prep-seed pattern transforms UUID-based foreign keys into BIGINT keys using resolution functions. The validation system catches common issues:
- ❌ Seed files targeting wrong schemas (Level 1)
- ❌ Schema mapping mismatches (Level 2)
- ❌ Schema drift in resolution functions (Level 3)
- ❌ Missing tables/columns at runtime (Level 4)
- ❌ NULL FKs and constraint violations after execution (Level 5)

### Quick Usage

```python
from pathlib import Path
from confiture.core.seed_validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)

# Configure validation
config = OrchestrationConfig(
    max_level=5,  # Run all levels
    seeds_dir=Path("db/seeds/prep"),
    schema_dir=Path("db/schema"),
    database_url="postgresql://localhost/test",  # Required for levels 4-5
    level_5_mode="comprehensive",  # Check all constraints
)

# Run validation
orchestrator = PrepSeedOrchestrator(config)
report = orchestrator.run()

# Check results
if report.has_violations:
    for v in report.violations:
        print(f"[{v.severity}] {v.message}")
```

### Validation Levels

| Level | Type | Speed | Use Case | Database |
|-------|------|-------|----------|----------|
| 1 | Seed files | ~1s | Pre-commit | ✗ |
| 2 | Schema consistency | ~2s | Pre-commit | ✗ |
| 3 | Resolution functions | ~3s | Pre-commit | ✗ |
| 4 | Runtime compatibility | ~10s | CI/CD | ✓ |
| 5 | Full execution | ~30s | Integration tests | ✓ |

### Configuration Options

```python
OrchestrationConfig(
    # Required
    max_level: int,              # 1-5: which levels to run
    seeds_dir: Path,             # Location of seed files
    schema_dir: Path,            # Location of schema files

    # Optional
    database_url: str | None = None,      # Required for levels 4-5
    stop_on_critical: bool = True,        # Halt on CRITICAL violations
    show_progress: bool = True,           # Show progress indicators

    # Schema customization
    prep_seed_schema: str = "prep_seed",   # Schema for prep tables
    catalog_schema: str = "catalog",       # Schema for final tables
    tables_to_validate: list[str] | None = None,  # Specific tables
    level_5_mode: str = "standard",       # "standard" or "comprehensive"
)
```

### Example: CI/CD Integration

```bash
#!/bin/bash

# Static validation (no database, ~5s)
python -c "
from pathlib import Path
from confiture.core.seed_validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)

config = OrchestrationConfig(
    max_level=3,
    seeds_dir=Path('db/seeds/prep'),
    schema_dir=Path('db/schema'),
)
orchestrator = PrepSeedOrchestrator(config)
report = orchestrator.run()

if report.has_violations:
    print('❌ Static validation failed')
    exit(1)
"

# Full validation with database (~40s)
python -c "
import os
from pathlib import Path
from confiture.core.seed_validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)

config = OrchestrationConfig(
    max_level=5,
    seeds_dir=Path('db/seeds/prep'),
    schema_dir=Path('db/schema'),
    database_url=os.environ['DATABASE_URL'],
    level_5_mode='comprehensive',
    stop_on_critical=True,
)
orchestrator = PrepSeedOrchestrator(config)
report = orchestrator.run()

# Fail on CRITICAL violations
critical_count = len([v for v in report.violations if v.severity == 'CRITICAL'])
if critical_count > 0:
    print(f'❌ {critical_count} critical violations found')
    exit(1)
"

echo "✅ All seed validation passed"
```

### Testing

Unit tests for the orchestrator:
```bash
uv run pytest tests/unit/seed_validation/prep_seed/test_orchestrator.py -v
```

Integration tests with database:
```bash
uv run pytest tests/integration/test_orchestrator_integration.py -v
```

### See Also

- **[Prep-Seed Validation Guide](./docs/guides/prep-seed-validation.md)** - Comprehensive guide
- **[Example: Prep-Seed Project](./examples/06-prep-seed-validation)** - Working example

---

## 🚀 Development Workflow

### Setting Up

```bash
# Clone repository
git clone https://github.com/evoludigit/confiture.git
cd confiture

# Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv sync --all-extras

# Install pre-commit hooks
uv run pre-commit install

# Verify installation
uv run confiture --version
```

### Daily Development

```bash
# 1. Create feature branch
git checkout -b feature/schema-diff

# 2. Write failing test (RED)
vim tests/unit/test_differ.py
uv run pytest tests/unit/test_differ.py::test_detect_column_rename -v
# Should FAIL

# 3. Implement minimal code (GREEN)
vim python/confiture/core/differ.py
uv run pytest tests/unit/test_differ.py::test_detect_column_rename -v
# Should PASS

# 4. Refactor (REFACTOR)
vim python/confiture/core/differ.py
uv run pytest tests/unit/test_differ.py -v
# All tests still pass

# 5. Quality checks (QA)
uv run ruff check .
uv run mypy python/confiture/
uv run pytest --cov=confiture

# 6. Commit (pre-commit hooks run automatically)
git add .
git commit -m "feat: detect column rename in schema diff"

# 7. Push and create PR
git push origin feature/schema-diff
```

---

## 🎨 Code Style

### Python Style Guide

Follow **PEP 8** with these additions:

```python
# Good: Descriptive names
def build_schema_from_ddl_files(env: str) -> str:
    """Build schema by concatenating DDL files for given environment."""
    ...

# Bad: Vague names
def build(e: str) -> str:
    ...

# Good: Type hints everywhere
def find_sql_files(self, directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.sql"))

# Bad: No type hints
def find_sql_files(self, directory):
    return sorted(directory.rglob("*.sql"))

# Good: Docstrings (Google style)
def migrate_up(self, target: str | None = None) -> None:
    """Apply pending migrations up to target version.

    Args:
        target: Target migration version. If None, applies all pending.

    Raises:
        MigrationError: If migration fails.

    Example:
        >>> migrator = Migrator(env="production")
        >>> migrator.migrate_up(target="003_add_user_bio")
    """
    ...
```

### Formatting

```bash
# Auto-format with ruff
uv run ruff format .

# Check code
uv run ruff check .

# Type checking (using Astral's ty type checker)
uv run ty check python/confiture/
```

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

Note: Type checking is handled by Astral's `ty` in CI/CD (see quality-gate.yml).
For local type checking, run: `uv run ty check python/confiture/`

---

## 🐛 Debugging

### pytest Debugging

```bash
# Run test with print statements
uv run pytest tests/unit/test_builder.py::test_find_sql_files -v -s

# Drop into debugger on failure
uv run pytest --pdb

# Run specific test with debugging
uv run pytest tests/unit/test_builder.py::test_find_sql_files --pdb -v
```

### Database Debugging

```bash
# Connect to test database
psql postgresql://localhost/confiture_test

# Check applied migrations
SELECT * FROM confiture_migrations ORDER BY applied_at DESC;

# Check schema version
SELECT * FROM confiture_version;
```

---

## 📝 Documentation

### Docstring Format (Google Style)

```python
def build_schema(env: str, output_path: Path | None = None) -> str:
    """Build schema by concatenating DDL files for given environment.

    This function reads all SQL files from db/schema/ directory in
    deterministic order and concatenates them into a single schema file.

    Args:
        env: Environment name (e.g., "local", "production").
        output_path: Optional custom output path. If None, uses
            db/generated/schema_{env}.sql.

    Returns:
        Generated schema content as string.

    Raises:
        FileNotFoundError: If schema directory doesn't exist.
        ConfigurationError: If environment config is invalid.

    Example:
        >>> builder = SchemaBuilder(env="local")
        >>> schema = builder.build_schema("local")
        >>> print(len(schema))
        15234

    Note:
        Files are processed in alphabetical order. Use numbered
        directories (00_common/, 10_tables/) to control order.
    """
    ...
```

### README Updates

When adding features, update README.md:

```markdown
## Features

- ✅ Build from DDL (Medium 1)
- ✅ Incremental migrations (Medium 2)
- ✅ Schema diff detection (NEW!)
- ⏳ Production sync (Medium 3) - Coming soon
- ⏳ Zero-downtime migrations (Medium 4) - Coming soon
```

---

## 🔒 Security

### Sensitive Data

**Never commit**:
- Database credentials (use environment variables)
- `.env` files
- Production data dumps
- API keys

**Always**:
- Use `psycopg3` parameterized queries (SQL injection prevention)
- Validate user input (file paths, environment names)
- Anonymize PII in production sync

```python
# Good: Parameterized query
cursor.execute(
    "SELECT * FROM users WHERE email = %s",
    (user_email,)
)

# Bad: String interpolation (SQL injection risk!)
cursor.execute(f"SELECT * FROM users WHERE email = '{user_email}'")
```

---

## 🤝 Contributing

### Branch Naming

```
feature/schema-diff          # New feature
fix/migration-rollback-bug   # Bug fix
docs/zero-downtime-guide     # Documentation
refactor/builder-cleanup     # Refactoring
test/integration-coverage    # Test improvements
```

### Commit Messages

Follow **Conventional Commits**:

```
feat: add schema diff detection
fix: correct column type mapping in differ
docs: update migration strategies guide
test: add integration tests for schema builder
refactor: simplify file discovery logic
perf: optimize hash computation for large files
```

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [x] New feature
- [ ] Breaking change
- [ ] Documentation

## Checklist
- [x] Tests pass (`uv run pytest`)
- [x] Code formatted (`uv run ruff format`)
- [x] Type checking passes (`uv run ty check python/confiture/`)
- [x] Documentation updated
- [x] PHASES.md updated (if applicable)

## Testing
Describe testing performed

## Related Issues
Closes #123
```

---

## 🎯 Current Status

### Beta (v0.8.9)

> **⚠️ Not Production-Tested**: All features below are implemented and have passing tests, but have never been used in a real production environment.

**Implemented Features**:
- ✅ Schema builder (Medium 1) - Build from DDL
- ✅ Migration system (Medium 2) - Incremental migrations with dry-run
- ✅ Production sync (Medium 3) - Copy data with PII anonymization
- ✅ Zero-downtime migrations (Medium 4) - Schema-to-schema via FDW
- ✅ Schema diff detection — pglast primary parser, sqlparse fallback
- ✅ Large-schema support — schemas with bulk seed data parse without token-limit crash
- ✅ Prep-seed validation - 5-level validation orchestrator with full Level 4-5 support
- ✅ CLI with rich terminal output
- ✅ Migration hooks
- ✅ Schema linting
- ✅ Anonymization strategies
- ✅ Timestamp-based migration versioning (YYYYMMDDHHMMSS)
- ✅ Exception hierarchy with error codes and resolution hints
- ✅ Library API: `Migrator.from_config()` + `MigratorSession` context manager
- ✅ Introspection layer: `FunctionIntrospector`, `TypeMapper`, `DependencyGraph`
- ✅ Grant accompaniment checker (detect grant changes without migration)
- ✅ Migration verifier (`.verify.sql` post-migration queries)
- ✅ `migrate rebuild` command
- ✅ Semantic exit codes for `migrate status`
- ✅ JSON/CSV/YAML structured output for all commands

**Test Metrics**:
- **Unit tests passing**: 4,420+
- **Python Support**: 3.11, 3.12, 3.13
- **Documentation**: Comprehensive with guides and API references

**Not Validated**:
- ❌ Production usage
- ❌ Real-world performance claims
- ❌ Edge case handling under load
- ❌ Failure recovery scenarios

---

## 🚨 Common Pitfalls

### ❌ Don't: Mix business logic with CLI
```python
# Bad: Business logic in CLI
@app.command()
def build(env: str):
    files = sorted(Path("db/schema").rglob("*.sql"))  # Logic in CLI!
    schema = "".join(f.read_text() for f in files)
```

### ✅ Do: Separate concerns
```python
# Good: CLI calls core logic
@app.command()
def build(env: str):
    builder = SchemaBuilder(env=env)  # Core logic
    builder.build()                    # Delegate
```

---

### ❌ Don't: Skip type hints
```python
# Bad
def build_schema(env):
    return schema
```

### ✅ Do: Add complete type hints
```python
# Good
def build_schema(env: str) -> str:
    return schema
```

---

### ❌ Don't: Use bare except
```python
# Bad
try:
    conn.execute(sql)
except:  # What error? Why?
    pass
```

### ✅ Do: Catch specific exceptions
```python
# Good
try:
    conn.execute(sql)
except psycopg.OperationalError as e:
    raise MigrationError(f"Database connection failed: {e}") from e
```

---

## 📊 Implementation Metrics

- ✅ **Tests**: 4,420+ unit passing (2026-03-23)
- ✅ **CLI Commands**: 20+ implemented across schema, migrate, admin, seed, branch, coordinate, generate subgroups
- ✅ **Documentation**: Comprehensive guides + API references
- ✅ **Validation System**: 5-level prep-seed orchestrator with full database support
- ✅ **CI/CD**: Multi-platform wheel building, quality gates (ruff + ty + pytest)
- ✅ **Python Support**: 3.11, 3.12, 3.13 tested
- ✅ **Library API**: `Migrator.from_config()` + `MigratorSession` context manager
- ✅ **Introspection layer**: `FunctionIntrospector`, `TypeMapper`, `DependencyGraph`
- ✅ **Structured error hierarchy**: `ConfiturError` + error codes + exit codes
- ✅ **Structured output**: JSON/CSV/YAML for all major commands

**Not Yet Measured in Production**:
- ❓ Actual build speed under real conditions
- ❓ Reliability over time
- ❓ Validation performance at scale
- ❓ Sequential seed execution at scale (>1M rows)

---

## 🆘 Getting Help

### Resources

- **Project Docs**: `docs/`
- **API Reference**: `docs/api/`
- **Examples**: `examples/`

### Questions to Ask

When stuck, ask:
1. "What test should I write first?" (RED)
2. "What's the simplest code to make this pass?" (GREEN)
3. "How can I improve this without breaking tests?" (REFACTOR)
4. "Does this meet quality standards?" (QA)

---

## 🎉 Philosophy

> **"Make it work, make it right, make it fast - in that order."**

1. **Make it work**: Write failing test, minimal implementation
2. **Make it right**: Refactor, clean code, documentation
3. **Make it fast**: Optimize with Rust extension when needed

**Always follow TDD cycles. Always.**

---

**Last Updated**: 2026-03-23
**Version**: 0.8.9 (Not Production-Tested)

---

*Making jam from strawberries, one commit at a time.* 🍓→🍯
