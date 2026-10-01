"""The live side reads a TVIEW from ``tviews.registry`` (#504).

pg_tviews is in no stock PostgreSQL: these tests run where the extension is
available, which the ``pg-tviews`` CI leg guarantees, and skip with the reason
elsewhere.
"""

from __future__ import annotations

from collections.abc import Callable

import psycopg
import pytest
from tests.conftest import create_supported_pg_tviews

from confiture.core import live_catalog
from confiture.core.linting.inventory import build_model
from confiture.core.schema_facts import collect_schema_facts
from confiture.core.schema_model import TView, ref_for
from confiture.exceptions import ConfigurationError

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
        create_supported_pg_tviews(conn)
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


def test_a_view_that_took_a_stale_backing_views_name_is_the_trees(tview_database: str) -> None:
    """The registry names the backing view; ``v_<entity>`` by name is only a guess.

    Once ``v_post`` is dropped, the registration is stale (``view`` is NULL) and a
    view the author creates under that name is theirs, read like any other view.
    """
    with psycopg.connect(tview_database, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_attribute WHERE attrelid = 'tviews.registry'::regclass"
            " AND attname = 'view'"
        ).fetchone():
            pytest.skip("this pg_tviews' registry has no `view` column (fraiseql/pg_tviews#153)")
        conn.execute("DROP VIEW v_post")
        conn.execute("CREATE VIEW v_post AS SELECT 1 AS mine")
        model = live_catalog.read(conn, schemas=["public"], views=True, tviews=True)

    assert list(model.tviews) == [ref_for("tview", "public", "tv_post")]
    assert ref_for("view", "public", "v_post") in model.views


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


PINNED = TREE.replace(
    "CREATE TABLE tv_post AS", "CREATE UNLOGGED TABLE tv_post WITH (fillfactor = 70) AS"
)


@pytest.fixture
def pinned_database(fresh_database_factory: Callable[[str], str]) -> str:
    url = fresh_database_factory("confiture_tv")
    with psycopg.connect(url, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tviews'"
        ).fetchone():
            pytest.skip("pg_tviews is not installed on this server (the pg-tviews CI leg has it)")
        create_supported_pg_tviews(conn)
        conn.execute(PINNED)
    return url


def test_the_live_side_reads_every_option_the_registry_holds(tview_database: str) -> None:
    """The registry holds each key, pinned or not; stock pg_tviews: unlogged, fillfactor 85."""
    with psycopg.connect(tview_database) as conn:
        (found,) = live_catalog.tviews(conn, ["public"])

    assert (found.logged, found.fillfactor) == (False, 85)


def test_a_tview_left_at_pg_tviews_defaults_reads_as_pinning_nothing(tview_database: str) -> None:
    """Measured for ``PARITY_NORMALISATIONS["tview_defaults"]``: the tree wrote no option, the
    registry holds pg_tviews' defaults. The day they change, this fails and the normalisation goes.
    """
    (declared,) = build_model(TREE).tviews.values()
    with psycopg.connect(tview_database) as conn:
        (found,) = live_catalog.tviews(conn, ["public"])

    assert ((declared.logged, declared.fillfactor), (found.logged, found.fillfactor)) == (
        (None, None),
        (False, 85),
    )


def test_the_parse_side_and_the_live_side_hold_one_pinned_tview(pinned_database: str) -> None:
    from confiture.core.schema_model import normalise_for_parity

    with psycopg.connect(pinned_database) as conn:
        live = live_catalog.read(conn, schemas=["public"], tviews=True)

    assert normalise_for_parity(live).tviews == normalise_for_parity(build_model(PINNED)).tviews


def test_a_database_built_from_a_pinned_tree_has_no_drift(pinned_database: str) -> None:
    assert _drift(pinned_database, PINNED) == []


def test_a_pinned_option_changed_by_hand_is_drift(pinned_database: str) -> None:
    with psycopg.connect(pinned_database, autocommit=True) as conn:
        conn.execute("ALTER TABLE tv_post SET LOGGED")
        conn.execute("ALTER TABLE tv_post SET (fillfactor = 60)")

    assert _drift(pinned_database, PINNED) == [
        ("tview_option_mismatch", "warning", "tv_post"),
        ("tview_option_mismatch", "warning", "tv_post"),
    ]


def test_an_option_the_tree_does_not_pin_is_never_drift(tview_database: str) -> None:
    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute("ALTER TABLE tv_post SET LOGGED")

    assert _drift(tview_database, TREE) == []


CALLED = TREE.replace(
    "CREATE TABLE tv_post AS\n",
    "SELECT tviews.pg_tviews_create_or_replace('tv_post', $q$\n",
).replace(
    "JOIN tb_user u ON u.pk_user = p.fk_user;",
    """JOIN tb_user u ON u.pk_user = p.fk_user$q$, options => '{"logged": true, "fillfactor": 70}');""",
)


def test_a_tree_that_calls_pg_tviews_is_the_database_it_builds(
    fresh_database_factory: Callable[[str], str],
) -> None:
    """The form a generated migration writes, read back as the tree it is."""
    from confiture.core.schema_model import normalise_for_parity

    url = fresh_database_factory("confiture_tv")
    with psycopg.connect(url, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tviews'"
        ).fetchone():
            pytest.skip("pg_tviews is not installed on this server (the pg-tviews CI leg has it)")
        create_supported_pg_tviews(conn)
        conn.execute(CALLED)
        live = live_catalog.read(conn, schemas=["public"], tviews=True)

    (found,) = live.tviews.values()
    assert (found.logged, found.fillfactor) == (True, 70)
    assert normalise_for_parity(live).tviews == normalise_for_parity(build_model(CALLED)).tviews
    assert _drift(url, CALLED) == []


LOGGED = f"{TREE}ALTER TABLE tv_post SET LOGGED;\n"


def test_set_logged_in_the_tree_is_what_the_database_holds(tview_database: str) -> None:
    """The tree ``tview_002`` asks for, built, reads back as itself; left unlogged, it drifts."""
    from confiture.core.schema_model import normalise_for_parity

    assert _drift(tview_database, LOGGED) == [("tview_option_mismatch", "warning", "tv_post")]

    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute("ALTER TABLE tv_post SET LOGGED")
        live = live_catalog.read(conn, schemas=["public"], tviews=True)

    assert normalise_for_parity(live).tviews == normalise_for_parity(build_model(LOGGED)).tviews
    assert _drift(tview_database, LOGGED) == []


FILLED = f"{TREE}ALTER TABLE tv_post SET (fillfactor = 70);\n"
RESET = f"{FILLED}ALTER TABLE tv_post RESET (fillfactor);\n"


def test_set_fillfactor_in_the_tree_is_what_the_database_holds(tview_database: str) -> None:
    """``SET (fillfactor = n)`` built reads back as itself; ``RESET`` reads back as 100."""
    from confiture.core.schema_model import normalise_for_parity

    assert _drift(tview_database, FILLED) == [("tview_option_mismatch", "warning", "tv_post")]

    for tree, statement in ((FILLED, "SET (fillfactor = 70)"), (RESET, "RESET (fillfactor)")):
        with psycopg.connect(tview_database, autocommit=True) as conn:
            conn.execute(f"ALTER TABLE tv_post {statement}")
            live = live_catalog.read(conn, schemas=["public"], tviews=True)

        assert normalise_for_parity(live).tviews == normalise_for_parity(build_model(tree)).tviews
        assert _drift(tview_database, tree) == []


def test_a_tview_that_became_a_plain_table_is_caught(fresh_database: str) -> None:
    """The tree declares a TVIEW and the database holds a plain ``tv_post`` table.

    Measured on PostgreSQL 18.4 + pg_tviews 0.1.0: a session that has not loaded the
    library (no ``shared_preload_libraries``, or the ``CREATE EXTENSION`` in the same
    batch) turns ``CREATE TABLE tv_post AS`` into a plain table and registers nothing,
    silently. The table is made here with a column list, which pg_tviews never
    intercepts, so the test is the same with the library preloaded or not.
    """
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(TREE.split("CREATE TABLE tv_post", maxsplit=1)[0])
        conn.execute("CREATE TABLE tv_post (pk_post bigint, id uuid, data jsonb)")

    found = _drift(fresh_database, TREE)
    assert ("missing_tview", "critical", "tv_post") in found
    assert ("extra_table", "warning", "public.tv_post") in found


def test_a_plain_tv_table_without_pg_tviews_is_a_table_on_both_sides(fresh_database: str) -> None:
    """No prefix rule on either side: only a CTAS is a TVIEW, and only the registry says one exists."""
    tree = "CREATE TABLE tv_order (id bigint PRIMARY KEY, data jsonb);\n"
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(tree)
        assert live_catalog.tviews(conn, ["public"]) == []

    assert _drift(fresh_database, tree) == []


def test_a_pg_tviews_offering_another_contract_is_refused(
    tview_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live model, drift and preflight all read TVIEWs through the contract."""
    monkeypatch.setattr(live_catalog, "CONTRACT_VERSION", 99)

    with psycopg.connect(tview_database) as conn:
        for read in (
            lambda: live_catalog.tviews(conn, ["public"]),
            lambda: live_catalog.read(conn, schemas=["public"], tviews=True),
            lambda: collect_schema_facts(conn),
        ):
            with pytest.raises(ConfigurationError) as refused:
                read()
            assert refused.value.error_code == "CONFIG_014"
            conn.rollback()


def test_a_database_without_pg_tviews_is_never_refused(
    fresh_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live_catalog, "CONTRACT_VERSION", 99)

    with psycopg.connect(fresh_database) as conn:
        assert live_catalog.read(conn, schemas=["public"], tviews=True).tviews == {}
