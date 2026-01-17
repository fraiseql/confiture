"""Large table migration patterns.

Provides utilities for migrating large tables (>1M rows) without
blocking production traffic. Includes batched operations, progress
reporting, and resumable patterns.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BatchConfig:
    """Configuration for batched operations.

    Attributes:
        batch_size: Number of rows per batch
        sleep_between_batches: Seconds to wait between batches
        max_retries: Maximum retries per batch on failure
        progress_callback: Optional callback for progress updates
        checkpoint_callback: Optional callback for checkpointing
    """

    batch_size: int = 10000
    sleep_between_batches: float = 0.1
    max_retries: int = 3
    progress_callback: Callable[[int, int], None] | None = None
    checkpoint_callback: Callable[[int], None] | None = None


@dataclass
class BatchProgress:
    """Progress of a batched operation.

    Tracks rows processed, batches completed, and timing information.
    """

    total_rows: int
    processed_rows: int = 0
    current_batch: int = 0
    total_batches: int = 0
    elapsed_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def percent_complete(self) -> float:
        """Get completion percentage."""
        if self.total_rows == 0:
            return 100.0
        return (self.processed_rows / self.total_rows) * 100

    @property
    def is_complete(self) -> bool:
        """Check if operation is complete."""
        return self.processed_rows >= self.total_rows

    @property
    def rows_per_second(self) -> float:
        """Calculate processing rate."""
        if self.elapsed_seconds == 0:
            return 0.0
        return self.processed_rows / self.elapsed_seconds

    @property
    def estimated_remaining_seconds(self) -> float:
        """Estimate remaining time."""
        if self.rows_per_second == 0:
            return 0.0
        remaining_rows = self.total_rows - self.processed_rows
        return remaining_rows / self.rows_per_second

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_rows": self.total_rows,
            "processed_rows": self.processed_rows,
            "percent_complete": round(self.percent_complete, 2),
            "current_batch": self.current_batch,
            "total_batches": self.total_batches,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "rows_per_second": round(self.rows_per_second, 2),
            "estimated_remaining_seconds": round(self.estimated_remaining_seconds, 2),
            "errors": self.errors,
        }


class BatchedMigration:
    """Execute migrations in batches for large tables.

    Provides methods for common large table operations that need
    to be done in batches to avoid long-running transactions.

    Example:
        >>> config = BatchConfig(batch_size=10000)
        >>> batched = BatchedMigration(conn, config)
        >>> progress = batched.add_column_with_default(
        ...     table="users",
        ...     column="status",
        ...     column_type="TEXT",
        ...     default="'active'"
        ... )
        >>> print(f"Processed {progress.processed_rows} rows")
    """

    def __init__(self, connection: Any, config: BatchConfig | None = None):
        """Initialize batched migration.

        Args:
            connection: Database connection
            config: Batch configuration (optional)
        """
        self.connection = connection
        self.config = config or BatchConfig()

    def add_column_with_default(
        self,
        table: str,
        column: str,
        column_type: str,
        default: str,
        start_from: int = 0,
    ) -> BatchProgress:
        """Add column with default value in batches.

        PostgreSQL 11+ adds columns with defaults instantly, but
        backfilling existing NULL rows can lock the table. This
        does the backfill in batches.

        Args:
            table: Table name
            column: Column name
            column_type: Column type (e.g., "TEXT", "INTEGER")
            default: Default value expression
            start_from: Resume from this row count (for resumption)

        Returns:
            BatchProgress with operation result
        """
        start_time = time.perf_counter()

        with self.connection.cursor() as cur:
            # Add column without default first (instant in PG 11+)
            cur.execute(
                f"""
                ALTER TABLE {table}
                ADD COLUMN IF NOT EXISTS {column} {column_type}
            """
            )
            self.connection.commit()

            # Get total rows needing update
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")
            total_rows = cur.fetchone()[0]

            if total_rows == 0:
                return BatchProgress(total_rows=0)

            total_batches = (total_rows + self.config.batch_size - 1) // self.config.batch_size
            processed = start_from
            progress = BatchProgress(
                total_rows=total_rows,
                processed_rows=processed,
                total_batches=total_batches,
            )

            batch_num = start_from // self.config.batch_size

            while processed < total_rows:
                batch_num += 1

                for attempt in range(self.config.max_retries):
                    try:
                        # Update batch using ctid for efficiency
                        cur.execute(
                            f"""
                            UPDATE {table}
                            SET {column} = {default}
                            WHERE ctid IN (
                                SELECT ctid FROM {table}
                                WHERE {column} IS NULL
                                LIMIT {self.config.batch_size}
                            )
                        """
                        )
                        rows_affected = cur.rowcount
                        self.connection.commit()
                        break
                    except Exception as e:
                        self.connection.rollback()
                        if attempt == self.config.max_retries - 1:
                            progress.errors.append(f"Batch {batch_num}: {e}")
                            raise
                        logger.warning(f"Batch {batch_num} failed, retrying: {e}")
                        time.sleep(self.config.sleep_between_batches * 2)

                processed += rows_affected
                progress.processed_rows = processed
                progress.current_batch = batch_num
                progress.elapsed_seconds = time.perf_counter() - start_time

                if self.config.progress_callback:
                    self.config.progress_callback(processed, total_rows)

                if self.config.checkpoint_callback:
                    self.config.checkpoint_callback(processed)

                logger.info(
                    f"Batch {batch_num}/{total_batches}: "
                    f"{progress.percent_complete:.1f}% complete "
                    f"({progress.rows_per_second:.0f} rows/sec)"
                )

                if rows_affected == 0:
                    break

                if self.config.sleep_between_batches > 0:
                    time.sleep(self.config.sleep_between_batches)

            # Set default for future inserts
            cur.execute(
                f"""
                ALTER TABLE {table}
                ALTER COLUMN {column} SET DEFAULT {default}
            """
            )
            self.connection.commit()

            progress.elapsed_seconds = time.perf_counter() - start_time
            return progress

    def backfill_column(
        self,
        table: str,
        column: str,
        expression: str,
        where_clause: str = "TRUE",
        start_from: int = 0,
    ) -> BatchProgress:
        """Backfill column values in batches.

        Example:
            >>> progress = batched.backfill_column(
            ...     table="orders",
            ...     column="total_cents",
            ...     expression="(subtotal + tax) * 100",
            ...     where_clause="total_cents IS NULL"
            ... )
        """
        start_time = time.perf_counter()

        with self.connection.cursor() as cur:
            # Get total rows
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_clause}")
            total_rows = cur.fetchone()[0]

            if total_rows == 0:
                return BatchProgress(total_rows=0)

            total_batches = (total_rows + self.config.batch_size - 1) // self.config.batch_size
            processed = start_from
            progress = BatchProgress(
                total_rows=total_rows,
                processed_rows=processed,
                total_batches=total_batches,
            )

            batch_num = start_from // self.config.batch_size

            while True:
                batch_num += 1

                cur.execute(
                    f"""
                    UPDATE {table}
                    SET {column} = {expression}
                    WHERE ctid IN (
                        SELECT ctid FROM {table}
                        WHERE {where_clause}
                        LIMIT {self.config.batch_size}
                    )
                """
                )

                rows_affected = cur.rowcount
                if rows_affected == 0:
                    break

                self.connection.commit()
                processed += rows_affected
                progress.processed_rows = processed
                progress.current_batch = batch_num
                progress.elapsed_seconds = time.perf_counter() - start_time

                if self.config.progress_callback:
                    self.config.progress_callback(processed, total_rows)

                if self.config.checkpoint_callback:
                    self.config.checkpoint_callback(processed)

                logger.info(
                    f"Backfill batch {batch_num}: {progress.percent_complete:.1f}% complete"
                )

                if self.config.sleep_between_batches > 0:
                    time.sleep(self.config.sleep_between_batches)

            progress.elapsed_seconds = time.perf_counter() - start_time
            return progress

    def delete_in_batches(
        self,
        table: str,
        where_clause: str,
        start_from: int = 0,
    ) -> BatchProgress:
        """Delete rows in batches to avoid long locks.

        Example:
            >>> progress = batched.delete_in_batches(
            ...     table="audit_logs",
            ...     where_clause="created_at < NOW() - INTERVAL '1 year'"
            ... )
        """
        start_time = time.perf_counter()

        with self.connection.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_clause}")
            total_rows = cur.fetchone()[0]

            if total_rows == 0:
                return BatchProgress(total_rows=0)

            total_batches = (total_rows + self.config.batch_size - 1) // self.config.batch_size
            processed = start_from
            progress = BatchProgress(
                total_rows=total_rows,
                processed_rows=processed,
                total_batches=total_batches,
            )

            batch_num = start_from // self.config.batch_size

            while True:
                batch_num += 1

                cur.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE ctid IN (
                        SELECT ctid FROM {table}
                        WHERE {where_clause}
                        LIMIT {self.config.batch_size}
                    )
                """
                )

                rows_deleted = cur.rowcount
                if rows_deleted == 0:
                    break

                self.connection.commit()
                processed += rows_deleted
                progress.processed_rows = processed
                progress.current_batch = batch_num
                progress.elapsed_seconds = time.perf_counter() - start_time

                if self.config.progress_callback:
                    self.config.progress_callback(processed, total_rows)

                if self.config.checkpoint_callback:
                    self.config.checkpoint_callback(processed)

                logger.info(
                    f"Delete batch {batch_num}: {progress.percent_complete:.1f}% complete"
                )

                if self.config.sleep_between_batches > 0:
                    time.sleep(self.config.sleep_between_batches)

            progress.elapsed_seconds = time.perf_counter() - start_time
            return progress

    def copy_to_new_table(
        self,
        source_table: str,
        target_table: str,
        columns: list[str] | None = None,
        transform: dict[str, str] | None = None,
        where_clause: str = "TRUE",
    ) -> BatchProgress:
        """Copy data to a new table in batches.

        Useful for table restructuring without blocking reads on source.

        Args:
            source_table: Source table name
            target_table: Target table name (must exist)
            columns: Columns to copy (None = all)
            transform: Column transformations {col: expression}
            where_clause: Filter condition

        Example:
            >>> progress = batched.copy_to_new_table(
            ...     source_table="users",
            ...     target_table="users_new",
            ...     transform={"email": "LOWER(email)"}
            ... )
        """
        start_time = time.perf_counter()

        with self.connection.cursor() as cur:
            # Get total rows
            cur.execute(f"SELECT COUNT(*) FROM {source_table} WHERE {where_clause}")
            total_rows = cur.fetchone()[0]

            if total_rows == 0:
                return BatchProgress(total_rows=0)

            # Get columns if not specified
            if columns is None:
                cur.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = %s AND table_schema = 'public'
                    ORDER BY ordinal_position
                """,
                    (source_table,),
                )
                columns = [row[0] for row in cur.fetchall()]

            # Build select expressions
            transform = transform or {}
            select_exprs = [transform.get(col, col) for col in columns]
            select_str = ", ".join(select_exprs)
            columns_str = ", ".join(columns)

            # Track last ID for pagination
            cur.execute(f"SELECT MIN(ctid) FROM {source_table} WHERE {where_clause}")
            result = cur.fetchone()
            if result[0] is None:
                return BatchProgress(total_rows=0)

            total_batches = (total_rows + self.config.batch_size - 1) // self.config.batch_size
            processed = 0
            progress = BatchProgress(
                total_rows=total_rows,
                total_batches=total_batches,
            )
            batch_num = 0

            # Use a tracking column for batching
            cur.execute(
                f"""
                CREATE TEMP TABLE _batch_tracker AS
                SELECT ctid as row_ctid, ROW_NUMBER() OVER () as rn
                FROM {source_table}
                WHERE {where_clause}
            """
            )
            self.connection.commit()

            try:
                while processed < total_rows:
                    batch_num += 1
                    offset = processed

                    cur.execute(
                        f"""
                        INSERT INTO {target_table} ({columns_str})
                        SELECT {select_str}
                        FROM {source_table} s
                        WHERE s.ctid IN (
                            SELECT row_ctid FROM _batch_tracker
                            WHERE rn > %s AND rn <= %s
                        )
                    """,
                        (offset, offset + self.config.batch_size),
                    )

                    rows_inserted = cur.rowcount
                    if rows_inserted == 0:
                        break

                    self.connection.commit()
                    processed += rows_inserted
                    progress.processed_rows = processed
                    progress.current_batch = batch_num
                    progress.elapsed_seconds = time.perf_counter() - start_time

                    if self.config.progress_callback:
                        self.config.progress_callback(processed, total_rows)

                    logger.info(
                        f"Copy batch {batch_num}/{total_batches}: "
                        f"{progress.percent_complete:.1f}% complete"
                    )

                    if self.config.sleep_between_batches > 0:
                        time.sleep(self.config.sleep_between_batches)

            finally:
                cur.execute("DROP TABLE IF EXISTS _batch_tracker")
                self.connection.commit()

            progress.elapsed_seconds = time.perf_counter() - start_time
            return progress


class OnlineIndexBuilder:
    """Build indexes without blocking writes.

    Provides utilities for creating, dropping, and rebuilding indexes
    using CONCURRENTLY operations to avoid blocking writes.

    Example:
        >>> builder = OnlineIndexBuilder(conn)
        >>> index_name = builder.create_index_concurrently(
        ...     table="users",
        ...     columns=["email"],
        ...     unique=True
        ... )
    """

    def __init__(self, connection: Any):
        """Initialize index builder.

        Args:
            connection: Database connection
        """
        self.connection = connection

    def create_index_concurrently(
        self,
        table: str,
        columns: list[str],
        index_name: str | None = None,
        unique: bool = False,
        where: str | None = None,
        method: str = "btree",
        include: list[str] | None = None,
    ) -> str:
        """Create index without blocking writes.

        Note: Requires autocommit mode. This method handles that automatically.

        Args:
            table: Table name
            columns: Columns to index
            index_name: Optional index name (auto-generated if not provided)
            unique: Create unique index
            where: Partial index condition
            method: Index method (btree, hash, gin, gist, etc.)
            include: Additional columns to include (covering index)

        Returns:
            Name of created index
        """
        if index_name is None:
            col_names = "_".join(columns)
            index_name = f"idx_{table}_{col_names}"

        unique_str = "UNIQUE " if unique else ""
        columns_str = ", ".join(columns)
        where_str = f" WHERE {where}" if where else ""
        include_str = f" INCLUDE ({', '.join(include)})" if include else ""

        # Must use autocommit for CONCURRENTLY
        old_autocommit = self.connection.autocommit
        self.connection.autocommit = True

        try:
            with self.connection.cursor() as cur:
                sql = f"""
                    CREATE {unique_str}INDEX CONCURRENTLY IF NOT EXISTS
                    {index_name} ON {table} USING {method} ({columns_str})
                    {include_str}{where_str}
                """
                logger.info(f"Creating index: {index_name}")
                cur.execute(sql)
                logger.info(f"Index created: {index_name}")
        finally:
            self.connection.autocommit = old_autocommit

        return index_name

    def drop_index_concurrently(self, index_name: str) -> None:
        """Drop index without blocking writes.

        Args:
            index_name: Name of index to drop
        """
        old_autocommit = self.connection.autocommit
        self.connection.autocommit = True

        try:
            with self.connection.cursor() as cur:
                logger.info(f"Dropping index: {index_name}")
                cur.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
                logger.info(f"Index dropped: {index_name}")
        finally:
            self.connection.autocommit = old_autocommit

    def reindex_concurrently(self, index_name: str) -> None:
        """Rebuild index without blocking writes (PG 12+).

        Args:
            index_name: Name of index to rebuild
        """
        old_autocommit = self.connection.autocommit
        self.connection.autocommit = True

        try:
            with self.connection.cursor() as cur:
                logger.info(f"Reindexing: {index_name}")
                cur.execute(f"REINDEX INDEX CONCURRENTLY {index_name}")
                logger.info(f"Reindex complete: {index_name}")
        finally:
            self.connection.autocommit = old_autocommit

    def check_index_validity(self, index_name: str) -> bool:
        """Check if index is valid (not corrupted/invalid from failed creation).

        Args:
            index_name: Name of index to check

        Returns:
            True if index is valid
        """
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT indisvalid
                FROM pg_index
                JOIN pg_class ON pg_index.indexrelid = pg_class.oid
                WHERE pg_class.relname = %s
            """,
                (index_name,),
            )
            result = cur.fetchone()
            if result is None:
                return False
            return result[0]

    def get_index_size(self, index_name: str) -> int:
        """Get index size in bytes.

        Args:
            index_name: Name of index

        Returns:
            Size in bytes
        """
        with self.connection.cursor() as cur:
            cur.execute(
                "SELECT pg_relation_size(%s)",
                (index_name,),
            )
            result = cur.fetchone()
            return result[0] if result else 0


class TableSizeEstimator:
    """Estimate table sizes for migration planning.

    Helps decide whether to use batched operations based on
    table size.
    """

    # Threshold in rows for using batched operations
    LARGE_TABLE_THRESHOLD = 100_000

    def __init__(self, connection: Any):
        """Initialize estimator.

        Args:
            connection: Database connection
        """
        self.connection = connection

    def get_row_count_estimate(self, table: str) -> int:
        """Get estimated row count (fast but approximate).

        Uses pg_class statistics rather than COUNT(*).

        Args:
            table: Table name

        Returns:
            Estimated row count
        """
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT reltuples::bigint
                FROM pg_class
                WHERE relname = %s
            """,
                (table,),
            )
            result = cur.fetchone()
            return max(0, result[0]) if result else 0

    def get_exact_row_count(self, table: str, where_clause: str = "TRUE") -> int:
        """Get exact row count (slow but accurate).

        Args:
            table: Table name
            where_clause: Optional filter

        Returns:
            Exact row count
        """
        with self.connection.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_clause}")
            return cur.fetchone()[0]

    def get_table_size(self, table: str) -> dict[str, int]:
        """Get table size information.

        Args:
            table: Table name

        Returns:
            Dictionary with size information
        """
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pg_table_size(%s) as table_size,
                    pg_indexes_size(%s) as index_size,
                    pg_total_relation_size(%s) as total_size
            """,
                (table, table, table),
            )
            row = cur.fetchone()
            return {
                "table_size_bytes": row[0],
                "index_size_bytes": row[1],
                "total_size_bytes": row[2],
            }

    def should_use_batched_operation(self, table: str) -> bool:
        """Determine if batched operations should be used.

        Args:
            table: Table name

        Returns:
            True if table is large enough to warrant batching
        """
        estimate = self.get_row_count_estimate(table)
        return estimate >= self.LARGE_TABLE_THRESHOLD

    def estimate_operation_time(
        self,
        table: str,
        rows_per_second: float = 10000.0,
    ) -> float:
        """Estimate time for a full-table operation.

        Args:
            table: Table name
            rows_per_second: Expected processing rate

        Returns:
            Estimated seconds
        """
        estimate = self.get_row_count_estimate(table)
        if rows_per_second <= 0:
            return 0.0
        return estimate / rows_per_second
