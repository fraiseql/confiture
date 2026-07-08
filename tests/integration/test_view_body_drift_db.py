"""DB-backed tests for view body-drift with scratch normalisation (#174).

The crux: a view whose *source* DDL differs from the *live* form only in
formatting / schema-qualification / ``*``-expansion must NOT be reported as
drift. Both sides are read back through the identical ``pg_get_viewdef(oid,
true)`` deparser (the source side via a scratch DB built by
:class:`ExpectedSchemaDB`), so string equality means semantic equality.

Both the "live" and the "expected" schemas are materialised into throwaway
databases here, so the test is fully self-contained.

Requires a PostgreSQL server at ``CONFITURE_TEST_DB_URL``.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from confiture.core.expected_db import ExpectedSchemaDB
from confiture.core.live_view_catalog import LiveViewCatalog
from confiture.core.view_body_drift import ViewBodyDriftDetector


@pytest.fixture
def server_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


@pytest.fixture
def _require_server(server_url: str) -> None:
    try:
        psycopg.connect(server_url.replace("/confiture_test", "/postgres"), autocommit=True).close()
    except psycopg.OperationalError as exc:  # pragma: no cover - env dependent
        pytest.skip(f"PostgreSQL not available: {exc}")


_BASE = "CREATE TABLE things (id bigint, name text, active boolean);\n"


def _compare(server_url: str, live_ddl: str, source_ddl: str):
    with (
        ExpectedSchemaDB(server_url).from_source(schema_sql=live_ddl) as live_conn,
        ExpectedSchemaDB(server_url).from_source(schema_sql=source_ddl) as scratch_conn,
    ):
        live_defs = LiveViewCatalog(live_conn).get_view_definitions(["public"])
        src_defs = LiveViewCatalog(scratch_conn).get_view_definitions(["public"])
        return ViewBodyDriftDetector().compare(src_defs, live_defs)


@pytest.mark.integration
def test_predicate_change_is_drift(server_url: str, _require_server: None) -> None:
    live = _BASE + "CREATE VIEW v AS SELECT id FROM things WHERE id > (5 + 1);\n"
    source = _BASE + "CREATE VIEW v AS SELECT id FROM things WHERE id > 5;\n"

    report = _compare(server_url, live, source)

    assert report.has_drift
    assert len(report.body_drifts) == 1
    drift = report.body_drifts[0]
    assert drift.schema == "public"
    assert drift.name == "v"
    assert drift.relkind == "v"
    # The deparsed diff pinpoints the predicate change.
    assert "5" in drift.unified_diff


@pytest.mark.integration
def test_semantically_identical_no_false_positive(server_url: str, _require_server: None) -> None:
    """Formatting / schema-qualification differences must NOT be drift.

    This is the whole reason for scratch-normalisation — a naive text compare of
    source DDL vs live pg_get_viewdef would flag these as false positives.
    """
    live = _BASE + "CREATE VIEW v AS SELECT id, name FROM public.things WHERE active;\n"
    source = (
        _BASE
        + "CREATE VIEW v AS\n"
        + "    SELECT\n"
        + "        id,\n"
        + "        name\n"
        + "    FROM things\n"
        + "    WHERE active;\n"
    )

    report = _compare(server_url, live, source)

    assert not report.has_drift, (
        "semantically-identical views must not drift; "
        f"drifts={[d.unified_diff for d in report.body_drifts]}"
    )
    assert report.views_checked == 1


@pytest.mark.integration
def test_star_expansion_no_false_positive(server_url: str, _require_server: None) -> None:
    """`SELECT *` in source vs explicit columns in live must not drift."""
    live = _BASE + "CREATE VIEW v AS SELECT id, name, active FROM things;\n"
    source = _BASE + "CREATE VIEW v AS SELECT * FROM things;\n"

    report = _compare(server_url, live, source)

    assert not report.has_drift, (
        f"star-expansion should normalise away; drifts={[d.unified_diff for d in report.body_drifts]}"
    )


@pytest.mark.integration
def test_materialized_view_covered(server_url: str, _require_server: None) -> None:
    live = _BASE + "CREATE MATERIALIZED VIEW mv AS SELECT count(id) AS n FROM things;\n"
    source = _BASE + "CREATE MATERIALIZED VIEW mv AS SELECT count(*) AS n FROM things;\n"

    report = _compare(server_url, live, source)

    assert report.has_drift
    assert report.body_drifts[0].relkind == "m"
    assert report.body_drifts[0].name == "mv"


@pytest.mark.integration
def test_schemas_filter_is_honored(server_url: str, _require_server: None) -> None:
    """Only views in the requested schemas are enumerated."""
    ddl = (
        "CREATE SCHEMA other;\n"
        + _BASE
        + "CREATE VIEW v AS SELECT id FROM things;\n"
        + "CREATE TABLE other.t (id bigint);\n"
        + "CREATE VIEW other.ov AS SELECT id FROM other.t;\n"
    )
    with ExpectedSchemaDB(server_url).from_source(schema_sql=ddl) as conn:
        public_only = LiveViewCatalog(conn).get_view_definitions(["public"])
        both = LiveViewCatalog(conn).get_view_definitions(["public", "other"])

    assert set(public_only) == {"public.v"}
    assert {"public.v", "other.ov"} <= set(both)
