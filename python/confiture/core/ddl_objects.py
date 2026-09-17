"""The schema objects a DDL tree defines, and what makes two of them the same one.

``migrate validate --require-migration`` asks whether the schema tree changed in
a way a migrate-only environment will never receive. Answering it needs more
than the tables, enum types and sequences :class:`~confiture.core.differ.SchemaDiffer`
modelled before #288 — a view, a routine, a trigger or an extension added to the
tree and not to a migration is exactly the change the gate exists to catch, and
each of them passed it with a green tick.

**Identity is the inventory's answer, not a second one.**
:func:`confiture.core.linting.inventory.object_from_statement` already decides
what a statement defines, how a schema qualifier is read and — for a routine —
which overload it is, over canonical argument types (#275). This module calls
it. What it adds is the half the inventory does not hold: the **definition**,
so a view redefined in place is visible, and a table of which parse nodes are
tracked here, so a node that creates something and is not tracked is a stated
decision rather than silence.

The definition is ``RawStream``'s canonical rendering of the statement, which
normalises whitespace, comments and keyword case — a reformatted view is not a
redefinition. ``OR REPLACE`` and ``IF NOT EXISTS`` are neutralised before
rendering: they say how the statement behaves when the object already exists,
not what the object is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pglast.stream import RawStream

from confiture.core.linting.inventory import (
    DEFAULT_SCHEMA,
    Signature,
    object_from_statement,
)

#: Which parse nodes this module turns into objects, and why each one that
#: creates something is absent. A node that is neither tracked nor named here
#: fails ``tests/unit/test_ddl_objects_are_exhaustive.py``: the gate's whole
#: value is that a schema change cannot be silent, so an unconsidered statement
#: kind is a hole in it.
TRACKED_NODES: frozenset[str] = frozenset(
    {
        "ViewStmt",
        "CreateTableAsStmt",  # only when it spells CREATE MATERIALIZED VIEW
    }
)

#: Parse nodes that define something the differ models elsewhere, so tracking
#: them here would report every table twice.
MODELLED_ELSEWHERE: dict[str, str] = {
    "CreateStmt": "ParsedSchema.tables, compared column by column",
    "CreateEnumStmt": "ParsedSchema.enum_types, compared value by value",
    "CreateSeqStmt": "ParsedSchema.sequences",
    "IndexStmt": "Table.indexes",
}

#: The statement-level attributes that say what happens when the object already
#: exists. They are not part of what the object *is*, so a view that gains
#: ``OR REPLACE`` is not a redefinition.
_EXISTENCE_ATTRS = ("replace", "if_not_exists")

#: Which existence clause makes each node re-appliable, for the statement a
#: generated migration carries. A view has ``OR REPLACE``; a materialized view
#: has only ``IF NOT EXISTS``, because PostgreSQL offers it no replace at all.
#: Rendered by setting the attribute and asking ``RawStream`` again rather than
#: by editing its output: the words belong to the printer, not to us.
_IDEMPOTENT_ATTR: dict[str, str] = {
    "ViewStmt": "replace",
    "CreateTableAsStmt": "if_not_exists",
}


@dataclass(frozen=True)
class ObjectRef:
    """What makes two ``CREATE`` statements define the same object.

    ``schema`` is folded and defaulted: an unqualified ``CREATE VIEW v`` and
    ``CREATE VIEW public.v`` are one object, which is what
    :data:`~confiture.core.linting.inventory.DEFAULT_SCHEMA` is for. ``name`` is
    folded for the same reason; :attr:`display` keeps the spelling a finding
    prints. ``signature`` is a routine's canonical input parameter types and
    ``None`` for every other kind.
    """

    kind: str
    schema: str
    name: str
    signature: Signature | None
    display: str

    @property
    def qualified(self) -> str:
        """How a change names the object: the spelling the author wrote."""
        return self.display


@dataclass(frozen=True)
class DDLObject:
    """One tracked ``CREATE``: what it defines, and two renderings of it.

    ``definition`` is what decides whether the object *changed* — existence
    clauses neutralised, so a view that gains ``OR REPLACE`` is the same view.
    ``create_sql`` is what a generated migration carries — the same statement
    with the existence clause its kind supports, so re-applying the migration
    is not an error.
    """

    ref: ObjectRef
    definition: str
    create_sql: str


def _rendered_with(stmt: Any, wanted: dict[str, bool]) -> str:
    """``RawStream``'s rendering of *stmt* with *wanted* attributes forced.

    The attributes are restored afterwards: the caller's parse tree is walked
    again for tables and constraints, and a statement left rewritten would lie
    to whoever reads it next. An attribute the node does not carry is skipped
    rather than added — ``CreateTableAsStmt`` has no ``replace``, and inventing
    one would render SQL PostgreSQL cannot parse.
    """
    saved: dict[str, Any] = {}
    for attr, value in wanted.items():
        current = getattr(stmt, attr, None)
        if current is not None and bool(current) != value:
            saved[attr] = current
            setattr(stmt, attr, value)
    try:
        return RawStream()(stmt)
    finally:
        for attr, value in saved.items():
            setattr(stmt, attr, value)


def _canonical_definition(stmt: Any) -> str:
    """The rendering that decides whether the object changed."""
    return _rendered_with(stmt, dict.fromkeys(_EXISTENCE_ATTRS, False))


def _creating_statement(stmt: Any) -> str:
    """The rendering a generated migration carries, re-appliable where it can be."""
    attr = _IDEMPOTENT_ATTR.get(type(stmt).__name__)
    if attr is None:
        return _canonical_definition(stmt)
    wanted = dict.fromkeys(_EXISTENCE_ATTRS, False)
    wanted[attr] = True
    return _rendered_with(stmt, wanted)


def object_of(sql: str, raw: Any) -> DDLObject | None:
    """The object this statement defines, or ``None`` when it defines none here.

    ``None`` covers three cases that are not failures: a node this module does
    not track, a node it tracks that this statement does not use to create an
    object (``CREATE TABLE … AS`` shares :class:`CreateTableAsStmt` with
    ``CREATE MATERIALIZED VIEW``), and a statement the inventory declines.
    """
    if type(raw.stmt).__name__ not in TRACKED_NODES:
        return None
    obj = object_from_statement(sql, raw)
    if obj is None:
        return None
    ref = ObjectRef(
        kind=obj.kind,
        schema=obj.folded_schema or DEFAULT_SCHEMA,
        name=obj.folded_name,
        signature=obj.signature_key,
        display=obj.identity,
    )
    return DDLObject(
        ref=ref,
        definition=_canonical_definition(raw.stmt),
        create_sql=_creating_statement(raw.stmt),
    )


def objects_in(sql: str, raws: list[Any]) -> dict[ObjectRef, DDLObject]:
    """Every tracked object in an already-parsed schema, keyed by reference.

    *raws* are the statements :func:`pglast.parse_sql` returned for *sql*; the
    caller passes its own parse rather than this module taking a second one, so
    a schema is read once however many walkers ask about it.

    A tree that defines the same object twice keeps the **last** definition, as
    PostgreSQL does when the second is a ``CREATE OR REPLACE``. A tree where the
    second would fail at build time is ``build_001``'s finding, not the gate's.
    """
    objects: dict[ObjectRef, DDLObject] = {}
    for raw in raws:
        found = object_of(sql, raw)
        if found is not None:
            objects[found.ref] = found
    return objects
