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
"""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import Any

from confiture.core._pglast_enums import member as _pg_member
from confiture.core.ddl_walk import enum_int, object_edits, read_constraint, relation_name
from confiture.core.migration_analyzer import runs_in_one_transaction
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import TVIEW_PREFIX, Constraint
from confiture.core.sql_lexer import ParsedStatement, parse

__all__ = ["AddedConstraint", "Scope", "Step", "walk"]

_AT_ADD_CONSTRAINT = _pg_member("AlterTableType", "AT_AddConstraint")


@dataclass(frozen=True)
class AddedConstraint:
    """A constraint an earlier statement of the file added: what its ``ADD`` locked.

    ``referenced`` is a foreign key's target as written, for a finding to name.
    """

    foreign_key: bool
    not_valid: bool
    referenced: str | None


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
    #: ``schema.tv_name``, case-folded, as ``tview_preflight`` keys a TVIEW.
    dropped_tviews: frozenset[str] = frozenset()
    default_schema: str = DEFAULT_SCHEMA

    def added_constraint(
        self, schema: str | None, table: str | None, name: str | None
    ) -> AddedConstraint | None:
        """The constraint ``table.name`` an earlier statement added, matched by identity."""
        if table is None or name is None:
            return None
        return self.constraints.get((schema or self.default_schema, table, name))


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
    added = _added_constraints(stmt, scope.default_schema)
    if not dropped and not added:
        return scope
    return replace(
        scope,
        constraints={**scope.constraints, **added},
        dropped_tviews=scope.dropped_tviews | dropped,
    )


def _added_constraints(
    stmt: Any, default_schema: str
) -> dict[tuple[str, str, str], AddedConstraint]:
    """``ALTER TABLE … ADD CONSTRAINT name …``: each named constraint and what its ADD locks."""
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
        added[(relation.schema or default_schema, relation.name, name)] = AddedConstraint(
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
