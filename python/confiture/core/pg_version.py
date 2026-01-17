"""PostgreSQL version detection and feature flags.

Provides utilities for detecting PostgreSQL version and checking
feature availability across versions 12-17.
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PGFeature(Enum):
    """PostgreSQL features by minimum required version.

    Each feature is associated with the minimum PostgreSQL major version
    that supports it.
    """

    # PostgreSQL 12 features
    GENERATED_COLUMNS = 12
    REINDEX_CONCURRENTLY = 12
    JSON_PATH = 12
    CTE_MATERIALIZATION_HINT = 12

    # PostgreSQL 13 features
    VACUUM_PARALLEL = 13
    INCREMENTAL_SORT = 13
    TRUSTED_EXTENSIONS = 13
    HASH_AGGREGATE_MEMORY = 13

    # PostgreSQL 14 features
    MULTIRANGE_TYPES = 14
    OUT_PARAMS_IN_PROCEDURES = 14
    DETACH_PARTITION_CONCURRENTLY = 14
    COMPRESSION_LZ4 = 14

    # PostgreSQL 15 features
    LOGICAL_REPLICATION_ROW_FILTER = 15
    MERGE_STATEMENT = 15
    SECURITY_INVOKER_VIEWS = 15
    UNIQUE_NULLS_NOT_DISTINCT = 15
    JSON_LOGS = 15

    # PostgreSQL 16 features
    JSON_IS_JSON = 16
    PARALLEL_FULL_OUTER_JOIN = 16
    LOGICAL_REPLICATION_FROM_STANDBY = 16
    EXTENSION_SET_SCHEMA = 16

    # PostgreSQL 17 features (upcoming/current)
    INCREMENTAL_BACKUP = 17
    LOGICAL_REPLICATION_FAILOVER = 17


@dataclass
class PGVersionInfo:
    """PostgreSQL version information.

    Example:
        >>> info = PGVersionInfo(major=15, minor=4, full_version="PostgreSQL 15.4")
        >>> info.supports(PGFeature.MERGE_STATEMENT)
        True
        >>> info.supports(PGFeature.JSON_IS_JSON)
        False
    """

    major: int
    minor: int
    patch: int = 0
    full_version: str = ""

    def supports(self, feature: PGFeature) -> bool:
        """Check if this version supports a feature.

        Args:
            feature: Feature to check

        Returns:
            True if feature is supported
        """
        return self.major >= feature.value

    def is_at_least(self, major: int, minor: int = 0) -> bool:
        """Check if version is at least the specified version.

        Args:
            major: Minimum major version
            minor: Minimum minor version

        Returns:
            True if version meets requirement
        """
        if self.major > major:
            return True
        if self.major == major:
            return self.minor >= minor
        return False

    @property
    def version_tuple(self) -> tuple[int, int, int]:
        """Get version as tuple."""
        return (self.major, self.minor, self.patch)

    def __str__(self) -> str:
        """String representation."""
        return f"{self.major}.{self.minor}.{self.patch}"


def detect_version(connection: Any) -> PGVersionInfo:
    """Detect PostgreSQL version from connection.

    Args:
        connection: Database connection

    Returns:
        PGVersionInfo with detected version

    Example:
        >>> info = detect_version(conn)
        >>> print(f"PostgreSQL {info.major}.{info.minor}")
        PostgreSQL 15.4
    """
    with connection.cursor() as cur:
        # Get full version string
        cur.execute("SELECT version()")
        version_str = cur.fetchone()[0]

        # Get numeric version
        cur.execute("SHOW server_version_num")
        version_num = int(cur.fetchone()[0])

        # Parse version number (e.g., 150004 = 15.0.4)
        major = version_num // 10000
        minor = (version_num % 10000) // 100
        patch = version_num % 100

        return PGVersionInfo(
            major=major,
            minor=minor,
            patch=patch,
            full_version=version_str,
        )


def parse_version_string(version_str: str) -> PGVersionInfo:
    """Parse a PostgreSQL version string.

    Args:
        version_str: Version string like "PostgreSQL 15.4" or "15.4"

    Returns:
        PGVersionInfo parsed from string

    Example:
        >>> info = parse_version_string("PostgreSQL 15.4.2")
        >>> info.major
        15
    """
    # Extract version numbers
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version_str)
    if not match:
        raise ValueError(f"Could not parse version from: {version_str}")

    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3)) if match.group(3) else 0

    return PGVersionInfo(
        major=major,
        minor=minor,
        patch=patch,
        full_version=version_str,
    )


class VersionAwareSQL:
    """Generate version-specific SQL.

    Provides utilities for generating SQL that adapts to the
    PostgreSQL version.

    Example:
        >>> sql = VersionAwareSQL(version_info)
        >>> sql.create_index_concurrently("idx_users_email", "users", ["email"])
        'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_email ON users (email)'
    """

    def __init__(self, version: PGVersionInfo):
        """Initialize with version info.

        Args:
            version: PostgreSQL version information
        """
        self.version = version

    def reindex_concurrently(self, index_name: str) -> str:
        """Generate REINDEX CONCURRENTLY statement.

        Note: REINDEX CONCURRENTLY is only available in PG 12+.

        Args:
            index_name: Name of index to rebuild

        Returns:
            SQL statement
        """
        if self.version.supports(PGFeature.REINDEX_CONCURRENTLY):
            return f"REINDEX INDEX CONCURRENTLY {index_name}"
        else:
            logger.warning(
                f"REINDEX CONCURRENTLY not available in PG {self.version.major}, "
                "using regular REINDEX (will block writes)"
            )
            return f"REINDEX INDEX {index_name}"

    def vacuum_parallel(self, table: str, parallel_workers: int = 2) -> str:
        """Generate VACUUM with parallel workers.

        Note: VACUUM (PARALLEL n) is only available in PG 13+.

        Args:
            table: Table to vacuum
            parallel_workers: Number of parallel workers

        Returns:
            SQL statement
        """
        if self.version.supports(PGFeature.VACUUM_PARALLEL):
            return f"VACUUM (PARALLEL {parallel_workers}) {table}"
        else:
            logger.warning(
                f"VACUUM PARALLEL not available in PG {self.version.major}, "
                "using single-threaded VACUUM"
            )
            return f"VACUUM {table}"

    def create_index_concurrently(
        self,
        index_name: str,
        table: str,
        columns: list[str],
        unique: bool = False,
        where: str | None = None,
    ) -> str:
        """Generate CREATE INDEX CONCURRENTLY statement.

        Args:
            index_name: Name for the new index
            table: Table to create index on
            columns: Columns to include in index
            unique: Whether index should be unique
            where: Optional WHERE clause for partial index

        Returns:
            SQL statement
        """
        unique_str = "UNIQUE " if unique else ""
        columns_str = ", ".join(columns)
        where_str = f" WHERE {where}" if where else ""

        return (
            f"CREATE {unique_str}INDEX CONCURRENTLY IF NOT EXISTS "
            f"{index_name} ON {table} ({columns_str}){where_str}"
        )

    def merge_statement(
        self,
        target: str,
        source: str,
        on_condition: str,
        when_matched: str | None = None,
        when_not_matched: str | None = None,
    ) -> str | None:
        """Generate MERGE statement (PG 15+).

        Args:
            target: Target table
            source: Source table or subquery
            on_condition: Join condition
            when_matched: Action when matched
            when_not_matched: Action when not matched

        Returns:
            SQL statement or None if not supported
        """
        if not self.version.supports(PGFeature.MERGE_STATEMENT):
            logger.warning(
                f"MERGE not available in PG {self.version.major}, "
                "use INSERT ON CONFLICT or manual upsert"
            )
            return None

        parts = [f"MERGE INTO {target}", f"USING {source}", f"ON {on_condition}"]

        if when_matched:
            parts.append(f"WHEN MATCHED THEN {when_matched}")
        if when_not_matched:
            parts.append(f"WHEN NOT MATCHED THEN {when_not_matched}")

        return " ".join(parts)

    def add_column_with_default_fast(
        self, table: str, column: str, column_type: str, default: str
    ) -> str:
        """Generate ADD COLUMN with DEFAULT.

        In PG 11+, adding a column with a default is instant for
        most data types (doesn't rewrite table).

        Args:
            table: Table name
            column: Column name
            column_type: Column type
            default: Default value expression

        Returns:
            SQL statement
        """
        # PG 11+ supports instant add column with default
        return (
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {column_type} DEFAULT {default}"
        )

    def unique_nulls_not_distinct(
        self, table: str, column: str, constraint_name: str
    ) -> str | None:
        """Generate UNIQUE constraint treating NULLs as equal (PG 15+).

        Args:
            table: Table name
            column: Column name
            constraint_name: Constraint name

        Returns:
            SQL statement or None if not supported
        """
        if not self.version.supports(PGFeature.UNIQUE_NULLS_NOT_DISTINCT):
            logger.warning(f"NULLS NOT DISTINCT not available in PG {self.version.major}")
            return None

        return (
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} "
            f"UNIQUE NULLS NOT DISTINCT ({column})"
        )

    def detach_partition_concurrently(self, parent: str, partition: str) -> str:
        """Generate DETACH PARTITION CONCURRENTLY (PG 14+).

        Args:
            parent: Parent table
            partition: Partition to detach

        Returns:
            SQL statement (may block if not supported)
        """
        if self.version.supports(PGFeature.DETACH_PARTITION_CONCURRENTLY):
            return f"ALTER TABLE {parent} DETACH PARTITION {partition} CONCURRENTLY"
        else:
            logger.warning(
                f"DETACH PARTITION CONCURRENTLY not available in PG {self.version.major}, "
                "using blocking DETACH"
            )
            return f"ALTER TABLE {parent} DETACH PARTITION {partition}"


def get_recommended_settings(version: PGVersionInfo) -> dict[str, str]:
    """Get recommended settings for a PostgreSQL version.

    Args:
        version: PostgreSQL version

    Returns:
        Dictionary of setting name to recommended value
    """
    settings = {
        "statement_timeout": "30s",
        "lock_timeout": "10s",
        "idle_in_transaction_session_timeout": "60s",
    }

    # Version-specific settings
    if version.is_at_least(13):
        settings["hash_mem_multiplier"] = "2.0"

    if version.is_at_least(14):
        settings["client_connection_check_interval"] = "1s"

    if version.is_at_least(15):
        settings["log_min_duration_statement"] = "1s"

    return settings


def check_version_compatibility(
    version: PGVersionInfo, min_version: tuple[int, int] = (12, 0)
) -> tuple[bool, str | None]:
    """Check if version meets minimum requirements.

    Args:
        version: Detected version
        min_version: Minimum required (major, minor)

    Returns:
        Tuple of (is_compatible, error_message)
    """
    min_major, min_minor = min_version

    if version.is_at_least(min_major, min_minor):
        return True, None

    return False, (
        f"PostgreSQL {version.major}.{version.minor} is not supported. "
        f"Minimum required version is {min_major}.{min_minor}."
    )
