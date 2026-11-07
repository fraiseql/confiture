"""``view_columns`` and ``view_reads`` agree with PostgreSQL, and with themselves (#812).

A tree is built into a fresh database and read back. Every view's columns, derived
from its definition, are the ones ``pg_attribute`` holds — from the tree's model and
from the database's — and its reads are the same from either side.
"""

from collections.abc import Callable

import psycopg
import pytest
from tests.conftest import create_supported_pg_tviews

from confiture.core.schema_model import ObjectRef, SchemaModel
from confiture.platform import introspect, parse_schema, view_columns, view_reads

pytestmark = pytest.mark.integration

TREE = """
CREATE SCHEMA app;
CREATE TABLE tb_a (id bigint PRIMARY KEY, tenant_id uuid, label text);
CREATE TABLE app.tb_b (id bigint, a_id bigint, note text);
CREATE TYPE pair AS (f1 int, f2 int);

CREATE VIEW v_star AS SELECT * FROM tb_a;
CREATE VIEW v_join AS SELECT a.*, b.note FROM tb_a a JOIN app.tb_b b ON b.a_id = a.id;
CREATE VIEW v_using AS SELECT * FROM tb_a JOIN app.tb_b USING (id);
CREATE VIEW v_natural AS SELECT * FROM tb_a NATURAL JOIN app.tb_b;
CREATE VIEW v_union AS SELECT id AS k, label FROM tb_a UNION ALL SELECT a_id, note FROM app.tb_b;
CREATE VIEW v_cte AS
    WITH c (x, y) AS (SELECT id, label FROM tb_a) SELECT * FROM c, (VALUES (1, 2)) v;
CREATE VIEW v_list (x, y) AS SELECT id, label FROM tb_a;
CREATE VIEW v_list_star (x) AS SELECT * FROM tb_a;
CREATE VIEW app.v_outer AS SELECT s.*, 1 AS one FROM v_star s;
CREATE VIEW v_exprs AS SELECT
    1, count(*), 'x'::text, CASE WHEN id > 0 THEN 1 END, ARRAY[1, 2], ROW(1, 2)::pair,
    coalesce(label, ''), greatest(id, 1), nullif(id, 1), EXISTS (SELECT 1 FROM app.tb_b),
    (SELECT max(a_id) FROM app.tb_b), current_date, current_user, (ROW(1, 2)::pair).f1,
    label COLLATE "C"
FROM tb_a GROUP BY id, label;
CREATE VIEW v_casts AS SELECT
    id + 1, id::int, CASE WHEN id > 0 THEN NULL ELSE tenant_id END,
    CASE WHEN id > 0 THEN 1 END::int, (SELECT * FROM (SELECT note FROM app.tb_b) s LIMIT 1)
FROM tb_a;
CREATE MATERIALIZED VIEW mv_list (k) AS SELECT id, label FROM tb_a;
"""


def _built(url: str, tree: str) -> tuple[SchemaModel, SchemaModel]:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(tree)
    return parse_schema(tree), introspect(url, schemas=["public", "app"])


def _attributes(url: str, ref: ObjectRef) -> tuple[str, ...]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT attname FROM pg_attribute "
            "WHERE attrelid = to_regclass(%s) AND attnum > 0 AND NOT attisdropped "
            "ORDER BY attnum",
            (f"{ref.schema}.{ref.name}",),
        ).fetchall()
    return tuple(row[0] for row in rows)


def test_every_view_s_columns_are_postgresql_s(
    fresh_database_factory: Callable[[str], str],
) -> None:
    url = fresh_database_factory("confiture_vf")
    tree, live = _built(url, TREE)

    assert set(tree.views) == set(live.views)
    for ref in tree.views:
        held = _attributes(url, ref)
        assert view_columns(tree, ref) == held, ref.display
        assert view_columns(live, ref) == held, ref.display


def test_every_view_reads_the_same_from_either_side(
    fresh_database_factory: Callable[[str], str],
) -> None:
    url = fresh_database_factory("confiture_vf")
    tree, live = _built(url, TREE)

    for ref in tree.views:
        assert view_reads(tree, ref) == view_reads(live, ref), ref.display


TVIEW_TREE = """
CREATE TABLE tb_user (pk_user bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, name text);
CREATE TABLE tb_post (
    pk_post bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, fk_user bigint REFERENCES tb_user,
    title text
);
CREATE VIEW v_user AS SELECT pk_user, id, name FROM tb_user;
CREATE TABLE tv_post AS
SELECT p.pk_post, p.id, jsonb_build_object('id', p.id, 'author', u.name) AS data
FROM tb_post p JOIN v_user u ON u.pk_user = p.fk_user;
"""


def test_a_tview_s_columns_are_its_table_s(fresh_database_factory: Callable[[str], str]) -> None:
    url = fresh_database_factory("confiture_vf")
    with psycopg.connect(url, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tviews'"
        ).fetchone():
            pytest.skip("pg_tviews is not installed on this server (the pg-tviews CI leg has it)")
        create_supported_pg_tviews(conn)
        conn.execute(TVIEW_TREE)
    tree, live = parse_schema(TVIEW_TREE), introspect(url, schemas=["public"])

    (ref,) = tree.tviews
    assert ref in live.tviews
    held = _attributes(url, ref)
    assert view_columns(tree, ref) == view_columns(live, ref) == held
    assert view_reads(tree, ref) == view_reads(live, ref)
    assert {(r.kind, r.name) for r in view_reads(live, ref)} == {
        ("table", "tb_post"),
        ("view", "v_user"),
        ("table", "tb_user"),
    }
