# Example 7: Comment Validation & File Separators

This example demonstrates the comment validation feature in Confiture and how to use CLI flags to override configuration.

## The Problem

When concatenating SQL files, unclosed block comments can corrupt the entire schema:

```sql
-- File 1: users.sql (UNCLOSED COMMENT!)
/* This comment is never closed

-- File 2: posts.sql (This becomes part of the comment!)
CREATE TABLE posts (id INT PRIMARY KEY);

-- Result: SQL syntax error!
```

The issue is **silent** - you get a corrupted schema without obvious error messages.

## The Solution

Comment validation detects:
1. **Unclosed block comments** - Comments that span files
2. **Comment spillover** - Files ending inside a block comment

## Project Structure

```
db/
├── schema/
│   ├── 10_tables.sql       # Valid SQL with proper comments
│   ├── 20_views_safe.sql   # Safe views file
│   └── 20_views_broken.sql # UNCLOSED COMMENT (for testing)
├── environments/
│   ├── unsafe.yaml         # No validation (dangerous)
│   ├── safe.yaml           # With validation
│   └── production.yaml      # Strict validation
└── generated/
    └── (output files)
```

## Quick Start

### 1. Try Unsafe Build (No Validation)

This build will **succeed** but produce invalid SQL:

```bash
# Use unsafe.yaml (validation disabled)
confiture build --env unsafe

# Or override with CLI flag
confiture build --no-validate-comments

# Output: db/generated/schema_unsafe.sql
# ⚠️  Contains syntax errors!
```

### 2. Try Safe Build (With Validation)

This build will **fail** because of the unclosed comment:

```bash
# Use safe.yaml (validation enabled)
confiture build --env safe

# Or override with CLI flag
confiture build --validate-comments

# Output:
# ❌ Comment validation failed:
#   db/schema/20_views_broken.sql:5 - Unclosed block comment
```

### 3. Fix and Rebuild

Remove the broken file:

```bash
rm db/schema/20_views_broken.sql

# Now rebuild with validation
confiture build --env safe --validate-comments

# ✅ Success!
# Output: db/generated/schema_safe.sql
```

## CLI Flag Examples

### Comment Validation Flags

```bash
# Enable validation (catches problems)
confiture build --validate-comments

# Disable validation (for legacy schemas)
confiture build --no-validate-comments

# Strict: fail on unclosed comments
confiture build --validate-comments --fail-on-unclosed

# Strict: fail on spillover
confiture build --validate-comments --fail-on-spillover

# Very strict: fail on any issue
confiture build --validate-comments --fail-on-unclosed --fail-on-spillover
```

### Separator Style Flags

```bash
# Block comment separators (safest)
confiture build --separator-style block_comment
# Result: /* File: db/schema/10_tables.sql */

# Line comment separators (faster)
confiture build --separator-style line_comment
# Result: -- File: db/schema/10_tables.sql

# Custom separators
confiture build --separator-style custom --separator-template "\n/* ===== {file_path} ===== */\n"
```

### Combined Overrides

```bash
# Strict CI/CD build
confiture build --env unsafe \
  --validate-comments \
  --fail-on-unclosed \
  --fail-on-spillover \
  --separator-style block_comment

# Production build
confiture build --env production \
  --validate-comments \
  --separator-style block_comment
```

## Environment Configuration

### Unsafe Configuration

```yaml
build:
  validate_comments:
    enabled: false  # No validation!
```

**When to use:** Never in production. Only for legacy schemas with known issues.

### Safe Configuration

```yaml
build:
  validate_comments:
    enabled: true
    fail_on_unclosed_blocks: true
    fail_on_spillover: true
  separators:
    style: block_comment  # Safest
```

**When to use:** Development and CI/CD.

### Production Configuration

```yaml
build:
  validate_comments:
    enabled: true
    fail_on_unclosed_blocks: true
    fail_on_spillover: true
  separators:
    style: block_comment
```

**When to use:** Always. Validates everything.

## Test Scenarios

### Scenario 1: Validation Catches Errors

```bash
# Set up broken schema
touch db/schema/20_views_broken.sql

# Try to build with validation
confiture build --env safe --validate-comments

# ❌ Fails with clear error message
```

### Scenario 2: Override Config at CLI

```bash
# Config says no validation, but CLI enables it
confiture build --env unsafe --validate-comments

# ❌ Fails (CLI override takes precedence)
```

### Scenario 3: Separator Style Override

```bash
# Config uses line_comment, but CLI says block_comment
confiture build --env unsafe --separator-style block_comment

# Output uses block comment separators
```

## Best Practices

### For Local Development

```yaml
build:
  validate_comments:
    enabled: true        # Catch errors early
  separators:
    style: block_comment # Readable output
```

### For CI/CD

```bash
confiture build --env ci \
  --validate-comments \
  --fail-on-unclosed \
  --fail-on-spillover \
  --separator-style block_comment
```

### For Production

```bash
confiture build --env production \
  --validate-comments \
  --separator-style block_comment
```

### For Legacy Schemas

```bash
confiture build --env legacy \
  --no-validate-comments \
  --separator-style line_comment
```

## Troubleshooting

### "Comment validation failed: Unclosed block comment"

**Cause:** Your SQL files have unclosed `/* ... */` comments.

**Solution:**
1. Review the file and line number mentioned
2. Close all block comments: `/* comment */`
3. Rebuild with validation

### "Custom separator style requires --separator-template"

**Cause:** You used `--separator-style custom` without `--separator-template`.

**Solution:** Provide a template:
```bash
confiture build --separator-style custom --separator-template "\n/* FILE: {file_path} */\n"
```

### "Invalid separator style: xyz"

**Cause:** You used an invalid style name.

**Valid styles:**
- `block_comment`
- `line_comment`
- `mysql`
- `custom` (requires `--separator-template`)

## What Gets Validated

### Comment Validation Checks

1. ✅ **Unclosed block comments** (`/* ... without closing */`)
2. ✅ **Comment spillover** (Files that end while inside a comment)
3. ✅ **Line comment integrity** (Line comments are safe)

### What's NOT Checked

- ❌ SQL syntax (use `confiture lint` for that)
- ❌ Semantics or logic
- ❌ Performance issues

## Related Commands

```bash
# Lint schema for SQL issues
confiture lint

# Dry run migration with validation
confiture migrate up --dry-run

# See all configuration options
confiture --help
```

## More Information

- **[Build Validation Guide](../../docs/guides/build-validation.md)** - Deep dive into validation
- **[CLI Reference](../../docs/reference/cli.md)** - All CLI commands
- **[Configuration Reference](../../docs/reference/configuration.md)** - Config options

## Next Steps

1. Try the unsafe build
2. See the validation fail
3. Use CLI flags to override config
4. Compare different separator styles
5. Apply patterns to your own project
