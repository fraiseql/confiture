"""Production data synchronization.

This module provides functionality to sync data from production databases to
local/staging environments with PII anonymization support.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql as pgsql
from psycopg.pq import TransactionStatus
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from confiture.config.environment import DatabaseConfig, Environment
from confiture.core import live_catalog
from confiture.core.anonymization.pseudonymizer import Pseudonymizer
from confiture.core.connection import create_connection
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.exceptions import ConfigurationError


@dataclass
class TableSelection:
    """Configuration for selecting which tables to sync."""

    include: list[str] | None = None  # Explicit table list or patterns
    exclude: list[str] | None = None  # Tables/patterns to exclude


# Strategies whose output is a pseudonym derived from the value; these need the
# per-deployment secret. `redact` (and any unknown strategy) does not.
KEYED_STRATEGIES = frozenset({"email", "phone", "name", "hash"})

#: Every strategy this sync path accepts: the keyed ones, which pseudonymise a
#: value into something of the same shape, plus ``redact``, which replaces it
#: with a constant. This is the *sync* file format's set and has nothing to say
#: about :class:`~confiture.core.anonymization.profile.AnonymizationProfile`,
#: whose ``StrategyType`` names a different and larger vocabulary.
SYNC_STRATEGIES = KEYED_STRATEGIES | frozenset({"redact"})


@dataclass
class AnonymizationRule:
    """Rule for anonymizing a specific column.

    The strategy name is checked here, not where a YAML file is read, because
    the file is not the only way to build one: a library caller passing
    ``SyncConfig(anonymization=…)`` deserves the same answer (#285).
    """

    column: str
    strategy: str  # one of SYNC_STRATEGIES
    seed: int | None = None  # Domain separator: different seeds, unrelated pseudonyms

    def __post_init__(self) -> None:
        """Refuse a strategy name nothing dispatches on.

        ``_anonymize_value`` falls through to ``[REDACTED]`` for any name it
        does not know, which is right for ``redact`` and wrong for ``emial``:
        one transposition from ``email``, and the column becomes a constant that
        no longer parses as an address, is no longer unique across rows and
        cannot be joined on — while the sync reports success (#285). By the time
        that dispatch runs, an intention and a mistake are indistinguishable, so
        the name is checked where the rule is built.

        Raises:
            ConfigurationError: ``CONFIG_002``, the code the CLI already uses for
                a configuration file it cannot accept.
        """
        if self.strategy in SYNC_STRATEGIES:
            return
        allowed = ", ".join(sorted(SYNC_STRATEGIES))
        near = get_close_matches(self.strategy, sorted(SYNC_STRATEGIES), n=1, cutoff=0.6)
        hint = f"Did you mean {near[0]!r}?" if near else f"Use one of: {allowed}"
        raise ConfigurationError(
            f"Unknown anonymization strategy {self.strategy!r} for column "
            f"{self.column!r}. Allowed strategies: {allowed}",
            error_code="CONFIG_002",
            resolution_hint=hint,
        )


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

        # Built on first keyed use; reading the secret is a configuration
        # error that must surface before any row is fetched, so
        # `_sync_with_anonymization` forces it up front when a keyed rule exists.
        self._pseudonymizer_cache: Pseudonymizer | None = None

    def __enter__(self) -> "ProductionSyncer":
        """Context manager entry."""
        self._source_conn = create_connection(self.source_config)
        try:
            self._target_conn = create_connection(self.target_config)
        # Reason: resource guard: the source connection must not leak on any exit, KeyboardInterrupt included
        except BaseException:
            self._source_conn.close()
            self._source_conn = None
            raise
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

        return sorted(
            name for _schema, name in live_catalog.relations(self._source_conn, [DEFAULT_SCHEMA])
        )

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

    def _pseudonymizer(self) -> Pseudonymizer:
        """The keyed pseudonym source, reading ``ANONYMIZATION_SECRET`` once.

        Raises:
            ConfigurationError: ``CONFIG_009`` when the secret is unset.
        """
        if self._pseudonymizer_cache is None:
            self._pseudonymizer_cache = Pseudonymizer()
        return self._pseudonymizer_cache

    def _anonymize_value(self, value: Any, strategy: str, seed: int | None = None) -> Any:
        """Anonymize a single value based on strategy.

        Every pseudonym is an HMAC under the deployment secret: stable within a
        deployment, so relationships survive; unrelated across deployments, so
        the anonymised copy cannot be matched back by hashing candidates.

        Args:
            value: Original value to anonymize
            strategy: Anonymization strategy ('email', 'phone', 'name', 'redact', 'hash')
            seed: Optional domain separator; different seeds give unrelated pseudonyms

        Returns:
            Anonymized value

        Raises:
            ConfigurationError: A keyed strategy was asked for and
                ``ANONYMIZATION_SECRET`` is not set.
        """
        if value is None:
            return None

        if strategy not in KEYED_STRATEGIES:
            # `redact`. `AnonymizationRule` refuses any other name (#285), so
            # this is not a catch-all that a typo can reach — it covers a
            # strategy that got past a validated boundary, which is the case a
            # defensive default is for.
            return "[REDACTED]"

        keyed = self._pseudonymizer()

        if strategy == "email":
            return f"user_{keyed.hex(value, seed=seed, length=8)}@example.com"

        if strategy == "phone":
            return f"+1-555-{1000 + keyed.integer(value, 9000, seed=seed)}"

        if strategy == "name":
            return f"User {keyed.hex(value, seed=seed, length=4).upper()}"

        # "hash": one-way, uniqueness-preserving
        return keyed.hex(value, seed=seed, length=16)

    def sync_table(
        self,
        table_name: str,
        anonymization_rules: list[AnonymizationRule] | None = None,
        batch_size: int = 5000,  # Optimized based on benchmarks
        progress_task: Any = None,
        progress: Progress | None = None,
        truncate: bool = True,
    ) -> int:
        """Sync a single table from source to target.

        Args:
            table_name: Name of table to sync
            anonymization_rules: Optional anonymization rules for PII
            batch_size: Number of rows per batch (default 5000, optimized via benchmarks)
            progress_task: Rich progress task ID for updating progress
            progress: Progress instance
            truncate: Empty the target table first. :meth:`sync` passes ``False``
                because it has already truncated every selected table in one
                statement; see :meth:`_truncate_targets` for why that matters.

        Returns:
            Number of rows synced
        """
        if not self._source_conn or not self._target_conn:
            raise RuntimeError("Not connected. Use context manager.")

        start_time = time.time()

        with self._source_conn.cursor() as src_cursor, self._target_conn.cursor() as dst_cursor:
            table_ident = pgsql.Identifier(table_name)

            # Truncate target table first (unless the caller already has —
            # CASCADE here would empty any table already copied that references
            # this one).
            if truncate:
                dst_cursor.execute(pgsql.SQL("TRUNCATE TABLE {} CASCADE").format(table_ident))

            # Get row count for verification
            src_cursor.execute(pgsql.SQL("SELECT COUNT(*) FROM {}").format(table_ident))
            expected_row = src_cursor.fetchone()
            expected_count: int = expected_row[0] if expected_row else 0

            # Update progress with total
            if progress and progress_task is not None:
                progress.update(progress_task, total=expected_count)

            # Temporarily disable triggers to allow FK constraint violations
            dst_cursor.execute(pgsql.SQL("ALTER TABLE {} DISABLE TRIGGER ALL").format(table_ident))

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
                # Re-enable triggers — unless the target transaction is already
                # aborted: another statement would only mask the real error, and
                # the rollback undoes the DISABLE anyway.
                if self._target_conn.info.transaction_status != TransactionStatus.INERROR:
                    dst_cursor.execute(
                        pgsql.SQL("ALTER TABLE {} ENABLE TRIGGER ALL").format(table_ident)
                    )

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
        table_ident = pgsql.Identifier(table_name)
        with (
            src_cursor.copy(pgsql.SQL("COPY {} TO STDOUT").format(table_ident)) as copy_out,
            dst_cursor.copy(pgsql.SQL("COPY {} FROM STDIN").format(table_ident)) as copy_in,
        ):
            for data in copy_out:
                copy_in.write(data)
                if progress and progress_task is not None:
                    progress.update(progress_task, advance=1)

        # Get final count
        dst_cursor.execute(pgsql.SQL("SELECT COUNT(*) FROM {}").format(table_ident))
        result = dst_cursor.fetchone()
        return int(result[0]) if result else 0

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
        table_ident = pgsql.Identifier(table_name)

        # Get column names
        src_cursor.execute(pgsql.SQL("SELECT * FROM {} LIMIT 0").format(table_ident))
        column_names = [desc[0] for desc in src_cursor.description]

        # Read the secret before the first row, not on it: an unset secret is a
        # configuration error to report, not a mid-copy crash.
        if any(rule.strategy in KEYED_STRATEGIES for rule in anonymization_rules):
            self._pseudonymizer()

        # Build column index map for anonymization
        anonymize_map: dict[int, AnonymizationRule] = {}
        for rule in anonymization_rules:
            if rule.column in column_names:
                col_idx = column_names.index(rule.column)
                anonymize_map[col_idx] = rule

        # Fetch all rows
        src_cursor.execute(pgsql.SQL("SELECT * FROM {}").format(table_ident))

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

        columns_sql = pgsql.SQL(", ").join(pgsql.Identifier(c) for c in column_names)
        placeholders_sql = pgsql.SQL(", ").join([pgsql.Placeholder()] * len(column_names))
        query = pgsql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            pgsql.Identifier(table_name), columns_sql, placeholders_sql
        )

        cursor.executemany(query, rows)

    def _truncate_targets(self, tables: list[str]) -> None:
        """Empty every target table in *tables* in one statement.

        Truncating each table immediately before copying it looks equivalent and
        is not. ``TRUNCATE ... CASCADE`` empties every table that references the
        one named, so with tables copied in alphabetical order a parent copied
        late would silently empty children copied earlier — ``users`` wiping
        ``orders``, and through it ``order_items`` and ``payments``. The sync
        would report every table at its full row count, because that count is
        what it inserts rather than what the target ends up holding.

        One ``TRUNCATE a, b, c CASCADE`` has no such ordering: all the named
        tables are emptied together, before anything is copied. CASCADE is still
        needed for tables that reference these but are not themselves being
        synced — truncating a parent without it would simply fail.
        """
        if not tables or not self._target_conn:
            return
        with self._target_conn.cursor() as cur:
            cur.execute(
                pgsql.SQL("TRUNCATE TABLE {} CASCADE").format(
                    pgsql.SQL(", ").join(pgsql.Identifier(name) for name in tables)
                )
            )
        self._target_conn.commit()

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

        # Empty every target table before copying any of them; see
        # _truncate_targets. On a resumed run the already-completed tables are
        # not in this list and keep the rows the interrupted run gave them.
        self._truncate_targets(tables)

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
                        truncate=False,
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
                    truncate=False,
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
        with Path(checkpoint_file).open("w") as f:
            json.dump(checkpoint_data, f, indent=2)

    def load_checkpoint(self, checkpoint_file: Path) -> None:
        """Load sync checkpoint from file.

        Args:
            checkpoint_file: Path to checkpoint file
        """
        with Path(checkpoint_file).open() as f:
            self._checkpoint_data = json.load(f)

        # Restore completed tables
        if "completed_tables" in self._checkpoint_data:
            self._completed_tables = set(self._checkpoint_data["completed_tables"].keys())
