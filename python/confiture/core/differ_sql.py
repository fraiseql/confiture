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

A change the rows a table already holds can refuse — a ``NOT NULL`` column
nothing fills, ``SET NOT NULL``, an added UNIQUE, primary key or CHECK, a type the
values may not fit — is written around a ``-- confiture:backfill`` placeholder
(:mod:`confiture.core.backfill_gate`), never as a statement that fails on data.
"""

from dataclasses import replace
from typing import assert_never

from confiture.core import backfill_gate
from confiture.core.ddl_clauses import (
    column_element,
    column_type,
    index_element,
    named,
    relation,
)
from confiture.core.ddl_clauses import constraint_body as _clause
from confiture.core.ddl_objects import OBJECT_KEYWORD, DDLObject, drop_statement, output_columns
from confiture.core.schema_change import (
    CheckConstraintAdded,
    CheckConstraintDropped,
    ColumnAdded,
    ColumnChange,
    ColumnDefaultChanged,
    ColumnDropped,
    ColumnNotNullValidityChanged,
    ColumnNullabilityChanged,
    ColumnOrderChanged,
    ColumnRenamed,
    ColumnTypeChanged,
    DefinitionChange,
    Dependent,
    DependentsDropped,
    DependentsRecreated,
    EnumOrSequenceChange,
    EnumTypeAdded,
    EnumTypeDropped,
    EnumValuesChanged,
    ExclusionConstraintAdded,
    ExclusionConstraintDropped,
    ForeignKeyAdded,
    ForeignKeyDropped,
    IndexAdded,
    IndexDropped,
    ObjectAdded,
    ObjectDropped,
    ObjectReplaced,
    PrimaryKeyAdded,
    PrimaryKeyDropped,
    RebuildChange,
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
    primary_keys,
)
from confiture.core.schema_identity import quote_identifier
from confiture.core.schema_model import (
    Column,
    Constraint,
    EnumType,
    Index,
    RelationName,
    Sequence,
    Table,
    ValueSource,
)
from confiture.core.sql_utils import comment_text
from confiture.core.type_lattice import TypeChange, compare_types, has_assignment_cast
from confiture.exceptions import DifferError

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
        "tview",
    }
)

#: The derived kinds PostgreSQL gives no ``IF NOT EXISTS`` or ``OR REPLACE``: the
#: creating statement is guarded on ``duplicate_object``, so a file that may run
#: again over what it created does not fail on it. A table or a materialized view
#: is created plainly instead where the file runs in one transaction and the change
#: proves the relation new (:meth:`DifferSQLGenerator.creates`); everywhere else a
#: creation carries ``IF NOT EXISTS`` or ``OR REPLACE``.
_GUARDED_KINDS: frozenset[str] = frozenset({"domain", "type", "policy"})

#: The kinds whose redefinition is a statement confiture writes. Every other
#: ``REPLACE`` is in ``ddl_objects.REPLACE_IS_AUTHORS_WORK``, with its reason.
_REPLACED_BY_DEFINITION: frozenset[str] = frozenset({"view", "function", "procedure", "tview"})
REPLACED_BY_DROP_AND_CREATE: frozenset[str] = frozenset({"matview", "aggregate"})

#: The derived kinds a file that runs in one transaction creates with no
#: existence clause, when the change proves the relation new: a table is the
#: other relation, created by ``TableAdded`` and ``TableDropped``'s down.
PLAIN_CREATE_KINDS: frozenset[str] = frozenset({"matview"})


def _comment(text: str) -> str:
    """A ``--`` comment line holding *text*, which names objects: see :func:`comment_text`."""
    return f"-- {comment_text(text)}\n"


def _unnamed(change: SchemaChange, what: str) -> str:
    """The generator's "this changed, you write it" for a change with no object name.

    Never a fabricated ``idx_{table}`` / ``fk_{table}``: a name confiture made up
    is indistinguishable from one the author chose, and ``confiture drift`` then
    reports the divergence forever. Qualify the table and the invention stops even
    being a legal identifier (``idx_tenant.t``).
    """
    wire = change.to_wire()
    return _comment(f"WARNING: Cannot generate {wire.type} on {wire.table} without a {what} name")


def _incomplete(change: SchemaChange, what: str) -> str:
    """:func:`_unnamed`'s sibling, for a change that has a name but not a statement."""
    wire = change.to_wire()
    return _comment(f"WARNING: Cannot generate {wire.type} on {wire.table} without {what}")


_NO_STATEMENT_HINT = (
    "Generate from a side read from a tree (Side.of) or a database (database_side); "
    "a stated or slot side is compared, never generated from"
)


def _stated(obj: DDLObject, change: SchemaChange) -> str:
    """*obj*'s statement, the one every rendering of a definition change reads.

    A side that is compared and never generated from (``differ.stated_side``,
    ``differ.slot_side``) gives each object an empty statement. A change carrying
    one is refused here, whole and in either direction, rather than written as a
    migration that lacks it, or as a ``DROP`` with no ``CREATE`` after it.

    Raises:
        DifferError: ``DIFFER_409``, naming the change.
    """
    if obj.create_sql:
        return obj.create_sql
    raise DifferError(
        f"{change.to_wire().type} {comment_text(obj.ref.display)} carries no statement: "
        "the side it came from is compared, never generated from",
        error_code="DIFFER_409",
        resolution_hint=_NO_STATEMENT_HINT,
    )


def _statement(sql: str) -> str:
    """A statement, terminated."""
    return f"{sql.rstrip().rstrip(';')};\n"


def _creating(obj: DDLObject, change: SchemaChange, *, plain: bool) -> str:
    """The statement that creates *obj*: re-appliable, or plain where it is asked and can be.

    A materialized view asked for *plain* is its ``definition``, which is the
    statement with no existence clause; every other kind is re-appliable either
    way, guarded where PostgreSQL has no clause.
    """
    stated = _stated(obj, change)
    if _creates_plainly(obj, plain=plain):
        return _statement(obj.definition)
    statement = _statement(stated)
    if obj.ref.kind not in _GUARDED_KINDS:
        return statement
    return (
        f"DO $confiture$\nBEGIN\n    {statement}"
        "EXCEPTION WHEN duplicate_object THEN NULL;\nEND\n$confiture$;\n"
    )


def _creates_plainly(obj: DDLObject, *, plain: bool) -> bool:
    """Whether *obj* is created with no existence clause: a matview, asked, with a definition."""
    return plain and obj.ref.kind in PLAIN_CREATE_KINDS and bool(obj.definition)


def _replacing(before: DDLObject, after: DDLObject, change: SchemaChange) -> str:
    """*after*'s definition over *before*'s: in place where PostgreSQL allows it.

    ``CREATE OR REPLACE VIEW`` keeps a view's columns and may only add some at the
    end; one removed or renamed is refused. A view whose columns do not extend
    the old ones is dropped and created instead. When either side's columns
    cannot be named (``*``), ``OR REPLACE`` is kept: PostgreSQL decides.
    """
    statement = _statement(_stated(after, change))
    if after.ref.kind != "view":
        return statement
    _stated(before, change)
    old, new = output_columns(before), output_columns(after)
    if old is None or new is None or new[: len(old)] == old:
        return statement
    return (
        _comment(
            f"review: {after.ref.qualified}'s columns change ({', '.join(old)} → "
            f"{', '.join(new)}), which CREATE OR REPLACE VIEW refuses; it is dropped and "
            "created, so its grants and comment go, and a dependent view fails the DROP"
        )
        + _drop("VIEW", after.ref.qualified)
        + statement
    )


def _dropping(obj: DDLObject, change: SchemaChange) -> str:
    """``DROP … IF EXISTS`` for *obj*: on its table where it is named per table.

    A TVIEW is dropped by name; every other kind reads its statement, which names
    the table a trigger, a policy or a rule is dropped on.
    """
    if obj.ref.kind != "tview":
        _stated(obj, change)
    if (statement := drop_statement(obj)) is not None:
        return f"{statement};\n"
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
    a composite one has somewhere to go, under the name the schema gave it: a
    later ``DROP CONSTRAINT`` names it. A constraint that says nothing — a CHECK
    with no expression, any other with no column — is not written at all.
    """
    listed = [
        *primary_keys(table),
        *table.constraints_of("foreign_key"),
        *table.constraints_of("unique"),
        *table.constraints_of("check"),
        *table.constraints_of("exclusion"),
    ]
    return [c for c in listed if (c.expression if c.kind == "check" else c.columns)]


def _create_table(table: Table, *, plain: bool) -> str:
    """The table the schema declared: its columns, its constraints **and** its indexes.

    A constraint the schema left unnamed is written unnamed, exactly as the
    author wrote it; PostgreSQL generates the name either way. *plain* writes
    ``CREATE TABLE`` without ``IF NOT EXISTS``: see :meth:`DifferSQLGenerator.creates`.
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
    create = "CREATE TABLE" if plain else "CREATE TABLE IF NOT EXISTS"
    return f"{warnings}{create} {relation(table.relation)} {body};\n{_table_indexes(table)}"


def _table_up(change: TableChange, *, plain: bool) -> str | None:
    match change:
        case TableAdded(table):
            return _create_table(table, plain=plain)
        case TableDropped(table):
            return f"DROP TABLE {relation(table.relation)};\n"
        case TableRenamed(old, new):
            # `ALTER TABLE a.t RENAME TO a.t2` is a syntax error: the target is a bare name.
            return f"ALTER TABLE {relation(old.relation)} RENAME TO {quote_identifier(new.name)};\n"
        case _:
            assert_never(change)


def _table_down(change: TableChange, *, plain: bool) -> str | None:
    match change:
        case TableAdded(table):
            return f"DROP TABLE {relation(table.relation)};\n"
        case TableDropped(table):
            return _create_table(table, plain=plain) if table.columns else None
        case TableRenamed(old, new):
            return f"ALTER TABLE {relation(new.relation)} RENAME TO {quote_identifier(old.name)};\n"
        case _:
            assert_never(change)


def _target(table: RelationName, column: str) -> str:
    return f"{relation(table)}.{quote_identifier(column)}"


def _not_null_check(table: RelationName, column: str) -> str:
    """The CHECK that proves a column holds no NULL.

    Not ``<table>_<column>_not_null``: PostgreSQL 18 gives the column's own NOT NULL
    constraint that name, and dropping the CHECK by it would read as dropping that.
    """
    return f"{table.name}_{column}_not_null_check"


def _add_not_valid(table: RelationName, name: str, body: str) -> str:
    """``ADD CONSTRAINT … NOT VALID``, after the same name dropped if it exists, then ``VALIDATE``.

    A file that runs outside a transaction commits each statement: when the
    ``VALIDATE`` fails on a row, the ``ADD`` has committed, and the run that
    follows the fix would fail on it. PostgreSQL has no ``ADD CONSTRAINT IF NOT
    EXISTS``; the drop before it is the change set's replacement, paired as written
    (#785).
    """
    target, constraint = relation(table), quote_identifier(name)
    return (
        f"ALTER TABLE {target} DROP CONSTRAINT IF EXISTS {constraint};\n"
        f"ALTER TABLE {target} ADD {named(name, body)} NOT VALID;\n"
        f"ALTER TABLE {target} VALIDATE CONSTRAINT {constraint};\n"
    )


def _tighten(table: RelationName, column: str) -> str:
    """``SET NOT NULL`` once a validated CHECK has proven it, then the CHECK dropped.

    expand/contract's ``add_not_null_column`` contract: on PostgreSQL 12+ the
    ``SET NOT NULL`` reads the validated CHECK instead of scanning the table.
    """
    target, check = relation(table), _not_null_check(table, column)
    return (
        _add_not_valid(table, check, f"CHECK ({quote_identifier(column)} IS NOT NULL)")
        + _nullability(table, column, nullable=False)
        + f"ALTER TABLE {target} DROP CONSTRAINT {quote_identifier(check)};\n"
    )


def _placeholder_for_nulls(table: RelationName, column: str) -> str:
    rows = f"the rows of {relation(table)} where {quote_identifier(column)} is NULL"
    return backfill_gate.placeholder(_target(table, column), rows)


def _fill_then_tighten(table: RelationName, column: str) -> str:
    return _placeholder_for_nulls(table, column) + _tighten(table, column)


def _filled_by_nothing(column: Column) -> bool:
    """A ``NOT NULL`` column PostgreSQL gives no value to when it is added to a table with rows."""
    return (
        column.not_null
        and column.not_null_validated
        and not column.primary_key
        and column.value_source is ValueSource.NONE
    )


def _add_column(table: RelationName, column: Column) -> str:
    """``ADD COLUMN``; a ``NOT NULL`` one nothing fills is added nullable, filled, then tightened.

    The nullable column is added ``IF NOT EXISTS``: when the tightening fails on a
    row outside a transaction, the run after the fix meets the column (#785).
    """
    if not _filled_by_nothing(column):
        return f"ALTER TABLE {relation(table)} ADD COLUMN {column_element(column)};\n"
    nullable = replace(column, not_null=False)
    return (
        f"ALTER TABLE {relation(table)} ADD COLUMN IF NOT EXISTS {column_element(nullable)};\n"
        + (_fill_then_tighten(table, column.folded))
    )


def _nullability(table: RelationName, column: str, *, nullable: bool) -> str:
    verb = "DROP" if nullable else "SET"
    return (
        f"ALTER TABLE {relation(table)} ALTER COLUMN {quote_identifier(column)} {verb} NOT NULL;\n"
    )


def _not_null_validity(table: RelationName, column: str, *, validated: bool) -> str:
    """A NOT NULL validated, or held ``NOT VALID`` again (PostgreSQL 18).

    ``SET NOT NULL`` validates a ``NOT VALID`` one: it scans the table, and fails
    on a NULL. No statement un-validates a constraint, so the other way drops the
    NOT NULL and adds it back ``NOT VALID``, under the name PostgreSQL chooses.
    """
    if validated:
        return _nullability(table, column, nullable=False)
    return _nullability(table, column, nullable=True) + (
        f"ALTER TABLE {relation(table)} ADD NOT NULL {quote_identifier(column)} NOT VALID;\n"
    )


def _default(table: RelationName, column: str, default: str | None) -> str:
    clause = f"SET DEFAULT {default}" if default else "DROP DEFAULT"
    return f"ALTER TABLE {relation(table)} ALTER COLUMN {quote_identifier(column)} {clause};\n"


def _retype(table: RelationName, old: Column, new: Column) -> str:
    """``ALTER COLUMN … TYPE``, with ``USING`` where PostgreSQL has no assignment cast.

    Where it has one — within a family, or to a string type — the statement needs
    none, and must not have one: an explicit ``::varchar(50)`` truncates a value
    the assignment cast would refuse. Where it has none (``text`` → ``integer``),
    the statement fails without ``USING``, so the value is cast explicitly and a
    review line says the cast can fail on data.
    """
    before, after = column_type(old), column_type(new)
    name = quote_identifier(old.folded)
    statement = f"ALTER TABLE {relation(table)} ALTER COLUMN {name} TYPE {after}"
    if has_assignment_cast(before, after):
        return f"{statement};\n"
    return (
        _comment(
            f"review: {before} to {after} has no assignment cast; each value is cast"
            " explicitly, and one that does not cast fails the migration"
        )
        + f"{statement} USING {name}::{after};\n"
    )


def _values_may_not_fit(table: RelationName, old: Column, new: Column) -> str:
    """The placeholder before a retype a value can fail: a narrowing, or a cast that is not assignment."""
    before, after = column_type(old), column_type(new)
    if compare_types(old.type_key, new.type_key) is not TypeChange.NARROWING and (
        has_assignment_cast(before, after)
    ):
        return ""
    rows = (
        f"the rows of {relation(table)} whose {quote_identifier(old.folded)} does not fit {after}"
    )
    return backfill_gate.placeholder(_target(table, old.folded), rows)


def _column_up(change: ColumnChange) -> str | None:
    match change:
        case ColumnAdded(table, column):
            return _add_column(table, column)
        case ColumnDropped(table, column):
            return f"ALTER TABLE {relation(table)} DROP COLUMN {quote_identifier(column.folded)};\n"
        case ColumnRenamed(table, old, new):
            return f"ALTER TABLE {relation(table)} RENAME COLUMN {quote_identifier(old)} TO {quote_identifier(new)};\n"
        case ColumnTypeChanged(table, old, new):
            return _values_may_not_fit(table, old, new) + _retype(table, old, new)
        case ColumnNullabilityChanged(table, column, nullable):
            return (
                _nullability(table, column, nullable=True)
                if nullable
                else _fill_then_tighten(table, column)
            )
        case ColumnNotNullValidityChanged(table, column, validated):
            fill = _placeholder_for_nulls(table, column) if validated else ""
            return fill + _not_null_validity(table, column, validated=validated)
        case ColumnDefaultChanged(table, column, _, new):
            return _default(table, column, new)
        case ColumnOrderChanged():
            return None
        case _:
            assert_never(change)


def _column_down(change: ColumnChange) -> str | None:
    """The reverse of each column change; a dropped column comes back, its rows do not."""
    match change:
        case ColumnAdded(table, column):
            return f"ALTER TABLE {relation(table)} DROP COLUMN {quote_identifier(column.folded)};\n"
        case ColumnDropped(table, column):
            return f"ALTER TABLE {relation(table)} ADD COLUMN {column_element(column)};\n"
        case ColumnRenamed(table, old, new):
            return f"ALTER TABLE {relation(table)} RENAME COLUMN {quote_identifier(new)} TO {quote_identifier(old)};\n"
        case ColumnTypeChanged(table, old, new):
            return _retype(table, new, old)
        case ColumnNullabilityChanged(table, column, nullable):
            return _nullability(table, column, nullable=not nullable)
        case ColumnNotNullValidityChanged(table, column, validated):
            return _not_null_validity(table, column, validated=not validated)
        case ColumnDefaultChanged(table, column, old, _):
            return _default(table, column, old)
        case ColumnOrderChanged():
            return None
        case _:
            assert_never(change)


def _index_keys(index: Index) -> str:
    options = index.key_options or ("",) * len(index.columns)
    kinds = index.expressions or (None,) * len(index.columns)
    return ", ".join(
        index_element(key, option, expression)
        for key, option, expression in zip(index.columns, options, kinds, strict=True)
    )


def _index_statement(index: Index, table: str, *, concurrently: bool) -> str:
    """The index as declared: its access method, each key with its options, its predicate."""
    unique = "UNIQUE " if index.unique else ""
    how = "CONCURRENTLY " if concurrently else ""
    method = f" USING {index.method}" if index.method not in (None, "btree") else ""
    nulls = " NULLS NOT DISTINCT" if index.nulls_not_distinct else ""
    where = f" WHERE {index.where}" if index.where else ""
    return (
        f"CREATE {unique}INDEX {how}IF NOT EXISTS {quote_identifier(index.name or '')}"
        f" ON {table}{method} ({_index_keys(index)}){nulls}{where};\n"
    )


def _undeclared(change: IndexAdded | IndexDropped) -> str:
    """The comment above an index on a table neither tree declares (#679): it assumes the table."""
    if change.table_declared:
        return ""
    return _comment(
        f"{change.table.qualified} is not declared in this schema: the index assumes it exists"
    )


def _create_index(change: IndexAdded | IndexDropped) -> str:
    """``CONCURRENTLY``: the table exists and is in use while the index builds."""
    if not change.index.name:
        return _unnamed(change, "index")
    statement = _index_statement(change.index, relation(change.table), concurrently=True)
    return _undeclared(change) + statement


def _table_indexes(table: Table) -> str:
    """A table's own indexes, created with it: see :func:`_relation_indexes`."""
    return _relation_indexes(table.relation, table.indexes)


def _relation_indexes(relation_name: RelationName, indexes: tuple[Index, ...]) -> str:
    """A relation's own indexes, created with it: not ``CONCURRENTLY``, since nobody reads it yet.

    A table, a materialized view or a TVIEW this migration creates — or drops and
    creates again, under the ``DROP``'s lock. One PostgreSQL creates to back a constraint is
    not written: the constraint creates it. One the schema left unnamed cannot be
    created ``IF NOT EXISTS``, and a migration that re-applies would add it again,
    so it is named as missing.
    """
    written = []
    for index in indexes:
        if index.backs_constraint:
            continue
        if index.name:
            written.append(_index_statement(index, relation(relation_name), concurrently=False))
        else:
            written.append(
                _comment(
                    f"WARNING: Cannot generate the index on {relation_name.qualified}"
                    f" ({_index_keys(index)}) without an index name"
                )
            )
    return "".join(written)


def _carried_indexes(indexes: tuple[Index, ...]) -> str:
    """The indexes a materialized view's or a TVIEW's change carries, created right after it."""
    return _relation_indexes(indexes[0].table, indexes) if indexes else ""


def _drop_index(change: IndexAdded | IndexDropped) -> str:
    if not change.index.name:
        return _unnamed(change, "index")
    # An index is in its table's schema, and a bare name would drop nothing there.
    index = relation(RelationName(change.table.schema, change.index.name))
    return f"{_undeclared(change)}DROP INDEX CONCURRENTLY IF EXISTS {index};\n"


def _add_foreign_key(change: ForeignKeyAdded | ForeignKeyDropped) -> str:
    """``NOT VALID`` then ``VALIDATE``, which needs a name — or one statement.

    The second step names the constraint. Run apart, the ``ADD`` takes a brief
    ``SHARE ROW EXCLUSIVE`` lock and the scan blocks no writer; in one transaction
    — a migration's default — the scan holds the ``ADD``'s lock, so writes on both
    tables wait for it, which the tier says (``lock_risky``). An unnamed foreign key
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
            f"ALTER TABLE {relation(change.table)} ADD {clause};"
            " -- review: unnamed in the schema, so it cannot be added NOT VALID and"
            " validated separately; this scans the table under a lock\n"
        )
    return (
        f"ALTER TABLE {relation(change.table)} ADD {clause} NOT VALID;\n"
        f"ALTER TABLE {relation(change.table)} VALIDATE CONSTRAINT {quote_identifier(name)};\n"
    )


def _add_constraint(
    change: CheckConstraintAdded
    | CheckConstraintDropped
    | UniqueConstraintAdded
    | PrimaryKeyAdded
    | UniqueConstraintDropped
    | PrimaryKeyDropped
    | ExclusionConstraintAdded
    | ExclusionConstraintDropped,
    missing: str,
) -> str:
    body = _clause(change.constraint)
    if body is None:
        return _incomplete(change, missing)
    return f"ALTER TABLE {relation(change.table)} ADD {named(change.constraint.name, body)};\n"


def _key_columns(constraint: Constraint) -> str:
    return "(" + ", ".join(quote_identifier(c) for c in constraint.columns) + ")"


def _constraint_target(table: RelationName, constraint: Constraint) -> str:
    """``tb_user.k`` for a named constraint; ``tb_user (a, b)`` or ``tb_user`` for an unnamed one."""
    if constraint.name:
        return _target(table, constraint.name)
    return (
        f"{relation(table)} {_key_columns(constraint)}" if constraint.columns else relation(table)
    )


def _rows_may_repeat(change: UniqueConstraintAdded | PrimaryKeyAdded) -> str:
    """The placeholder before a key is added: the rows whose key repeats (or, for a primary key, is NULL)."""
    if _clause(change.constraint) is None:
        return _add_constraint(change, "a column list")
    keys = _key_columns(change.constraint)
    rows = f"the rows of {relation(change.table)} whose {keys} repeats"
    if isinstance(change, PrimaryKeyAdded):
        rows += " or holds a NULL"
    return backfill_gate.placeholder(
        _constraint_target(change.table, change.constraint), rows
    ) + _add_constraint(change, "a column list")


def _add_check(change: CheckConstraintAdded) -> str:
    """The placeholder, then the CHECK added ``NOT VALID`` and validated — one statement when unnamed."""
    body = _clause(change.constraint)
    if body is None:
        return _incomplete(change, "a CHECK expression")
    name = change.constraint.name
    rows = f"the rows of {relation(change.table)} that fail {body}"
    fill = backfill_gate.placeholder(_constraint_target(change.table, change.constraint), rows)
    if not name:
        return fill + f"ALTER TABLE {relation(change.table)} ADD {body};\n"
    return fill + _add_not_valid(change.table, name, body)


def _drop_constraint(
    change: ForeignKeyAdded
    | ForeignKeyDropped
    | CheckConstraintAdded
    | CheckConstraintDropped
    | UniqueConstraintAdded
    | PrimaryKeyAdded
    | UniqueConstraintDropped
    | PrimaryKeyDropped
    | ExclusionConstraintAdded
    | ExclusionConstraintDropped,
) -> str:
    if not change.constraint.name:
        return _unnamed(change, "constraint")
    return f"ALTER TABLE {relation(change.table)} DROP CONSTRAINT IF EXISTS {quote_identifier(change.constraint.name)};\n"


def _table_object_up(change: TableObjectChange) -> str:
    match change:
        case IndexAdded():
            return _create_index(change)
        case IndexDropped():
            return _drop_index(change)
        case ForeignKeyAdded():
            return _add_foreign_key(change)
        case CheckConstraintAdded():
            return _add_check(change)
        case UniqueConstraintAdded() | PrimaryKeyAdded():
            return _rows_may_repeat(change)
        case ExclusionConstraintAdded():
            return _add_constraint(change, "its elements")
        case (
            ForeignKeyDropped()
            | CheckConstraintDropped()
            | UniqueConstraintDropped()
            | PrimaryKeyDropped()
            | ExclusionConstraintDropped()
        ):
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
        case UniqueConstraintDropped() | PrimaryKeyDropped():
            return _add_constraint(change, "a column list")
        case ExclusionConstraintDropped():
            return _add_constraint(change, "its elements")
        case (
            ForeignKeyAdded()
            | CheckConstraintAdded()
            | UniqueConstraintAdded()
            | PrimaryKeyAdded()
            | ExclusionConstraintAdded()
        ):
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
            _comment(
                f"WARNING: Removing enum values ({removed}) from {name}"
                " requires DROP + RECREATE. Edit this migration manually."
            )
        )
    return "".join(parts) if parts else _comment(f"No enum value changes for {name}")


_BIGINT_MIN, _BIGINT_MAX = -(2**63), 2**63 - 1


def _create_enum(enum: EnumType) -> str:
    labels = ", ".join(_quoted(v) for v in enum.values)
    return f"CREATE TYPE {relation(RelationName(enum.schema, enum.name))} AS ENUM ({labels});\n"


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
    name = relation(RelationName(sequence.schema, sequence.name))
    return f"CREATE SEQUENCE IF NOT EXISTS {name}{written};\n"


class DifferSQLGenerator:
    """Generates the DDL for a schema change, up and down."""

    def generate_up(self, change: SchemaChange, *, plain_creates: bool = False) -> str | None:
        """The forward DDL for *change*, or ``None`` when none is derived.

        *plain_creates* writes a relation the change creates without ``IF NOT
        EXISTS``: see :meth:`creates`.
        """
        match change:
            case TableAdded() | TableDropped() | TableRenamed():
                return _table_up(change, plain=plain_creates)
            case (
                ColumnAdded()
                | ColumnDropped()
                | ColumnRenamed()
                | ColumnTypeChanged()
                | ColumnNullabilityChanged()
                | ColumnNotNullValidityChanged()
                | ColumnDefaultChanged()
                | ColumnOrderChanged()
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
                | PrimaryKeyAdded()
                | UniqueConstraintDropped()
                | PrimaryKeyDropped()
                | ExclusionConstraintAdded()
                | ExclusionConstraintDropped()
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
                return _definition_up(change, plain=plain_creates)
            case DependentsDropped() | DependentsRecreated():
                return _rebuild_up(change, plain=plain_creates)
            case _:
                assert_never(change)

    def generate_down(self, change: SchemaChange, *, plain_creates: bool = False) -> str | None:
        """The DDL that undoes *change*, or ``None`` when no rollback is derived.

        *plain_creates* as for :meth:`generate_up`.
        """
        match change:
            case TableAdded() | TableDropped() | TableRenamed():
                return _table_down(change, plain=plain_creates)
            case (
                ColumnAdded()
                | ColumnDropped()
                | ColumnRenamed()
                | ColumnTypeChanged()
                | ColumnNullabilityChanged()
                | ColumnNotNullValidityChanged()
                | ColumnDefaultChanged()
                | ColumnOrderChanged()
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
                | PrimaryKeyAdded()
                | UniqueConstraintDropped()
                | PrimaryKeyDropped()
                | ExclusionConstraintAdded()
                | ExclusionConstraintDropped()
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
                return _definition_down(change, plain=plain_creates)
            case DependentsDropped() | DependentsRecreated():
                return _rebuild_down(change, plain=plain_creates)
            case _:
                assert_never(change)

    def creates(
        self, change: SchemaChange, *, down: bool = False, plain_creates: bool = False
    ) -> tuple[str, ...]:
        """The relations *change*'s up (or *down*) creates plainly, each as it is spelled.

        A file that runs in one transaction creates a table or a materialized
        view the change proves new with no ``IF NOT EXISTS``: PostgreSQL then
        proves it new, and a failure rolls the whole file back. One that does
        not — a concurrent index, an enum label — keeps the clause, because a
        failed file is run again from the top. The generator decides which, for
        the file, and asks for *plain_creates*; without it nothing is created
        plainly and this is ``()``. Each name is the created object's own
        spelling, which the generator declares above the change.
        """
        if not plain_creates:
            return ()
        match change:
            case TableAdded() | TableDropped() | TableRenamed():
                return _table_creates(change, down=down)
            case ObjectAdded() | ObjectDropped() | ObjectReplaced():
                return _definition_creates(change, down=down)
            case DependentsDropped() | DependentsRecreated():
                return _rebuild_creates(change, down=down)
            case (
                ColumnAdded()
                | ColumnDropped()
                | ColumnRenamed()
                | ColumnTypeChanged()
                | ColumnNullabilityChanged()
                | ColumnNotNullValidityChanged()
                | ColumnDefaultChanged()
                | ColumnOrderChanged()
                | IndexAdded()
                | IndexDropped()
                | ForeignKeyAdded()
                | ForeignKeyDropped()
                | CheckConstraintAdded()
                | CheckConstraintDropped()
                | UniqueConstraintAdded()
                | PrimaryKeyAdded()
                | UniqueConstraintDropped()
                | PrimaryKeyDropped()
                | ExclusionConstraintAdded()
                | ExclusionConstraintDropped()
                | EnumTypeAdded()
                | EnumTypeDropped()
                | EnumValuesChanged()
                | SequenceAdded()
                | SequenceDropped()
            ):
                return ()
            case _:
                assert_never(change)


def _table_creates(change: TableChange, *, down: bool) -> tuple[str, ...]:
    match change:
        case TableAdded(table) if not down:
            return (relation(table.relation),)
        case TableDropped(table) if down and table.columns:
            return (relation(table.relation),)
        case TableAdded() | TableDropped() | TableRenamed():
            return ()
        case _:
            assert_never(change)


def _definition_creates(change: DefinitionChange, *, down: bool) -> tuple[str, ...]:
    """The object the change's up or down creates, when it creates it plainly."""
    kind = change.ref.kind
    match change:
        case ObjectAdded(_, obj) if not down and kind in DERIVED_KINDS:
            created = obj
        case ObjectDropped(_, obj) if down and kind in DERIVED_KINDS:
            created = obj
        case ObjectReplaced(_, old, new) if kind in REPLACED_BY_DROP_AND_CREATE:
            created = old if down else new
        case ObjectAdded() | ObjectDropped() | ObjectReplaced():
            return ()
        case _:
            assert_never(change)
    return (created.ref.qualified,) if _creates_plainly(created, plain=True) else ()


def _rebuild_creates(change: RebuildChange, *, down: bool) -> tuple[str, ...]:
    """The dependents the change's up (recreated) or down (dropped) creates plainly."""
    match change:
        case DependentsRecreated(dependents) if not down:
            created = dependents
        case DependentsDropped(dependents) if down:
            created = dependents
        case DependentsDropped() | DependentsRecreated():
            return ()
        case _:
            assert_never(change)
    return tuple(d.ref.qualified for d in created if _creates_plainly(d.obj, plain=True))


def _dropping_dependents(dependents: tuple[Dependent, ...], change: RebuildChange) -> str:
    """Each dependent dropped, the ones reading the others first."""
    names = ", ".join(d.ref.qualified for d in dependents)
    return _comment(f"Read by a column change PostgreSQL refuses under them: {names}") + "".join(
        _dropping(d.obj, change) for d in reversed(dependents)
    )


def _creating_dependents(
    dependents: tuple[Dependent, ...], change: RebuildChange, *, plain: bool
) -> str:
    """Each dependent created, after the ones it reads, with its indexes and what it carried."""
    return "".join(
        _creating(d.obj, change, plain=plain) + _carried_indexes(d.indexes) + "".join(d.attached)
        for d in dependents
    )


def _rebuild_up(change: RebuildChange, *, plain: bool) -> str:
    """Dropped from the old tree before the tables are edited; created from the new one after."""
    match change:
        case DependentsDropped(dependents):
            return _dropping_dependents(dependents, change)
        case DependentsRecreated(dependents):
            return _creating_dependents(dependents, change, plain=plain)
        case _:
            assert_never(change)


def _rebuild_down(change: RebuildChange, *, plain: bool) -> str:
    """The up in reverse: the new tree's dropped, the old tree's created again."""
    match change:
        case DependentsDropped(dependents):
            return _creating_dependents(dependents, change, plain=plain)
        case DependentsRecreated(dependents):
            return _dropping_dependents(dependents, change)
        case _:
            assert_never(change)


def _enum_or_sequence_up(change: EnumOrSequenceChange) -> str:
    match change:
        case EnumTypeAdded(enum):
            return _create_enum(enum)
        case EnumTypeDropped(enum):
            return _drop("TYPE", relation(RelationName(enum.schema, enum.name)))
        case EnumValuesChanged():
            return _enum_values(change)
        case SequenceAdded(sequence):
            return _create_sequence(sequence)
        case SequenceDropped(sequence):
            return _drop("SEQUENCE", relation(RelationName(sequence.schema, sequence.name)))
        case _:
            assert_never(change)


def _definition_up(change: DefinitionChange, *, plain: bool) -> str | None:
    kind = change.ref.kind
    keyword = OBJECT_KEYWORD.get(kind, "")
    name = change.ref.qualified
    match change:
        case ObjectAdded(_, obj, indexes) if kind in DERIVED_KINDS:
            return _creating(obj, change, plain=plain) + _carried_indexes(indexes)
        case ObjectDropped(_, obj) if kind in DERIVED_KINDS:
            return _dropping(obj, change)
        case ObjectReplaced(_, old, new) if kind in _REPLACED_BY_DEFINITION:
            return _replacing(old, new, change)
        case ObjectReplaced(new=new, new_indexes=indexes) if kind in REPLACED_BY_DROP_AND_CREATE:
            created = _creating(new, change, plain=plain) + _carried_indexes(indexes)
            return _drop(keyword, name) + created
        case ObjectAdded() | ObjectDropped() | ObjectReplaced():
            return None
        case _:
            assert_never(change)


def _enum_or_sequence_down(change: EnumOrSequenceChange) -> str | None:
    """A drop comes back from what the change carries; an added label cannot be taken back."""
    match change:
        case EnumTypeAdded(enum):
            return _drop("TYPE", relation(RelationName(enum.schema, enum.name)))
        case EnumTypeDropped(enum):
            return _create_enum(enum)
        case EnumValuesChanged():
            return None
        case SequenceAdded(sequence):
            return _drop("SEQUENCE", relation(RelationName(sequence.schema, sequence.name)))
        case SequenceDropped(sequence):
            return _create_sequence(sequence)
        case _:
            assert_never(change)


def _definition_down(change: DefinitionChange, *, plain: bool) -> str | None:
    """A create is undone by a drop, a drop by the definition it carried, a replace by the old one."""
    kind = change.ref.kind
    keyword = OBJECT_KEYWORD.get(kind, "")
    name = change.ref.qualified
    match change:
        case ObjectAdded(_, obj) if kind in DERIVED_KINDS:
            return _dropping(obj, change)
        case ObjectDropped(_, obj, indexes) if kind in DERIVED_KINDS:
            return _creating(obj, change, plain=plain) + _carried_indexes(indexes)
        case ObjectReplaced(_, old, new) if kind in _REPLACED_BY_DEFINITION:
            return _replacing(new, old, change)
        case ObjectReplaced(old=old, old_indexes=indexes) if kind in REPLACED_BY_DROP_AND_CREATE:
            created = _creating(old, change, plain=plain) + _carried_indexes(indexes)
            return _drop(keyword, name) + created
        case ObjectAdded() | ObjectDropped() | ObjectReplaced():
            return None
        case _:
            assert_never(change)
