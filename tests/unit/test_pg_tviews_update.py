"""Bringing a database's pg_tviews catalog to the loaded library (#809), decided without one.

What the database answers (``live_catalog.pg_tviews_releases``, the registry, the
views reading pg_tviews) is stubbed; what is run is recorded instead of executed.
``tests/integration/test_pg_tviews_update.py`` runs the same against pg_tviews.
"""

import json
from typing import Any, cast

import pglast
import psycopg
import pytest

from confiture.core import live_catalog, pg_tviews_update
from confiture.core.schema_model import RelationName
from confiture.core.schema_sources import parse_schema
from confiture.exceptions import ConfigurationError

TREE = """
CREATE TABLE tb_user (pk_user bigint PRIMARY KEY, id uuid, name text);
CREATE TABLE tb_post (pk_post bigint PRIMARY KEY, id uuid, fk_user bigint REFERENCES tb_user);
CREATE TABLE tv_user AS SELECT pk_user, id, jsonb_build_object('name', name) AS data FROM tb_user;
SELECT tviews.pg_tviews_create_or_replace('tv_post',
    $$SELECT p.pk_post, p.id, p.fk_user, jsonb_build_object('author', u.data) AS data
      FROM tb_post p JOIN tv_user u ON u.pk_user = p.fk_user$$,
    options => '{"fillfactor": 70}');
CREATE INDEX idx_tv_post_author ON tv_post ((data->'author'));
"""


#: No database is reached: every read is stubbed.
CONN = cast("psycopg.Connection", object())


def _releases(
    catalog: str = "0.1.0-beta.34",
    library: str | None = "0.1.0-beta.35",
    package: str | None = "0.1.0-beta.35",
    *,
    update_path: bool = True,
) -> live_catalog.PgTviewsReleases:
    return live_catalog.PgTviewsReleases(catalog, library, package, update_path)


@pytest.fixture
def ran(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What would run, each statement as text; nothing is executed."""
    statements: list[str] = []

    def record(_conn: Any, run: list[Any], _releases: Any) -> None:
        statements.extend(s if isinstance(s, str) else _text(s) for s in run)

    monkeypatch.setattr(pg_tviews_update, "_in_one_transaction", record)
    monkeypatch.setattr(pg_tviews_update, "_registered", lambda _conn: [])
    monkeypatch.setattr(live_catalog, "readers_of_pg_tviews", lambda _conn, _tables: [])
    return statements


def _text(template: Any) -> str:
    return "".join(part if isinstance(part, str) else str(part.value) for part in template)


def _answering(monkeypatch: pytest.MonkeyPatch, releases: Any) -> None:
    monkeypatch.setattr(live_catalog, "pg_tviews_releases", lambda _conn: releases)


def test_a_database_without_pg_tviews_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, ran: list[str]
) -> None:
    _answering(monkeypatch, None)

    assert pg_tviews_update.bring_up_to_date(object()) is None  # type: ignore[arg-type]
    assert ran == []


def test_a_catalog_at_the_library_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, ran: list[str]
) -> None:
    _answering(monkeypatch, _releases(catalog="0.1.0-beta.35", update_path=False))

    assert pg_tviews_update.bring_up_to_date(object()) is None  # type: ignore[arg-type]
    assert ran == []


def test_the_library_installed_but_not_loaded_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, ran: list[str]
) -> None:
    """The package is on disk, the server still runs the catalog's library: no window yet."""
    _answering(monkeypatch, _releases(library="0.1.0-beta.34", update_path=False))

    assert pg_tviews_update.bring_up_to_date(object()) is None  # type: ignore[arg-type]
    assert ran == []


def test_a_catalog_one_release_behind_is_updated_to_the_library(
    monkeypatch: pytest.MonkeyPatch, ran: list[str]
) -> None:
    _answering(monkeypatch, _releases())

    done = pg_tviews_update.bring_up_to_date(CONN)

    assert done == pg_tviews_update.CatalogUpdate("updated", "0.1.0-beta.34", "0.1.0-beta.35")
    assert ran == ["ALTER EXTENSION pg_tviews UPDATE TO 0.1.0-beta.35"]
    assert done.message == "pg_tviews 0.1.0-beta.34 updated to 0.1.0-beta.35"


def test_a_library_that_is_not_the_package_is_refused(
    monkeypatch: pytest.MonkeyPatch, ran: list[str]
) -> None:
    """A library matching neither the catalog nor the package: PostgreSQL needs a restart."""
    _answering(monkeypatch, _releases(package="0.1.0-beta.36"))

    with pytest.raises(ConfigurationError) as refused:
        pg_tviews_update.bring_up_to_date(CONN)

    assert refused.value.error_code == "CONFIG_016"
    assert "not restarted" in str(refused.value)
    assert ran == []


def test_a_catalog_with_no_update_is_refused_without_the_recreate(
    monkeypatch: pytest.MonkeyPatch, ran: list[str]
) -> None:
    _answering(monkeypatch, _releases(catalog="0.1.0-beta.30", update_path=False))

    with pytest.raises(ConfigurationError) as refused:
        pg_tviews_update.bring_up_to_date(CONN)

    assert refused.value.error_code == "CONFIG_016"
    assert "no update from 0.1.0-beta.30" in str(refused.value)
    assert "--recreate-pg-tviews" in (refused.value.resolution_hint or "")
    assert ran == []


def test_the_recreate_drops_pg_tviews_and_creates_every_tview_in_build_order(
    monkeypatch: pytest.MonkeyPatch, ran: list[str]
) -> None:
    _answering(monkeypatch, _releases(catalog="0.1.0-beta.30", update_path=False))
    monkeypatch.setattr(
        pg_tviews_update,
        "_registered",
        lambda _conn: [RelationName("public", "tv_post"), RelationName("public", "tv_user")],
    )

    done = pg_tviews_update.bring_up_to_date(
        CONN,
        recreate_from=parse_schema(TREE),
    )

    assert done is not None
    assert done.action == "recreated"
    assert done.tviews == ("tv_user", "tv_post")
    assert ran[:2] == ["DROP EXTENSION pg_tviews CASCADE", "DROP SCHEMA IF EXISTS tviews CASCADE"]
    assert sorted(ran[2:4]) == [
        "DROP TABLE IF EXISTS public.tv_post",
        "DROP TABLE IF EXISTS public.tv_user",
    ]
    assert ran[4] == "CREATE EXTENSION pg_tviews CASCADE"
    statements = [stmt.stmt for text in ran[5:] for stmt in pglast.parse_sql(text)]
    calls = {
        call.args[0].val.sval: call.args
        for stmt in statements
        if type(stmt).__name__ == "SelectStmt"
        for call in [stmt.targetList[0].val]
    }
    assert list(calls) == ["tv_user", "tv_post"]
    assert json.loads(calls["tv_post"][2].arg.val.sval) == {"fillfactor": 70}
    assert [s.idxname for s in statements if type(s).__name__ == "IndexStmt"] == [
        "idx_tv_post_author"
    ]


def test_the_recreate_refuses_a_tview_the_schema_files_do_not_declare(
    monkeypatch: pytest.MonkeyPatch, ran: list[str]
) -> None:
    _answering(monkeypatch, _releases(catalog="0.1.0-beta.30", update_path=False))
    monkeypatch.setattr(
        pg_tviews_update, "_registered", lambda _conn: [RelationName("app", "tv_order")]
    )

    with pytest.raises(ConfigurationError) as refused:
        pg_tviews_update.bring_up_to_date(CONN, recreate_from=parse_schema(TREE))

    assert refused.value.error_code == "CONFIG_016"
    assert "app.tv_order" in str(refused.value)
    assert ran == []


def test_the_recreate_refuses_to_drop_a_view_that_reads_a_tview(
    monkeypatch: pytest.MonkeyPatch, ran: list[str]
) -> None:
    _answering(monkeypatch, _releases(catalog="0.1.0-beta.30", update_path=False))
    monkeypatch.setattr(
        live_catalog,
        "readers_of_pg_tviews",
        lambda _conn, _tables: [RelationName("public", "v_post")],
    )

    with pytest.raises(ConfigurationError) as refused:
        pg_tviews_update.bring_up_to_date(CONN, recreate_from=parse_schema(TREE))

    assert refused.value.error_code == "CONFIG_016"
    assert "public.v_post" in str(refused.value)
    assert ran == []
