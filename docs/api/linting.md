# Linting Rule API Reference

[← Back to API Reference](index.md)

**Stability**: Stable ✅

---

## Overview

The Linting Rule API enables you to define custom schema validation rules. Rules validate that your database schema follows best practices, compliance requirements, and organizational standards before executing migrations.

**Tagline**: *Define custom schema validation rules for database quality*

---

## What is a Linting Rule?

A Linting Rule is a class that validates a specific aspect of your database schema. Rules can:
- Check naming conventions
- Enforce security best practices
- Validate compliance requirements
- Ensure performance best practices
- Detect anti-patterns

**Key Concept**: Rules examine schema structure and report violations. They don't modify schema.

---

## When to Use Linting Rules

**✅ Good Use Cases**:
- Enforce naming conventions (`users` not `user_table`)
- Require primary keys on all tables
- Verify PII columns are encrypted
- Check index coverage for large tables
- Enforce audit logging columns
- Validate foreign key constraints

**Common Rule Categories**:
1. **Security**: PII handling, encryption, access control
2. **Performance**: Indexes, data types, partitioning
3. **Quality**: Naming, constraints, documentation
4. **Compliance**: HIPAA audit logs, SOX segregation
5. **Architecture**: Primary keys, relationships

---

## Rule Class Structure

### Base Rule Definition

```python
from confiture.linting import Rule, RuleContext, Violation, Severity

class MyRule(Rule):
    """Custom linting rule."""

    # Rule metadata
    name = "my_custom_rule"
    severity = Severity.ERROR  # or WARNING, INFO
    description = "Validates something about the schema"

    def check(self, context: RuleContext) -> list[Violation]:
        """
        Check schema against this rule.

        Args:
            context: RuleContext with schema information

        Returns:
            List of violations (empty if all pass)
        """
        violations = []

        # Examine schema
        for table in context.schema.tables:
            # Check some condition
            if condition_fails(table):
                violations.append(
                    Violation(
                        rule=self.name,
                        table=table.name,
                        severity=self.severity,
                        message=f"Table {table.name} violates rule"
                    )
                )

        return violations
```

### Rule Attributes

```python
class MyRule(Rule):
    # REQUIRED
    name: str = "rule_name"           # Unique identifier
    description: str = "What this validates"

    # OPTIONAL
    severity: Severity = Severity.ERROR  # ERROR, WARNING, INFO
    autofix: bool = False              # Can be auto-fixed?
    category: str = "security"         # Rule category
```

### Severity Levels

| Level | Impact | Default Behavior |
|-------|--------|-----------------|
| `ERROR` | Schema is broken | Prevents migration |
| `WARNING` | Potential issue | Allowed but flagged |
| `INFO` | FYI only | Informational |

---

## RuleContext Object

The context provides schema information for validation.

### Context Structure

```python
@dataclass
class RuleContext:
    schema: Schema            # Full schema information
    environment: str          # 'development', 'staging', 'production'
    database_url: str         # Connection string
    config: dict             # Rule configuration

class Schema:
    """Database schema information."""
    tables: list[Table]      # All tables
    views: list[View]        # All views
    indexes: list[Index]     # All indexes
    constraints: list[Constraint]  # All constraints
```

### Table Information

```python
@dataclass
class Table:
    name: str
    schema: str              # Usually 'public'
    columns: list[Column]
    primary_key: list[str]   # PK column names
    foreign_keys: list[ForeignKey]
    indexes: list[Index]
    row_count: int | None    # Row count (if available)
    created_at: datetime | None
```

### Column Information

```python
@dataclass
class Column:
    name: str
    data_type: str           # 'INTEGER', 'TEXT', 'TIMESTAMP', etc.
    nullable: bool           # NOT NULL?
    default: str | None      # DEFAULT value
    unique: bool             # UNIQUE constraint?
    comment: str | None      # Column comment
```

---

## Violation Creation

### Violation Object

```python
@dataclass
class Violation:
    rule: str                # Rule name
    message: str             # Human-readable message
    severity: Severity       # ERROR, WARNING, INFO
    table: str | None = None # Table name if applicable
    column: str | None = None # Column name if applicable
    suggested_fix: str | None = None  # How to fix it
```

### Creating Violations

```python
# Simple violation
violation = Violation(
    rule="require_primary_key",
    message="Table 'users' missing primary key",
    severity=Severity.ERROR,
    table="users"
)

# With fix suggestion
violation = Violation(
    rule="require_primary_key",
    message="Table 'users' missing primary key",
    severity=Severity.ERROR,
    table="users",
    suggested_fix="ADD PRIMARY KEY (id)"
)
```

---

## Linting Rule Examples

### Example 1: Require Primary Keys

```python
from confiture.linting import Rule, RuleContext, Violation, Severity

class RequirePrimaryKey(Rule):
    """Enforce primary key on all tables."""

    name = "require_primary_key"
    severity = Severity.ERROR
    description = "All tables must have a primary key"

    def check(self, context: RuleContext) -> list[Violation]:
        """Check that all tables have primary keys."""
        violations = []

        for table in context.schema.tables:
            if not table.primary_key:
                violations.append(
                    Violation(
                        rule=self.name,
                        message=f"Table '{table.name}' missing primary key",
                        severity=self.severity,
                        table=table.name,
                        suggested_fix=f"ALTER TABLE {table.name} ADD PRIMARY KEY (id)"
                    )
                )

        return violations
```

---

### Example 2: Naming Convention

```python
import re
from confiture.linting import Rule, RuleContext, Violation, Severity

class SnakeCaseNaming(Rule):
    """Enforce snake_case naming for tables and columns."""

    name = "snake_case_naming"
    severity = Severity.WARNING
    description = "Use snake_case for table and column names"

    SNAKE_CASE_PATTERN = re.compile(r'^[a-z][a-z0-9_]*$')

    def check(self, context: RuleContext) -> list[Violation]:
        """Check naming conventions."""
        violations = []

        # Check table names
        for table in context.schema.tables:
            if not self.SNAKE_CASE_PATTERN.match(table.name):
                violations.append(
                    Violation(
                        rule=self.name,
                        message=f"Table '{table.name}' not in snake_case",
                        severity=self.severity,
                        table=table.name
                    )
                )

            # Check column names
            for column in table.columns:
                if not self.SNAKE_CASE_PATTERN.match(column.name):
                    violations.append(
                        Violation(
                            rule=self.name,
                            message=f"Column '{table.name}.{column.name}' not in snake_case",
                            severity=self.severity,
                            table=table.name,
                            column=column.name
                        )
                    )

        return violations
```

---

### Example 3: PII Encryption

```python
from confiture.linting import Rule, RuleContext, Violation, Severity

class PIIEncryption(Rule):
    """Ensure PII columns are encrypted."""

    name = "pii_encryption"
    severity = Severity.ERROR
    description = "PII columns must be encrypted"

    # Sensitive column patterns
    SENSITIVE_COLUMNS = ['email', 'phone', 'ssn', 'credit_card', 'password']

    def check(self, context: RuleContext) -> list[Violation]:
        """Check PII columns are encrypted."""
        violations = []

        for table in context.schema.tables:
            for column in table.columns:
                # Check if column matches sensitive pattern
                is_sensitive = any(
                    pattern in column.name.lower()
                    for pattern in self.SENSITIVE_COLUMNS
                )

                if is_sensitive:
                    # Check if encrypted (by comment or type)
                    is_encrypted = (
                        column.comment and 'encrypted' in column.comment.lower()
                    ) or 'encrypted' in str(column.data_type).lower()

                    if not is_encrypted:
                        violations.append(
                            Violation(
                                rule=self.name,
                                message=f"PII column '{table.name}.{column.name}' not encrypted",
                                severity=self.severity,
                                table=table.name,
                                column=column.name,
                                suggested_fix=f"COMMENT ON COLUMN {table.name}.{column.name} IS 'encrypted'"
                            )
                        )

        return violations
```

---

### Example 4: Index Coverage

```python
from confiture.linting import Rule, RuleContext, Violation, Severity

class IndexCoverage(Rule):
    """Ensure large tables have indexes on foreign keys."""

    name = "index_coverage"
    severity = Severity.WARNING
    description = "Large tables should have indexes on FK columns"

    LARGE_TABLE_THRESHOLD = 10000  # rows

    def check(self, context: RuleContext) -> list[Violation]:
        """Check index coverage for large tables."""
        violations = []

        for table in context.schema.tables:
            # Only check large tables
            if table.row_count and table.row_count < self.LARGE_TABLE_THRESHOLD:
                continue

            indexed_columns = {col for idx in table.indexes for col in idx.columns}

            for fk in table.foreign_keys:
                # Check if FK is indexed
                if fk.columns[0] not in indexed_columns:
                    violations.append(
                        Violation(
                            rule=self.name,
                            message=f"FK '{fk.columns[0]}' in large table not indexed",
                            severity=self.severity,
                            table=table.name,
                            column=fk.columns[0],
                            suggested_fix=f"CREATE INDEX {table.name}_{fk.columns[0]}_idx ON {table.name}({fk.columns[0]})"
                        )
                    )

        return violations
```

---

### Example 5: Audit Logging

```python
from confiture.linting import Rule, RuleContext, Violation, Severity

class AuditLogging(Rule):
    """Ensure tables have audit logging columns."""

    name = "audit_logging"
    severity = Severity.WARNING
    description = "Tables should have created_at, updated_at columns"

    def check(self, context: RuleContext) -> list[Violation]:
        """Check audit logging columns."""
        violations = []

        # Skip system tables
        system_tables = {'pg_*', 'information_schema.*'}

        for table in context.schema.tables:
            if any(table.name.startswith(prefix.rstrip('*'))
                   for prefix in system_tables):
                continue

            column_names = {col.name.lower() for col in table.columns}

            # Check for audit columns
            has_created = 'created_at' in column_names
            has_updated = 'updated_at' in column_names

            if not has_created or not has_updated:
                missing = []
                if not has_created:
                    missing.append('created_at')
                if not has_updated:
                    missing.append('updated_at')

                violations.append(
                    Violation(
                        rule=self.name,
                        message=f"Table '{table.name}' missing audit columns: {', '.join(missing)}",
                        severity=self.severity,
                        table=table.name,
                        suggested_fix=f"ALTER TABLE {table.name} ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    )
                )

        return violations
```

---

## Registering Rules

### Automatic Registration

```python
from confiture.linting import Rule

# Automatically discovered and registered
class MyRule(Rule):
    name = "my_rule"
    severity = Severity.ERROR

    def check(self, context: RuleContext) -> list[Violation]:
        pass
```

### Manual Registration

```python
from confiture.linting import register_rule

register_rule(MyRule())
```

### Disabling Rules

```python
# In configuration
LINTING_CONFIG = {
    'disabled_rules': ['rule_name_to_skip'],
    'rules_config': {
        'rule_name': {
            'threshold': 1000,
            'environment': 'production'
        }
    }
}
```

---

## Best Practices

### ✅ Do's

1. **Clear violation messages**
   ```python
   # Good
   message = f"Table '{table.name}' missing primary key"

   # Bad
   message = "PK missing"
   ```

2. **Provide fix suggestions**
   ```python
   violation = Violation(
       ...,
       suggested_fix="ALTER TABLE users ADD PRIMARY KEY (id)"
   )
   ```

3. **Handle edge cases**
   ```python
   # Good: Skip system tables
   if table.name.startswith('pg_'):
       continue

   # Check for None values
   if table.row_count is None:
       continue
   ```

4. **Environment-aware rules**
   ```python
   # Only strict in production
   if context.environment == 'production':
       severity = Severity.ERROR
   else:
       severity = Severity.WARNING
   ```

### ❌ Don'ts

1. **Don't modify schema**
   ```python
   # Bad: Modifies database
   context.connection.execute(f"ALTER TABLE {table}")

   # Good: Just report violation
   return [Violation(...)]
   ```

2. **Don't have side effects**
   ```python
   # Bad: External calls
   requests.post("https://monitoring.example.com", ...)

   # Good: Pure validation
   return violations
   ```

---

## Running Linting

### CLI Usage

```bash
# Check schema against all rules
confiture lint --database postgresql://localhost/mydb

# Check specific rule
confiture lint --rule require_primary_key --database postgresql://localhost/mydb

# Fix warnings
confiture lint --fix --database postgresql://localhost/mydb
```

### Programmatic Usage

```python
from confiture.linting import Linter

linter = Linter(database_url="postgresql://localhost/mydb")
violations = linter.check_all()

for violation in violations:
    print(f"{violation.severity}: {violation.message}")
```

---

## See Also

- [Schema Linting Guide](../guides/schema-linting.md) - User guide with patterns
- [Migration Hooks Guide](../guides/hooks.md) - Pre-commit integration
- [Integrations Guide](../guides/integrations.md) - CI/CD linting

---

**Last Updated**: January 17, 2026

