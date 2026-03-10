"""FK-based dependency graph and topological sort."""

from __future__ import annotations

import dataclasses

from confiture.models.introspection import IntrospectionResult


@dataclasses.dataclass
class DependencyOrder:
    """Result of topological sort on the FK graph."""

    ordered: list[str]
    cycles: list[list[str]]


class DependencyGraph:
    """Build and query a directed graph of FK dependencies.

    An edge A -> B means "A has a FK pointing to B" (A depends on B).
    """

    def __init__(self, edges: dict[str, set[str]]) -> None:
        self._edges = edges  # table -> set of tables it depends on
        self._all_tables: set[str] = set(edges.keys()) | {
            t for deps in edges.values() for t in deps
        }

    @classmethod
    def from_introspection(cls, result: IntrospectionResult) -> DependencyGraph:
        """Build graph from an IntrospectionResult.

        Each table's outbound_fks describe which other tables it depends on.
        """
        edges: dict[str, set[str]] = {}
        for table in result.tables:
            name = table.name
            if name not in edges:
                edges[name] = set()
            for fk in table.outbound_fks:
                if fk.to_table is not None:
                    edges[name].add(fk.to_table)
        return cls(edges)

    def topological_sort(self) -> DependencyOrder:
        """Return tables in dependency order (Kahn's algorithm).

        Tables with no dependencies come first. Cycles are detected
        and reported separately.
        """
        # Build reverse: for each B that A depends on, B -> A edge
        reverse: dict[str, set[str]] = {t: set() for t in self._all_tables}
        for table, deps in self._edges.items():
            for dep in deps:
                if dep in reverse:
                    reverse[dep].add(table)

        # In-degree = number of dependencies (tables this table points to)
        in_deg: dict[str, int] = {}
        for table in self._all_tables:
            in_deg[table] = len(self._edges.get(table, set()))

        # Start with tables that have no dependencies (leaves)
        queue = sorted([t for t, d in in_deg.items() if d == 0])
        ordered: list[str] = []

        while queue:
            node = queue.pop(0)
            ordered.append(node)
            for dependent in sorted(reverse.get(node, set())):
                in_deg[dependent] -= 1
                if in_deg[dependent] == 0:
                    queue.append(dependent)

        # Any remaining nodes with in_degree > 0 are in cycles
        remaining = [t for t, d in in_deg.items() if d > 0]
        cycles: list[list[str]] = []
        if remaining:
            cycles.append(sorted(remaining))

        return DependencyOrder(ordered=ordered, cycles=cycles)

    def dependencies_of(self, table: str) -> set[str]:
        """Return all transitive dependencies of a table."""
        visited: set[str] = set()
        stack = list(self._edges.get(table, set()))
        while stack:
            node = stack.pop()
            if node not in visited:
                visited.add(node)
                stack.extend(self._edges.get(node, set()) - visited)
        return visited

    def dependents_of(self, table: str) -> set[str]:
        """Return all tables that transitively depend on this table."""
        # Build reverse graph on demand
        reverse: dict[str, set[str]] = {t: set() for t in self._all_tables}
        for t, deps in self._edges.items():
            for dep in deps:
                if dep in reverse:
                    reverse[dep].add(t)

        visited: set[str] = set()
        stack = list(reverse.get(table, set()))
        while stack:
            node = stack.pop()
            if node not in visited:
                visited.add(node)
                stack.extend(reverse.get(node, set()) - visited)
        return visited
