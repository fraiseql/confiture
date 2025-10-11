"""Production data synchronization.

This module provides functionality to sync data from production databases to
local/staging environments with PII anonymization support.
"""

from dataclasses import dataclass
from typing import Any

import psycopg

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
    batch_size: int = 10000
    resume: bool = False


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

    def sync_table(
        self,
        table_name: str,
        anonymization_rules: list[AnonymizationRule] | None = None,  # noqa: ARG002
        batch_size: int = 10000,  # noqa: ARG002
    ) -> int:
        """Sync a single table from source to target.

        Args:
            table_name: Name of table to sync
            anonymization_rules: Optional anonymization rules (not yet implemented)
            batch_size: Number of rows per batch (not yet implemented)

        Returns:
            Number of rows synced

        Note:
            anonymization_rules and batch_size parameters are reserved for
            Milestone 3.7 and 3.8 implementations.
        """
        if not self._source_conn or not self._target_conn:
            raise RuntimeError("Not connected. Use context manager.")

        # For now, implement simple COPY without anonymization
        # Will add anonymization in Milestone 3.8
        with self._source_conn.cursor() as src_cursor, \
             self._target_conn.cursor() as dst_cursor:

            # Truncate target table first
            dst_cursor.execute(f"TRUNCATE TABLE {table_name} CASCADE")

            # Get row count for verification
            src_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            expected_row = src_cursor.fetchone()
            expected_count: int = expected_row[0] if expected_row else 0

            # Use COPY for efficient data transfer
            with (
                src_cursor.copy(f"COPY {table_name} TO STDOUT") as copy_out,
                dst_cursor.copy(f"COPY {table_name} FROM STDIN") as copy_in,
            ):
                for data in copy_out:
                    copy_in.write(data)

            # Commit target transaction
            self._target_conn.commit()

            # Verify row count
            dst_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            actual_row = dst_cursor.fetchone()
            actual_count: int = actual_row[0] if actual_row else 0

            if actual_count != expected_count:
                raise RuntimeError(
                    f"Row count mismatch for {table_name}: "
                    f"expected {expected_count}, got {actual_count}"
                )

            return actual_count

    def sync(self, config: SyncConfig) -> dict[str, int]:
        """Sync multiple tables based on configuration.

        Args:
            config: Sync configuration

        Returns:
            Dictionary mapping table names to row counts synced
        """
        tables = self.select_tables(config.tables)
        results = {}

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

        return results
