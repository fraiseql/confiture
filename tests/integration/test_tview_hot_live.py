"""``tview_001`` against what PostgreSQL does to a TVIEW's updates (#795).

The rule reads the tree; this holds it to the server. From pg_tviews 0.1.0-beta.34
a TVIEW's table holds only its definition's columns, so an ``updated_at`` the
definition projects is the base row's, and an index over it leaves a refresh that
does not change it HOT. An index over ``data`` never does. pg_tviews is in no stock
PostgreSQL: these tests run where the extension is available, which the
``pg-tviews`` CI leg guarantees, and skip with the reason elsewhere.
"""

from collections.abc import Callable

import psycopg
import pytest
from tests.conftest import create_supported_pg_tviews

from confiture.core.linting.gate import Threshold
from confiture.core.linting.schema_linter import SchemaLinter
from confiture.core.linting.selection import linter_config

pytestmark = pytest.mark.integration

BASE = """
CREATE TABLE tb_note (pk_note bigint PRIMARY KEY, id uuid NOT NULL UNIQUE, body text,
                      updated_at timestamptz NOT NULL DEFAULT now());
INSERT INTO tb_note VALUES (1, gen_random_uuid(), 'first');
"""

PROJECTED = """
CREATE TABLE tv_note AS
SELECT n.pk_note, n.id, n.updated_at, jsonb_build_object('body', n.body) AS data FROM tb_note n;
"""

UNPROJECTED = """
CREATE TABLE tv_note AS
SELECT n.pk_note, n.id, jsonb_build_object('body', n.body) AS data FROM tb_note n;
"""

#: The first catalog revision whose TVIEW tables hold only the definition's columns.
_ONLY_THE_DEFINITION = 10


@pytest.fixture
def tview_url(fresh_database_factory: Callable[[str], str]) -> str:
    url = fresh_database_factory("confiture_tv_hot")
    with psycopg.connect(url, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_tviews'"
        ).fetchone():
            pytest.skip("pg_tviews is not installed on this server (the pg-tviews CI leg has it)")
        # Its own round trip: in one batch with the CREATE EXTENSION, pg_tviews'
        # hook is not loaded yet and the TVIEW becomes a plain table (measured).
        create_supported_pg_tviews(conn)
        (revision,) = conn.execute("SELECT tviews.pg_tviews_catalog_revision()").fetchone()
        if revision < _ONLY_THE_DEFINITION:
            pytest.skip(f"pg_tviews before 0.1.0-beta.34 (catalog revision {revision})")
    return url


def _tview_001(tree: str) -> list[str]:
    config = linter_config(frozenset({"tview_001"}), Threshold.NEVER)
    report = SchemaLinter(env="local", config=config).lint(tree)
    return [v.message for v in [*report.errors, *report.warnings, *report.info]]


def _updates(url: str, tree: str, index: str) -> tuple[int, int]:
    """``(updates, HOT updates)`` of ``tv_note`` after ten writes of its base row's body."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(tree)
        conn.execute(index)
        for n in range(10):
            conn.execute("UPDATE tb_note SET body = %s WHERE pk_note = 1", (f"edit {n}",))
        conn.execute("SELECT pg_stat_force_next_flush()")
        conn.execute("SELECT pg_stat_clear_snapshot()")
        row = conn.execute(
            "SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables WHERE relname = 'tv_note'"
        ).fetchone()
    assert row is not None
    return row[0], row[1]


def test_an_index_over_a_projected_updated_at_leaves_refreshes_hot(tview_url: str) -> None:
    index = "CREATE INDEX ix ON tv_note (updated_at);"

    updates, hot = _updates(tview_url, BASE + PROJECTED, index)

    assert (updates, hot) == (10, 10)
    assert _tview_001(BASE + PROJECTED + index) == []


def test_an_index_over_data_leaves_no_refresh_hot(tview_url: str) -> None:
    index = "CREATE INDEX ix ON tv_note ((data->>'body'));"

    updates, hot = _updates(tview_url, BASE + PROJECTED, index)

    assert (updates, hot) == (10, 0)
    (message,) = _tview_001(BASE + PROJECTED + index)
    assert "covers data," in message


def test_an_unprojected_updated_at_is_no_column_of_the_tview(tview_url: str) -> None:
    """pg_tviews 0.1.0-beta.33 and earlier added it; ``tview_001`` names that release."""
    with psycopg.connect(tview_url, autocommit=True) as conn:
        conn.execute(BASE + UNPROJECTED)
        columns = [
            name
            for (name,) in conn.execute(
                "SELECT attname::text FROM pg_attribute "
                "WHERE attrelid = 'tv_note'::regclass AND attnum > 0 AND NOT attisdropped "
                "ORDER BY attnum"
            )
        ]

    assert columns == ["pk_note", "id", "data"]
    (message,) = _tview_001(BASE + UNPROJECTED + "CREATE INDEX ix ON tv_note (updated_at);")
    assert "0.1.0-beta.34" in message
