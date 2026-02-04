# Build-Time Validation Guide

Confiture includes three complementary validation features to catch schema errors before deployment. This guide explains each feature, how to configure them, and best practices.

---

## Overview

The build process includes optional validation at three stages:

```
SchemaBuilder.build()
  ├─> Find SQL files
  ├─> ① Comment Validation (enabled by default)
  │   └─> Catch unclosed block comments that corrupt schemas
  ├─> Generate schema
  ├─> ② Separators (block_comment style by default)
  │   └─> Prevent comment spillover between files
  └─> ③ Schema Linting (disabled by default, opt-in)
      └─> Enforce naming conventions and best practices
```

**All three features are optional and configurable per environment.**

---

## 1. Comment Validation

### What It Does

Comment validation **detects unclosed SQL block comments** before they corrupt your concatenated schema. Two types of errors are detected:

1. **Unclosed Block Comments**: `/* comment` without matching `*/`
2. **File Spillover**: File ends while inside an unclosed comment

### Why It Matters

When schemas are concatenated, an unclosed comment in one file silently comments out all subsequent files:

```sql
-- File 1:
SELECT * FROM users;
/* This comment is unclosed

-- File 2:
CREATE TABLE products (...)  -- This is now commented out!
```

Without validation, the subsequent file's SQL is silently ignored.

### Configuration

```yaml
build:
  validate_comments:
    enabled: true                 # Default: true (enabled)
    fail_on_unclosed_blocks: true  # Fail if `/*` without `*/`
    fail_on_spillover: true        # Fail if file ends in comment
```

### Examples

**Valid schema (passes validation)**:
```sql
-- This is a line comment
SELECT 1;

/* This is a block comment */ SELECT 2;

/*
  Multi-line
  block comment
*/
SELECT 3;
```

**Invalid schema (fails validation)**:
```sql
/* Unclosed comment
SELECT 1;
```

Error output:
```
SchemaError: Comment validation failed:
  db/schema/01_tables.sql:1 - Unclosed block comment starting at line 1.
  File ends while still inside comment.
```

### Disabling Validation

To disable comment validation (not recommended):

```yaml
build:
  validate_comments:
    enabled: false
```

Or use alternative separator styles that prevent spillover:

---

## 2. File Separators

### What They Do

File separators are visual dividers between concatenated SQL files. Confiture supports multiple styles, with **block comment separators being safer** (immune to spillover).

### Separator Styles

#### Block Comment (Recommended)
```sql
/* ==========================================
 * File: db/schema/10_tables/users.sql
 * ========================================== */
```

**Advantages:**
- Immune to spillover (if previous file ends with `/*`, this separator's `*/` closes it)
- Clear visual boundary
- Professional appearance

#### Line Comment (Default for Rust Extension)
```sql
-- ==========================================
-- File: db/schema/10_tables/users.sql
-- ==========================================
```

**Advantages:**
- Traditional style
- Compatible with Rust fast path
- Familiar to SQL users

#### MySQL
```sql
# ==========================================
# File: db/schema/10_tables/users.sql
# ==========================================
```

**Use when:** Working with MySQL databases

### Configuration

```yaml
build:
  separators:
    style: block_comment  # Default (safe)
    # Options: block_comment, line_comment, mysql, custom
```

### Custom Separators

For custom separators, use a template with `{file_path}` placeholder:

```yaml
build:
  separators:
    style: custom
    custom_template: "\n/* FILE: {file_path} */\n"
```

### Examples

**Generate schema with block comment separators:**
```bash
confiture build --env local
```

Output:
```sql
-- ============================================
-- PostgreSQL Schema for Confiture
-- ============================================

/* ==========================================
 * File: 01_tables.sql
 * ========================================== */

CREATE TABLE users (...);

/* ==========================================
 * File: 02_indexes.sql
 * ========================================== */

CREATE INDEX idx_users_name ...;
```

---

## 3. Schema Linting

### What It Does

Schema linting validates your SQL against best practices:
- Naming conventions
- Primary key requirements
- Documentation standards
- Missing indexes
- Security issues

### Why Use It

Linting catches schema design issues early, before they reach production.

### Configuration

```yaml
build:
  lint:
    enabled: false              # Default: disabled (opt-in)
    fail_on_error: true         # Fail on critical issues
    fail_on_warning: false      # Warnings don't fail (optional)
    rules:
      - naming_convention       # Table/column names follow conventions
      - primary_key             # All tables have primary keys
      - documentation           # Tables/columns are documented
      - missing_index           # Detect missing indexes
      - security                # Security best practices
```

### Examples

**Enable linting in development:**
```yaml
build:
  lint:
    enabled: true
    fail_on_error: true
    fail_on_warning: false
```

**Strict linting in CI/CD:**
```yaml
build:
  lint:
    enabled: true
    fail_on_error: true
    fail_on_warning: true       # Treat warnings as errors
```

**Selective rules:**
```yaml
build:
  lint:
    enabled: true
    rules:
      - naming_convention
      - primary_key
      # Documentation not required
```

---

## Configuration Examples

### Local Development (Safe Defaults)

```yaml
# db/environments/local.yaml
name: local
database_url: "postgresql://localhost/mydb"
include_dirs:
  - db/schema
exclude_dirs: []

build:
  sort_mode: alphabetical

  # Comment validation: catch errors early
  validate_comments:
    enabled: true
    fail_on_unclosed_blocks: true
    fail_on_spillover: true

  # Safe separators
  separators:
    style: block_comment

  # Optional: enable linting in development
  lint:
    enabled: true
    fail_on_error: true
    fail_on_warning: false
```

### Production (Verified Schemas)

```yaml
# db/environments/production.yaml
name: production
database_url: "postgresql://prod-host/database"
include_dirs:
  - db/schema
exclude_dirs: []

build:
  sort_mode: alphabetical

  # Validation should have already passed in CI/CD
  validate_comments:
    enabled: false  # Trust CI validation

  separators:
    style: line_comment  # Use fast path

  lint:
    enabled: false  # Linting already done
```

### CI/CD (Strictest)

```yaml
# db/environments/ci.yaml
name: ci
database_url: "postgresql://ci-test-db/test"
include_dirs:
  - db/schema
exclude_dirs: []

build:
  sort_mode: alphabetical

  # Strict validation
  validate_comments:
    enabled: true
    fail_on_unclosed_blocks: true
    fail_on_spillover: true

  separators:
    style: block_comment  # Safest option

  # Comprehensive linting
  lint:
    enabled: true
    fail_on_error: true
    fail_on_warning: true        # Treat warnings as errors
    rules:
      - naming_convention
      - primary_key
      - documentation
      - missing_index
      - security
```

---

## Error Messages & Troubleshooting

### Comment Validation Errors

**Error: "Unclosed block comment starting at line X"**

Find line X in the file and check for unmatched `/*` or `*/`:

```bash
# Search for comment markers
grep -n "/\*\|^\*/" db/schema/my_file.sql
```

**Fix:** Add the missing `*/` or remove the unmatched `/*`

**Error: "File ends while still inside comment"**

The file ends inside an unclosed comment. Check the end of the file:

```bash
tail -5 db/schema/my_file.sql  # Check last 5 lines
```

**Fix:** Close the comment with `*/` before the end of file

### Separator Style Errors

**Error: "Invalid separator style: XXX"**

Check `build.separators.style` in your config. Valid options are:
- `block_comment`
- `line_comment`
- `mysql`
- `custom` (requires custom_template)

### Linting Errors

**Error: "Linting failed: Table 'users' has no documentation"**

Add a comment before the table:

```sql
-- Table: users
-- Stores user account information
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    -- Column: user email address
    email VARCHAR(255) NOT NULL,
    ...
);
```

---

## Best Practices

### 1. Enable Comment Validation in Development

Comment errors are silent and destructive. Catch them early:

```yaml
build:
  validate_comments:
    enabled: true  # Always in dev
```

### 2. Use Block Comment Separators

More defensive against spillover:

```yaml
build:
  separators:
    style: block_comment  # Recommended
```

### 3. Document Your Schema

Add comments to tables and important columns:

```sql
-- Table: users
-- Core user account table
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    -- User's email address (unique)
    email VARCHAR(255) UNIQUE NOT NULL,
    -- User's full name
    name VARCHAR(255),
    -- When account was created
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 4. Use Environment-Specific Config

Different environments need different validation levels:

```yaml
# Local: catch everything early
# Production: trust CI/CD
# CI/CD: strictest validation
```

### 5. Test Your Migrations

Before deploying:

```bash
# Build the schema locally
confiture build --env local

# Verify it compiles
psql -f generated/schema.sql -d test_db

# Check for warnings
confiture lint --env local
```

---

## CLI Usage

### Build with Default Validation

```bash
confiture build --env local
```

### Disable Validation

```bash
# Note: validation is controlled by config, not CLI flags (yet)
# Edit your environment config instead
```

### Run Specific Environment

```bash
confiture build --env production  # Uses prod validation rules
```

---

## Advanced Topics

### Performance Tuning

**Comment validation overhead:** ~100-200ms for 100 files (Python) or ~20ms (Rust)

To skip validation in production:

```yaml
build:
  validate_comments:
    enabled: false  # Already validated in CI/CD
```

### Custom Validation

For environment-specific validation, create separate config files:

```
db/environments/
  ├── local.yaml        # Development (strict)
  ├── ci.yaml          # CI/CD (very strict)
  └── production.yaml  # Production (minimal)
```

### Rust Extension

The Rust extension provides 10-50x speedup for schema building. It's used automatically when:

1. Rust extension is installed
2. Separator style is `line_comment` (Rust uses this style)

For other separator styles, the Python implementation is used automatically.

---

## See Also

- **[Configuration Reference](../reference/configuration.md)** - Complete configuration options
- **[Schema Linting Guide](./schema-linting.md)** - Deep dive into linting rules
- **[CLI Reference](../reference/cli.md)** - All CLI commands

---

## Feedback

Have questions about validation? Open an issue:
https://github.com/evoludigit/confiture/issues
