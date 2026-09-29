"""The migration ``migrate diff --generate`` writes for a TVIEW, applied to pg_tviews (#504).

Each migration runs as a transactional ``.up.sql`` does — one script, one
transaction, a session of its own — on a server that preloads pg_tviews, as
pg_tviews requires and the ``pg-tviews`` CI leg does. Elsewhere the tests skip
with the reason.
"""

from __future__ import annotations

from collections.abc import Callable

import psycopg
import pytest

from confiture.core import live_catalog
from confiture.core.change_order import apply_order
from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.linting.inventory import build_model

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
        conn.execute("CREATE EXTENSION pg_tviews")
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
