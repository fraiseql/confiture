# Type Checking with Astral's `ty`

This project uses **Astral's `ty`** type checker for Python type validation. `ty` is a modern, ultra-fast type checker built by the team behind Ruff.

## Overview

**`ty`** is the successor to mypy, offering:
- ⚡ **Ultra-fast type checking** (10-100x faster than mypy)
- 🎯 **High accuracy** with Pyright-compatible type inference
- 🔧 **Zero config** for simple projects
- 📦 **PostgreSQL strict types** for psycopg3 compatibility
- 🚀 **Fast iteration** during development

## Quick Start

### Check Types Locally

```bash
# Basic type check
uv run ty check python/confiture/

# Verbose output (detailed diagnostics)
uv run ty check python/confiture/ --verbose

# Using convenience script
./scripts/type-check.sh
./scripts/type-check.sh --verbose
./scripts/type-check.sh --watch
```

### Watch Mode (During Development)

```bash
# Auto-recheck on file changes
./scripts/type-check.sh --watch

# Or with uv directly
uv run ty check python/confiture/ --watch
```

## Configuration

Type checking is configured in `pyproject.toml`:

```toml
[tool.ty.src]
include = ["python"]
exclude = ["examples", "tests", "**/test_*.py"]

[tool.ty.environment]
python-version = "3.11"
root = ["python"]

[tool.ty.analysis]
respect-type-ignore-comments = true

[tool.ty.rules]
# psycopg3 uses strict type requirements (LiteralString)
invalid-argument-type = "warn"
```

### Configuration Options

| Option | Type | Description |
|--------|------|-------------|
| `include` | List | Directories to type check |
| `exclude` | List | Directories to skip |
| `python-version` | String | Python version to check against |
| `respect-type-ignore-comments` | Bool | Honor `# type: ignore` comments |

### Rule Settings

You can configure individual type checking rules:

- `invalid-argument-type` - Type mismatch in function arguments
- `invalid-return-type` - Type mismatch in return values
- `undefined-variable` - References to undefined variables
- `unused-import` - Unused imports

## Common Type Issues

### psycopg3 `LiteralString` Requirement

psycopg3 requires SQL strings to be `LiteralString` for security (prevents SQL injection):

```python
# ❌ NOT ALLOWED - Dynamic string
sql = f"SELECT * FROM users WHERE id = {user_id}"
cursor.execute(sql)  # Type error!

# ✅ CORRECT - Literal string with parameters
sql = "SELECT * FROM users WHERE id = %s"
cursor.execute(sql, (user_id,))

# ✅ ALSO CORRECT - Using SQL composition
from psycopg import sql
query = sql.SQL("SELECT * FROM {} WHERE id = %s").format(
    sql.Identifier('users')
)
cursor.execute(query, (user_id,))
```

### Type Ignoring

For rare cases where you need to bypass type checking:

```python
# Ignore single line
x = some_untyped_function()  # type: ignore

# Ignore specific rule
x = some_untyped_function()  # type: ignore[return-value]

# Ignore entire block
# type: ignore
untyped_code()
more_untyped_code()
```

## Integration with Development

### Local Development

1. **Before committing**: Run `./scripts/type-check.sh`
2. **During development**: Use `./scripts/type-check.sh --watch`
3. **In IDE**: Most IDEs can integrate with `ty` via LSP

### Pre-commit Hook

Type checking is NOT added to pre-commit hooks since it can be slow.
Instead, run locally or rely on CI/CD for blocking checks.

To add optional pre-commit type checking:

```bash
# Install and configure in .pre-commit-config.yaml
# (not in default config to keep commits fast)
```

### CI/CD Pipeline

Type checking runs automatically in GitHub Actions:

```bash
# In quality-gate.yml
- name: Run ty type check
  run: ty check python/confiture/
```

Type check failures **block merges** to main branch.

## Development Workflow

### Type-Checking During Development

```bash
# Terminal 1: Watch for changes
./scripts/type-check.sh --watch

# Terminal 2: Make code changes
# type-check will automatically rerun in Terminal 1
```

### Running Full Quality Checks

```bash
# Run all quality checks (tests, lint, types)
uv run pytest
uv run ruff check .
uv run ty check python/confiture/

# Or use convenience script
./scripts/quality-check.sh  # if available
```

## Troubleshooting

### `ty: command not found`

Install with:
```bash
uv tool install ty
```

Or include in dev dependencies:
```bash
uv sync --all-extras
```

### Type Errors with External Libraries

If you get type errors from untyped libraries, you can:

1. **Suppress the warning**:
   ```python
   import untyped_lib  # type: ignore[import-not-found]
   ```

2. **Check for type stubs**:
   ```bash
   uv pip install types-package-name
   ```

### psycopg3 Type Issues

For `psycopg` cursor type errors, ensure you're using:

```python
# Correct: Using parameterized queries
cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))

# NOT: Dynamic string building
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
```

## Performance Tips

### Speed Up Type Checking

1. **Exclude unnecessary directories**:
   ```toml
   [tool.ty.src]
   exclude = ["examples", "tests", "**/test_*.py"]
   ```

2. **Focus on specific files**:
   ```bash
   uv run ty check python/confiture/core/  # Just core
   ```

3. **Use watch mode for incremental checks**:
   ```bash
   ./scripts/type-check.sh --watch
   ```

## Comparison: ty vs mypy

| Feature | ty | mypy |
|---------|----|----|
| Speed | ⚡⚡⚡ Ultra-fast | ⚡ Slow |
| Accuracy | 🎯 High | 🎯 High |
| Configuration | 📦 Simple | 📋 Complex |
| PostgreSQL Support | ✅ Yes | ⚠️ Requires stubs |
| Development | 🚀 Modern | 🏛️ Legacy |

## Resources

- **[Astral ty Documentation](https://docs.astral.sh/ty/)** - Official documentation
- **[Python Type Hints](https://docs.python.org/3/library/typing.html)** - Python typing reference
- **[PEP 484](https://www.python.org/dev/peps/pep-0484/)** - Type hints specification
- **[psycopg Type Safety](https://www.psycopg.org/psycopg3/docs/basic/queries.html)** - psycopg3 security

## Contributing

When contributing code:

1. ✅ Ensure types pass: `uv run ty check python/confiture/`
2. ✅ Fix type errors before committing
3. ✅ Use type hints for all public APIs
4. ✅ Add `# type: ignore` comments with explanation if needed

## Migration from mypy

If you've used mypy before:

- **Configuration** is similar but in `[tool.ty.*]` sections
- **Type syntax** is identical (same `typing` module)
- **Error messages** are more concise
- **Performance** is much faster (no need for watch scripts)

No code changes needed - `ty` understands all Python type hints!

---

**Status**: Using Astral's `ty` v0.0.7+ for all type checking
**Last Updated**: December 2025
