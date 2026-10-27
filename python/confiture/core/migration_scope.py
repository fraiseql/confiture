"""One migration scope: what the statements before this one did, as every classifier reads it.

A statement in a migration is judged in the context of the file that holds it:
the transaction it runs in, a constraint an earlier statement added, a TVIEW an
earlier statement dropped. :func:`walk` folds a file's statements in order and
hands each classifier — the replica verdict, the change set, the TVIEW preflight
— the same context, so two verdicts on one file cannot read it two ways
(ARCHITECTURE Decision 9: independent classifiers, one scope).

**Each fact states its matching direction.** A fact that makes a verdict
*stricter* matches by identity — the schema a statement leaves out is the
default one — because a false match errs safe: a constraint the file added is
one whose validation scans under the ADD's lock (``lock_risky``). A fact that
makes a verdict *looser* must not match more than the statement says: a TVIEW
the file dropped silences what a later statement does to its base table, so it
is keyed as :mod:`tview_preflight` always keyed it, and a fact this module cannot
read is never assumed.

**A relation the file creates** is the loosening fact the classifiers share
(:meth:`Scope.exempts`). PostgreSQL proves it new only when the statement can
fail on an existing one — a plain ``CREATE TABLE``, ``CREATE TABLE … AS``,
``CREATE MATERIALIZED VIEW`` or ``tviews.pg_tviews_create()`` — so no session
outside the migration can read or write it yet, and an operation on it breaks
nothing that existed. It is kept under the schema and name as written: an
unqualified ``t`` never exempts ``public.t``. Anything that could move it, hide
it or reach past it forgets it: a drop, rename onto, ``SET SCHEMA`` or
``DROP SCHEMA`` under any spelling of its name, a ``search_path`` change (the
unqualified ones), ``ATTACH PARTITION`` / ``INHERIT`` into it, and any statement
this module cannot read — ``DO``, ``CALL``, ``EXECUTE``, a function call — which
forgets them all.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import Any

from confiture.core._pglast_enums import member as _pg_member
from confiture.core.ddl_walk import (
    enum_int,
    object_edits,
    read_constraint,
    relation_name,
    tview_calls,
    walk_nodes,
)
from confiture.core.migration_analyzer import runs_in_one_transaction
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import TVIEW_PREFIX, Constraint
from confiture.core.sql_lexer import ParsedStatement, parse

__all__ = ["EXEMPT", "AddedConstraint", "Created", "Scope", "Step", "Target", "targets", "walk"]

_AT_ADD_CONSTRAINT = _pg_member("AlterTableType", "AT_AddConstraint")
_AT_DROP_CONSTRAINT = _pg_member("AlterTableType", "AT_DropConstraint")

#: A constraint's key with its schema as written (``None`` when the statement left it out).
WrittenKey = tuple[str | None, str, str]
#: Subcommands that join a relation to one that already existed.
_AT_JOINS_ANOTHER = frozenset(
    {
        _pg_member("AlterTableType", "AT_AttachPartition"),
        _pg_member("AlterTableType", "AT_AddInherit"),
    }
)

#: What an operation on a relation the same migration created may be, in the change
#: set's vocabulary: each changes a relation no other session can see yet. A kind
#: absent here is judged as on any relation.
EXEMPT: frozenset[str] = frozenset(
    {
        "add_column",
        "add_constraint",
        "alter_column_type",
        "cluster",
        "create_index",
        "drop_column",
        "drop_column_default",
        "drop_constraint",
        "drop_materialized_view",
        "drop_not_null",
        "drop_table",
        "refresh_materialized_view",
        "reindex",
        "rename_column",
        "rename_object",
        "set_column_default",
        "set_not_null",
        "truncate",
        "validate_constraint",
    }
)
#: The object kinds a relation's name is shared with: dropping or moving one of
#: them under a created relation's name forgets it.
_RELATION_KINDS = frozenset({"table", "view", "matview", "foreign_table", "sequence", "tview"})
#: Statements whose effect this module cannot read when they call a function.
_MAY_CALL = frozenset({"SelectStmt", "InsertStmt", "UpdateStmt", "DeleteStmt", "MergeStmt"})
_OPAQUE = frozenset({"DoStmt", "CallStmt", "ExecuteStmt"})

_DROP_CASCADE = _pg_member("DropBehavior", "DROP_CASCADE")

#: ``(schema as written, name)``; ``schema`` is ``None`` when the statement wrote none.
type Written = tuple[str | None, str]


@dataclass(frozen=True)
class Target:
    """The relation one operation of a statement acts on, and what else it may reach.

    ``cascade`` is a ``CASCADE`` the statement carries; ``references`` are the
    relations a foreign key it declares points at, as written.
    """

    relation: Written
    cascade: bool = False
    references: tuple[Written, ...] = ()


@dataclass(frozen=True)
class AddedConstraint:
    """A constraint an earlier statement of the file added: what its ``ADD`` locked.

    ``referenced`` is a foreign key's target as written, for a finding to name.
    """

    foreign_key: bool
    not_valid: bool
    referenced: str | None


@dataclass(frozen=True)
class Created:
    """A relation an earlier statement of the file created, and PostgreSQL proved new.

    ``references_existing`` is whether it holds a foreign key to a relation the
    file did not create: dropping it then takes a lock on that one.
    """

    references_existing: bool = False


@dataclass(frozen=True)
class Scope:
    """What the statements before one did, in the file that holds them.

    ``transactional`` is whether the file runs as one transaction
    (:func:`~confiture.core.migration_analyzer.runs_in_one_transaction`): when it
    does not, each statement commits on its own and nothing an earlier one locked
    is still held.
    """

    transactional: bool = True
    #: ``(schema, table, name)``, the schema defaulted: a tightening fact.
    constraints: dict[tuple[str, str, str], AddedConstraint] = field(default_factory=dict)
    #: The same constraints keyed as written: a loosening fact (a later ``DROP
    #: CONSTRAINT`` of one drops nothing that existed before the file). Only an
    #: ``ALTER TABLE`` keeps it: any other statement may have dropped the
    #: constraint and added another under its name, so the fact is forgotten.
    written_constraints: dict[WrittenKey, AddedConstraint] = field(default_factory=dict)
    #: ``schema.tv_name``, case-folded, as ``tview_preflight`` keys a TVIEW.
    dropped_tviews: frozenset[str] = frozenset()
    #: Keyed as written: a loosening fact.
    created: dict[Written, Created] = field(default_factory=dict)
    default_schema: str = DEFAULT_SCHEMA

    def added_constraint(
        self, schema: str | None, table: str | None, name: str | None
    ) -> AddedConstraint | None:
        """The constraint ``table.name`` an earlier statement added, matched by identity."""
        if table is None or name is None:
            return None
        return self.constraints.get((schema or self.default_schema, table, name))

    def added_as_written(
        self, schema: str | None, table: str | None, name: str | None
    ) -> AddedConstraint | None:
        """The constraint an earlier statement added, named exactly as this statement names it."""
        if table is None or name is None:
            return None
        return self.written_constraints.get((schema, table, name))

    def fresh(self, schema: str | None, name: str | None) -> Created | None:
        """The relation ``schema.name`` an earlier statement created, matched as written."""
        return None if name is None else self.created.get((schema, name))

    def exempts(
        self,
        kind: str,
        schema: str | None,
        name: str | None,
        *,
        cascade: bool = False,
        references: Written | None = None,
    ) -> bool:
        """Whether an operation of *kind* on ``schema.name`` reaches only a relation the file created.

        *cascade* is a ``CASCADE`` the statement carries, which reaches its
        dependents; *references* is the relation a foreign key it adds points at,
        which it locks. Dropping a created relation that holds a key to one the
        file did not create locks that one too.
        """
        created = self.fresh(schema, name)
        if created is None or kind not in EXEMPT or cascade:
            return False
        if kind in ("drop_table", "drop_materialized_view") and created.references_existing:
            return False
        return references is None or self._created_or_self(references, (schema, name))

    def exempts_target(self, kind: str, target: Target | None) -> bool:
        """:meth:`exempts` for an operation of *kind* on *target* (:func:`targets`)."""
        if target is None:
            return False
        schema, name = target.relation
        if not target.references:
            return self.exempts(kind, schema, name, cascade=target.cascade)
        return all(
            self.exempts(kind, schema, name, cascade=target.cascade, references=ref)
            for ref in target.references
        )

    def _created_or_self(self, target: Written, relation: Written) -> bool:
        return target == relation or self.fresh(*target) is not None


@dataclass(frozen=True)
class Step:
    """One statement, with the scope before it and the scope it leaves."""

    statement: ParsedStatement
    before: Scope
    after: Scope


def walk(sql: str, *, default_schema: str = DEFAULT_SCHEMA) -> Iterator[Step]:
    """Each statement of the migration *sql*, in order, with what came before it.

    Raises:
        pglast.parser.ParseError: PostgreSQL's parser rejects *sql*.
    """
    statements = parse(sql)
    scope = Scope(transactional=runs_in_one_transaction(sql), default_schema=default_schema)
    for statement in statements:
        after = _after(scope, statement.stmt)
        yield Step(statement, scope, after)
        scope = after


def _after(scope: Scope, stmt: Any) -> Scope:
    """The scope *stmt* leaves."""
    dropped = _dropped_tviews(stmt)
    added = _added_constraints(stmt)
    written = _written_after(scope, stmt, added)
    created = _created_after(scope, stmt)
    if (
        not dropped
        and not added
        and written == scope.written_constraints
        and created == scope.created
    ):
        return scope
    return replace(
        scope,
        constraints={
            **scope.constraints,
            **{(key[0] or scope.default_schema, *key[1:]): fact for key, fact in added.items()},
        },
        written_constraints=written,
        dropped_tviews=scope.dropped_tviews | dropped,
        created=created,
    )


def _created_after(scope: Scope, stmt: Any) -> dict[Written, Created]:
    """The relations the file has created once *stmt* ran, each as written."""
    name = type(stmt).__name__
    if name in _OPAQUE or (name in _MAY_CALL and _calls_a_function(stmt)):
        return {}
    created = dict(scope.created)
    if name == "VariableSetStmt" and stmt.name in (None, "search_path"):
        return {key: value for key, value in created.items() if key[0] is not None}
    for edit in object_edits(stmt):
        if edit.object_kind == "schema" and edit.kind == "drop":
            created = {
                key: value for key, value in created.items() if key[0] not in (None, edit.name)
            }
        elif edit.object_kind in _RELATION_KINDS and edit.kind != "rename_column":
            moved = created.get((edit.schema, edit.name))
            created = {key: value for key, value in created.items() if key[1] != edit.name}
            if edit.kind == "rename" and edit.new_name and moved is not None:
                created = {key: value for key, value in created.items() if key[1] != edit.new_name}
                created[(edit.schema, edit.new_name)] = moved
    for call in tview_calls(stmt):
        if call.name is None:
            continue
        if call.action == "create":
            created[(call.schema, call.name)] = Created()
        else:
            created.pop((call.schema, call.name), None)
    return _fold_created(created, stmt)


def _fold_created(created: dict[Written, Created], stmt: Any) -> dict[Written, Created]:
    """*created* once *stmt* creates a relation, joins one to another, or adds a key to one."""
    name = type(stmt).__name__
    if name == "CreateStmt":
        relation = relation_name(stmt.relation)
        if relation is not None and _proves_new(stmt):
            key = (relation.schema, relation.name)
            targets = _key_targets(stmt.tableElts or ())
            created[key] = Created(
                references_existing=any(
                    target != key and target not in created for target in targets
                )
            )
    elif name == "CreateTableAsStmt":
        relation = relation_name(getattr(stmt.into, "rel", None))
        if relation is not None and not stmt.if_not_exists:
            created[(relation.schema, relation.name)] = Created()
    elif name == "AlterTableStmt":
        relation = relation_name(stmt.relation)
        key = None if relation is None else (relation.schema, relation.name)
        if key in created:
            for cmd in stmt.cmds or ():
                if enum_int(cmd.subtype) in _AT_JOINS_ANOTHER:
                    del created[key]
                    break
                targets = _key_targets([getattr(cmd, "def_", None)])
                if any(target != key and target not in created for target in targets):
                    created[key] = Created(references_existing=True)
    return created


def targets(stmt: Any) -> list[Target | None]:
    """What each operation of *stmt* acts on, in the order its classifiers build them.

    One per ``ALTER TABLE`` subcommand, per dropped object, per truncated
    relation; one for an index, a rename, a ``REFRESH``, ``CLUSTER`` or
    ``REINDEX``; ``[]`` for any other statement. ``None`` where the operation
    names no relation this reader can spell.
    """
    name = type(stmt).__name__
    if name == "AlterTableStmt":
        relation = _written(stmt.relation)
        return [
            None
            if relation is None
            else Target(relation, references=tuple(_key_targets([getattr(cmd, "def_", None)])))
            for cmd in stmt.cmds or ()
        ]
    if name in ("IndexStmt", "RenameStmt", "RefreshMatViewStmt", "ClusterStmt", "ReindexStmt"):
        relation = _written(getattr(stmt, "relation", None))
        return [None if relation is None else Target(relation)]
    cascade = enum_int(getattr(stmt, "behavior", None)) == _DROP_CASCADE
    if name == "TruncateStmt":
        return [
            None if (relation := _written(rel)) is None else Target(relation, cascade)
            for rel in stmt.relations or ()
        ]
    if name == "DropStmt":
        return [
            None if (relation := _dropped(obj)) is None else Target(relation, cascade)
            for obj in stmt.objects or ()
        ]
    return []


def _written(relation: Any) -> Written | None:
    named = relation_name(relation)
    return None if named is None else (named.schema, named.name)


def _dropped(obj: Any) -> Written | None:
    """A dropped relation's name as written, from its list of name parts."""
    parts = [getattr(part, "sval", None) for part in obj] if isinstance(obj, list | tuple) else []
    match parts:
        case [str() as name] if name:
            return (None, name)
        case [str() as schema, str() as name] if schema and name:
            return (schema, name)
        case _:
            return None


def _proves_new(stmt: Any) -> bool:
    """A ``CREATE TABLE`` that fails on an existing relation and joins no other one."""
    return not stmt.if_not_exists and not stmt.inhRelations and stmt.partbound is None


def _key_targets(nodes: Any) -> list[Written]:
    """The relation each foreign key among *nodes* points at, as written."""
    targets = []
    for node in walk_nodes(list(nodes)):
        if type(node).__name__ != "Constraint":
            continue
        read = read_constraint(node)
        if isinstance(read, Constraint) and read.ref_table is not None:
            targets.append((read.ref_table.schema, read.ref_table.name))
    return targets


def _calls_a_function(stmt: Any) -> bool:
    """Whether *stmt* calls a function other than pg_tviews' own."""
    calls = sum(1 for node in walk_nodes(stmt) if type(node).__name__ == "FuncCall")
    return calls > len(tview_calls(stmt))


def _written_after(
    scope: Scope, stmt: Any, added: dict[WrittenKey, AddedConstraint]
) -> dict[WrittenKey, AddedConstraint]:
    """The as-written constraints *stmt* leaves: an ``ALTER TABLE`` adds and drops, anything else forgets."""
    if type(stmt).__name__ != "AlterTableStmt":
        return {}
    relation = relation_name(stmt.relation)
    dropped = {
        (relation.schema, relation.name, cmd.name)
        for cmd in stmt.cmds or ()
        if relation is not None and enum_int(cmd.subtype) == _AT_DROP_CONSTRAINT
    }
    kept = {k: v for k, v in scope.written_constraints.items() if k not in dropped}
    return {**kept, **added}


def _added_constraints(stmt: Any) -> dict[WrittenKey, AddedConstraint]:
    """``ALTER TABLE … ADD CONSTRAINT name …``: each named constraint, as written, and what its ADD locks."""
    if type(stmt).__name__ != "AlterTableStmt":
        return {}
    relation = relation_name(stmt.relation)
    if relation is None:
        return {}
    added = {}
    for cmd in stmt.cmds or ():
        node = getattr(cmd, "def_", None)
        name = getattr(node, "conname", None)
        if enum_int(cmd.subtype) != _AT_ADD_CONSTRAINT or not name:
            continue
        read = read_constraint(node)
        foreign_key = isinstance(read, Constraint) and read.kind == "foreign_key"
        target = read.ref_table if isinstance(read, Constraint) and foreign_key else None
        added[(relation.schema, relation.name, name)] = AddedConstraint(
            foreign_key=foreign_key,
            not_valid=bool(getattr(node, "skip_validation", False)),
            referenced=target.qualified if target is not None else None,
        )
    return added


def _dropped_tviews(stmt: Any) -> frozenset[str]:
    """What *stmt* drops of the TVIEWs: ``DROP TABLE tv_*``, or ``tviews.pg_tviews_drop()``."""
    return frozenset(
        f"{(edit.schema or DEFAULT_SCHEMA).lower()}.{edit.name.lower()}"
        for edit in object_edits(stmt)
        if edit.kind == "drop" and edit.name.startswith(TVIEW_PREFIX)
    )
