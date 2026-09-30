"""A staging table's foreign keys: which table each references, and whether a resolver resolves it.

A staging table holds a key as ``fk_<role>_id``, the parent's UUID; its final
table holds ``fk_<role>``, the parent's BIGINT, and says in its ``REFERENCES``
which table that is. A key is named for its *role* as often as for its table (an
owner, a parent, a company that is an organization), so the target is read from
the schema, never from the name (#498): the final table's foreign key first,
then one the staging table declares itself, and only for a key with neither the
convention ``tb_<role>``.

A resolver resolves a key where it matches the key's UUID to the target's
``id`` — a ``JOIN … ON``, a comma join and a ``WHERE``, a scalar subquery, a CTE
— in an ``INSERT`` into the final table or in a second-pass ``UPDATE`` of it,
which is how a self-reference is resolved.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from confiture.core.ddl_walk import relation_parts, walk_nodes
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import Table
from confiture.core.seed.validation.prep_seed.resolvers import Resolver

#: A staging table's foreign key: ``fk_<role>_id``, holding the parent's UUID.
FK_PREFIX, FK_SUFFIX = "fk_", "_id"

#: The column a staging key's UUID is matched on in its parent.
_ID = "id"

#: The statements a resolver fills its final table with.
_FILLING = frozenset({"InsertStmt", "UpdateStmt"})


def is_key(column: str) -> bool:
    """Whether a staging column is a foreign key by the convention: ``fk_<role>_id``."""
    return column.startswith(FK_PREFIX) and column.endswith(FK_SUFFIX)


def target(final: Table | None, staging: Table, column: str) -> tuple[str, bool]:
    """``(table name, declared)``: the table *column* references, and whether the schema says so.

    The final table's ``REFERENCES`` on ``fk_<role>`` first, then the staging
    table's own on ``fk_<role>_id``; ``declared`` is ``False`` for the
    convention's ``tb_<role>``.
    """
    held = column.removesuffix(FK_SUFFIX)
    for table, key in ((final, held), (staging, column)):
        if table is None:
            continue
        for constraint in table.constraints_of("foreign_key"):
            if constraint.columns == (key,) and constraint.ref_table is not None:
                return constraint.ref_table.name, True
    return "tb_" + held.removeprefix(FK_PREFIX), False


def filling(resolver: Resolver, schema: str, name: str) -> Iterator[Any]:
    """Each ``INSERT`` into, or ``UPDATE`` of, ``schema.name`` in *resolver*'s body."""
    for statement in resolver.body.statements:
        for node in walk_nodes(statement.root):
            if type(node).__name__ not in _FILLING:
                continue
            written, table = relation_parts(node.relation)
            if table == name and (written or DEFAULT_SCHEMA).lower() == schema:
                yield node


def resolves(statements: list[Any], parent: str, column: str) -> bool:
    """Whether one of *statements* matches ``<parent>.id`` to ``<…>.<column>``."""
    return any(_joined(parent, column, _sources(node), _equalities(node)) for node in statements)


def joins_any(statements: list[Any], column: str) -> bool:
    """Whether one of *statements* matches some table's ``id`` to ``<…>.<column>``.

    A key with no ``REFERENCES`` (a key into a partitioned table cannot have
    one) is resolved by what its resolver joins, whatever the key is named (#530).
    """
    return any(_joined(None, column, _sources(node), _equalities(node)) for node in statements)


def reads(statements: list[Any], column: str) -> bool:
    """Whether one of *statements* reads *column* at all: the second pass a self-reference needs."""
    return any(
        (fields := _column(node)) is not None and fields[-1] == column
        for statement in statements
        for node in walk_nodes(statement)
    )


def _name(node: Any) -> tuple[str, ...]:
    """A ``ColumnRef``'s fields, or an operator's name, as the strings pglast holds."""
    return tuple(str(getattr(part, "sval", "")) for part in node or ())


def _column(node: Any) -> tuple[str, ...] | None:
    """The fields of *node* when it is a column reference, else ``None``."""
    if type(node).__name__ != "ColumnRef":
        return None
    return _name(node.fields)


def _sources(root: Any) -> dict[str, set[str]]:
    """Each name a column can be qualified by in *root*, and the tables it stands for.

    A relation stands for itself under its alias, or under its own name when it
    has none; a CTE stands for every table its query reads, so a join through
    ``WITH makers AS (SELECT … FROM catalog.tb_manufacturer)`` is a join to
    ``tb_manufacturer``.
    """
    nodes = list(walk_nodes(root))
    ctes = {
        node.ctename: {rv.relname for rv in walk_nodes(node.ctequery) if _is_relation(rv)}
        for node in nodes
        if type(node).__name__ == "CommonTableExpr"
    }
    sources: dict[str, set[str]] = {}
    for node in nodes:
        if not _is_relation(node):
            continue
        # Only an unqualified name can be a CTE's.
        cte = ctes.get(node.relname) if node.schemaname is None else None
        alias = getattr(getattr(node, "alias", None), "aliasname", None) or node.relname
        sources.setdefault(alias, set()).update(cte or {node.relname})
    return sources


def _is_relation(node: Any) -> bool:
    return type(node).__name__ == "RangeVar"


def _equalities(root: Any) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    """Every ``column = column`` under *root*, wherever it is written."""
    found = []
    for node in walk_nodes(root):
        if type(node).__name__ != "A_Expr" or _name(node.name) != ("=",):
            continue
        left, right = _column(node.lexpr), _column(node.rexpr)
        if left and right:
            found.append((left, right))
    return found


def _joined(
    parent: str | None,
    column: str,
    sources: dict[str, set[str]],
    equalities: list[tuple[tuple[str, ...], tuple[str, ...]]],
) -> bool:
    """Whether some ``<parent>.id = <…>.<column>`` is written, in either order.

    With no *parent*, any table's ``id`` will do.
    """
    for left, right in equalities:
        for id_side, fk_side in ((left, right), (right, left)):
            if id_side[-1] != _ID or fk_side[-1] != column:
                continue
            if len(id_side) == 1:
                if parent is None or any(parent in tables for tables in sources.values()):
                    return True
            elif parent is None or parent in sources.get(id_side[-2], set()):
                return True
    return False
