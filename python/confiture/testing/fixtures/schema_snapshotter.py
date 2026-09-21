"""Schema snapshot utility for migration testing.

Captures and compares database schema states to validate migrations work correctly.
Can be extracted to confiture-testing package in the future.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from confiture.core import live_catalog

if TYPE_CHECKING:
    import psycopg

    from confiture.core.schema_model import Index, Table


#: What ``information_schema.table_constraints`` called each kind a table
#: constraint can be; a NOT NULL column is not one of them.
_CONSTRAINT_TYPES = {
    "primary_key": "PRIMARY KEY",
    "unique": "UNIQUE",
    "check": "CHECK",
    "foreign_key": "FOREIGN KEY",
}

#: Every ``prokind``: function, procedure, aggregate, window function.
_ROUTINE_KINDS = ("f", "p", "a", "w")


@dataclass
class ColumnInfo:
    """Information about a database column.

    ``data_type`` is ``format_type``'s spelling — ``character varying(50)``,
    ``text[]``, the enum's own name — and ``column_default`` the default as
    confiture renders a DDL default.
    """

    name: str
    data_type: str
    is_nullable: bool
    column_default: str | None = None


@dataclass
class ConstraintInfo:
    """Information about a table constraint."""

    name: str
    constraint_type: str  # PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK
    #: The key columns, in key order — a foreign key's own, not the ones it
    #: references; empty for a CHECK.
    columns: list[str] = field(default_factory=list)


@dataclass
class IndexInfo:
    """Information about a database index."""

    name: str
    table_name: str
    is_unique: bool
    #: Each key, a column name or its expression as confiture renders one.
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
class SnapshotChange:
    """Represents a detected schema change."""

    change_type: str  # added, removed, modified
    object_type: str  # table, column, index, constraint, etc.
    object_name: str
    details: dict[str, Any] = field(default_factory=dict)


# Backward-compatible alias
SchemaChange = SnapshotChange


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

        Every user schema the connection's role can use is read through
        ``core/live_catalog``. ``tables`` holds every table, partitioned table,
        view and foreign table — what ``information_schema.tables`` listed —
        and ``functions`` the name of every routine of every kind; an
        extension's own routines, views and indexes are kept, its tables are
        not.

        Returns:
            SchemaSnapshot with complete schema information
        """
        snapshot = SchemaSnapshot()
        schemas = live_catalog.user_schemas(self.connection)

        model = live_catalog.read(self.connection, schemas=schemas, kinds=live_catalog.TABLE_LIKE)
        indexes = live_catalog.indexes(self.connection, schemas)
        for ref, table in model.tables.items():
            snapshot.tables[f"{table.schema}.{table.name}"] = _table_schema(
                table, indexes.get(ref, ())
            )

        views = live_catalog.views(self.connection, schemas)
        snapshot.views = {view.name for view in views if view.relkind == "v"}
        snapshot.materialized_views = {view.name for view in views if view.relkind == "m"}
        snapshot.functions = {
            routine.name
            for routine in live_catalog.routines(self.connection, schemas, kinds=_ROUTINE_KINDS)
        }

        return snapshot

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
                "columns_added": set(after_table.columns.keys()) - set(before_table.columns.keys()),
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

            table_changes["constraints_added"] = after_constraint_names - before_constraint_names
            table_changes["constraints_removed"] = before_constraint_names - after_constraint_names

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


def _table_schema(table: Table, indexes: Iterable[Index]) -> TableSchema:
    """One table as the snapshot holds it."""
    return TableSchema(
        name=table.name,
        schema_name=table.schema or "",
        columns={
            column.name: ColumnInfo(
                name=column.name,
                data_type=column.type_text or "",
                is_nullable=not column.not_null,
                column_default=column.default,
            )
            for column in table.columns
        },
        constraints=[
            ConstraintInfo(
                name=constraint.name,
                constraint_type=_CONSTRAINT_TYPES[constraint.kind],
                columns=list(constraint.columns),
            )
            for constraint in table.constraints
        ],
        indexes=[
            IndexInfo(
                name=index.name or "",
                table_name=table.name,
                is_unique=index.unique,
                columns=list(index.columns),
            )
            for index in indexes
        ],
        foreign_keys=[
            ForeignKeyInfo(
                constraint_name=fk.name,
                column_name=column,
                referenced_table=(fk.ref_table or "").rpartition(".")[2],
                referenced_column=referenced,
            )
            for fk in table.constraints_of("foreign_key")
            for column, referenced in zip(fk.columns, fk.ref_columns, strict=True)
        ],
    )
