"""Integration: a build artifact round-trips through `confiture restore` (P1).

Builds a small schema into a pg_dump -Fc / -Fd artifact via an ephemeral
database, restores it into a fresh database with the three-phase restorer, and
asserts the restored object set matches what the schema declares.

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

_SCHEMA_SQL = """
CREATE TABLE parent (id int PRIMARY KEY);
CREATE TABLE child (
    id int PRIMARY KEY,
    parent_id int REFERENCES parent (id)
);
CREATE INDEX idx_child_parent ON child (parent_id);
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
    """Create an empty target database; drop it afterwards."""
    target = "confiture_artifact_roundtrip"
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


def _restored_tables(server_url: str, target_db: str) -> set[str]:
    target_url = server_url.rsplit("/", 1)[0] + f"/{target_db}"
    with psycopg.connect(target_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    return {r[0] for r in rows}


@pytest.mark.parametrize("dump_format", ["custom", "directory"])
def test_artifact_round_trips_through_restore(
    server_url: str, fresh_target: str, tmp_path: Path, dump_format: str
) -> None:
    ext = "pgdump" if dump_format == "custom" else "pgdir"
    artifact = tmp_path / f"schema_test.full.deadbeefcafe.{ext}"

    result = build_schema_artifact(
        server_url=server_url,
        schema_sql=_SCHEMA_SQL,
        output_path=artifact,
        schema_hash="deadbeefcafe0000",
        dump_format=dump_format,
        dumper=SchemaArtifactDumper(jobs=2),
    )
    assert result.skipped is False
    assert artifact.exists()

    host = "localhost"
    restore = DatabaseRestorer().restore(
        RestoreOptions(
            backup_path=artifact,
            target_db=fresh_target,
            host=host,
            port=5432,
            jobs=2,
            parallel_restore=True,
            no_owner=True,
            no_acl=True,
        )
    )
    assert restore.success, restore.errors

    assert _restored_tables(server_url, fresh_target) == {"parent", "child"}


_COPY_SCHEMA_SQL = """
CREATE TABLE country (code text PRIMARY KEY, name text);
COPY country (code, name) FROM stdin;
FR\tFrance
DE\tGermany
\\.
CREATE TABLE city (id int PRIMARY KEY, country_code text REFERENCES country (code), name text);
"""


def _row_count(server_url: str, target_db: str, table: str) -> int:
    target_url = server_url.rsplit("/", 1)[0] + f"/{target_db}"
    with psycopg.connect(target_url, autocommit=True) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_copy_bearing_schema_and_seed_round_trip(
    server_url: str, fresh_target: str, tmp_path: Path
) -> None:
    """#159 end-to-end: build --dump applies a COPY-bearing schema *and* a
    COPY-bearing seed file via psql, then the artifact restores with rows intact."""
    seed = tmp_path / "30_seed_backend" / "cities.sql"
    seed.parent.mkdir(parents=True)
    seed.write_text(
        "COPY city (id, country_code, name) FROM stdin;\n"
        "1\tFR\tParis\n"
        "2\tDE\tBerlin\n"
        "3\tFR\tLyon\n"
        "\\.\n"
    )

    artifact = tmp_path / "schema_test.full.copecafe0000.pgdump"
    result = build_schema_artifact(
        server_url=server_url,
        schema_sql=_COPY_SCHEMA_SQL,
        output_path=artifact,
        schema_hash="copecafe00000000",
        seed_files=[seed],
        dumper=SchemaArtifactDumper(jobs=2),
    )
    assert result.skipped is False
    assert result.seed_files_applied == 1
    assert artifact.exists()

    restore = DatabaseRestorer().restore(
        RestoreOptions(
            backup_path=artifact,
            target_db=fresh_target,
            host="localhost",
            port=5432,
            jobs=2,
            parallel_restore=True,
            no_owner=True,
            no_acl=True,
        )
    )
    assert restore.success, restore.errors

    assert _restored_tables(server_url, fresh_target) == {"country", "city"}
    # COPY data from both the schema file and the seed file survived the round-trip.
    assert _row_count(server_url, fresh_target, "country") == 2
    assert _row_count(server_url, fresh_target, "city") == 3


def test_skip_when_artifact_exists_is_a_noop(server_url: str, tmp_path: Path) -> None:
    artifact = tmp_path / "schema_test.full.deadbeefcafe.pgdump"
    artifact.write_bytes(b"PGDMP-stub")  # pretend a cached artifact is present

    result = build_schema_artifact(
        server_url=server_url,
        schema_sql=_SCHEMA_SQL,
        output_path=artifact,
        schema_hash="deadbeefcafe0000",
    )

    assert result.skipped is True
    assert artifact.read_bytes() == b"PGDMP-stub"  # untouched
