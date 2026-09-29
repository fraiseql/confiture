"""The live side reads a TVIEW from ``pg_tview_meta`` (#504).

pg_tviews is in no stock PostgreSQL: these tests run where the extension is
available, which the ``pg-tviews`` CI leg guarantees, and skip with the reason
elsewhere.
"""

from __future__ import annotations

from collections.abc import Callable

import psycopg
import pytest

from confiture.core import live_catalog
from confiture.core.linting.inventory import build_model
from confiture.core.schema_model import TView, ref_for

pytestmark = pytest.mark.integration

TREE = """
CREATE TABLE tb_user (pk_user bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, name text);
CREATE TABLE tb_post (
    pk_post bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, fk_user bigint REFERENCES tb_user, title text
);
CREATE TABLE tv_post AS
SELECT p.pk_post, p.id, jsonb_build_object('id', p.id, 'author', u.name) AS data
FROM tb_post p JOIN tb_user u ON u.pk_user = p.fk_user;
"""


@pytest.fixture
def tview_database(fresh_database_factory: Callable[[str], str]) -> str:
    url = fresh_database_factory("confiture_tv")
    with psycopg.connect(url, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tviews'"
        ).fetchone():
            pytest.skip("pg_tviews is not installed on this server (the pg-tviews CI leg has it)")
        # Its own round trip: in one batch with the CREATE EXTENSION, pg_tviews'
        # hook is not loaded yet and `tv_post` becomes a plain table (measured).
        conn.execute("CREATE EXTENSION pg_tviews")
        conn.execute(TREE)
    return url


def test_the_live_side_reads_each_tview(tview_database: str) -> None:
    with psycopg.connect(tview_database) as conn:
        found = live_catalog.tviews(conn, ["public"])

    assert [(t.schema, t.name) for t in found] == [("public", "tv_post")]
    # One deparser on both sides: the query reads the same from the DDL and the database.
    (declared,) = build_model(TREE).tviews.values()
    assert found[0].definition == declared.definition


def test_a_database_without_pg_tviews_has_none(fresh_database: str) -> None:
    with psycopg.connect(fresh_database) as conn:
        assert live_catalog.tviews(conn, ["public"]) == []


def test_the_model_holds_the_tview_and_not_its_parts(tview_database: str) -> None:
    with psycopg.connect(tview_database) as conn:
        model = live_catalog.read(conn, schemas=["public"], views=True, triggers=True, tviews=True)

    assert list(model.tviews) == [ref_for("tview", "public", "tv_post")]
    assert isinstance(model.tviews[ref_for("tview", "public", "tv_post")], TView)
    assert ref_for("table", "public", "tv_post") not in model.tables
    assert ref_for("view", "public", "v_post") not in model.views
    assert [t.name for t in model.triggers.values()] == []


def _drift(url: str, ddl: str) -> list[tuple[str, str, str]]:
    """What ``confiture drift --schema`` reports: the file's schemas, objects compared."""
    from confiture.core.drift import SchemaDriftDetector, parse_expected_schema

    expected = parse_expected_schema(ddl)
    with psycopg.connect(url) as conn:
        detector = SchemaDriftDetector(conn)
        actual = detector.get_live_schema(expected.schemas, objects=True)
        report = detector.compare_schemas(expected.model, actual, objects=True)
    return sorted((i.drift_type.value, i.severity.value, i.object_name) for i in report.drift_items)


def test_a_database_built_from_its_tree_has_no_drift(tview_database: str) -> None:
    """1.26.0 reported `extra_table warning public.tv_post` here (measured)."""
    assert _drift(tview_database, TREE) == []


def test_a_dropped_tview_is_critical_drift(tview_database: str) -> None:
    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute("DROP TABLE tv_post")

    assert _drift(tview_database, TREE) == [("missing_tview", "critical", "tv_post")]


def test_the_parse_side_and_the_live_side_hold_one_tview(tview_database: str) -> None:
    """The parity every other kind holds (``test_parse_live_parity``), for a TVIEW."""
    from confiture.core.schema_model import normalise_for_parity

    with psycopg.connect(tview_database) as conn:
        live = live_catalog.read(conn, schemas=["public"], tviews=True)

    assert normalise_for_parity(live).tviews == normalise_for_parity(build_model(TREE)).tviews


def test_a_tview_that_became_a_plain_table_is_caught(fresh_database: str) -> None:
    """Without pg_tviews loaded in the session, ``CREATE TABLE tv_post AS`` is a plain table.

    Measured on PostgreSQL 18.4 + pg_tviews 0.1.0: a session that has not loaded the
    library (no ``shared_preload_libraries``, or the ``CREATE EXTENSION`` in the same
    batch) creates ``tv_post`` and registers nothing, silently. Drift is where that
    surfaces: the tree declares a TVIEW and the database holds a table.
    """
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(TREE)

    found = _drift(fresh_database, TREE)
    assert ("missing_tview", "critical", "tv_post") in found
    assert ("extra_table", "warning", "public.tv_post") in found
