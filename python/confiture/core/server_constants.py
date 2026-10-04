"""How a server spells a tree's constants, so a default is compared as a value (#564).

PostgreSQL stores a constant in its type's output spelling: a ``jsonb`` object with
its keys sorted and duplicates collapsed, ``'2024-1-1'`` as ``2024-01-01``, ``'t'``
as ``true``, a ``timestamptz`` in the session's ``TimeZone``. A parse tree holds a
constant as opaque text, so the only faithful spelling is the server's own:
:func:`server_constants` asks the database a tree is compared with to cast each of
the tree's typed constants and print it back, in that database's session, so
``TimeZone``, ``DateStyle`` and ``IntervalStyle`` are the ones ``pg_get_expr``
printed with. Nothing is written; two statements are run.

A type is named the way the tree resolves it (``model_facts.resolve``), not the way
the session's ``search_path`` would, and the server validates it (``to_regtype``)
before it is used. A type the server lacks — an enum the tree adds — and a literal
it refuses — a value that enum does not hold yet — are left as written: the missing
type or value is a difference of its own.
"""

from typing import TYPE_CHECKING

import psycopg
from psycopg import sql

from confiture.core.ddl_walk import AS_WRITTEN, ConstantSpellings, typed_constants
from confiture.core.model_facts import resolve

if TYPE_CHECKING:
    from confiture.core.schema_model import ObjectRef, SchemaModel

#: What a server raises for a value its type refuses: input it cannot read or an
#: enum label it does not hold (``DataError``), a domain's CHECK (``IntegrityError``).
_REFUSED = (psycopg.errors.DataError, psycopg.errors.IntegrityError)

#: The kinds a constant's type can be that a tree declares.
_TYPE_KINDS = frozenset({"type", "domain"})


def server_constants(conn: psycopg.Connection, model: SchemaModel) -> ConstantSpellings:
    """How *conn*'s server spells every typed constant in *model*'s column defaults.

    Read in a transaction of its own — a savepoint inside the caller's — so a cast
    the server refuses leaves the caller's transaction as it was.
    """
    asked = sorted(
        {
            constant
            for table in model.tables.values()
            for column in table.columns
            for constant in typed_constants(column.default, column.type_text or column.type_key)
        }
    )
    if not asked:
        return AS_WRITTEN
    types = _server_types(conn, model, {type_ for _, type_ in asked})
    wanted = [(literal, type_) for literal, type_ in asked if type_ in types]
    try:
        spelled = _cast(conn, wanted, types)
    except _REFUSED:
        # One refused literal refuses the statement: ask for each on its own.
        spelled = {}
        for constant in wanted:
            try:
                spelled |= _cast(conn, [constant], types)
            except _REFUSED:
                continue  # left as written: the refused value is its own difference
    return ConstantSpellings(spelled)


def _server_types(conn: psycopg.Connection, model: SchemaModel, types: set[str]) -> dict[str, str]:
    """Each of *types* the server knows, as it spells it (``format_type``'s quoting)."""
    refs = [ref for ref in (*model.enum_types, *model.other_objects) if ref.kind in _TYPE_KINDS]
    qualified = {type_: _qualified(refs, type_) for type_ in types}
    rows = conn.execute(
        "SELECT t, to_regtype(t)::text FROM unnest(%s::text[]) AS t",
        [sorted(set(qualified.values()))],
    ).fetchall()
    known = {written: spelled for written, spelled in rows if spelled is not None}
    return {type_: known[name] for type_, name in qualified.items() if name in known}


def _qualified(refs: list[ObjectRef], type_: str) -> str:
    """*type_* with the schema the tree puts it in, when the tree declares it."""
    base = type_.removesuffix("[]" * type_.count("[]"))
    ref = resolve(refs, base)
    if ref is None:
        return type_
    return f"{ref.schema}.{ref.name}" + type_[len(base) :]


def _cast(
    conn: psycopg.Connection, constants: list[tuple[str, str]], types: dict[str, str]
) -> dict[tuple[str, str], str]:
    """*constants* cast to their types and printed back by the server, in one statement.

    Printed by each type's output function (``format('%s', …)``), as
    ``pg_get_expr`` prints a constant — not by a cast to ``text``, which for
    ``inet`` keeps a ``/32`` the stored default does not show.
    """
    if not constants:
        return {}
    query = sql.SQL("SELECT {}").format(
        sql.SQL(", ").join(
            sql.SQL("format('%%s', CAST({} AS {}))").format(
                sql.Placeholder(), sql.SQL(types[type_])
            )
            for _, type_ in constants
        )
    )
    with conn.transaction():
        row = conn.execute(query, [literal for literal, _ in constants]).fetchone()
    return dict(zip(constants, row or (), strict=True))
