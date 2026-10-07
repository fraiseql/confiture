"""Which tables the tree tombstones: writes a value other than ``NULL`` to the soft-delete column.

``soft_delete: {tables: written}`` (#640) judges a table as soft-deleting when some
statement of the tree marks one of its rows deleted, not merely when the table
carries the column — a tree that puts the audit columns on every table has it on
reference tables nothing ever deletes.

A write is ``SET <column> = <value>`` where *value* is anything but ``NULL`` (cast
or not) and ``DEFAULT``: ``now()``, ``CURRENT_TIMESTAMP``, a variable, a parameter,
``EXCLUDED.<column>`` all mark a row deleted. It is read wherever PostgreSQL updates a
row: ``UPDATE`` (in a CTE, with ``FROM``, ``SET (a, b) = (…)``), ``INSERT … ON
CONFLICT DO UPDATE``, ``MERGE … UPDATE``, a ``CREATE RULE``'s action — at the top
level of a file and in every function and procedure body
(:func:`~confiture.core.linting.references.routine_bodies`: PL/pgSQL, ``LANGUAGE
sql``, ``BEGIN ATOMIC``). An ``UPDATE`` without ``ONLY`` writes a partitioned
table's partitions too.

The target is matched as ``build_003`` matches a reference: a name without a schema
matches the table in any schema. Over-marking is the safe direction — a table judged
that never deletes costs a finding, one missed hides one. What cannot be read — a
body the compiler refuses, a statement pglast rejects, an ``EXECUTE`` built at run
time — is *undecided*, named in the rule's ``degraded`` status, never taken as
"writes nothing". A trigger function that assigns ``NEW.<column>`` is not read.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from confiture.core._pglast_enums import member as _pg_member
from confiture.core.ddl_walk import enum_int, walk_nodes
from confiture.core.linting.inventory import Inventory, SchemaObject
from confiture.core.linting.references import RoutineBody, routine_bodies
from confiture.core.schema_identity import identifier_identity
from confiture.core.sql_lexer import ParsedFile

_CMD_UPDATE = _pg_member("CmdType", "CMD_UPDATE")

#: A table, as the softdel rules key it: its folded schema (``None`` when unwritten) and name.
TableKey = tuple[str | None, str]


@dataclass(frozen=True)
class Tombstoned:
    """The tables the tree marks rows of deleted, and what could not be read to say so.

    Attributes:
        tables: Each table some statement tombstones.
        undecided: One line per routine whose body, or a statement in it, could not
            be read: whether it tombstones a table is not known.
    """

    tables: frozenset[TableKey]
    undecided: tuple[str, ...]


def key_of(table: SchemaObject) -> TableKey:
    """The key :attr:`Tombstoned.tables` holds *table* under."""
    return (table.folded_schema, table.folded_name)


def _is_null(value: Any) -> bool:
    """Whether *value* writes ``NULL``: the constant, cast or not, or ``DEFAULT``."""
    kind = type(value).__name__
    if kind == "TypeCast":
        return _is_null(value.arg)
    return kind == "SetToDefault" or (kind == "A_Const" and bool(value.isnull))


def _value(target: Any) -> Any:
    """The expression a ``SET`` target is given; for ``SET (a, b) = (…)``, its own element."""
    value = target.val
    if type(value).__name__ != "MultiAssignRef":
        return value
    source = value.source
    if type(source).__name__ == "RowExpr" and source.args:
        return source.args[value.colno - 1]
    return source  # a sub-select: some value, read as one


def _writes(targets: Sequence[Any] | None, column: str) -> bool:
    """Whether a ``SET`` list gives *column* a value other than ``NULL``."""
    return any(
        target.name is not None
        and identifier_identity(target.name) == column
        and not _is_null(_value(target))
        for target in targets or ()
    )


def _written_relations(root: Any, column: str) -> Iterator[Any]:
    """The ``RangeVar`` of every relation a statement tombstones, nested statements included."""
    for node in walk_nodes(root):
        kind = type(node).__name__
        if kind == "UpdateStmt" and _writes(node.targetList, column):
            yield node.relation
        elif kind == "InsertStmt" and node.onConflictClause is not None:
            if _writes(node.onConflictClause.targetList, column):
                yield node.relation
        elif kind == "MergeStmt" and any(
            enum_int(clause.commandType) == _CMD_UPDATE and _writes(clause.targetList, column)
            for clause in node.mergeWhenClauses or ()
        ):
            yield node.relation


def _tables(inventory: Inventory, relation: Any) -> Iterator[SchemaObject]:
    """The tables a written ``RangeVar`` names, and — without ``ONLY`` — their partitions."""
    for table in inventory.find_all(("table",), relation.schemaname, relation.relname):
        yield table
        if relation.inh:
            yield from (
                child
                for child in inventory.tables
                if child.parent is not None
                and identifier_identity(child.parent.name) == table.folded_name
                and child.parent.schema in (None, table.folded_schema)
            )


def _undecided(body: RoutineBody) -> str | None:
    """What of *body* was not read, in one line, or ``None`` when all of it was."""
    reasons = []
    if body.refused is not None:
        reasons.append(f"its body could not be read ({body.refused})")
    if body.dynamic:
        reasons.append(f"{len(body.dynamic)} EXECUTE built at run time")
    if body.unread:
        reasons.append(f"{len(body.unread)} statement(s) pglast rejects")
    return f"{body.obj.identity}: {', '.join(reasons)}" if reasons else None


def tombstoned(inventory: Inventory, files: Sequence[ParsedFile], column: str) -> Tombstoned:
    """Every table the tree writes *column* of, and the routines it could not read.

    Args:
        inventory: The tables the tree declares, ``ALTER``s folded in.
        files: The schema files, each parsed once.
        column: The tombstone column, folded.
    """
    tables: set[TableKey] = set()
    undecided: list[str] = []
    for parsed in files:
        roots = [raw.stmt for raw in parsed.statements]
        for body in routine_bodies(parsed):
            if (unread := _undecided(body)) is not None:
                undecided.append(unread)
            roots += [statement.root for statement in body.statements]
        for root in roots:
            for relation in _written_relations(root, column):
                tables.update(key_of(table) for table in _tables(inventory, relation))
    return Tombstoned(frozenset(tables), tuple(undecided))
