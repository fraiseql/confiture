# Migration Naming Best Practices

[← Back to Guides](../index.md) · [Incremental Migrations](02-incremental-migrations.md) · [Advanced Patterns →](advanced-patterns.md)

**Follow the migration naming convention to ensure all your migrations are discovered and applied**

---

## Overview

Confiture has a strict migration naming convention to ensure **deterministic file discovery** and **prevent silent failures**. Misnamed migration files are silently ignored, which can lead to production failures.

> **Core principle**: Migration file names follow a predictable pattern so Confiture can reliably find and apply them.

---

## The Three Patterns

Confiture recognizes **exactly three** migration file patterns:

### 1. Python Class Migrations

```
{NNN}_{name}.py

Where:
- {NNN}: Version number (001, 042, 100, etc.)
- {name}: Descriptive snake_case name
- .py: Python file extension
```

**Examples**:
```
001_create_users.py
002_add_email.py
003_create_posts.py
042_add_user_bio.py
100_refactor_schema.py
```

**Requirements**:
- Version number starts the filename
- Underscore separates version from name
- Snake case for name (lowercase with underscores)
- `.py` extension

### 2. SQL Forward Migrations

```
{NNN}_{name}.up.sql

Where:
- {NNN}: Version number (001, 042, 100, etc.)
- {name}: Descriptive snake_case name
- .up: Indicates forward migration
- .sql: SQL file extension
```

**Examples**:
```
001_create_users.up.sql
002_add_email.up.sql
003_create_posts.up.sql
042_add_user_bio.up.sql
100_refactor_schema.up.sql
```

**Requirements**:
- Version number starts the filename
- Underscore separates version from name
- `.up.sql` suffix (not `.sql`!)
- Snake case for name

### 3. SQL Rollback Migrations

```
{NNN}_{name}.down.sql

Where:
- {NNN}: Version number (same as corresponding .up.sql)
- {name}: Same name as corresponding .up.sql
- .down: Indicates rollback migration
- .sql: SQL file extension
```

**Examples**:
```
001_create_users.down.sql
002_add_email.down.sql
003_create_posts.down.sql
042_add_user_bio.down.sql
100_refactor_schema.down.sql
```

**Requirements**:
- Version number and name MUST match corresponding `.up.sql` file
- `.down.sql` suffix (not `.sql`!)
- Present for each forward migration (unless read-only DDL)

---

## Common Mistakes

### ❌ Mistake 1: Missing `.up` Suffix

```
❌ WRONG:
001_create_users.sql          # Missing .up!

✅ CORRECT:
001_create_users.up.sql
```

**What happens**: File is silently ignored, migration is never applied.

**Fix**:
```bash
# Rename manually
mv db/migrations/001_create_users.sql db/migrations/001_create_users.up.sql

# Or use auto-fix
confiture migrate validate --fix-naming
```

### ❌ Mistake 2: Inconsistent Version Numbers

```
❌ WRONG:
002_add_email.up.sql
003_add_email.down.sql        # Version 003, but forward migration is 002!

✅ CORRECT:
002_add_email.up.sql
002_add_email.down.sql        # Same version number
```

**What happens**: Confiture might not pair them correctly.

**Fix**: Keep version numbers identical for paired up/down files.

### ❌ Mistake 3: Non-Snake Case Names

```
❌ WRONG:
001_AddEmailField.py          # PascalCase
001_add-email-field.py        # Kebab-case
001_add email field.py        # Spaces

✅ CORRECT:
001_add_email_field.py        # snake_case
```

**What happens**: While still discoverable, inconsistent naming makes scripts harder to parse.

**Fix**: Always use snake_case for migration names.

### ❌ Mistake 4: Starting with Non-Numeric

```
❌ WRONG:
schema_001_create_users.py    # Doesn't start with number
v001_create_users.py          # Starts with 'v'
release_001_create_users.py   # Starts with text

✅ CORRECT:
001_create_users.py           # Starts with number
```

**What happens**: Confiture won't find the file.

**Fix**: Always start filename with the version number.

---

## Version Numbering Schemes

### Simple Sequential (Most Projects)

```
001_create_users.up.sql
002_add_email.up.sql
003_create_posts.up.sql
004_add_post_tags.up.sql
005_add_indexes.up.sql
```

**Pros**: Simple, obvious
**Cons**: Hard to insert gaps

### Decade Spacing (Good for Growth)

```
010_create_users.up.sql
020_add_email.up.sql
030_create_posts.up.sql
040_add_post_tags.up.sql
050_add_indexes.up.sql
```

**Pros**: Easy to insert `015_new_migration.up.sql` between 010 and 020
**Cons**: Uses larger numbers (001-999)

### Grouped by Layer (Complex Projects)

```
# Users domain
001_create_users.up.sql
002_add_user_profile.up.sql
003_add_user_settings.up.sql

# Posts domain
101_create_posts.up.sql
102_add_post_tags.up.sql
103_add_post_reactions.up.sql

# Indexes (always last)
201_add_all_indexes.up.sql
```

**Pros**: Groups related migrations, easy to understand
**Cons**: Requires more coordination

### Timestamp-Based (Distributed Teams)

```
20260127_001_alice_add_users.up.sql
20260127_002_bob_add_posts.up.sql
20260127_003_alice_add_indexes.up.sql
```

**Pros**: Prevents merge conflicts in distributed teams
**Cons**: Harder to read and order correctly

---

## Best Practices

### 1. Use Decade Spacing from Day One

Even if you only have a few migrations, use spacing (010, 020, 030) instead of (001, 002, 003). You'll thank yourself later when you need to insert migrations:

```
010_create_users.up.sql
020_add_email.up.sql
025_add_email_indexes.up.sql    # ← Easy to insert!
030_create_posts.up.sql
```

### 2. Name Migrations Descriptively

**Bad**:
```
001_init.py                 # What is initialized?
002_changes.py              # What changes?
003_fix.py                  # What is fixed?
```

**Good**:
```
001_create_users_table.py
002_add_email_to_users.py
003_create_posts_table.py
```

### 3. One Migration Per Feature (Usually)

```
❌ WRONG: Too many changes in one migration
020_add_email_add_phone_add_address.py

✅ BETTER: One change per migration
020_add_email.up.sql
021_add_phone.up.sql
022_add_address.up.sql
```

**Exception**: Related changes can be grouped:
```
✅ OK: Related changes together
020_add_email_and_email_index.up.sql
```

### 4. Always Create `.down` Migrations

Even if you think you won't need to rollback, create `.down` migrations for safety:

```
✅ GOOD:
001_create_users.up.sql      # CREATE TABLE users (...)
001_create_users.down.sql    # DROP TABLE users

❌ AVOID:
001_create_users.up.sql      # No down migration!
```

### 5. Use Consistent Naming for Paired Files

Keep version and name identical for up/down files:

```
✅ CORRECT:
001_add_email.up.sql
001_add_email.down.sql     # Same version and name

❌ WRONG:
001_add_email.up.sql
002_remove_email.down.sql  # Different version and name!
```

### 6. Document Your Numbering Scheme

In your project's README or a `db/migrations/README.md`:

```markdown
# Migration Numbering Scheme

## Version Ranges

- **001-099**: Users and authentication
- **101-199**: Posts and content
- **201-299**: Indexes and performance
- **301-399**: Views and aggregations

## Example

010_create_users.up.sql      ← Users domain
020_add_email.up.sql         ← Users domain
030_create_posts.up.sql      ← Posts domain
110_create_comments.up.sql   ← Posts domain

## How to Add a New Migration

1. Find the appropriate version range
2. Pick next available number
3. Create both .up.sql and .down.sql files
```

---

## Validating Your Migrations

### Use `confiture migrate validate`

This command checks your migration files and helps fix naming issues:

```bash
# Check for orphaned files
confiture migrate validate

# Preview fixes (dry-run)
confiture migrate validate --fix-naming --dry-run

# Actually fix the files
confiture migrate validate --fix-naming
```

### In CI/CD Pipelines

Add validation to your pipeline to catch naming issues early:

```yaml
# .github/workflows/validate.yml
name: Validate Migrations
on: [pull_request, push]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: "3.11"

      - name: Install confiture
        run: pip install confiture

      - name: Validate migration naming
        run: |
          confiture migrate validate --format json --output validation-report.json

      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: validation-report
          path: validation-report.json
```

### Manual Verification

Check that all `.sql` files in `db/migrations/` match the pattern:

```bash
# List all migration files
ls -1 db/migrations/

# Expected output:
001_create_users.py
002_add_email.up.sql
002_add_email.down.sql
003_create_posts.up.sql
003_create_posts.down.sql

# Unexpected output (❌ would be silently ignored):
001_initial_schema.sql       # Missing .up
002_add_columns.sql          # Missing .up
```

---

## Migration File Content Guidelines

### Python Migrations

```python
# db/migrations/002_add_email.py
"""Add email column to users table with index"""

from confiture.models.migration import Migration

class AddEmail(Migration):
    version = "002"
    name = "add_email"

    def up(self):
        """Apply migration: add email column and index"""
        self.execute("ALTER TABLE users ADD COLUMN email TEXT UNIQUE")
        self.execute("CREATE INDEX idx_users_email ON users(email)")

    def down(self):
        """Rollback migration: remove email column and index"""
        self.execute("DROP INDEX IF EXISTS idx_users_email")
        self.execute("ALTER TABLE users DROP COLUMN IF EXISTS email")
```

### SQL Migrations

```sql
-- db/migrations/002_add_email.up.sql
-- Add email column to users table with index

ALTER TABLE users ADD COLUMN email TEXT UNIQUE;
CREATE INDEX idx_users_email ON users(email);
```

```sql
-- db/migrations/002_add_email.down.sql
-- Rollback: remove email column and index

DROP INDEX IF EXISTS idx_users_email;
ALTER TABLE users DROP COLUMN IF EXISTS email;
```

---

## Troubleshooting

### Q: Why is my migration not being applied?

**A**: Most likely the filename doesn't match the expected pattern. Run:

```bash
confiture migrate validate
```

If you see your migration listed under "Orphaned migration files", rename it:

```bash
# Example: 001_schema.sql → 001_schema.up.sql
confiture migrate validate --fix-naming
```

### Q: Can I have migrations without version numbers?

**A**: No. Confiture **requires** version numbers at the start of every migration filename. This ensures:
- Deterministic ordering
- No accidental collisions
- Clear audit trail

### Q: Can I use different naming schemes in the same project?

**A**: Technically yes, but don't. Consistency is more important:

```
❌ INCONSISTENT (Don't do this):
001_users.py
002_add_email.sql         # Different pattern!
003_add_posts.down.sql    # Different pattern!

✅ CONSISTENT:
001_create_users.py
002_add_email.up.sql
002_add_email.down.sql
003_create_posts.py
```

### Q: What if I have 1000+ migrations?

**A**: Still use the same naming pattern. If you need better organization, consider:
1. Using decade spacing (001, 010, 020) for logical groups
2. Documenting ranges: "001-099 = Users, 101-199 = Posts, etc."
3. Adding comments to `db/migrations/README.md`

---

## Summary

✅ **DO**:
- Start filenames with version number: `001`, `002`, `003`
- Use `.up.sql` and `.down.sql` suffixes for SQL migrations
- Use snake_case for migration names
- Use decade spacing: 001, 010, 020, 030 (not 001, 002, 003, 004)
- Create `.down` migrations for every `.up` migration
- Validate with `confiture migrate validate`

❌ **DON'T**:
- Create `.sql` files without `.up` suffix
- Mix version numbers for up/down pairs
- Use PascalCase or kebab-case names
- Start filenames with non-numeric characters
- Skip `.down` migrations
- Assume Confiture will apply misnamed migrations

---

## Related Documentation

- **[Incremental Migrations Guide](02-incremental-migrations.md)** - How to write good migrations
- **[CLI Reference: validate command](../reference/cli.md)** - Detailed command documentation
- **[Troubleshooting](../troubleshooting.md)** - Solutions for common problems
- **[Advanced Migration Patterns](advanced-patterns.md)** - Complex scenarios

---

## See Also

- **[GitHub Issue #13](https://github.com/evoludigit/confiture/issues/13)** - Migration discovery validation discussion
- **[Organizing SQL Files](../organizing-sql-files.md)** - Schema file naming (different from migrations)

---

*Part of [Confiture](../../README.md) - PostgreSQL migrations, sweetly done 🍓*
