"""Validate table completeness in seed data.

This module provides validation that all required tables are present in the
seed dataset and contain the minimum required number of rows.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class CompletenessViolation:
    """Represents a table completeness violation.

    Attributes:
        table: Table name that is missing or incomplete
        violation_type: Type of violation (MISSING_REQUIRED_TABLE or TABLE_TOO_SMALL)
        message: Human-readable violation message
        expected_count: Expected minimum row count (only for TABLE_TOO_SMALL)
        actual_count: Actual row count (only for TABLE_TOO_SMALL)
        severity: Severity level (ERROR, WARNING)
    """

    table: str
    violation_type: str
    message: str
    severity: str = "ERROR"
    expected_count: int | None = None
    actual_count: int | None = None


class CompletenessValidator:
    """Validate table completeness in seed data.

    Checks that all required tables are present in the seed dataset and
    contain the minimum required number of rows. Handles:
    - Required vs optional tables
    - Minimum row count requirements
    - Missing tables detection
    - Empty table detection
    - Multiple completeness violations

    Example:
        >>> validator = CompletenessValidator()
        >>> seed_data = {
        ...     "users": [{"id": "1"}, {"id": "2"}],
        ...     "roles": [{"id": "1"}],
        ... }
        >>> schema_context = {
        ...     "users": {"required": True},
        ...     "roles": {"required": True},
        ...     "audit_logs": {"required": False},
        ... }
        >>> violations = validator.validate(seed_data, schema_context)
        >>> len(violations)
        0
    """

    def __init__(self) -> None:
        """Initialize the validator."""
        pass

    def validate(
        self,
        seed_data: dict[str, list[dict[str, Any]]],
        schema_context: dict[str, Any],
    ) -> list[CompletenessViolation]:
        """Validate table completeness in seed data.

        Checks that all required tables are present and have the minimum rows.

        Args:
            seed_data: Dictionary mapping table names to lists of row dicts
            schema_context: Schema metadata including required table definitions

        Returns:
            List of CompletenessViolation objects for any violations found
        """
        violations = []

        # Check each table in schema_context
        for table_name, table_schema in schema_context.items():
            # Check if table is required
            is_required = table_schema.get("required", False)

            # Check if table exists in seed data
            if table_name not in seed_data:
                if is_required:
                    violation = CompletenessViolation(
                        table=table_name,
                        violation_type="MISSING_REQUIRED_TABLE",
                        message=f"Required table {table_name} is missing from seed data",
                        severity="ERROR",
                    )
                    violations.append(violation)
                continue

            # Table exists, check row count requirements
            table_rows = seed_data[table_name]
            min_rows = table_schema.get("min_rows")

            if min_rows is not None and len(table_rows) < min_rows:
                violation = CompletenessViolation(
                    table=table_name,
                    violation_type="TABLE_TOO_SMALL",
                    message=(
                        f"Table {table_name} has {len(table_rows)} rows but "
                        f"requires minimum {min_rows} rows"
                    ),
                    severity="ERROR",
                    expected_count=min_rows,
                    actual_count=len(table_rows),
                )
                violations.append(violation)

        return violations
