"""Where each staging table's rows land: decided once, and read by every level (#458).

``prep_seed.<table>`` resolves into a final table that need not be in one
configured schema: a tree that keeps shared reference data in ``catalog`` and
per-tenant tables in ``tenant`` resolves into both. The final table is, in order:

1. **What the resolver writes.** The ``INSERT`` target, in the body of the
   routine named ``fn_resolve_<table>``, of a statement that reads
   ``<prep_seed>.<table>`` — read through the one body reader, so a quoted,
   aliased or CTE-wrapped statement is the same statement. An unqualified target
   is in :data:`~confiture.core.schema_identity.DEFAULT_SCHEMA`. A target the
   schema does not declare is not an answer: level 3 reports that resolver's
   drift, and the next rule decides.
2. **The one schema that declares ``<table>``**, outside the prep-seed schema.
   A name declared in more than one is an ambiguity, reported and never guessed.
3. **``catalog_schema``**, which keeps a single-schema tree's behaviour.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from confiture.core.ddl_walk import relation_parts, walk_nodes
from confiture.core.schema_identity import DEFAULT_SCHEMA

if TYPE_CHECKING:
    from confiture.core.schema_model import SchemaModel
    from confiture.core.seed.validation.prep_seed.resolvers import Resolver

#: Why a final table is the one it is, in the order the rules are tried.
RESOLVER, SCHEMA, CATALOG_SCHEMA = "resolver", "schema", "catalog_schema"


@dataclass(frozen=True)
class FinalTable:
    """The table a staging table's rows are resolved into.

    Attributes:
        schema: Its schema, folded, a missing qualifier defaulted.
        name: Its name, as PostgreSQL holds it.
        basis: Which rule decided it: ``"resolver"``, ``"schema"`` or
            ``"catalog_schema"``.
    """

    schema: str
    name: str
    basis: str

    @property
    def qualified(self) -> str:
        """``schema.name``, for a finding."""
        return f"{self.schema}.{self.name}"


@dataclass(frozen=True)
class FinalTables:
    """Every staging table's final table, and the names no rule could decide.

    Attributes:
        catalog_schema: The fallback schema.
        found: The final table of each staging table a rule decided.
        ambiguous: Each staging table whose final table could be any of several,
            with those candidates as ``schema.name``.
    """

    catalog_schema: str
    found: dict[str, FinalTable] = field(default_factory=dict)
    ambiguous: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def of(self, staging: str) -> FinalTable | None:
        """The final table of *staging*; ``None`` when it is ambiguous."""
        if staging in self.ambiguous:
            return None
        return self.found.get(staging) or FinalTable(self.catalog_schema, staging, CATALOG_SCHEMA)


def decide(
    model: SchemaModel,
    resolvers: Iterable[Resolver],
    *,
    prep_seed_schema: str,
    catalog_schema: str,
) -> FinalTables:
    """The final table of every prep-seed table *model* declares or a resolver is named for."""
    prep = prep_seed_schema.lower()
    tables = {(ref.schema.lower(), ref.name) for ref in model.tables}
    named: dict[str, list[Resolver]] = {}
    for resolver in resolvers:
        named.setdefault(resolver.table, []).append(resolver)
    staging = {name for schema, name in tables if schema == prep} | set(named)

    finals = FinalTables(catalog_schema.lower())
    for name in sorted(staging):
        written = {
            target
            for resolver in named.get(name, ())
            for target in _written(resolver, name, prep)
            if target in tables
        }
        declared = written or {key for key in tables if key[1] == name and key[0] != prep}
        if len(declared) > 1:
            finals.ambiguous[name] = tuple(
                f"{schema}.{table}" for schema, table in sorted(declared)
            )
        elif declared:
            ((schema, table),) = declared
            finals.found[name] = FinalTable(schema, table, RESOLVER if written else SCHEMA)
    return finals


def _written(resolver: Resolver, staging: str, prep: str) -> set[tuple[str, str]]:
    """``(schema, name)`` of each table *resolver* inserts rows of ``<prep>.<staging>`` into."""
    targets: set[tuple[str, str]] = set()
    for statement in resolver.body.statements:
        for node in walk_nodes(statement.root):
            if type(node).__name__ != "InsertStmt":
                continue
            schema, table = relation_parts(node.relation)
            target = ((schema or DEFAULT_SCHEMA).lower(), table)
            if table is None or target[0] == prep or not _reads(node, prep, staging):
                continue
            targets.add((target[0], table))
    return targets


def _reads(insert: Any, prep: str, staging: str) -> bool:
    """Whether *insert* reads ``<prep>.<staging>`` anywhere but its own target."""
    return any(
        type(node).__name__ == "RangeVar"
        and node is not insert.relation
        and (node.schemaname or "").lower() == prep
        and node.relname == staging
        for node in walk_nodes(insert)
    )
