#!/usr/bin/env python3
"""Example demonstrating seed data consistency validation.

This example shows how to use the ConsistencyValidator to check seed data
for data integrity issues before deployment.
"""

from confiture.core.seed_validation.consistency_cli import ConsistencyCLI, ConsistencyCLIConfig
from confiture.core.seed_validation.consistency_validator import ConsistencyValidator
from confiture.core.seed_validation.environment_comparator import EnvironmentComparator


def example_1_basic_validation():
    """Example 1: Basic consistency validation."""
    print("=" * 60)
    print("Example 1: Basic Consistency Validation")
    print("=" * 60)

    validator = ConsistencyValidator()

    # Valid seed data
    seed_data = {
        "users": [
            {"id": "1", "email": "alice@example.com", "name": "Alice"},
            {"id": "2", "email": "bob@example.com", "name": "Bob"},
        ],
        "orders": [
            {"id": "1", "customer_id": "1", "amount": "100.00"},
            {"id": "2", "customer_id": "2", "amount": "200.00"},
        ],
    }

    schema_context = {
        "users": {
            "required": True,
            "min_rows": 1,
            "columns": {
                "id": {"required": True, "unique": True},
                "email": {"required": True, "unique": True},
                "name": {"required": True},
            },
        },
        "orders": {
            "required": True,
            "columns": {
                "id": {"required": True, "unique": True},
                "customer_id": {
                    "required": True,
                    "foreign_key": ("users", "id"),
                },
            },
        },
    }

    report = validator.validate(seed_data, schema_context)

    if report.has_violations:
        print(f"❌ Validation failed with {report.violation_count} violations:")
        for violation in report.violations:
            print(f"  - {violation.message}")
    else:
        print("✓ All consistency checks passed!")
        print(f"  Validators run: {', '.join(report.validators_run)}")

    print()


def example_2_foreign_key_violation():
    """Example 2: Detecting foreign key violations."""
    print("=" * 60)
    print("Example 2: Foreign Key Violation Detection")
    print("=" * 60)

    validator = ConsistencyValidator()

    # Invalid: customer_id 999 doesn't exist
    seed_data = {
        "users": [
            {"id": "1", "email": "alice@example.com"},
        ],
        "orders": [
            {"id": "1", "customer_id": "1"},
            {"id": "2", "customer_id": "999"},  # ERROR!
        ],
    }

    schema_context = {
        "users": {"required": True},
        "orders": {"columns": {"customer_id": {"foreign_key": ("users", "id")}}},
    }

    report = validator.validate(seed_data, schema_context)

    print(f"Found {report.violation_count} violations:")
    for violation in report.violations:
        print(f"  - {violation.message}")

    print()


def example_3_unique_constraint_violation():
    """Example 3: Detecting duplicate values in UNIQUE columns."""
    print("=" * 60)
    print("Example 3: Unique Constraint Violation Detection")
    print("=" * 60)

    validator = ConsistencyValidator()

    # Invalid: duplicate email
    seed_data = {
        "users": [
            {"id": "1", "email": "alice@example.com"},
            {"id": "2", "email": "alice@example.com"},  # ERROR: duplicate!
        ],
    }

    schema_context = {
        "users": {
            "columns": {
                "id": {"unique": True},
                "email": {"unique": True},
            }
        }
    }

    report = validator.validate(seed_data, schema_context)

    print(f"Found {report.violation_count} violations:")
    for violation in report.violations:
        print(f"  - {violation.message}")

    print()


def example_4_not_null_violation():
    """Example 4: Detecting NULL in required columns."""
    print("=" * 60)
    print("Example 4: NOT NULL Violation Detection")
    print("=" * 60)

    validator = ConsistencyValidator()

    # Invalid: required email is NULL
    seed_data = {
        "users": [
            {"id": "1", "email": "alice@example.com", "name": "Alice"},
            {"id": "2", "email": None, "name": "Bob"},  # ERROR: NULL email!
        ],
    }

    schema_context = {
        "users": {
            "columns": {
                "email": {"required": True},
                "name": {"required": True},
            }
        }
    }

    report = validator.validate(seed_data, schema_context)

    print(f"Found {report.violation_count} violations:")
    for violation in report.violations:
        print(f"  - {violation.message}")

    print()


def example_5_completeness_violation():
    """Example 5: Detecting missing required tables."""
    print("=" * 60)
    print("Example 5: Completeness Violation Detection")
    print("=" * 60)

    validator = ConsistencyValidator()

    # Invalid: roles table is missing
    seed_data = {
        "users": [
            {"id": "1", "email": "alice@example.com"},
        ],
    }

    schema_context = {
        "users": {"required": True},
        "roles": {"required": True},  # ERROR: missing!
        "permissions": {"required": False},  # OK to miss
    }

    report = validator.validate(seed_data, schema_context)

    print(f"Found {report.violation_count} violations:")
    for violation in report.violations:
        print(f"  - {violation.message}")

    print()


def example_6_environment_comparison():
    """Example 6: Comparing seed data across environments."""
    print("=" * 60)
    print("Example 6: Environment Comparison")
    print("=" * 60)

    comparator = EnvironmentComparator()

    dev_data = {
        "users": [
            {"id": "1", "email": "alice@dev.example.com"},
            {"id": "2", "email": "bob@dev.example.com"},
        ]
    }

    prod_data = {
        "users": [
            {"id": "1", "email": "alice@example.com"},
            {"id": "2", "email": "bob@example.com"},
            {"id": "3", "email": "charlie@example.com"},  # Extra row!
        ]
    }

    differences = comparator.compare(dev_data, prod_data)

    if differences:
        print(f"Found {len(differences)} differences between environments:")
        for diff in differences:
            print(f"  - {diff.message}")
    else:
        print("✓ Environments have identical seed data")

    print()


def example_7_cli_interface():
    """Example 7: Using the CLI interface."""
    print("=" * 60)
    print("Example 7: CLI Interface")
    print("=" * 60)

    config = ConsistencyCLIConfig(
        output_format="text",
        verbose=True,
    )
    cli = ConsistencyCLI(config=config)

    seed_data = {
        "users": [
            {"id": "1", "email": "alice@example.com"},
            {"id": "2", "email": "alice@example.com"},  # Duplicate!
        ]
    }

    schema_context = {"users": {"columns": {"email": {"unique": True}}}}

    result = cli.validate(seed_data, schema_context)
    print(result.format_output())

    print()


def example_8_json_output():
    """Example 8: JSON output format."""
    print("=" * 60)
    print("Example 8: JSON Output Format")
    print("=" * 60)

    config = ConsistencyCLIConfig(
        output_format="json",
        verbose=False,
    )
    cli = ConsistencyCLI(config=config)

    seed_data = {
        "users": [
            {"id": "1", "email": None},  # ERROR: required field is NULL
        ]
    }

    schema_context = {"users": {"columns": {"email": {"required": True}}}}

    result = cli.validate(seed_data, schema_context)
    print(result.format_output())

    print()


def example_9_multiple_violations():
    """Example 9: Multiple violations in one dataset."""
    print("=" * 60)
    print("Example 9: Multiple Violations")
    print("=" * 60)

    validator = ConsistencyValidator()

    # Multiple errors
    seed_data = {
        "users": [
            {"id": "1", "email": "alice@example.com", "name": None},  # NOT NULL error
            {"id": "2", "email": "alice@example.com", "name": "Bob"},  # Unique error
        ],
        "orders": [
            {"id": "1", "customer_id": "999"},  # FK error
        ],
    }

    schema_context = {
        "users": {
            "required": True,
            "columns": {
                "id": {"unique": True},
                "email": {"unique": True},
                "name": {"required": True},
            },
        },
        "orders": {"columns": {"customer_id": {"foreign_key": ("users", "id")}}},
        "roles": {"required": True},  # Completeness error
    }

    report = validator.validate(seed_data, schema_context)

    print(f"Found {report.violation_count} violations:")
    for i, violation in enumerate(report.violations, 1):
        vtype = getattr(violation, "violation_type", "unknown")
        print(f"  {i}. [{vtype}] {violation.message}")

    print(f"\nValidators that ran: {', '.join(report.validators_run)}")

    print()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Seed Data Consistency Validation Examples")
    print("=" * 60 + "\n")

    example_1_basic_validation()
    example_2_foreign_key_violation()
    example_3_unique_constraint_violation()
    example_4_not_null_violation()
    example_5_completeness_violation()
    example_6_environment_comparison()
    example_7_cli_interface()
    example_8_json_output()
    example_9_multiple_violations()

    print("=" * 60)
    print("All examples completed!")
    print("=" * 60)
