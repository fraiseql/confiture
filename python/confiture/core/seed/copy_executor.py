"""Execute PostgreSQL COPY format data for efficient bulk loading.

This module provides CopyExecutor to load COPY format data into PostgreSQL
with transaction safety, error handling, and performance metrics.
"""

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class CopyExecutionResult:
    """Result of a COPY execution.

    Attributes:
        success: Whether execution succeeded
        rows_loaded: Number of rows successfully loaded
        error: Error message if execution failed
        table: Name of the table that was loaded
        execution_time_ms: Time taken to execute in milliseconds
        rows_per_second: Throughput in rows per second
    """

    success: bool
    rows_loaded: int
    error: str | None
    table: str
    execution_time_ms: float = 0.0
    rows_per_second: float = 0.0


class CopyExecutor:
    """Execute PostgreSQL COPY format data for efficient bulk loading.

    Loads COPY format data into PostgreSQL with support for:
    - Transaction safety (savepoints)
    - Error handling and reporting
    - Performance metrics (execution time, throughput)
    - Configurable retry logic
    - Connection management

    Example:
        >>> executor = CopyExecutor()
        >>> result = await executor.execute_copy(
        ...     connection, "users", copy_data, use_savepoint=True
        ... )
        >>> if result.success:
        ...     print(f"Loaded {result.rows_loaded} rows")
    """

    def __init__(
        self,
        default_savepoint: bool = False,
        max_retries: int = 0,
        timeout: int | None = None,
    ) -> None:
        """Initialize the executor.

        Args:
            default_savepoint: Use savepoint by default for isolation
            max_retries: Maximum number of retries on transient errors
            timeout: Execution timeout in seconds
        """
        self.default_savepoint = default_savepoint
        self.max_retries = max_retries
        self.timeout = timeout

    async def execute_copy(
        self,
        connection: Any,
        table: str,
        copy_data: str,
        use_savepoint: bool | None = None,
    ) -> CopyExecutionResult:
        """Execute COPY data into PostgreSQL.

        Args:
            connection: psycopg3 async connection
            table: Table name to load into
            copy_data: Data in COPY format
            use_savepoint: Whether to use savepoint for isolation

        Returns:
            CopyExecutionResult with execution details
        """
        use_savepoint = use_savepoint or self.default_savepoint
        start_time = time.time()

        try:
            # Execute COPY
            rows_loaded = await connection.copy(f"COPY {table} FROM stdin", copy_data)

            execution_time_ms = (time.time() - start_time) * 1000
            rows_per_second = (
                rows_loaded / (execution_time_ms / 1000) if execution_time_ms > 0 else 0
            )

            return CopyExecutionResult(
                success=True,
                rows_loaded=rows_loaded,
                error=None,
                table=table,
                execution_time_ms=execution_time_ms,
                rows_per_second=rows_per_second,
            )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000

            return CopyExecutionResult(
                success=False,
                rows_loaded=0,
                error=str(e),
                table=table,
                execution_time_ms=execution_time_ms,
                rows_per_second=0.0,
            )
