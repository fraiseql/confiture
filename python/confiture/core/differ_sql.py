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
generator writes as an ``irreversible`` directive with its reason. A ``-- WARNING:``
line is what this module writes where a statement would need what the change does
not carry — an index or constraint with no name, a CHECK with no expression. A
statement ends with its semicolon and a newline.
"""

from __future__ import annotations

from typing import assert_never

from confiture.core.ddl_clauses import column_body, column_element, column_type, named
from confiture.core.ddl_clauses import constraint_body as _clause
from confiture.core.ddl_objects import OBJECT_KEYWORD, DDLObject, drop_on_table
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
from confiture.core.schema_model import Column, Constraint, EnumType, Index, Sequence, Table
from confiture.core.type_lattice import has_assignment_cast

#: The kinds compared by definition that a migration is derived for, created and
#: dropped — the ones ``migrate diff --generate`` writes (#288, #335). The rest —
#: a rule, an event trigger, statistics, a server, … — are reported, and the
#: migration says ``-- WARNING: no SQL derived`` for the author to write.
DERIVED_KINDS: frozenset[str] = frozenset(
    {
        "view",
        "matview",
        "function",
        "procedure",
        "aggregate",
        "domain",
        "type",
        "trigger",
        "extension",
        "schema",
        "policy",
    }
)

#: The derived kinds PostgreSQL gives no ``IF NOT EXISTS`` or ``OR REPLACE``: the
#: creating statement is guarded on ``duplicate_object`` so that the migration
#: re-applies, as every other creation it writes does.
_GUARDED_KINDS: frozenset[str] = frozenset({"domain", "type", "policy"})

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


def _statement(sql: str | None, change: SchemaChange) -> str:
    """A definition the differ captured, terminated; a warning when it has none."""
    if not sql:
        wire = change.to_wire()
        return f"-- WARNING: no definition captured for {wire.type} {wire.table}\n"
    return f"{sql.rstrip().rstrip(';')};\n"


def _creating(obj: DDLObject, change: SchemaChange) -> str:
    """The statement that creates *obj*, re-appliable: guarded where PostgreSQL has no clause."""
    statement = _statement(obj.create_sql, change)
    if obj.ref.kind not in _GUARDED_KINDS or not obj.create_sql:
        return statement
    return (
        f"DO $confiture$\nBEGIN\n    {statement}"
        "EXCEPTION WHEN duplicate_object THEN NULL;\nEND\n$confiture$;\n"
    )


def _dropping(obj: DDLObject) -> str:
    """``DROP … IF EXISTS`` for *obj*: on its table where it is named per table."""
    if (on_table := drop_on_table(obj)) is not None:
        return f"{on_table};\n"
    return _drop(OBJECT_KEYWORD.get(obj.ref.kind, ""), obj.ref.qualified)


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
    """The table the schema declared: its columns, its constraints **and** its indexes.

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
    joined = ",\n    ".join(elements)
    body = f"(\n    {joined}\n)" if elements else "()"
    return (
        f"{warnings}CREATE TABLE IF NOT EXISTS {table.qualified} {body};\n{_table_indexes(table)}"
    )


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


def _retype(table: str, old: Column, new: Column) -> str:
    """``ALTER COLUMN … TYPE``, with ``USING`` where PostgreSQL has no assignment cast.

    Where it has one — within a family, or to a string type — the statement needs
    none, and must not have one: an explicit ``::varchar(50)`` truncates a value
    the assignment cast would refuse. Where it has none (``text`` → ``integer``),
    the statement fails without ``USING``, so the value is cast explicitly and a
    review line says the cast can fail on data.
    """
    before, after = column_type(old), column_type(new)
    statement = f"ALTER TABLE {table} ALTER COLUMN {old.folded} TYPE {after}"
    if has_assignment_cast(before, after):
        return f"{statement};\n"
    return (
        f"-- review: {before} to {after} has no assignment cast; each value is cast"
        " explicitly, and one that does not cast fails the migration\n"
        f"{statement} USING {old.folded}::{after};\n"
    )


def _column_up(change: ColumnChange) -> str:
    match change:
        case ColumnAdded(table, column):
            return f"ALTER TABLE {table} ADD COLUMN {column.folded} {column_body(column)};\n"
        case ColumnDropped(table, column):
            return f"ALTER TABLE {table} DROP COLUMN {column.folded};\n"
        case ColumnRenamed(table, old, new):
            return f"ALTER TABLE {table} RENAME COLUMN {old} TO {new};\n"
        case ColumnTypeChanged(table, old, new):
            return _retype(table, old, new)
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
        case ColumnTypeChanged(table, old, new):
            return _retype(table, new, old)
        case ColumnNullabilityChanged(table, column, nullable):
            return _nullability(table, column, nullable=not nullable)
        case ColumnDefaultChanged(table, column, old, _):
            return _default(table, column, old)
        case _:
            assert_never(change)


def _index_element(key: str, options: str) -> str:
    """One key of a ``CREATE INDEX``: a column bare, an expression in its own parentheses."""
    element = key if key.isidentifier() else f"({key})"
    return f"{element} {options}" if options else element


def _index_keys(index: Index) -> str:
    options = index.key_options or ("",) * len(index.columns)
    return ", ".join(_index_element(k, o) for k, o in zip(index.columns, options, strict=True))


def _index_statement(index: Index, table: str, *, concurrently: bool) -> str:
    """The index as declared: its access method, each key with its options, its predicate."""
    unique = "UNIQUE " if index.unique else ""
    how = "CONCURRENTLY " if concurrently else ""
    method = f" USING {index.method}" if index.method not in (None, "btree") else ""
    where = f" WHERE {index.where}" if index.where else ""
    return (
        f"CREATE {unique}INDEX {how}IF NOT EXISTS {index.name}"
        f" ON {table}{method} ({_index_keys(index)}){where};\n"
    )


def _create_index(change: IndexAdded | IndexDropped) -> str:
    """``CONCURRENTLY``: the table exists and is in use while the index builds."""
    if not change.index.name:
        return _unnamed(change, "index")
    return _index_statement(change.index, change.table, concurrently=True)


def _table_indexes(table: Table) -> str:
    """A table's own indexes, created with it: not ``CONCURRENTLY``, since it is empty.

    One PostgreSQL creates to back a constraint is not written: the constraint
    creates it. One the schema left unnamed cannot be created ``IF NOT EXISTS``,
    and a migration that re-applies would add it again, so it is named as missing.
    """
    written = []
    for index in table.indexes:
        if index.backs_constraint:
            continue
        if index.name:
            written.append(_index_statement(index, table.qualified, concurrently=False))
        else:
            written.append(
                f"-- WARNING: Cannot generate the index on {table.qualified}"
                f" ({_index_keys(index)}) without an index name\n"
            )
    return "".join(written)


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


_BIGINT_MIN, _BIGINT_MAX = -(2**63), 2**63 - 1


def _create_enum(enum: EnumType) -> str:
    labels = ", ".join(_quoted(v) for v in enum.values)
    return f"CREATE TYPE {enum.qualified} AS ENUM ({labels});\n"


def _create_sequence(sequence: Sequence) -> str:
    """``CREATE SEQUENCE IF NOT EXISTS`` with each option the model holds that is not the default.

    PostgreSQL's defaults depend on the direction: an ascending sequence runs from
    1 to the largest ``bigint``, a descending one from ``-1`` down to the smallest,
    and either starts at the end it runs from. The live reader fills every option
    in, so a default is recognised rather than written.
    """
    increment = 1 if sequence.increment is None else sequence.increment
    low, high = (1, _BIGINT_MAX) if increment > 0 else (_BIGINT_MIN, -1)
    minimum = low if sequence.min_value is None else sequence.min_value
    maximum = high if sequence.max_value is None else sequence.max_value
    start = minimum if increment > 0 else maximum
    options = [
        (f"INCREMENT BY {increment}", increment != 1),
        (f"MINVALUE {minimum}", minimum != low),
        (f"MAXVALUE {maximum}", maximum != high),
        (f"START WITH {sequence.start}", sequence.start not in (None, start)),
    ]
    written = "".join(f" {option}" for option, differs in options if differs)
    return f"CREATE SEQUENCE IF NOT EXISTS {sequence.qualified}{written};\n"


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
            return _create_enum(enum)
        case EnumTypeDropped(enum):
            return _drop("TYPE", enum.qualified)
        case EnumValuesChanged():
            return _enum_values(change)
        case SequenceAdded(sequence):
            return _create_sequence(sequence)
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
            return _creating(obj, change)
        case ObjectDropped(_, obj) if kind in DERIVED_KINDS:
            return _dropping(obj)
        case ObjectReplaced(_, _, new) if kind in _REPLACED_BY_DEFINITION:
            return _statement(new.create_sql, change)
        case ObjectReplaced(_, _, new) if kind in REPLACED_BY_DROP_AND_CREATE:
            return _drop(keyword, name) + _statement(new.create_sql, change)
        case ObjectAdded() | ObjectDropped() | ObjectReplaced():
            return None
        case _:
            assert_never(change)


def _enum_or_sequence_down(change: EnumOrSequenceChange) -> str | None:
    """A drop comes back from what the change carries; an added label cannot be taken back."""
    match change:
        case EnumTypeAdded(enum):
            return _drop("TYPE", enum.qualified)
        case EnumTypeDropped(enum):
            return _create_enum(enum)
        case EnumValuesChanged():
            return None
        case SequenceAdded(sequence):
            return _drop("SEQUENCE", sequence.qualified)
        case SequenceDropped(sequence):
            return _create_sequence(sequence)
        case _:
            assert_never(change)


def _definition_down(change: DefinitionChange) -> str | None:
    """A create is undone by a drop, a drop by the definition it carried, a replace by the old one."""
    kind = change.ref.kind
    keyword = OBJECT_KEYWORD.get(kind, "")
    name = change.ref.qualified
    match change:
        case ObjectAdded(_, obj) if kind in DERIVED_KINDS:
            return _dropping(obj)
        case ObjectDropped(_, obj) if kind in DERIVED_KINDS:
            return _creating(obj, change)
        case ObjectReplaced(_, old, _) if kind in _REPLACED_BY_DEFINITION:
            return _statement(old.create_sql, change)
        case ObjectReplaced(_, old, _) if kind in REPLACED_BY_DROP_AND_CREATE:
            return _drop(keyword, name) + _statement(old.create_sql, change)
        case ObjectAdded() | ObjectDropped() | ObjectReplaced():
            return None
        case _:
            assert_never(change)
