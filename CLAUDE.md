# Confiture Development Guide

**Project**: Confiture - PostgreSQL Migrations, Sweetly Done 🍓
**Version**: 0.3.4
**Last Updated**: January 2026
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
pydantic = ">=2.0"        # Configuration validation
pyyaml = ">=6.0"          # YAML parsing
psycopg = {version = ">=3.0", extras = ["binary"]}  # PostgreSQL driver
rich = ">=13.0"           # Terminal formatting
sqlparse = ">=0.5"        # SQL parsing (Python)

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "ruff>=0.6",
    "mypy>=1.11",
    "pre-commit>=3.0",
]
```

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
│   ├── __init__.py              # Public API
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py              # Entry point (Typer app)
│   │   ├── build.py             # confiture build
│   │   ├── migrate.py           # confiture migrate
│   │   └── sync.py              # confiture sync
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── builder.py           # Schema builder (Medium 1)
│   │   ├── migrator.py          # Migration executor (Medium 2)
│   │   ├── differ.py            # Schema diff detector
│   │   ├── syncer.py            # Production sync (Medium 3)
│   │   └── schema_to_schema.py  # FDW migration (Medium 4)
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── environment.py       # Environment config
│   │   └── version.py           # Version tracking
│   │
│   └── models/
│       ├── __init__.py
│       ├── migration.py         # Migration base class
│       └── schema.py            # Schema models
│
├── tests/
│   ├── unit/                    # Fast, isolated tests
│   │   ├── test_builder.py
│   │   ├── test_migrator.py
│   │   ├── test_differ.py
│   │   └── test_config.py
│   │
│   ├── integration/             # Database-dependent tests
│   │   ├── test_build_local.py
│   │   ├── test_migrate_up.py
│   │   └── test_sync.py
│   │
│   ├── e2e/                     # Full workflow tests
│   │   └── test_complete_workflow.py
│   │
│   ├── fixtures/                # Test data
│   │   ├── schemas/
│   │   └── migrations/
│   │
│   └── conftest.py              # Pytest config
│
├── docs/
│   ├── index.md                 # Documentation homepage
│   ├── getting-started.md
│   ├── guides/                 # User guides
│   │   ├── medium-1-build-from-ddl.md
│   │   ├── medium-2-incremental-migrations.md
│   │   ├── medium-3-production-sync.md
│   │   ├── medium-4-schema-to-schema.md
│   │   └── migration-decision-tree.md
│   ├── reference/              # API/CLI reference
│   │   ├── cli.md
│   │   └── configuration.md
│   └── api/                    # API documentation
│       ├── builder.md
│       ├── migrator.md
│       ├── syncer.md
│       └── schema-to-schema.md
│
├── examples/
│   ├── basic/                   # Simple example
│   ├── fraiseql/                # FraiseQL integration
│   └── zero-downtime/           # Production migration
│
├── .github/
│   └── workflows/
│       ├── ci.yml               # Run tests
│       └── release.yml          # Build wheels
│
├── pyproject.toml               # Python packaging
├── uv.lock                      # Dependency lock file
├── .python-version              # Python 3.11
├── .gitignore
├── README.md
├── PRD.md
├── CLAUDE.md                    # This file
├── PHASES.md
└── LICENSE
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

### Beta (v0.3.4)

> **⚠️ Not Production-Tested**: All features below are implemented and have passing tests, but have never been used in a real production environment.

**Implemented Features**:
- ✅ Schema builder (Medium 1) - Build from DDL
- ✅ Migration system (Medium 2) - Incremental migrations with dry-run
- ✅ Production sync (Medium 3) - Copy data with PII anonymization
- ✅ Zero-downtime migrations (Medium 4) - Schema-to-schema via FDW
- ✅ Schema diff detection
- ✅ CLI with rich terminal output
- ✅ Migration hooks
- ✅ Schema linting
- ✅ Anonymization strategies

**Test Metrics**:
- **Tests**: 3,200+ passing
- **Python Support**: 3.11, 3.12, 3.13
- **Documentation**: Comprehensive

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

- ✅ **Test Coverage**: 3,200+ tests passing
- ✅ **CLI Commands**: 8 implemented (`build`, `migrate up/down`, `status`, `init`, `sync`, `schema-to-schema`)
- ✅ **Documentation**: Comprehensive guides + API references
- ✅ **Examples**: 5 example scenarios
- ✅ **CI/CD**: Multi-platform wheel building, quality gates
- ✅ **Python Support**: 3.11, 3.12, 3.13 tested

**Not Yet Measured in Production**:
- ❓ Actual build speed under real conditions
- ❓ Rust extension performance gains
- ❓ Reliability over time

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

**Last Updated**: January 2026
**Version**: 0.3.4 (Not Production-Tested)

---

*Making jam from strawberries, one commit at a time.* 🍓→🍯
