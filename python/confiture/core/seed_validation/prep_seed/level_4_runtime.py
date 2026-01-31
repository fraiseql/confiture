"""Level 4: Runtime validation.

Cycles 1-4: Database connection, table existence, column types, dry-run.

Validates resolution setup without actually loading data.
Uses SAVEPOINT for safe dry-run execution.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)


class Level4RuntimeValidator:
    """Validates runtime environment before seed loading.

    Checks:
    - Database connectivity
    - Target tables exist in database
    - Column types match expectations
    - Dry-run resolution with SAVEPOINT

    Example:
        >>> validator = Level4RuntimeValidator()
        >>> violations = validator.validate_runtime(
        ...     func_name="fn_resolve_tb_manufacturer",
        ...     target_schema="catalog",
        ...     target_table="tb_manufacturer"
        ... )
    """

    def __init__(
        self,
        table_exists: Callable[[str, str], bool] | None = None,
        get_column_type: Callable[[str, str, str], str | None] | None = None,
    ) -> None:
        """Initialize the validator.

        Args:
            table_exists: Optional function(schema, table) -> bool
            get_column_type: Optional function(schema, table, column) -> type_str
        """
        self.table_exists = table_exists
        self.get_column_type = get_column_type

    def validate_runtime(
        self,
        func_name: str,
        target_schema: str,
        target_table: str,
    ) -> list[PrepSeedViolation]:
        """Validate runtime environment for resolution.

        Args:
            func_name: Name of the resolution function
            target_schema: Target schema (e.g., "catalog")
            target_table: Target table (e.g., "tb_manufacturer")

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        # Check if table exists in database
        if self.table_exists and not self.table_exists(target_schema, target_table):
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                    severity=ViolationSeverity.ERROR,
                    message=(
                        f"Target table {target_schema}.{target_table} does not exist in database"
                    ),
                    file_path=f"db/schema/functions/{func_name}.sql",
                    line_number=1,
                    impact="Resolution function will fail",
                    fix_available=False,
                )
            )

        return violations

    def validate_column_type(
        self,
        schema: str,
        table: str,
        column: str,
        expected_type: str,
    ) -> list[PrepSeedViolation]:
        """Validate column type matches expected.

        Args:
            schema: Schema name
            table: Table name
            column: Column name
            expected_type: Expected type (e.g., "BIGINT")

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        if not self.get_column_type:
            return violations

        actual_type = self.get_column_type(schema, table, column)
        if actual_type and actual_type.upper() != expected_type.upper():
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_MAPPING,
                    severity=ViolationSeverity.ERROR,
                    message=(
                        f"Column {schema}.{table}.{column} has type {actual_type} "
                        f"but expected {expected_type}"
                    ),
                    file_path=f"db/schema/{table}.sql",
                    line_number=1,
                    impact="Type mismatch may cause resolution failures",
                )
            )

        return violations

    def dry_run_resolution(
        self,
        func_name: str,
        connection: Any,
        savepoint_name: str = "sp_validation",
    ) -> list[PrepSeedViolation]:
        """Execute resolution function with SAVEPOINT (no commit).

        Args:
            func_name: Name of the resolution function
            connection: Database connection
            savepoint_name: SAVEPOINT name for rollback

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        try:
            # Create savepoint
            connection.execute(f"SAVEPOINT {savepoint_name};")

            # Execute resolution function
            func_call = f"SELECT {func_name}();"
            connection.execute(func_call)

            # Rollback to savepoint (undo changes)
            connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name};")

            return violations

        except Exception as e:
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                    severity=ViolationSeverity.ERROR,
                    message=(
                        f"Resolution function {func_name} execution failed: {str(e)}"
                    ),
                    file_path=f"db/schema/functions/{func_name}.sql",
                    line_number=1,
                    impact="Resolution cannot execute",
                    fix_available=False,
                )
            )

            # Try to rollback on error (savepoint may not exist if execute failed)
            with contextlib.suppress(Exception):
                connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name};")

            return violations
