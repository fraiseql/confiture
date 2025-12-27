# Schema Linting

**Validate schema files against best practices and custom rules**

---

## What is Schema Linting?

Schema linting analyzes your DDL files for common issues, naming violations, and performance problems before you deploy. It's like a spell-checker for SQL schema.

### Key Concept

> **"Catch schema mistakes before they hit production"**

Linting prevents bad designs early, enforces team standards, and improves long-term database health.

---

## When to Use Schema Linting

### ✅ Perfect For

- **Pre-deployment validation** - Catch issues before production
- **Team standards** - Enforce consistent naming conventions
- **Performance** - Detect missing indices, bad design
- **Security** - Find PII without encryption, weak constraints
- **Compliance** - Verify GDPR/HIPAA requirements
- **Code review** - Automated feedback on schema changes
- **CI/CD gates** - Block schema changes that violate rules

### ❌ Not For

- **Runtime data validation** - Use database constraints instead
- **Query optimization** - Use query analyzers instead
- **Backup strategy** - Use backup tools instead
- **Access control** - Use row-level security instead

---

## How Linting Works

### The Linting Pipeline

```
confiture lint
     │
     ├─→ Load schema files
     │
     ├─→ Parse SQL
     │
     ├─→ For each object:
     │   ├─ Apply built-in rules
     │   ├─ Apply custom rules
     │   └─ Collect violations
     │
     ├─→ Report issues
     │
     └─→ Exit with code 0 (pass) or 1 (fail)
```

### Rule Categories

| Category | Purpose | Examples |
|----------|---------|----------|
| **Naming** | Enforce conventions | Table names, column names |
| **Structure** | Best practices | Primary keys, timestamps |
| **Security** | Prevent vulnerabilities | PII encryption, weak constraints |
| **Performance** | Optimize queries | Missing indices, N+1 patterns |
| **Compliance** | Meet regulations | Data retention, audit trails |

---

## Running the Linter

### Basic Linting

```bash
# Lint all schema files
confiture lint

# Lint specific file
confiture lint db/schema/10_tables/users.sql

# Lint specific directory
confiture lint db/schema/10_tables/
```

**Output**:
```
🔍 Confiture Schema Linter
═════════════════════════════════════════════════════════════

Scanning: db/schema/ (15 files)

✅ PASS: db/schema/00_common/types.sql (5 objects)
⚠️  WARN: db/schema/10_tables/users.sql (3 issues)
❌ FAIL: db/schema/20_indexes/user_indices.sql (1 critical)

═════════════════════════════════════════════════════════════

Issues Found: 4

⚠️  Warnings (3):
  [W001] users.sql:12 - Column 'created_at' missing type hint comment
  [W002] users.sql:23 - Missing NOT NULL on 'email' column
  [W003] users.sql:45 - Table name uses underscore (prefer snake_case)

❌ Critical (1):
  [C001] user_indices.sql:8 - Index on non-existent column 'user_name'

═════════════════════════════════════════════════════════════

Exit code: 1 (failed)
```

---

## Configuring Rules

### Option 1: YAML Configuration

```yaml
# db/confiture.yaml

linting:
  rules:
    # Built-in rules
    naming:
      table_case: snake_case
      column_case: snake_case
      function_case: snake_case
      max_name_length: 63

    structure:
      require_primary_key: true
      require_timestamps: true
      timestamp_fields:
        - created_at
        - updated_at

    security:
      warn_plain_text_pii: true
      require_password_hash: true
      require_ssl_connections: false

    performance:
      warn_missing_indices: true
      warn_select_star: true
      max_index_columns: 5

  # Custom rules
  custom:
    - name: "email_constraint"
      description: "Ensure all email columns have uniqueness"
      rule: "email_column:unique"

    - name: "audit_table"
      description: "Ensure audit tables have timestamps"
      rule: "created_at:required"
```

### Option 2: Python Rules

```python
# db/linting/rules.py

from confiture.linting import Rule, RuleContext, Violation

class EmailConstraintRule(Rule):
    """Custom rule: email columns must have uniqueness."""

    name = "email_constraint"
    severity = "warning"
    description = "Ensure email columns have unique constraint"

    def check(self, context: RuleContext) -> list[Violation]:
        """Check for email columns without unique constraint."""
        violations = []

        for table in context.schema.tables:
            for column in table.columns:
                if 'email' in column.name.lower():
                    if not column.has_constraint('unique'):
                        violations.append(
                            Violation(
                                rule=self.name,
                                severity=self.severity,
                                table=table.name,
                                column=column.name,
                                message=f"Email column '{column.name}' must have UNIQUE constraint",
                                fix=f"ALTER TABLE {table.name} ADD CONSTRAINT {table.name}__{column.name}_unique UNIQUE ({column.name})"
                            )
                        )

        return violations
```

---

## Example: Naming Convention Rule

**Situation**: Enforce team naming standards (snake_case, no abbreviations).

```yaml
# db/confiture.yaml

linting:
  rules:
    naming:
      table_case: snake_case           # Users → users ✓
      column_case: snake_case          # UserName → user_name ✓
      index_prefix: idx_               # idx_users_email ✓
      foreign_key_prefix: fk_          # fk_users_id ✓
      max_name_length: 63              # PostgreSQL limit
      abbreviations_forbidden:
        - tbl
        - col
        - usr
        - msg
```

**Linting Output**:
```
⚠️  WARN: users.sql:1 - Table name 'UserTbl' violates convention
  Expected: user
  Found: UserTbl

⚠️  WARN: users.sql:5 - Abbreviation 'usr' forbidden
  Expected: user
  Found: usr_id
```

---

## Example: Security Rule

**Situation**: Ensure PII is encrypted and passwords are hashed.

```python
# db/linting/security_rules.py

from confiture.linting import Rule, RuleContext, Violation

class PIIEncryptionRule(Rule):
    """Ensure PII columns are encrypted."""

    name = "pii_encryption"
    severity = "critical"

    PII_PATTERNS = ['email', 'ssn', 'credit_card', 'phone', 'password']

    def check(self, context: RuleContext) -> list[Violation]:
        violations = []

        for table in context.schema.tables:
            for column in table.columns:
                # Check if column matches PII patterns
                if any(pii in column.name.lower() for pii in self.PII_PATTERNS):
                    # Check if encrypted
                    if not column.has_comment('encrypted') and 'hash' not in column.name:
                        violations.append(
                            Violation(
                                rule=self.name,
                                severity=self.severity,
                                table=table.name,
                                column=column.name,
                                message=f"PII column '{column.name}' must be encrypted or hashed",
                                fix=f"Add comment to {column.name}: -- encrypted"
                            )
                        )

        return violations
```

**Configuration**:
```yaml
linting:
  security:
    require_encryption:
      - email
      - ssn
      - credit_card
      - phone
    require_hash:
      - password
    forbidden_plain_text:
      - api_key
      - secret
      - token
```

---

## Example: Performance Rule

**Situation**: Detect missing indices and optimize queries.

```python
# db/linting/performance_rules.py

from confiture.linting import Rule, RuleContext, Violation

class MissingIndexRule(Rule):
    """Detect columns that should have indices."""

    name = "missing_indices"
    severity = "warning"

    # Columns commonly queried
    COMMONLY_QUERIED = [
        'id', 'user_id', 'email', 'created_at',
        'status', 'type', 'category'
    ]

    def check(self, context: RuleContext) -> list[Violation]:
        violations = []

        for table in context.schema.tables:
            for column in table.columns:
                # Check if commonly queried
                if column.name in self.COMMONLY_QUERIED:
                    # Check if indexed
                    if not column.has_index():
                        violations.append(
                            Violation(
                                rule=self.name,
                                severity=self.severity,
                                table=table.name,
                                column=column.name,
                                message=f"Column '{column.name}' should probably have an index",
                                fix=(
                                    f"CREATE INDEX idx_{table.name}_{column.name} "
                                    f"ON {table.name}({column.name});"
                                )
                            )
                        )

        return violations
```

---

## Example: Compliance Rule

**Situation**: Ensure GDPR compliance (data retention, audit trails).

```python
# db/linting/compliance_rules.py

from confiture.linting import Rule, RuleContext, Violation

class GDPRComplianceRule(Rule):
    """Ensure GDPR compliance requirements."""

    name = "gdpr_compliance"
    severity = "critical"

    def check(self, context: RuleContext) -> list[Violation]:
        violations = []

        for table in context.schema.tables:
            # Check for required audit columns
            has_created_at = any(c.name == 'created_at' for c in table.columns)
            has_updated_at = any(c.name == 'updated_at' for c in table.columns)

            if not has_created_at:
                violations.append(
                    Violation(
                        rule=self.name,
                        severity="critical",
                        table=table.name,
                        message="Table must have 'created_at' column for GDPR audit trail",
                        fix=f"ALTER TABLE {table.name} ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();"
                    )
                )

            if not has_updated_at:
                violations.append(
                    Violation(
                        rule=self.name,
                        severity="critical",
                        table=table.name,
                        message="Table must have 'updated_at' column for tracking changes",
                        fix=f"ALTER TABLE {table.name} ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();"
                    )
                )

            # Check for PII columns without encryption
            for column in table.columns:
                if 'email' in column.name.lower() and 'encrypted' not in column.name:
                    if not column.has_comment('encrypted'):
                        violations.append(
                            Violation(
                                rule=self.name,
                                severity="critical",
                                table=table.name,
                                column=column.name,
                                message="PII must be encrypted for GDPR compliance"
                            )
                        )

        return violations
```

---

## CI/CD Integration

### GitHub Actions Example

```yaml
# .github/workflows/schema-lint.yml

name: Schema Lint

on:
  pull_request:
    paths:
      - 'db/schema/**'

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Confiture
        run: pip install confiture

      - name: Lint schema
        run: confiture lint --strict

      - name: Comment on PR
        if: failure()
        uses: actions/github-script@v6
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          script: |
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: '❌ Schema lint failed. Run `confiture lint` locally to see issues.'
            })
```

---

## Best Practices

### 1. Enforce Linting in CI/CD

**Good**:
```bash
# Fail on any lint violations
confiture lint --strict

# Fail on critical issues only
confiture lint --fail-level critical
```

**Bad**:
```bash
# Ignore lint issues
confiture lint # (warnings don't fail)
```

### 2. Document Custom Rules

**Good**:
```python
class CustomRule(Rule):
    """
    Custom rule: All tables must have owner.

    This ensures we can contact the team responsible
    for each table for schema changes.

    Example fix:
        COMMENT ON TABLE users IS 'owner: platform-team';
    """
```

**Bad**:
```python
class CustomRule(Rule):
    """Check something"""
    pass
```

### 3. Include Auto-Fixes

**Good**:
```python
violations.append(
    Violation(
        rule="naming",
        message="Table name should be snake_case",
        fix="Rename to lowercase"  # Clear fix
    )
)
```

**Bad**:
```python
violations.append(
    Violation(
        rule="naming",
        message="Bad table name"  # Vague
        # No fix suggestion
    )
)
```

---

## Troubleshooting

### ❌ Error: "Rule not found"

**Cause**: Custom rule not loaded or wrong name.

**Solution**: Check configuration:

```bash
# List all available rules
confiture lint --list-rules

# Load custom rules explicitly
confiture lint --rules db/linting/rules.py
```

---

### ❌ Error: "Too many false positives"

**Cause**: Rule too strict for codebase.

**Solution**: Adjust rule severity or exceptions:

```yaml
linting:
  rules:
    naming:
      table_case: snake_case
      # But allow legacy tables
      exclude_tables:
        - UserTbl  # Existing legacy table
        - MsgQueue

  # Or disable rule
  exclude_rules:
    - "naming"  # Skip naming checks
```

---

## See Also

- [Advanced Patterns](./advanced-patterns.md) - Complex validation workflows
- [Schema Design](../migration-strategies.md) - Best practices
- [Troubleshooting](./troubleshooting.md) - Common issues
- [CLI Reference](../reference/cli.md) - Lint command documentation

---

## 🎯 Next Steps

**Ready to lint your schema?**
- ✅ You now understand: Linting rules, custom rules, CI/CD integration

**What to do next:**

1. **[Advanced Patterns](./advanced-patterns.md)** - Custom validation rules
2. **[CLI Reference](../reference/cli.md)** - Full lint command documentation
3. **[Examples](../../examples/)** - Production linting examples

**Got questions?**
- **[FAQ](../glossary.md)** - Glossary and definitions
- **[Troubleshooting](./troubleshooting.md)** - Common issues

---

*Part of Confiture documentation* 🍓

*Making migrations sweet and simple*
