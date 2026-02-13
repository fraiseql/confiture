"""Validate unique constraints in seed data.

This module provides validation that all values in UNIQUE columns are actually
unique within the seed dataset, and detects duplicate values that would violate
constraints.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class UniqueConstraintViolation:
    """Represents a unique constraint violation.

    Attributes:
        table: Table name containing the UNIQUE constraint
        column: Column name with UNIQUE constraint
        value: The value that appears more than once
        duplicate_count: Number of times this value appears
        violation_type: Type of violation (e.g., DUPLICATE_UNIQUE_VALUE)
        message: Human-readable violation message
        severity: Severity level (ERROR, WARNING)
    """

    table: str
    column: str
    value: Any
    duplicate_count: int
    violation_type: str
    message: str
    severity: str = "ERROR"


class UniqueConstraintValidator:
    """Validate unique constraints in seed data.

    Checks that all values in UNIQUE columns are actually unique within
    the seed dataset. Handles:
    - Simple single-column UNIQUE constraints
    - Multiple UNIQUE constraints in a single table
    - Composite (multi-column) UNIQUE constraints
    - NULL values (multiple NULLs allowed)
    - UUID, numeric, and string values
    - Case-sensitive matching

    Example:
        >>> validator = UniqueConstraintValidator()
        >>> users = [
        ...     {"id": "1", "email": "alice@example.com"},
        ...     {"id": "2", "email": "bob@example.com"},
        ... ]
        >>> seed_data = {"users": users}
        >>> schema_context = {
        ...     "users": {
        ...         "columns": {
        ...             "email": {"unique": True}
        ...         }
        ...     }
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
    ) -> list[UniqueConstraintViolation]:
        """Validate all UNIQUE constraints in seed data.

        Checks both single-column UNIQUE constraints and composite keys.

        Args:
            seed_data: Dictionary mapping table names to lists of row dicts
            schema_context: Schema metadata including UNIQUE definitions

        Returns:
            List of UniqueConstraintViolation objects for any violations found
        """
        violations = []

        # For each table in schema_context
        for table_name, table_schema in schema_context.items():
            if table_name not in seed_data:
                # Table not in seed data, skip
                continue

            table_rows = seed_data[table_name]

            # Check single-column UNIQUE constraints
            columns = table_schema.get("columns", {})
            for column_name, column_info in columns.items():
                if column_info.get("unique"):
                    violations.extend(
                        self._validate_unique_column(table_name, column_name, table_rows)
                    )

            # Check composite UNIQUE constraints
            unique_constraints = table_schema.get("unique_constraints", [])
            for constraint in unique_constraints:
                constraint_columns = constraint.get("columns", [])
                if constraint_columns:
                    violations.extend(
                        self._validate_composite_unique(table_name, constraint_columns, table_rows)
                    )

        return violations

    def _validate_unique_column(
        self,
        table_name: str,
        column_name: str,
        table_rows: list[dict[str, Any]],
    ) -> list[UniqueConstraintViolation]:
        """Validate a single UNIQUE column.

        Args:
            table_name: Name of table containing the UNIQUE constraint
            column_name: Name of UNIQUE column
            table_rows: Rows from the table

        Returns:
            List of violations for this UNIQUE column
        """
        # Count occurrences of each value
        value_counts = self._count_column_values(table_rows, column_name)

        # Report violations for duplicates
        return self._create_unique_violations(
            table_name, column_name, value_counts, "DUPLICATE_UNIQUE_VALUE"
        )

    @staticmethod
    def _count_column_values(table_rows: list[dict[str, Any]], column_name: str) -> dict[str, int]:
        """Count occurrences of each non-NULL value in a column.

        Args:
            table_rows: Rows from the table
            column_name: Column name to count

        Returns:
            Dictionary mapping string values to occurrence counts
        """
        value_counts: dict[str, int] = {}
        for row in table_rows:
            value = row.get(column_name)

            # NULL values don't trigger violations
            if value is None:
                continue

            # Use string representation for comparison
            str_value = str(value)
            value_counts[str_value] = value_counts.get(str_value, 0) + 1

        return value_counts

    @staticmethod
    def _create_unique_violations(
        table_name: str,
        column_name: str,
        value_counts: dict[str, int],
        violation_type: str,
    ) -> list[UniqueConstraintViolation]:
        """Create violations for duplicate values.

        Args:
            table_name: Name of table
            column_name: Name of column(s) involved
            value_counts: Dictionary of value -> count
            violation_type: Type of violation (DUPLICATE_UNIQUE_VALUE or DUPLICATE_COMPOSITE_KEY)

        Returns:
            List of violations for duplicates
        """
        violations = []

        for str_value, count in value_counts.items():
            if count > 1:
                violation = UniqueConstraintViolation(
                    table=table_name,
                    column=column_name,
                    value=str_value,
                    duplicate_count=count,
                    violation_type=violation_type,
                    message=(
                        f"Column {table_name}.{column_name} is UNIQUE but value "
                        f"{str_value} appears {count} times"
                    ),
                    severity="ERROR",
                )
                violations.append(violation)

        return violations

    def _validate_composite_unique(
        self,
        table_name: str,
        constraint_columns: list[str],
        table_rows: list[dict[str, Any]],
    ) -> list[UniqueConstraintViolation]:
        """Validate a composite UNIQUE constraint.

        Args:
            table_name: Name of table containing the constraint
            constraint_columns: List of columns in the composite key
            table_rows: Rows from the table

        Returns:
            List of violations for this composite constraint
        """
        # Count occurrences of each composite key
        key_counts = self._count_composite_keys(table_rows, constraint_columns)

        # Report violations for duplicates
        cols_str = ", ".join(constraint_columns)
        violations = []

        for key_tuple, count in key_counts.items():
            if count > 1:
                key_str = " / ".join(str(v) for v in key_tuple)
                violation = UniqueConstraintViolation(
                    table=table_name,
                    column=cols_str,
                    value=key_str,
                    duplicate_count=count,
                    violation_type="DUPLICATE_COMPOSITE_KEY",
                    message=(
                        f"Composite UNIQUE constraint on {table_name}({cols_str}) "
                        f"violated: key ({key_str}) appears {count} times"
                    ),
                    severity="ERROR",
                )
                violations.append(violation)

        return violations

    @staticmethod
    def _count_composite_keys(
        table_rows: list[dict[str, Any]], constraint_columns: list[str]
    ) -> dict[tuple[str, ...], int]:
        """Count occurrences of each composite key.

        Args:
            table_rows: Rows from the table
            constraint_columns: List of columns in the composite key

        Returns:
            Dictionary mapping composite key tuples to occurrence counts
        """
        key_counts: dict[tuple[str, ...], int] = {}

        for row in table_rows:
            # Extract values for all constraint columns
            key_values = []
            has_null = False
            for col in constraint_columns:
                val = row.get(col)
                if val is None:
                    has_null = True
                key_values.append(val)

            # Skip if any NULL (NULLs in composite keys don't trigger violations)
            if has_null:
                continue

            key_tuple = tuple(str(v) for v in key_values)
            key_counts[key_tuple] = key_counts.get(key_tuple, 0) + 1

        return key_counts
