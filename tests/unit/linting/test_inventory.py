"""The object inventory records every commentable kind, every definition, and where it is.

Phase 05 built the inventory for tables only. The doc family (#217) needs
functions matched on name *and* argument types, views and materialised views,
composite types and domains, and partitions told apart from their parents; the
duplicate-definition check (#218) needs every definition of the same key kept,
with its byte offset, not just the last one. Every case runs on a bare name and
on its schema-qualified twin and must inventory the same objects.
"""

from __future__ import annotations

import pytest

from confiture.core.linting.inventory import Inventory, SchemaObject, build_inventory

pytestmark = pytest.mark.parametrize("q", ["", "app."], ids=["bare", "qualified"])

_BODY = "RETURNS int LANGUAGE sql AS $$ select 1 $$;"


def _kind(inventory: Inventory, kind: str) -> list[SchemaObject]:
    return [o for o in inventory.objects if o.kind == kind]


def _schema(q: str) -> str | None:
    return q.rstrip(".") or None


def test_functions_record_each_overload_with_a_signature(q: str) -> None:
    sql = (
        f"CREATE FUNCTION {q}f(a integer, b text) {_BODY}\n"
        f"CREATE OR REPLACE FUNCTION {q}f(a text) {_BODY}\n"
    )
    functions = _kind(build_inventory(sql), "function")
    assert [f"{o.qualified}({o.signature})" for o in functions] == [
        f"{q}f(integer, text)",
        f"{q}f(text)",
    ]
    assert {o.schema for o in functions} == {_schema(q)}
    assert [o.line for o in functions] == [1, 2]


def test_out_and_table_parameters_are_not_part_of_the_signature(q: str) -> None:
    sql = (
        f"CREATE FUNCTION {q}g(a int, OUT b text, VARIADIC c text[]) {_BODY}\n"
        f"CREATE FUNCTION {q}h(a numeric(10,2)) RETURNS TABLE(x int) LANGUAGE sql AS $$ select 1 $$;\n"
    )
    functions = _kind(build_inventory(sql), "function")
    assert [o.signature for o in functions] == ["integer, text[]", "numeric"]


def test_procedures_are_their_own_kind(q: str) -> None:
    sql = f"CREATE PROCEDURE {q}p(x bigint) LANGUAGE sql AS $$ select 1 $$;\n"
    inventory = build_inventory(sql)
    assert [(o.kind, o.qualified, o.signature) for o in inventory.objects] == [
        ("procedure", f"{q}p", "bigint")
    ]


def test_views_and_materialized_views(q: str) -> None:
    sql = (
        f"CREATE VIEW {q}v_thing AS SELECT 1 AS a;\n"
        f"CREATE MATERIALIZED VIEW {q}mv_thing AS SELECT 1 AS a;\n"
    )
    inventory = build_inventory(sql)
    assert [(o.kind, o.qualified, o.signature) for o in inventory.objects] == [
        ("view", f"{q}v_thing", None),
        ("matview", f"{q}mv_thing", None),
    ]


def test_composite_types_enums_and_domains(q: str) -> None:
    sql = (
        f"CREATE TYPE {q}ty AS (a int, b text);\n"
        f"CREATE TYPE {q}en AS ENUM ('a', 'b');\n"
        f"CREATE DOMAIN {q}dm AS text CHECK (VALUE <> '');\n"
    )
    inventory = build_inventory(sql)
    assert [(o.kind, o.qualified) for o in inventory.objects] == [
        ("type", f"{q}ty"),
        ("type", f"{q}en"),
        ("domain", f"{q}dm"),
    ]


def test_partition_children_are_marked_and_parents_are_not(q: str) -> None:
    sql = (
        f"CREATE TABLE {q}parent (id int) PARTITION BY RANGE (id);\n"
        f"CREATE TABLE {q}child PARTITION OF {q}parent FOR VALUES FROM (1) TO (10);\n"
    )
    tables = build_inventory(sql).tables
    assert [(o.qualified, o.is_partition) for o in tables] == [
        (f"{q}parent", False),
        (f"{q}child", True),
    ]


def test_comment_on_function_documents_only_the_named_overload(q: str) -> None:
    sql = (
        f"CREATE FUNCTION {q}f(a integer) {_BODY}\n"
        f"CREATE FUNCTION {q}f(a text) {_BODY}\n"
        f"COMMENT ON FUNCTION {q}f(integer) IS 'the integer one';\n"
    )
    functions = _kind(build_inventory(sql), "function")
    assert [(o.signature, o.documented) for o in functions] == [("integer", True), ("text", False)]


def test_comment_on_procedure_matches_on_signature(q: str) -> None:
    sql = (
        f"CREATE PROCEDURE {q}p(x numeric(10,2)) LANGUAGE sql AS $$ select 1 $$;\n"
        f"COMMENT ON PROCEDURE {q}p(numeric) IS 'p';\n"
    )
    assert [o.documented for o in build_inventory(sql).objects] == [True]


def test_comments_attach_to_views_matviews_types_and_domains(q: str) -> None:
    sql = (
        f"CREATE VIEW {q}v AS SELECT 1 AS a;\n"
        f"CREATE MATERIALIZED VIEW {q}mv AS SELECT 1 AS a;\n"
        f"CREATE TYPE {q}ty AS (a int);\n"
        f"CREATE DOMAIN {q}dm AS text;\n"
        f"CREATE TYPE {q}undocumented AS (a int);\n"
        f"COMMENT ON VIEW {q}v IS 'v';\n"
        f"COMMENT ON MATERIALIZED VIEW {q}mv IS 'mv';\n"
        f"COMMENT ON TYPE {q}ty IS 'ty';\n"
        f"COMMENT ON DOMAIN {q}dm IS 'dm';\n"
    )
    inventory = build_inventory(sql)
    assert [(o.qualified, o.documented) for o in inventory.objects] == [
        (f"{q}v", True),
        (f"{q}mv", True),
        (f"{q}ty", True),
        (f"{q}dm", True),
        (f"{q}undocumented", False),
    ]


def test_a_comment_on_one_kind_never_documents_a_namesake_of_another(q: str) -> None:
    sql = (
        f"CREATE TABLE {q}thing (id int PRIMARY KEY);\n"
        f"CREATE VIEW {q}thing_v AS SELECT 1 AS a;\n"
        f"CREATE FUNCTION {q}thing() {_BODY}\n"
        f"COMMENT ON TABLE {q}thing IS 'the table';\n"
    )
    inventory = build_inventory(sql)
    assert [(o.kind, o.documented) for o in inventory.objects] == [
        ("table", True),
        ("view", False),
        ("function", False),
    ]


def test_every_definition_is_kept_with_its_offset(q: str) -> None:
    first = f"CREATE OR REPLACE FUNCTION {q}f(a int) {_BODY}"
    second = f"CREATE OR REPLACE FUNCTION {q}f(a int) {_BODY}"
    table = f"CREATE TABLE {q}t (id int PRIMARY KEY);"
    table_again = f"CREATE TABLE IF NOT EXISTS {q}t (id int PRIMARY KEY);"
    sql = f"-- header\n{first}\n\n{second}\n{table}\n{table_again}\n"
    inventory = build_inventory(sql)
    functions = _kind(inventory, "function")
    assert [o.offset for o in functions] == [
        sql.index(first),
        sql.index(second, sql.index(first) + 1),
    ]
    assert [o.signature for o in functions] == ["integer", "integer"]
    assert [o.offset for o in inventory.tables] == [sql.index(table), sql.index(table_again)]


def test_offsets_count_characters_not_bytes(q: str) -> None:
    create = f"CREATE TABLE {q}t (id int PRIMARY KEY);"
    sql = f"-- café ☕ — non-ASCII before the statement\n{create}\n"
    assert [o.offset for o in build_inventory(sql).tables] == [sql.index(create)]


def test_tables_lists_only_tables_and_keeps_their_shape(q: str) -> None:
    sql = (
        f"CREATE TABLE {q}t (id int PRIMARY KEY, name text);\n"
        f"CREATE VIEW {q}v AS SELECT 1 AS a;\n"
        f"CREATE FUNCTION {q}f() {_BODY}\n"
    )
    inventory = build_inventory(sql)
    assert inventory.tables == [o for o in inventory.objects if o.kind == "table"]
    (table,) = inventory.tables
    assert table.has_primary_key is True
    assert [c.name for c in table.columns] == ["id", "name"]
    assert table.signature is None
