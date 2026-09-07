"""Large table migration patterns.

Provides utilities for migrating large tables (>1M rows) without
blocking production traffic. Includes batched operations, progress
reporting, and resumable patterns.
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg import sql as pgsql

from confiture.core.ledger import split_qualified_table

logger = logging.getLogger(__name__)


_SIMPLE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _relation(name: str) -> pgsql.Identifier:
    """A table or index name, optionally ``schema.``-qualified, as an identifier."""
    schema, bare = split_qualified_table(name)
    return pgsql.Identifier(schema, bare) if schema else pgsql.Identifier(bare)


def _column_or_expression(text: str) -> pgsql.Composable:
    """A bare column name is quoted; anything else (``lower(email)``) is an expression."""
    return pgsql.Identifier(text) if _SIMPLE_IDENT.match(text) else pgsql.SQL(text)


def _columns(names: list[str]) -> pgsql.Composed:
    return pgsql.SQL(", ").join(_column_or_expression(n) for n in names)


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
    block_callback: Callable[[int], None] | None = None  # the next ctid block, after each commit


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
            rel, col = _relation(table), pgsql.Identifier(column)
            cur.execute(
                pgsql.SQL("ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {c} {type}").format(
                    t=rel, c=col, type=pgsql.SQL(column_type)
                )
            )
            self.connection.commit()

            # Get total rows needing update
            cur.execute(
                pgsql.SQL("SELECT COUNT(*) FROM {t} WHERE {c} IS NULL").format(t=rel, c=col)
            )
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
                            pgsql.SQL(
                                "UPDATE {t} SET {c} = {d} WHERE ctid IN ("
                                "SELECT ctid FROM {t} WHERE {c} IS NULL LIMIT {n})"
                            ).format(
                                t=rel,
                                c=col,
                                d=pgsql.SQL(default),
                                n=pgsql.Literal(self.config.batch_size),
                            )
                        )
                        rows_affected = cur.rowcount
                        self.connection.commit()
                        break
                    except psycopg.Error as e:
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
                pgsql.SQL("ALTER TABLE {t} ALTER COLUMN {c} SET DEFAULT {d}").format(
                    t=rel, c=col, d=pgsql.SQL(default)
                )
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
        start_block: int | None = None,
    ) -> BatchProgress:
        """Backfill a column in batches, committing after each.

        Termination contract: the table's block range is measured once, up
        front (``pg_relation_size`` / block size), and each batch updates one
        slice of ``ctid`` block ranges, ``WHERE ctid >= '(b,0)' AND ctid <
        '(b+n,0)' AND (where_clause)``. The loop ends when the last block has
        been visited — it never depends on *where_clause* becoming false, so
        the default ``"TRUE"`` terminates. Blocks per batch is sized so a batch
        holds about ``batch_size`` rows.

        Each row is updated once: a rewritten row's new tuple version may land
        in a block not yet visited, so every batch also excludes tuples created
        after the backfill began (``xmin`` newer than the starting transaction).
        Rows inserted concurrently, after the start, are therefore not visited.

        ``expression`` and ``where_clause`` are SQL fragments supplied by the
        migration author and are interpolated raw by documented contract.

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
            rel = _relation(table)
            cur.execute(
                pgsql.SQL("SELECT COUNT(*) FROM {t} WHERE {w}").format(
                    t=rel, w=pgsql.SQL(where_clause)
                )
            )
            total_rows = cur.fetchone()[0]

            if total_rows == 0:
                return BatchProgress(total_rows=0)

            cur.execute(
                "SELECT pg_relation_size(%s::regclass) / current_setting('block_size')::int",
                (rel.as_string(),),
            )
            blocks = max(1, int(cur.fetchone()[0]))
            # Tuples this backfill writes carry a newer xmin than this
            # transaction's id; excluding them keeps a rewritten row from being
            # updated again when its new version lands in a later block.
            cur.execute("SELECT txid_current() % 4294967296")
            start_xid = int(cur.fetchone()[0])
            rows_per_block = max(1, -(-total_rows // blocks))
            blocks_per_batch = max(1, self.config.batch_size // rows_per_block)
            total_batches = -(-blocks // blocks_per_batch)
            # ``start_block`` is the resumable cursor (``block_callback`` reports it);
            # ``start_from`` maps rows to a block through today's matching count.
            first_block = (
                min(blocks, start_block)
                if start_block is not None
                else min(blocks, start_from // rows_per_block)
            )

            processed = start_from
            progress = BatchProgress(
                total_rows=total_rows,
                processed_rows=processed,
                total_batches=total_batches,
            )
            batch_num = first_block // blocks_per_batch

            for block in range(first_block, blocks, blocks_per_batch):
                batch_num += 1
                cur.execute(
                    pgsql.SQL(
                        "UPDATE {table} SET {column} = {expression} "
                        "WHERE ctid >= {lower}::tid AND ctid < {upper}::tid "
                        "AND xmin::text::bigint < {start_xid} AND ({where})"
                    ).format(
                        table=rel,
                        column=pgsql.Identifier(column),
                        expression=pgsql.SQL(expression),
                        lower=pgsql.Literal(f"({block},0)"),
                        upper=pgsql.Literal(f"({block + blocks_per_batch},0)"),
                        start_xid=pgsql.Literal(start_xid),
                        where=pgsql.SQL(where_clause),
                    )
                )
                rows_affected = cur.rowcount
                self.connection.commit()

                processed += rows_affected
                progress.processed_rows = processed
                progress.current_batch = batch_num
                progress.elapsed_seconds = time.perf_counter() - start_time

                if self.config.progress_callback:
                    self.config.progress_callback(processed, total_rows)

                if self.config.checkpoint_callback:
                    self.config.checkpoint_callback(processed)
                if self.config.block_callback:
                    self.config.block_callback(block + blocks_per_batch)

                logger.info(
                    f"Backfill batch {batch_num}/{total_batches}: "
                    f"{progress.percent_complete:.1f}% complete"
                )

                if self.config.sleep_between_batches > 0 and block + blocks_per_batch < blocks:
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
            rel = _relation(table)
            cur.execute(
                pgsql.SQL("SELECT COUNT(*) FROM {t} WHERE {w}").format(
                    t=rel, w=pgsql.SQL(where_clause)
                )
            )
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
                    pgsql.SQL(
                        "DELETE FROM {t} WHERE ctid IN (SELECT ctid FROM {t} WHERE {w} LIMIT {n})"
                    ).format(
                        t=rel, w=pgsql.SQL(where_clause), n=pgsql.Literal(self.config.batch_size)
                    )
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

                logger.info(f"Delete batch {batch_num}: {progress.percent_complete:.1f}% complete")

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
            src, tgt = _relation(source_table), _relation(target_table)
            where = pgsql.SQL(where_clause)
            cur.execute(pgsql.SQL("SELECT COUNT(*) FROM {t} WHERE {w}").format(t=src, w=where))
            total_rows = cur.fetchone()[0]

            if total_rows == 0:
                return BatchProgress(total_rows=0)

            # Get columns if not specified
            if columns is None:
                schema, bare = split_qualified_table(source_table)
                cur.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = %s AND table_schema = %s
                    ORDER BY ordinal_position
                """,
                    (bare, schema or "public"),
                )
                columns = [row[0] for row in cur.fetchall()]

            # Build select expressions
            transform = transform or {}
            select_list = pgsql.SQL(", ").join(
                pgsql.SQL(transform[col]) if col in transform else pgsql.Identifier(col)
                for col in columns
            )
            column_list = pgsql.SQL(", ").join(pgsql.Identifier(col) for col in columns)

            # Track last ID for pagination
            cur.execute(pgsql.SQL("SELECT MIN(ctid) FROM {t} WHERE {w}").format(t=src, w=where))
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
                pgsql.SQL(
                    "CREATE TEMP TABLE _batch_tracker AS "
                    "SELECT ctid AS row_ctid, ROW_NUMBER() OVER () AS rn FROM {t} WHERE {w}"
                ).format(t=src, w=where)
            )
            self.connection.commit()

            try:
                while processed < total_rows:
                    batch_num += 1
                    offset = processed

                    cur.execute(
                        pgsql.SQL(
                            "INSERT INTO {tgt} ({cols}) SELECT {exprs} FROM {src} s "
                            "WHERE s.ctid IN (SELECT row_ctid FROM _batch_tracker "
                            "WHERE rn > {lo} AND rn <= {hi})"
                        ).format(
                            tgt=tgt,
                            cols=column_list,
                            exprs=select_list,
                            src=src,
                            lo=pgsql.Literal(offset),
                            hi=pgsql.Literal(offset + self.config.batch_size),
                        )
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
            index_name = f"idx_{split_qualified_table(table)[1]}_{col_names}"

        # Must use autocommit for CONCURRENTLY
        old_autocommit = self.connection.autocommit
        self.connection.autocommit = True

        try:
            with self.connection.cursor() as cur:
                statement = pgsql.SQL(
                    "CREATE {unique}INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} "
                    "USING {method} ({columns}){include}{where}"
                ).format(
                    unique=pgsql.SQL("UNIQUE " if unique else ""),
                    name=pgsql.Identifier(index_name),
                    table=_relation(table),
                    method=pgsql.Identifier(method),
                    columns=_columns(columns),
                    include=(
                        pgsql.SQL(" INCLUDE (") + _columns(include) + pgsql.SQL(")")
                        if include
                        else pgsql.SQL("")
                    ),
                    where=pgsql.SQL(" WHERE " + where) if where else pgsql.SQL(""),
                )
                logger.info(f"Creating index: {index_name}")
                cur.execute(statement)
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
                cur.execute(
                    pgsql.SQL("DROP INDEX CONCURRENTLY IF EXISTS {}").format(_relation(index_name))
                )
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
                cur.execute(
                    pgsql.SQL("REINDEX INDEX CONCURRENTLY {}").format(_relation(index_name))
                )
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

    def all_tables(self, schema: str = "public") -> list[str]:
        """List the base tables in *schema*, ordered by name.

        Centralizes the ``pg_tables`` enumeration the ``migrate estimate``
        command needs when no explicit tables are passed, keeping raw catalog
        SQL out of the CLI layer (ARCH-L2).

        Args:
            schema: Schema to enumerate (default ``public``).

        Returns:
            Sorted list of table names in *schema*.
        """
        with self.connection.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY tablename",
                (schema,),
            )
            return [row[0] for row in cur.fetchall()]

    def get_exact_row_count(self, table: str, where_clause: str = "TRUE") -> int:
        """Get exact row count (slow but accurate).

        Args:
            table: Table name
            where_clause: Optional filter

        Returns:
            Exact row count
        """
        with self.connection.cursor() as cur:
            cur.execute(
                pgsql.SQL("SELECT COUNT(*) FROM {t} WHERE {w}").format(
                    t=_relation(table), w=pgsql.SQL(where_clause)
                )
            )
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
