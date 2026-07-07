"""Integration: `confiture restore` defers matview refresh past ANALYZE (issue #172).

Builds a schema containing a *populated* materialized view into a pg_dump -Fc
artifact, then restores it into a fresh database and asserts:

- default: the matview is refreshed (populated) after a database-wide ANALYZE, and
  the result reports the deferral + refresh;
- ``no_refresh_matviews``: the matview is restored WITH NO DATA (not populated),
  leaving it for the caller to refresh on their own schedule.

Requires a reachable local PostgreSQL (CONFITURE_TEST_DB_URL or localhost).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import psycopg.sql
import pytest

from confiture.core.restorer import DatabaseRestorer, RestoreOptions
from confiture.core.schema_artifact import SchemaArtifactDumper, build_schema_artifact

pytestmark = pytest.mark.integration

# A table with rows plus a materialized view over it. Created WITH DATA (the
# default), so pg_dump emits a MATERIALIZED VIEW DATA (REFRESH) entry.
_MATVIEW_SCHEMA_SQL = """
CREATE TABLE measurement (id int PRIMARY KEY, bucket int, amount numeric);
INSERT INTO measurement
    SELECT g, g % 5, (g * 1.5)::numeric FROM generate_series(1, 200) AS g;
CREATE MATERIALIZED VIEW mv_bucket_totals AS
    SELECT bucket, count(*) AS n, sum(amount) AS total
    FROM measurement
    GROUP BY bucket;
"""


def _server_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


def _maintenance_url(server_url: str) -> str:
    from confiture.core.temp_database import _maintenance_url

    return _maintenance_url(server_url)


@pytest.fixture
def server_url() -> str:
    url = _server_url()
    try:
        with psycopg.connect(_maintenance_url(url), autocommit=True):
            pass
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")
    return url


@pytest.fixture
def fresh_target(server_url: str) -> Iterator[str]:
    target = "confiture_matview_deferral"
    maint = _maintenance_url(server_url)
    target_id = psycopg.sql.Identifier(target)
    with psycopg.connect(maint, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(target_id))
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(target_id))
    try:
        yield target
    finally:
        with psycopg.connect(maint, autocommit=True) as conn:
            conn.execute(
                psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(target_id)
            )


def _matview_is_populated(server_url: str, target_db: str, matview: str) -> bool:
    target_url = server_url.rsplit("/", 1)[0] + f"/{target_db}"
    with psycopg.connect(target_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT ispopulated FROM pg_matviews WHERE matviewname = %s",
            (matview,),
        ).fetchone()
    assert row is not None, f"matview {matview!r} was not restored at all"
    return bool(row[0])


def _build_matview_artifact(server_url: str, tmp_path: Path) -> Path:
    artifact = tmp_path / "matview_schema.full.deadbeefcafe.pgdump"
    result = build_schema_artifact(
        server_url=server_url,
        schema_sql=_MATVIEW_SCHEMA_SQL,
        output_path=artifact,
        schema_hash="deadbeefcafe0001",
        dump_format="custom",
        dumper=SchemaArtifactDumper(jobs=2),
    )
    assert result.skipped is False
    assert artifact.exists()
    return artifact


def _restore_options(artifact: Path, target: str, **kwargs) -> RestoreOptions:
    return RestoreOptions(
        backup_path=artifact,
        target_db=target,
        host="localhost",
        port=5432,
        jobs=2,
        parallel_restore=True,
        no_owner=True,
        no_acl=True,
        **kwargs,
    )


def test_default_restore_refreshes_matview_after_analyze(
    server_url: str, fresh_target: str, tmp_path: Path
) -> None:
    artifact = _build_matview_artifact(server_url, tmp_path)

    result = DatabaseRestorer().restore(_restore_options(artifact, fresh_target))

    assert result.success, result.errors
    # The matview refresh was deferred out of the data phase and run after ANALYZE.
    assert result.matviews_deferred == 1
    assert result.matviews_refreshed == 1
    assert result.analyze_ran is True
    assert "analyze" in result.phases_completed
    assert "refresh-matviews" in result.phases_completed
    # And it is actually populated in the restored database.
    assert _matview_is_populated(server_url, fresh_target, "mv_bucket_totals") is True


def test_no_refresh_matviews_leaves_matview_unpopulated(
    server_url: str, fresh_target: str, tmp_path: Path
) -> None:
    artifact = _build_matview_artifact(server_url, tmp_path)

    result = DatabaseRestorer().restore(
        _restore_options(artifact, fresh_target, no_refresh_matviews=True)
    )

    assert result.success, result.errors
    assert result.matviews_deferred == 1
    assert result.matviews_refreshed == 0
    assert result.analyze_ran is False
    assert "refresh-matviews" not in result.phases_completed
    # The matview exists but was restored WITH NO DATA.
    assert _matview_is_populated(server_url, fresh_target, "mv_bucket_totals") is False
