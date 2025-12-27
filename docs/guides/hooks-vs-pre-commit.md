# Hooks vs Pre-commit: Which Should You Use?

**Compare Confiture hooks and git pre-commit hooks to choose the right tool**

---

## Quick Comparison

| Aspect | Confiture Hooks | Git Pre-commit |
|--------|-----------------|----------------|
| **Trigger** | Migration lifecycle | Git commit |
| **When** | Before/after SQL execution | Before code enters repo |
| **Language** | Python only | Any language |
| **Access** | Database, migration context | Git objects, file content |
| **Scope** | Single migration | All changed files |
| **Failure** | Stops migration | Prevents commit |
| **Use case** | Data validation, logging | Code standards, formatting |

---

## Confiture Hooks

### What They Do

Confiture hooks run **during migration execution** to validate data, log changes, and handle side effects.

**Lifecycle**:
```
confiture migrate up
    ↓
[pre_execute] → Run SQL → [post_execute]
```

### Perfect For

✅ **Database-specific tasks**
- Validate data integrity after migration
- Log migration metadata to audit table
- Check preconditions before applying

✅ **Migration-aware operations**
- Notify team via Slack on completion
- Update caches after schema changes
- Rebuild indices based on migration

✅ **Environment-specific logic**
- Run checks only in production
- Different behavior for staging vs production

### Examples

```python
# ✅ GOOD: Hook validates data integrity
@register_hook('post_execute')
def verify_schema(context: HookContext) -> None:
    """Verify data matches new schema after migration."""
    with psycopg.connect() as conn:
        # Query database to verify constraints
        result = conn.execute("SELECT COUNT(*) FROM users WHERE email IS NULL")
        if result.scalar() > 0:
            raise ValueError("Found NULL emails after migration!")

# ✅ GOOD: Hook logs to database
@register_hook('post_execute')
def audit_log(context: HookContext) -> None:
    """Log migration to audit table."""
    with psycopg.connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (migration, applied_at) VALUES (%s, NOW())",
            (context.migration.name,)
        )
```

---

## Git Pre-commit Hooks

### What They Do

Git pre-commit hooks run **before committing code** to prevent bad commits from entering the repository.

**Lifecycle**:
```
git commit
    ↓
[pre-commit hooks] → Update staging → [commit created]
```

### Perfect For

✅ **Code quality checks**
- Format code (black, prettier)
- Lint SQL files (sqlfluff)
- Check type hints

✅ **File-level operations**
- Validate schema file syntax
- Check SQL for common mistakes
- Verify documentation is updated

✅ **Prevent bad commits**
- Block commits with console.log
- Enforce commit message format
- Ensure all tests pass

### Examples

```yaml
# ✅ GOOD: Pre-commit lints SQL files
repos:
  - repo: https://github.com/sqlfluff/sqlfluff
    rev: 2.1.1
    hooks:
      - id: sqlfluff-lint
        files: ^db/schema/
        args: ['--dialect', 'postgres']

# ✅ GOOD: Pre-commit formats code
  - repo: https://github.com/psf/black
    rev: 23.12.0
    hooks:
      - id: black
        language_version: python3
```

---

## Decision Tree

### Use Confiture Hooks If...

```
Do you need to validate/check DATABASE STATE?
├─ YES → Confiture Hooks ✓
│   (You need actual database access)
│
└─ NO → Continue...

Does it run DURING migration execution?
├─ YES → Confiture Hooks ✓
│   (You need migration context)
│
└─ NO → Continue...

Should it affect WHEN migration is applied?
├─ YES → Confiture Hooks ✓
│   (Hooks can stop migration)
│
└─ NO → Pre-commit Hooks
```

### Use Pre-commit Hooks If...

```
Do you need to CHECK FILES before commit?
├─ YES → Pre-commit Hooks ✓
│   (File validation is pre-commit's strength)
│
└─ NO → Continue...

Should it PREVENT bad commits?
├─ YES → Pre-commit Hooks ✓
│   (Pre-commit runs before commit is created)
│
└─ NO → Continue...

Does it NOT require database access?
├─ YES → Pre-commit Hooks ✓
│   (Pre-commit can't access database)
│
└─ NO → Confiture Hooks
```

---

## Real-World Examples

### Example 1: Validate Schema Syntax

**Situation**: Ensure SQL files are valid before committing.

**Use pre-commit hooks**:
```yaml
# .pre-commit-config.yaml

repos:
  - repo: https://github.com/sqlfluff/sqlfluff
    rev: 2.1.1
    hooks:
      - id: sqlfluff-lint
        files: ^db/schema/
        args: ['--dialect', 'postgres']
```

**Why**:
- ✅ Catches syntax errors before commit
- ✅ No database needed
- ✅ File-level validation

---

### Example 2: Verify Data Integrity After Migration

**Situation**: Ensure data is valid after applying migration.

**Use Confiture hooks**:
```python
# confiture_hooks.py

@register_hook('post_execute')
def verify_emails(context: HookContext) -> None:
    """Ensure all users have valid emails after migration."""
    with psycopg.connect() as conn:
        # Query DATABASE to check actual data
        result = conn.execute("SELECT COUNT(*) FROM users WHERE email IS NULL")
        if result.scalar() > 0:
            raise ValueError("Migration created NULL emails!")
```

**Why**:
- ✅ Requires actual database access
- ✅ Validates data integrity (not just syntax)
- ✅ Can access migration context
- ❌ Pre-commit hooks can't access database

---

### Example 3: Format SQL Files

**Situation**: Auto-format SQL to consistent style.

**Use pre-commit hooks**:
```yaml
# .pre-commit-config.yaml

repos:
  - repo: https://github.com/sqlfluff/sqlfluff
    rev: 2.1.1
    hooks:
      - id: sqlfluff-fix  # Auto-fixes formatting
        files: ^db/schema/
```

**Why**:
- ✅ Formats files before commit
- ✅ No database needed
- ✅ File-level operation

---

### Example 4: Log Migration to Audit Table

**Situation**: Record who applied each migration for compliance.

**Use Confiture hooks**:
```python
# confiture_hooks.py

@register_hook('post_execute')
def audit_log(context: HookContext) -> None:
    """Log to audit table."""
    with psycopg.connect() as conn:
        conn.execute(
            "INSERT INTO audit (migration, applied_by) VALUES (%s, %s)",
            (context.migration.name, os.getenv('USER'))
        )
```

**Why**:
- ✅ Requires database access
- ✅ Only runs when migration executes
- ✅ Has migration metadata

---

### Example 5: Validate Commit Messages

**Situation**: Enforce conventional commits format.

**Use pre-commit hooks**:
```bash
# .pre-commit-config.yaml

repos:
  - repo: https://github.com/compilerla/conventional-pre-commit
    rev: v2.4.0
    hooks:
      - id: conventional-pre-commit
        stages: [commit-msg]
```

**Why**:
- ✅ Pre-commit runs before commit is created
- ✅ Can validate commit message
- ✅ No database needed

---

## Common Mistakes

### ❌ Mistake 1: Using Pre-commit for Database Validation

```yaml
# BAD: Pre-commit can't access database
repos:
  - repo: local
    hooks:
      - id: check-database
        name: Check database state
        entry: python check_db.py  # CAN'T ACCESS DB!
        language: python
        files: ^db/schema/
```

**Fix**: Use Confiture hooks instead
```python
@register_hook('post_execute')
def check_database(context: HookContext) -> None:
    """Runs after migration with database access."""
    # Database is accessible here
    with psycopg.connect() as conn:
        pass
```

---

### ❌ Mistake 2: Using Confiture Hooks for Code Quality

```python
# BAD: Confiture hooks only run during migration
@register_hook('pre_execute')
def check_python_format(context: HookContext) -> None:
    """This only runs during migration, not during development."""
    # Won't catch unformatted code in day-to-day work
    pass
```

**Fix**: Use pre-commit hooks for code quality
```yaml
# .pre-commit-config.yaml

repos:
  - repo: https://github.com/psf/black
    rev: 23.12.0
    hooks:
      - id: black  # Runs on every commit
```

---

### ❌ Mistake 3: Pre-commit Tries to Check Migration Safety

```python
# BAD: Pre-commit can't understand migration safety
entry: check_migration_safety.py --file db/schema/10_tables/users.sql
# Just checking file syntax, not actual impact
```

**Fix**: Let migrations execute with Confiture hooks for actual checks
```python
@register_hook('pre_execute')
def check_migration_safety(context: HookContext) -> None:
    """Runs before migration with full context."""
    # Can access schema, migration details, etc.
    if 'drop' in context.migration.sql.lower():
        # Check if data will be lost
        pass
```

---

## Combined Strategy (Recommended)

**Use both together for maximum benefit**:

```
Development:
  git commit
    → [pre-commit: format & lint code]
    → [commit created]
    → confiture migrate up
       → [Confiture hooks: validate data]

CI/CD:
  pull_request
    → [pre-commit: lint schema files]
    → [migration applies]
       → [Confiture hooks: verify in staging]
```

### Example: Complete Setup

```yaml
# .pre-commit-config.yaml
# Runs on every commit

repos:
  - repo: https://github.com/sqlfluff/sqlfluff
    rev: 2.1.1
    hooks:
      - id: sqlfluff-lint
        files: ^db/schema/

  - repo: https://github.com/psf/black
    rev: 23.12.0
    hooks:
      - id: black
```

```python
# confiture_hooks.py
# Runs during migration

from confiture.hooks import register_hook, HookContext

@register_hook('pre_execute')
def check_preconditions(context: HookContext) -> None:
    """Run database checks before migration."""
    with psycopg.connect() as conn:
        conn.execute("SELECT 1")  # Verify DB is accessible

@register_hook('post_execute')
def verify_integrity(context: HookContext) -> None:
    """Verify data integrity after migration."""
    with psycopg.connect() as conn:
        # Validate schema matches expectations
        pass
```

---

## See Also

- [Migration Hooks](./migration-hooks.md) - Confiture hooks guide
- [Pre-commit Framework](https://pre-commit.com) - Official pre-commit docs
- [SQLFluff](https://github.com/sqlfluff/sqlfluff) - SQL linting tool
- [Black](https://github.com/psf/black) - Python formatting

---

## 🎯 Quick Decision Guide

**Need to validate database state?** → Confiture Hooks
**Need to format code?** → Pre-commit Hooks
**Need to check syntax before commit?** → Pre-commit Hooks
**Need to log migration metadata?** → Confiture Hooks
**Need to prevent bad commits?** → Pre-commit Hooks
**Need access to migration context?** → Confiture Hooks

---

*Part of Confiture documentation* 🍓

*Making migrations sweet and simple*
