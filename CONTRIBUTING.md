# Contributing to Confiture

Thank you for your interest in contributing to Confiture! This document provides guidelines and instructions for contributing.

---

## 🌟 Ways to Contribute

### 1. Code Contributions

- **Bug fixes** - Fix issues reported on GitHub
- **New features** - Implement items from [PHASES.md](PHASES.md)
- **Performance improvements** - Optimize Python or Rust code
- **Test coverage** - Add or improve tests

### 2. Documentation

- **User guides** - Improve existing guides or write new ones
- **API documentation** - Document public APIs with examples
- **Tutorials** - Write step-by-step tutorials
- **README improvements** - Clarify installation, usage, or examples

### 3. Examples

- **New scenarios** - Add production-ready examples
- **Improve existing** - Enhance current examples
- **Real-world use cases** - Share your Confiture workflow

### 4. Community

- **Answer questions** - Help users on GitHub Issues
- **Share experiences** - Blog posts, talks, or tutorials
- **Report bugs** - File detailed bug reports
- **Feature requests** - Suggest improvements

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.11+** (3.12 recommended)
- **Rust 1.75+** (for Rust performance layer)
- **PostgreSQL 12+** (for integration tests)
- **uv** package manager (recommended)

### Development Setup

```bash
# 1. Fork and clone repository
git clone https://github.com/YOUR_USERNAME/confiture.git
cd confiture

# 2. Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Install dependencies (includes Python + Rust)
uv sync --all-extras

# 4. Build Rust extension
uv run maturin develop

# 5. Verify installation
uv run confiture --version

# 6. Run tests to ensure everything works
uv run pytest --cov=confiture
```

### Project Structure

```
confiture/
├── python/confiture/         # Python source code
│   ├── cli/                  # CLI commands
│   ├── core/                 # Core logic (builder, migrator, etc.)
│   ├── config/               # Configuration management
│   └── models/               # Data models
│
├── rust/src/                 # Rust performance layer
│   ├── lib.rs                # Main Rust entry point
│   ├── hash.rs               # Fast hashing
│   └── parser.rs             # SQL parsing
│
├── tests/                    # Test suite
│   ├── unit/                 # Fast unit tests
│   ├── integration/          # Database-dependent tests
│   └── e2e/                  # End-to-end tests
│
├── docs/                     # Documentation
│   ├── guides/               # User guides
│   └── reference/            # API reference
│
├── examples/                 # Production examples
│
├── pyproject.toml            # Python dependencies
├── Cargo.toml                # Rust dependencies
└── uv.lock                   # Locked dependencies
```

---

## 🧪 Development Workflow

### 1. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
```

**Branch naming**:
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `test/` - Test improvements

### 2. Make Your Changes

Follow the [Code Style Guidelines](#-code-style-guidelines) below.

### 3. Write Tests

**Test requirements**:
- All new code must have tests
- Maintain or improve coverage (target: >90%)
- Follow TDD when possible (write test first)

**Run tests**:

```bash
# All tests
uv run pytest

# Unit tests only (fast)
uv run pytest tests/unit/ -v

# Integration tests (requires PostgreSQL)
uv run pytest tests/integration/ -v

# With coverage report
uv run pytest --cov=confiture --cov-report=html

# Open coverage report
open htmlcov/index.html
```

### 4. Format Code

```bash
# Auto-format with ruff
uv run ruff format .

# Check code style
uv run ruff check .

# Type checking
uv run mypy python/confiture/
```

### 5. Run Pre-commit Hooks

```bash
# Install pre-commit hooks
uv run pre-commit install

# Run manually
uv run pre-commit run --all-files
```

### 6. Commit Your Changes

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types**:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Test improvements
- `perf:` - Performance improvements
- `chore:` - Maintenance tasks

**Examples**:

```bash
git commit -m "feat(cli): add --dry-run flag to migrate up"
git commit -m "fix(differ): handle NULL column defaults correctly"
git commit -m "docs(guide): improve zero-downtime migration guide"
git commit -m "test(core): add integration tests for schema builder"
```

### 7. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then open a Pull Request on GitHub.

---

## 📝 Code Style Guidelines

### Python Style

Follow **PEP 8** with these additions:

#### Type Hints

Always use type hints:

```python
# Good
def build_schema(env: str, output_path: Path | None = None) -> str:
    ...

# Bad
def build_schema(env, output_path=None):
    ...
```

#### Docstrings

Use Google-style docstrings:

```python
def migrate_up(target: str | None = None) -> None:
    """Apply pending migrations up to target version.

    Args:
        target: Target migration version. If None, applies all pending.

    Raises:
        MigrationError: If migration fails.

    Example:
        >>> migrator = Migrator(env="production")
        >>> migrator.migrate_up(target="003")
    """
    ...
```

#### Naming Conventions

```python
# Functions and variables: snake_case
def find_sql_files(directory: Path) -> list[Path]:
    sql_files = []
    ...

# Classes: PascalCase
class SchemaBuilder:
    ...

# Constants: UPPER_SNAKE_CASE
DEFAULT_MIGRATION_TABLE = "confiture_migrations"

# Private: prefix with underscore
def _internal_helper():
    ...
```

#### Import Order

```python
# 1. Standard library
from pathlib import Path
from typing import Any

# 2. Third-party
import typer
from rich.console import Console

# 3. Local imports
from confiture.core.builder import SchemaBuilder
from confiture.exceptions import ConfigurationError
```

### Rust Style

Follow standard Rust conventions:

```rust
// Use rustfmt
cargo fmt

// Use clippy for linting
cargo clippy

// Doc comments for public APIs
/// Compute SHA-256 hash of schema content.
///
/// # Arguments
/// * `content` - Schema content as string
///
/// # Returns
/// Hex-encoded SHA-256 hash
pub fn compute_hash(content: &str) -> String {
    ...
}
```

---

## 🧪 Testing Guidelines

### Test Pyramid

```
      ┌──────┐
      │  E2E │  10% - Full workflows (slow)
      ├──────┤
      │ Integ│  30% - Database operations (medium)
      ├──────┤
      │ Unit │  60% - Fast, isolated (fast)
      └──────┘
```

### Unit Tests (60%)

**Location**: `tests/unit/`

**Characteristics**:
- Fast (<1ms per test)
- No database or external dependencies
- Test individual functions/classes

**Example**:

```python
# tests/unit/test_builder.py
def test_find_sql_files(tmp_path):
    """Test SQL file discovery without database."""
    # Create test files
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / "users.sql").write_text("CREATE TABLE users (...);")
    (schema_dir / "posts.sql").write_text("CREATE TABLE posts (...);")

    # Test file discovery
    builder = SchemaBuilder(schema_dir)
    files = builder.find_sql_files()

    assert len(files) == 2
    assert all(f.suffix == ".sql" for f in files)
```

### Integration Tests (30%)

**Location**: `tests/integration/`

**Characteristics**:
- Medium speed (100-500ms per test)
- Require PostgreSQL database
- Test actual database operations

**Example**:

```python
# tests/integration/test_build_local.py
@pytest.mark.asyncio
async def test_build_creates_database(test_db):
    """Test actual database creation."""
    builder = SchemaBuilder(env="test")
    await builder.build()

    # Verify tables exist
    async with test_db.connection() as conn:
        result = await conn.execute(
            "SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'"
        )
        assert result.scalar() > 0
```

### E2E Tests (10%)

**Location**: `tests/e2e/`

**Characteristics**:
- Slow (1-5 seconds per test)
- Test complete workflows
- CLI commands

**Example**:

```python
# tests/e2e/test_complete_workflow.py
def test_full_migration_cycle():
    """Test: init -> build -> migrate -> verify."""
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

### Test Fixtures

Use pytest fixtures for common setup:

```python
# tests/conftest.py
@pytest.fixture
def test_db():
    """Create temporary test database."""
    db = create_test_database()
    yield db
    db.drop()

@pytest.fixture
def schema_dir(tmp_path):
    """Create temporary schema directory."""
    schema = tmp_path / "schema"
    schema.mkdir()
    return schema
```

---

## 📖 Documentation Guidelines

### User Guides

**Location**: `docs/guides/`

**Requirements**:
- Start with clear objective
- Step-by-step instructions
- Include code examples
- Add troubleshooting section

**Template**:

```markdown
# Guide Title

Brief description of what this guide covers.

## Prerequisites

- Requirement 1
- Requirement 2

## Step 1: Do Something

Explanation...

```bash
command --option
```

Expected output...

## Step 2: Do Next Thing

...

## Troubleshooting

### Problem: Error message

**Solution**: Fix...

## Further Reading

- Link to related guide
```

### API Reference

**Location**: `docs/reference/`

**Requirements**:
- Document all public APIs
- Include type signatures
- Provide usage examples
- Explain parameters and return values

### Examples

**Location**: `examples/`

**Requirements**:
- Complete working project
- README with tutorial
- Sample data (if applicable)
- Clear learning objectives

See [examples/README.md](examples/README.md) for structure.

---

## 🔍 Pull Request Process

### Before Submitting

- [ ] Tests pass: `uv run pytest`
- [ ] Code formatted: `uv run ruff format .`
- [ ] Linting passes: `uv run ruff check .`
- [ ] Type checking passes: `uv run mypy python/confiture/`
- [ ] Documentation updated (if needed)
- [ ] CHANGELOG.md updated (if user-facing change)

### PR Template

Use this template for your PR description:

```markdown
## Description

Brief description of changes.

## Type of Change

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change
- [ ] Documentation update

## Testing

Describe testing performed:

- [ ] Added unit tests
- [ ] Added integration tests
- [ ] Manual testing completed

## Checklist

- [ ] Tests pass
- [ ] Code formatted
- [ ] Documentation updated
- [ ] CHANGELOG.md updated

## Related Issues

Closes #123
```

### Review Process

1. **Automated checks** run on CI (tests, linting, type checking)
2. **Maintainer review** (typically within 3-5 days)
3. **Address feedback** if requested
4. **Merge** when approved

---

## 🐛 Reporting Bugs

### Before Filing

1. **Search existing issues** to avoid duplicates
2. **Verify bug** on latest version
3. **Check documentation** for known issues

### Bug Report Template

```markdown
## Description

Clear description of the bug.

## Steps to Reproduce

1. Run command: `confiture build --env local`
2. Error occurs: ...

## Expected Behavior

What should happen.

## Actual Behavior

What actually happens.

## Environment

- Confiture version: 0.3.0
- Python version: 3.12.0
- PostgreSQL version: 15.3
- Operating system: Ubuntu 22.04

## Additional Context

Logs, screenshots, or config files.
```

---

## 💡 Feature Requests

### Before Requesting

1. **Check roadmap** ([PHASES.md](PHASES.md))
2. **Search existing issues**
3. **Consider alternatives**

### Feature Request Template

```markdown
## Problem

What problem does this solve?

## Proposed Solution

How should it work?

## Alternatives Considered

Other approaches?

## Additional Context

Examples, mockups, or use cases.
```

---

## 🌍 Community Guidelines

### Code of Conduct

We follow the **Contributor Covenant Code of Conduct**:

- **Be respectful** of differing viewpoints
- **Be welcoming** to newcomers
- **Be constructive** in feedback
- **Focus on** what's best for the community

### Communication

- **GitHub Issues** - Bug reports, feature requests
- **GitHub Discussions** - Questions, ideas, show and tell
- **Pull Requests** - Code contributions

---

## 📋 Checklist for First-Time Contributors

If this is your first contribution to Confiture:

- [ ] Read [CLAUDE.md](CLAUDE.md) for development guide
- [ ] Review [PHASES.md](PHASES.md) to understand roadmap
- [ ] Look for issues labeled `good-first-issue`
- [ ] Set up development environment
- [ ] Run tests to ensure setup works
- [ ] Make a small change (typo fix, comment improvement)
- [ ] Submit your first PR!

---

## 🎓 Learning Resources

### Recommended Reading

- **Python**:
  - [PEP 8 Style Guide](https://peps.python.org/pep-0008/)
  - [Type Hints](https://docs.python.org/3/library/typing.html)
  - [pytest Documentation](https://docs.pytest.org/)

- **Rust**:
  - [The Rust Book](https://doc.rust-lang.org/book/)
  - [PyO3 Guide](https://pyo3.rs/) (Python bindings)
  - [Rustfmt](https://github.com/rust-lang/rustfmt)

- **PostgreSQL**:
  - [PostgreSQL Documentation](https://www.postgresql.org/docs/)
  - [Foreign Data Wrappers](https://www.postgresql.org/docs/current/ddl-foreign-data.html)

### Confiture Internals

- **[CLAUDE.md](CLAUDE.md)** - Development methodology
- **[PHASES.md](PHASES.md)** - Roadmap and architecture
- **[docs/reference/](docs/reference/)** - API documentation

---

## 🙏 Recognition

All contributors are recognized in:

- **[CONTRIBUTORS.md](CONTRIBUTORS.md)** (if it exists)
- Git commit history
- Release notes

Thank you for contributing to Confiture! 🍓

---

## 📞 Questions?

- **General questions**: [GitHub Discussions](https://github.com/fraiseql/confiture/discussions)
- **Bug reports**: [GitHub Issues](https://github.com/fraiseql/confiture/issues)
- **Security issues**: Email lionel.hamayon@evolution-digitale.fr

---

**Last Updated**: October 12, 2025

*Making jam from strawberries, one contribution at a time.* 🍓
