"""The live side reads a TVIEW from ``tviews.registry`` (#504).

pg_tviews is in no stock PostgreSQL: these tests run where the extension is
available, which the ``pg-tviews`` CI leg guarantees, and skip with the reason
elsewhere.
"""

from collections.abc import Callable

import psycopg
import pytest
from tests.conftest import create_supported_pg_tviews

from confiture.core import live_catalog
from confiture.core.schema_facts import collect_schema_facts
from confiture.core.schema_model import TView, ref_for
from confiture.core.schema_read import read_text
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
    (declared,) = read_text(TREE).model.tviews.values()
    assert found[0].definition == declared.definition


def test_a_database_without_pg_tviews_has_none(fresh_database: str) -> None:
    with psycopg.connect(fresh_database) as conn:
        assert live_catalog.tviews(conn, ["public"]) == []


def test_the_model_holds_the_tview_and_not_its_parts(tview_database: str) -> None:
    with psycopg.connect(tview_database) as conn:
        model = live_catalog.read(conn, schemas=["public", "tviews"], views=True, triggers=True)

    assert list(model.tviews) == [ref_for("tview", "public", "tv_post")]
    assert isinstance(model.tviews[ref_for("tview", "public", "tv_post")], TView)
    assert ref_for("table", "public", "tv_post") not in model.tables
    assert dict(model.views) == {}
    assert [t.name for t in model.triggers.values()] == []


def _drift(url: str, ddl: str) -> list[tuple[str, str, str]]:
    """What ``confiture drift --schema`` reports: the file's schemas, objects compared."""
    from confiture.core.drift import SchemaDriftDetector, parse_expected_schema

    expected = parse_expected_schema(ddl)
    with psycopg.connect(url) as conn:
        detector = SchemaDriftDetector(conn)
        actual = detector.get_live_schema(expected.schemas, objects=True)
        report = detector.compare_schemas(expected.model, actual)
    return sorted((i.drift_type.value, i.severity.value, i.object_name) for i in report.drift_items)


def test_an_application_view_named_like_the_entity_is_the_trees(tview_database: str) -> None:
    """The registry names the backing view, which pg_tviews keeps in ``tviews``.

    ``v_<entity>`` is the application's query view in fraiseql's convention, so
    pg_tviews 0.1.0-beta.25 freed the name (fraiseql/pg_tviews#181): a ``v_post``
    created beside a live TVIEW is a view of the tree's, read like any other.
    """
    with psycopg.connect(tview_database, autocommit=True) as conn:
        backing = conn.execute(
            "SELECT n.nspname FROM tviews.registry r"
            " JOIN pg_class c ON c.oid = r.view JOIN pg_namespace n ON n.oid = c.relnamespace"
        ).fetchone()
        if backing is None or backing[0] == "public":
            pytest.skip("this pg_tviews keeps its backing view in the application's schema")
        conn.execute("CREATE VIEW v_post AS SELECT 1 AS mine")
        model = live_catalog.read(conn, schemas=["public", "tviews"], views=True)

    # Read with `tviews` too: the backing view there is the TVIEW's part, folded.
    assert list(model.tviews) == [ref_for("tview", "public", "tv_post")]
    assert list(model.views) == [ref_for("view", "public", "v_post")]


OWN_VIEW = f"{TREE}CREATE VIEW v_post AS SELECT data FROM tv_post;\n"


def test_a_tree_that_declares_its_own_entity_view_has_no_drift(
    fresh_database_factory: Callable[[str], str],
) -> None:
    """``tv_post`` and the application's ``v_post`` over it, built: one TVIEW and one view."""
    url = fresh_database_factory("confiture_tv")
    with psycopg.connect(url, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tviews'"
        ).fetchone():
            pytest.skip("pg_tviews is not installed on this server (the pg-tviews CI leg has it)")
        create_supported_pg_tviews(conn)
        try:
            conn.execute(OWN_VIEW)
        except psycopg.errors.DuplicateTable:
            pytest.skip("this pg_tviews keeps its backing view as public.v_post (pg_tviews#181)")
        model = live_catalog.read(conn, schemas=["public"], views=True)

    assert list(model.tviews) == [ref_for("tview", "public", "tv_post")]
    assert [ref.name for ref in model.views] == ["v_post"]
    assert _drift(url, OWN_VIEW) == []


UNCASCADED = """
CREATE TABLE tb_label (k int PRIMARY KEY, v text);
CREATE TABLE tb_user (pk_user bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, name text);
SELECT tviews.pg_tviews_create_or_replace('tv_user', $q$
SELECT u.pk_user, u.id, jsonb_build_object('label', (SELECT v FROM tb_label LIMIT 1)) AS data
FROM tb_user u$q$, options => '{"uncascaded_policy": "full_refresh"}');
"""


@pytest.fixture
def uncascaded_database(fresh_database_factory: Callable[[str], str]) -> str:
    """A TVIEW reading a table no cascade reaches, which declares what such a write does."""
    url = fresh_database_factory("confiture_tv")
    with psycopg.connect(url, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tviews'"
        ).fetchone():
            pytest.skip("pg_tviews is not installed on this server (the pg-tviews CI leg has it)")
        create_supported_pg_tviews(conn)
        conn.execute(UNCASCADED)
    return url


def test_the_live_side_reads_the_uncascaded_policy(uncascaded_database: str) -> None:
    """``tviews.registry.uncascaded_policy``, stored beside ``options`` and not in them."""
    from confiture.core.schema_model import normalise_for_parity

    with psycopg.connect(uncascaded_database) as conn:
        live = live_catalog.read(conn, schemas=["public"])

    (found,) = live.tviews.values()
    assert found.uncascaded_policy == "full_refresh"
    assert (
        normalise_for_parity(live).tviews
        == normalise_for_parity(read_text(UNCASCADED).model).tviews
    )
    assert _drift(uncascaded_database, UNCASCADED) == []


def test_a_policy_changed_on_the_database_is_drift(uncascaded_database: str) -> None:
    with psycopg.connect(uncascaded_database, autocommit=True) as conn:
        (definition,) = conn.execute("SELECT query FROM tviews.registry").fetchone()
        (answer,) = conn.execute(
            "SELECT tviews.pg_tviews_create_or_replace('tv_user', %s,"
            ' options => \'{"uncascaded_policy": "warn"}\')',
            (definition,),
        ).fetchone()

    assert answer == "altered"
    assert _drift(uncascaded_database, UNCASCADED) == [
        ("tview_option_mismatch", "warning", "tv_user")
    ]


def test_a_generated_migration_carries_the_policy_the_tree_declares(
    uncascaded_database: str, fresh_database_factory: Callable[[str], str]
) -> None:
    """The call ``migrate diff --generate`` writes builds the TVIEW the tree declares."""
    from confiture.core.ddl_objects import objects_in
    from confiture.core.sql_lexer import parse_file

    tview = next(
        obj for ref, (obj,) in objects_in([parse_file(UNCASCADED)]).items() if ref.kind == "tview"
    )
    url = fresh_database_factory("confiture_tv")
    with psycopg.connect(url, autocommit=True) as conn:
        create_supported_pg_tviews(conn)
        conn.execute(UNCASCADED.split("SELECT tviews", maxsplit=1)[0])
        conn.execute(tview.create_sql)
        (found,) = live_catalog.tviews(conn, ["public"])

    assert found.uncascaded_policy == "full_refresh"


#: A TVIEW reading the time and a table inside a STABLE function, declaring both
#: (fraiseql/pg_tviews#193): the function unqualified, its table on the path. A
#: declared table is a read no cascade reaches, so its policy rebuilds the TVIEW.
READS = """
CREATE TABLE tb_setting (code text PRIMARY KEY, value text);
CREATE TABLE tb_locale (code text PRIMARY KEY);
CREATE FUNCTION label_suffix() RETURNS text STABLE LANGUAGE sql
    AS $f$ SELECT value FROM tb_setting WHERE code = 'label_suffix' $f$;
CREATE TABLE tb_contract (pk_contract bigint PRIMARY KEY, id uuid NOT NULL UNIQUE,
                          name text, end_date date);
SELECT tviews.pg_tviews_create_or_replace('tv_contract', $q$
SELECT c.pk_contract, c.id,
       jsonb_build_object('label', c.name || label_suffix(),
                          'is_current', c.end_date >= CURRENT_DATE) AS data
FROM tb_contract c$q$,
    options => '{"time_refresh": "external", "uncascaded_policy": "full_refresh",
                 "function_reads": {"label_suffix()": ["tb_setting"]}}');
"""


@pytest.fixture
def reads_database(fresh_database_factory: Callable[[str], str]) -> str:
    url = fresh_database_factory("confiture_tv")
    with psycopg.connect(url, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tviews'"
        ).fetchone():
            pytest.skip("pg_tviews is not installed on this server (the pg-tviews CI leg has it)")
        create_supported_pg_tviews(conn)
        conn.execute(READS)
    return url


def test_the_live_side_reads_the_declared_reads(reads_database: str) -> None:
    """``tviews.registry.time_refresh`` and ``function_reads``, as the registry spells them."""
    from confiture.core.schema_model import FunctionRead

    with psycopg.connect(reads_database) as conn:
        (found,) = live_catalog.tviews(conn, ["public"])

    assert found.time_refresh == "external"
    assert found.function_reads == (FunctionRead("public.label_suffix()", ("tb_setting",)),)
    assert _drift(reads_database, READS) == []


def test_a_declared_read_changed_on_the_database_is_drift(reads_database: str) -> None:
    with psycopg.connect(reads_database, autocommit=True) as conn:
        (definition,) = conn.execute("SELECT query FROM tviews.registry").fetchone()
        (answer,) = conn.execute(
            "SELECT tviews.pg_tviews_create_or_replace('tv_contract', %s, options =>"
            """ '{"function_reads": {"label_suffix()": ["tb_setting", "tb_locale"]}}')""",
            (definition,),
        ).fetchone()

    assert answer == "altered"
    assert _drift(reads_database, READS) == [("tview_option_mismatch", "warning", "tv_contract")]


def test_a_generated_migration_carries_the_reads_the_tree_declares(
    reads_database: str, fresh_database_factory: Callable[[str], str]
) -> None:
    """The call ``migrate diff --generate`` writes passes pg_tviews' default ``error`` policy."""
    from confiture.core.ddl_objects import objects_in
    from confiture.core.sql_lexer import parse_file

    tview = next(
        obj for ref, (obj,) in objects_in([parse_file(READS)]).items() if ref.kind == "tview"
    )
    url = fresh_database_factory("confiture_tv")
    with psycopg.connect(url, autocommit=True) as conn:
        create_supported_pg_tviews(conn)
        conn.execute(READS.split("SELECT tviews", maxsplit=1)[0])
        conn.execute(tview.create_sql)
        (found,) = live_catalog.tviews(conn, ["public"])

    assert (found.time_refresh, len(found.function_reads or ())) == ("external", 1)
    assert _drift(url, READS) == []


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
        live = live_catalog.read(conn, schemas=["public"])

    assert normalise_for_parity(live).tviews == normalise_for_parity(read_text(TREE).model).tviews


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
    (declared,) = read_text(TREE).model.tviews.values()
    with psycopg.connect(tview_database) as conn:
        (found,) = live_catalog.tviews(conn, ["public"])

    assert ((declared.logged, declared.fillfactor), (found.logged, found.fillfactor)) == (
        (None, None),
        (False, 85),
    )


def test_the_parse_side_and_the_live_side_hold_one_pinned_tview(pinned_database: str) -> None:
    from confiture.core.schema_model import normalise_for_parity

    with psycopg.connect(pinned_database) as conn:
        live = live_catalog.read(conn, schemas=["public"])

    assert normalise_for_parity(live).tviews == normalise_for_parity(read_text(PINNED).model).tviews


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
        live = live_catalog.read(conn, schemas=["public"])

    (found,) = live.tviews.values()
    assert (found.logged, found.fillfactor) == (True, 70)
    assert normalise_for_parity(live).tviews == normalise_for_parity(read_text(CALLED).model).tviews
    assert _drift(url, CALLED) == []


LOGGED = f"{TREE}ALTER TABLE tv_post SET LOGGED;\n"


def test_set_logged_in_the_tree_is_what_the_database_holds(tview_database: str) -> None:
    """The tree ``tview_002`` asks for, built, reads back as itself; left unlogged, it drifts."""
    from confiture.core.schema_model import normalise_for_parity

    assert _drift(tview_database, LOGGED) == [("tview_option_mismatch", "warning", "tv_post")]

    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute("ALTER TABLE tv_post SET LOGGED")
        live = live_catalog.read(conn, schemas=["public"])

    assert normalise_for_parity(live).tviews == normalise_for_parity(read_text(LOGGED).model).tviews
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
            live = live_catalog.read(conn, schemas=["public"])

        assert (
            normalise_for_parity(live).tviews == normalise_for_parity(read_text(tree).model).tviews
        )
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
            lambda: live_catalog.read(conn, schemas=["public"]),
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
        assert live_catalog.read(conn, schemas=["public"]).tviews == {}


def test_every_reader_of_a_database_holds_a_tview_as_one_object(tview_database: str) -> None:
    """``introspect`` (the seam) and a bare live read fold a TVIEW as drift does.

    Read as parts, ``tv_post`` is a table and its backing view a view: a tool reading
    the seam, a snapshot, or ``squash``'s check would each see objects the tree
    never declared.
    """
    from confiture.platform import introspect

    # `tviews` read too: from 0.1.0-beta.25 the backing view is there (pg_tviews#181).
    schemas = ["public", "tviews"]
    for model in (
        introspect(tview_database, schemas=schemas),
        live_catalog.read(psycopg.connect(tview_database), schemas=schemas, views=True),
    ):
        assert list(model.tviews) == [ref_for("tview", "public", "tv_post")]
        assert ref_for("table", "public", "tv_post") not in model.tables
        assert dict(model.views) == {}


def test_squash_from_build_accepts_a_tree_with_a_tview(
    tmp_path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    """``squash --from-build`` compares the tree with a replay: a TVIEW is one object on both."""
    from confiture.core.squash import plan_squash

    with psycopg.connect(fresh_database_factory("confiture_tv_probe"), autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tviews'"
        ).fetchone():
            pytest.skip("pg_tviews is not installed on this server (the pg-tviews CI leg has it)")
        create_supported_pg_tviews(conn)
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "20260101000000_extension.up.sql").write_text("CREATE EXTENSION pg_tviews;\n")
    (migrations / "20260101000000_extension.down.sql").write_text("DROP EXTENSION pg_tviews;\n")
    (migrations / "20260102000000_tree.up.sql").write_text(TREE)
    (migrations / "20260102000000_tree.down.sql").write_text(
        "DROP TABLE tv_post; DROP TABLE tb_post; DROP TABLE tb_user;\n"
    )

    plan = plan_squash(migrations, "20260102000000", server_url=test_db_url, build_sql=TREE)

    assert plan.source == "build"


def _materialised_drift(
    url: str, ddl: str, scratch_url: str, tmp_path
) -> list[tuple[str, str, str]]:
    """``confiture drift`` with a scratch server: the tree built there, read back, compared."""
    from confiture.core.drift import SchemaDriftDetector

    schema = tmp_path / "schema.sql"
    schema.write_text(f"CREATE EXTENSION IF NOT EXISTS pg_tviews;\n{ddl}")
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn, scratch_url=scratch_url).compare_with_schema_file(
            str(schema)
        )
    assert report.fidelity == "materialised"
    return sorted((i.drift_type.value, i.severity.value, i.object_name) for i in report.drift_items)


def test_a_materialised_tree_pins_what_it_wrote_and_nothing_else(
    tview_database: str, test_db_url: str, tmp_path
) -> None:
    """The scratch registry holds every key; the tree pins none, so none is drift."""
    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute("ALTER TABLE tv_post SET LOGGED")

    assert _materialised_drift(tview_database, TREE, test_db_url, tmp_path) == []


def test_a_materialised_pinned_option_changed_by_hand_is_drift(
    pinned_database: str, test_db_url: str, tmp_path
) -> None:
    with psycopg.connect(pinned_database, autocommit=True) as conn:
        conn.execute("ALTER TABLE tv_post SET (fillfactor = 60)")

    # Read back from a database, the tree is spelled as PostgreSQL spells it: qualified.
    assert _materialised_drift(pinned_database, PINNED, test_db_url, tmp_path) == [
        ("tview_option_mismatch", "warning", "public.tv_post"),
    ]


def test_the_seam_accepts_a_supported_pg_tviews_by_url_or_connection(reads_database: str) -> None:
    from confiture import platform

    assert platform.require_supported_pg_tviews_on(reads_database) is None
    with psycopg.connect(reads_database) as conn:
        assert platform.require_supported_pg_tviews_on(conn) is None


def test_the_seam_accepts_a_database_without_pg_tviews(
    fresh_database_factory: Callable[[str], str],
) -> None:
    from confiture import platform

    assert platform.require_supported_pg_tviews_on(fresh_database_factory("confiture_tv")) is None
