"""Level 4: Runtime validation.

Database connection, table existence, dry-run.

Validates resolution setup without actually loading data.
Uses SAVEPOINT for safe dry-run execution.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from psycopg import sql

from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)

if TYPE_CHECKING:
    from confiture.core.seed.validation.prep_seed.resolvers import Resolver


class Level4RuntimeValidator:
    """Validates runtime environment before seed loading.

    Checks:
    - Database connectivity
    - Target tables exist in database
    - Dry-run resolution with SAVEPOINT

    Example:
        >>> validator = Level4RuntimeValidator()
        >>> violations = validator.validate_runtime(
        ...     resolver, target_schema="catalog", target_table="tb_manufacturer"
        ... )
    """

    def __init__(self, table_exists: Callable[[str, str], bool] | None = None) -> None:
        """Initialize the validator.

        Args:
            table_exists: Optional function(schema, table) -> bool
        """
        self.table_exists = table_exists

    def validate_runtime(
        self,
        resolver: Resolver,
        target_schema: str,
        target_table: str,
    ) -> list[PrepSeedViolation]:
        """Validate runtime environment for resolution.

        Args:
            resolver: The resolution function
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
                    file_path=resolver.file,
                    line_number=resolver.line,
                    impact=f"{resolver.name} will fail",
                    fix_available=False,
                )
            )

        return violations

    def dry_run_resolution(
        self,
        resolver: Resolver,
        connection: Any,
        savepoint_name: str = "sp_validation",
    ) -> list[PrepSeedViolation]:
        """Call *resolver* inside a SAVEPOINT and roll it back: nothing it writes is kept.

        The call names the routine by :attr:`Resolver.identifier` and the
        savepoint by :class:`psycopg.sql.Identifier`, with no parameters, so a
        mixed-case or ``%``-bearing name is the routine the DDL created.

        Args:
            resolver: The resolution function
            connection: Database connection
            savepoint_name: SAVEPOINT name for rollback

        Returns:
            List of violations found
        """
        savepoint = sql.Identifier(savepoint_name)
        try:
            connection.execute(sql.SQL("SAVEPOINT {}").format(savepoint))
            connection.execute(sql.SQL("SELECT {}()").format(resolver.identifier))
            connection.execute(sql.SQL("ROLLBACK TO SAVEPOINT {}").format(savepoint))
        except Exception as e:  # Reason: executes a user resolution function under a savepoint; any failure is a reported violation
            # The savepoint may not exist if creating it is what failed.
            with contextlib.suppress(Exception):
                connection.execute(sql.SQL("ROLLBACK TO SAVEPOINT {}").format(savepoint))
            return [
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                    severity=ViolationSeverity.ERROR,
                    message=f"Resolution function {resolver.name} execution failed: {e!s}",
                    file_path=resolver.file,
                    line_number=resolver.line,
                    impact="Resolution cannot execute",
                    fix_available=False,
                )
            ]
        return []
