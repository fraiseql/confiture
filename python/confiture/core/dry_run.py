"""SAVEPOINT-based dry-run execution with guaranteed rollback."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import psycopg

from confiture.exceptions import ConfiturError

logger = logging.getLogger(__name__)


class DryRunError(ConfiturError):
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


@dataclass(frozen=True)
class StatementResult:
    """Result of executing a single SQL statement in dry-run."""

    sql: str
    success: bool
    execution_time_ms: float
    rows_affected: int = 0
    error: str | None = None


@dataclass(frozen=True)
class DryRunResult:
    """Aggregate result of a dry-run execution."""

    migration_name: str
    success: bool
    total_time_ms: float
    confidence_pct: int  # 80-90 for SAVEPOINT-based
    statements: list[StatementResult] = field(default_factory=list)
    error: str | None = None

    @property
    def rows_affected(self) -> int:
        return sum(s.rows_affected for s in self.statements)

    @property
    def failed_statements(self) -> list[StatementResult]:
        return [s for s in self.statements if not s.success]

    # Backward compatibility properties for old API
    @property
    def confidence_percent(self) -> int:
        """Backward compatibility alias."""
        return self.confidence_pct

    @property
    def execution_time_ms(self) -> float:
        """Backward compatibility alias."""
        return self.total_time_ms

    @property
    def migration_version(self) -> str:
        """Backward compatibility: assume migration_name contains version."""
        return getattr(self, "_migration_version", self.migration_name)

    @property
    def warnings(self) -> list[str]:
        """Backward compatibility: generate warnings from statements."""
        warnings = []
        if self.confidence_pct < 80:
            warnings.append(
                "Simulation only: no database connection used. Row counts and lock detection are unavailable."
            )
        return warnings


@dataclass(frozen=True)
class _LegacyDryRunResult(DryRunResult):
    """DryRunResult subclass for legacy API compatibility."""

    migration: Any = None  # Store migration object for version access

    @property
    def migration_version(self) -> str:
        """Backward compatibility: get version from migration object."""
        if self.migration:
            return getattr(self.migration, "version", self.migration_name)
        return self.migration_name


class DryRunExecutor:
    """Execute migration SQL inside a SAVEPOINT, then rollback.

    Unlike the previous simulation executor, this runs real SQL against
    the database. The SAVEPOINT guarantees no data is persisted.

    Supports both old and new APIs for backward compatibility.
    """

    SAVEPOINT_NAME = "confiture_dry_run"

    def __init__(self, conn: psycopg.Connection | None = None) -> None:
        self._conn = conn

    def run(
        self,
        migration_name_or_conn=None,
        statements_or_migration=None,
        *,
        _conn: psycopg.Connection | None = None,
        migration=None,
        migration_name: str | None = None,
        statements: list[str] | None = None,
    ) -> DryRunResult:
        """Execute migration in dry-run mode.

        Supports two APIs for backward compatibility:

        Old API (deprecated):
            executor.run(migration=migration_obj)

        New API:
            executor = DryRunExecutor(conn)
            executor.run("migration_name", ["SQL...", ...])
            # or equivalently:
            executor.run(migration_name="name", statements=["SQL..."])
        """
        # Reconcile positional new-API args with keyword form.  The first
        # positional may be either the migration_name (new API) or — in
        # very old call sites — a connection object that's now ignored.
        if migration_name_or_conn is not None and migration_name is None:
            if isinstance(migration_name_or_conn, str):
                migration_name = migration_name_or_conn
            elif isinstance(migration_name_or_conn, psycopg.Connection):
                # Pre-instance-conn callers passed conn first; silently
                # accepted for compatibility.
                pass
            elif hasattr(migration_name_or_conn, "up"):
                # Legacy: caller passed a migration object positionally.
                migration = migration_name_or_conn
        if statements_or_migration is not None and statements is None:
            if isinstance(statements_or_migration, list):
                statements = statements_or_migration
            elif hasattr(statements_or_migration, "up"):
                migration = statements_or_migration

        # Handle old API
        if migration is not None:
            # Old simulation API - fallback to basic timing
            start_time = time.perf_counter()
            try:
                migration.up()
                execution_time_ms = int((time.perf_counter() - start_time) * 1000)
                # For old API, create a result that knows about the migration object
                return _LegacyDryRunResult(
                    migration=migration,
                    migration_name=getattr(migration, "name", "unknown"),
                    success=True,
                    total_time_ms=execution_time_ms,
                    confidence_pct=40,  # Low confidence for simulation
                    statements=[],
                )
            except Exception as e:
                execution_time_ms = int((time.perf_counter() - start_time) * 1000)
                raise DryRunError(getattr(migration, "name", "unknown"), e) from e

        # New API
        if not self._conn:
            raise ValueError("Connection required for SAVEPOINT-based dry-run")
        if not migration_name or not statements:
            raise ValueError("migration_name and statements required for new API")

        results: list[StatementResult] = []
        start = time.perf_counter()
        error: str | None = None
        success = True

        self._conn.execute(f"SAVEPOINT {self.SAVEPOINT_NAME}")
        try:
            for sql in statements:
                result = self._execute_one(sql)
                results.append(result)
                if not result.success:
                    success = False
                    error = result.error
                    break  # stop on first failure
        finally:
            self._conn.execute(f"ROLLBACK TO SAVEPOINT {self.SAVEPOINT_NAME}")
            self._conn.execute(f"RELEASE SAVEPOINT {self.SAVEPOINT_NAME}")

        total_ms = (time.perf_counter() - start) * 1000
        return DryRunResult(
            migration_name=migration_name,
            success=success,
            total_time_ms=total_ms,
            confidence_pct=85,
            statements=results,
            error=error,
        )

    def _execute_one(self, sql: str) -> StatementResult:
        """Execute a single statement, capturing metrics."""
        start = time.perf_counter()
        try:
            cur = self._conn.execute(sql)
            elapsed = (time.perf_counter() - start) * 1000
            return StatementResult(
                sql=sql,
                success=True,
                execution_time_ms=elapsed,
                rows_affected=cur.rowcount if cur.rowcount >= 0 else 0,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return StatementResult(
                sql=sql,
                success=False,
                execution_time_ms=elapsed,
                error=str(exc),
            )
