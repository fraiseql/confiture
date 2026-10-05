"""Unique keys on a table that soft-deletes (``softdel_001``, ``softdel_002``, #597).

A table carrying the tombstone column ``db/project.yaml``'s ``soft_delete:`` names
keeps a deleted row, with its key. A ``UNIQUE`` constraint or unique index that
does not exclude tombstones keeps reserving that value: adding the same product to
the same order again fails with ``23505``, and so does renaming another row to the
freed value. The constraint is right on a table that hard-deletes and wrong on one
that soft-deletes, and only the table says which.

``softdel_001`` reports each unique key of a soft-deleting table whose predicate
does not imply ``<column> IS NULL``. "Implies" is read from the predicate's parse
tree: a top-level ``AND`` conjunct (``AND`` nested in ``AND`` included) that is
``<column> IS NULL``. Anything else — an ``OR``, a function, ``IS NOT NULL`` — does
not imply it. A ``UNIQUE`` constraint has no predicate, so it is always reported.
Exempt:

- the primary key: a row is not re-created under the key a deleted one had;
- a one-column key whose value no author chooses — an identity, a sequence, a
  generated uuid (``ValueSource.unique_without_author_input``) — or a ``uuid``
  column: a uuid is never reused by intent, so reserving it forever costs nothing;
- an index backing a constraint, which is judged once, as the constraint.

``softdel_002`` reports such a key — partial or not — that covers a nullable column
and does not say ``NULLS NOT DISTINCT``: two rows holding ``NULL`` there never
collide, so when ``NULL`` is a real value of the scope (a tree's root has no
parent) two roots may share a name. The flag is read from the key's statement, not
from the schema model, which does not hold it.

A value that must stay reserved after its row is deleted is waived with
``-- confiture:softdel-keep-reserved`` on the line above the statement that writes
the key: the ``CREATE UNIQUE INDEX`` or the ``ALTER TABLE … ADD CONSTRAINT``. A
``CREATE TABLE`` writes several keys, so above one the directive names the key it
waives: ``-- confiture:softdel-keep-reserved tb_order_line_code_key`` (an unnamed
key by the name PostgreSQL gives it).

A key is judged on the table the tree ends with — the model's: an index a later
``DROP INDEX`` drops is not judged — and a child table reads the columns it
inherits.
"""

import bisect
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from confiture.config.project import SoftDeleteConfig
from confiture.core import sql_lexer
from confiture.core._pglast_enums import member as _pg_member
from confiture.core.ddl_clauses import relation as relation_text
from confiture.core.ddl_walk import (
    added_constraint,
    enum_int,
    read_constraint,
    read_index,
)
from confiture.core.linting.inventory import Inventory, SchemaObject, inherit_columns
from confiture.core.schema_identity import identifier_identity, quote_identifier
from confiture.core.schema_model import Column, Constraint, RelationName
from confiture.core.sql_lexer import ParsedFile

#: The directive that keeps a key reserving deleted rows on purpose.
KEEP_RESERVED = "softdel-keep-reserved"

_AND_EXPR = _pg_member("BoolExprType", "AND_EXPR")
_IS_NULL = _pg_member("NullTestType", "IS_NULL")


@dataclass(frozen=True)
class WrittenKey:
    """One unique key a statement writes, on the table the tree ends with.

    Attributes:
        table: The table, with the columns it inherits.
        name: The key's name — PostgreSQL's own for an unnamed constraint — or
            ``None`` for an unnamed index.
        keys: Each key as written: a column name or a rendered expression.
        expressions: Alongside :attr:`keys`, whether each is an expression.
        constraint: A ``UNIQUE`` constraint rather than a ``CREATE UNIQUE INDEX``.
        predicate: The index's ``WHERE`` as pglast holds it, ``None`` for none.
        where: The same predicate, rendered.
        nulls_not_distinct: Whether the key says ``NULLS NOT DISTINCT``.
        file: The file that writes the key.
        line: Where a finding points: the key in a ``CREATE TABLE``, else its statement.
        waived: A ``softdel-keep-reserved`` directive waives it.
    """

    table: SchemaObject
    name: str | None
    keys: tuple[str, ...]
    expressions: tuple[bool, ...]
    constraint: bool
    predicate: Any
    where: str | None
    nulls_not_distinct: bool
    file: str | None
    line: int
    waived: bool

    def column(self, folded: str) -> Column | None:
        """The table's column named *folded*, or ``None``."""
        return next((c for c in self.table.columns if c.folded == folded), None)

    @property
    def columns(self) -> tuple[str, ...]:
        """The keys that are columns, not expressions."""
        return tuple(k for k, e in zip(self.keys, self.expressions, strict=True) if not e)


@dataclass(frozen=True)
class SoftDeleteFinding:
    """A key that reserves deleted rows, or treats a nullable column's ``NULL`` as distinct."""

    table: str
    file: str | None
    line: int
    message: str
    fix: str


@dataclass(frozen=True)
class _Statement:
    """Where one statement writes its keys: its table, its file, its line, its waivers."""

    table: SchemaObject
    parsed: ParsedFile
    line: int
    #: The arguments of each ``softdel-keep-reserved`` above it, ``None`` for a bare one.
    waivers: frozenset[str | None]
    #: A ``CREATE TABLE``, whose bare directive waives nothing: it writes several keys.
    creates_table: bool

    def waives(self, name: str | None) -> bool:
        """Whether a directive above the statement keeps the key *name* reserved."""
        return (None in self.waivers and not self.creates_table) or (
            name is not None and name in self.waivers
        )


def _line_finder(text: str) -> Callable[[int], int]:
    """The 1-based line of an offset into *text*, by binary search over its newlines."""
    newlines = [i for i, c in enumerate(text) if c == "\n"]
    return lambda offset: bisect.bisect_left(newlines, min(max(offset, 0), len(text))) + 1


def _waivers(parsed: ParsedFile) -> dict[int, frozenset[str | None]]:
    """Statement line → the arguments of each ``softdel-keep-reserved`` above it."""
    found: dict[int, set[str | None]] = {}
    for directive in sql_lexer.directives(parsed.text):
        if directive.name == KEEP_RESERVED and directive.statement_line is not None:
            argument = identifier_identity(directive.argument) if directive.argument else None
            found.setdefault(directive.statement_line, set()).add(argument)
    return {line: frozenset(arguments) for line, arguments in found.items()}


def _table(held: Inventory, relation: Any) -> SchemaObject | None:
    found = held.find_all(("table",), relation.schemaname, relation.relname)
    return found[0] if found else None


def _default_name(table: SchemaObject, columns: tuple[str, ...]) -> str:
    """The name PostgreSQL gives an unnamed ``UNIQUE``: ``<table>_<columns>_key``."""
    return "_".join((table.folded_name, *columns, "key"))


def _constraint_key(at: _Statement, node: Any, column: str | None, line: int) -> WrittenKey | None:
    """The key a ``Constraint`` node writes, when it is a ``UNIQUE`` the table still holds."""
    read = read_constraint(node, column=column)
    if not isinstance(read, Constraint) or read.kind != "unique" or not read.columns:
        return None
    if not any(
        held.kind == "unique" and held.columns == read.columns and held.name == read.name
        for held in at.table.constraints
    ):
        return None
    name = read.name or _default_name(at.table, read.columns)
    return WrittenKey(
        table=at.table,
        name=name,
        keys=read.columns,
        expressions=tuple(False for _ in read.columns),
        constraint=True,
        predicate=None,
        where=None,
        nulls_not_distinct=bool(getattr(node, "nulls_not_distinct", False)),
        file=at.parsed.label,
        line=line,
        waived=at.waives(name),
    )


def _index_key(at: _Statement, stmt: Any) -> WrittenKey | None:
    """The key a ``CREATE UNIQUE INDEX`` writes, when the table still holds the index."""
    index = read_index(stmt, table=RelationName(at.table.schema, at.table.name))
    if not index.unique or index not in at.table.indexes:
        return None
    return WrittenKey(
        table=at.table,
        name=index.name,
        keys=index.columns,
        expressions=index.expressions or tuple(False for _ in index.columns),
        constraint=False,
        predicate=stmt.whereClause,
        where=index.where,
        nulls_not_distinct=bool(getattr(stmt, "nulls_not_distinct", False)),
        file=at.parsed.label,
        line=at.line,
        waived=at.waives(index.name),
    )


def _create_table_keys(
    at: _Statement, stmt: Any, line_of: Callable[[int], int]
) -> Iterator[WrittenKey]:
    """Every ``UNIQUE`` a ``CREATE TABLE`` writes, on a column or at table level."""
    for element in stmt.tableElts or ():
        if type(element).__name__ == "ColumnDef":
            nodes = [(node, element.colname) for node in element.constraints or ()]
        elif type(element).__name__ == "Constraint":
            nodes = [(element, None)]
        else:
            continue
        for node, column in nodes:
            key = _constraint_key(at, node, column, line_of(getattr(node, "location", -1)))
            if key is not None:
                yield key


def _statement_keys(
    held: Inventory,
    parsed: ParsedFile,
    raw: Any,
    waivers: dict[int, frozenset[str | None]],
    line_of: Callable[[int], int],
) -> Iterator[WrittenKey]:
    """The unique keys one statement writes on a table the tree declares."""
    stmt = raw.stmt
    kind = type(stmt).__name__
    if kind not in ("CreateStmt", "AlterTableStmt", "IndexStmt"):
        return
    table = _table(held, stmt.relation)
    if table is None:
        return
    line = line_of(sql_lexer.skip_leading_comments(parsed.text, raw.stmt_location or 0))
    at = _Statement(table, parsed, line, waivers.get(line, frozenset()), kind == "CreateStmt")
    if kind == "CreateStmt":
        yield from _create_table_keys(at, stmt, line_of)
    elif kind == "AlterTableStmt":
        for cmd in stmt.cmds or ():
            node = added_constraint(cmd)
            key = None if node is None else _constraint_key(at, node, None, line)
            if key is not None:
                yield key
    elif stmt.unique:
        key = _index_key(at, stmt)
        if key is not None:
            yield key


def written_keys(inventory: Inventory, files: Sequence[ParsedFile]) -> Iterator[WrittenKey]:
    """Every unique key the tree writes and still holds, in the order it writes them.

    The primary key is not one: it is never judged. A table reads with the
    columns it inherits (``INHERITS``, ``PARTITION OF``).
    """
    held = inherit_columns(inventory)
    for parsed in files:
        waivers = _waivers(parsed)
        line_of = _line_finder(parsed.text)
        for raw in parsed.statements:
            yield from _statement_keys(held, parsed, raw, waivers, line_of)


def _conjuncts(node: Any) -> Iterator[Any]:
    """The terms of a predicate's top-level ``AND``, nested ``AND`` flattened."""
    if type(node).__name__ == "BoolExpr" and enum_int(node.boolop) == _AND_EXPR:
        for arg in node.args or ():
            yield from _conjuncts(arg)
    else:
        yield node


def _is_null_test_on(node: Any, column: str) -> bool:
    """Whether *node* is ``<column> IS NULL``, the column qualified or not."""
    if type(node).__name__ != "NullTest" or enum_int(node.nulltesttype) != _IS_NULL:
        return False
    arg = node.arg
    if type(arg).__name__ != "ColumnRef" or not arg.fields:
        return False
    last = arg.fields[-1]
    return type(last).__name__ == "String" and last.sval == column


def excludes_tombstones(key: WrittenKey, column: str) -> bool:
    """Whether the key's predicate implies ``<column> IS NULL``."""
    return key.predicate is not None and any(
        _is_null_test_on(term, column) for term in _conjuncts(key.predicate)
    )


def _no_author_chooses(key: WrittenKey) -> bool:
    """A one-column key PostgreSQL fills, or a uuid: never reused by intent."""
    if len(key.keys) != 1 or key.expressions[0]:
        return False
    column = key.column(key.keys[0])
    return column is not None and (
        column.value_source.unique_without_author_input or column.type_key == "uuid"
    )


def _keys_to_judge(
    inventory: Inventory, files: Sequence[ParsedFile], column: str
) -> Iterator[WrittenKey]:
    """The keys of every soft-deleting table that an author's value fills."""
    for key in written_keys(inventory, files):
        if key.column(column) is not None and not _no_author_chooses(key):
            yield key


def _key_text(key: WrittenKey, keys: tuple[str, ...] | None = None) -> str:
    """Keys as SQL: a column quoted if it must be, an expression as rendered."""
    expressions = dict(zip(key.keys, key.expressions, strict=True))
    return ", ".join(k if expressions.get(k) else quote_identifier(k) for k in keys or key.keys)


def _called(key: WrittenKey) -> str:
    kind = "UNIQUE" if key.constraint else "unique index"
    return f"{kind} {key.name}" if key.name else f"the {kind} on ({_key_text(key)})"


def _table_text(key: WrittenKey) -> str:
    return relation_text(RelationName(key.table.folded_schema, key.table.folded_name))


def _partial_index(key: WrittenKey, column: str, *, nulls_not_distinct: bool = False) -> str:
    """The ``CREATE UNIQUE INDEX`` that covers live rows only."""
    kept = tuple(k for k in key.keys if k != column) or key.keys
    tombstone = f"{quote_identifier(column)} IS NULL"
    if key.where is None:
        where = tombstone
    elif excludes_tombstones(key, column):
        where = key.where
    else:
        where = f"({key.where}) AND {tombstone}"
    name = f"{quote_identifier(key.name)} " if key.name else ""
    nulls = " NULLS NOT DISTINCT" if nulls_not_distinct or key.nulls_not_distinct else ""
    return (
        f"CREATE UNIQUE INDEX {name}ON {_table_text(key)} ({_key_text(key, kept)}){nulls} "
        f"WHERE {where}"
    )


def _reserving(key: WrittenKey, column: str) -> SoftDeleteFinding:
    """``softdel_001``'s finding on one key, with the rewrite."""
    waiver = f"-- confiture:{KEEP_RESERVED}"
    if key.constraint:
        name = quote_identifier(key.name or "")
        fix = (
            f"ALTER TABLE {_table_text(key)} DROP CONSTRAINT {name}; "
            f"{_partial_index(key, column)}; a partial index is no constraint, so "
            f"ON CONFLICT ON CONSTRAINT {name} no longer finds it: write "
            f"ON CONFLICT ({_key_text(key)}) WHERE {quote_identifier(column)} IS NULL. "
            "A value that stays reserved after its row is deleted, on purpose: "
            f"`{waiver} {key.name}` above the statement that writes it"
        )
    else:
        fix = (
            f"{_partial_index(key, column)}, in place of the index. A value that stays "
            f"reserved after its row is deleted, on purpose: `{waiver}` above the "
            "CREATE UNIQUE INDEX"
        )
    message = (
        f"{_called(key)} on {key.table.qualified} keeps reserving a deleted row's value: "
        f"the table soft-deletes ({column}) and the key does not exclude rows where "
        f"{column} IS NOT NULL"
    )
    return SoftDeleteFinding(key.table.qualified, key.file, key.line, message, fix)


def reserved_key_findings(
    inventory: Inventory, files: Sequence[ParsedFile], config: SoftDeleteConfig
) -> Iterator[SoftDeleteFinding]:
    """``softdel_001``: every key of a soft-deleting table that reserves deleted rows."""
    column = identifier_identity(config.column)
    for key in _keys_to_judge(inventory, files, column):
        if not key.waived and not excludes_tombstones(key, column):
            yield _reserving(key, column)


def _nullable(key: WrittenKey, column: str) -> list[str]:
    """The key's columns, the tombstone aside, that may hold ``NULL``."""
    return [
        name
        for name in key.columns
        if name != column and (held := key.column(name)) is not None and not held.not_null
    ]


def null_key_findings(
    inventory: Inventory, files: Sequence[ParsedFile], config: SoftDeleteConfig
) -> Iterator[SoftDeleteFinding]:
    """``softdel_002``: every such key over a nullable column, without ``NULLS NOT DISTINCT``."""
    column = identifier_identity(config.column)
    for key in _keys_to_judge(inventory, files, column):
        nullable = _nullable(key, column)
        if key.nulls_not_distinct or not nullable:
            continue
        if key.constraint:
            rewrite = f"UNIQUE NULLS NOT DISTINCT ({_key_text(key)})"
        else:
            rewrite = _partial_index(key, column, nulls_not_distinct=True)
        yield SoftDeleteFinding(
            key.table.qualified,
            key.file,
            key.line,
            f"{_called(key)} on {key.table.qualified} covers {', '.join(nullable)}, which "
            "may be NULL, without NULLS NOT DISTINCT: two rows holding NULL there never "
            "collide",
            f"when NULL is a value of the key (a root has no parent): {rewrite}",
        )
