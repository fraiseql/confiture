"""``dependency_order``: tables parents first, by foreign key, the same way every run.

A seed writer loads a parent before its children, and it writes the files once:
so the order is a function of the schema alone — among the tables ready to go,
the first by ``(schema, name)`` — never of declaration order or hash order. A
table that references itself is ordered like any other (its rows are the
writer's to order); a cycle between tables has no order and says which tables
make it. Identity is ``(schema, name)`` (#313): the prep-seed pattern keeps the
same table names in two schemas, and nothing here may confuse them.
"""

from __future__ import annotations

import pytest

from confiture import platform
from confiture.core.introspection.dependency_graph import DependencyGraph

TWINS = """
CREATE TABLE catalog.tb_child (pk_child BIGINT PRIMARY KEY,
    fk_parent BIGINT REFERENCES catalog.tb_parent (pk_parent));
CREATE TABLE prep_seed.tb_child (id UUID PRIMARY KEY,
    fk_parent UUID REFERENCES prep_seed.tb_parent (id));
CREATE TABLE catalog.tb_parent (pk_parent BIGINT PRIMARY KEY);
CREATE TABLE prep_seed.tb_parent (id UUID PRIMARY KEY);
CREATE TABLE catalog.tb_grandchild (fk_child BIGINT REFERENCES catalog.tb_child);
"""


def _names(refs: list[platform.ObjectRef]) -> list[str]:
    return [f"{ref.schema}.{ref.name}" for ref in refs]


def test_parents_come_first_across_two_schemas_with_one_set_of_names() -> None:
    order = _names(platform.dependency_order(platform.parse_schema(TWINS)))
    assert order == [
        "catalog.tb_parent",
        "catalog.tb_child",
        "catalog.tb_grandchild",
        "prep_seed.tb_parent",
        "prep_seed.tb_child",
    ]


def test_the_order_is_the_schemas_not_the_files() -> None:
    statements = [s for s in TWINS.split(";") if s.strip()]
    reversed_ddl = ";".join(reversed(statements)) + ";"
    first = platform.dependency_order(platform.parse_schema(TWINS))
    assert platform.dependency_order(platform.parse_schema(reversed_ddl)) == first


def test_among_the_ready_tables_the_first_by_schema_and_name_goes_first() -> None:
    """The rule is statable: not a breadth-first walk's accident."""
    graph = DependencyGraph(edges={"a": {"c"}, "b": {"c"}, "c": set(), "d": set()})
    assert graph.topological_sort().ordered == ["c", "a", "b", "d"]


def test_a_table_that_references_itself_is_ordered() -> None:
    model = platform.parse_schema(
        "CREATE TABLE category (id INT PRIMARY KEY, parent_id INT REFERENCES category (id));\n"
        "CREATE TABLE item (category_id INT REFERENCES category);"
    )
    assert _names(platform.dependency_order(model)) == ["public.category", "public.item"]


def test_a_cycle_between_tables_is_reported_by_its_tables() -> None:
    model = platform.parse_schema(
        "CREATE TABLE a (id INT PRIMARY KEY, b_id INT);\n"
        "CREATE TABLE b (id INT PRIMARY KEY, a_id INT REFERENCES a);\n"
        "ALTER TABLE a ADD FOREIGN KEY (b_id) REFERENCES b;\n"
        "CREATE TABLE downstream (a_id INT REFERENCES a);\n"
    )
    with pytest.raises(platform.DependencyCycleError) as caught:
        platform.dependency_order(model)
    assert _names(list(caught.value.tables)) == ["public.a", "public.b"]
    assert caught.value.error_code == "SCHEMA_202"


def test_an_unqualified_reference_is_the_default_schemas_table() -> None:
    model = platform.parse_schema(
        "CREATE TABLE child (p INT REFERENCES parent);\n"
        "CREATE TABLE parent (id INT PRIMARY KEY);\n"
        "CREATE TABLE other.parent (id INT PRIMARY KEY);\n"
    )
    order = _names(platform.dependency_order(model))
    assert order.index("public.parent") < order.index("public.child")


def test_an_unqualified_reference_search_path_placed_is_found_by_its_name() -> None:
    """``SET search_path`` is invisible to a parse; a name only one schema holds is that one."""
    model = platform.parse_schema(
        "CREATE TABLE app.child (p INT REFERENCES parent);\n"
        "CREATE TABLE app.parent (id INT PRIMARY KEY);\n"
    )
    assert _names(platform.dependency_order(model)) == ["app.parent", "app.child"]


def test_a_reference_outside_the_model_is_no_dependency() -> None:
    model = platform.parse_schema("CREATE TABLE child (p INT REFERENCES elsewhere.parent);")
    assert _names(platform.dependency_order(model)) == ["public.child"]


def test_a_subset_is_ordered_through_the_tables_it_depends_on() -> None:
    model = platform.parse_schema(TWINS + "CREATE TABLE x (y INT);\nCREATE TABLE y (x INT);\n")
    order = platform.dependency_order(model, tables=["catalog.tb_grandchild", "catalog.tb_parent"])
    assert _names(order) == ["catalog.tb_parent", "catalog.tb_grandchild"]


def test_a_cycle_outside_the_subset_does_not_stop_it() -> None:
    model = platform.parse_schema(
        "CREATE TABLE a (id INT PRIMARY KEY, b_id INT);\n"
        "CREATE TABLE b (id INT PRIMARY KEY, a_id INT REFERENCES a);\n"
        "ALTER TABLE a ADD FOREIGN KEY (b_id) REFERENCES b;\n"
        "CREATE TABLE lone (id INT);\n"
    )
    assert _names(platform.dependency_order(model, tables=["lone"])) == ["public.lone"]


def test_a_table_the_model_lacks_is_a_key_error() -> None:
    with pytest.raises(KeyError, match="nope"):
        platform.dependency_order(platform.parse_schema("CREATE TABLE a (x INT);"), tables=["nope"])
