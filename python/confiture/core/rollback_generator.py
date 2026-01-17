"""Auto-generate rollback SQL for simple operations.

Provides utilities to generate rollback SQL for common DDL operations
and test rollback safety.
"""

import contextlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RollbackSuggestion:
    """Suggested rollback SQL for a statement."""

    original_sql: str
    rollback_sql: str
    confidence: str  # "high", "medium", "low"
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "original_sql": self.original_sql[:100],
            "rollback_sql": self.rollback_sql,
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class RollbackTestResult:
    """Result of rollback testing."""

    migration_version: str
    migration_name: str
    clean_state: bool
    tables_before: set[str] = field(default_factory=set)
    tables_after: set[str] = field(default_factory=set)
    indexes_before: set[str] = field(default_factory=set)
    indexes_after: set[str] = field(default_factory=set)
    duration_ms: int = 0
    error: str | None = None

    @property
    def is_successful(self) -> bool:
        """Check if rollback test was successful."""
        return self.clean_state and self.error is None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "migration_version": self.migration_version,
            "migration_name": self.migration_name,
            "clean_state": self.clean_state,
            "is_successful": self.is_successful,
            "tables_before": list(self.tables_before),
            "tables_after": list(self.tables_after),
            "indexes_before": list(self.indexes_before),
            "indexes_after": list(self.indexes_after),
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


def generate_rollback(sql: str) -> RollbackSuggestion | None:
    """Generate rollback SQL for a statement.

    Supports automatic rollback generation for:
    - CREATE TABLE -> DROP TABLE
    - CREATE INDEX -> DROP INDEX
    - ADD COLUMN -> DROP COLUMN
    - ALTER TABLE ADD CONSTRAINT -> DROP CONSTRAINT

    Args:
        sql: SQL statement to generate rollback for

    Returns:
        RollbackSuggestion if generation is possible, None otherwise

    Example:
        >>> result = generate_rollback("CREATE TABLE users (id INT)")
        >>> print(result.rollback_sql)
        DROP TABLE IF EXISTS users
    """
    sql_upper = sql.upper().strip()
    sql_stripped = sql.strip()

    # CREATE TABLE -> DROP TABLE
    match = re.search(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?",
        sql_upper,
    )
    if match:
        table_name = match.group(1).lower()
        return RollbackSuggestion(
            original_sql=sql_stripped,
            rollback_sql=f"DROP TABLE IF EXISTS {table_name}",
            confidence="high",
            notes="Table will be dropped with all data",
        )

    # CREATE INDEX -> DROP INDEX
    match = re.search(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?",
        sql_upper,
    )
    if match:
        index_name = match.group(1).lower()
        # Check if CONCURRENTLY was used
        concurrent = "CONCURRENTLY" in sql_upper
        drop_sql = f"DROP INDEX {'CONCURRENTLY ' if concurrent else ''}IF EXISTS {index_name}"
        return RollbackSuggestion(
            original_sql=sql_stripped,
            rollback_sql=drop_sql,
            confidence="high",
        )

    # ALTER TABLE ADD COLUMN -> DROP COLUMN
    match = re.search(
        r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?:\")?(\w+)(?:\")?\s+"
        r"ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?",
        sql_upper,
    )
    if match and "ADD CONSTRAINT" not in sql_upper:
        table_name = match.group(1).lower()
        col_name = match.group(2).lower()
        return RollbackSuggestion(
            original_sql=sql_stripped,
            rollback_sql=f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS {col_name}",
            confidence="high",
            notes="Column data will be lost",
        )

    # ALTER TABLE ADD CONSTRAINT -> DROP CONSTRAINT
    match = re.search(
        r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?:\")?(\w+)(?:\")?\s+"
        r"ADD\s+CONSTRAINT\s+(?:\")?(\w+)(?:\")?",
        sql_upper,
    )
    if match:
        table_name = match.group(1).lower()
        constraint_name = match.group(2).lower()
        return RollbackSuggestion(
            original_sql=sql_stripped,
            rollback_sql=f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS {constraint_name}",
            confidence="high",
        )

    # CREATE SEQUENCE -> DROP SEQUENCE
    match = re.search(
        r"CREATE\s+SEQUENCE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?",
        sql_upper,
    )
    if match:
        seq_name = match.group(1).lower()
        return RollbackSuggestion(
            original_sql=sql_stripped,
            rollback_sql=f"DROP SEQUENCE IF EXISTS {seq_name}",
            confidence="high",
        )

    # CREATE TYPE -> DROP TYPE
    match = re.search(
        r"CREATE\s+TYPE\s+(?:\")?(\w+)(?:\")?",
        sql_upper,
    )
    if match:
        type_name = match.group(1).lower()
        return RollbackSuggestion(
            original_sql=sql_stripped,
            rollback_sql=f"DROP TYPE IF EXISTS {type_name}",
            confidence="high",
        )

    # CREATE EXTENSION -> DROP EXTENSION
    match = re.search(
        r"CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?",
        sql_upper,
    )
    if match:
        ext_name = match.group(1).lower()
        return RollbackSuggestion(
            original_sql=sql_stripped,
            rollback_sql=f"DROP EXTENSION IF EXISTS {ext_name}",
            confidence="medium",
            notes="Extension may be used by other objects",
        )

    return None


def generate_rollback_script(sql: str) -> list[RollbackSuggestion]:
    """Generate rollback SQL for multiple statements.

    Args:
        sql: SQL script with multiple statements

    Returns:
        List of RollbackSuggestions in reverse order (for proper rollback)
    """
    import sqlparse

    suggestions: list[RollbackSuggestion] = []
    statements = sqlparse.parse(sql)

    for stmt in statements:
        stmt_str = str(stmt).strip()
        if not stmt_str or stmt_str == ";":
            continue

        suggestion = generate_rollback(stmt_str)
        if suggestion:
            suggestions.append(suggestion)

    # Reverse for proper rollback order
    return list(reversed(suggestions))


class RollbackTester:
    """Helper for testing rollback safety.

    Tests the apply -> rollback -> verify cycle to ensure
    migrations can be safely rolled back.

    Example:
        >>> tester = RollbackTester(conn)
        >>> result = tester.test_migration(migration)
        >>> if not result.is_successful:
        ...     print(f"Rollback test failed: {result.error}")
    """

    def __init__(self, connection: Any):
        """Initialize rollback tester.

        Args:
            connection: Database connection
        """
        self.connection = connection

    def test_migration(self, migration: Any) -> RollbackTestResult:
        """Test apply -> rollback -> verify cycle.

        Args:
            migration: Migration instance with up() and down() methods

        Returns:
            RollbackTestResult with test outcome
        """
        import time

        start_time = time.perf_counter()

        result = RollbackTestResult(
            migration_version=getattr(migration, "version", "unknown"),
            migration_name=getattr(migration, "name", "unknown"),
            clean_state=False,
        )

        try:
            # Capture schema before
            result.tables_before = self._get_tables()
            result.indexes_before = self._get_indexes()

            # Apply migration
            if hasattr(migration, "up"):
                migration.up()
            self.connection.commit()

            # Rollback migration
            if hasattr(migration, "down"):
                migration.down()
            else:
                result.error = "Migration has no down() method"
                return result
            self.connection.commit()

            # Verify clean state
            result.tables_after = self._get_tables()
            result.indexes_after = self._get_indexes()

            # Check if state matches
            result.clean_state = (
                result.tables_before == result.tables_after
                and result.indexes_before == result.indexes_after
            )

            if not result.clean_state:
                # Identify what changed
                added_tables = result.tables_after - result.tables_before
                removed_tables = result.tables_before - result.tables_after
                added_indexes = result.indexes_after - result.indexes_before
                removed_indexes = result.indexes_before - result.indexes_after

                changes = []
                if added_tables:
                    changes.append(f"Tables added: {added_tables}")
                if removed_tables:
                    changes.append(f"Tables removed: {removed_tables}")
                if added_indexes:
                    changes.append(f"Indexes added: {added_indexes}")
                if removed_indexes:
                    changes.append(f"Indexes removed: {removed_indexes}")

                result.error = "; ".join(changes)

        except Exception as e:
            result.error = str(e)
            # Try to rollback the transaction
            with contextlib.suppress(Exception):
                self.connection.rollback()

        result.duration_ms = int((time.perf_counter() - start_time) * 1000)
        return result

    def _get_tables(self) -> set[str]:
        """Get all tables in public schema."""
        with self.connection.cursor() as cur:
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
            """)
            return {row[0] for row in cur.fetchall()}

    def _get_indexes(self) -> set[str]:
        """Get all indexes in public schema."""
        with self.connection.cursor() as cur:
            cur.execute("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
            """)
            return {row[0] for row in cur.fetchall()}


def suggest_backup_for_destructive_operations(sql: str) -> list[str]:
    """Suggest backup commands for destructive operations.

    Args:
        sql: SQL statement to analyze

    Returns:
        List of backup suggestions
    """
    suggestions: list[str] = []
    sql_upper = sql.upper()

    # DROP TABLE
    match = re.search(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?", sql_upper)
    if match:
        table_name = match.group(1).lower()
        suggestions.append(
            f"Consider backing up table '{table_name}' before dropping:\n"
            f"  CREATE TABLE {table_name}_backup AS SELECT * FROM {table_name};\n"
            f"  -- or use pg_dump: pg_dump -t {table_name} database_name > backup.sql"
        )

    # DROP COLUMN
    match = re.search(
        r"ALTER\s+TABLE\s+(?:\")?(\w+)(?:\")?\s+DROP\s+(?:COLUMN\s+)?(?:IF\s+EXISTS\s+)?(?:\")?(\w+)(?:\")?",
        sql_upper,
    )
    if match:
        table_name = match.group(1).lower()
        col_name = match.group(2).lower()
        suggestions.append(
            f"Consider backing up column '{col_name}' from '{table_name}' before dropping:\n"
            f"  ALTER TABLE {table_name} ADD COLUMN {col_name}_backup <type>;\n"
            f"  UPDATE {table_name} SET {col_name}_backup = {col_name};"
        )

    # TRUNCATE
    if "TRUNCATE" in sql_upper:
        match = re.search(r"TRUNCATE\s+(?:TABLE\s+)?(?:\")?(\w+)(?:\")?", sql_upper)
        if match:
            table_name = match.group(1).lower()
            suggestions.append(
                f"Consider backing up table '{table_name}' before truncating:\n"
                f"  CREATE TABLE {table_name}_backup AS SELECT * FROM {table_name};"
            )

    return suggestions
