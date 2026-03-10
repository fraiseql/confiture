"""Unit tests for DependencyGraph: topological sort, cycle detection, queries.

No database required — all tests use manually constructed edge sets
or IntrospectionResult objects.
"""

from confiture.core.introspection.dependency_graph import DependencyGraph, DependencyOrder
from confiture.models.introspection import (
    FKReference,
    IntrospectedColumn,
    IntrospectedTable,
    IntrospectionResult,
)


def _make_result(tables: list[tuple[str, list[tuple[str, str]]]]) -> IntrospectionResult:
    """Build a minimal IntrospectionResult.

    Args:
        tables: list of (table_name, [(via_column, to_table), ...])
    """
    introspected_tables = []
    for name, fks in tables:
        outbound = [
            FKReference(from_table=None, to_table=to_table, via_column=via, on_column="id")
            for via, to_table in fks
        ]
        introspected_tables.append(
            IntrospectedTable(
                name=name,
                columns=[IntrospectedColumn("id", "bigint", nullable=False, is_primary_key=True)],
                outbound_fks=outbound,
                inbound_fks=[],
                hints=None,
            )
        )
    return IntrospectionResult(
        database="testdb",
        schema="public",
        introspected_at="2026-01-01T00:00:00+00:00",
        tables=introspected_tables,
    )


class TestEmptyGraph:
    def test_empty_edges(self):
        graph = DependencyGraph(edges={})
        order = graph.topological_sort()
        assert order.ordered == []
        assert order.cycles == []

    def test_single_table_no_deps(self):
        graph = DependencyGraph(edges={"users": set()})
        order = graph.topological_sort()
        assert order.ordered == ["users"]
        assert order.cycles == []

    def test_dependencies_of_unknown_table(self):
        graph = DependencyGraph(edges={"users": set()})
        assert graph.dependencies_of("nonexistent") == set()

    def test_dependents_of_unknown_table(self):
        graph = DependencyGraph(edges={"users": set()})
        assert graph.dependents_of("nonexistent") == set()


class TestLinearChain:
    """A -> B -> C: C has no deps, B depends on C, A depends on B."""

    def setup_method(self):
        self.graph = DependencyGraph(
            edges={
                "a": {"b"},
                "b": {"c"},
                "c": set(),
            }
        )

    def test_topological_order(self):
        order = self.graph.topological_sort()
        # c must come before b, b before a
        assert order.cycles == []
        assert order.ordered.index("c") < order.ordered.index("b")
        assert order.ordered.index("b") < order.ordered.index("a")

    def test_no_cycles(self):
        order = self.graph.topological_sort()
        assert order.cycles == []

    def test_dependencies_of_a(self):
        deps = self.graph.dependencies_of("a")
        assert deps == {"b", "c"}

    def test_dependencies_of_b(self):
        deps = self.graph.dependencies_of("b")
        assert deps == {"c"}

    def test_dependencies_of_c(self):
        deps = self.graph.dependencies_of("c")
        assert deps == set()

    def test_dependents_of_c(self):
        dependents = self.graph.dependents_of("c")
        assert dependents == {"a", "b"}

    def test_dependents_of_b(self):
        dependents = self.graph.dependents_of("b")
        assert dependents == {"a"}

    def test_dependents_of_a(self):
        dependents = self.graph.dependents_of("a")
        assert dependents == set()


class TestDiamondShape:
    """Diamond: A depends on B and C; B and C both depend on D."""

    def setup_method(self):
        self.graph = DependencyGraph(
            edges={
                "orders": {"users", "products"},
                "users": {"tenants"},
                "products": {"tenants"},
                "tenants": set(),
            }
        )

    def test_topological_order_valid(self):
        order = self.graph.topological_sort()
        assert order.cycles == []
        idx = {t: i for i, t in enumerate(order.ordered)}
        assert idx["tenants"] < idx["users"]
        assert idx["tenants"] < idx["products"]
        assert idx["users"] < idx["orders"]
        assert idx["products"] < idx["orders"]

    def test_all_tables_present(self):
        order = self.graph.topological_sort()
        assert set(order.ordered) == {"orders", "users", "products", "tenants"}

    def test_dependencies_of_orders(self):
        deps = self.graph.dependencies_of("orders")
        assert "users" in deps
        assert "products" in deps
        assert "tenants" in deps

    def test_dependents_of_tenants(self):
        dependents = self.graph.dependents_of("tenants")
        assert "users" in dependents
        assert "products" in dependents
        assert "orders" in dependents


class TestCycleDetection:
    """A -> B -> A is a cycle."""

    def setup_method(self):
        self.graph = DependencyGraph(
            edges={
                "a": {"b"},
                "b": {"a"},
            }
        )

    def test_cycle_detected(self):
        order = self.graph.topological_sort()
        assert len(order.cycles) > 0
        assert {"a", "b"} == set(order.cycles[0])

    def test_ordered_is_empty_when_all_cyclic(self):
        order = self.graph.topological_sort()
        assert order.ordered == []

    def test_partial_cycle(self):
        # C has no deps, A->B->A cycle, C->A ref
        graph = DependencyGraph(edges={"a": {"b"}, "b": {"a"}, "c": {"a"}})
        order = graph.topological_sort()
        assert len(order.cycles) > 0
        cyclic_nodes = set(order.cycles[0])
        assert "a" in cyclic_nodes
        assert "b" in cyclic_nodes


class TestSelfReferentialFK:
    """A table that references itself (e.g. tree structure)."""

    def test_self_ref_detected_as_cycle(self):
        graph = DependencyGraph(edges={"categories": {"categories"}})
        order = graph.topological_sort()
        assert len(order.cycles) > 0
        assert "categories" in order.cycles[0]


class TestFromIntrospection:
    def test_simple_two_table_result(self):
        result = _make_result(
            [
                ("orders", [("user_id", "users")]),
                ("users", []),
            ]
        )
        graph = DependencyGraph.from_introspection(result)
        order = graph.topological_sort()
        assert order.cycles == []
        assert order.ordered.index("users") < order.ordered.index("orders")

    def test_no_fks(self):
        result = _make_result([("alpha", []), ("beta", [])])
        graph = DependencyGraph.from_introspection(result)
        order = graph.topological_sort()
        assert order.cycles == []
        assert set(order.ordered) == {"alpha", "beta"}

    def test_complex_schema(self):
        result = _make_result(
            [
                ("line_items", [("order_id", "orders"), ("product_id", "products")]),
                ("orders", [("customer_id", "customers")]),
                ("products", []),
                ("customers", []),
            ]
        )
        graph = DependencyGraph.from_introspection(result)
        order = graph.topological_sort()
        assert order.cycles == []
        idx = {t: i for i, t in enumerate(order.ordered)}
        assert idx["customers"] < idx["orders"]
        assert idx["products"] < idx["line_items"]
        assert idx["orders"] < idx["line_items"]


class TestDependencyOrderDataclass:
    def test_is_dataclass(self):
        import dataclasses

        assert dataclasses.is_dataclass(DependencyOrder)

    def test_construction(self):
        order = DependencyOrder(ordered=["a", "b"], cycles=[])
        assert order.ordered == ["a", "b"]
        assert order.cycles == []
