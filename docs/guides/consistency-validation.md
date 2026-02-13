# Seed Data Consistency Validation Guide

> **New in Phase 11**: Comprehensive validation system to catch data integrity issues before deployment.

## Overview

The consistency validation system detects data integrity problems in seed files that would cause deployment failures:

- ❌ **Foreign Key Violations** - FK references pointing to non-existent rows
- ❌ **Unique Constraint Violations** - Duplicate values in UNIQUE columns
- ❌ **NOT NULL Violations** - Missing required column values
- ❌ **Completeness Issues** - Missing required tables or insufficient rows
- ❌ **Environment Mismatches** - Inconsistencies between dev/staging/prod seed data

## Quick Start

### Basic Usage

```python
from confiture.core.seed_validation.consistency_validator import ConsistencyValidator

validator = ConsistencyValidator()

seed_data = {
    "users": [
        {"id": "1", "email": "alice@example.com"},
        {"id": "2", "email": "bob@example.com"},
    ],
    "orders": [
        {"id": "1", "customer_id": "1"},
        {"id": "2", "customer_id": "999"},  # ERROR: customer doesn't exist!
    ]
}

schema_context = {
    "users": {"required": True},
    "orders": {
        "columns": {
            "customer_id": {"foreign_key": ("users", "id")}
        }
    }
}

report = validator.validate(seed_data, schema_context)

if report.has_violations:
    print(f"Found {report.violation_count} violations:")
    for violation in report.violations:
        print(f"  - {violation.message}")
else:
    print("✓ All consistency checks passed!")
```

### CLI Usage

```bash
# Validate with text output
confiture seed validate --consistency-check

# Validate with JSON output
confiture seed validate --consistency-check --format json

# Verbose mode with detailed diagnostics
confiture seed validate --consistency-check --verbose
```

## Components

### 1. Foreign Key Validation

Verifies that all foreign key references point to existing rows.

**Schema Configuration:**
```python
schema_context = {
    "orders": {
        "columns": {
            "customer_id": {
                "foreign_key": ("users", "id")
            }
        }
    }
}
```

**What It Catches:**
- Missing referenced rows
- Missing referenced tables
- NULL values in optional FKs (allowed)
- UUID, numeric, and string FK values

**Example Violation:**
```
Foreign key orders.customer_id = 999 does not exist in users.id
```

### 2. Unique Constraint Validation

Detects duplicate values in UNIQUE columns.

**Schema Configuration:**
```python
schema_context = {
    "users": {
        "columns": {
            "email": {"unique": True},
            "username": {"unique": True},
        },
        "unique_constraints": [
            {"columns": ["tenant_id", "email"]}  # Composite key
        ]
    }
}
```

**What It Catches:**
- Duplicate single-column values
- Duplicate composite key combinations
- NULL handling (multiple NULLs allowed)

**Example Violations:**
```
Column users.email is UNIQUE but value alice@example.com appears 2 times
Composite UNIQUE constraint on orders(user_id, product_id, date) violated: key (1 / 100 / 2026-02-13) appears 2 times
```

### 3. NOT NULL Validation

Verifies that required columns have values.

**Schema Configuration:**
```python
schema_context = {
    "users": {
        "columns": {
            "email": {"required": True},
            "name": {"required": True},
            "phone": {"required": False},  # Optional
        }
    }
}
```

**What It Catches:**
- NULL values in required columns
- Missing columns in row dicts
- Distinguishes NULL from empty string, 0, or false

**Example Violation:**
```
Column users.email is required but row 1 has NULL value
```

### 4. Completeness Validation

Ensures all required tables are present and have minimum rows.

**Schema Configuration:**
```python
schema_context = {
    "users": {
        "required": True,
        "min_rows": 1,  # At least one user required
    },
    "roles": {
        "required": True,
        "min_rows": 3,  # At least 3 roles required
    },
    "audit_logs": {
        "required": False,  # Optional table
    }
}
```

**What It Catches:**
- Missing required tables
- Empty required tables
- Tables with fewer rows than minimum

**Example Violations:**
```
Required table roles is missing from seed data
Table users has 0 rows but requires minimum 1 rows
```

### 5. Environment Comparison

Compares seed data across environments (dev, staging, production).

**Usage:**
```python
from confiture.core.seed_validation.environment_comparator import EnvironmentComparator

comparator = EnvironmentComparator()

dev_data = {"users": [{"id": "1", "email": "alice@dev.example.com"}]}
prod_data = {"users": [{"id": "1", "email": "alice@example.com"}]}

differences = comparator.compare(dev_data, prod_data)

if differences:
    for diff in differences:
        print(f"{diff.table}: {diff.message}")
```

**What It Catches:**
- Missing tables in one environment
- Row count mismatches
- Data value differences
- Extra or missing rows
- NULL vs value differences

**Example Differences:**
```
users: Table users has 5 rows in environment 1 but 10 rows in environment 2
roles: Table roles has different values between environments
```

## Advanced Configuration

### Stop on First Violation

Stop validation at the first violation for fast-fail scenarios:

```python
validator = ConsistencyValidator(stop_on_first_violation=True)
report = validator.validate(seed_data, schema_context)
```

### Environment Comparison

Include environment comparison in orchestrated validation:

```python
validator = ConsistencyValidator(compare_with_env2=True)
report = validator.validate(
    seed_data,
    schema_context,
    env2_data=prod_seed_data  # Optional second environment
)
```

### CLI Configuration

```bash
# Stop on first violation
confiture seed validate --consistency-check --stop-on-first

# Verbose output with all details
confiture seed validate --consistency-check --verbose

# JSON output for programmatic processing
confiture seed validate --consistency-check --format json > report.json
```

## Integration Examples

### Pre-Commit Hook

```bash
#!/bin/bash
# .git/hooks/pre-commit

echo "Validating seed data consistency..."
python -c "
from pathlib import Path
from confiture.core.seed_validation.consistency_validator import ConsistencyValidator

validator = ConsistencyValidator()
# Load seed data and schema from files...
report = validator.validate(seed_data, schema_context)

if report.has_violations:
    print('❌ Seed validation failed!')
    exit(1)
"
echo "✓ Seed data is consistent"
```

### CI/CD Pipeline

```yaml
# .github/workflows/seed-validation.yml
name: Seed Validation

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
      - run: pip install confiture
      - run: confiture seed validate --consistency-check --format json
        continue-on-error: true
      - name: Check validation results
        if: failure()
        run: |
          echo "❌ Seed data validation failed"
          exit 1
```

### Build Process

```python
# In your build script
from pathlib import Path
from confiture.core.seed_validation.consistency_validator import ConsistencyValidator
from confiture.core.seed_validation.consistency_cli import ConsistencyCLI, ConsistencyCLIConfig

def validate_seeds(seeds_dir: Path, schema_dir: Path) -> bool:
    """Validate seed files before build."""
    config = ConsistencyCLIConfig(
        output_format="text",
        verbose=True
    )
    cli = ConsistencyCLI(config=config)

    # Load seed data and schema...
    seed_data = load_seed_files(seeds_dir)
    schema_context = load_schema(schema_dir)

    result = cli.validate(seed_data, schema_context)
    print(result.format_output())

    return result.exit_code == 0

if not validate_seeds(Path("db/seeds"), Path("db/schema")):
    exit(1)
```

## Violation Types

### Foreign Key Violations

- `MISSING_FOREIGN_KEY` - FK value doesn't exist in referenced table
- `MISSING_REFERENCED_TABLE` - Referenced table doesn't exist in seed data

### Unique Constraint Violations

- `DUPLICATE_UNIQUE_VALUE` - Value appears multiple times in UNIQUE column
- `DUPLICATE_COMPOSITE_KEY` - Composite key appears multiple times

### NOT NULL Violations

- `NULL_IN_REQUIRED_COLUMN` - Required column has NULL value

### Completeness Violations

- `MISSING_REQUIRED_TABLE` - Required table is not in seed data
- `TABLE_TOO_SMALL` - Table has fewer rows than minimum required

### Environment Comparison Differences

- `TABLE_MISSING_IN_ENV2` - Table exists in env1 but not env2
- `TABLE_EXTRA_IN_ENV2` - Table exists in env2 but not env1
- `ROW_COUNT_MISMATCH` - Different row counts between environments
- `VALUE_MISMATCH` - Different data values between environments

## Best Practices

### 1. Define Schema Context Thoroughly

```python
schema_context = {
    "users": {
        "required": True,
        "min_rows": 1,
        "columns": {
            "id": {"required": True, "unique": True},
            "email": {"required": True, "unique": True},
            "name": {"required": True},
            "phone": {"required": False},
        }
    },
    "orders": {
        "required": True,
        "columns": {
            "id": {"required": True, "unique": True},
            "customer_id": {
                "required": True,
                "foreign_key": ("users", "id")
            }
        }
    }
}
```

### 2. Validate Early and Often

```bash
# Before git commit
pre-commit hook

# Before PR merge
CI/CD pipeline

# Before production deploy
Pre-deployment validation
```

### 3. Compare Across Environments

```python
# Ensure dev, staging, and prod have consistent seed data
dev_validator = ConsistencyValidator(compare_with_env2=True)
dev_report = dev_validator.validate(
    dev_seed_data,
    schema_context,
    env2_data=staging_seed_data
)
```

### 4. Use Verbose Mode for Debugging

```bash
# When validation fails, run in verbose mode
confiture seed validate --consistency-check --verbose
```

## Troubleshooting

### "Foreign key X does not exist"

**Cause**: Referenced row not found in target table

**Solution**:
1. Check the FK value is spelled correctly (case-sensitive)
2. Verify the referenced table has the row
3. Check for whitespace in values

### "Value X appears N times"

**Cause**: Duplicate in UNIQUE column

**Solution**:
1. Find and remove the duplicate
2. Verify the uniqueness constraint definition

### "Column X is required but NULL"

**Cause**: Required column has NULL value

**Solution**:
1. Provide a value for the required column
2. Check if column should be optional

### "Required table Y is missing"

**Cause**: Table not included in seed data

**Solution**:
1. Create seed data for the required table
2. Or mark the table as optional if not needed

## Output Formats

### Text Format

```
✓ Seed data validation passed
  Validators run: ForeignKeyDepthValidator, UniqueConstraintValidator, NotNullValidator

# or

✗ Seed data validation failed
  Violations found: 3

  Violations:
    - users: Column users.email is required but row 1 has NULL value
    - orders: Foreign key orders.customer_id = 999 does not exist in users.id
    - roles: Required table roles is missing from seed data

  Found 3 violations: NULL_IN_REQUIRED_COLUMN, MISSING_FOREIGN_KEY, MISSING_REQUIRED_TABLE
```

### JSON Format

```json
{
  "success": false,
  "message": "Found 3 violations: MISSING_FOREIGN_KEY, MISSING_REQUIRED_TABLE, NULL_IN_REQUIRED_COLUMN",
  "violation_count": 3,
  "validators_run": [
    "ForeignKeyDepthValidator",
    "UniqueConstraintValidator",
    "NotNullValidator",
    "CompletenessValidator"
  ],
  "violations": [
    {
      "table": "orders",
      "type": "MISSING_FOREIGN_KEY",
      "message": "Foreign key orders.customer_id = 999 does not exist in users.id"
    },
    {
      "table": "users",
      "type": "NULL_IN_REQUIRED_COLUMN",
      "message": "Column users.email is required but row 1 has NULL value"
    },
    {
      "table": "roles",
      "type": "MISSING_REQUIRED_TABLE",
      "message": "Required table roles is missing from seed data"
    }
  ]
}
```

## See Also

- [DataExtractor API](../api/data-extractor.md) - SQL parsing for seed data
- [ForeignKeyDepthValidator API](../api/foreign-key-validator.md) - FK validation
- [ConsistencyValidator API](../api/consistency-validator.md) - Orchestrator API
- [Phase 11 Plan](../../.phases/phase-11-data-consistency.md) - Implementation details

## FAQ

**Q: Does consistency validation run during `confiture build`?**
A: By default, no. Use `--consistency-check` flag or configure in environment settings.

**Q: Can I skip certain validations?**
A: Not yet, but this is planned for a future release.

**Q: Does row order matter?**
A: No. Environment comparison ignores row order.

**Q: How do I handle timestamps/generated values?**
A: Use placeholder values in seed data. Consistency validation only checks the values as provided.

---

**Last Updated**: February 13, 2026
**Version**: Phase 11, Cycle 9 (Documentation)
