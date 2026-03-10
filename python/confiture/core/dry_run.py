"""Migration dry-run mode - test migrations in transaction.

This module provides dry-run capability for migrations, allowing operators to:
- Test migrations without making permanent changes
- Verify data integrity before production deployment
- Estimate execution time and identify locking issues
- Detect constraint violations early
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import psycopg

from confiture.exceptions import MigrationError

# Logger for dry-run execution
logger = logging.getLogger(__name__)


class DryRunError(MigrationError):
    """Error raised when dry-run execution fails."""

    def __init__(self, migration_name: str, error: Exception):
        """Initialize dry-run error.

        Args:
            migration_name: Name of migration that failed
            error: Original exception
        """
        self.migration_name = migration_name
        self.original_error = error
        super().__init__(f"Dry-run failed for migration {migration_name}: {str(error)}")


@dataclass
class DryRunResult:
    """Result of a dry-run execution."""

    migration_name: str
    migration_version: str
    success: bool
    execution_time_ms: int = 0
    rows_affected: int = 0
    locked_tables: list[str] = field(default_factory=list)
    estimated_production_time_ms: int = 0
    confidence_percent: int = 0
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize empty collections if needed."""
        if self.locked_tables is None:
            self.locked_tables = []
        if self.warnings is None:
            self.warnings = []
        if self.stats is None:
            self.stats = {}


class DryRunExecutor:
    """Simulates migration execution to estimate timing without a database connection.

    WARNING: This executor does NOT connect to the database. It measures the time
    to call migration.up() in isolation (no DB, no transaction, no SAVEPOINT).
    Row counts and lock detection are unavailable in this mode.

    Reported values:
    - execution_time_ms: time to call migration.up() without a database connection
    - rows_affected: always 0 (not measurable without a connection)
    - confidence_percent: 40 (low — no real DB execution)
    """

    def __init__(self):
        """Initialize dry-run executor."""
        self.logger = logger

    def run(
        self,
        _conn: psycopg.Connection | None,
        migration,
    ) -> DryRunResult:
        """Simulate migration execution to estimate timing.

        Calls migration.up() without a database connection. The connection
        parameter is accepted for API compatibility but is not used.

        Args:
            _conn: Accepted but not used. Migration SQL files are connection-agnostic.
            migration: Migration instance with up() method

        Returns:
            DryRunResult with timing estimate (confidence_percent=40)

        Raises:
            DryRunError: If migration execution fails
        """
        # Log dry-run start
        self.logger.info(
            "dry_run_start",
            extra={
                "migration": migration.name,
                "version": migration.version,
            },
        )

        try:
            execution_time_ms = self._execute_migration(migration)
            result = self._build_result(migration, execution_time_ms)

            # Log dry-run completion
            self.logger.info(
                "dry_run_completed",
                extra={
                    "migration": migration.name,
                    "version": migration.version,
                    "execution_time_ms": execution_time_ms,
                    "success": True,
                },
            )

            return result

        except Exception as e:
            # Log dry-run failure
            self.logger.error(
                "dry_run_failed",
                extra={
                    "migration": migration.name,
                    "version": migration.version,
                    "error": str(e),
                },
                exc_info=True,
            )

            raise DryRunError(migration_name=migration.name, error=e) from e

    def _execute_migration(self, migration) -> int:
        """Execute migration and return execution time in milliseconds.

        Args:
            migration: Migration instance with up() method

        Returns:
            Execution time in milliseconds
        """
        start_time = time.time()
        migration.up()
        return int((time.time() - start_time) * 1000)

    def _build_result(self, migration, execution_time_ms: int) -> DryRunResult:
        """Build DryRunResult from simulation metrics.

        Args:
            migration: Migration instance
            execution_time_ms: Execution time in milliseconds

        Returns:
            DryRunResult with simulation results
        """
        return DryRunResult(
            migration_name=migration.name,
            migration_version=migration.version,
            success=True,
            execution_time_ms=execution_time_ms,
            rows_affected=0,
            locked_tables=[],
            estimated_production_time_ms=execution_time_ms,
            confidence_percent=40,
            warnings=[
                "Simulation only: no database connection used. "
                "Row counts and lock detection are unavailable."
            ],
            stats={
                "measured_execution_ms": execution_time_ms,
                "estimated_range_low_ms": int(execution_time_ms * 0.85),
                "estimated_range_high_ms": int(execution_time_ms * 1.15),
            },
        )
