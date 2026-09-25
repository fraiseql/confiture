"""Render a schema change as DDL: the up and the down each variant is, in SQL.

The one renderer of a :data:`~confiture.core.schema_change.SchemaChange`.
``MigrationGenerator`` writes the files — the destructive gate, the tier and
irreversibility directives — and asks this module what each change is, for every
kind: a second renderer is how a kind comes to have a rendering nothing calls,
tested and unreachable. Dispatch is a ``match`` per group, each closed by
``assert_never``, so a new variant is a type error here before it is a missing
migration.

``None`` from :meth:`DifferSQLGenerator.generate_up` is *no SQL derived*: the
change is reported and the author writes its DDL. ``None`` from
:meth:`~DifferSQLGenerator.generate_down` is *no rollback derived*, which the
generator writes as an ``irreversible`` directive; a down this module can say more
about — a dropped enum type it cannot recreate, an added constraint it does not yet
drop — comes back as a ``-- WARNING:`` line instead. A statement ends with its
semicolon and a newline.
"""

from __future__ import annotations

from typing import assert_never

from confiture.core.ddl_clauses import column_body, column_element, column_type, named
from confiture.core.ddl_clauses import constraint_body as _clause
from confiture.core.ddl_objects import OBJECT_KEYWORD
from confiture.core.schema_change import (
    CheckConstraintAdded,
    CheckConstraintDropped,
    ColumnAdded,
    ColumnChange,
    ColumnDefaultChanged,
    ColumnDropped,
    ColumnNullabilityChanged,
    ColumnRenamed,
    ColumnTypeChanged,
    DefinitionChange,
    EnumOrSequenceChange,
    EnumTypeAdded,
    EnumTypeDropped,
    EnumValuesChanged,
    ForeignKeyAdded,
    ForeignKeyDropped,
    IndexAdded,
    IndexDropped,
    ObjectAdded,
    ObjectDropped,
    ObjectReplaced,
    SchemaChange,
    SequenceAdded,
    SequenceDropped,
    TableAdded,
    TableChange,
    TableDropped,
    TableObjectChange,
    TableRenamed,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)
from confiture.core.schema_model import Constraint, Table

#: The kinds compared by definition that a migration is derived for, created and
#: dropped — the ones ``migrate diff --generate`` writes (#288). The rest —
#: a trigger, an extension, a schema, a policy, … — are reported, and the migration
#: says ``-- WARNING: no SQL derived`` for the author to write.
DERIVED_KINDS: frozenset[str] = frozenset(
    {"view", "matview", "function", "procedure", "aggregate", "domain", "type"}
)

#: The kinds whose redefinition is a statement confiture writes. Every other
#: ``REPLACE`` is in ``ddl_objects.REPLACE_IS_AUTHORS_WORK``, with its reason.
_REPLACED_BY_DEFINITION: frozenset[str] = frozenset({"view", "function", "procedure"})
REPLACED_BY_DROP_AND_CREATE: frozenset[str] = frozenset({"matview", "aggregate"})


def _unnamed(change: SchemaChange, what: str) -> str:
    """The generator's "this changed, you write it" for a change with no object name.

    Never a fabricated ``idx_{table}`` / ``fk_{table}``: a name confiture made up
    is indistinguishable from one the author chose, and ``confiture drift`` then
    reports the divergence forever. Qualify the table and the invention stops even
    being a legal identifier (``idx_tenant.t``).
    """
    wire = change.to_wire()
    return f"-- WARNING: Cannot generate {wire.type} on {wire.table} without a {what} name\n"


def _incomplete(change: SchemaChange, what: str) -> str:
    """:func:`_unnamed`'s sibling, for a change that has a name but not a statement."""
    wire = change.to_wire()
    return f"-- WARNING: Cannot generate {wire.type} on {wire.table} without {what}\n"


def _no_rollback(change: SchemaChange) -> str:
    return f"-- WARNING: No automatic rollback for {change.to_wire().type}\n"


def _statement(sql: str | None, change: SchemaChange) -> str:
    """A definition the differ captured, terminated; a warning when it has none."""
    if not sql:
        wire = change.to_wire()
        return f"-- WARNING: no definition captured for {wire.type} {wire.table}\n"
    return f"{sql.rstrip().rstrip(';')};\n"


def _drop(keyword: str, name: str) -> str:
    """``DROP <keyword> IF EXISTS <name>``; a routine's name carries its argument types.

    ``fn_c(bigint)`` is what picks the overload: without it the statement is
    ambiguous the moment a second overload exists.
    """
    return f"DROP {keyword} IF EXISTS {name};\n"


def _table_constraints(table: Table) -> list[Constraint]:
    """A table's own constraints in the order a ``CREATE TABLE`` writes them.

    The primary key is written at table level rather than on the column, so that
    a composite one has somewhere to go. A constraint that says nothing — a CHECK
    with no expression, any other with no column — is not written at all.
    """
    primary = Constraint(
        kind="primary_key",
        columns=tuple(column.folded for column in table.columns if column.primary_key),
    )
    listed = [
        primary,
        *table.constraints_of("foreign_key"),
        *table.constraints_of("unique"),
        *table.constraints_of("check"),
    ]
    return [c for c in listed if (c.expression if c.kind == "check" else c.columns)]


def _create_table(table: Table) -> str:
    """The table the schema declared: its columns **and** its constraints.

    A constraint the schema left unnamed is written unnamed, exactly as the
    author wrote it; PostgreSQL generates the name either way.
    """
    elements = [column_element(column) for column in table.columns]
    bodies = [(c, _clause(c)) for c in _table_constraints(table)]
    elements.extend(named(c.name, body) for c, body in bodies if body is not None)
    warnings = "".join(
        _incomplete(TableAdded(table), f"a complete {c.kind.replace('_', ' ').upper()} clause")
        for c, body in bodies
        if body is None
    )
    if elements:
        joined = ",\n    ".join(elements)
        return f"{warnings}CREATE TABLE IF NOT EXISTS {table.qualified} (\n    {joined}\n);\n"
    return f"{warnings}CREATE TABLE IF NOT EXISTS {table.qualified} ();\n"


def _table_up(change: TableChange) -> str | None:
    match change:
        case TableAdded(table):
            return _create_table(table)
        case TableDropped(table):
            return f"DROP TABLE {table.qualified};\n"
        case TableRenamed(old, new):
            # `ALTER TABLE a.t RENAME TO a.t2` is a syntax error: the target is a bare name.
            return f"ALTER TABLE {old.qualified} RENAME TO {new.name};\n"
        case _:
            assert_never(change)


def _table_down(change: TableChange) -> str | None:
    match change:
        case TableAdded(table):
            return f"DROP TABLE {table.qualified};\n"
        case TableDropped(table):
            return _create_table(table) if table.columns else None
        case TableRenamed(old, new):
            return f"ALTER TABLE {new.qualified} RENAME TO {old.name};\n"
        case _:
            assert_never(change)


def _nullability(table: str, column: str, *, nullable: bool) -> str:
    verb = "DROP" if nullable else "SET"
    return f"ALTER TABLE {table} ALTER COLUMN {column} {verb} NOT NULL;\n"


def _default(table: str, column: str, default: str | None) -> str:
    clause = f"SET DEFAULT {default}" if default else "DROP DEFAULT"
    return f"ALTER TABLE {table} ALTER COLUMN {column} {clause};\n"


def _column_up(change: ColumnChange) -> str:
    match change:
        case ColumnAdded(table, column):
            return f"ALTER TABLE {table} ADD COLUMN {column.folded} {column_body(column)};\n"
        case ColumnDropped(table, column):
            return f"ALTER TABLE {table} DROP COLUMN {column.folded};\n"
        case ColumnRenamed(table, old, new):
            return f"ALTER TABLE {table} RENAME COLUMN {old} TO {new};\n"
        case ColumnTypeChanged(table, old, new):
            return f"ALTER TABLE {table} ALTER COLUMN {old.folded} TYPE {column_type(new)};\n"
        case ColumnNullabilityChanged(table, column, nullable):
            return _nullability(table, column, nullable=nullable)
        case ColumnDefaultChanged(table, column, _, new):
            return _default(table, column, new)
        case _:
            assert_never(change)


def _column_down(change: ColumnChange) -> str:
    """The reverse of each column change; a dropped column comes back, its rows do not."""
    match change:
        case ColumnAdded(table, column):
            return f"ALTER TABLE {table} DROP COLUMN {column.folded};\n"
        case ColumnDropped(table, column):
            return f"ALTER TABLE {table} ADD COLUMN {column.folded} {column_body(column)};\n"
        case ColumnRenamed(table, old, new):
            return f"ALTER TABLE {table} RENAME COLUMN {new} TO {old};\n"
        case ColumnTypeChanged(table, old, _):
            return f"ALTER TABLE {table} ALTER COLUMN {old.folded} TYPE {column_type(old)};\n"
        case ColumnNullabilityChanged(table, column, nullable):
            return _nullability(table, column, nullable=not nullable)
        case ColumnDefaultChanged(table, column, old, _):
            return _default(table, column, old)
        case _:
            assert_never(change)


def _create_index(change: IndexAdded | IndexDropped) -> str:
    index = change.index
    if not index.name:
        return _unnamed(change, "index")
    unique = "UNIQUE " if index.unique else ""
    return (
        f"CREATE {unique}INDEX CONCURRENTLY IF NOT EXISTS {index.name}"
        f" ON {change.table} ({', '.join(index.columns)});\n"
    )


def _drop_index(change: IndexAdded | IndexDropped) -> str:
    if not change.index.name:
        return _unnamed(change, "index")
    return f"DROP INDEX CONCURRENTLY IF EXISTS {change.index.name};\n"


def _add_foreign_key(change: ForeignKeyAdded | ForeignKeyDropped) -> str:
    """``NOT VALID`` then ``VALIDATE``, which needs a name — or one statement.

    The two-step takes a brief ``SHARE ROW EXCLUSIVE`` lock and scans the table
    outside it, and the second step names the constraint. An unnamed foreign key
    cannot be validated separately, so it is added in one statement and the
    statement says so rather than carrying a name confiture made up.
    """
    body = _clause(change.constraint)
    if body is None:
        return _incomplete(change, "a column list and a referenced table")
    name = change.constraint.name
    clause = named(name, body)
    if not name:
        return (
            f"ALTER TABLE {change.table} ADD {clause};"
            " -- review: unnamed in the schema, so it cannot be added NOT VALID and"
            " validated separately; this scans the table under a lock\n"
        )
    return (
        f"ALTER TABLE {change.table} ADD {clause} NOT VALID;\n"
        f"ALTER TABLE {change.table} VALIDATE CONSTRAINT {name};\n"
    )


def _add_constraint(
    change: CheckConstraintAdded
    | CheckConstraintDropped
    | UniqueConstraintAdded
    | UniqueConstraintDropped,
    missing: str,
) -> str:
    body = _clause(change.constraint)
    if body is None:
        return _incomplete(change, missing)
    return f"ALTER TABLE {change.table} ADD {named(change.constraint.name, body)};\n"


def _drop_constraint(
    change: ForeignKeyAdded
    | ForeignKeyDropped
    | CheckConstraintAdded
    | CheckConstraintDropped
    | UniqueConstraintAdded
    | UniqueConstraintDropped,
) -> str:
    if not change.constraint.name:
        return _unnamed(change, "constraint")
    return f"ALTER TABLE {change.table} DROP CONSTRAINT IF EXISTS {change.constraint.name};\n"


def _table_object_up(change: TableObjectChange) -> str:
    match change:
        case IndexAdded():
            return _create_index(change)
        case IndexDropped():
            return _drop_index(change)
        case ForeignKeyAdded():
            return _add_foreign_key(change)
        case CheckConstraintAdded():
            return _add_constraint(change, "a CHECK expression")
        case UniqueConstraintAdded():
            return _add_constraint(change, "a column list")
        case ForeignKeyDropped() | CheckConstraintDropped() | UniqueConstraintDropped():
            return _drop_constraint(change)
        case _:
            assert_never(change)


def _table_object_down(change: TableObjectChange) -> str | None:
    """A drop is undone by the ``ADD`` the change carries, an add by dropping what it named.

    An added constraint the schema left unnamed has no rollback: PostgreSQL chooses
    its name when it is added, and a name confiture guessed would drop nothing,
    or something else.
    """
    match change:
        case IndexAdded():
            return _drop_index(change)
        case IndexDropped():
            return _create_index(change)
        case ForeignKeyDropped():
            return _add_foreign_key(change)
        case CheckConstraintDropped():
            return _add_constraint(change, "a CHECK expression")
        case UniqueConstraintDropped():
            return _add_constraint(change, "a column list")
        case ForeignKeyAdded() | CheckConstraintAdded() | UniqueConstraintAdded():
            return _drop_constraint(change) if change.constraint.name else None
        case _:
            assert_never(change)


def _quoted(label: str) -> str:
    return "'" + label.replace("'", "''") + "'"


def _enum_values(change: EnumValuesChanged) -> str:
    name = change.enum
    parts = [f"ALTER TYPE {name} ADD VALUE IF NOT EXISTS {_quoted(v)};\n" for v in change.added]
    if change.removed:
        removed = ", ".join(_quoted(v) for v in change.removed)
        parts.append(
            f"-- WARNING: Removing enum values ({removed}) from {name}"
            " requires DROP + RECREATE. Edit this migration manually.\n"
        )
    return "".join(parts) if parts else f"-- No enum value changes for {name}\n"


class DifferSQLGenerator:
    """Generates the DDL for a schema change, up and down."""

    def generate_up(self, change: SchemaChange) -> str | None:
        """The forward DDL for *change*, or ``None`` when none is derived."""
        match change:
            case TableAdded() | TableDropped() | TableRenamed():
                return _table_up(change)
            case (
                ColumnAdded()
                | ColumnDropped()
                | ColumnRenamed()
                | ColumnTypeChanged()
                | ColumnNullabilityChanged()
                | ColumnDefaultChanged()
            ):
                return _column_up(change)
            case (
                IndexAdded()
                | IndexDropped()
                | ForeignKeyAdded()
                | ForeignKeyDropped()
                | CheckConstraintAdded()
                | CheckConstraintDropped()
                | UniqueConstraintAdded()
                | UniqueConstraintDropped()
            ):
                return _table_object_up(change)
            case (
                EnumTypeAdded()
                | EnumTypeDropped()
                | EnumValuesChanged()
                | SequenceAdded()
                | SequenceDropped()
            ):
                return _enum_or_sequence_up(change)
            case ObjectAdded() | ObjectDropped() | ObjectReplaced():
                return _definition_up(change)
            case _:
                assert_never(change)

    def generate_down(self, change: SchemaChange) -> str | None:
        """The DDL that undoes *change*, or ``None`` when no rollback is derived."""
        match change:
            case TableAdded() | TableDropped() | TableRenamed():
                return _table_down(change)
            case (
                ColumnAdded()
                | ColumnDropped()
                | ColumnRenamed()
                | ColumnTypeChanged()
                | ColumnNullabilityChanged()
                | ColumnDefaultChanged()
            ):
                return _column_down(change)
            case (
                IndexAdded()
                | IndexDropped()
                | ForeignKeyAdded()
                | ForeignKeyDropped()
                | CheckConstraintAdded()
                | CheckConstraintDropped()
                | UniqueConstraintAdded()
                | UniqueConstraintDropped()
            ):
                return _table_object_down(change)
            case (
                EnumTypeAdded()
                | EnumTypeDropped()
                | EnumValuesChanged()
                | SequenceAdded()
                | SequenceDropped()
            ):
                return _enum_or_sequence_down(change)
            case ObjectAdded() | ObjectDropped() | ObjectReplaced():
                return _definition_down(change)
            case _:
                assert_never(change)


def _enum_or_sequence_up(change: EnumOrSequenceChange) -> str:
    match change:
        case EnumTypeAdded(enum):
            labels = ", ".join(_quoted(v) for v in enum.values)
            return f"CREATE TYPE {enum.qualified} AS ENUM ({labels});\n"
        case EnumTypeDropped(enum):
            return _drop("TYPE", enum.qualified)
        case EnumValuesChanged():
            return _enum_values(change)
        case SequenceAdded(sequence):
            return f"CREATE SEQUENCE IF NOT EXISTS {sequence.qualified};\n"
        case SequenceDropped(sequence):
            return _drop("SEQUENCE", sequence.qualified)
        case _:
            assert_never(change)


def _definition_up(change: DefinitionChange) -> str | None:
    kind = change.ref.kind
    keyword = OBJECT_KEYWORD.get(kind, "")
    name = change.ref.qualified
    match change:
        case ObjectAdded(_, obj) if kind in DERIVED_KINDS:
            return _statement(obj.create_sql, change)
        case ObjectDropped() if kind in DERIVED_KINDS:
            return _drop(keyword, name)
        case ObjectReplaced(_, _, new) if kind in _REPLACED_BY_DEFINITION:
            return _statement(new.create_sql, change)
        case ObjectReplaced(_, _, new) if kind in REPLACED_BY_DROP_AND_CREATE:
            return _drop(keyword, name) + _statement(new.create_sql, change)
        case ObjectAdded() | ObjectDropped() | ObjectReplaced():
            return None
        case _:
            assert_never(change)


def _enum_or_sequence_down(change: EnumOrSequenceChange) -> str:
    match change:
        case EnumTypeAdded(enum):
            return _drop("TYPE", enum.qualified)
        case EnumTypeDropped(enum):
            return f"-- WARNING: Cannot automatically recreate dropped enum type {enum.qualified}\n"
        case EnumValuesChanged():
            return _no_rollback(change)
        case SequenceAdded(sequence):
            return _drop("SEQUENCE", sequence.qualified)
        case SequenceDropped(sequence):
            return (
                f"-- WARNING: Cannot automatically recreate dropped sequence {sequence.qualified}\n"
            )
        case _:
            assert_never(change)


def _definition_down(change: DefinitionChange) -> str | None:
    """A create is undone by a drop, a drop by the definition it carried, a replace by the old one."""
    kind = change.ref.kind
    keyword = OBJECT_KEYWORD.get(kind, "")
    name = change.ref.qualified
    match change:
        case ObjectAdded() if kind in DERIVED_KINDS:
            return _drop(keyword, name)
        case ObjectDropped(_, obj) if kind in DERIVED_KINDS:
            return _statement(obj.create_sql, change)
        case ObjectReplaced(_, old, _) if kind in _REPLACED_BY_DEFINITION:
            return _statement(old.create_sql, change)
        case ObjectReplaced(_, old, _) if kind in REPLACED_BY_DROP_AND_CREATE:
            return _drop(keyword, name) + _statement(old.create_sql, change)
        case ObjectAdded() | ObjectDropped() | ObjectReplaced():
            return None
        case _:
            assert_never(change)
