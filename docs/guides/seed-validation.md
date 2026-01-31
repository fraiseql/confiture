# Seed Data Validation Guide

Ensure consistency and correctness in your seed files with Confiture's seed validation system.

## Overview

The `confiture seed validate` command checks seed files for common data consistency issues that can lead to bugs and inconsistencies. It helps catch problems at commit time rather than in production.

### Validation Modes

1. **Static Validation** (default) - Fast checks that don't require a database
2. **Database Validation** (with `--mode database`) - Schema-aware checks against PostgreSQL

## Quick Start

### Validate Default Seed Directory

```bash
confiture seed validate
```

This validates all `.sql` files in `db/seeds/` and subdirectories.

### Validate Specific Directory

```bash
confiture seed validate --seeds-dir db/seeds/test
```

### Validate All Environments

```bash
confiture seed validate --all
```

## Issues Detected

### DOUBLE_SEMICOLON (Error)

Two semicolons in a row indicate a potential SQL syntax error.

**Example:**
```sql
INSERT INTO users (id, name) VALUES (1, 'test');;
--                                                ^^
```

**Fix:** Remove the extra semicolon
```sql
INSERT INTO users (id, name) VALUES (1, 'test');
```

---

### NON_INSERT_STATEMENT (Error)

DDL or DML statements (other than INSERT) in seed files indicate incorrect file usage.

**Example:**
```sql
CREATE TABLE users (id INT);  -- ❌ Wrong file for this
INSERT INTO users VALUES (1);
```

**Fix:** Move DDL to schema files, keep only INSERT in seeds
```sql
INSERT INTO users VALUES (1);
```

---

### MISSING_ON_CONFLICT (Warning)

INSERT statements without `ON CONFLICT` can fail if records already exist.

**Example:**
```sql
INSERT INTO users (id, name) VALUES (1, 'admin');
--                                   ^ No conflict handling
```

**Auto-Fix Available:** Yes - Use `--fix` to add `ON CONFLICT DO NOTHING`

```sql
INSERT INTO users (id, name) VALUES (1, 'admin') ON CONFLICT DO NOTHING;
```

---

## Auto-Fix Mode

Automatically fix correctable issues in seed files.

### Preview Fixes (Dry-Run)

See what would be fixed without modifying files:

```bash
confiture seed validate --fix --dry-run
```

Output example:
```
~ Would fix 1 issues in db/seeds/common/users.sql
```

### Apply Fixes

```bash
confiture seed validate --fix
```

This modifies files in place, adding `ON CONFLICT DO NOTHING` to INSERT statements.

**Current Fix:** Adding `ON CONFLICT DO NOTHING` to INSERT statements

## Database Validation

Validate against actual PostgreSQL schema (requires database connection).

```bash
confiture seed validate --mode database --database-url postgresql://localhost/mydb
```

This checks:
- ✅ Tables and columns exist
- ✅ Column count matches VALUES
- ✅ Data types are compatible
- ⏳ Foreign key references (future)
- ⏳ Uniqueness constraints (future)

## Output Formats

### Text (Default)

Human-readable table format:

```bash
confiture seed validate
```

```
Seed Validation Report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Files scanned: 3
Violations found: 2

Issues found:
┏━━━━━━━━━━━━━━━━┳━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ File           ┃ Line ┃ Issue     ┃ Suggestion┃
┡━━━━━━━━━━━━━━━━╇━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━┩
│ users.sql      │ 1    │ DOUBLE_   │ Remove    │
│                │      │ SEMICOLON │ extra     │
│                │      │           │ semicolon │
└────────────────┴─────┴───────────┴───────────┘
```

### JSON

Machine-readable JSON format:

```bash
confiture seed validate --format json
```

```json
{
  "violations": [
    {
      "pattern": "DOUBLE_SEMICOLON",
      "line_number": 1,
      "file_path": "db/seeds/common/users.sql",
      "suggestion": "Remove the extra semicolon (;;)",
      "fix_available": false
    }
  ],
  "violation_count": 1,
  "files_scanned": 3,
  "has_violations": true
}
```

### Save to File

```bash
confiture seed validate --format json --output report.json
```

## Pre-Commit Hook Integration

Validate seeds before committing to catch issues early:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: confiture-seed-validate
        name: Confiture Seed Validation
        entry: confiture seed validate --all
        language: system
        stages: [commit]
        files: '^db/seeds/'
```

Install and run:
```bash
pre-commit install
pre-commit run confiture-seed-validate --all-files
```

## CI/CD Integration

Add seed validation to your GitHub Actions workflow:

```yaml
# .github/workflows/quality-gate.yml
- name: Validate seed data
  run: confiture seed validate --all --format json --output validation-report.json
```

## Exit Codes

- `0` - All seed files are valid
- `1` - Violations found
- `2` - Error (e.g., directory not found, database connection failed)

Use exit codes in scripts:

```bash
confiture seed validate
if [ $? -eq 1 ]; then
  echo "Seed validation failed!"
  exit 1
fi
```

## Best Practices

### 1. Keep Seeds Idempotent

Always include `ON CONFLICT` to allow re-running:

```sql
INSERT INTO users (id, name) VALUES (1, 'admin') ON CONFLICT DO NOTHING;
```

### 2. Organize by Environment

```
db/seeds/
├── common/          # Loaded in all environments
│   ├── users.sql
│   └── roles.sql
├── development/     # Development-specific
│   └── test_data.sql
└── test/            # Test environment only
    └── fixtures.sql
```

### 3. Use Descriptive Filenames

```
db/seeds/
├── 001_users.sql              # ✅ Clear ordering
├── 002_user_roles.sql
└── 003_roles.sql
```

### 4. One Concern Per File

Keep related data together:

```
db/seeds/common/
├── users.sql                   # User records
├── roles.sql                   # Role records
└── user_roles.sql              # Assignments
```

### 5. Run Validation in CI/CD

Catch issues before they reach production:

```bash
confiture seed validate --all --strict
```

## Common Patterns

### Inserting Multiple Records

```sql
INSERT INTO users (id, email) VALUES
  (1, 'admin@example.com'),
  (2, 'user@example.com')
ON CONFLICT (id) DO NOTHING;
```

### Conditional Inserts (When Needed)

For complex logic, use a migration file instead:

```python
# db/migrations/001_seed_initial_data.py
from confiture.models import Migration

class SeedInitialData(Migration):
    def up(self, connection):
        cursor = connection.cursor()
        cursor.execute("""
            INSERT INTO users (id, email) VALUES (1, 'admin@example.com')
            ON CONFLICT DO NOTHING;
        """)
```

### Referencing Other Tables

Ensure dependent tables exist:

```sql
-- First: users.sql
INSERT INTO users (id, email) VALUES (1, 'admin@example.com') ON CONFLICT DO NOTHING;

-- Second: user_roles.sql (runs after users)
INSERT INTO user_roles (user_id, role_id) VALUES (1, 1) ON CONFLICT DO NOTHING;
```

## Troubleshooting

### "Seeds directory not found"

```bash
# Check path exists
ls -la db/seeds/

# Validate with absolute path
confiture seed validate --seeds-dir /full/path/to/db/seeds
```

### "Seed files are valid" but validation still reports issues

```bash
# Run validation with verbose output
confiture seed validate --format json | jq '.violations'
```

### auto-fix didn't fix all issues

Some issues can't be auto-fixed:

- `DOUBLE_SEMICOLON` - manual fix required
- `NON_INSERT_STATEMENT` - must move to schema files

Only `MISSING_ON_CONFLICT` is auto-fixable.

## Next Steps

- Add seed validation to your pre-commit hooks
- Integrate into GitHub Actions for CI/CD
- Run `confiture seed validate --all` regularly
- Use `--fix` to standardize ON CONFLICT usage

## See Also

- [Seed Files Guide](../getting-started.md#seed-files)
- [CLI Reference](../reference/cli.md#seed)
- [Migration Validation](../guides/migration-validation.md)
- [Prep-Seed Validation](./prep-seed-validation.md) - UUID to BIGINT transformation validation
