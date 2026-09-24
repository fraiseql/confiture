"""Level 3: Resolution function validation.

Validates that resolution functions correctly transform UUIDs to BIGINTs.

This is the CRITICAL level that detects:
- Schema drift (functions referencing wrong schema)
- Missing FK transformations (JOINs missing from resolution)

A resolver's body is read through
:func:`~confiture.core.linting.references.read_body` — the one PL/pgSQL
fragment reader, or pglast for a ``LANGUAGE sql`` body — and every table it is
compared with comes from the one schema model. So the ``INSERT`` target is the
statement's ``RangeVar`` however it is spelled (quoted, aliased, unqualified),
and a join is an equality between a ``fk_<entity>_id`` column and the ``id`` of
a relation that is ``tb_<entity>`` — written as a ``JOIN … ON``, a comma join
and a ``WHERE``, a correlated subquery, or through a CTE. What cannot be read
(a string ``EXECUTE`` builds, a statement pglast rejects, a body in another
language) is a finding naming it, never a clean result.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from confiture.core.ddl_walk import relation_parts, walk_nodes
from confiture.core.linting.references import BodyStatement
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import SchemaModel, Table
from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)
from confiture.core.seed.validation.prep_seed.resolvers import Resolver

#: A prep-seed foreign key's column: ``fk_<entity>_id``, holding the parent's UUID.
_FK_PREFIX, _FK_SUFFIX = "fk_", "_id"

#: The column a prep-seed foreign key's UUID is matched on in its parent.
_ID = "id"


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


def _equalities(root: Any) -> Iterator[tuple[tuple[str, ...], tuple[str, ...]]]:
    """Every ``column = column`` under *root*, wherever it is written."""
    for node in walk_nodes(root):
        if type(node).__name__ != "A_Expr" or _name(node.name) != ("=",):
            continue
        left, right = _column(node.lexpr), _column(node.rexpr)
        if left and right:
            yield left, right


class Level3ResolutionValidator:
    """Validates resolution functions for schema drift and FK transformations.

    Example:
        >>> read = read_schema(Path("db/schema"))
        >>> validator = Level3ResolutionValidator(read.model)
        >>> for resolver in find_resolvers(read, catalog_schema="catalog"):
        ...     violations = validator.validate(resolver)
    """

    def __init__(
        self,
        model: SchemaModel,
        *,
        prep_seed_schema: str = "prep_seed",
        catalog_schema: str = "catalog",
    ) -> None:
        """Initialize the validator.

        Args:
            model: The schema the resolvers are compared with.
            prep_seed_schema: The schema the UUID-keyed rows are loaded into.
            catalog_schema: The schema the resolvers fill.
        """
        self.prep_seed_schema = prep_seed_schema.lower()
        self.catalog_schema = catalog_schema.lower()
        self._tables: dict[tuple[str, str], Table] = {
            ((table.schema or DEFAULT_SCHEMA).lower(), table.name): table
            for table in model.tables.values()
        }

    def validate(self, resolver: Resolver) -> list[PrepSeedViolation]:
        """Every ``INSERT`` in *resolver*'s body checked, and what could not be read named."""
        violations: list[PrepSeedViolation] = []
        for statement in resolver.body.statements:
            for node in walk_nodes(statement.root):
                if type(node).__name__ == "InsertStmt":
                    violations.extend(self._insert(resolver, statement, node))
        violations.extend(self._not_read(resolver))
        return violations

    def _insert(
        self, resolver: Resolver, statement: BodyStatement, insert: Any
    ) -> list[PrepSeedViolation]:
        written_schema, table = relation_parts(insert.relation)
        if table is None:
            return []
        file, line = resolver.where(statement.line_at(insert.relation.location))
        schema = (written_schema or DEFAULT_SCHEMA).lower()
        violations: list[PrepSeedViolation] = []
        if (schema, table) not in self._tables:
            homes = sorted(home for home, name in self._tables if name == table)
            if not homes:
                return []
            schema = self.catalog_schema if self.catalog_schema in homes else homes[0]
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER,
                    severity=ViolationSeverity.CRITICAL,
                    message=(
                        f"{resolver.name} inserts into {written_schema or DEFAULT_SCHEMA}.{table} "
                        f"but the table is in {schema}.{table}"
                    ),
                    file_path=file,
                    line_number=line,
                    impact="Will cause NULL foreign keys in dependent tables",
                    fix_available=True,
                    suggestion=f"Change INSERT target to {schema}.{table}",
                )
            )
        if schema == self.catalog_schema:
            violations.extend(self._fk_transformations(resolver, insert, table, (file, line)))
        return violations

    def _fk_transformations(
        self, resolver: Resolver, insert: Any, table: str, at: tuple[str, int]
    ) -> list[PrepSeedViolation]:
        """Each ``fk_<entity>_id`` of the prep-seed table that the ``INSERT`` never joins."""
        prep = self._tables.get((self.prep_seed_schema, table))
        if prep is None:
            return []
        sources = _sources(insert)
        equalities = list(_equalities(insert))
        violations: list[PrepSeedViolation] = []
        for column in prep.columns:
            name = column.folded
            if not (name.startswith(_FK_PREFIX) and name.endswith(_FK_SUFFIX)):
                continue
            parent = self._parent(prep, name)
            if self._joined(parent, name, sources, equalities):
                continue
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                    severity=ViolationSeverity.ERROR,
                    message=(
                        f"{resolver.name} fills {self.catalog_schema}.{table} but never joins "
                        f"{parent} on {name}: {name.removesuffix(_FK_SUFFIX)} is not resolved"
                    ),
                    file_path=at[0],
                    line_number=at[1],
                    impact="This FK will have NULL values after resolution",
                    fix_available=True,
                    suggestion=(
                        f"Add: LEFT JOIN {self.catalog_schema}.{parent} ON {parent}.id = {name}"
                    ),
                )
            )
        return violations

    @staticmethod
    def _parent(prep: Table, column: str) -> str:
        """The table *column* points at: its foreign key's, or ``tb_<entity>`` by convention."""
        for constraint in prep.constraints_of("foreign_key"):
            if constraint.columns == (column,) and constraint.ref_table:
                return constraint.ref_table.rsplit(".", 1)[-1]
        return "tb_" + column.removeprefix(_FK_PREFIX).removesuffix(_FK_SUFFIX)

    @staticmethod
    def _joined(
        parent: str,
        column: str,
        sources: dict[str, set[str]],
        equalities: list[tuple[tuple[str, ...], tuple[str, ...]]],
    ) -> bool:
        """Whether some ``<parent>.id = <…>.<column>`` is written, in either order."""
        for left, right in equalities:
            for id_side, fk_side in ((left, right), (right, left)):
                if id_side[-1] != _ID or fk_side[-1] != column:
                    continue
                if len(id_side) == 1:
                    if any(parent in tables for tables in sources.values()):
                        return True
                elif parent in sources.get(id_side[-2], set()):
                    return True
        return False

    @staticmethod
    def _not_read(resolver: Resolver) -> list[PrepSeedViolation]:
        """What of *resolver*'s body level 3 could not read: one finding per reason."""
        body = resolver.body
        reasons: list[tuple[int | None, str]] = []
        if body.refused is not None:
            reasons.append(
                (None, f"the PL/pgSQL compiler did not return its body ({body.refused})")
            )
        elif not body.is_sql:
            reasons.append((None, f"its body is LANGUAGE {body.language}, which is not SQL"))
        if body.dynamic:
            reasons.append(
                (
                    body.dynamic[0][0],
                    f"{len(body.dynamic)} statement(s) built at run time (EXECUTE)",
                )
            )
        if body.unread:
            line, why = body.unread[0]
            reasons.append((line, f"{len(body.unread)} statement(s) could not be parsed: {why}"))
        violations: list[PrepSeedViolation] = []
        for line, reason in reasons:
            file, at = resolver.where(line)
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.RESOLVER_NOT_READ,
                    severity=ViolationSeverity.WARNING,
                    message=f"{resolver.name} not checked: {reason}",
                    file_path=file,
                    line_number=at,
                    impact="Schema drift and missing FK joins in what was not read are not detected",
                )
            )
        return violations
