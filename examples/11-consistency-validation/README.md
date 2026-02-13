# Consistency Validation Example

Comprehensive examples demonstrating seed data consistency validation.

## Overview

This example shows how to use the ConsistencyValidator and related components to catch data integrity issues before deployment:

- Foreign key violations
- Unique constraint violations
- NOT NULL violations
- Completeness violations (missing tables/rows)
- Environment mismatches

## Running the Examples

```bash
# Run all examples
python consistency_validation_example.py

# Or run specific examples in your code
from consistency_validation_example import example_1_basic_validation
example_1_basic_validation()
```

## Examples Included

### Example 1: Basic Validation
- Valid seed data passes all checks
- Shows how to define schema context
- Demonstrates successful validation report

### Example 2: Foreign Key Violations
- Detects FK references pointing to non-existent rows
- Shows violation message format
- Demonstrates FK constraint definition

### Example 3: Unique Constraint Violations
- Detects duplicate values in UNIQUE columns
- Shows how to define UNIQUE constraints
- Demonstrates violation reporting

### Example 4: NOT NULL Violations
- Detects NULL values in required columns
- Shows required column definition
- Demonstrates NULL handling

### Example 5: Completeness Violations
- Detects missing required tables
- Detects tables with insufficient rows
- Shows min_rows configuration

### Example 6: Environment Comparison
- Compares seed data between two environments
- Shows environment mismatch detection
- Demonstrates cross-environment validation

### Example 7: CLI Interface
- Uses ConsistencyCLI for command-line validation
- Shows text output formatting
- Demonstrates verbose mode

### Example 8: JSON Output
- Formats validation results as JSON
- Shows programmatic output format
- Useful for CI/CD integration

### Example 9: Multiple Violations
- Complex scenario with multiple validation errors
- Shows comprehensive violation aggregation
- Demonstrates real-world error patterns

## Key Concepts

### Schema Context Definition

```python
schema_context = {
    "table_name": {
        "required": True,              # Table must be present
        "min_rows": 1,                 # Minimum row count
        "columns": {
            "column_name": {
                "required": True,      # Column must have value
                "unique": True,        # No duplicates
                "foreign_key": ("ref_table", "ref_column"),
            }
        }
    }
}
```

### Violation Types

- `MISSING_FOREIGN_KEY` - FK reference doesn't exist
- `DUPLICATE_UNIQUE_VALUE` - Value duplicated in UNIQUE column
- `NULL_IN_REQUIRED_COLUMN` - Required column is NULL
- `MISSING_REQUIRED_TABLE` - Required table not in seed data
- `TABLE_TOO_SMALL` - Table has fewer rows than minimum

### Output Formats

**Text:**
```
✓ All consistency checks passed!
  Validators run: ForeignKeyDepthValidator, UniqueConstraintValidator, ...
```

**JSON:**
```json
{
  "success": true,
  "violation_count": 0,
  "validators_run": ["ForeignKeyDepthValidator", ...]
}
```

## Integration Points

### Pre-Commit Hooks
```bash
# Validate before each commit
confiture seed validate --consistency-check
```

### CI/CD Pipelines
```yaml
- run: confiture seed validate --consistency-check --format json
```

### Build Scripts
```python
from confiture.core.seed_validation.consistency_validator import ConsistencyValidator
validator = ConsistencyValidator()
report = validator.validate(seed_data, schema_context)
if report.has_violations:
    exit(1)
```

## Next Steps

1. **Read the Guide**: See [consistency-validation.md](../../docs/guides/consistency-validation.md) for comprehensive documentation

2. **Define Your Schema**: Create schema context with all constraints

3. **Run Validation**: Use ConsistencyValidator or CLI to validate seed data

4. **Fix Issues**: Address any violations found

5. **Integrate**: Add validation to your build/deployment pipeline

## API Reference

- `ConsistencyValidator` - Main validator orchestrator
- `ConsistencyCLI` - Command-line interface
- `ForeignKeyDepthValidator` - FK validation
- `UniqueConstraintValidator` - UNIQUE constraint validation
- `NotNullValidator` - NOT NULL validation
- `CompletenessValidator` - Table completeness validation
- `EnvironmentComparator` - Cross-environment comparison

## See Also

- [DataExtractor](../../python/confiture/core/seed_validation/data_extractor.py) - SQL parsing
- [ForeignKeyDepthValidator](../../python/confiture/core/seed_validation/foreign_key_validator.py) - FK validation
- [ConsistencyValidator](../../python/confiture/core/seed_validation/consistency_validator.py) - Orchestrator
- [Phase 11 Plan](../../.phases/phase-11-data-consistency.md) - Implementation details

---

**Example Version**: Phase 11, Cycle 9
**Last Updated**: February 13, 2026
