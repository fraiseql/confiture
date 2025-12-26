#!/usr/bin/env python3
"""Basic schema linting example.

This example demonstrates how to use the schema linting system programmatically.
It shows how to:

1. Create a SchemaLinter instance
2. Run linting on a schema
3. Process and display results
4. Handle violations by severity

This is useful for integrating linting into custom workflows, automation
scripts, or applications that need programmatic access to linting results.
"""

from confiture.core.linting import SchemaLinter
from confiture.models.lint import LintSeverity


def main() -> None:
    """Run basic schema linting example."""
    # Create linter for test environment (useful for examples)
    print("Creating linter for 'test' environment...")
    linter = SchemaLinter(env="test")

    # Run linting on the schema
    print("Running schema linting...\n")
    report = linter.lint()

    # Display basic metrics
    print("=" * 60)
    print("LINTING RESULTS")
    print("=" * 60)
    print(f"Schema:  {report.schema_name}")
    print(f"Tables checked:  {report.tables_checked}")
    print(f"Columns checked: {report.columns_checked}")
    print(f"Execution time:  {report.execution_time_ms}ms")
    print()

    # Display summary counts
    print("VIOLATION SUMMARY")
    print("-" * 60)
    print(f"Total violations: {len(report.violations)}")
    print(f"  - Errors:   {report.errors_count}")
    print(f"  - Warnings: {report.warnings_count}")
    print(f"  - Info:     {report.info_count}")
    print()

    # If no violations, show success message
    if not report.violations:
        print("✅ No violations found! Schema is clean.")
        return

    # Display violations grouped by severity
    print("VIOLATIONS BY SEVERITY")
    print("-" * 60)

    # Show errors first
    errors = [v for v in report.violations if v.severity == LintSeverity.ERROR]
    if errors:
        print("\n❌ ERRORS (must be fixed):\n")
        for violation in errors:
            print(f"  Rule:     {violation.rule_name}")
            print(f"  Location: {violation.location}")
            print(f"  Message:  {violation.message}")
            if violation.suggested_fix:
                print(f"  Fix:      {violation.suggested_fix}")
            print()

    # Show warnings
    warnings = [v for v in report.violations if v.severity == LintSeverity.WARNING]
    if warnings:
        print("⚠️  WARNINGS (should be fixed):\n")
        for violation in warnings:
            print(f"  Rule:     {violation.rule_name}")
            print(f"  Location: {violation.location}")
            print(f"  Message:  {violation.message}")
            if violation.suggested_fix:
                print(f"  Fix:      {violation.suggested_fix}")
            print()

    # Show info messages
    info = [v for v in report.violations if v.severity == LintSeverity.INFO]
    if info:
        print("ℹ️  INFO (review for awareness):\n")
        for violation in info:
            print(f"  Rule:     {violation.rule_name}")
            print(f"  Location: {violation.location}")
            print(f"  Message:  {violation.message}")
            if violation.suggested_fix:
                print(f"  Fix:      {violation.suggested_fix}")
            print()

    # Summary statistics
    print("=" * 60)
    if report.has_errors:
        print("❌ RESULT: Schema has errors that must be fixed!")
        print("\nNext steps:")
        print("1. Review each error above")
        print("2. Apply the suggested fixes")
        print("3. Run linting again to verify")
        return 1
    elif report.has_warnings:
        print("⚠️  RESULT: Schema has warnings to address")
        print("\nNext steps:")
        print("1. Review warnings above")
        print("2. Consider applying suggested fixes")
        print("3. Update configuration if necessary")
        return 0
    else:
        print("✅ RESULT: Schema is clean!")
        return 0


if __name__ == "__main__":
    import sys

    exit_code = main()
    sys.exit(exit_code or 0)
