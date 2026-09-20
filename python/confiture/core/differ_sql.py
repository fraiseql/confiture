"""Generate DDL SQL from SchemaChange objects."""

from __future__ import annotations

from typing import Any

from confiture.core.ddl_objects import TABLE_SCOPED_KINDS
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


def _unnamed(change: SchemaChange, what: str) -> str:
    """The generator's "this changed, you write it" for a change with no object name.

    Never a fabricated ``idx_{table}`` / ``fk_{table}``: a name confiture made up
    is indistinguishable from one the author chose, which is how the
    ``index_name`` / ``name`` key mismatch survived unseen — the rebuild path
    created ``ix``, the migrate path created ``idx_t``, and ``confiture drift``
    then reported the divergence forever. Qualify the table and the invention
    stops even being a legal identifier (``idx_tenant.t``).

    ``-- WARNING:`` is this module's existing way of saying so.
    """
    return f"-- WARNING: Cannot generate {change.type} on {change.table} without a {what} name\n"


class DifferSQLGenerator:
    """Generates safe, idempotent DDL SQL from SchemaChange objects."""

    def __init__(self, force_destructive: bool = False) -> None:
        self._force = force_destructive

    def generate_up(self, change: SchemaChange) -> str:
        """Generate the forward DDL SQL for a schema change."""
        method = getattr(self, f"_up_{change.type.lower()}", None)
        if method is not None:
            return method(change)
        generic = self._generic_object_sql(change, forward=True)
        if generic is not None:
            return generic
        raise NotImplementedError(f"No DDL generator for change type: {change.type}")

    def generate_down(self, change: SchemaChange) -> str:
        """Generate the rollback DDL SQL for a schema change."""
        method = getattr(self, f"_down_{change.type.lower()}", None)
        if method is not None:
            return method(change)
        generic = self._generic_object_sql(change, forward=False)
        if generic is not None:
            return generic
        return f"-- WARNING: No automatic rollback for {change.type}\n"

    # ------------------------------------------------------------------
    # The object kinds #288 tracks that have no bespoke generator
    # ------------------------------------------------------------------

    def _generic_object_sql(self, change: SchemaChange, *, forward: bool) -> str | None:
        """Create-or-drop DDL for a tracked object, from what the change carries.

        ``None`` when the change is not one of #288's objects, or when its kind
        is in :data:`REPLACE_IS_AUTHORS_WORK` — every ``REPLACE`` whose one
        right statement PostgreSQL does not have. Those reach the migration as
        the generator's own ``-- WARNING: no SQL derived``, which is the
        existing way of saying "this changed, you write it".
        """
        details = change.details or {}
        kind = details.get("kind")
        keyword = details.get("keyword")
        if not kind or not keyword:
            return None
        verb, _, _ = change.type.partition("_")
        if verb == "REPLACE":
            # Every kind reaching here is in REPLACE_IS_AUTHORS_WORK; the ones
            # with one right statement have a bespoke `_up_replace_*` above.
            return None
        dropping = (verb == "DROP") == forward
        if dropping:
            if verb == "DROP" and forward and not self._force:
                raise UnsafeOperationError(
                    f"DROP {keyword} {change.table!r} is destructive. "
                    "Re-run with --force to generate this DDL."
                )
            return self._drop_object(kind, keyword, change)
        source = change.old_value if verb == "DROP" else change.new_value
        return self._statement(source, f"{change.type} {change.table}")

    @staticmethod
    def _drop_object(kind: str, keyword: str, change: SchemaChange) -> str:
        """``DROP <keyword> IF EXISTS <name>``, with the table a trigger hangs off."""
        name = (change.details or {}).get("name") or change.table or ""
        if kind in TABLE_SCOPED_KINDS:
            qualified, _, local = name.rpartition(".")
            if qualified:
                return f"DROP {keyword} IF EXISTS {local} ON {qualified};\n"
        return f"DROP {keyword} IF EXISTS {name};\n"

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
            f" USING {change.column}::{change.new_value}; -- review: verify the USING cast against existing data\n"
        )

    def _up_add_index(self, change: SchemaChange) -> str:
        details = change.details or {}
        index_name = details.get("name", "")
        if not index_name:
            return _unnamed(change, "index")
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
            return _unnamed(change, "index")
        return f"DROP INDEX CONCURRENTLY IF EXISTS {index_name};\n"

    def _down_add_index(self, change: SchemaChange) -> str:
        details = change.details or {}
        index_name = details.get("name", "")
        if not index_name:
            return _unnamed(change, "index")
        return f"DROP INDEX CONCURRENTLY IF EXISTS {index_name};\n"

    def _up_add_constraint(self, change: SchemaChange) -> str:
        details = change.details or {}
        constraint_name = details.get("name", "")
        if not constraint_name:
            return _unnamed(change, "constraint")
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
            return _unnamed(change, "constraint")
        return f"ALTER TABLE {change.table} DROP CONSTRAINT IF EXISTS {constraint_name};\n"

    def _up_add_foreign_key(self, change: SchemaChange) -> str:
        details = change.details or {}
        return self._up_add_constraint(
            SchemaChange(
                type=change.type,
                table=change.table,
                details={
                    "name": details.get("name", ""),
                    "type": "FOREIGN KEY",
                    "columns": details.get("columns", []),
                    "references": (
                        f"{details.get('ref_table', '')}({', '.join(details.get('ref_columns', []))})"
                    ),
                },
            )
        )

    def _up_drop_foreign_key(self, change: SchemaChange) -> str:
        details = change.details or {}
        return self._up_drop_constraint(
            SchemaChange(
                type=change.type,
                table=change.table,
                details={"name": details.get("name", "")},
            )
        )

    def _up_add_check_constraint(self, change: SchemaChange) -> str:
        details = change.details or {}
        return self._up_add_constraint(
            SchemaChange(
                type=change.type,
                table=change.table,
                details={
                    "name": details.get("name", ""),
                    "type": f"CHECK ({details.get('expression', '')})",
                    "columns": [],
                },
            )
        )

    def _up_drop_check_constraint(self, change: SchemaChange) -> str:
        details = change.details or {}
        return self._up_drop_constraint(
            SchemaChange(
                type=change.type,
                table=change.table,
                details={"name": details.get("name", "")},
            )
        )

    def _up_add_unique_constraint(self, change: SchemaChange) -> str:
        details = change.details or {}
        return self._up_add_constraint(
            SchemaChange(
                type=change.type,
                table=change.table,
                details={
                    "name": details.get("name", ""),
                    "type": "UNIQUE",
                    "columns": details.get("columns", []),
                },
            )
        )

    def _up_drop_unique_constraint(self, change: SchemaChange) -> str:
        details = change.details or {}
        return self._up_drop_constraint(
            SchemaChange(
                type=change.type,
                table=change.table,
                details={"name": details.get("name", "")},
            )
        )

    def _up_add_function(self, change: SchemaChange) -> str:
        """The routine's own ``CREATE OR REPLACE``.

        ``details["source"]`` predates #288 and is kept: a caller that builds
        the change by hand — the only kind there was, since ``SchemaDiffer``
        never emitted this type until #288 — still works.
        """
        source = (change.details or {}).get("source") or change.new_value
        return self._statement(source, f"ADD_FUNCTION {change.table}")

    def _down_add_function(self, change: SchemaChange) -> str:
        return self._drop_routine("FUNCTION", change)

    def _up_replace_function(self, change: SchemaChange) -> str:
        return self._statement(change.new_value, f"REPLACE_FUNCTION {change.table}")

    def _down_replace_function(self, change: SchemaChange) -> str:
        return self._statement(change.old_value, f"REPLACE_FUNCTION {change.table}")

    def _up_drop_function(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP FUNCTION {change.table!r} is destructive. "
                "Re-run with --force to generate this DDL."
            )
        return self._drop_routine("FUNCTION", change)

    def _down_drop_function(self, change: SchemaChange) -> str:
        return self._statement(change.old_value, f"DROP_FUNCTION {change.table}")

    def _up_add_procedure(self, change: SchemaChange) -> str:
        return self._statement(change.new_value, f"ADD_PROCEDURE {change.table}")

    def _down_add_procedure(self, change: SchemaChange) -> str:
        return self._drop_routine("PROCEDURE", change)

    def _up_replace_procedure(self, change: SchemaChange) -> str:
        return self._statement(change.new_value, f"REPLACE_PROCEDURE {change.table}")

    def _down_replace_procedure(self, change: SchemaChange) -> str:
        return self._statement(change.old_value, f"REPLACE_PROCEDURE {change.table}")

    def _up_drop_procedure(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP PROCEDURE {change.table!r} is destructive. "
                "Re-run with --force to generate this DDL."
            )
        return self._drop_routine("PROCEDURE", change)

    def _down_drop_procedure(self, change: SchemaChange) -> str:
        return self._statement(change.old_value, f"DROP_PROCEDURE {change.table}")

    def _up_add_aggregate(self, change: SchemaChange) -> str:
        return self._statement(change.new_value, f"ADD_AGGREGATE {change.table}")

    def _down_add_aggregate(self, change: SchemaChange) -> str:
        return self._drop_routine("AGGREGATE", change)

    def _up_replace_aggregate(self, change: SchemaChange) -> str:
        """An aggregate has no ``OR REPLACE`` either: drop it, then define it again."""
        return self._drop_routine("AGGREGATE", change) + self._statement(
            change.new_value, f"REPLACE_AGGREGATE {change.table}"
        )

    def _down_replace_aggregate(self, change: SchemaChange) -> str:
        return self._drop_routine("AGGREGATE", change) + self._statement(
            change.old_value, f"REPLACE_AGGREGATE {change.table}"
        )

    def _up_drop_aggregate(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP AGGREGATE {change.table!r} is destructive. "
                "Re-run with --force to generate this DDL."
            )
        return self._drop_routine("AGGREGATE", change)

    def _down_drop_aggregate(self, change: SchemaChange) -> str:
        return self._statement(change.old_value, f"DROP_AGGREGATE {change.table}")

    def _up_add_domain(self, change: SchemaChange) -> str:
        return self._statement(change.new_value, f"ADD_DOMAIN {change.table}")

    def _down_add_domain(self, change: SchemaChange) -> str:
        return f"DROP DOMAIN IF EXISTS {change.table};\n"

    def _up_drop_domain(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP DOMAIN {change.table!r} is destructive. "
                "Re-run with --force to generate this DDL."
            )
        return f"DROP DOMAIN IF EXISTS {change.table};\n"

    def _down_drop_domain(self, change: SchemaChange) -> str:
        return self._statement(change.old_value, f"DROP_DOMAIN {change.table}")

    def _up_add_type(self, change: SchemaChange) -> str:
        return self._statement(change.new_value, f"ADD_TYPE {change.table}")

    def _down_add_type(self, change: SchemaChange) -> str:
        return f"DROP TYPE IF EXISTS {change.table};\n"

    def _up_drop_type(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP TYPE {change.table!r} is destructive. "
                "Re-run with --force to generate this DDL."
            )
        return f"DROP TYPE IF EXISTS {change.table};\n"

    def _down_drop_type(self, change: SchemaChange) -> str:
        return self._statement(change.old_value, f"DROP_TYPE {change.table}")

    @staticmethod
    def _drop_routine(keyword: str, change: SchemaChange) -> str:
        """``DROP <keyword> IF EXISTS name(args)``.

        ``change.table`` carries the routine's identity — ``fn_c(bigint)`` — so
        the argument list PostgreSQL needs to pick the overload is already
        there. Without it the statement is ambiguous the moment a second
        overload exists.
        """
        return f"DROP {keyword} IF EXISTS {change.table};\n"

    # ------------------------------------------------------------------
    # Objects carried as whole definitions (#288)
    # ------------------------------------------------------------------

    @staticmethod
    def _statement(sql: str | None, missing: str) -> str:
        """A definition the differ captured, terminated; a warning when it has none."""
        if not sql:
            return f"-- WARNING: no definition captured for {missing}\n"
        return f"{sql.rstrip().rstrip(';')};\n"

    def _up_add_view(self, change: SchemaChange) -> str:
        return self._statement(change.new_value, f"ADD_VIEW {change.table}")

    def _down_add_view(self, change: SchemaChange) -> str:
        return f"DROP VIEW IF EXISTS {change.table};\n"

    def _up_replace_view(self, change: SchemaChange) -> str:
        return self._statement(change.new_value, f"REPLACE_VIEW {change.table}")

    def _down_replace_view(self, change: SchemaChange) -> str:
        """Back to the definition that was there — a replace is not undone by a drop."""
        return self._statement(change.old_value, f"REPLACE_VIEW {change.table}")

    def _up_drop_view(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP VIEW {change.table!r} is destructive. Re-run with --force to generate this DDL."
            )
        return f"DROP VIEW IF EXISTS {change.table};\n"

    def _down_drop_view(self, change: SchemaChange) -> str:
        return self._statement(change.old_value, f"DROP_VIEW {change.table}")

    def _up_add_matview(self, change: SchemaChange) -> str:
        return self._statement(change.new_value, f"ADD_MATVIEW {change.table}")

    def _down_add_matview(self, change: SchemaChange) -> str:
        return f"DROP MATERIALIZED VIEW IF EXISTS {change.table};\n"

    def _up_replace_matview(self, change: SchemaChange) -> str:
        """PostgreSQL has no ``CREATE OR REPLACE MATERIALIZED VIEW``: drop, then create.

        The rows are lost and rebuilt, which is what a matview is for; what a
        reader has to know is that dependent objects are dropped with it, so the
        statement says ``CASCADE`` nowhere and will fail loudly if any exist.
        """
        return f"DROP MATERIALIZED VIEW IF EXISTS {change.table};\n" + self._statement(
            change.new_value, f"REPLACE_MATVIEW {change.table}"
        )

    def _down_replace_matview(self, change: SchemaChange) -> str:
        return f"DROP MATERIALIZED VIEW IF EXISTS {change.table};\n" + self._statement(
            change.old_value, f"REPLACE_MATVIEW {change.table}"
        )

    def _up_drop_matview(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP MATERIALIZED VIEW {change.table!r} is destructive. "
                "Re-run with --force to generate this DDL."
            )
        return f"DROP MATERIALIZED VIEW IF EXISTS {change.table};\n"

    def _down_drop_matview(self, change: SchemaChange) -> str:
        return self._statement(change.old_value, f"DROP_MATVIEW {change.table}")

    def _up_add_enum_type(self, change: SchemaChange) -> str:
        details = change.details or {}
        values = details.get("values", [])
        name = change.table or ""
        if values:
            quoted = ", ".join(f"'{v}'" for v in values)
            return f"CREATE TYPE {name} AS ENUM ({quoted});\n"
        return f"CREATE TYPE {name} AS ENUM ();\n"

    def _down_add_enum_type(self, change: SchemaChange) -> str:
        name = change.table or ""
        return f"DROP TYPE IF EXISTS {name};\n"

    def _up_drop_enum_type(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP TYPE {change.table!r} is destructive. Re-run with --force to generate this DDL."
            )
        name = change.table or ""
        return f"DROP TYPE IF EXISTS {name};\n"

    def _down_drop_enum_type(self, change: SchemaChange) -> str:
        name = change.table or ""
        return f"-- WARNING: Cannot automatically recreate dropped enum type {name}\n"

    def _up_change_enum_values(self, change: SchemaChange) -> str:
        details = change.details or {}
        name = change.table or ""
        added = details.get("added_values", [])
        removed = details.get("removed_values", [])
        parts: list[str] = []
        parts.extend(f"ALTER TYPE {name} ADD VALUE IF NOT EXISTS '{v}';\n" for v in added)
        if removed:
            removed_list = ", ".join(f"'{v}'" for v in removed)
            parts.append(
                f"-- WARNING: Removing enum values ({removed_list}) from {name}"
                " requires DROP + RECREATE. Edit this migration manually.\n"
            )
        return "".join(parts) if parts else f"-- No enum value changes for {name}\n"

    def _up_add_sequence(self, change: SchemaChange) -> str:
        name = change.table or ""
        return f"CREATE SEQUENCE IF NOT EXISTS {name};\n"

    def _down_add_sequence(self, change: SchemaChange) -> str:
        name = change.table or ""
        return f"DROP SEQUENCE IF EXISTS {name};\n"

    def _up_drop_sequence(self, change: SchemaChange) -> str:
        if not self._force:
            raise UnsafeOperationError(
                f"DROP SEQUENCE {change.table!r} is destructive. Re-run with --force to generate this DDL."
            )
        name = change.table or ""
        return f"DROP SEQUENCE IF EXISTS {name};\n"

    def _down_drop_sequence(self, change: SchemaChange) -> str:
        name = change.table or ""
        return f"-- WARNING: Cannot automatically recreate dropped sequence {name}\n"
