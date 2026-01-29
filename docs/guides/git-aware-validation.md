# Git-Aware Schema Validation

Enable automatic validation of database schema changes using git history. Perfect for CI/CD pipelines, pre-commit hooks, and code review gates.

## Overview

Git-aware validation allows you to:

- **Detect schema drift** - Compare your current schema against any git reference (branch, tag, commit) to find untracked changes
- **Enforce migration accompaniment** - Ensure every schema change has a corresponding migration file
- **Pre-commit validation** - Validate staged changes before commit
- **CI/CD integration** - Enforce validation in GitHub Actions, GitLab CI, or any CI system

## Quick Start

### Basic Usage

```bash
# Check for schema drift against main branch
confiture migrate validate --check-drift --base-ref origin/main

# Ensure DDL changes have migrations
confiture migrate validate --require-migration --base-ref origin/main

# Both checks together
confiture migrate validate --check-drift --require-migration --base-ref origin/main
```

### With JSON Output (CI/CD)

```bash
confiture migrate validate \
  --check-drift \
  --require-migration \
  --base-ref origin/main \
  --format json
```

## Use Cases

### 1. Pre-Commit Hook (Local Validation)

Catch schema issues before committing:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: confiture-validate
        name: Validate schema changes
        entry: confiture migrate validate --check-drift --require-migration --staged
        language: system
        pass_filenames: false
        stages: [commit]
```

**Setup:**
```bash
# Install pre-commit
pip install pre-commit

# Install the hook
pre-commit install

# Test it
git add db/schema/users.sql
pre-commit run  # Will validate before you can commit
```

### 2. GitHub Actions (CI/CD)

Enforce validation on all PRs:

```yaml
# .github/workflows/validate-schema.yml
name: Validate Schema

on: [pull_request, push]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0  # Full history for comparison

      - uses: actions/setup-python@v4
        with:
          python-version: "3.11"

      - name: Install Confiture
        run: pip install confiture

      - name: Validate schema changes
        run: |
          confiture migrate validate \
            --check-drift \
            --require-migration \
            --base-ref origin/main \
            --format json
```

### 3. GitLab CI

```yaml
# .gitlab-ci.yml
validate_schema:
  stage: test
  script:
    - pip install confiture
    - confiture migrate validate \
        --check-drift \
        --require-migration \
        --base-ref origin/main
  only:
    - merge_requests
    - main
```

### 4. Code Review Gate

Prevent merging PRs with schema drift:

```bash
#!/bin/bash
# scripts/validate-schema.sh
set -e

if ! confiture migrate validate \
    --check-drift \
    --require-migration \
    --base-ref origin/main; then
  echo "❌ Schema validation failed"
  echo "You must:"
  echo "  1. Add missing migration files, or"
  echo "  2. Update schema files to match migrations"
  exit 1
fi

echo "✅ Schema validation passed"
```

## Command Reference

### Flags

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--check-drift` | - | Boolean | False | Detect schema differences between git refs |
| `--require-migration` | - | Boolean | False | Ensure DDL changes have migration files |
| `--base-ref` | - | String | `origin/main` | Reference point for comparison |
| `--since` | - | String | None | Alias for `--base-ref` |
| `--staged` | - | Boolean | False | Only validate staged files (pre-commit mode) |
| `--format` | `-f` | String | `text` | Output format: `text` or `json` |
| `--output` | `-o` | Path | None | Save output to file |

### Exit Codes

- **0**: Validation passed - no issues found
- **1**: Validation failed - schema issues detected
- **2**: Error - git not found or invalid configuration

## Decision Tree

Choose the right flags for your workflow:

```
What are you validating?
├─ Local development
│  └─ Use: --staged (pre-commit hook)
│     Commands staged changes only
│
├─ CI/CD pipeline
│  └─ What should we check?
│     ├─ Schema drift only
│     │  └─ Use: --check-drift --base-ref origin/main
│     │
│     ├─ Migration accompaniment only
│     │  └─ Use: --require-migration --base-ref origin/main
│     │
│     └─ Both (recommended)
│        └─ Use: --check-drift --require-migration --base-ref origin/main
│
└─ Manual validation
   └─ Use: --base-ref <branch-or-commit>
      Compares against specific reference

When comparing:
├─ Most recent commit
│  └─ Use: --base-ref HEAD (default context)
│
├─ Last merge to main
│  └─ Use: --base-ref origin/main
│
├─ Tag
│  └─ Use: --base-ref v1.0.0
│
└─ Days ago
   └─ Use: --base-ref HEAD~N
      where N is commits ago
```

## Common Scenarios

### Scenario 1: "I modified the schema but forgot a migration"

**Problem**: You changed `db/schema/users.sql` but didn't create a migration file.

**Detection**:
```bash
confiture migrate validate --require-migration --base-ref origin/main
```

**Output**:
```
❌ DDL changes without migration files
   Changes: 1
   DDL changes found but no migrations added
```

**Solution**:
```bash
# Create a migration file
touch db/migrations/001_add_email_column.up.sql

# Add the migration SQL
echo "ALTER TABLE users ADD COLUMN email TEXT;" >> db/migrations/001_add_email_column.up.sql

# Run validation again
confiture migrate validate --require-migration --base-ref origin/main
# ✅ DDL changes accompanied by migrations
```

### Scenario 2: "I want to ensure my PR doesn't introduce schema drift"

**Problem**: You want to prevent untracked schema changes in code review.

**Solution**:
```bash
confiture migrate validate --check-drift --base-ref origin/main
```

**What it checks**:
- Structural DDL differences (tables, columns, indexes, constraints)
- Ignores whitespace and comment-only changes
- Ignores formatting differences

**If it finds drift**:
```
⚠️  Schema differences detected
  • ADD_TABLE posts
  • ADD_COLUMN users.bio
```

Then either:
1. Add the changes to a migration, or
2. Revert the schema changes until migrations are ready

### Scenario 3: "My git command is hanging"

**Problem**: Validation seems to hang on large repositories.

**Causes**:
- Very large schema files (100MB+)
- Slow git repository
- Network latency (if fetching from remote)

**Solutions**:

```bash
# Use a more recent base to limit diff
confiture migrate validate --check-drift --base-ref HEAD~10

# Or use a specific branch
confiture migrate validate --check-drift --base-ref origin/develop

# Or use a tag closer to current
confiture migrate validate --check-drift --base-ref v1.5.0
```

The command has a 30-second timeout per git operation. If hitting timeout:
1. Check git repo health: `git fsck`
2. Try fetching latest: `git fetch origin`
3. Use a more recent base ref

### Scenario 4: "I'm getting false positives for migration files"

**Problem**: Migration files in non-standard locations are being detected.

**Why**: Validation looks for `db/migrations/*.up.sql` files specifically.

**Valid migration locations**:
```
✅ db/migrations/001_create_users.up.sql
✅ db/migrations/001_create_users.down.sql
✅ db/migrations/v1.5/001_alter_posts.up.sql  (nested in db/migrations)

❌ src/migrations/001_create_users.up.sql (wrong parent directory)
❌ migrations/001_create_users.up.sql (missing db/)
❌ db/migrations/001_create_users.sql (missing .up suffix)
```

If your migrations are in a different location, adjust your setup or use `--require-migration=false` to skip this check.

## Performance Tips

### For Large Repositories

1. **Use recent base refs**
   ```bash
   # Slower: compares against year-old branch
   confiture migrate validate --check-drift --base-ref v1.0.0

   # Faster: compares against recent main
   confiture migrate validate --check-drift --base-ref origin/main
   ```

2. **Limit to recent commits**
   ```bash
   # Compare against last 50 commits
   confiture migrate validate --check-drift --base-ref HEAD~50
   ```

3. **Use specific directories in environment config**
   ```yaml
   # db/environments/local.yaml
   include_dirs:
     - path: db/schema/core  # Only include core tables
       recursive: true
   ```

4. **Cache in CI/CD**
   ```yaml
   # GitHub Actions example
   - name: Cache git operations
     uses: actions/cache@v3
     with:
       path: .git
       key: git-${{ github.sha }}
   ```

### For Pre-Commit Hooks

Pre-commit hooks should be fast (<1 second):

1. **Use `--staged` flag** - Only validates changed files
   ```bash
   confiture migrate validate --check-drift --staged
   ```

2. **Limit scope in CI/CD instead**
   - Run full validation on every commit in CI
   - Run quick validation locally with --staged

## Troubleshooting

### "Not a git repository" error

```
❌ Git validation error: Not a git repository: /path/to/project
```

**Solutions**:
```bash
# Initialize git if needed
git init

# Or cd into git repository root
cd /path/to/git/root
confiture migrate validate --check-drift
```

### "Invalid git reference" error

```
❌ Git validation error: Invalid git reference 'origin/main': fatal: bad revision
```

**Solutions**:
```bash
# List available branches
git branch -a

# Fetch latest from remote
git fetch origin

# Use correct branch name
confiture migrate validate --check-drift --base-ref origin/main
```

### "Command timed out" error

```
❌ Git command timed out listing files at 'origin/main'
```

**Solutions**:
```bash
# Use more recent base
confiture migrate validate --check-drift --base-ref HEAD~10

# Check git repository health
git fsck

# Or fetch fresh data
git fetch origin
```

### Migration files not detected

**Problem**: You added a migration file but validation says "no migrations"

**Check**:
1. File is in `db/migrations/` directory
2. File ends with `.up.sql`
3. File follows pattern: `{NNN}_{name}.up.sql`

**Valid examples**:
```
db/migrations/001_create_users.up.sql     ✅
db/migrations/002_add_email.up.sql        ✅
db/migrations/1_initial.up.sql            ✅

migrations/001_create_users.up.sql        ❌ Wrong location
db/migrations/001_create_users.sql        ❌ Missing .up
db/migrations/create_users.up.sql         ❌ Missing number prefix
```

## Integration Examples

### With FraiseQL

Validate schema before GraphQL generation:

```bash
# 1. Validate schema is in sync
confiture migrate validate --check-drift --require-migration

# 2. If valid, generate GraphQL schema
fraiseql generate

# 3. Run tests
pytest
```

### With GitHub Pages Documentation

Track schema changes in docs:

```yaml
name: Generate Schema Docs

on:
  push:
    branches: [main]
  pull_request:

jobs:
  validate_and_document:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Validate schema
        run: confiture migrate validate --check-drift --base-ref main

      - name: Generate schema docs
        run: confiture doc generate --output docs/schema.md

      - name: Deploy docs
        if: github.ref == 'refs/heads/main'
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: docs
```

### With Database Migrations CI

```bash
#!/bin/bash
# scripts/ci-validate-migrations.sh

set -e

echo "Validating schema migrations..."

# 1. Check drift
echo "Checking for schema drift..."
confiture migrate validate \
  --check-drift \
  --base-ref origin/main

# 2. Check accompaniment
echo "Checking migration accompaniment..."
confiture migrate validate \
  --require-migration \
  --base-ref origin/main

# 3. Test migrations on fresh database
echo "Testing migrations on fresh database..."
confiture build --env test
confiture migrate up --env test

# 4. Run database tests
echo "Running database tests..."
pytest tests/database/

echo "✅ All schema validations passed"
```

## API Reference

### GitRepository Class

```python
from confiture.core.git import GitRepository

repo = GitRepository()  # Uses current directory
repo = GitRepository(Path("/path/to/repo"))

# Check if in git repo
if repo.is_git_repo():
    # Get file at specific ref
    content = repo.get_file_at_ref(Path("db/schema/users.sql"), "HEAD")

    # Get changed files
    files = repo.get_changed_files("origin/main", "HEAD")

    # Get staged files
    staged = repo.get_staged_files()
```

### GitSchemaDiffer Class

```python
from confiture.core.git_schema import GitSchemaDiffer

differ = GitSchemaDiffer(env="local")

# Compare schemas between refs
diff = differ.compare_refs("origin/main", "HEAD")

# Check for DDL changes
if differ.has_ddl_changes(diff):
    for change in diff.changes:
        print(f"Change: {change}")
```

### MigrationAccompanimentChecker Class

```python
from confiture.core.git_accompaniment import MigrationAccompanimentChecker

checker = MigrationAccompanimentChecker(env="local")

# Check if migrations accompany DDL changes
report = checker.check_accompaniment("origin/main", "HEAD")

if report.is_valid:
    print("✅ Valid: DDL has migrations")
else:
    print(f"❌ Invalid: {report.summary()}")

# Get report as JSON for CI/CD
import json
print(json.dumps(report.to_dict()))
```

## Best Practices

### 1. Always Validate Before Merging

```bash
# In CI/CD: Always run before merge
confiture migrate validate --check-drift --require-migration --base-ref origin/main
```

### 2. Keep Migrations Close to Schema Changes

When you change schema in `db/schema/`, immediately create a migration in `db/migrations/`.

### 3. Use Consistent Base References

```bash
# Good: Use same ref in all environments
CI=origin/main
LOCAL=origin/main  # Both use main branch

# Avoid: Using different refs for CI vs local
CI=v1.0.0
LOCAL=HEAD  # Different - causes confusion
```

### 4. Review Diff Output

```bash
# Check what changed before validating
git diff origin/main db/schema/

# Then validate
confiture migrate validate --check-drift --require-migration
```

### 5. Use Pre-Commit Hooks for Local Validation

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: confiture-validate
      name: Validate schema
      entry: confiture migrate validate --check-drift --require-migration --staged
      language: system
      pass_filenames: false
      # Add these for better performance:
      stages: [commit]
      exclude: ^(\.git|vendor)/
```

### 6. Document Schema Changes

Always include a migration file that explains the change:

```sql
-- db/migrations/001_add_email_column.up.sql
-- Adds email column to users table for user contact information
-- Rolled out in: PR #123
ALTER TABLE users ADD COLUMN email TEXT UNIQUE;
CREATE INDEX idx_users_email ON users(email);
```

## Glossary

**Drift**: Schema differences between your current code and a git reference. For example, your `db/schema/` files don't match what was deployed at `origin/main`.

**Accompaniment**: A schema change is "accompanied" if it has a corresponding migration file. Required for tracking and applying changes.

**Staged**: Files that have been added to git with `git add` but not yet committed.

**Ref**: Any git reference: commit hash, branch name, tag, or relative reference (HEAD~5).

**Migration**: A `.up.sql` or `.down.sql` file that applies/reverts a schema change.

## Related Documentation

- [Migration Naming Best Practices](./migration-naming-best-practices.md)
- [Migration Strategies](./migration-decision-tree.md)
- [Pre-Commit Hooks Setup](https://pre-commit.com/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
