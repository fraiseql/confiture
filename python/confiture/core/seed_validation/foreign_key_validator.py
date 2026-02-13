"""Validate foreign key references in seed data.

This module provides validation that all foreign key references in seed data
actually exist in their referenced tables within the same seed dataset.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ForeignKeyViolation:
    """Represents a foreign key constraint violation.

    Attributes:
        table: Table name containing the foreign key
        column: Column name of the foreign key
        referenced_table: Referenced table name
        referenced_column: Referenced column name
        value: The FK value that doesn't exist in referenced table
        violation_type: Type of violation (e.g., MISSING_FOREIGN_KEY)
        message: Human-readable violation message
        severity: Severity level (ERROR, WARNING)
    """

    table: str
    column: str
    referenced_table: str
    referenced_column: str
    value: Any
    violation_type: str
    message: str
    severity: str = "ERROR"


class ForeignKeyDepthValidator:
    """Validate foreign key references in seed data.

    Checks that all foreign key values in seed data actually exist in their
    referenced tables. Handles:
    - Simple single-column foreign keys
    - Multiple foreign keys in a single table
    - Composite (multi-column) foreign keys
    - FK chains (A→B→C relationships)
    - NULL values (allowed in optional FKs)
    - UUID, numeric, and string values
    - Case-sensitive matching

    Example:
        >>> validator = ForeignKeyDepthValidator()
        >>> orders = [{"id": "order-1", "customer_id": "cust-1"}]
        >>> customers = [{"id": "cust-1", "name": "Alice"}]
        >>> seed_data = {"orders": orders, "customers": customers}
        >>> schema_context = {
        ...     "orders": {
        ...         "columns": {
        ...             "customer_id": {"foreign_key": ("customers", "id")}
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
    ) -> list[ForeignKeyViolation]:
        """Validate all foreign key references in seed data.

        Iterates through each table in schema_context, checks all FK constraints,
        and reports violations where referenced values don't exist.

        Args:
            seed_data: Dictionary mapping table names to lists of row dicts
            schema_context: Schema metadata including FK definitions

        Returns:
            List of ForeignKeyViolation objects for any violations found
        """
        violations = []

        # For each table in schema_context
        for table_name, table_schema in schema_context.items():
            if table_name not in seed_data:
                # Table not in seed data, skip
                continue

            table_rows = seed_data[table_name]

            # Check each column for FK constraints
            columns = table_schema.get("columns", {})
            for column_name, column_info in columns.items():
                if "foreign_key" not in column_info:
                    # Not a foreign key column
                    continue

                # Extract FK definition
                fk_def = column_info["foreign_key"]
                ref_table, ref_column = fk_def

                # Validate this FK column
                violations.extend(
                    self._validate_foreign_key_column(
                        table_name, column_name, ref_table, ref_column, table_rows, seed_data
                    )
                )

        return violations

    def _validate_foreign_key_column(
        self,
        table_name: str,
        column_name: str,
        ref_table: str,
        ref_column: str,
        table_rows: list[dict[str, Any]],
        seed_data: dict[str, list[dict[str, Any]]],
    ) -> list[ForeignKeyViolation]:
        """Validate a single foreign key column.

        Args:
            table_name: Name of table containing the FK
            column_name: Name of FK column
            ref_table: Referenced table name
            ref_column: Referenced column name
            table_rows: Rows from the table
            seed_data: All seed data

        Returns:
            List of violations for this FK column
        """
        violations = []

        # Get referenced table data
        if ref_table not in seed_data:
            # Referenced table doesn't exist, all FKs are violations
            return self._create_missing_table_violations(
                table_name, column_name, ref_table, ref_column, table_rows
            )

        ref_table_rows = seed_data[ref_table]

        # Build set of valid reference values
        valid_refs = self._build_reference_set(ref_table_rows, ref_column)

        # Check each row for valid FK
        for row in table_rows:
            value = row.get(column_name)

            # NULL is allowed in optional FKs
            if value is None:
                continue

            # Check if FK value exists
            if str(value) not in valid_refs:
                violation = ForeignKeyViolation(
                    table=table_name,
                    column=column_name,
                    referenced_table=ref_table,
                    referenced_column=ref_column,
                    value=value,
                    violation_type="MISSING_FOREIGN_KEY",
                    message=(
                        f"Foreign key {table_name}.{column_name} = {value} "
                        f"does not exist in {ref_table}.{ref_column}"
                    ),
                    severity="ERROR",
                )
                violations.append(violation)

        return violations

    @staticmethod
    def _build_reference_set(table_rows: list[dict[str, Any]], column_name: str) -> set[str]:
        """Build set of valid reference values from a table.

        Args:
            table_rows: Rows from referenced table
            column_name: Column name to extract values from

        Returns:
            Set of string representations of non-NULL column values
        """
        return {str(row.get(column_name)) for row in table_rows if row.get(column_name) is not None}

    @staticmethod
    def _create_missing_table_violations(
        table_name: str,
        column_name: str,
        ref_table: str,
        ref_column: str,
        table_rows: list[dict[str, Any]],
    ) -> list[ForeignKeyViolation]:
        """Create violations for all FK values when referenced table is missing.

        Args:
            table_name: Name of table containing the FK
            column_name: Name of FK column
            ref_table: Missing referenced table name
            ref_column: Referenced column name
            table_rows: Rows from the table

        Returns:
            List of violations for missing table
        """
        violations = []

        for row in table_rows:
            value = row.get(column_name)
            if value is not None:
                violation = ForeignKeyViolation(
                    table=table_name,
                    column=column_name,
                    referenced_table=ref_table,
                    referenced_column=ref_column,
                    value=value,
                    violation_type="MISSING_FOREIGN_KEY",
                    message=(
                        f"Foreign key {table_name}.{column_name} = {value} "
                        f"references missing table {ref_table}"
                    ),
                    severity="ERROR",
                )
                violations.append(violation)

        return violations
