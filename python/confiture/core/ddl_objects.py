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

from dataclasses import dataclass, field
from typing import Any

from pglast.stream import RawStream

from confiture.core.linting.inventory import (
    DEFAULT_SCHEMA,
    Signature,
    object_from_statement,
    signature_bucket,
    signatures_match,
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
        "CreateFunctionStmt",  # functions and procedures both
        "DefineStmt",  # only when it spells CREATE AGGREGATE
        "CreateDomainStmt",
        "CompositeTypeStmt",
    }
)

#: The kinds whose ``REPLACE`` is a *body* edit. ``--require-migration-bodies``
#: (#178) already reports these and is off by default, so the accompaniment gate
#: keeps them behind that flag rather than turning an opt-in into an always-on.
#: A view is not among them: nothing else in that gate reports a redefined view.
BODY_KINDS: frozenset[str] = frozenset({"function", "procedure", "aggregate"})

#: Parse nodes that define something the differ models elsewhere, so tracking
#: them here would report every table twice.
MODELLED_ELSEWHERE: dict[str, str] = {
    "CreateStmt": "ParsedSchema.tables, compared column by column",
    "CreateEnumStmt": (
        "ParsedSchema.enum_types, compared value by value. The inventory calls "
        "an enum a 'type', the same kind it gives a composite, so tracking it "
        "here would report every enum twice — once as ADD_TYPE and once as "
        "ADD_ENUM_TYPE."
    ),
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
    "CreateFunctionStmt": "replace",
}


@dataclass(frozen=True)
class ObjectRef:
    """A **bucket**: what makes two ``CREATE`` statements *candidates* for one object.

    ``schema`` is folded and defaulted, so an unqualified ``CREATE VIEW v`` and
    ``CREATE VIEW public.v`` are one object — what
    :data:`~confiture.core.linting.inventory.DEFAULT_SCHEMA` is for. ``name`` is
    folded for the same reason; :attr:`display` keeps the spelling a change
    prints.

    ``signature`` is the inventory's :func:`~confiture.core.linting.inventory.signature_bucket`
    — the canonical *names* of a routine's input parameter types, without their
    own schemas. It is deliberately not the full signature: a dict key cannot
    express "a type schema written on one side and left off the other still
    matches", so ``fn(bigint)`` and ``fn(int8)`` must land in one bucket and
    :func:`~confiture.core.linting.inventory.signatures_match` decides inside it.
    Keying on the full signature reported an added and a dropped function where
    one routine had been respelled (CLAUDE.md, #275).
    """

    kind: str
    schema: str
    name: str
    signature: tuple[str, ...] | None
    #: The spelling a change prints. Out of the key deliberately: it carries the
    #: *signature as written*, and ``fn(bigint)`` and ``fn(int8)`` are one
    #: routine written two ways (#275). Keying on it reported a dropped and an
    #: added function where a type had merely been respelled.
    display: str = field(compare=False)

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
    is not an error. ``signature`` is the routine's full canonical signature,
    schemas included, which is what separates two definitions that share a
    bucket.
    """

    ref: ObjectRef
    definition: str
    create_sql: str
    signature: Signature | None = None


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
        schema=(obj.folded_schema or DEFAULT_SCHEMA).lower(),
        name=obj.folded_name,
        signature=signature_bucket(obj.signature_key),
        display=obj.identity,
    )
    return DDLObject(
        ref=ref,
        definition=_canonical_definition(raw.stmt),
        create_sql=_creating_statement(raw.stmt),
        signature=obj.signature_key,
    )


def objects_in(sql: str, raws: list[Any]) -> dict[ObjectRef, list[DDLObject]]:
    """Every tracked object in an already-parsed schema, bucketed by reference.

    *raws* are the statements :func:`pglast.parse_sql` returned for *sql*; the
    caller passes its own parse rather than this module taking a second one, so
    a schema is read once however many walkers ask about it.

    The value is a **list** because :class:`ObjectRef` is a bucket: two routines
    whose argument types differ only in the schema they name — ``app.f(app.t)``
    and ``app.f(other.t)`` — share one, and are two objects. They are kept in
    source order and separated by :func:`pair_definitions`.
    """
    objects: dict[ObjectRef, list[DDLObject]] = {}
    for raw in raws:
        found = object_of(sql, raw)
        if found is not None:
            objects.setdefault(found.ref, []).append(found)
    return objects


def pair_definitions(
    old: list[DDLObject], new: list[DDLObject]
) -> tuple[list[tuple[DDLObject, DDLObject]], list[DDLObject], list[DDLObject]]:
    """Match one bucket's definitions across two schemas.

    Returns ``(pairs, dropped, added)``. A definition pairs with the first one
    on the other side whose full signature matches it, which for every kind that
    is not a routine — and for the overwhelming majority that are — is the only
    candidate in the bucket. What is left over on either side is an object that
    appeared or went away.
    """
    remaining = list(new)
    pairs: list[tuple[DDLObject, DDLObject]] = []
    dropped: list[DDLObject] = []
    for before in old:
        match = next(
            (after for after in remaining if signatures_match(before.signature, after.signature)),
            None,
        )
        if match is None:
            dropped.append(before)
        else:
            remaining.remove(match)
            pairs.append((before, match))
    return pairs, dropped, remaining
