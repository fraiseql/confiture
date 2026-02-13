# Error Context Development Guide

Guide for adding new error contexts to Confiture's enhanced error messaging system (Phase 2 M2).

---

## Overview

Confiture's error message system provides users with:
- Clear explanation of what went wrong
- Step-by-step instructions to fix it
- Real examples they can copy and use
- Links to detailed documentation

This guide shows how to add new error contexts for additional error scenarios.

---

## How Error Context System Works

### Flow

```
Exception raised in code
    ↓
Exception caught in CLI
    ↓
print_error_to_console(error)
    ↓
_detect_error_context(error)  [pattern matching]
    ↓
format_error_with_context()  [Rich formatting]
    ↓
Display to user with full context
```

### Components

1. **ErrorContext** (dataclass)
   - Stores error information
   - Located in `confiture/core/error_context.py`

2. **ERROR_CONTEXTS** (dict)
   - Maps error codes to ErrorContext objects
   - Located in `confiture/core/error_context.py`

3. **_detect_error_context()** (function)
   - Pattern matches exceptions to error codes
   - Located in `confiture/core/error_handler.py`

4. **format_error_with_context()** (function)
   - Formats error context into user-friendly message
   - Located in `confiture/core/error_context.py`

---

## Adding a New Error Context

### Step 1: Define the ErrorContext

Add an entry to `ERROR_CONTEXTS` in `error_context.py`:

```python
# In confiture/core/error_context.py
ERROR_CONTEXTS = {
    # ... existing contexts ...

    "YOUR_ERROR_CODE": ErrorContext(
        error_code="YOUR_ERROR_CODE",
        message="Brief message for users",
        cause="What caused this error to happen",
        solutions=[
            "Step 1: First thing to try",
            "Step 2: Second thing to try",
            "Step 3: Third thing to try",
            "Step 4: Additional options",
        ],
        examples=[
            "confiture command --example",
            "export VAR=value && confiture command",
        ],
        docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#your_error_code",
    ),
}
```

### Step 2: Add Error Detection

Add pattern matching to `_detect_error_context()` in `error_handler.py`:

```python
# In confiture/core/error_handler.py
def _detect_error_context(error: Exception) -> str | None:
    error_msg = str(error).lower()

    # ... existing detection logic ...

    # Your new error detection
    if isinstance(error, YourExceptionType) and some_pattern in error_msg:
        return "YOUR_ERROR_CODE"

    return None
```

### Step 3: Write Tests

Add tests in `tests/unit/test_m2_error_context_integration.py`:

```python
def test_detect_your_error(self):
    """Detect your error type."""
    error = YourExceptionType("Error message with pattern")
    detected = _detect_error_context(error)
    assert detected == "YOUR_ERROR_CODE"

def test_format_your_error(self):
    """Format your error properly."""
    output = format_error_with_context("YOUR_ERROR_CODE")
    assert "HOW TO FIX" in output
    assert "EXAMPLES" in output
```

### Step 4: Verify

```bash
# Run tests
uv run pytest tests/unit/test_m2_error_context_integration.py -v

# Check linting
uv run ruff check python/confiture/core/

# Verify full test suite
uv run pytest tests/unit/ -x
```

---

## Best Practices

### 1. Message Design

**Good message**:
```
"Database connection failed"
```

**Bad message**:
```
"Unable to establish a connection to the database instance"
```

✅ Be specific but concise
❌ Avoid overly technical language

### 2. Cause Explanation

**Good cause**:
```
"Cannot reach PostgreSQL database at the specified URL"
```

**Bad cause**:
```
"ECONNREFUSED"
```

✅ Explain in user-friendly terms
❌ Don't just repeat the error

### 3. Solutions

**Good solutions**:
```
[
    "Verify PostgreSQL is running: pg_isready localhost",
    "Check your DATABASE_URL parameter",
    "Verify username/password: psql -U postgres",
]
```

**Bad solutions**:
```
[
    "Debug the connection",
    "Check the database",
]
```

✅ Specific, actionable steps
✅ Include actual commands to run
❌ Vague instructions
❌ Assume user knowledge

### 4. Examples

**Good examples**:
```
[
    "confiture build --database-url postgresql://localhost/mydb",
    "export DATABASE_URL=postgresql://user:pass@localhost/mydb",
]
```

**Bad examples**:
```
[
    "use the database",
    "connect to PostgreSQL",
]
```

✅ Copy-paste ready
✅ Show both methods (CLI flag and env var)
❌ Not executable
❌ Incomplete

### 5. Documentation Links

**Good links**:
```
"https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#db_connection_failed"
```

**Bad links**:
```
"See our docs"
```

✅ Direct link to section
✅ Include anchor (#section)
❌ Vague reference
❌ Link to home page

---

## Error Code Naming

Use ALL_CAPS with underscores:

```
GOOD:
- DB_CONNECTION_FAILED
- SCHEMA_DIR_NOT_FOUND
- FOREIGN_KEY_CONSTRAINT
- INSUFFICIENT_DISK_SPACE

BAD:
- database_connection
- schema-not-found
- FK_Constraint
- OutOfDiskSpace
```

---

## Exception Type Detection

### Matching by Exception Type

```python
# Best: Match specific exception type
if isinstance(error, ConfigurationError):
    return "YOUR_ERROR_CODE"
```

### Matching by Message Pattern

```python
# Good: Match pattern in message
if "pattern" in error_msg.lower():
    return "YOUR_ERROR_CODE"

# Better: Match multiple related patterns
if any(keyword in error_msg for keyword in ["pattern1", "pattern2"]):
    return "YOUR_ERROR_CODE"

# Best: Combine type and pattern
if isinstance(error, SomeError) and "pattern" in error_msg:
    return "YOUR_ERROR_CODE"
```

### Multiple Conditions

```python
# Chain conditions logically
if isinstance(error, ConfigurationError):
    if "permission" in error_msg or "denied" in error_msg:
        return "DB_PERMISSION_DENIED"
    if "connection" in error_msg or "connect" in error_msg:
        return "DB_CONNECTION_FAILED"
```

---

## Testing Your Error Context

### Unit Test

```python
def test_detect_my_error(self):
    """Detect my new error type."""
    error = MyException("Error message with pattern")
    detected = _detect_error_context(error)
    assert detected == "MY_ERROR_CODE"

def test_format_my_error(self):
    """Verify formatting includes all sections."""
    output = format_error_with_context("MY_ERROR_CODE")
    assert "❌" in output
    assert "CAUSE:" in output
    assert "HOW TO FIX:" in output
    assert "EXAMPLES:" in output
    assert "LEARN MORE:" in output
```

### Manual Testing

```bash
# Create a test scenario that triggers your error
# For example, if adding a disk space error:
# - Temporarily reduce partition size
# - Run operation that needs disk
# - Verify error message displays correctly

# Or simulate the error in code:
python3 << 'EOF'
from confiture.core.error_handler import _detect_error_context, print_error_to_console

# Create error
error = Exception("no space left on device")

# Detect context
context = _detect_error_context(error)
print(f"Detected: {context}")

# Print as user would see
print_error_to_console(error)
EOF
```

---

## Common Pitfalls

### 1. Missing Documentation Links

❌ **Bad**:
```python
docs_url="https://github.com/fraiseql/confiture",
```

✅ **Good**:
```python
docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#db_connection_failed",
```

### 2. Unclear Solutions

❌ **Bad**:
```python
solutions=["Check the database", "Verify settings"]
```

✅ **Good**:
```python
solutions=[
    "Verify PostgreSQL is running: pg_isready localhost",
    "Check DATABASE_URL: echo $DATABASE_URL",
]
```

### 3. Too Broad Detection

❌ **Bad**:
```python
if "error" in error_msg:  # Matches everything!
    return "GENERIC_ERROR"
```

✅ **Good**:
```python
if "permission" in error_msg and isinstance(error, ConfigurationError):
    return "DB_PERMISSION_DENIED"
```

### 4. Not Testing Edge Cases

- Test with uppercase/lowercase
- Test with multi-line error messages
- Test with special characters
- Test with missing context

---

## Current Error Contexts

Reference for error patterns already handled:

| Code | Pattern | Type |
|------|---------|------|
| DB_CONNECTION_FAILED | "connection" + ConfigurationError | Database |
| DB_PERMISSION_DENIED | "permission" + ConfigurationError | Database |
| SCHEMA_DIR_NOT_FOUND | "schema" + FileNotFoundError | File System |
| MIGRATIONS_DIR_NOT_FOUND | "migration" + FileNotFoundError | File System |
| SEEDS_DIR_NOT_FOUND | "seed" + FileNotFoundError | File System |
| MIGRATION_CONFLICT | MigrationConflictError | Migration |
| SEED_VALIDATION_FAILED | "validation" + SeedError | Seed |
| SQL_SYNTAX_ERROR | "syntax" | SQL |
| TABLE_ALREADY_EXISTS | "already exists" + ("table"\|"relation") | SQL |
| FOREIGN_KEY_CONSTRAINT | "foreign key"\|"constraint" | SQL |
| INSUFFICIENT_DISK_SPACE | "no space" | System |
| LOCK_TIMEOUT | "timeout" | Database |

---

## Adding Documentation

After creating an error context:

1. **Add to Error Reference**
   - Edit `docs/error-reference.md`
   - Add section with cause, fix steps, examples

2. **Update Troubleshooting Guide**
   - Link to error reference
   - Add specific scenarios if relevant

3. **Consider Developer Guide**
   - If new exception type, document it
   - Link to related patterns

---

## Review Checklist

Before submitting:

- [ ] ErrorContext defined in error_context.py
- [ ] Pattern detection in error_handler.py
- [ ] Tests written and passing
- [ ] Documentation added
- [ ] All tests pass: `uv run pytest tests/unit/`
- [ ] Linting passes: `uv run ruff check python/confiture/`
- [ ] Backward compatible (no breaking changes)
- [ ] Message follows guidelines (clear, specific)
- [ ] Solutions are actionable
- [ ] Examples are copy-paste ready
- [ ] Documentation link is correct

---

## Example: Complete New Error Context

Here's a complete example adding a new error for invalid configuration file:

**error_context.py**:
```python
"INVALID_CONFIG_FILE": ErrorContext(
    error_code="INVALID_CONFIG_FILE",
    message="Configuration file is invalid YAML",
    cause="The YAML syntax in your config file is incorrect",
    solutions=[
        "Check YAML syntax: run file through YAML validator",
        "Check indentation: YAML requires consistent spaces (not tabs)",
        "Verify quotes: strings may need single or double quotes",
        "Common issues: missing colons after keys, tabs instead of spaces",
        "Use: confiture init to generate valid config",
    ],
    examples=[
        "python3 -m yaml < db/config.yaml  # Validate YAML",
        "confiture init  # Generate valid config",
    ],
    docs_url="https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#invalid_config_file",
),
```

**error_handler.py**:
```python
if isinstance(error, ConfigurationError) and "yaml" in error_msg:
    return "INVALID_CONFIG_FILE"
```

**test_m2_error_context_integration.py**:
```python
def test_detect_invalid_config(self):
    """Detect invalid YAML configuration."""
    error = ConfigurationError("YAML parsing failed at line 5")
    detected = _detect_error_context(error)
    assert detected == "INVALID_CONFIG_FILE"
```

---

## Questions?

- See existing error contexts for examples
- Check tests for pattern matching examples
- Review error-reference.md for documentation style

---

**Last Updated**: February 13, 2026
**Version**: 0.4.1+
**Status**: Comprehensive guide for M2 error context development
