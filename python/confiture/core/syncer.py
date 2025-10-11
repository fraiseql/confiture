"""Production data synchronization.

This module provides functionality to sync data from production databases to
local/staging environments with PII anonymization support.
"""

import hashlib
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from confiture.config.environment import DatabaseConfig
from confiture.core.connection import create_connection


@dataclass
class TableSelection:
    """Configuration for selecting which tables to sync."""

    include: list[str] | None = None  # Explicit table list or patterns
    exclude: list[str] | None = None  # Tables/patterns to exclude


@dataclass
class AnonymizationRule:
    """Rule for anonymizing a specific column."""

    column: str
    strategy: str  # 'email', 'phone', 'name', 'redact', 'hash'
    seed: int | None = None  # For reproducible anonymization


@dataclass
class SyncConfig:
    """Configuration for data sync operation."""

    tables: TableSelection
    anonymization: dict[str, list[AnonymizationRule]] | None = None  # table -> rules
    batch_size: int = 5000  # Optimized based on benchmarks
    resume: bool = False
    show_progress: bool = False
    checkpoint_file: Path | None = None


@dataclass
class TableMetrics:
    """Performance metrics for a single table sync."""

    rows_synced: int
    elapsed_seconds: float
    rows_per_second: float
    synced_at: str


class ProductionSyncer:
    """Synchronize data from production to target database.

    Features:
    - Table selection with include/exclude patterns
    - Schema-aware data copying
    - PII anonymization
    - Progress reporting
    - Resume support for interrupted syncs
    """

    def __init__(
        self,
        source: DatabaseConfig | str,
        target: DatabaseConfig | str,
    ):
        """Initialize syncer with source and target databases.

        Args:
            source: Source database config or environment name
            target: Target database config or environment name
        """
        from confiture.config.environment import Environment

        # Load configs if strings provided
        if isinstance(source, str):
            source = Environment.load(source).database

        if isinstance(target, str):
            target = Environment.load(target).database

        self.source_config = source
        self.target_config = target

        self._source_conn: psycopg.Connection[Any] | None = None
        self._target_conn: psycopg.Connection[Any] | None = None

        # Progress tracking and metrics
        self._metrics: dict[str, TableMetrics] = {}
        self._completed_tables: set[str] = set()
        self._checkpoint_data: dict[str, Any] = {}

    def __enter__(self) -> "ProductionSyncer":
        """Context manager entry."""
        self._source_conn = create_connection(self.source_config)
        self._target_conn = create_connection(self.target_config)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        if self._source_conn:
            self._source_conn.close()
        if self._target_conn:
            self._target_conn.close()

    def get_all_tables(self) -> list[str]:
        """Get list of all user tables in source database.

        Returns:
            List of table names in public schema
        """
        if not self._source_conn:
            raise RuntimeError("Not connected. Use context manager.")

        with self._source_conn.cursor() as cursor:
            cursor.execute("""
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
            """)
            return [row[0] for row in cursor.fetchall()]

    def select_tables(self, selection: TableSelection) -> list[str]:
        """Select tables based on include/exclude patterns.

        Args:
            selection: Table selection configuration

        Returns:
            List of table names to sync
        """
        all_tables = self.get_all_tables()

        # If explicit include list, start with those
        if selection.include:
            tables = [t for t in all_tables if t in selection.include]
        else:
            tables = all_tables

        # Apply exclusions
        if selection.exclude:
            tables = [t for t in tables if t not in selection.exclude]

        return tables

    def _anonymize_value(
        self, value: Any, strategy: str, seed: int | None = None
    ) -> Any:
        """Anonymize a single value based on strategy.

        Args:
            value: Original value to anonymize
            strategy: Anonymization strategy ('email', 'phone', 'name', 'redact', 'hash')
            seed: Optional seed for deterministic anonymization

        Returns:
            Anonymized value
        """
        if value is None:
            return None

        # Set random seed for deterministic anonymization
        if seed is not None:
            random.seed(f"{seed}:{value}")

        if strategy == "email":
            # Generate deterministic fake email
            hash_value = hashlib.sha256(str(value).encode()).hexdigest()[:8]
            return f"user_{hash_value}@example.com"

        elif strategy == "phone":
            # Generate fake phone number
            if seed is not None:
                # Deterministic based on seed
                hash_int = int(hashlib.sha256(str(value).encode()).hexdigest()[:8], 16)
                number = (hash_int % 10000)
            else:
                number = random.randint(1000, 9999)
            return f"+1-555-{number}"

        elif strategy == "name":
            # Generate fake name
            hash_str = hashlib.sha256(str(value).encode()).hexdigest()[:8]
            return f"User {hash_str[:4].upper()}"

        elif strategy == "redact":
            # Simply redact the value
            return "[REDACTED]"

        elif strategy == "hash":
            # One-way hash (preserves uniqueness)
            return hashlib.sha256(str(value).encode()).hexdigest()[:16]

        else:
            # Unknown strategy, redact by default
            return "[REDACTED]"

    def sync_table(
        self,
        table_name: str,
        anonymization_rules: list[AnonymizationRule] | None = None,
        batch_size: int = 5000,  # Optimized based on benchmarks
        progress_task: Any = None,
        progress: Progress | None = None,
    ) -> int:
        """Sync a single table from source to target.

        Args:
            table_name: Name of table to sync
            anonymization_rules: Optional anonymization rules for PII
            batch_size: Number of rows per batch (default 5000, optimized via benchmarks)
            progress_task: Rich progress task ID for updating progress
            progress: Progress instance

        Returns:
            Number of rows synced
        """
        if not self._source_conn or not self._target_conn:
            raise RuntimeError("Not connected. Use context manager.")

        start_time = time.time()

        with self._source_conn.cursor() as src_cursor, \
             self._target_conn.cursor() as dst_cursor:

            # Truncate target table first
            dst_cursor.execute(f"TRUNCATE TABLE {table_name} CASCADE")

            # Get row count for verification
            src_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            expected_row = src_cursor.fetchone()
            expected_count: int = expected_row[0] if expected_row else 0

            # Update progress with total
            if progress and progress_task is not None:
                progress.update(progress_task, total=expected_count)

            # Temporarily disable triggers to allow FK constraint violations
            dst_cursor.execute(f"ALTER TABLE {table_name} DISABLE TRIGGER ALL")

            try:
                if anonymization_rules:
                    # Anonymization path: fetch, anonymize, insert
                    actual_count = self._sync_with_anonymization(
                        src_cursor,
                        dst_cursor,
                        table_name,
                        anonymization_rules,
                        batch_size,
                        progress_task,
                        progress,
                    )
                else:
                    # Fast path: direct COPY
                    actual_count = self._sync_with_copy(
                        src_cursor,
                        dst_cursor,
                        table_name,
                        progress_task,
                        progress,
                    )
            finally:
                # Re-enable triggers
                dst_cursor.execute(f"ALTER TABLE {table_name} ENABLE TRIGGER ALL")

            # Commit target transaction
            self._target_conn.commit()

            # Verify row count
            if actual_count != expected_count:
                raise RuntimeError(
                    f"Row count mismatch for {table_name}: "
                    f"expected {expected_count}, got {actual_count}"
                )

            # Track metrics
            elapsed = time.time() - start_time
            rows_per_second = actual_count / elapsed if elapsed > 0 else 0
            self._metrics[table_name] = TableMetrics(
                rows_synced=actual_count,
                elapsed_seconds=elapsed,
                rows_per_second=rows_per_second,
                synced_at=datetime.now().isoformat(),
            )
            self._completed_tables.add(table_name)

            return actual_count

    def _sync_with_copy(
        self,
        src_cursor: Any,
        dst_cursor: Any,
        table_name: str,
        progress_task: Any = None,
        progress: Progress | None = None,
    ) -> int:
        """Fast sync using COPY (no anonymization).

        Args:
            src_cursor: Source database cursor
            dst_cursor: Target database cursor
            table_name: Name of table to sync
            progress_task: Progress task ID
            progress: Progress instance

        Returns:
            Number of rows synced
        """
        with (
            src_cursor.copy(f"COPY {table_name} TO STDOUT") as copy_out,
            dst_cursor.copy(f"COPY {table_name} FROM STDIN") as copy_in,
        ):
            for data in copy_out:
                copy_in.write(data)
                if progress and progress_task is not None:
                    progress.update(progress_task, advance=1)

        # Get final count
        dst_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        result = dst_cursor.fetchone()
        return result[0] if result else 0

    def _sync_with_anonymization(
        self,
        src_cursor: Any,
        dst_cursor: Any,
        table_name: str,
        anonymization_rules: list[AnonymizationRule],
        batch_size: int,
        progress_task: Any = None,
        progress: Progress | None = None,
    ) -> int:
        """Sync with anonymization (slower, row-by-row).

        Args:
            src_cursor: Source database cursor
            dst_cursor: Target database cursor
            table_name: Name of table to sync
            anonymization_rules: List of anonymization rules
            batch_size: Batch size for inserts
            progress_task: Progress task ID
            progress: Progress instance

        Returns:
            Number of rows synced
        """
        # Get column names
        src_cursor.execute(f"SELECT * FROM {table_name} LIMIT 0")
        column_names = [desc[0] for desc in src_cursor.description]

        # Build column index map for anonymization
        anonymize_map: dict[int, AnonymizationRule] = {}
        for rule in anonymization_rules:
            if rule.column in column_names:
                col_idx = column_names.index(rule.column)
                anonymize_map[col_idx] = rule

        # Fetch all rows
        src_cursor.execute(f"SELECT * FROM {table_name}")

        # Process in batches
        rows_synced = 0
        batch = []

        for row in src_cursor:
            # Anonymize specified columns
            anonymized_row = list(row)
            for col_idx, rule in anonymize_map.items():
                anonymized_row[col_idx] = self._anonymize_value(
                    row[col_idx], rule.strategy, rule.seed
                )

            batch.append(tuple(anonymized_row))

            # Insert batch when full
            if len(batch) >= batch_size:
                self._insert_batch(dst_cursor, table_name, column_names, batch)
                rows_synced += len(batch)
                if progress and progress_task is not None:
                    progress.update(progress_task, advance=len(batch))
                batch = []

        # Insert remaining rows
        if batch:
            self._insert_batch(dst_cursor, table_name, column_names, batch)
            rows_synced += len(batch)
            if progress and progress_task is not None:
                progress.update(progress_task, advance=len(batch))

        return rows_synced

    def _insert_batch(
        self,
        cursor: Any,
        table_name: str,
        column_names: list[str],
        rows: list[tuple[Any, ...]],
    ) -> None:
        """Insert a batch of rows into target table.

        Args:
            cursor: Database cursor
            table_name: Name of table
            column_names: List of column names
            rows: List of row tuples to insert
        """
        if not rows:
            return

        columns_str = ", ".join(column_names)
        placeholders = ", ".join(["%s"] * len(column_names))
        query = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"

        cursor.executemany(query, rows)

    def sync(self, config: SyncConfig) -> dict[str, int]:
        """Sync multiple tables based on configuration.

        Args:
            config: Sync configuration

        Returns:
            Dictionary mapping table names to row counts synced
        """
        # Load checkpoint if requested
        if config.resume and config.checkpoint_file and config.checkpoint_file.exists():
            self.load_checkpoint(config.checkpoint_file)

        tables = self.select_tables(config.tables)
        results = {}

        # Filter out completed tables if resuming
        if config.resume:
            tables = [t for t in tables if t not in self._completed_tables]

        if config.show_progress:
            # Use rich progress bar
            with Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("•"),
                TextColumn("{task.completed}/{task.total} rows"),
                TimeRemainingColumn(),
            ) as progress:
                for table in tables:
                    task = progress.add_task(f"Syncing {table}", total=0)

                    anonymization_rules = None
                    if config.anonymization and table in config.anonymization:
                        anonymization_rules = config.anonymization[table]

                    rows_synced = self.sync_table(
                        table,
                        anonymization_rules=anonymization_rules,
                        batch_size=config.batch_size,
                        progress_task=task,
                        progress=progress,
                    )
                    results[table] = rows_synced
        else:
            # No progress bar
            for table in tables:
                anonymization_rules = None
                if config.anonymization and table in config.anonymization:
                    anonymization_rules = config.anonymization[table]

                rows_synced = self.sync_table(
                    table,
                    anonymization_rules=anonymization_rules,
                    batch_size=config.batch_size,
                )
                results[table] = rows_synced

        # Save checkpoint if requested
        if config.checkpoint_file:
            self.save_checkpoint(config.checkpoint_file)

        return results

    def get_metrics(self) -> dict[str, dict[str, Any]]:
        """Get performance metrics for all synced tables.

        Returns:
            Dictionary mapping table names to metrics
        """
        return {
            table: {
                "rows_synced": metrics.rows_synced,
                "elapsed_seconds": metrics.elapsed_seconds,
                "rows_per_second": metrics.rows_per_second,
                "synced_at": metrics.synced_at,
            }
            for table, metrics in self._metrics.items()
        }

    def save_checkpoint(self, checkpoint_file: Path) -> None:
        """Save sync checkpoint to file.

        Args:
            checkpoint_file: Path to checkpoint file
        """
        checkpoint_data = {
            "version": "1.0",
            "timestamp": datetime.now().isoformat(),
            "source_database": f"{self.source_config.host}:{self.source_config.port}/{self.source_config.database}",
            "target_database": f"{self.target_config.host}:{self.target_config.port}/{self.target_config.database}",
            "completed_tables": {
                table: {
                    "rows_synced": metrics.rows_synced,
                    "synced_at": metrics.synced_at,
                }
                for table, metrics in self._metrics.items()
            },
        }

        checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        with open(checkpoint_file, "w") as f:
            json.dump(checkpoint_data, f, indent=2)

    def load_checkpoint(self, checkpoint_file: Path) -> None:
        """Load sync checkpoint from file.

        Args:
            checkpoint_file: Path to checkpoint file
        """
        with open(checkpoint_file) as f:
            self._checkpoint_data = json.load(f)

        # Restore completed tables
        if "completed_tables" in self._checkpoint_data:
            self._completed_tables = set(self._checkpoint_data["completed_tables"].keys())
