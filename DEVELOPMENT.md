# Development Guide

**Confiture - PostgreSQL Migrations, Sweetly Done** 🍓

This guide explains how to set up your development environment and contribute to Confiture.

---

## Quick Start

### Prerequisites

- **Python**: 3.11, 3.12, or 3.13
- **PostgreSQL**: 12.0 or later (for running tests)
- **uv**: Python package manager (see [installation](https://docs.astral.sh/uv/))

### Installation

```bash
# Clone repository
git clone https://github.com/evoludigit/confiture.git
cd confiture

# Install uv (macOS/Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv sync --all-extras

# Install pre-commit hooks (optional but recommended)
uv run pre-commit install

# Verify installation
uv run confiture --version
```

---

## Understanding the Project

Before making changes, understand Confiture's architecture:

1. **[README.md](./README.md)** - Quick overview and features
2. **[ARCHITECTURE.md](./ARCHITECTURE.md)** - System design and components
3. **[CLAUDE.md](./CLAUDE.md)** - Development standards and philosophy

### Key Concepts

**Four Mediums** (different ways to migrate):
1. **Build from DDL** - Create fresh database in <1 second
2. **Incremental Migrations** - Apply changes step-by-step
3. **Production Sync** - Copy data with anonymization
4. **Schema-to-Schema** - Zero-downtime migrations via FDW

**Single Source of Truth**: `db/schema/` directory contains all DDL files

---

## Development Workflow

### 1. Create Feature Branch

```bash
git checkout -b feature/your-feature-name

# Branch naming conventions:
# - feature/schema-diff     # New feature
# - fix/migration-bug       # Bug fix
# - docs/contributing-guide # Documentation
# - test/coverage           # Test improvements
```

### 2. Make Changes (Follow TDD)

Confiture follows **Test-Driven Development** with 4 phases:

#### Phase 1: RED - Write Failing Test

```bash
# Create test file or add to existing
vim tests/unit/test_my_feature.py

# Write test that demonstrates missing feature
def test_detect_column_rename():
    """Test that we can detect column rename operations"""
    old = "CREATE TABLE users (id INT, name VARCHAR);"
    new = "CREATE TABLE users (id INT, full_name VARCHAR);"

    differ = SchemaDiffer()
    changes = differ.detect_changes(old, new)

    assert any(c.type == "column_renamed" for c in changes)

# Run test - should FAIL
uv run pytest tests/unit/test_my_feature.py::test_detect_column_rename -v
# Expected: FAILED (not implemented yet)
```

#### Phase 2: GREEN - Minimal Implementation

```bash
# Implement minimal code to make test pass
vim python/confiture/core/differ.py

# Add minimal implementation
def detect_changes(self, old_schema, new_schema):
    # Minimal logic to pass test
    return [Change(type="column_renamed")]

# Run test - should PASS
uv run pytest tests/unit/test_my_feature.py::test_detect_column_rename -v
# Expected: PASSED
```

#### Phase 3: REFACTOR - Clean Code

```bash
# Clean up implementation (without changing behavior)
vim python/confiture/core/differ.py

# Refactor for clarity
def detect_changes(self, old_schema: str, new_schema: str) -> list[Change]:
    """Detect differences between two schemas."""
    old_tables = self._parse_schema(old_schema)
    new_tables = self._parse_schema(new_schema)

    changes = []
    for table_name in set(old_tables.keys()) | set(new_tables.keys()):
        old_table = old_tables.get(table_name)
        new_table = new_tables.get(table_name)

        if old_table and new_table:
            changes.extend(self._detect_column_changes(old_table, new_table))
        # ... more logic

    return changes

# All tests still pass
uv run pytest tests/unit/ -v
# Expected: All tests PASSED
```

#### Phase 4: QA - Quality Checks

```bash
# Run full test suite
uv run pytest --cov=confiture --cov-report=term-missing

# Check code style
uv run ruff check .
uv run ruff format .

# Type checking
uv run ty check python/confiture/

# Pre-commit hooks (if installed)
uv run pre-commit run --all-files
```

### 3. Commit Changes

```bash
# Stage changes
git add .

# Commit with conventional commit message
git commit -m "feat: detect column rename in schema diff

- Implement SchemaDiffer.detect_changes() method
- Add test coverage for rename detection
- Handle ALTER COLUMN RENAME operations
- Preserve backwards compatibility"

# Pre-commit hooks run automatically (if installed)
```

### 4. Push and Create Pull Request

```bash
# Push to remote
git push origin feature/your-feature-name

# Create PR on GitHub
gh pr create --title "feat: detect column rename" \
  --body "## Description\nImplements automatic detection of column renames in schema diffing"
```

---

## Running Tests

### All Tests

```bash
# Run entire test suite
uv run pytest

# Run with coverage report
uv run pytest --cov=confiture --cov-report=html
# Open htmlcov/index.html in browser
```

### Specific Tests

```bash
# Run single test file
uv run pytest tests/unit/test_differ.py -v

# Run single test function
uv run pytest tests/unit/test_differ.py::test_detect_column_rename -v

# Run tests matching pattern
uv run pytest -k "rename" -v

# Run with debugging
uv run pytest --pdb -v

# Run with output (print statements visible)
uv run pytest -s -v
```

### Test Categories

```bash
# Unit tests only (fast, no database needed)
uv run pytest tests/unit/ -v

# Integration tests (requires PostgreSQL)
uv run pytest tests/integration/ -v

# E2E tests (full workflows)
uv run pytest tests/e2e/ -v
```

---

## Code Style

### Python Style

Follow **PEP 8** with these additions:

```python
# Good: Descriptive names
def detect_column_rename(
    self,
    old_table: Table,
    new_table: Table
) -> list[ColumnRename]:
    """Detect if column was renamed between two table versions."""
    # ... implementation

# Bad: Vague names
def detect_rename(self, old, new):
    # ...

# Good: Type hints everywhere
def apply(self, migrations: list[Path]) -> None:
    """Apply migrations in transaction."""
    # ...

# Bad: No type hints
def apply(self, migrations):
    # ...
```

### Docstring Format

Use **Google-style docstrings**:

```python
def find_sql_files(self, directory: Path) -> list[Path]:
    """Find all SQL files in directory in deterministic order.

    Searches recursively for files ending in .sql and returns them
    sorted alphabetically to ensure reproducible builds.

    Args:
        directory: Directory to search for SQL files.

    Returns:
        List of Path objects for found SQL files, sorted.

    Raises:
        FileNotFoundError: If directory doesn't exist.

    Example:
        >>> builder = SchemaBuilder(env="local")
        >>> files = builder.find_sql_files(Path("db/schema"))
        >>> print(len(files))
        12
    """
```

### Formatting

```bash
# Auto-format code
uv run ruff format .

# Check code style
uv run ruff check .
uv run ruff check . --fix  # Auto-fix issues

# Type checking
uv run ty check python/confiture/
```

---

## Project Structure

```
confiture/
├── python/confiture/          # Main package
│   ├── cli/                   # Command-line interface
│   │   ├── main.py           # Typer app entry point
│   │   └── dry_run.py        # Phase 5: dry-run helpers
│   │
│   ├── core/                  # Business logic
│   │   ├── builder.py        # Medium 1: build from DDL
│   │   ├── migrator.py       # Medium 2: incremental migrations
│   │   ├── differ.py         # Schema diff detection
│   │   ├── dry_run.py        # Phase 4: test migrations safely
│   │   ├── syncer.py         # Medium 3: production sync
│   │   └── schema_to_schema.py # Medium 4: zero-downtime FDW
│   │
│   ├── config/                # Configuration management
│   ├── models/                # Data types
│   └── __init__.py
│
├── tests/                     # Test suite
│   ├── unit/                 # Fast, isolated tests
│   ├── integration/          # Database-dependent tests
│   ├── e2e/                  # Full workflow tests
│   ├── fixtures/             # Test data
│   └── conftest.py
│
├── docs/                      # Documentation
│   ├── guides/               # User guides for each medium
│   ├── api/                  # API reference
│   ├── reference/            # Configuration reference
│   └── release-notes/        # Version-specific notes
│
├── ARCHITECTURE.md           # System design
├── DEVELOPMENT.md            # This file
├── CLAUDE.md                 # Development standards
├── README.md                 # Quick start
├── CHANGELOG.md              # Release notes
└── pyproject.toml            # Python packaging
```

---

## Common Tasks

### Add a New Feature

1. **Understand the architecture**: Read [ARCHITECTURE.md](./ARCHITECTURE.md)
2. **Find the right module**: Features go in `core/` unless CLI-specific
3. **Write failing test** first (RED phase)
4. **Implement minimal code** (GREEN phase)
5. **Refactor and clean up** (REFACTOR phase)
6. **Run quality checks** (QA phase)
7. **Commit with conventional message**

### Fix a Bug

1. **Write a test** that reproduces the bug (should fail)
2. **Fix the bug** (make test pass)
3. **Run all tests** to ensure no regressions
4. **Commit with conventional message** (`fix: ...`)

### Update Documentation

1. **Identify which doc** needs updating:
   - User guides: `docs/guides/`
   - API reference: `docs/api/`
   - Architecture: `ARCHITECTURE.md`
   - Contributing: `DEVELOPMENT.md`

2. **Make changes** and review formatting

3. **Commit with conventional message** (`docs: ...`)

### Add a Test

Tests should follow the **pyramid pattern**:
- 60% unit tests (fast, no database)
- 30% integration tests (with database)
- 10% E2E tests (full workflows)

```bash
# Create test file
vim tests/unit/test_new_feature.py

# Import test utilities
from unittest.mock import Mock, patch
import pytest

# Write tests
def test_feature_works():
    """Test the new feature."""
    result = my_function(input_data)
    assert result == expected_output

# Run test
uv run pytest tests/unit/test_new_feature.py -v
```

---

## Debugging

### Using pytest Debugger

```bash
# Drop into debugger on failure
uv run pytest --pdb

# Drop into debugger on specific test
uv run pytest tests/unit/test_builder.py::test_find_sql_files --pdb
```

### Printing in Tests

```bash
# Run with print output visible
uv run pytest -s tests/unit/test_builder.py

# Specifically see prints from failing test
uv run pytest -s --tb=short tests/unit/test_builder.py
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

## Performance Optimization

Confiture aims for fast operations:

### Building
- Target: <1 second for fresh database build
- Method: Concatenate DDL files, single CREATE statement
- Measure: `time confiture build --env test`

### Migrations
- Target: Apply each migration in <100ms
- Measure: Use `--verbose` flag to see timing
- Optimize: Batch statements, use GiST indexes

### Schema Diffing
- Target: Compare schemas in <50ms
- Measure: Time differs in unit tests
- Optimize: Cache parsed schema, use Rust layer if needed

---

## Continuous Integration

The project uses GitHub Actions for CI/CD:

- **Tests**: Run all tests on every push
- **Linting**: Check code style with ruff
- **Type checking**: Validate with ty
- **Coverage**: Maintain 80%+ code coverage
- **Wheels**: Build Python wheels for distribution

Check `.github/workflows/` for details.

---

## Contributing Guidelines

### Before Submitting PR

- [ ] All tests pass (`uv run pytest`)
- [ ] Code is formatted (`uv run ruff format`)
- [ ] Type checking passes (`uv run ty check python/confiture/`)
- [ ] No new linting issues (`uv run ruff check`)
- [ ] Documentation updated (if needed)
- [ ] Commit messages follow convention

### PR Description Template

```markdown
## Description
Brief summary of changes

## Type of Change
- [ ] Bug fix
- [x] New feature
- [ ] Breaking change
- [ ] Documentation

## Testing
How was this tested?

## Checklist
- [x] Tests pass
- [x] Code formatted
- [x] Type checking passes
- [x] Documentation updated

## Related Issues
Closes #123
```

---

## Getting Help

### Resources

- **Architecture**: [ARCHITECTURE.md](./ARCHITECTURE.md)
- **Quick Start**: [README.md](./README.md)
- **Standards**: [CLAUDE.md](./CLAUDE.md)
- **Guides**: [docs/guides/](./docs/guides/)
- **Development History**: [.development/INDEX.md](./.development/INDEX.md)

### Questions?

1. Check the [ARCHITECTURE.md](./ARCHITECTURE.md) for design decisions
2. Look at [docs/guides/](./docs/guides/) for examples
3. Read related test files for usage patterns
4. Open an issue with detailed description

---

## Development Standards

Confiture follows these principles:

1. **Test-Driven Development**: RED → GREEN → REFACTOR → QA
2. **Single Source of Truth**: DDL files are primary, migrations derived
3. **Production Ready**: All code must meet quality standards
4. **Clear Code**: Prioritize readability over cleverness
5. **Documentation**: Every feature documented with examples

---

## Release Process

1. **Update version** in `pyproject.toml`
2. **Update CHANGELOG.md** with release notes
3. **Create git tag**: `git tag v0.4.0`
4. **Push tag**: `git push origin v0.4.0`
5. **GitHub creates release** with wheels (automatic via CI/CD)

---

**Last Updated**: December 27, 2025
**Version**: 0.4.0
**Status**: Production Ready 🚀

*Making jam from strawberries, one commit at a time.* 🍓→🍯
