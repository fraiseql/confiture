"""A TVIEW's indexes, read from the database as pg_tviews publishes them.

``tviews.registry.managed_indexes`` (pg_tviews 0.1.0-beta.27, #219) names the
indexes pg_tviews created on a TVIEW's table. The user's are every other index
on it but those a constraint uses — pg_tviews' own rule, read, never re-derived.
The live reader reads them from the one index query it already runs, splits them
into ``TView.indexes`` and ``TView.managed_indexes``, and a tree compared with
the database it built is the same TVIEW once pg_tviews' adoptions are applied.

The pins of pg_tviews' behaviour are what the comparison relies on: a reserved
name refused, a user's GIN on ``data`` kept across the option, a rebuild refused
over an invalid user index.
"""

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import psycopg
import pytest
from psycopg import errors
from tests.conftest import create_supported_pg_tviews

from confiture.core import live_catalog
from confiture.core.differ import CATALOGUED, adopted_by_pg_tviews
from confiture.core.schema_model import TView, parity_tview, ref_for
from confiture.core.schema_read import read_text

pytestmark = pytest.mark.integration

TREE = """
CREATE TABLE tb_post (pk_post bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, title text);
CREATE TABLE tv_post AS
SELECT p.pk_post, p.id, p.title, jsonb_build_object('id', p.id, 'title', p.title) AS data
FROM tb_post p;
"""
USER_INDEX = "CREATE INDEX ix_tv_post_title ON tv_post (title);\n"
#: pg_tviews' own index on ``id``, written exactly: pg_tviews already holds the name,
#: so ``IF NOT EXISTS`` skips it and the tree's statement is pg_tviews' index.
ADOPTED_COPY = "CREATE INDEX IF NOT EXISTS idx_tv_post_id ON tv_post (id);\n"
TVREF = ref_for("tview", "public", "tv_post")
QUERY = "SELECT query FROM tviews.registry WHERE name = 'tv_post'"


@pytest.fixture
def tview_database(fresh_database_factory: Callable[[str], str]) -> str:
    url = fresh_database_factory("confiture_tvi")
    with psycopg.connect(url, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tviews'"
        ).fetchone():
            pytest.skip("pg_tviews is not installed on this server (the pg-tviews CI leg has it)")
        create_supported_pg_tviews(conn)
        conn.execute(TREE)
    return url


def _tview(conn: psycopg.Connection) -> TView:
    return live_catalog.read(conn, schemas=["public"]).tviews[TVREF]


def _names(indexes: Any) -> list[str]:
    return sorted(index.name for index in indexes or ())


def _registry_managed(conn: psycopg.Connection) -> list[str]:
    row = conn.execute(
        "SELECT ARRAY(SELECT m::regclass::text FROM unnest(managed_indexes) m ORDER BY 1)"
        " FROM tviews.registry WHERE name = 'tv_post'"
    ).fetchone()
    assert row is not None
    return list(row[0])


def _invalid_unique_index(conn: psycopg.Connection) -> None:
    """A failed ``CREATE UNIQUE INDEX CONCURRENTLY`` leaves the index INVALID."""
    conn.execute(
        "INSERT INTO tb_post VALUES (1, gen_random_uuid(), 'same'), (2, gen_random_uuid(), 'same')"
    )
    with pytest.raises(errors.UniqueViolation):
        conn.execute("CREATE UNIQUE INDEX CONCURRENTLY ux_tv_post_title ON tv_post (title)")


def test_a_user_index_is_read_with_its_validity(tview_database: str) -> None:
    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute(USER_INDEX)
        _invalid_unique_index(conn)
        tview = _tview(conn)

    validity = {index.name: index.valid for index in tview.indexes or ()}
    assert validity == {"ix_tv_post_title": True, "ux_tv_post_title": False}


def test_pg_tviews_own_and_constraint_indexes_are_not_the_user_s(tview_database: str) -> None:
    """The primary key's index, pg_tviews' own, and one a referencing key uses (N1)."""
    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute(USER_INDEX)
        conn.execute("CREATE UNIQUE INDEX ux_tv_post_id ON tv_post (id)")
        conn.execute("CREATE TABLE tb_ref (post uuid REFERENCES tv_post (id))")
        tview = _tview(conn)
        managed = _registry_managed(conn)

    assert _names(tview.indexes) == ["ix_tv_post_title"]
    assert managed
    assert _names(tview.managed_indexes) == managed


def test_an_exact_copy_of_pg_tviews_gin_is_adopted(tview_database: str) -> None:
    """``idx_tv_post_data_gin`` is reserved; written exactly, it is pg_tviews' own."""
    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute("CREATE INDEX idx_tv_post_data_gin ON tv_post USING gin (data)")
        tview = _tview(conn)
        managed = _registry_managed(conn)

    assert "idx_tv_post_data_gin" in managed
    assert "idx_tv_post_data_gin" in _names(tview.managed_indexes)
    assert "idx_tv_post_data_gin" not in _names(tview.indexes)


def test_another_index_under_a_reserved_name_is_refused(tview_database: str) -> None:
    with (
        psycopg.connect(tview_database, autocommit=True) as conn,
        pytest.raises(psycopg.Error) as refused,
    ):
        conn.execute("CREATE INDEX idx_tv_post_data_gin ON tv_post USING gin (data jsonb_path_ops)")
    assert refused.value.sqlstate == "42939"


def test_a_user_gin_on_data_survives_the_option(tview_database: str) -> None:
    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute("CREATE INDEX ix_tv_post_data ON tv_post USING gin (data)")
        for on in ("true", "false"):
            conn.execute(
                "SELECT tviews.pg_tviews_create_or_replace('tv_post', query,"
                f" options => '{{\"data_gin_index\": {on}}}') FROM tviews.registry"
                " WHERE name = 'tv_post'"
            )
        tview = _tview(conn)

    assert "ix_tv_post_data" in _names(tview.indexes)


def test_a_rebuild_is_refused_over_an_invalid_user_index(tview_database: str) -> None:
    """Why a generated migration drops an index before ``pg_tviews_create_or_replace()``."""
    with psycopg.connect(tview_database, autocommit=True) as conn:
        _invalid_unique_index(conn)
        with pytest.raises(psycopg.Error) as refused:
            conn.execute(
                "SELECT tviews.pg_tviews_create_or_replace('tv_post', 'SELECT p.pk_post, p.id,"
                " p.title, upper(p.title) AS shout, jsonb_build_object(''id'', p.id) AS data"
                " FROM tb_post p')"
            )
    assert refused.value.sqlstate == "55000"


def test_the_tree_is_the_database_it_built(tview_database: str) -> None:
    """Parity: what the tree writes on the TVIEW is what the database holds, once
    pg_tviews' adoption of the exact copy is applied (``adopted_by_pg_tviews``)."""
    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute(USER_INDEX + ADOPTED_COPY)
        live = _tview(conn)
    tree = read_text(TREE + USER_INDEX + ADOPTED_COPY).catalogued.tviews[
        ref_for("tview", None, "tv_post")
    ]

    kept, skipped = adopted_by_pg_tviews(tree, live, CATALOGUED.rules)
    assert skipped == ()
    expected = parity_tview(replace(tree, indexes=kept), CATALOGUED.rules).indexes
    assert expected == parity_tview(live, CATALOGUED.rules).indexes
    assert _names(kept) == ["ix_tv_post_title"]


class _Counted:
    """A connection that counts the index queries run through it."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self.index_queries = 0

    def execute(self, query: Any, params: Any = None) -> Any:
        if "pg_get_indexdef" in str(query):
            self.index_queries += 1
        return self.conn.execute(query, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.conn, name)


def test_the_reader_runs_one_index_query(tview_database: str) -> None:
    """A TVIEW's indexes come from the rows the tables' index query already read."""
    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute(USER_INDEX)
        counted = _Counted(conn)
        tview = live_catalog.read(counted, schemas=["public"]).tviews[TVREF]  # type: ignore[arg-type]

    assert counted.index_queries == 1
    assert _names(tview.indexes) == ["ix_tv_post_title"]


def test_tviews_reads_no_index(tview_database: str) -> None:
    """``live_catalog.tviews()`` reads the registry alone: its indexes are not read."""
    with psycopg.connect(tview_database) as conn:
        (tview,) = live_catalog.tviews(conn, ["public"])
    assert tview.indexes is None


def _drift(url: str, tree: str, tmp_path: Any) -> Any:
    from confiture.core.drift import SchemaDriftDetector

    schema_file = tmp_path / "schema.sql"
    schema_file.write_text("CREATE EXTENSION pg_tviews;\n" + tree, encoding="utf-8")
    with psycopg.connect(url) as conn:
        return SchemaDriftDetector(conn).compare_with_schema_file(str(schema_file))


def test_drift_reports_an_invalid_unique_user_index(tview_database: str, tmp_path: Any) -> None:
    unique = "CREATE UNIQUE INDEX ux_tv_post_title ON tv_post (title);\n"
    with psycopg.connect(tview_database, autocommit=True) as conn:
        _invalid_unique_index(conn)
    report = _drift(tview_database, TREE + unique, tmp_path)

    found = {(i.drift_type.value, i.severity.value) for i in report.drift_items}
    assert found == {("missing_index", "critical"), ("extra_index", "info")}
    (missing,) = [i for i in report.drift_items if i.drift_type.value == "missing_index"]
    assert "INVALID" in missing.message
    assert missing.object_name == "public.tv_post.ux_tv_post_title"


def test_drift_takes_an_adopted_copy_as_pg_tviews_own(tview_database: str, tmp_path: Any) -> None:
    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute(USER_INDEX + ADOPTED_COPY)
    report = _drift(tview_database, TREE + USER_INDEX + ADOPTED_COPY, tmp_path)

    assert report.drift_items == []
    assert report.indexes_checked >= 1


def test_drift_refuses_an_index_pg_tviews_skipped(tview_database: str, tmp_path: Any) -> None:
    """pg_tviews skipped it: its name was taken by pg_tviews' own index (DIFFER_410)."""
    from confiture.exceptions import DifferError

    skipped = "CREATE INDEX IF NOT EXISTS idx_tv_post_id ON tv_post (lower(id::text));\n"
    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute(skipped)
    with pytest.raises(DifferError) as refused:
        _drift(tview_database, TREE + skipped, tmp_path)
    assert refused.value.error_code == "DIFFER_410"
