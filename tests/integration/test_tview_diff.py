"""``migrate diff --from db`` reads a pg_tviews TVIEW as the one object ``drift`` reads (#562).

Read as ``pg_dump`` text, a TVIEW the tree did not declare was its parts: a
``DROP TABLE tv_x`` (irreversible), a ``DROP VIEW v_x``, and a ``DROP TRIGGER`` for
pg_tviews' refresh triggers on every base table — tables the tree declares among
them. Read through ``live_catalog``, it is one object, dropped the way pg_tviews
drops one.

pg_tviews is in no stock PostgreSQL: these tests run on the ``pg-tviews`` CI leg
and skip with the reason elsewhere.
"""

from collections.abc import Callable

import psycopg
import pytest
from tests.conftest import create_supported_pg_tviews

from confiture import platform
from confiture.core.differ_sql import DifferSQLGenerator

pytestmark = pytest.mark.integration

BASE = """
CREATE TABLE tb_user (pk_user bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, name text);
CREATE TABLE tb_post (
    pk_post bigint NOT NULL,
    id uuid NOT NULL,
    fk_user bigint REFERENCES tb_user,
    title text,
    created date NOT NULL,
    PRIMARY KEY (pk_post, created)
) PARTITION BY RANGE (created);
CREATE TABLE tb_post_2026 PARTITION OF tb_post FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
"""

TVIEW = """
CREATE TABLE tv_post AS
SELECT p.pk_post, p.id, jsonb_build_object('id', p.id, 'author', u.name) AS data
FROM tb_post p JOIN tb_user u ON u.pk_user = p.fk_user;
"""


@pytest.fixture
def database(fresh_database_factory: Callable[[str], str]) -> str:
    url = fresh_database_factory("confiture_tv_diff")
    with psycopg.connect(url, autocommit=True) as conn:
        if "pg_tviews" not in conn.execute("SHOW shared_preload_libraries").fetchone()[0]:
            pytest.skip("pg_tviews is not preloaded on this server (the pg-tviews CI leg is)")
        # Its own round trip: in one batch with the CREATE EXTENSION, pg_tviews'
        # hook is not loaded yet and `tv_post` becomes a plain table (measured).
        create_supported_pg_tviews(conn)
        conn.execute(BASE)
        conn.execute(TVIEW)
    return url


def test_a_tview_the_tree_does_not_declare_is_one_drop(database: str) -> None:
    changes = platform.diff(database, "CREATE EXTENSION pg_tviews;" + BASE).changes
    assert [type(change).__name__ for change in changes] == ["ObjectDropped"]
    (change,) = changes
    assert change.ref.kind == "tview"
    statement = DifferSQLGenerator().generate_up(change)
    assert "tviews.pg_tviews_drop" in statement
    assert "DROP TRIGGER" not in statement.upper()
    assert "DROP VIEW" not in statement.upper()


def test_a_database_built_from_a_tree_with_a_tview_is_no_change(database: str) -> None:
    assert platform.diff(database, "CREATE EXTENSION pg_tviews;" + BASE + TVIEW).changes == []
