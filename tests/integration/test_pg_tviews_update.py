"""``migrate up`` brings a database's pg_tviews catalog to the loaded library (#809).

The ``pg-tviews`` CI image (``ci/pg-tviews/Dockerfile``) loads 0.1.0-beta.35 and carries
0.1.0-beta.34's install script, so a database can hold the previous release's catalog
under the new library: the window between a package install and ``ALTER EXTENSION
pg_tviews UPDATE``, in which pg_tviews refuses its functions and every write to a
TVIEW's base tables (55000). It also carries that script as ``0.1.0-beta.33``, a
version the package has no update from. Elsewhere the tests skip with the reason.
"""

import textwrap
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core import live_catalog
from confiture.core.migrator import MigratorSession
from confiture.core.schema_sources import parse_schema
from confiture.exceptions import ConfigurationError

pytestmark = pytest.mark.integration

PREVIOUS, LIBRARY, NO_UPDATE = "0.1.0-beta.34", "0.1.0-beta.35", "0.1.0-beta.33"

BASE = """
CREATE TABLE tb_post (pk_post bigint PRIMARY KEY, id uuid NOT NULL DEFAULT gen_random_uuid(),
                      title text);
"""
TVIEW = """
SELECT tviews.pg_tviews_create_or_replace('tv_post',
    $$SELECT pk_post, id, jsonb_build_object('title', title) AS data FROM tb_post$$,
    options => '{"fillfactor": 70}');
CREATE INDEX idx_tv_post_title ON tv_post ((data->>'title'));
"""


def _catalog_at(url: str, version: str) -> None:
    """*url*'s database with pg_tviews' catalog at *version*, and two posts."""
    with psycopg.connect(url, autocommit=True) as conn:
        if "pg_tviews" not in conn.execute("SHOW shared_preload_libraries").fetchone()[0]:
            pytest.skip("pg_tviews is not preloaded on this server (the pg-tviews CI leg is)")
        offered = {
            row[0]
            for row in conn.execute(
                "SELECT version FROM pg_available_extension_versions WHERE name = 'pg_tviews'"
            ).fetchall()
        }
        if not {version, LIBRARY} <= offered:
            pytest.skip(f"this server offers pg_tviews {sorted(offered)}, not {version}")
        conn.execute(t"CREATE EXTENSION pg_tviews VERSION {version:l} CASCADE")
        conn.execute(BASE)
        conn.execute("INSERT INTO tb_post (pk_post, title) VALUES (1, 'a'), (2, 'b')")


@pytest.fixture
def make_database(fresh_database_factory: Callable[[str], str]) -> Callable[[str], str]:
    def make(version: str) -> str:
        url = fresh_database_factory("confiture_tvu")
        _catalog_at(url, version)
        return url

    return make


def _extversion(url: str) -> str:
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'pg_tviews'"
        ).fetchone()[0]


def _tview_rows(url: str) -> list[tuple[int, str]]:
    with psycopg.connect(url) as conn:
        registered = conn.execute("SELECT name FROM tviews.registry").fetchall()
        assert registered == [("tv_post",)]
        return conn.execute("SELECT pk_post, data->>'title' FROM tv_post ORDER BY 1").fetchall()


def _migrations(tmp_path: Path, sql: str = TVIEW) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "20260101000000_tview.up.sql").write_text(sql)
    (directory / "20260101000000_tview.down.sql").write_text("SELECT 1;\n")
    return directory


def test_the_window_is_read_as_a_catalog_behind_the_library(
    make_database: Callable[[str], str],
) -> None:
    url = make_database(PREVIOUS)

    with psycopg.connect(url) as conn:
        assert live_catalog.pg_tviews_releases(conn) == live_catalog.PgTviewsReleases(
            PREVIOUS, LIBRARY, LIBRARY, update_path=True
        )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            conn.execute(TVIEW)


def test_migrate_up_updates_the_catalog_before_it_applies(
    make_database: Callable[[str], str], tmp_path: Path
) -> None:
    """A TVIEW migration refused in the window applies once the update has run."""
    url = make_database(PREVIOUS)
    events: list[str] = []

    with MigratorSession(None, _migrations(tmp_path), database_url_override=url) as session:
        result = session.up(on_event=lambda e: events.append(f"{e.kind}: {e.message}"))

    assert result.success, result.errors
    assert f"pg_tviews_updated: pg_tviews {PREVIOUS} updated to {LIBRARY}" in events
    assert _extversion(url) == LIBRARY
    assert _tview_rows(url) == [(1, "a"), (2, "b")]


def test_a_catalog_at_the_library_is_left_alone(
    make_database: Callable[[str], str], tmp_path: Path
) -> None:
    url = make_database(LIBRARY)
    events: list[str] = []

    with MigratorSession(None, _migrations(tmp_path), database_url_override=url) as session:
        assert session.up(on_event=lambda e: events.append(e.kind)).success

    assert "pg_tviews_updated" not in events


def test_a_dry_run_updates_nothing_and_says_what_a_run_does_first(
    make_database: Callable[[str], str], tmp_path: Path
) -> None:
    """In the window pg_tviews refuses confiture's own ledger DDL: the dry run says why."""
    url = make_database(PREVIOUS)

    with MigratorSession(None, _migrations(tmp_path), database_url_override=url) as session:
        with pytest.raises(ConfigurationError) as refused:
            session.up(dry_run=True)

    assert refused.value.error_code == "CONFIG_016"
    assert "without --dry-run" in (refused.value.resolution_hint or "")
    assert _extversion(url) == PREVIOUS


def test_a_catalog_with_no_update_is_refused_and_nothing_changes(
    make_database: Callable[[str], str], tmp_path: Path
) -> None:
    url = make_database(NO_UPDATE)

    with MigratorSession(None, _migrations(tmp_path), database_url_override=url) as session:
        with pytest.raises(ConfigurationError) as refused:
            session.up()

    assert refused.value.error_code == "CONFIG_016"
    assert f"has no update from {NO_UPDATE}" in str(refused.value)
    assert "--recreate-pg-tviews" in (refused.value.resolution_hint or "")
    assert _extversion(url) == NO_UPDATE
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT to_regclass('tv_post')").fetchone() == (None,)


def test_the_recreate_creates_every_tview_from_the_schema_files(
    make_database: Callable[[str], str], tmp_path: Path
) -> None:
    """The extension is created again and the TVIEW refilled from its base table."""
    url = make_database(NO_UPDATE)
    with psycopg.connect(url, autocommit=True) as conn:
        # A former TVIEW's table, an ordinary relation once its extension is gone.
        conn.execute("CREATE TABLE tv_post (pk_post bigint PRIMARY KEY, id uuid, data jsonb)")
    migrations = tmp_path / "migrations"
    migrations.mkdir()

    with MigratorSession(None, migrations, database_url_override=url) as session:
        result = session.up(recreate_pg_tviews_from=parse_schema(BASE + TVIEW))

    assert result.success, result.errors
    assert _extversion(url) == LIBRARY
    assert _tview_rows(url) == [(1, "a"), (2, "b")]
    with psycopg.connect(url) as conn:
        assert conn.execute(
            "SELECT options->>'fillfactor' FROM tviews.registry WHERE name = 'tv_post'"
        ).fetchone() == ("70",)
        assert conn.execute("SELECT to_regclass('idx_tv_post_title')").fetchone() != (None,)


def test_the_recreate_never_drops_a_view_that_reads_a_tview(
    make_database: Callable[[str], str], tmp_path: Path
) -> None:
    url = make_database(NO_UPDATE)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE TABLE tv_post (pk_post bigint PRIMARY KEY, id uuid, data jsonb)")
        conn.execute("CREATE VIEW v_post AS SELECT data FROM tv_post")
    migrations = tmp_path / "migrations"
    migrations.mkdir()

    with MigratorSession(None, migrations, database_url_override=url) as session:
        with pytest.raises(ConfigurationError) as refused:
            session.up(recreate_pg_tviews_from=parse_schema(BASE + TVIEW))

    assert refused.value.error_code == "CONFIG_016"
    assert "public.v_post" in str(refused.value)
    assert _extversion(url) == NO_UPDATE
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT to_regclass('v_post')").fetchone() != (None,)


def test_the_cli_refuses_without_the_flag_and_recreates_with_it(
    make_database: Callable[[str], str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = make_database(NO_UPDATE)
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "posts.sql").write_text(BASE + TVIEW)
    (tmp_path / "db" / "migrations").mkdir()
    (tmp_path / "db" / "environments").mkdir()
    config = tmp_path / "db" / "environments" / "local.yaml"
    config.write_text(
        textwrap.dedent(
            f"""\
            name: local
            database_url: "{url}"
            include_dirs:
              - db/schema
            """
        )
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    args = ["migrate", "up", "--config", str(config), "--migrations-dir", "db/migrations"]

    refused = runner.invoke(app, args)
    assert refused.exit_code == 5, refused.output
    assert f"has no update from {NO_UPDATE}" in refused.output
    assert _extversion(url) == NO_UPDATE

    recreated = runner.invoke(app, [*args, "--recreate-pg-tviews"])
    assert recreated.exit_code == 0, recreated.output
    assert f"pg_tviews {NO_UPDATE} dropped and created again at {LIBRARY}" in recreated.output
    assert _tview_rows(url) == [(1, "a"), (2, "b")]
