"""The migration ``migrate diff --generate`` writes for a TVIEW, applied to pg_tviews (#504).

Each migration runs as a transactional ``.up.sql`` does — one script, one
transaction, a session of its own — on a server that preloads pg_tviews, as
pg_tviews requires and the ``pg-tviews`` CI leg does. Elsewhere the tests skip
with the reason.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from tests.conftest import create_supported_pg_tviews

from confiture.core import live_catalog
from confiture.core.change_order import apply_order
from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.linting.inventory import build_model
from confiture.core.schema_facts import collect_schema_facts
from confiture.core.tview_preflight import live_issues

pytestmark = pytest.mark.integration

BASE = """
CREATE TABLE tb_user (pk_user bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, name text);
CREATE TABLE tb_post (
    pk_post bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, fk_user bigint REFERENCES tb_user, title text
);
"""
OLD = """
CREATE TABLE tv_post AS
SELECT p.pk_post, p.id, jsonb_build_object('title', p.title) AS data
FROM tb_post p;
"""
NEW = """
CREATE TABLE tv_post AS
SELECT p.pk_post, p.id, jsonb_build_object('title', p.title, 'author', u.name) AS data
FROM tb_post p JOIN tb_user u ON u.pk_user = p.fk_user;
"""


@pytest.fixture
def tview_database(fresh_database_factory: Callable[[str], str]) -> str:
    url = fresh_database_factory("confiture_tvm")
    with psycopg.connect(url, autocommit=True) as conn:
        if "pg_tviews" not in conn.execute("SHOW shared_preload_libraries").fetchone()[0]:
            pytest.skip("pg_tviews is not preloaded on this server (the pg-tviews CI leg is)")
        create_supported_pg_tviews(conn)
        conn.execute(BASE)
        conn.execute("INSERT INTO tb_user VALUES (1, gen_random_uuid(), 'ann')")
        conn.execute("INSERT INTO tb_post VALUES (1, gen_random_uuid(), 1, 'hello')")
    return url


def _migration(old: str, new: str) -> tuple[str, str]:
    """The up and the down ``migrate diff --generate`` derives, each one script."""
    changes = apply_order(SchemaDiffer().compare(BASE + old, BASE + new).changes)
    generator = DifferSQLGenerator()
    up = "".join(generator.generate_up(change) for change in changes)
    down = "".join(generator.generate_down(change) for change in reversed(changes))
    return up, down


def _apply(url: str, script: str) -> None:
    """One script, one transaction, a new session: a transactional ``.up.sql``."""
    with psycopg.connect(url) as conn:
        conn.execute(script)


def _registered(url: str) -> dict[str, str | None]:
    with psycopg.connect(url) as conn:
        return {t.name: t.definition for t in live_catalog.tviews(conn, ["public"])}


def _declared(tree: str) -> dict[str, str | None]:
    return {t.name: t.definition for t in build_model(tree).tviews.values()}


def test_an_added_tview_is_registered_and_its_down_removes_it(tview_database: str) -> None:
    up, down = _migration("", OLD)

    _apply(tview_database, up)
    _apply(tview_database, up)
    assert _registered(tview_database) == _declared(OLD)

    _apply(tview_database, down)
    assert _registered(tview_database) == {}


def test_a_replaced_tview_is_rebuilt_even_when_applied_twice(tview_database: str) -> None:
    _apply(tview_database, OLD)
    up, down = _migration(OLD, NEW)

    _apply(tview_database, up)
    _apply(tview_database, up)
    assert _registered(tview_database) == _declared(NEW)
    with psycopg.connect(tview_database) as conn:
        (data,) = conn.execute("SELECT data FROM tv_post").fetchone()
    assert data == {"title": "hello", "author": "ann"}

    _apply(tview_database, down)
    assert _registered(tview_database) == _declared(OLD)


def test_the_rebuilt_tview_follows_its_base_tables(tview_database: str) -> None:
    """pg_tviews' triggers are on the base tables again after the rebuild."""
    _apply(tview_database, OLD)
    _apply(tview_database, _migration(OLD, NEW)[0])

    with psycopg.connect(tview_database) as conn:
        conn.execute("UPDATE tb_user SET name = 'bea'")
        (data,) = conn.execute("SELECT data FROM tv_post").fetchone()
    assert data["author"] == "bea"


def test_a_dropped_tview_is_unregistered_and_its_down_restores_it(tview_database: str) -> None:
    _apply(tview_database, OLD)
    up, down = _migration(OLD, "")

    _apply(tview_database, up)
    _apply(tview_database, up)
    assert _registered(tview_database) == {}

    _apply(tview_database, down)
    assert _registered(tview_database) == _declared(OLD)


def test_a_replaced_tview_keeps_its_grants_and_indexes(tview_database: str) -> None:
    """``pg_tviews_create_or_replace`` replaces in place: nothing the table carries is lost."""
    _apply(tview_database, OLD)
    with psycopg.connect(tview_database, autocommit=True) as conn:
        conn.execute("CREATE ROLE confiture_tv_reader")
        conn.execute("GRANT SELECT ON tv_post TO confiture_tv_reader")
        conn.execute("CREATE INDEX tv_post_data_title ON tv_post ((data->>'title'))")
    try:
        _apply(tview_database, _migration(OLD, NEW)[0])
        with psycopg.connect(tview_database) as conn:
            granted = conn.execute(
                "SELECT has_table_privilege('confiture_tv_reader', 'tv_post', 'SELECT')"
            ).fetchone()
            index = conn.execute("SELECT to_regclass('tv_post_data_title')").fetchone()
        assert granted == (True,)
        assert index is not None and index[0] is not None
    finally:
        with psycopg.connect(tview_database, autocommit=True) as conn:
            conn.execute("DROP OWNED BY confiture_tv_reader")
            conn.execute("DROP ROLE confiture_tv_reader")


def test_the_storage_the_tree_pins_reaches_the_registry(tview_database: str) -> None:
    unlogged = OLD.replace(
        "CREATE TABLE tv_post", "CREATE UNLOGGED TABLE tv_post WITH (fillfactor = 70)"
    )
    _apply(tview_database, _migration("", unlogged)[0])

    with psycopg.connect(tview_database) as conn:
        options = conn.execute("SELECT options FROM tviews.registry").fetchone()
    assert options is not None
    assert (options[0]["logged"], options[0]["fillfactor"]) == (False, 70)


def test_preflight_names_a_change_to_a_column_the_registered_tview_reads(
    tview_database: str, tmp_path: Path
) -> None:
    """PostgreSQL refuses the DROP COLUMN; preflight says so before it is tried."""
    _apply(tview_database, OLD)
    migration = tmp_path / "20260929000009_drop_title.up.sql"
    migration.write_text("ALTER TABLE tb_post DROP COLUMN title;")
    with psycopg.connect(tview_database) as conn:
        facts = collect_schema_facts(conn)

    (issue,) = live_issues([migration], facts.tviews)
    assert issue.code == "PFLIGHT_TVIEW_BASE_COLUMN"
    with (
        psycopg.connect(tview_database) as conn,
        pytest.raises(psycopg.errors.DependentObjectsStillExist),
    ):
        conn.execute(migration.read_text())


def _write(directory: Path, stem: str, up: str) -> None:
    (directory / f"{stem}.up.sql").write_text(up)
    (directory / f"{stem}.down.sql").write_text("SELECT 1;\n")


def test_migrate_up_refuses_a_tview_migration_on_an_unsupported_pg_tviews(
    tview_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pg_tviews whose contract confiture does not read is refused before anything applies."""
    from confiture.core.migrator import MigratorSession
    from confiture.exceptions import ConfigurationError

    monkeypatch.setattr(live_catalog, "CONTRACT_VERSION", 99)
    _write(tmp_path, "20260101000000_tview", OLD)

    with MigratorSession(None, tmp_path, database_url_override=tview_database) as session:
        with pytest.raises(ConfigurationError) as refused:
            session.up()

    assert refused.value.error_code == "CONFIG_014"
    with psycopg.connect(tview_database) as conn:
        assert conn.execute("SELECT to_regclass('tv_post')").fetchone() == (None,)


def test_migrate_up_applies_a_migration_that_touches_no_tview_there(
    tview_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from confiture.core.migrator import MigratorSession

    monkeypatch.setattr(live_catalog, "CONTRACT_VERSION", 99)
    _write(tmp_path, "20260101000000_column", "ALTER TABLE tb_post ADD COLUMN body text;\n")

    with MigratorSession(None, tmp_path, database_url_override=tview_database) as session:
        result = session.up()

    assert [m.version for m in result.migrations_applied] == ["20260101000000"]
