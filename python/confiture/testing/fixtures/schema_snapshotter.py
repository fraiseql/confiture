"""Schema snapshot utility for migration testing.

Captures and compares database schema states to validate migrations work correctly.
Can be extracted to confiture-testing package in the future.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg


@dataclass
class ColumnInfo:
    """Information about a database column."""

    name: str
    data_type: str
    is_nullable: bool
    column_default: str | None = None


@dataclass
class ConstraintInfo:
    """Information about a table constraint."""

    name: str
    constraint_type: str  # PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK, etc.
    columns: list[str] = field(default_factory=list)


@dataclass
class IndexInfo:
    """Information about a database index."""

    name: str
    table_name: str
    is_unique: bool
    columns: list[str] = field(default_factory=list)


@dataclass
class ForeignKeyInfo:
    """Information about a foreign key relationship."""

    constraint_name: str
    column_name: str
    referenced_table: str
    referenced_column: str


@dataclass
class TableSchema:
    """Complete schema information for a single table."""

    name: str
    schema_name: str
    columns: dict[str, ColumnInfo] = field(default_factory=dict)
    constraints: list[ConstraintInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)


@dataclass
class SchemaSnapshot:
    """Complete snapshot of database schema at a point in time."""

    tables: dict[str, TableSchema] = field(default_factory=dict)
    views: set[str] = field(default_factory=set)
    materialized_views: set[str] = field(default_factory=set)
    functions: set[str] = field(default_factory=set)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SchemaChange:
    """Represents a detected schema change."""

    change_type: str  # added, removed, modified
    object_type: str  # table, column, index, constraint, etc.
    object_name: str
    details: dict[str, Any] = field(default_factory=dict)


class SchemaSnapshotter:
    """Capture and compare database schema states.

    Generic schema introspection that can be extracted to confiture-testing.
    """

    def __init__(self, connection: psycopg.Connection):
        """Initialize schema snapshotter.

        Args:
            connection: PostgreSQL connection for schema introspection
        """
        self.connection = connection

    def capture(self) -> SchemaSnapshot:
        """Capture current schema state.

        Returns:
            SchemaSnapshot with complete schema information
        """
        snapshot = SchemaSnapshot()

        with self.connection.cursor() as cur:
            # Get all tables
            cur.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name
                """
            )
            tables = cur.fetchall()

            # Capture each table's schema
            for schema_name, table_name in tables:
                table_key = f"{schema_name}.{table_name}"
                snapshot.tables[table_key] = self._capture_table_schema(
                    cur, schema_name, table_name
                )

            # Get views
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.views
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_name
                """
            )
            snapshot.views = {row[0] for row in cur.fetchall()}

            # Get materialized views
            cur.execute(
                "SELECT matviewname FROM pg_matviews WHERE schemaname != 'pg_catalog'"
            )
            snapshot.materialized_views = {row[0] for row in cur.fetchall()}

            # Get functions
            cur.execute(
                """
                SELECT routine_name
                FROM information_schema.routines
                WHERE routine_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY routine_name
                """
            )
            snapshot.functions = {row[0] for row in cur.fetchall()}

        return snapshot

    def _capture_table_schema(
        self, cur: psycopg.cursor, schema_name: str, table_name: str
    ) -> TableSchema:
        """Capture schema for a single table.

        Args:
            cur: Database cursor
            schema_name: Schema name
            table_name: Table name

        Returns:
            TableSchema with complete table information
        """
        table = TableSchema(name=table_name, schema_name=schema_name)

        # Get columns
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema_name, table_name),
        )

        for col_name, data_type, is_nullable, col_default in cur.fetchall():
            table.columns[col_name] = ColumnInfo(
                name=col_name,
                data_type=data_type,
                is_nullable=is_nullable == "YES",
                column_default=col_default,
            )

        # Get constraints
        cur.execute(
            """
            SELECT constraint_name, constraint_type
            FROM information_schema.table_constraints
            WHERE table_schema = %s AND table_name = %s
            ORDER BY constraint_name
            """,
            (schema_name, table_name),
        )

        for constraint_name, constraint_type in cur.fetchall():
            # Get columns for this constraint
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.constraint_column_usage
                WHERE constraint_schema = %s
                  AND constraint_name = %s
                ORDER BY column_name
                """,
                (schema_name, constraint_name),
            )
            columns = [row[0] for row in cur.fetchall()]

            table.constraints.append(
                ConstraintInfo(
                    name=constraint_name, constraint_type=constraint_type, columns=columns
                )
            )

        # Get indexes
        cur.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = %s AND tablename = %s
            ORDER BY indexname
            """,
            (schema_name, table_name),
        )

        for index_name, index_def in cur.fetchall():
            is_unique = "UNIQUE" in (index_def or "").upper()
            table.indexes.append(
                IndexInfo(
                    name=index_name,
                    table_name=table_name,
                    is_unique=is_unique,
                    columns=[],  # Would need to parse index_def to get columns
                )
            )

        # Get foreign keys
        cur.execute(
            """
            SELECT
                kcu.constraint_name,
                kcu.column_name,
                ccu.table_name,
                ccu.column_name
            FROM information_schema.key_column_usage kcu
            JOIN information_schema.constraint_column_usage ccu
                ON kcu.constraint_name = ccu.constraint_name
                AND kcu.table_schema = ccu.table_schema
            WHERE kcu.table_schema = %s
              AND kcu.table_name = %s
              AND kcu.constraint_name IN (
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = %s
                  AND table_name = %s
                  AND constraint_type = 'FOREIGN KEY'
              )
            """,
            (schema_name, table_name, schema_name, table_name),
        )

        for constraint_name, col_name, ref_table, ref_col in cur.fetchall():
            table.foreign_keys.append(
                ForeignKeyInfo(
                    constraint_name=constraint_name,
                    column_name=col_name,
                    referenced_table=ref_table,
                    referenced_column=ref_col,
                )
            )

        return table

    def compare(self, before: SchemaSnapshot, after: SchemaSnapshot) -> dict[str, Any]:
        """Compare two schema snapshots.

        Args:
            before: Schema snapshot before migration
            after: Schema snapshot after migration

        Returns:
            Dictionary of detected changes
        """
        changes = {
            "tables_added": set(after.tables.keys()) - set(before.tables.keys()),
            "tables_removed": set(before.tables.keys()) - set(after.tables.keys()),
            "tables_modified": [],
            "views_added": after.views - before.views,
            "views_removed": before.views - after.views,
            "mat_views_added": after.materialized_views - before.materialized_views,
            "mat_views_removed": before.materialized_views - after.materialized_views,
            "functions_added": after.functions - before.functions,
            "functions_removed": before.functions - after.functions,
        }

        # Check for modified tables
        common_tables = set(before.tables.keys()) & set(after.tables.keys())
        for table_name in common_tables:
            before_table = before.tables[table_name]
            after_table = after.tables[table_name]

            table_changes = {
                "table": table_name,
                "columns_added": set(after_table.columns.keys())
                - set(before_table.columns.keys()),
                "columns_removed": set(before_table.columns.keys())
                - set(after_table.columns.keys()),
                "columns_modified": [],
            }

            # Check for modified columns
            common_cols = set(before_table.columns.keys()) & set(after_table.columns.keys())
            for col_name in common_cols:
                before_col = before_table.columns[col_name]
                after_col = after_table.columns[col_name]

                if (
                    before_col.data_type != after_col.data_type
                    or before_col.is_nullable != after_col.is_nullable
                ):
                    table_changes["columns_modified"].append(
                        {
                            "column": col_name,
                            "before_type": before_col.data_type,
                            "after_type": after_col.data_type,
                            "before_nullable": before_col.is_nullable,
                            "after_nullable": after_col.is_nullable,
                        }
                    )

            # Check for constraint changes
            before_constraint_names = {c.name for c in before_table.constraints}
            after_constraint_names = {c.name for c in after_table.constraints}

            table_changes["constraints_added"] = (
                after_constraint_names - before_constraint_names
            )
            table_changes["constraints_removed"] = (
                before_constraint_names - after_constraint_names
            )

            # Only add to modified list if there are actual changes
            if (
                table_changes["columns_added"]
                or table_changes["columns_removed"]
                or table_changes["columns_modified"]
                or table_changes["constraints_added"]
                or table_changes["constraints_removed"]
            ):
                changes["tables_modified"].append(table_changes)

        return changes
