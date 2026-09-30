"""``confiture restore`` of a database holding a pg_tviews TVIEW (#504).

The dump comes from a database whose extension was created by the pg_tviews the
server runs, and goes through the three-phase restore. The TVIEW must come back
registered, and a change to a base table must still reach it, a cascade through
a foreign key included: pg_tviews rebinds each recorded OID in a trigger as the
restore loads ``pg_tview_meta``. Runs on a server that preloads pg_tviews, as the
``pg-tviews`` CI leg does; elsewhere it skips with the reason.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest
from tests.conftest import create_supported_pg_tviews

from confiture.core import live_catalog
from confiture.core.restorer import DatabaseRestorer, RestoreOptions
from confiture.core.schema_artifact import SchemaArtifactDumper

pytestmark = pytest.mark.integration

SOURCE = (
    "CREATE TABLE tb_user (pk_user bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, name text)",
    """CREATE TABLE tb_post (
        pk_post bigint PRIMARY KEY, id uuid NOT NULL UNIQUE,
        fk_user bigint REFERENCES tb_user, title text
    )""",
    "INSERT INTO tb_user VALUES (1, gen_random_uuid(), 'ann')",
    "INSERT INTO tb_post VALUES (1, gen_random_uuid(), 1, 'hello')",
    """CREATE TABLE tv_post AS
    SELECT p.pk_post, p.id, p.fk_user,
           jsonb_build_object('title', p.title, 'author', u.name) AS data
    FROM tb_post p JOIN tb_user u ON u.pk_user = p.fk_user""",
)


@pytest.fixture
def tview_dump(fresh_database_factory: Callable[[str], str], tmp_path: Path) -> Path:
    url = fresh_database_factory("confiture_tvr_src")
    with psycopg.connect(url, autocommit=True) as conn:
        if "pg_tviews" not in conn.execute("SHOW shared_preload_libraries").fetchone()[0]:
            pytest.skip("pg_tviews is not preloaded on this server (the pg-tviews CI leg is)")
        create_supported_pg_tviews(conn)
        for statement in SOURCE:
            conn.execute(statement)
    dump = tmp_path / "tview.pgdump"
    SchemaArtifactDumper().dump(url, dump)
    return dump


@pytest.fixture
def restored(
    tview_dump: Path,
    fresh_database_factory: Callable[[str], str],
    restore_connection_kwargs: dict,
) -> str:
    url = fresh_database_factory("confiture_tvr_dst")
    result = DatabaseRestorer().restore(
        RestoreOptions(
            backup_path=tview_dump,
            target_db=urlparse(url).path.lstrip("/"),
            **restore_connection_kwargs,
            jobs=2,
            parallel_restore=True,
        )
    )
    assert result.success, result.errors
    return url


def _author(url: str, pk_post: int) -> str | None:
    with psycopg.connect(url) as conn:
        row = conn.execute("SELECT data->>'author' FROM tv_post WHERE pk_post = %s", (pk_post,))
        found = row.fetchone()
    return None if found is None else found[0]


def test_the_restored_tview_is_registered(restored: str) -> None:
    with psycopg.connect(restored) as conn:
        names = [t.name for t in live_catalog.tviews(conn, ["public"])]

    assert names == ["tv_post"]


def test_the_restored_tview_keeps_its_rows(restored: str) -> None:
    assert _author(restored, 1) == "ann"


def test_a_row_inserted_after_the_restore_reaches_the_tview(restored: str) -> None:
    with psycopg.connect(restored) as conn:
        conn.execute("INSERT INTO tb_post VALUES (2, gen_random_uuid(), 1, 'second')")

    assert _author(restored, 2) == "ann"


def test_a_change_to_a_joined_table_cascades_after_the_restore(restored: str) -> None:
    with psycopg.connect(restored) as conn:
        conn.execute("UPDATE tb_user SET name = 'bob' WHERE pk_user = 1")

    assert _author(restored, 1) == "bob"
