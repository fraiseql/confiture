"""SAVEPOINT-based dry-run execution with guaranteed rollback."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import psycopg


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


class DryRunExecutor:
    """Execute migration SQL inside a SAVEPOINT, then rollback.

    Unlike the previous simulation executor, this runs real SQL against
    the database. The SAVEPOINT guarantees no data is persisted.

    Usage:
        executor = DryRunExecutor(conn)
        result = executor.run(migration_name, statements)
    """

    SAVEPOINT_NAME = "confiture_dry_run"

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def run(self, migration_name: str, statements: list[str]) -> DryRunResult:
        """Execute statements in a SAVEPOINT, always rollback."""
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
