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
and a key is resolved where its UUID is matched to the ``id`` of the table the
final table's ``REFERENCES`` names, in that ``INSERT`` or a second-pass
``UPDATE`` (:mod:`.keys`). What cannot be read
(a string ``EXECUTE`` builds, a statement pglast rejects, a body in another
language) is a finding naming it, never a clean result.
"""

from __future__ import annotations

from typing import Any

from confiture.core.ddl_walk import relation_parts, walk_nodes
from confiture.core.linting.references import BodyStatement
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import SchemaModel, Table
from confiture.core.seed.validation.prep_seed import keys
from confiture.core.seed.validation.prep_seed.final_tables import FinalTable, FinalTables
from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)
from confiture.core.seed.validation.prep_seed.resolvers import Resolver


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
        finals: FinalTables | None = None,
    ) -> None:
        """Initialize the validator.

        Args:
            model: The schema the resolvers are compared with.
            prep_seed_schema: The schema the UUID-keyed rows are loaded into.
            catalog_schema: The schema the resolvers fill when nothing says otherwise.
            finals: Each staging table's final table; without it every one is
                in *catalog_schema*.
        """
        self.prep_seed_schema = prep_seed_schema.lower()
        self.catalog_schema = catalog_schema.lower()
        self._finals = finals or FinalTables(self.catalog_schema)
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
            final = self._finals.of(table)
            schema = final.schema if final is not None and final.schema in homes else homes[0]
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
        final = self._finals.of(table)
        if final is not None and (final.schema, final.name) == (schema, table):
            violations.extend(self._fk_transformations(resolver, insert, final, (file, line)))
        return violations

    def _home(self, table: str) -> str:
        """``schema.name`` of *table*'s final table, for a suggestion."""
        final = self._finals.of(table)
        return final.qualified if final is not None else table

    def _fk_transformations(
        self, resolver: Resolver, insert: Any, target: FinalTable, at: tuple[str, int]
    ) -> list[PrepSeedViolation]:
        """Each ``fk_<role>_id`` of the prep-seed table the resolver never resolves.

        Resolved in *insert*, or in any other ``INSERT`` into or ``UPDATE`` of the
        final table in the same body: a self-reference is set in a second pass.
        """
        prep = self._tables.get((self.prep_seed_schema, target.name))
        if prep is None:
            return []
        final = self._tables.get((target.schema, target.name))
        statements = [insert, *keys.filling(resolver, target.schema, target.name)]
        violations: list[PrepSeedViolation] = []
        for column in prep.columns:
            name = column.folded
            if not keys.is_key(name):
                continue
            parent, declared = keys.target(final, prep, name)
            if keys.resolves(statements, parent, name):
                continue
            if not declared and keys.joins_any(statements, name):
                continue
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                    severity=ViolationSeverity.ERROR,
                    message=(
                        f"{resolver.name} fills {target.qualified} but never joins "
                        f"{parent} on {name}: {name.removesuffix(keys.FK_SUFFIX)} is not resolved"
                    ),
                    file_path=at[0],
                    line_number=at[1],
                    impact="This FK will have NULL values after resolution",
                    fix_available=True,
                    suggestion=(f"Add: LEFT JOIN {self._home(parent)} ON {parent}.id = {name}"),
                )
            )
        return violations

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
