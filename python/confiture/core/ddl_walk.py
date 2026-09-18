"""Helpers shared by the AST walkers that read DDL, and what a statement means for a schema.

The replica classifier (``core/replica/classifier.py``) and the change-set
walker (``core/change_set/walker.py``) feed two verdicts — replica
forward-compatibility and risk tier — from the same pglast nodes. What
"nullable", "has a default" and "the type as written" mean must be one
definition, so it lives here.

So does the other half: what a statement *does to the schema a DDL tree
declares*. A build-from-DDL tree is read by two walkers with unrelated object
models — the lint inventory and the differ — and each used to decide for itself
which statements change what a tree declares. :func:`column_edit` answers for
the ``ALTER TABLE`` subcommands and :func:`object_edits` for the statement kinds
that are not ``ALTER TABLE`` at all, both in neither reader's vocabulary. The
tables beside them say which of pglast's members are answered for and, for the
rest, why not — because a member nobody considered looks exactly like one that
was decided (#288, #301).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

from pglast import ast as _pg_ast

from confiture.core._pglast_enums import member as _pg_member

_CONSTR_NOTNULL = _pg_member("ConstrType", "CONSTR_NOTNULL")
_CONSTR_DEFAULT = _pg_member("ConstrType", "CONSTR_DEFAULT")

# Resolved BY NAME, never by literal ordinal (#192).
_AT_ADD_COLUMN = _pg_member("AlterTableType", "AT_AddColumn")
_AT_DROP_COLUMN = _pg_member("AlterTableType", "AT_DropColumn")
_AT_ALTER_COLUMN_TYPE = _pg_member("AlterTableType", "AT_AlterColumnType")
_AT_ADD_CONSTRAINT = _pg_member("AlterTableType", "AT_AddConstraint")
_CONSTR_PRIMARY = _pg_member("ConstrType", "CONSTR_PRIMARY")


def walk_nodes(node: Any) -> Iterator[Any]:
    """Every parse node under ``node``, itself included, in source order.

    pglast nodes carry their children in ``__slots__``, singly or in a tuple,
    so "walk the tree" is the same three lines wherever it is needed. It lives
    here because it is the only piece the DDL walkers were still each writing
    for themselves.
    """
    if isinstance(node, list | tuple):
        for item in node:
            yield from walk_nodes(item)
        return
    if not isinstance(node, _pg_ast.Node):
        return
    yield node
    for slot in node.__slots__:
        child = getattr(node, slot, None)
        if child is not None and not isinstance(child, str | int | float | bool | bytes):
            yield from walk_nodes(child)


@dataclass(frozen=True)
class ColumnEdit:
    """What one ``AlterTableCmd`` does to a table's columns, in no reader's vocabulary.

    A build-from-DDL tree may append an ``ALTER TABLE`` rather than edit the
    ``CREATE TABLE``, so what a database ends up with is the two together — and
    two readers have to see it: the lint inventory (``core/linting/inventory.py``)
    and the differ (``core/differ.py``). Their object models share nothing, so
    what they share is this *decision*; each applies it to its own types.

    ``kind`` is the decision. ``column`` names the target for every kind but
    ``add``, where the name is inside ``coldef`` — ``AT_AlterColumnType`` puts it
    on ``cmd.name`` and leaves the ``ColumnDef`` anonymous, and
    ``AT_AddColumn`` does the opposite. ``default`` carries the expression of a
    ``SET DEFAULT``.

    ``ADD COLUMN IF NOT EXISTS`` is the same edit as ``ADD COLUMN``:
    ``cmd.missing_ok`` is deliberately not carried, because an expected schema
    records what a column *is*, not whether the tree guarded its creation. The
    day something needs to tell them apart, this is the docstring that was
    wrong.

    A cmd this module does not model yields ``None`` — never a silently-empty
    edit, which is how a renumbered enum member disappeared in #192.
    """

    kind: Literal[
        "add",
        "drop",
        "retype",
        "set_not_null",
        "drop_not_null",
        "set_default",
        "drop_default",
    ]
    column: str | None = None
    coldef: Any | None = None
    default: Any | None = None


def _is_column_def(definition: Any) -> bool:
    return definition is not None and type(definition).__name__ == "ColumnDef"


def _added_column(cmd: Any) -> ColumnEdit | None:
    definition = getattr(cmd, "def_", None)
    return ColumnEdit("add", coldef=definition) if _is_column_def(definition) else None


def _dropped_column(cmd: Any) -> ColumnEdit | None:
    name = getattr(cmd, "name", None)
    return ColumnEdit("drop", column=str(name)) if name else None


def _retyped_column(cmd: Any) -> ColumnEdit | None:
    definition = getattr(cmd, "def_", None)
    name = getattr(cmd, "name", None)
    if not name or not _is_column_def(definition):
        return None
    return ColumnEdit("retype", column=str(name), coldef=definition)


def _set_not_null(cmd: Any) -> ColumnEdit | None:
    name = getattr(cmd, "name", None)
    return ColumnEdit("set_not_null", column=str(name)) if name else None


def _drop_not_null(cmd: Any) -> ColumnEdit | None:
    name = getattr(cmd, "name", None)
    return ColumnEdit("drop_not_null", column=str(name)) if name else None


def _column_default(cmd: Any) -> ColumnEdit | None:
    """``SET DEFAULT`` and ``DROP DEFAULT``, which are one ``AlterTableType`` member.

    They are told apart by ``cmd.def_``, not by a second member. Reading the
    member alone turns a ``DROP DEFAULT`` into a ``SET DEFAULT None`` — right by
    accident today, and wrong the moment anything distinguishes "no default"
    from "default removed".
    """
    name = getattr(cmd, "name", None)
    if not name:
        return None
    expression = getattr(cmd, "def_", None)
    if expression is None:
        return ColumnEdit("drop_default", column=str(name))
    return ColumnEdit("set_default", column=str(name), default=expression)


#: ``AlterTableType`` member name -> how to read one cmd of that subtype. A table
#: rather than an ``elif`` chain so that adding a subtype is a row, and keyed by
#: *name* so that :data:`FOLDED` and the ordinal dispatch cannot disagree about
#: which subtypes are folded.
_COLUMN_EDITS_BY_NAME: dict[str, Callable[[Any], ColumnEdit | None]] = {
    "AT_AddColumn": _added_column,
    "AT_DropColumn": _dropped_column,
    "AT_AlterColumnType": _retyped_column,
    "AT_SetNotNull": _set_not_null,
    "AT_DropNotNull": _drop_not_null,
    "AT_ColumnDefault": _column_default,
}

#: The subtypes an expected schema is built from. Read by
#: ``tests/unit/test_alter_subtypes_are_exhaustive.py``, which requires every
#: member of pglast's own enum to be here, in :data:`MODELLED_ELSEWHERE`, or in
#: :data:`NOT_AN_EXPECTED_SCHEMA_FACT` with a reason.
FOLDED: frozenset[str] = frozenset(_COLUMN_EDITS_BY_NAME)

_COLUMN_EDITS: dict[int, Callable[[Any], ColumnEdit | None]] = {
    _pg_member("AlterTableType", name): build for name, build in _COLUMN_EDITS_BY_NAME.items()
}


def column_edit(cmd: Any) -> ColumnEdit | None:
    """What ``cmd`` does to a table's columns, or ``None`` for a subtype not modelled.

    Which subtypes those are, and why each of the other ~60 is not one, is
    :data:`FOLDED` / :data:`MODELLED_ELSEWHERE` / :data:`NOT_AN_EXPECTED_SCHEMA_FACT`
    below — enumerated against pglast's own enum by
    ``tests/unit/test_alter_subtypes_are_exhaustive.py``.
    """
    build = _COLUMN_EDITS.get(enum_int(getattr(cmd, "subtype", None)))
    return build(cmd) if build is not None else None


#: ``AlterTableType`` members an expected schema is built from some *other* way,
#: with where.
MODELLED_ELSEWHERE: dict[str, str] = {
    "AT_AddConstraint": (
        "`adds_primary_key` above sets the table's primary-key flag, and "
        "`differ._collect_alter_table_constraints` models FK / CHECK / UNIQUE for "
        "`migrate diff`. A table-level constraint is the table's fact, not a column's"
    ),
    "AT_ChangeOwner": (
        "ownership is its own expectation and its own drift type (`wrong_owner`), "
        "read from the live catalogue rather than folded out of DDL"
    ),
}

#: Every other member, grouped by the reason an expected schema does not model
#: the fact it changes. Each reason is written once; every member name appears.
_NOT_A_FACT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "the parser produces it only for its own rewriting and for `pg_dump` output; "
        "no authored `ALTER TABLE` yields one — `ADD CONSTRAINT … UNIQUE USING INDEX` "
        "is an `AT_AddConstraint`, measured — so a DDL tree never carries it",
        (
            "AT_AddColumnToView",
            "AT_CookedColumnDefault",
            "AT_AddIndex",
            "AT_ReAddIndex",
            "AT_AddIndexConstraint",
            "AT_ReAddConstraint",
            "AT_ReAddDomainConstraint",
            "AT_ReAddComment",
            "AT_ReAddStatistics",
        ),
    ),
    (
        "constraints are read from the live database and never compared: the expected "
        "side has no constraint reader at all, so folding a constraint change would "
        "change nothing anything asks for. If that comparison lands, this group moves",
        ("AT_DropConstraint", "AT_AlterConstraint", "AT_ValidateConstraint"),
    ),
    (
        "a generated column's expression is modelled on neither side — PostgreSQL "
        "keeps it in `attgenerated`, and what a column records here is the text of a "
        "*default*, which a generated expression is not",
        ("AT_SetExpression", "AT_DropExpression"),
    ),
    (
        "an identity is not a default: measured on PostgreSQL 18.4, an identity column "
        "has `attidentity` set, **no** `pg_attrdef` row and a NULL "
        "`information_schema.column_default`, where a `serial` has `nextval(…)`. So "
        "there is no default fact to fold, and defaults are not compared in any case",
        ("AT_AddIdentity", "AT_SetIdentity", "AT_DropIdentity"),
    ),
    (
        "a per-column storage or planner attribute: it changes how PostgreSQL keeps or "
        "estimates the column, never what type it is, whether it accepts NULL, or "
        "whether it exists",
        (
            "AT_SetStatistics",
            "AT_SetOptions",
            "AT_ResetOptions",
            "AT_SetStorage",
            "AT_SetCompression",
            "AT_AlterColumnGenericOptions",
        ),
    ),
    (
        "a table-level storage or physical property — where the heap lives, how it is "
        "clustered, whether it is logged, what access method or options it uses. None "
        "of it is a schema shape a deploy can drift on in the sense this compares",
        (
            "AT_ClusterOn",
            "AT_DropCluster",
            "AT_SetLogged",
            "AT_SetUnLogged",
            "AT_DropOids",
            "AT_SetAccessMethod",
            "AT_SetTableSpace",
            "AT_SetRelOptions",
            "AT_ResetRelOptions",
            "AT_ReplaceRelOptions",
            "AT_GenericOptions",
        ),
    ),
    (
        "trigger and rule *enablement*, which is a state a trigger or rule is in and "
        "not whether it exists; existence is compared from the live catalogue",
        (
            "AT_EnableTrig",
            "AT_EnableAlwaysTrig",
            "AT_EnableReplicaTrig",
            "AT_DisableTrig",
            "AT_EnableTrigAll",
            "AT_DisableTrigAll",
            "AT_EnableTrigUser",
            "AT_DisableTrigUser",
            "AT_EnableRule",
            "AT_EnableAlwaysRule",
            "AT_EnableReplicaRule",
            "AT_DisableRule",
        ),
    ),
    (
        "row-level security is an access-control fact, in the same family as grants and "
        "ownership, and is compared — where it is compared — from the live catalogue",
        (
            "AT_EnableRowSecurity",
            "AT_DisableRowSecurity",
            "AT_ForceRowSecurity",
            "AT_NoForceRowSecurity",
        ),
    ),
    (
        "inheritance and typed tables add no column: PostgreSQL requires the child to "
        "hold every parent column *already* — `ALTER TABLE t INHERIT p` on a table "
        'missing one is `child table is missing column "b"`, measured — so there is '
        "nothing for a column fold to do",
        ("AT_AddInherit", "AT_DropInherit", "AT_AddOf", "AT_DropOf"),
    ),
    (
        "partition membership, which the columns must already match; the inventory "
        "records `is_partition` from a `CREATE TABLE … PARTITION OF` and drift compares "
        "a partition like any other table",
        ("AT_AttachPartition", "AT_DetachPartition", "AT_DetachPartitionFinalize"),
    ),
    (
        "replica identity decides what a replica sees of an UPDATE, which is the "
        "replica classifier's question about an operation, not a shape to compare",
        ("AT_ReplicaIdentity",),
    ),
)

#: Member -> why an expected schema does not model what it changes.
NOT_AN_EXPECTED_SCHEMA_FACT: dict[str, str] = {
    member: reason for reason, members in _NOT_A_FACT_GROUPS for member in members
}


@dataclass(frozen=True)
class ObjectEdit:
    """What one statement that is not ``ALTER TABLE`` does to an object a tree declares.

    ``DROP TABLE``, ``ALTER TABLE … RENAME COLUMN``, ``ALTER TABLE … RENAME TO``
    and ``ALTER TABLE … SET SCHEMA`` are a ``DropStmt``, two ``RenameStmt`` and
    an ``AlterObjectSchemaStmt`` — not ``AlterTableStmt``, so folding the
    subcommands reaches none of them. A tree that created and then dropped a
    table still expected it: one critical ``missing_table`` on a database that
    matches the tree exactly, which is #301's defect class one node type over.

    ``object_kind`` is the vocabulary the lint inventory and ``ddl_objects``
    share (``table``, ``view``, ``function``, …). ``name`` is the object's own
    name, except for the kinds PostgreSQL names *per table* — a trigger, a
    policy, a rule — where it is ``table.name``, because two tables may each
    have a ``trg_touch`` and they are two objects. ``arg_types`` carries a
    routine's argument types as written, since a routine's identity is its
    arguments; ``None`` means the statement named no argument list
    (``DROP FUNCTION f``), which matches any overload.

    A ``DROP … CASCADE`` takes dependents with it, and this does not model them:
    the tree's author knows what they are and PostgreSQL's dependency graph is
    not something to reimplement in a parser. A dependent view left in the
    expected set reports as missing — a false positive that names a real
    ambiguity, and better than a guess.
    """

    kind: Literal["drop", "rename", "rename_column", "set_schema"]
    object_kind: str
    schema: str | None
    name: str
    column: str | None = None
    new_name: str | None = None
    new_schema: str | None = None
    arg_types: tuple[str, ...] | None = None


#: ``ObjectType`` member -> the kind vocabulary the inventory and ``ddl_objects``
#: use. A member absent here yields no edit, which keeps the object in the
#: expected schema: an unfolded drop reports a *false* missing object, which is
#: loud, where an over-eager fold silently stops expecting something real.
_OBJECT_KINDS_BY_NAME: dict[str, str] = {
    "OBJECT_TABLE": "table",
    "OBJECT_VIEW": "view",
    "OBJECT_MATVIEW": "matview",
    "OBJECT_FOREIGN_TABLE": "foreign_table",
    "OBJECT_SEQUENCE": "sequence",
    "OBJECT_INDEX": "index",
    "OBJECT_TYPE": "type",
    "OBJECT_DOMAIN": "domain",
    "OBJECT_SCHEMA": "schema",
    "OBJECT_EXTENSION": "extension",
    "OBJECT_FUNCTION": "function",
    "OBJECT_PROCEDURE": "procedure",
    "OBJECT_ROUTINE": "routine",
    "OBJECT_AGGREGATE": "aggregate",
    "OBJECT_TRIGGER": "trigger",
    "OBJECT_POLICY": "policy",
    "OBJECT_RULE": "rule",
}

_OBJECT_KINDS: dict[int, str] = {
    _pg_member("ObjectType", name): kind for name, kind in _OBJECT_KINDS_BY_NAME.items()
}

_OBJECT_COLUMN = _pg_member("ObjectType", "OBJECT_COLUMN")

#: One statement kind names several object kinds: ``DROP ROUTINE f(int)`` drops a
#: function, a procedure or an aggregate, whichever ``f`` turns out to be, and a
#: reader of a tree does not know which until it looks.
_KIND_ALIASES: dict[str, tuple[str, ...]] = {"routine": ("function", "procedure", "aggregate")}


def object_kinds(kind: str) -> tuple[str, ...]:
    """The kinds an :attr:`ObjectEdit.object_kind` may name — usually just itself."""
    return _KIND_ALIASES.get(kind, (kind,))


#: Kinds PostgreSQL names per table, whose ``name`` is therefore ``table.name``.
_PER_TABLE_KINDS: frozenset[str] = frozenset({"trigger", "policy", "rule"})

#: ``DROP TRIGGER trg ON t`` names two parts (table, trigger) and three when the
#: table is schema-qualified.
_PER_TABLE_PARTS = 2
_PER_TABLE_PARTS_QUALIFIED = 3


def _string_parts(entry: Any) -> list[str]:
    """The ``String`` parts of a name, however pglast wrapped it.

    ``DROP TABLE core.t`` gives a tuple of two ``String``; ``DROP SCHEMA s``
    gives a bare one; ``DROP TYPE core.e`` gives a ``TypeName``. All three are
    the same question.
    """
    if isinstance(entry, list | tuple):
        return [str(part.sval) for part in entry if getattr(part, "sval", None)]
    names = getattr(entry, "names", None)
    if names is not None:
        return [str(part.sval) for part in names if getattr(part, "sval", None)]
    sval = getattr(entry, "sval", None)
    return [str(sval)] if sval else []


def _dropped_object(kind: str, entry: Any) -> ObjectEdit | None:
    """One entry of ``DropStmt.objects`` as an edit, or ``None`` when unreadable."""
    objname = getattr(entry, "objname", None)
    if objname is not None:
        # A routine: `ObjectWithArgs`, whose identity includes its arguments.
        parts = _string_parts(objname)
        args = (
            None
            if getattr(entry, "args_unspecified", False)
            else tuple(type_name(arg) or "" for arg in getattr(entry, "objargs", None) or ())
        )
        schema, name = _split_last(parts)
        return None if name is None else ObjectEdit("drop", kind, schema, name, arg_types=args)
    parts = _string_parts(entry)
    if kind in _PER_TABLE_KINDS:
        # `DROP TRIGGER trg ON core.t` -> ('core', 't', 'trg'); the object is
        # `t.trg` in schema `core`, which is how `ddl_objects` keys it.
        if len(parts) < _PER_TABLE_PARTS:
            return None
        schema = parts[0] if len(parts) >= _PER_TABLE_PARTS_QUALIFIED else None
        return ObjectEdit("drop", kind, schema, f"{parts[-2]}.{parts[-1]}")
    schema, name = _split_last(parts)
    return None if name is None else ObjectEdit("drop", kind, schema, name)


def _split_last(parts: list[str]) -> tuple[str | None, str | None]:
    """``(schema, name)`` of a dotted name; a single part has no schema."""
    if not parts:
        return (None, None)
    if len(parts) == 1:
        return (None, parts[0])
    return (parts[-2], parts[-1])


def _drop_edits(stmt: Any) -> list[ObjectEdit]:
    kind = _OBJECT_KINDS.get(enum_int(getattr(stmt, "removeType", None)))
    if kind is None:
        return []
    found = [_dropped_object(kind, entry) for entry in getattr(stmt, "objects", None) or ()]
    return [edit for edit in found if edit is not None]


def _renamed(stmt: Any) -> list[ObjectEdit]:
    rename_type = enum_int(getattr(stmt, "renameType", None))
    new_name = getattr(stmt, "newname", None)
    subname = getattr(stmt, "subname", None)
    schema, relname = relation_parts(getattr(stmt, "relation", None))
    if rename_type == _OBJECT_COLUMN:
        if not (relname and subname and new_name):
            return []
        return [
            ObjectEdit(
                "rename_column",
                "table",
                schema,
                str(relname),
                column=str(subname),
                new_name=str(new_name),
            )
        ]
    kind = _OBJECT_KINDS.get(rename_type)
    if kind is None or not new_name:
        return []
    if kind in _PER_TABLE_KINDS:
        if not (relname and subname):
            return []
        return [
            ObjectEdit(
                "rename",
                kind,
                schema,
                f"{relname}.{subname}",
                new_name=f"{relname}.{new_name}",
            )
        ]
    name_schema, name = _relation_or_object(stmt)
    if name is None:
        return []
    return [ObjectEdit("rename", kind, name_schema, name, new_name=str(new_name))]


def _relation_or_object(stmt: Any) -> tuple[str | None, str | None]:
    """``(schema, name)`` of the thing a ``RenameStmt`` / ``AlterObjectSchemaStmt`` names.

    A relation sits on ``relation`` as a ``RangeVar``; everything else sits on
    ``object``, as a name list or a ``TypeName``.
    """
    schema, relname = relation_parts(getattr(stmt, "relation", None))
    if relname:
        return (schema, str(relname))
    return _split_last(_string_parts(getattr(stmt, "object", None)))


def _moved(stmt: Any) -> list[ObjectEdit]:
    kind = _OBJECT_KINDS.get(enum_int(getattr(stmt, "objectType", None)))
    new_schema = getattr(stmt, "newschema", None)
    if kind is None or not new_schema:
        return []
    schema, name = _relation_or_object(stmt)
    if name is None:
        return []
    return [ObjectEdit("set_schema", kind, schema, name, new_schema=str(new_schema))]


#: Statement node -> how to read what it does to the objects a tree declares.
_OBJECT_EDITS_BY_NODE: dict[str, Callable[[Any], list[ObjectEdit]]] = {
    "DropStmt": _drop_edits,
    "RenameStmt": _renamed,
    "AlterObjectSchemaStmt": _moved,
}

#: The statement kinds an expected schema is built from besides ``AlterTableStmt``.
#: Read by ``tests/unit/test_ddl_statement_kinds_are_exhaustive.py``.
FOLDED_STATEMENTS: frozenset[str] = frozenset(_OBJECT_EDITS_BY_NODE)


def object_edits(stmt: Any) -> list[ObjectEdit]:
    """What ``stmt`` does to the objects a DDL tree declares; ``[]`` when nothing.

    A list because one statement may carry several edits (``DROP TABLE a, b``).
    An unmodelled statement, or one naming a kind no expected schema models,
    yields no edit at all rather than a partial one.
    """
    read = _OBJECT_EDITS_BY_NODE.get(type(stmt).__name__)
    return read(stmt) if read is not None else []


#: Statement kinds an expected schema reaches some other way, with where.
MODELLED_STATEMENTS: dict[str, str] = {
    "AlterTableStmt": (
        "its subcommands are `column_edit` and `adds_primary_key` above, each "
        "member of `AlterTableType` accounted for in FOLDED / MODELLED_ELSEWHERE / "
        "NOT_AN_EXPECTED_SCHEMA_FACT"
    ),
    "AlterOwnerStmt": (
        "ownership is its own expectation and its own drift type (`wrong_owner`), "
        "read from the live catalogue rather than folded out of DDL"
    ),
    "AlterDefaultPrivilegesStmt": (
        "default privileges are grants, which `AclDriftDetector` compares against "
        "the `acls:` config rather than against a DDL tree"
    ),
}

#: Every other ``Alter…`` / ``Drop…`` / ``Rename…`` statement, grouped by the
#: reason an expected schema does not model what it changes.
_NOT_A_STATEMENT_FACT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "cluster-scoped: a role, a database, a tablespace or a subscription is not "
        "in a schema, and `confiture build` never creates one either — the same "
        "reason `ddl_objects.NOT_A_SCHEMA_OBJECT` declines their `CREATE`",
        (
            "AlterRoleStmt",
            "AlterRoleSetStmt",
            "DropRoleStmt",
            "DropOwnedStmt",
            "AlterDatabaseStmt",
            "AlterDatabaseSetStmt",
            "AlterDatabaseRefreshCollStmt",
            "DropdbStmt",
            "AlterTableSpaceOptionsStmt",
            "DropTableSpaceStmt",
            "AlterTableMoveAllStmt",
            "AlterSystemStmt",
            "AlterSubscriptionStmt",
            "DropSubscriptionStmt",
            "AlterPublicationStmt",
        ),
    ),
    (
        "it changes an object's *contents* or options rather than which objects "
        "exist and what shape they are: an added enum label, a sequence's "
        "increment, a domain's constraint, a routine's volatility. A comparison of "
        "those is a comparison this reader does not make",
        (
            "AlterEnumStmt",
            "AlterSeqStmt",
            "AlterDomainStmt",
            "AlterFunctionStmt",
            "AlterTypeStmt",
            "AlterOperatorStmt",
            "AlterOpFamilyStmt",
            "AlterStatsStmt",
            "AlterCollationStmt",
            "AlterTSDictionaryStmt",
            "AlterTSConfigurationStmt",
            "AlterPolicyStmt",
            "AlterEventTrigStmt",
        ),
    ),
    (
        "foreign-data plumbing: a wrapper, a server or a user mapping is a "
        "connection, and a connection has no business in a schema tree — the "
        "reason `CreateSubscriptionStmt` is declined next door",
        (
            "AlterFdwStmt",
            "AlterForeignServerStmt",
            "AlterUserMappingStmt",
            "DropUserMappingStmt",
        ),
    ),
    (
        "extension membership, not schema shape: `ALTER EXTENSION … ADD/DROP` moves "
        "an object in or out of an extension's ownership, and an extension arrives "
        "as `CREATE EXTENSION`, which is tracked",
        ("AlterExtensionStmt", "AlterExtensionContentsStmt"),
    ),
    (
        "it changes what an object *depends on* rather than what it is: "
        "`ALTER … DEPENDS ON EXTENSION` only says what a drop cascades to",
        ("AlterObjectDependsStmt",),
    ),
)

#: Statement kind -> why an expected schema does not model what it changes.
NOT_AN_EXPECTED_SCHEMA_STATEMENT: dict[str, str] = {
    kind: reason for reason, kinds in _NOT_A_STATEMENT_FACT_GROUPS for kind in kinds
}


def adds_primary_key(cmd: Any) -> bool:
    """Whether ``cmd`` is an ``ADD CONSTRAINT … PRIMARY KEY``.

    Not a :class:`ColumnEdit`: a table-level constraint is the table's fact, not
    a column's, and folding it into the column vocabulary would make every
    reader unpack something it did not ask for. It lives here for the same
    reason ``column_edit`` does — one module knows what an ``AlterTableType``
    member means, because a literal ordinal silently stopped matching once
    already (#192).
    """
    if enum_int(getattr(cmd, "subtype", None)) != _AT_ADD_CONSTRAINT:
        return False
    definition = getattr(cmd, "def_", None)
    return enum_int(getattr(definition, "contype", None)) == _CONSTR_PRIMARY


def routine_body(stmt: Any) -> tuple[str | None, str | None]:
    """``(language, body text)`` of a ``CreateFunctionStmt``, both as written.

    The body of a ``LANGUAGE c`` routine is a shared-object symbol rather than
    SQL, which is why the language comes back with it: every caller has to
    decide what the text it is holding actually is.
    """
    language: str | None = None
    body: str | None = None
    for opt in getattr(stmt, "options", None) or ():
        args = opt.arg if isinstance(opt.arg, tuple | list) else [opt.arg]
        values = [getattr(a, "sval", None) for a in args]
        if opt.defname == "language":
            language = values[0].lower() if values and values[0] else None
        elif opt.defname == "as":
            body = values[0] if values else None
    return language, body


def enum_int(value: object) -> int | None:
    """The ordinal of a pglast enum value (or ``None`` when it is not one)."""
    if value is None:
        return None
    inner = getattr(value, "value", value)
    try:
        return int(inner)
    except (TypeError, ValueError):
        return None


def relation_parts(relation: object) -> tuple[str | None, str | None]:
    """``(schemaname, relname)`` of a pglast ``RangeVar``, as pglast spells them."""
    if relation is None:
        return (None, None)
    return (getattr(relation, "schemaname", None), getattr(relation, "relname", None))


def qualified_relname(relation: object) -> str | None:
    """``schema.name`` (schema only when present) of a ``RangeVar``, as pglast spells it."""
    if relation is None:
        return None
    relname = getattr(relation, "relname", None)
    if not relname:
        return None
    # pglast has already folded unquoted identifiers; a quoted "MyTable" keeps its case.
    schema = getattr(relation, "schemaname", None)
    return f"{schema}.{relname}" if schema else str(relname)


def name_parts(raw: Any) -> str | None:
    """Join a pglast list of ``String`` name parts into a dotted identifier."""
    parts = [str(getattr(part, "sval", part)) for part in raw or ()]
    return ".".join(part.lower() for part in parts if part) or None


def column_is_not_null(coldef: object) -> bool:
    if bool(getattr(coldef, "is_not_null", False)):
        return True
    for c in getattr(coldef, "constraints", None) or ():
        if enum_int(getattr(c, "contype", None)) == _CONSTR_NOTNULL:
            return True
    return False


def column_has_default(coldef: object) -> bool:
    if getattr(coldef, "raw_default", None) is not None:
        return True
    for c in getattr(coldef, "constraints", None) or ():
        if enum_int(getattr(c, "contype", None)) == _CONSTR_DEFAULT:
            return True
    return False


def type_name(type_node: Any) -> str | None:
    """Render a pglast ``TypeName`` back to ``varchar(50)`` / ``numeric(10,2)[]``.

    The ``pg_catalog`` qualifier the parser adds is dropped; the internal spelling
    (``int8``) is left alone, since :mod:`confiture.core.type_lattice` aliases it.

    The array bounds are **not** dropped. They live on ``arrayBounds`` rather
    than in ``names``, and reading only ``names`` made ``int[]`` render ``int4`` —
    the same string as ``int``. Both callers compose this with ``canonical_type``
    over an ``ALTER COLUMN … TYPE``, so a column going ``varchar(50)`` to
    ``text[]`` was captured as ``text`` and compared as a free, rewrite-less
    widening (#275).
    """
    if type_node is None:
        return None
    parts = [str(getattr(part, "sval", part)) for part in getattr(type_node, "names", None) or ()]
    names = [part for part in parts if part and part != "pg_catalog"]
    if not names:
        return None
    name = ".".join(names)
    mods = [
        str(ival)
        for ival in (
            getattr(getattr(mod, "val", None), "ival", None)
            for mod in getattr(type_node, "typmods", None) or ()
        )
        if ival is not None
    ]
    bounds = "[]" * len(getattr(type_node, "arrayBounds", None) or ())
    return (f"{name}({', '.join(mods)})" if mods else name) + bounds
