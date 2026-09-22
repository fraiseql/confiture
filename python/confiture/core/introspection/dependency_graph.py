"""FK-based dependency graph and topological sort.

The order is a function of the graph alone: among the tables ready to go — every
table they reference already placed — the first by name goes first. A writer that
loads seeds in this order writes the same files on every run, whatever order the
schema declared its tables in.
"""

from __future__ import annotations

import dataclasses
import heapq
from collections.abc import Iterable
from typing import Generic, TypeVar

from confiture.core.model_facts import resolve, table_ref
from confiture.core.schema_model import ObjectRef, SchemaModel
from confiture.exceptions import SchemaError
from confiture.models.introspection import IntrospectionResult

#: A table as the graph holds it: a bare name, or ``(schema, name)`` for a model's.
Node = TypeVar("Node", str, tuple[str, str])


@dataclasses.dataclass
class DependencyOrder(Generic[Node]):
    """Result of topological sort on the FK graph."""

    ordered: list[Node]
    cycles: list[list[Node]]


class DependencyCycle(SchemaError):
    """Tables whose foreign keys form a cycle: none of them can be loaded first."""

    def __init__(self, tables: tuple[ObjectRef, ...]) -> None:
        self.tables = tables
        names = ", ".join(f"{table.schema}.{table.name}" for table in tables)
        super().__init__(
            f"Foreign keys form a cycle between {names}: no table in it can be loaded "
            "before the tables it references.",
            error_code="SCHEMA_202",
            resolution_hint=(
                "Load one table of the cycle with its reference NULL and set it afterwards, "
                "or make one foreign key DEFERRABLE and load the cycle in one transaction."
            ),
        )


class DependencyGraph(Generic[Node]):
    """Build and query a directed graph of FK dependencies.

    An edge A -> B means "A has a FK pointing to B" (A depends on B).
    """

    def __init__(self, edges: dict[Node, set[Node]]) -> None:
        self._edges = edges  # table -> set of tables it depends on
        self._all_tables: set[Node] = set(edges.keys()) | {
            t for deps in edges.values() for t in deps
        }

    @staticmethod
    def from_introspection(result: IntrospectionResult) -> DependencyGraph[str]:
        """Build graph from an IntrospectionResult.

        Each table's outbound_fks describe which other tables it depends on. A
        table that references itself does not depend on itself.
        """
        edges: dict[str, set[str]] = {}
        for table in result.tables:
            name = table.name
            if name not in edges:
                edges[name] = set()
            for fk in table.outbound_fks:
                if fk.to_table is not None and fk.to_table != name:
                    edges[name].add(fk.to_table)
        return DependencyGraph(edges)

    @staticmethod
    def from_model(model: SchemaModel) -> DependencyGraph[tuple[str, str]]:
        """The graph of *model*'s tables, each ``(schema, name)``, over its foreign keys.

        A reference resolves the way DDL's does (``model_facts.resolve``). One the
        model does not hold — a table outside the schemas read — is no edge, and
        neither is a table's reference to itself: its rows are the writer's to order.
        """
        edges: dict[tuple[str, str], set[tuple[str, str]]] = {}
        for ref, table in model.tables.items():
            node = (ref.schema, ref.name)
            targets = (
                resolve(model.tables, fk.ref_table or "")
                for fk in table.constraints_of("foreign_key")
            )
            edges[node] = {(t.schema, t.name) for t in targets if t is not None} - {node}
        return DependencyGraph(edges)

    def restricted_to(self, tables: Iterable[Node]) -> DependencyGraph[Node]:
        """The graph of *tables* and every table they transitively depend on."""
        keep = set(tables)
        for table in list(keep):
            keep |= self.dependencies_of(table)
        return DependencyGraph({t: self._edges.get(t, set()) & keep for t in keep})

    def topological_sort(self) -> DependencyOrder[Node]:
        """Return tables in dependency order (Kahn's algorithm).

        Tables with no dependencies come first; among the tables ready at each
        step, the smallest goes first. Tables that cannot be ordered are reported
        in ``cycles``: those on a cycle, not the ones that merely depend on one.
        """
        # Build reverse: for each B that A depends on, B -> A edge
        reverse: dict[Node, set[Node]] = {t: set() for t in self._all_tables}
        for table, deps in self._edges.items():
            for dep in deps:
                reverse[dep].add(table)

        # In-degree = number of dependencies (tables this table points to)
        in_deg = {table: len(self._edges.get(table, set())) for table in self._all_tables}
        ready = [t for t, d in in_deg.items() if d == 0]
        heapq.heapify(ready)
        ordered: list[Node] = []
        while ready:
            node = heapq.heappop(ready)
            ordered.append(node)
            for dependent in reverse[node]:
                in_deg[dependent] -= 1
                if in_deg[dependent] == 0:
                    heapq.heappush(ready, dependent)

        on_cycles = self._on_cycles({t for t, d in in_deg.items() if d > 0})
        return DependencyOrder(ordered=ordered, cycles=[on_cycles] if on_cycles else [])

    def _on_cycles(self, remaining: set[Node]) -> list[Node]:
        """*remaining* less every table only downstream of a cycle, repeatedly.

        A table nothing left depends on cannot be on a cycle; removing it may
        leave another one that nothing depends on. What survives lies on a cycle,
        or between two.
        """
        left = set(remaining)
        while True:
            downstream = {t for t in left if not any(t in self._edges.get(o, set()) for o in left)}
            if not downstream:
                return sorted(left)
            left -= downstream

    def dependencies_of(self, table: Node) -> set[Node]:
        """Return all transitive dependencies of a table."""
        visited: set[Node] = set()
        stack = list(self._edges.get(table, set()))
        while stack:
            node = stack.pop()
            if node not in visited:
                visited.add(node)
                stack.extend(self._edges.get(node, set()) - visited)
        return visited

    def dependents_of(self, table: Node) -> set[Node]:
        """Return all tables that transitively depend on this table."""
        # Build reverse graph on demand
        reverse: dict[Node, set[Node]] = {t: set() for t in self._all_tables}
        for t, deps in self._edges.items():
            for dep in deps:
                if dep in reverse:
                    reverse[dep].add(t)

        visited: set[Node] = set()
        stack = list(reverse.get(table, set()))
        while stack:
            node = stack.pop()
            if node not in visited:
                visited.add(node)
                stack.extend(reverse.get(node, set()) - visited)
        return visited


def dependency_order(
    model: SchemaModel, *, tables: Iterable[ObjectRef | str] | None = None
) -> list[ObjectRef]:
    """*model*'s tables, each after every table it references by foreign key.

    Deterministic: among the tables ready at each step, the first by
    ``(schema, name)``. A table that references itself is ordered like any other.
    *tables* orders just those — a reference or a name, resolved as DDL's is — and
    reads through the tables they depend on, so a cycle elsewhere does not stop it.

    Raises:
        DependencyCycle: tables whose foreign keys form a cycle, named.
        KeyError: a table in *tables* the model does not hold.
    """
    refs = {(ref.schema, ref.name): ref for ref in model.tables}
    graph = DependencyGraph.from_model(model)
    wanted = None
    if tables is not None:
        wanted = {(ref.schema, ref.name) for ref in (table_ref(model, t) for t in tables)}
        graph = graph.restricted_to(wanted)
    order = graph.topological_sort()
    if order.cycles:
        raise DependencyCycle(tuple(refs[node] for node in order.cycles[0]))
    return [refs[node] for node in order.ordered if wanted is None or node in wanted]
