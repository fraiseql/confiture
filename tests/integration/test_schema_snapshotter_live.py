"""What the pytest plugin's snapshotter and sandbox see, on a real database.

Both read through ``core/live_catalog``. Three things the ``information_schema``
readers they replaced got wrong are pinned here: a NOT NULL column was a CHECK
constraint of its own, an index had no columns, and a composite foreign key was
the cross product of its two column lists — while one pointing into another
schema was not there at all.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import psycopg
import pytest

from confiture.testing.fixtures.schema_snapshotter import SchemaSnapshotter
from confiture.testing.sandbox import MigrationSandbox

DDL = """
CREATE EXTENSION IF NOT EXISTS citext;
CREATE SCHEMA app;
CREATE SCHEMA other;
CREATE TYPE app.mood AS ENUM ('sad', 'happy');
CREATE TABLE other.tb_ext (id BIGINT PRIMARY KEY, code TEXT UNIQUE);
CREATE TABLE app.tb_pair (a INT, b INT, label VARCHAR(50) NOT NULL, PRIMARY KEY (a, b));
CREATE TABLE app.tb_parent (pk_parent BIGINT PRIMARY KEY);
CREATE TABLE app."tb_Mixed" (
    "UserId" BIGINT PRIMARY KEY,
    amount NUMERIC(10, 2),
    tags TEXT[],
    mood app.mood,
    at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE app.tb_child (
    pk_child BIGINT PRIMARY KEY,
    pa INT,
    pb INT,
    fk_parent BIGINT NOT NULL,
    ext_id BIGINT,
    CONSTRAINT zz_pair FOREIGN KEY (pb, pa) REFERENCES app.tb_pair (b, a),
    CONSTRAINT aa_parent FOREIGN KEY (fk_parent) REFERENCES app.tb_parent (pk_parent),
    CONSTRAINT mm_ext FOREIGN KEY (ext_id) REFERENCES other.tb_ext (id),
    CONSTRAINT ck_pa CHECK (pa > 0)
);
CREATE INDEX ix_child_pa ON app.tb_child (pa, lower(pb::text)) WHERE pa IS NOT NULL;
CREATE TABLE app.tb_part (id INT, at DATE) PARTITION BY RANGE (at);
CREATE TABLE app.tb_part_2026 PARTITION OF app.tb_part
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE VIEW app.v_child AS SELECT pk_child FROM app.tb_child;
CREATE MATERIALIZED VIEW app.mv_child AS SELECT pk_child FROM app.tb_child;
CREATE FUNCTION app.fn_one() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$;
CREATE PROCEDURE app.pr_do() LANGUAGE sql AS $$ SELECT 1 $$;
CREATE AGGREGATE app.agg_sum(INT) (sfunc = int4pl, stype = INT);
"""


@pytest.fixture
def url(fresh_database_factory: Callable[[str], str]) -> str:
    built = fresh_database_factory("confiture_snap")
    with psycopg.connect(built, autocommit=True) as c:
        c.execute(DDL)
    return built


@pytest.fixture
def conn(url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(url, autocommit=True) as c:
        yield c


def test_every_table_like_relation_is_a_table(conn: psycopg.Connection) -> None:
    """Tables, partitioned tables and views, in every user schema — what
    ``information_schema.tables`` listed; a materialized view is not one."""
    snapshot = SchemaSnapshotter(conn).capture()
    assert sorted(snapshot.tables) == [
        "app.tb_Mixed",
        "app.tb_child",
        "app.tb_pair",
        "app.tb_parent",
        "app.tb_part",
        "app.tb_part_2026",
        "app.v_child",
        "other.tb_ext",
    ]
    assert snapshot.views == {"v_child"}
    assert snapshot.materialized_views == {"mv_child"}


def test_routines_of_every_kind_and_owner(conn: psycopg.Connection) -> None:
    """Functions, procedures and aggregates; an extension's routines too."""
    functions = SchemaSnapshotter(conn).capture().functions
    assert {"fn_one", "pr_do", "agg_sum"} <= functions
    assert {"citext", "texticlike"} <= functions


def test_a_column_carries_its_whole_type(conn: psycopg.Connection) -> None:
    columns = SchemaSnapshotter(conn).capture().tables["app.tb_Mixed"].columns
    assert [(c.name, c.data_type, c.is_nullable) for c in columns.values()] == [
        ("UserId", "bigint", False),
        ("amount", "numeric(10,2)", True),
        ("tags", "text[]", True),
        ("mood", "app.mood", True),
        ("at", "timestamp with time zone", True),
    ]
    assert columns["at"].column_default == "now()"
    assert columns["amount"].column_default is None


def test_a_not_null_column_is_not_a_constraint(conn: psycopg.Connection) -> None:
    table = SchemaSnapshotter(conn).capture().tables["app.tb_child"]
    assert [(c.name, c.constraint_type, c.columns) for c in table.constraints] == [
        ("aa_parent", "FOREIGN KEY", ["fk_parent"]),
        ("ck_pa", "CHECK", []),
        ("mm_ext", "FOREIGN KEY", ["ext_id"]),
        ("tb_child_pkey", "PRIMARY KEY", ["pk_child"]),
        ("zz_pair", "FOREIGN KEY", ["pb", "pa"]),
    ]


def test_a_foreign_key_pairs_its_columns(conn: psycopg.Connection) -> None:
    table = SchemaSnapshotter(conn).capture().tables["app.tb_child"]
    assert [
        (fk.constraint_name, fk.column_name, fk.referenced_table, fk.referenced_column)
        for fk in table.foreign_keys
    ] == [
        ("aa_parent", "fk_parent", "tb_parent", "pk_parent"),
        ("mm_ext", "ext_id", "tb_ext", "id"),
        ("zz_pair", "pb", "tb_pair", "b"),
        ("zz_pair", "pa", "tb_pair", "a"),
    ]


def test_an_index_has_columns(conn: psycopg.Connection) -> None:
    """Every index, the ones backing a constraint included, with its keys."""
    table = SchemaSnapshotter(conn).capture().tables["app.tb_child"]
    assert [(i.name, i.table_name, i.is_unique, i.columns) for i in table.indexes] == [
        ("ix_child_pa", "tb_child", False, ["pa", "lower(CAST(pb AS text))"]),
        ("tb_child_pkey", "tb_child", True, ["pk_child"]),
    ]


def test_compare_sees_a_typmod_and_no_not_null_constraint(conn: psycopg.Connection) -> None:
    snapshotter = SchemaSnapshotter(conn)
    before = snapshotter.capture()
    conn.execute("ALTER TABLE app.tb_pair ALTER COLUMN label TYPE VARCHAR(100)")
    conn.execute("ALTER TABLE app.tb_pair ADD COLUMN note TEXT NOT NULL DEFAULT ''")
    changes = snapshotter.compare(before, snapshotter.capture())
    [modified] = changes["tables_modified"]
    assert modified["table"] == "app.tb_pair"
    assert modified["columns_added"] == {"note"}
    assert [
        (m["column"], m["before_type"], m["after_type"]) for m in modified["columns_modified"]
    ] == [("label", "character varying(50)", "character varying(100)")]
    assert modified["constraints_added"] == set()


def test_the_sandbox_helpers(url: str) -> None:
    with MigrationSandbox(url) as sandbox:
        assert_helpers(sandbox)


def assert_helpers(sandbox: MigrationSandbox) -> None:
    assert sandbox.table_exists("tb_child", schema="app")
    assert sandbox.table_exists("v_child", schema="app")
    assert sandbox.table_exists("tb_part", schema="app")
    assert not sandbox.table_exists("mv_child", schema="app")
    assert not sandbox.table_exists("tb_child")
    assert sandbox.column_exists("tb_child", "pa", schema="app")
    assert not sandbox.column_exists("tb_child", "absent", schema="app")
    assert not sandbox.column_exists("absent", "pa", schema="app")
