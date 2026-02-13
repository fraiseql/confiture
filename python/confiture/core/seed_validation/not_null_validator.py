"""Validate NOT NULL constraints in seed data.

This module provides validation that all required columns (NOT NULL) have values
and detects NULL values that would violate constraints.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class NotNullViolation:
    """Represents a NOT NULL constraint violation.

    Attributes:
        table: Table name containing the NOT NULL constraint
        column: Column name with NOT NULL constraint
        row_index: Index of the row with NULL value (0-based)
        violation_type: Type of violation (e.g., NULL_IN_REQUIRED_COLUMN)
        message: Human-readable violation message
        severity: Severity level (ERROR, WARNING)
    """

    table: str
    column: str
    row_index: int
    violation_type: str
    message: str
    severity: str = "ERROR"


class NotNullValidator:
    """Validate NOT NULL constraints in seed data.

    Checks that all required columns (marked as NOT NULL or required=True)
    have values in every row. Handles:
    - Single-column required constraints
    - Multiple required columns in a single table
    - Proper NULL detection (None, not empty string/0/false)
    - Missing columns (treated as NULL)
    - Row indexing for error reporting

    Example:
        >>> validator = NotNullValidator()
        >>> users = [
        ...     {"id": "1", "email": "alice@example.com"},
        ...     {"id": "2", "email": None},
        ... ]
        >>> seed_data = {"users": users}
        >>> schema_context = {
        ...     "users": {
        ...         "columns": {
        ...             "email": {"required": True}
        ...         }
        ...     }
        ... }
        >>> violations = validator.validate(seed_data, schema_context)
        >>> len(violations)
        1
    """

    def __init__(self) -> None:
        """Initialize the validator."""
        pass

    def validate(
        self,
        seed_data: dict[str, list[dict[str, Any]]],
        schema_context: dict[str, Any],
    ) -> list[NotNullViolation]:
        """Validate all NOT NULL constraints in seed data.

        Checks each required column in each table row.

        Args:
            seed_data: Dictionary mapping table names to lists of row dicts
            schema_context: Schema metadata including required column definitions

        Returns:
            List of NotNullViolation objects for any violations found
        """
        violations = []

        # For each table in schema_context
        for table_name, table_schema in schema_context.items():
            if table_name not in seed_data:
                # Table not in seed data, skip
                continue

            table_rows = seed_data[table_name]

            # Check each column for NOT NULL constraints
            columns = table_schema.get("columns", {})
            for column_name, column_info in columns.items():
                if column_info.get("required"):
                    violations.extend(
                        self._validate_required_column(table_name, column_name, table_rows)
                    )

        return violations

    def _validate_required_column(
        self,
        table_name: str,
        column_name: str,
        table_rows: list[dict[str, Any]],
    ) -> list[NotNullViolation]:
        """Validate a single required column.

        Args:
            table_name: Name of table containing the required column
            column_name: Name of required column
            table_rows: Rows from the table

        Returns:
            List of violations for this required column
        """
        violations = []

        # Check each row for NULL values
        for row_index, row in enumerate(table_rows):
            if self._has_null_value(row, column_name):
                violation = self._create_null_violation(table_name, column_name, row_index)
                violations.append(violation)

        return violations

    @staticmethod
    def _has_null_value(row: dict[str, Any], column_name: str) -> bool:
        """Check if a column value is NULL in a row.

        Args:
            row: Row dictionary
            column_name: Column name to check

        Returns:
            True if column value is None, False otherwise
        """
        return row.get(column_name) is None

    @staticmethod
    def _create_null_violation(
        table_name: str, column_name: str, row_index: int
    ) -> NotNullViolation:
        """Create a NOT NULL violation.

        Args:
            table_name: Name of table
            column_name: Name of column
            row_index: Index of row with NULL value

        Returns:
            NotNullViolation object
        """
        return NotNullViolation(
            table=table_name,
            column=column_name,
            row_index=row_index,
            violation_type="NULL_IN_REQUIRED_COLUMN",
            message=(
                f"Column {table_name}.{column_name} is required but row {row_index} has NULL value"
            ),
            severity="ERROR",
        )
