# Schema Linting Guide

Schema linting is a quality assurance process that validates your PostgreSQL schema against a set of best practices and conventions. This guide covers everything you need to integrate linting into your development workflow.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Six Linting Rules](#six-linting-rules)
- [Configuration](#configuration)
- [Output Formats](#output-formats)
- [CLI Reference](#cli-reference)
- [Integration](#integration)
- [Troubleshooting](#troubleshooting)
- [Best Practices](#best-practices)

---

## Overview

Schema linting helps teams maintain consistent, maintainable, and secure PostgreSQL databases. It validates schemas against configurable rules and produces detailed reports that guide improvements.

### What is Schema Linting?

Schema linting automatically checks your database schema against a set of predefined rules. Each rule validates a specific aspect of schema design, from naming conventions to security concerns. When violations are found, the linter provides:

- **Detailed violation descriptions** - Exactly what's wrong and where
- **Severity levels** - Errors (must fix), Warnings (should fix), Info (nice to have)
- **Suggested fixes** - How to resolve many violations
- **Structured reports** - JSON or CSV format for automation

### Why Validate Schemas?

Database schemas are critical infrastructure. Inconsistent or poorly designed schemas lead to:

- **Performance problems** - Missing indexes on foreign keys, poor query design
- **Security vulnerabilities** - Unencrypted password fields, improper access controls
- **Maintenance difficulties** - Inconsistent naming makes code harder to understand
- **Data integrity issues** - Missing primary keys or unique constraints
- **Scaling problems** - Multi-tenant systems without proper isolation

Schema linting catches these issues early, before they reach production.

### When to Use Linting

Schema linting is useful in many contexts:

- **Development**: Validate schema changes before committing
- **Code review**: Include lint reports in pull requests
- **CI/CD pipeline**: Fail builds that violate schema rules
- **Production deployments**: Ensure schemas meet production standards
- **Compliance**: Verify security-sensitive schema decisions
- **Onboarding**: Help new team members understand schema conventions

---

## Quick Start

### Installation

Confiture is available on PyPI:

```bash
# Install with pip
pip install confiture

# Or with uv (recommended)
uv pip install confiture
```

### First Lint Command

The simplest way to lint your schema:

```bash
# Lint your default environment
confiture lint
```

This command:

1. Loads your schema from `db/schema/` directory
2. Parses it into tables and columns
3. Runs all enabled rules
4. Displays results in a rich terminal table

### Understanding Output

A typical lint report looks like:

```
Schema Linting Results - production

Tables: 24 checked
Columns: 187 checked
Time: 145ms

Violations

Severity  Rule                  Location        Message
─────────────────────────────────────────────────────────────
ERROR     PrimaryKeyRule        users           Missing PRIMARY KEY
ERROR     NamingConventionRule  user_profiles   Column 'UserID' violates snake_case naming
WARNING   MissingIndexRule      orders          Foreign key order_user_id is not indexed
WARNING   DocumentationRule     products        Missing table documentation
INFO      SecurityRule          users           Password column detected

Summary:
  2 errors
  2 warnings
  1 info

Suggested Fixes:
  users: Add PRIMARY KEY constraint
  user_profiles: Rename 'UserID' to 'user_id'
```

### Common Commands

```bash
# Lint with custom environment
confiture lint --env production

# Output as JSON (for automation)
confiture lint --format json

# Save report to file
confiture lint --format json --output report.json

# Strict mode (fail on warnings too)
confiture lint --fail-on-warning

# Skip error check (warnings only)
confiture lint --no-fail-on-error
```

---

## Six Linting Rules

Confiture includes six built-in rules that validate fundamental aspects of schema design. Each rule is configurable and can be enabled or disabled per environment.

### 1. NamingConventionRule

**Purpose**: Enforce consistent naming conventions (snake_case)

**Validates**:
- Table names use snake_case
- Column names use snake_case
- Index names follow naming patterns
- Schema conventions are consistent

**Severity**: ERROR (violations must be fixed)

**Example Violations**:

```sql
-- BAD: CamelCase table name
CREATE TABLE UserProfiles (
    id INTEGER PRIMARY KEY,
    firstName VARCHAR(100),  -- CamelCase column
    email VARCHAR(255)
);

-- GOOD: snake_case naming
CREATE TABLE user_profiles (
    id INTEGER PRIMARY KEY,
    first_name VARCHAR(100),
    email VARCHAR(255)
);
```

**Suggested Fix**: Rename to snake_case version

**Configuration**:

```yaml
rules:
  naming_convention:
    enabled: true
    style: snake_case  # Only supported style
```

**Why This Matters**: Inconsistent naming creates friction in code:
- SQL is harder to read when mixing naming conventions
- ORM mappings become confusing (user_id vs userId)
- Team members waste time debating naming
- Automated code generation becomes error-prone

### 2. PrimaryKeyRule

**Purpose**: Ensure all tables have a primary key

**Validates**:
- Every table has exactly one PRIMARY KEY constraint
- Excludes PostgreSQL system tables (pg_*)

**Severity**: ERROR (must have for data integrity)

**Example Violations**:

```sql
-- BAD: No primary key
CREATE TABLE audit_logs (
    id INTEGER,
    message TEXT,
    created_at TIMESTAMP
);

-- GOOD: With primary key
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY,
    message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Suggested Fix**: Add `PRIMARY KEY` constraint

**Configuration**:

```yaml
rules:
  primary_key:
    enabled: true  # Always recommended in production
```

**Why This Matters**: Primary keys are fundamental:
- Enable efficient lookups and JOINs
- Prevent duplicate data
- Required for replication and backups
- Essential for ORM operations

### 3. DocumentationRule

**Purpose**: Require table documentation (COMMENT)

**Validates**:
- Tables have meaningful COMMENT text
- Documentation explains table purpose
- Comments are not empty

**Severity**: WARNING (best practice)

**Example Violations**:

```sql
-- BAD: No documentation
CREATE TABLE user_sessions (
    id UUID PRIMARY KEY,
    user_id INTEGER NOT NULL,
    token TEXT NOT NULL,
    expires_at TIMESTAMP
);

-- GOOD: With documentation
CREATE TABLE user_sessions (
    id UUID PRIMARY KEY,
    user_id INTEGER NOT NULL,
    token TEXT NOT NULL,
    expires_at TIMESTAMP
);
COMMENT ON TABLE user_sessions IS 'Active user authentication sessions. Automatically cleaned up after expiration.';
```

**Suggested Fix**: Add meaningful COMMENT

**Configuration**:

```yaml
rules:
  documentation:
    enabled: true   # Recommended for production
    # Can be disabled in development if desired
```

**Why This Matters**: Documentation is crucial for teams:
- New developers understand schema quickly
- Reduces onboarding time
- Clarifies business logic in schema
- Enables better code reviews

### 4. MultiTenantRule

**Purpose**: Enforce multi-tenant table structure

**Validates**:
- Multi-tenant tables have a tenant_id column
- Tenant identifiers are properly indexed
- Prevents accidental data leaks across tenants

**Severity**: ERROR (critical for security)

**Example Violations**:

```sql
-- BAD: No tenant isolation
CREATE TABLE user_settings (
    id UUID PRIMARY KEY,
    user_id INTEGER NOT NULL,
    theme VARCHAR(50),
    notifications_enabled BOOLEAN
);

-- GOOD: With tenant_id
CREATE TABLE user_settings (
    id UUID PRIMARY KEY,
    tenant_id INTEGER NOT NULL,  -- Added
    user_id INTEGER NOT NULL,
    theme VARCHAR(50),
    notifications_enabled BOOLEAN,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);
CREATE INDEX idx_user_settings_tenant_id ON user_settings(tenant_id);
```

**Configuration**:

```yaml
rules:
  multi_tenant:
    enabled: true
    identifier: tenant_id  # Customize if needed
```

**Detecting Multi-Tenant Tables**: The rule uses heuristics to detect multi-tenant tables:
- Presence of tenant_id column
- Multiple clients/organizations sharing the database
- SaaS application architecture

**Why This Matters**: Multi-tenancy is critical for security:
- Prevents data leaks between customers
- Enables efficient resource sharing
- Supports scaling and isolation

### 5. MissingIndexRule

**Purpose**: Detect unindexed foreign keys

**Validates**:
- Foreign key columns have matching indexes
- Join operations are performant
- Query performance doesn't degrade

**Severity**: WARNING (performance impact)

**Example Violations**:

```sql
-- BAD: Foreign key without index
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
    -- Missing indexes on user_id and product_id
);

-- GOOD: Indexes on foreign keys
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);
CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_product_id ON orders(product_id);
```

**Suggested Fix**: Add indexes on foreign key columns

**Configuration**:

```yaml
rules:
  missing_index:
    enabled: true  # Recommended for production
```

**Why This Matters**: Missing indexes cause serious performance issues:
- JOINs become full table scans
- Queries slow exponentially with data growth
- Users experience timeouts and freezes
- Database CPU utilization increases

### 6. SecurityRule

**Purpose**: Detect security-sensitive schema decisions

**Validates**:
- Password fields are not plain text
- Secret columns are flagged for review
- Token columns are identified
- Sensitive data handling is documented

**Severity**: INFO (requires manual review)

**Example Violations**:

```sql
-- BAD: Plain text password
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email VARCHAR(255),
    password VARCHAR(255)  -- FLAGGED: Consider using password_hash
);

-- GOOD: Encrypted or hashed password
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email VARCHAR(255),
    password_hash VARCHAR(255),  -- Using hash
    COMMENT ON COLUMN users.password_hash IS 'Bcrypt hash, never store plain passwords'
);
```

**Detected Patterns**:
- Columns named: password, secret, token, api_key, private_key
- Columns of type VARCHAR/TEXT without length restrictions for sensitive data

**Suggested Fix**: Use appropriate security mechanisms (hashing, encryption, vaults)

**Configuration**:

```yaml
rules:
  security:
    enabled: true  # Always recommended
```

**Why This Matters**: Security violations have serious consequences:
- Breached passwords compromises user accounts
- Exposed secrets allow unauthorized access
- Compliance violations lead to legal issues
- Damage to trust and reputation

---

## Configuration

### Configuration Files

Confiture reads configuration from multiple sources (in order):

1. **Command-line arguments** (highest priority)
2. **confiture.yaml** in project root
3. **Environment variables**
4. **Default configuration** (lowest priority)

### Configuration Reference

Complete configuration example with all options:

```yaml
# confiture.yaml - Schema linting configuration

# Global linting settings
linting:
  enabled: true                    # Enable/disable entire linting system
  fail_on_error: true             # Exit with code 1 if errors found
  fail_on_warning: false          # Exit with code 1 if warnings found (stricter mode)

  # Tables to exclude from linting
  exclude_tables:
    - pg_*                        # PostgreSQL system tables
    - information_schema.*        # Information schema views
    - _timescaledb_*             # TimescaleDB extension tables (if using)

  # Linting rules configuration
  rules:
    # Rule 1: Naming conventions
    naming_convention:
      enabled: true
      style: snake_case           # Only supported style

    # Rule 2: Primary keys
    primary_key:
      enabled: true               # Require PRIMARY KEY on all tables

    # Rule 3: Documentation
    documentation:
      enabled: true               # Require COMMENT on tables
      # Can be disabled in development environments

    # Rule 4: Multi-tenant structure
    multi_tenant:
      enabled: true
      identifier: tenant_id       # Column name to check (customizable)

    # Rule 5: Missing indexes
    missing_index:
      enabled: true               # Warn about unindexed foreign keys

    # Rule 6: Security review
    security:
      enabled: true               # Flag password/secret columns

# Environment-specific overrides
environments:
  development:
    linting:
      fail_on_error: true
      fail_on_warning: false      # Relaxed in development
      rules:
        documentation:
          enabled: false          # Optional in dev
        missing_index:
          enabled: true           # But catch perf issues early

  production:
    linting:
      fail_on_error: true
      fail_on_warning: true       # Strict in production
      rules:
        documentation:
          enabled: true           # Required in production
        missing_index:
          enabled: true           # Catch all perf issues
```

### Environment-Specific Configuration

Different environments have different standards:

```yaml
# Development: Relaxed standards for rapid iteration
dev:
  linting:
    fail_on_error: true
    fail_on_warning: false        # Warnings don't block
    rules:
      documentation:
        enabled: false            # Not required in dev
      security:
        enabled: true             # Still check for obvious issues

# Production: Strict standards for stability
production:
  linting:
    fail_on_error: true
    fail_on_warning: true         # Fail on all violations
    exclude_tables:
      - pg_*
    rules:
      documentation:
        enabled: true             # All tables documented
      missing_index:
        enabled: true             # All perf issues caught
      security:
        enabled: true             # All security reviewed
```

### Excluding Specific Tables

Use glob patterns to exclude tables:

```yaml
linting:
  exclude_tables:
    - pg_*                        # All PostgreSQL system tables
    - information_schema.*        # Information schema
    - old_*                       # Deprecated old tables
    - test_*                      # Test fixture tables
```

---

## Output Formats

Confiture supports three output formats for different use cases.

### Table Format (Terminal)

Default human-readable format with colors and rich formatting.

```bash
confiture lint --format table
```

Output:

```
Schema Linting Results - production

Tables: 15 checked
Columns: 127 checked
Time: 234ms

Violations

Severity  Rule                  Location      Message
─────────────────────────────────────────────────────────
ERROR     PrimaryKeyRule        sessions      Missing PRIMARY KEY
WARNING   MissingIndexRule      orders        Foreign key user_id is not indexed
WARNING   DocumentationRule     products      Missing table documentation

Summary:
  1 error
  0 warnings
  0 info

Suggested Fixes:
  sessions: Add PRIMARY KEY constraint
  orders: CREATE INDEX idx_orders_user_id ON orders(user_id)
```

**Best for**: Development, manual inspection, immediate feedback

### JSON Format

Structured format for automation and programmatic access.

```bash
confiture lint --format json
```

Output:

```json
{
  "schema_name": "production",
  "tables_checked": 15,
  "columns_checked": 127,
  "execution_time_ms": 234,
  "violations": {
    "total": 3,
    "errors": 1,
    "warnings": 2,
    "info": 0,
    "items": [
      {
        "rule": "PrimaryKeyRule",
        "severity": "error",
        "location": "sessions",
        "message": "Missing PRIMARY KEY",
        "suggested_fix": "Add PRIMARY KEY constraint"
      },
      {
        "rule": "MissingIndexRule",
        "severity": "warning",
        "location": "orders",
        "message": "Foreign key user_id is not indexed",
        "suggested_fix": "CREATE INDEX idx_orders_user_id ON orders(user_id)"
      },
      {
        "rule": "DocumentationRule",
        "severity": "warning",
        "location": "products",
        "message": "Missing table documentation",
        "suggested_fix": "Add COMMENT ON TABLE products IS 'Description'"
      }
    ]
  }
}
```

**Best for**: CI/CD pipelines, parsing in scripts, storing in databases

### CSV Format

Spreadsheet-compatible format for analysis.

```bash
confiture lint --format csv
```

Output:

```csv
rule_name,severity,location,message,suggested_fix
PrimaryKeyRule,error,sessions,Missing PRIMARY KEY,Add PRIMARY KEY constraint
MissingIndexRule,warning,orders,Foreign key user_id is not indexed,CREATE INDEX idx_orders_user_id ON orders(user_id)
DocumentationRule,warning,products,Missing table documentation,Add COMMENT ON TABLE products IS 'Description'
```

**Best for**: Spreadsheet analysis, data import, historical tracking

---

## CLI Reference

### Command: `confiture lint`

Validate schema against configured linting rules.

#### Syntax

```bash
confiture lint [OPTIONS]
```

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--env` | `-e` | "local" | Environment to lint (local, development, production, etc.) |
| `--format` | `-f` | "table" | Output format: table, json, or csv |
| `--output` | `-o` | stdout | Save output to file (for json/csv formats) |
| `--fail-on-error` | | true | Exit with code 1 if errors found (default behavior) |
| `--no-fail-on-error` | | | Exit with code 0 even if errors found |
| `--fail-on-warning` | | false | Exit with code 1 if warnings found (strict mode) |
| `--help` | `-h` | | Show help message |

#### Exit Codes

- `0` - No violations found (or only ignored violations)
- `1` - Violations found that match fail criteria
- `2` - Configuration error or invalid environment

#### Examples

```bash
# Basic linting
confiture lint

# Lint production environment
confiture lint --env production

# Generate JSON report
confiture lint --format json --output report.json

# Strict mode (fail on warnings)
confiture lint --fail-on-warning

# Only warnings (ignore errors)
confiture lint --no-fail-on-error

# View help
confiture lint --help
```

---

## Integration

Schema linting integrates into your development workflow at multiple levels.

### Local Development

Lint before committing changes:

```bash
# Check for violations in current work
confiture lint

# Exit code tells you if there are problems
if [ $? -ne 0 ]; then
    echo "Schema violations detected!"
    exit 1
fi
```

### Pre-commit Hooks

Use git pre-commit hooks to lint automatically:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: confiture-lint
        name: confiture lint
        entry: confiture lint --fail-on-error
        language: python
        files: ^db/schema/
        pass_filenames: false
        additional_dependencies: [confiture]
```

### Code Review

Include lint reports in pull requests:

```bash
# Generate report for PR comment
confiture lint --format json > /tmp/lint-report.json

# Parse and comment on violations
python scripts/comment_lint_violations.py /tmp/lint-report.json
```

### CI/CD Pipeline

Fail builds that violate schema rules:

```yaml
# GitHub Actions example
name: Schema Linting
on:
  push:
    branches: [main, develop]
    paths: [db/schema/**]
  pull_request:
    paths: [db/schema/**]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      - run: pip install confiture
      - run: confiture lint --env production --fail-on-warning
```

### Production Deployments

Validate before deploying:

```bash
#!/bin/bash
set -e

echo "Validating schema..."
confiture lint --env production --format json > lint-report.json

# Check for errors
if grep -q '"severity": "error"' lint-report.json; then
    echo "❌ Schema validation failed!"
    cat lint-report.json
    exit 1
fi

echo "✅ Schema validation passed"
# Proceed with deployment
```

---

## Troubleshooting

### Common Issues

#### Issue: "Environment config not found"

**Error**: `ConfigurationError: Environment config not found: /path/to/db/environments/production.yaml`

**Cause**: Configuration file missing or incorrect path

**Solution**:
1. Check environment config exists in `db/environments/`
2. Verify environment name matches file name
3. Create missing environment config

#### Issue: "No violations found" vs "Violations found"

**Cause**: Configuration might be disabling rules or excluding tables

**Solution**:
```bash
# Check which rules are enabled
confiture lint --help | grep -A 20 "rules"

# Review configuration
cat db/environments/production.yaml
```

#### Issue: High number of violations (overwhelming)

**Cause**: Schema has many issues; address incrementally

**Solution**:
```bash
# Focus on errors first
confiture lint --format json | jq '.violations.items[] | select(.severity == "error")'

# Fix one rule at a time
# Then gradually enable stricter rules
```

#### Issue: False positives or irrelevant violations

**Cause**: Rules might not match your schema design

**Solution**:
```yaml
# Disable irrelevant rules for your schema
rules:
  multi_tenant:
    enabled: false  # If not using multi-tenancy
  documentation:
    enabled: false  # If not required in development
```

### Getting Help

- Check examples at `/examples/linting/`
- Review detailed rule descriptions above
- Check configuration reference
- Run `confiture lint --help` for CLI options

---

## Best Practices

### Schema Design Patterns

#### Pattern 1: Always Include Primary Key

```sql
-- GOOD: Clear, efficient primary key
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### Pattern 2: Document Complex Tables

```sql
-- Document the purpose
CREATE TABLE order_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id),
    product_id UUID NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(10, 2) NOT NULL
);
COMMENT ON TABLE order_items IS 'Line items in orders. Links orders to products with quantities and pricing. Denormalized price prevents issues if product price changes.';
```

#### Pattern 3: Index Foreign Keys

```sql
-- Always index foreign key lookups
CREATE TABLE comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id UUID NOT NULL REFERENCES posts(id),
    user_id UUID NOT NULL REFERENCES users(id),
    content TEXT NOT NULL
);
CREATE INDEX idx_comments_post_id ON comments(post_id);
CREATE INDEX idx_comments_user_id ON comments(user_id);
```

### Incremental Adoption

If your schema has many violations, adopt linting incrementally:

**Phase 1: Audit (Warning Level)**
- Enable linting in read-only mode
- Generate reports without failing builds
- Understand the scope of violations

**Phase 2: Fix Critical Issues (Errors)**
- Address error-level violations first
- These are data integrity and security issues
- Set `fail_on_error: true`

**Phase 3: Address Warnings**
- Fix missing indexes and documentation
- Improve schema quality
- Set `fail_on_warning: true` in production

**Phase 4: Maintain Standards**
- Keep linting in CI/CD pipeline
- Prevent new violations from being introduced
- Regularly review and update rules

### Integration with Migrations

Use linting with confiture's migration system:

```bash
# Before applying migrations
confiture lint --env staging

# Check schema after migration
confiture migrate up --env staging
confiture lint --env staging

# Validate production before deploying
confiture lint --env production --fail-on-warning
```

### Team Conventions

Create a `.confiture-standards.md` document for your team:

```markdown
# Schema Linting Standards

## Required Conventions

1. **Naming**: All names must use snake_case
2. **Primary Keys**: All tables must have a PRIMARY KEY
3. **Documentation**: Production tables require COMMENT
4. **Indexes**: All foreign keys must be indexed
5. **Security**: No plain text passwords

## Exceptions

Multi-tenant detection is automatic. If you have edge cases:
- File a GitHub issue with example schema
- Document exception in table comment

## Gradual Adoption

- Development: fail_on_error only
- Staging: fail_on_error and fail_on_warning
- Production: strict mode with all rules enabled
```

### Monitoring and Reporting

Track linting metrics over time:

```bash
#!/bin/bash
# Generate weekly linting report
confiture lint --format json --env production > reports/lint-$(date +%Y-%m-%d).json

# Analyze trends
python scripts/analyze_lint_trends.py reports/
```

---

## Summary

Schema linting is a powerful tool for maintaining schema quality. By integrating linting into your development workflow, you gain:

- **Consistency**: Teams follow the same naming and design patterns
- **Safety**: Catch potential issues before they reach production
- **Performance**: Ensure databases are properly indexed
- **Security**: Detect sensitive data that needs protection
- **Documentation**: Maintain clear, understandable schemas
- **Automation**: Prevent violations through CI/CD gates

Start with basic linting today, and gradually adopt stricter standards as your team matures.

---

## Related Documentation

- **Configuration Reference**: See `confiture.yaml` options above
- **CLI Commands**: Run `confiture lint --help`
- **API Documentation**: See `docs/linting-api.md` (Python developers)
- **Examples**: Check `examples/linting/` for working code
- **GitHub Issues**: Report bugs or request features
