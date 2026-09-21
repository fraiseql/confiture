"""What ``live_catalog``'s listings answer on a real database.

``relations``, ``schemas`` / ``user_schemas``, ``indexes``, ``views``,
``triggers``, ``routines`` and ``existing_names`` replaced catalog SQL spread over
a dozen modules; each is asked here about the case that module's own query
decided — a partition and its parent, an index a constraint owns, an object an
extension owns, the internal triggers of a foreign key.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import psycopg
import pytest

from confiture.core import live_catalog

DDL = """
CREATE EXTENSION IF NOT EXISTS citext;
CREATE SCHEMA app;
CREATE TABLE app.tb_parent (id BIGINT PRIMARY KEY, code TEXT UNIQUE);
CREATE TABLE app.tb_child (
    id BIGINT PRIMARY KEY,
    parent_id BIGINT REFERENCES app.tb_parent (id)
);
CREATE INDEX ix_child_parent ON app.tb_child (parent_id) WHERE parent_id IS NOT NULL;
CREATE TABLE app.tb_part (id INT, at DATE) PARTITION BY RANGE (at);
CREATE TABLE app.tb_part_2026 PARTITION OF app.tb_part
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE app.tb_owned (id INT);
ALTER EXTENSION citext ADD TABLE app.tb_owned;
CREATE VIEW app.v_parent AS SELECT id FROM app.tb_parent;
CREATE VIEW app.v_owned AS SELECT 1 AS one;
ALTER EXTENSION citext ADD VIEW app.v_owned;
CREATE MATERIALIZED VIEW app.mv_parent AS SELECT id FROM app.tb_parent;
CREATE UNIQUE INDEX ix_mv_parent ON app.mv_parent (id);
CREATE FUNCTION app.fn_touch() RETURNS trigger LANGUAGE plpgsql
    AS $$ BEGIN RETURN NEW; END $$;
CREATE TRIGGER trg_touch BEFORE UPDATE ON app.tb_child
    FOR EACH ROW EXECUTE FUNCTION app.fn_touch();
"""


@pytest.fixture
def conn(fresh_database_factory: Callable[[str], str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(fresh_database_factory("confiture_listing"), autocommit=True) as c:
        c.execute(DDL)
        yield c


def test_relations_by_kind_without_an_extensions_own(conn: psycopg.Connection) -> None:
    tables = ["tb_child", "tb_parent", "tb_part", "tb_part_2026"]
    assert live_catalog.relations(conn, ["app"]) == [("app", t) for t in tables]
    assert live_catalog.relations(conn, ["app"], kinds=("r",)) == [
        ("app", t) for t in tables if t != "tb_part"
    ]
    assert ("app", "v_parent") in live_catalog.relations(conn, ["app"], live_catalog.TABLE_LIKE)


def test_schemas_the_role_can_use(conn: psycopg.Connection) -> None:
    listed = live_catalog.schemas(conn)
    assert {"app", "public", "pg_catalog", "information_schema"} <= set(listed)
    assert live_catalog.user_schemas(conn) == ["app", "public"]


def test_every_index_a_constraints_own_included(conn: psycopg.Connection) -> None:
    found = live_catalog.indexes(conn, ["app"])
    on = {
        ref.name: [(i.name, i.columns, i.unique) for i in found_on]
        for ref, found_on in found.items()
    }
    assert on == {
        "tb_child": [("ix_child_parent", ("parent_id",), False), ("tb_child_pkey", ("id",), True)],
        "tb_parent": [("tb_parent_code_key", ("code",), True), ("tb_parent_pkey", ("id",), True)],
        "mv_parent": [("ix_mv_parent", ("id",), True)],
    }


def test_views_keep_an_extensions_own_unless_asked(conn: psycopg.Connection) -> None:
    rows = live_catalog.views(conn, ["app"])
    assert [(v.name, v.materialized, v.definition) for v in rows] == [
        ("mv_parent", True, None),
        ("v_owned", False, None),
        ("v_parent", False, None),
    ]
    assert [v.name for v in live_catalog.views(conn, ["app"], extensions=False)] == [
        "mv_parent",
        "v_parent",
    ]
    defined = {v.name: v.definition for v in live_catalog.views(conn, ["app"], definitions=True)}
    assert defined["v_parent"] is not None
    assert "FROM app.tb_parent" in defined["v_parent"]


def test_triggers_a_user_created(conn: psycopg.Connection) -> None:
    """A foreign key's internal triggers are PostgreSQL's, not the schema's."""
    assert [(t.schema, t.table, t.name) for t in live_catalog.triggers(conn, ["app"])] == [
        ("app", "tb_child", "trg_touch")
    ]


def test_routines_filter_by_kind_trigger_and_name(conn: psycopg.Connection) -> None:
    assert [r.name for r in live_catalog.routines(conn, ["app"])] == ["fn_touch"]
    assert live_catalog.routines(conn, ["app"], include_triggers=False) == []
    public = live_catalog.routines(conn, ["public"], name_pattern="citext", exact_name=True)
    assert {r.name for r in public} == {"citext"}
    assert all(r.extension_owned for r in public)


def test_existing_names(conn: psycopg.Connection) -> None:
    relations, routines = live_catalog.existing_names(
        conn,
        relations=["app.tb_parent", "app.v_parent", "app.tb_parent_pkey", "app.absent"],
        routines=["app.fn_touch", "public.citext", "app.absent"],
    )
    assert relations == {"app.tb_parent", "app.v_parent", "app.tb_parent_pkey"}
    assert routines == {"app.fn_touch", "public.citext"}
