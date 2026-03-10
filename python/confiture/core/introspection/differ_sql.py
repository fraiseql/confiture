"""Generate DDL SQL from SchemaChange objects."""

from __future__ import annotations

from typing import Any

from confiture.exceptions import UnsafeOperationError
from confiture.models.schema import SchemaChange


def _format_column(col: dict[str, Any]) -> str:
    name = col["name"]
    col_type = col.get("type", "text")
    nullable = col.get("nullable", True)
    default = col.get("default")
    parts = [f"{name} {col_type}"]
    if not nullable:
        parts.append("NOT NULL")
    if default is not None:
        parts.append(f"DEFAULT {default}")
    return " ".join(parts)


class DifferSQLGenerator:
    """Generates safe, idempotent DDL SQL from SchemaChange objects."""

    def __init__(self, force_destructive: bool = False) -> None:
        self._force = force_destructive

    def generate_up(self, change: SchemaChange) -> str:
        """Generate the forward DDL SQL for a schema change."""
        method_name = f"_up_{change.type.lower()}"
        method = getattr(self, method_name, None)
        if method is None:
            raise NotImplementedError(f"No DDL generator for change type: {change.type}")
        return method(change)

    def generate_down(self, change: SchemaChange) -> str:
        """Generate the rollback DDL SQL for a schema change."""
        method_name = f"_down_{change.type.lower()}"
        method = getattr(self, method_name, None)
        if method is None:
            return f"-- WARNING: No automatic rollback for {change.type}\n"
        return method(change)

    def _up_add_table(self, change: SchemaChange) -> str:
        details = change.details or {}
        cols = details.get("columns", [])
        if cols:
            col_defs = ",\n    ".join(_format_column(c) for c in cols)
            return f"CREATE TABLE IF NOT EXISTS {change.table} (\n    {col_defs}\n);\n"
        return f"CREATE TABLE IF NOT EXISTS {change.table} ();\n"

    def _down_add_table(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP TABLE {change.table!r} is destructive. Re-run with --force to generate this DDL."
            )
        return f"DROP TABLE IF EXISTS {change.table} CASCADE;\n"

    def _up_drop_table(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP TABLE {change.table!r} is destructive. Re-run with --force to generate this DDL."
            )
        return f"DROP TABLE IF EXISTS {change.table} CASCADE;\n"

    def _down_drop_table(self, change: SchemaChange) -> str:
        return f"-- WARNING: Cannot automatically recreate dropped table {change.table}\n"

    def _up_add_column(self, change: SchemaChange) -> str:
        details = change.details or {}
        col_type = details.get("type", "text")
        nullable = details.get("nullable", True)
        default = details.get("default")
        col_def = f"{change.column} {col_type}"
        if not nullable:
            col_def += " NOT NULL"
        if default is not None:
            col_def += f" DEFAULT {default}"
        return f"ALTER TABLE {change.table} ADD COLUMN IF NOT EXISTS {col_def};\n"

    def _down_add_column(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP COLUMN {change.table}.{change.column} is destructive. Re-run with --force."
            )
        return f"ALTER TABLE {change.table} DROP COLUMN IF EXISTS {change.column};\n"

    def _up_drop_column(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP COLUMN {change.table}.{change.column} is destructive. Re-run with --force."
            )
        return f"ALTER TABLE {change.table} DROP COLUMN IF EXISTS {change.column};\n"

    def _down_drop_column(self, change: SchemaChange) -> str:
        return f"-- WARNING: Cannot automatically restore dropped column {change.table}.{change.column}\n"

    def _up_alter_column_type(self, change: SchemaChange) -> str:
        return (
            f"ALTER TABLE {change.table} ALTER COLUMN {change.column} TYPE {change.new_value}"
            f" USING {change.column}::{change.new_value}; -- FIXME: verify USING clause\n"
        )

    def _up_add_index(self, change: SchemaChange) -> str:
        details = change.details or {}
        index_name = details.get("name", f"idx_{change.table}")
        columns = details.get("columns", [])
        unique = details.get("unique", False)
        cols_str = ", ".join(columns) if columns else change.column or ""
        unique_str = "UNIQUE " if unique else ""
        return (
            f"CREATE {unique_str}INDEX CONCURRENTLY IF NOT EXISTS {index_name}"
            f" ON {change.table} ({cols_str});\n"
        )

    def _up_drop_index(self, change: SchemaChange) -> str:
        details = change.details or {}
        index_name = details.get("name", "")
        if not index_name:
            return "-- WARNING: Cannot drop index without name\n"
        return f"DROP INDEX CONCURRENTLY IF EXISTS {index_name};\n"

    def _up_add_constraint(self, change: SchemaChange) -> str:
        details = change.details or {}
        constraint_name = details.get("name", f"fk_{change.table}")
        constraint_type = details.get("type", "")
        columns = details.get("columns", [])
        references = details.get("references", "")
        cols_str = ", ".join(columns) if columns else ""

        if constraint_type == "FOREIGN KEY":
            return (
                f"ALTER TABLE {change.table} ADD CONSTRAINT {constraint_name}"
                f" FOREIGN KEY ({cols_str}) REFERENCES {references} NOT VALID;\n"
                f"ALTER TABLE {change.table} VALIDATE CONSTRAINT {constraint_name};\n"
            )
        return (
            f"ALTER TABLE {change.table} ADD CONSTRAINT {constraint_name}"
            f" {constraint_type} ({cols_str});\n"
        )

    def _up_drop_constraint(self, change: SchemaChange) -> str:
        details = change.details or {}
        constraint_name = details.get("name", "")
        if not constraint_name:
            return "-- WARNING: Cannot drop constraint without name\n"
        return f"ALTER TABLE {change.table} DROP CONSTRAINT IF EXISTS {constraint_name};\n"

    def _up_add_function(self, change: SchemaChange) -> str:
        details = change.details or {}
        source = details.get("source", "")
        if source:
            return f"{source}\n"
        return f"-- WARNING: No source provided for ADD_FUNCTION {change.table}\n"
