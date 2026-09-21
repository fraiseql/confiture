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

from confiture.core.ddl_walk import ObjectEdit, object_edits, object_kinds
from confiture.core.linting.inventory import (
    DEFAULT_SCHEMA,
    KIND_KEYWORD,
    Signature,
    object_from_statement,
    signature_bucket,
    signature_from_type_names,
    signatures_match,
    split_names,
)

# Defined with the rest of the model; re-exported for the callers that name it here.
from confiture.core.schema_model import ObjectRef, Trigger

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
        # The kinds the lint inventory does not model, read by _EXTRA below.
        "CreateTrigStmt",
        "CreatePolicyStmt",
        "RuleStmt",
        "CreateExtensionStmt",
        "CreateSchemaStmt",
        "CreateEventTrigStmt",
        "CreateRangeStmt",
        "CreateStatsStmt",
        "CreateForeignTableStmt",
        "CreateFdwStmt",
        "CreateForeignServerStmt",
        "CreatePublicationStmt",
        "CreateConversionStmt",
        "CreateOpClassStmt",
        "CreateOpFamilyStmt",
        "CreateAmStmt",
    }
)

#: Statements that create something the accompaniment gate does not ask about,
#: with the reason. The reason is the point: a hole the gate has on purpose is a
#: decision someone made, and a node in neither this table nor a tracked one
#: fails ``tests/unit/test_ddl_objects_are_exhaustive.py``.
NOT_A_SCHEMA_OBJECT: dict[str, str] = {
    "CreateRoleStmt": (
        "a role is cluster-scoped: `confiture build` never creates one either, "
        "so a migrate-only environment is no worse off than a rebuilt one"
    ),
    "CreatedbStmt": "a database is cluster-scoped, and is what confiture builds *into*",
    "CreateTableSpaceStmt": "a tablespace is cluster-scoped and filesystem-bound",
    "CreateSubscriptionStmt": (
        "logical replication is cluster configuration, not schema; it carries a "
        "connection string that has no business in a schema tree"
    ),
    "CreateCastStmt": (
        "a cast's identity is a pair of types with no name of its own, so it has "
        "nothing to key on; it is also vanishingly rare outside an extension, "
        "which arrives as CREATE EXTENSION and is tracked"
    ),
    "CreateTransformStmt": "identity is a (type, language) pair with no name of its own",
    "CreateUserMappingStmt": (
        "identity is a (role, server) pair, and the role half is cluster-scoped"
    ),
    "CreatePLangStmt": (
        "PostgreSQL parses CREATE LANGUAGE as CreateExtensionStmt, which is "
        "tracked; this node is unreachable from a parse"
    ),
}

#: The kinds whose ``REPLACE`` is a *body* edit. ``--require-migration-bodies``
#: (#178) already reports these and is off by default, so the accompaniment gate
#: keeps them behind that flag rather than turning an opt-in into an always-on.
#: A view is not among them: nothing else in that gate reports a redefined view.
BODY_KINDS: frozenset[str] = frozenset({"function", "procedure", "aggregate"})

#: Parse nodes that define something the differ models elsewhere, so tracking
#: them here would report every table twice.
#:
#: Each reason names the identity that model is keyed by, because for as long as
#: both modules existed these four were delegated to a reader that identified
#: them differently — by a bare name — while this module's docstring said
#: identity was the inventory's answer and not a second one (#313). A reason
#: that says only *where* a kind is modelled cannot catch that.
MODELLED_ELSEWHERE: dict[str, str] = {
    "CreateStmt": (
        "the schema model's tables (core/schema_model.py), read whole by the lint "
        "inventory and keyed by ObjectRef — (schema, name) with DEFAULT_SCHEMA "
        "folded in — then compared column by column and constraint by constraint"
    ),
    "CreateEnumStmt": (
        "the schema model's enum types, keyed by ObjectRef and compared value by "
        "value. The inventory calls an enum a 'type', the same kind it gives a "
        "composite, so tracking it here would report every enum twice — once as "
        "ADD_TYPE and once as ADD_ENUM_TYPE."
    ),
    "CreateSeqStmt": "the schema model's sequences, keyed by ObjectRef",
    "IndexStmt": (
        "the schema model's Table.indexes, keyed by bare name — correctly, because "
        "the comparison is already scoped to one table, itself keyed by ObjectRef"
    ),
}


@dataclass(frozen=True)
class _Extra:
    """How to read the identity of a node the lint inventory does not model.

    ``name_attr`` is where the object's own name lives — a plain string on most
    nodes, a ``(String, …)`` list on the ones that can be schema-qualified.
    ``parent_attr`` names a ``RangeVar`` the object hangs off: a trigger, a
    policy and a rule are named *per table*, so two tables may each have a
    ``trg_audit`` and they are two objects.
    """

    kind: str
    name_attr: str
    parent_attr: str | None = None


#: One row per tracked node the lint inventory has no builder for. The kinds it
#: *does* model are read through :func:`object_from_statement` instead, so there
#: is one answer to "what does this statement define" and not two.
_EXTRA: dict[str, _Extra] = {
    "CreateTrigStmt": _Extra("trigger", "trigname", "relation"),
    "CreatePolicyStmt": _Extra("policy", "policy_name", "table"),
    "RuleStmt": _Extra("rule", "rulename", "relation"),
    "CreateExtensionStmt": _Extra("extension", "extname"),
    "CreateSchemaStmt": _Extra("schema", "schemaname"),
    "CreateEventTrigStmt": _Extra("event_trigger", "trigname"),
    "CreateRangeStmt": _Extra("type", "typeName"),
    "CreateStatsStmt": _Extra("statistics", "defnames"),
    "CreateForeignTableStmt": _Extra("foreign_table", "base"),
    "CreateFdwStmt": _Extra("foreign_data_wrapper", "fdwname"),
    "CreateForeignServerStmt": _Extra("server", "servername"),
    "CreatePublicationStmt": _Extra("publication", "pubname"),
    "CreateConversionStmt": _Extra("conversion", "conversion_name"),
    "CreateOpClassStmt": _Extra("operator_class", "opclassname"),
    "CreateOpFamilyStmt": _Extra("operator_family", "opfamilyname"),
    "CreateAmStmt": _Extra("access_method", "amname"),
}

#: The SQL keyword each kind is dropped with. Composed from the inventory's own
#: table rather than restated beside it, so the two cannot disagree about what a
#: ``matview`` is called.
OBJECT_KEYWORD: dict[str, str] = {
    **KIND_KEYWORD,
    "trigger": "TRIGGER",
    "policy": "POLICY",
    "rule": "RULE",
    "extension": "EXTENSION",
    "schema": "SCHEMA",
    "event_trigger": "EVENT TRIGGER",
    "statistics": "STATISTICS",
    "foreign_table": "FOREIGN TABLE",
    "foreign_data_wrapper": "FOREIGN DATA WRAPPER",
    "server": "SERVER",
    "publication": "PUBLICATION",
    "conversion": "CONVERSION",
    "operator_class": "OPERATOR CLASS",
    "operator_family": "OPERATOR FAMILY",
    "access_method": "ACCESS METHOD",
}

#: Kinds whose object is named *inside* a table: ``DROP TRIGGER trg ON t``, not
#: ``DROP TRIGGER t.trg``. The reference spells the identity with a dot because
#: that is what makes two same-named triggers on two tables two objects; the
#: DDL has to spell it back out.
TABLE_SCOPED_KINDS: frozenset[str] = frozenset({"trigger", "policy", "rule"})

#: Kinds whose redefinition has no one statement that is plainly right, with the
#: reason. ``migrate diff --generate`` writes ``-- WARNING: no SQL derived`` for
#: these — the change is still *reported*, which is what the gate needs; what is
#: left to the author is the DDL. An entry that stops matching a kind the differ
#: emits fails ``tests/unit/test_differ_sql_objects.py``.
REPLACE_IS_AUTHORS_WORK: dict[str, str] = {
    "domain": "a domain's constraints are altered one at a time; dropping it takes "
    "every column that uses it",
    "type": "a composite type's attributes are altered one at a time",
    "trigger": "CREATE OR REPLACE TRIGGER needs PostgreSQL 14, and dropping one "
    "silently changes what fires during the migration itself",
    "policy": "ALTER POLICY changes a clause at a time, and a dropped policy "
    "leaves rows unprotected for the length of the transaction",
    "rule": "a rewrite rule redefined by drop and create changes what the table "
    "does to concurrent writers mid-migration",
    "extension": "ALTER EXTENSION UPDATE TO a version is the operation; dropping "
    "one takes every object it owns",
    "statistics": "statistics are dropped and recreated, but the estimate they "
    "carry is lost and only ANALYZE brings it back",
    "foreign_table": "a foreign table's columns are altered one at a time, as a table's are",
    "server": "ALTER SERVER changes options in place; dropping one takes its "
    "foreign tables and user mappings",
    "foreign_data_wrapper": "ALTER FOREIGN DATA WRAPPER changes handlers in place",
    "publication": "ALTER PUBLICATION changes its table set; dropping one breaks every subscriber",
    "operator_class": "an operator class is altered by ALTER OPERATOR FAMILY",
    "operator_family": "ALTER OPERATOR FAMILY adds and drops members",
    "access_method": "PostgreSQL has no ALTER ACCESS METHOD beyond rename and owner",
    "conversion": "ALTER CONVERSION only renames; a redefinition is a drop and a "
    "create, and a dropped conversion changes how bytes decode meanwhile",
    "event_trigger": "a dropped event trigger stops firing during the migration "
    "that replaces it, which is when it matters most",
    "schema": "a schema is not redefined; what changed is something in it",
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
    #: A trigger, as the schema model holds one; ``None`` for every other kind.
    trigger: Trigger | None = None


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


def _named(value: Any) -> tuple[str | None, str] | None:
    """``(schema, name)`` from a node attribute that holds an identifier.

    A plain string is the unqualified case; a ``(String, …)`` list is the
    qualified one and is read by the inventory's own ``split_names``, so a
    dotted name is split the same way everywhere.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return None, value
    if type(value).__name__ == "CreateStmt":  # CREATE FOREIGN TABLE embeds one
        return value.relation.schemaname, value.relation.relname
    try:
        return split_names(value)
    except (AttributeError, IndexError, TypeError):
        return None


def _extra_ref(stmt: Any, spec: _Extra) -> ObjectRef | None:
    """The reference for a node the lint inventory does not model."""
    named = _named(getattr(stmt, spec.name_attr, None))
    if named is None:
        return None
    schema, name = named
    parent = getattr(stmt, spec.parent_attr, None) if spec.parent_attr else None
    if spec.parent_attr is not None and parent is None:
        return None
    if parent is not None:
        schema = parent.schemaname or schema
        name = f"{parent.relname}.{name}"
    return ObjectRef(
        kind=spec.kind,
        schema=(schema or DEFAULT_SCHEMA).lower(),
        name=name.lower(),
        signature=None,
        display=f"{schema}.{name}" if schema else name,
    )


def _inventory_ref(sql: str, raw: Any) -> tuple[ObjectRef, Signature | None] | None:
    """The reference for a node the lint inventory models — its answer, not ours."""
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
    return ref, obj.signature_key


def object_of(sql: str, raw: Any) -> DDLObject | None:
    """The object this statement defines, or ``None`` when it defines none here.

    ``None`` covers three cases that are not failures: a node this module does
    not track, a node it tracks that this statement does not use to create an
    object (``CREATE TABLE … AS`` shares :class:`CreateTableAsStmt` with
    ``CREATE MATERIALIZED VIEW``, and ``DefineStmt`` with ``CREATE OPERATOR``),
    and a statement whose name is not where the grammar usually keeps it.
    """
    stmt = raw.stmt
    node = type(stmt).__name__
    if node not in TRACKED_NODES:
        return None

    spec = _EXTRA.get(node)
    if spec is not None:
        ref = _extra_ref(stmt, spec)
        signature = None
    else:
        found = _inventory_ref(sql, raw)
        if found is None:
            return None
        ref, signature = found
    if ref is None:
        return None
    return DDLObject(
        ref=ref,
        definition=_canonical_definition(stmt),
        create_sql=_creating_statement(stmt),
        signature=signature,
        trigger=_trigger(stmt) if ref.kind == "trigger" else None,
    )


def _trigger(stmt: Any) -> Trigger:
    relation = stmt.relation
    return Trigger(name=stmt.trigname, table=relation.relname, schema=relation.schemaname)


def declared_triggers(objects: dict[ObjectRef, list[DDLObject]]) -> list[Trigger]:
    """The triggers a tree still declares, from :func:`objects_in`'s answer."""
    return [obj.trigger for found in objects.values() for obj in found if obj.trigger is not None]


def _matches(ref: ObjectRef, edit: ObjectEdit) -> bool:
    """Whether ``edit`` names ``ref``, by the inventory's identity rules.

    A schema the statement left off matches any: PostgreSQL resolves the bare
    spelling through ``search_path``, and a tree that wrote ``DROP VIEW v`` did
    not say which schema it meant. The same wildcard ``find_all`` applies to an
    object's own schema.
    """
    if ref.kind not in object_kinds(edit.object_kind) or ref.name != edit.name.lower():
        return False
    return edit.schema is None or ref.schema == edit.schema.lower()


def _apply_drop(objects: dict[ObjectRef, list[DDLObject]], edit: ObjectEdit) -> None:
    """Forget the objects a ``DROP`` names, overload by overload.

    An ``ObjectRef`` is a bucket, so a dropped overload is matched inside it by
    its full signature — ``DROP FUNCTION f(bigint)`` and a tree's ``f(int8)`` are
    one routine (#275). A drop that named no argument list takes every overload,
    which is what PostgreSQL does with the one it finds.
    """
    wanted = signature_from_type_names(edit.arg_types) if edit.arg_types is not None else None
    for ref in [ref for ref in objects if _matches(ref, edit)]:
        remaining = (
            []
            if wanted is None
            else [obj for obj in objects[ref] if not signatures_match(obj.signature, wanted)]
        )
        if remaining:
            objects[ref] = remaining
        else:
            del objects[ref]


def objects_in(sql: str, raws: list[Any]) -> dict[ObjectRef, list[DDLObject]]:
    """Every tracked object an already-parsed schema still declares, bucketed by reference.

    *raws* are the statements :func:`pglast.parse_sql` returned for *sql*; the
    caller passes its own parse rather than this module taking a second one, so
    a schema is read once however many walkers ask about it.

    The value is a **list** because :class:`ObjectRef` is a bucket: two routines
    whose argument types differ only in the schema they name — ``app.f(app.t)``
    and ``app.f(other.t)`` — share one, and are two objects. They are kept in
    source order and separated by :func:`pair_definitions`.

    A ``DROP`` is folded as the walk reaches it, so an object a tree creates and
    later drops is not declared, and the everyday
    ``DROP TABLE IF EXISTS x; CREATE TABLE x (…);`` still declares ``x``.

    A **rename** and a ``SET SCHEMA`` are deliberately *not* folded here, and
    this is the one reader where that is true. Both of this module's renderings
    are of the statement that created the object: rewriting ``CREATE VIEW v`` as
    ``CREATE VIEW v2`` is SQL generation, not parsing, and a ``create_sql`` that
    still said ``v`` would put the wrong name in a generated migration. So a tree
    that renames a tracked object declares it under its old name here, while the
    lint inventory — which holds no definition to go stale — folds the rename.
    """
    objects: dict[ObjectRef, list[DDLObject]] = {}
    for raw in raws:
        found = object_of(sql, raw)
        if found is not None:
            objects.setdefault(found.ref, []).append(found)
            continue
        for edit in object_edits(raw.stmt):
            if edit.kind == "drop":
                _apply_drop(objects, edit)
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
