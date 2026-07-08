"""Integration tests for ``ExpectedSchemaDB`` (Phase 4 foundation).

Builds an "expected" schema into a throwaway database and reads it back through
a live connection — the reusable primitive that Phases 5–7 use to normalise the
expected side through Postgres' own deparser (``pg_get_viewdef``, ``prosrc``)
instead of text-normalising source DDL.

Requires a PostgreSQL server at ``CONFITURE_TEST_DB_URL``
(default ``postgresql://localhost/confiture_test``).
"""

from __future__ import annotations

import os

import psycopg
import pytest

from confiture.core.expected_db import ExpectedSchemaDB


@pytest.fixture
def server_url() -> str:
    return os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")


@pytest.fixture
def _require_server(server_url: str) -> None:
    """Skip the whole module cleanly when no server is reachable."""
    try:
        psycopg.connect(server_url.replace("/confiture_test", "/postgres"), autocommit=True).close()
    except psycopg.OperationalError as exc:  # pragma: no cover - env dependent
        pytest.skip(f"PostgreSQL not available: {exc}")


_TWO_TABLES_ONE_VIEW = """
CREATE TABLE authors (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE books (
    id BIGSERIAL PRIMARY KEY,
    author_id BIGINT NOT NULL REFERENCES authors(id),
    title TEXT NOT NULL
);

CREATE VIEW author_book_counts AS
    SELECT a.id, a.name, count(b.id) AS book_count
    FROM authors a
    LEFT JOIN books b ON b.author_id = a.id
    GROUP BY a.id, a.name;
"""


def _scratch_db_names(server_url: str) -> set[str]:
    maint = server_url.replace("/confiture_test", "/postgres")
    with psycopg.connect(maint, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE 'confiture_tmp_%'"
        ).fetchall()
    return {r[0] for r in rows}


@pytest.mark.integration
def test_from_source_yields_connection_with_expected_objects(
    server_url: str, _require_server: None
) -> None:
    before = _scratch_db_names(server_url)

    with ExpectedSchemaDB(server_url).from_source(schema_sql=_TWO_TABLES_ONE_VIEW) as conn:
        # The scratch connection sees the built objects.
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
        assert {"authors", "books"} <= tables

        views = {
            r[0]
            for r in conn.execute(
                "SELECT viewname FROM pg_views WHERE schemaname = 'public'"
            ).fetchall()
        }
        assert "author_book_counts" in views

        # And pg's own deparser is available for the readback the later phases need.
        viewdef = conn.execute(
            "SELECT pg_get_viewdef('public.author_book_counts'::regclass, true)"
        ).fetchone()[0]
        assert "book_count" in viewdef

        # Capture the scratch DB name so we can assert it is gone afterwards.
        scratch_name = conn.execute("SELECT current_database()").fetchone()[0]

    # The scratch DB is dropped on exit — no orphan left behind.
    assert scratch_name.startswith("confiture_tmp_")
    after = _scratch_db_names(server_url)
    assert scratch_name not in after
    assert after <= before  # created no net-new scratch DBs


_BASE_SQL = """
CREATE TABLE widgets (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL
);
"""


@pytest.mark.integration
def test_from_base_plus_migrations_applies_all_migrations(
    server_url: str, _require_server: None, tmp_path
) -> None:
    # Two migrations on top of the base: add a column, then a function.
    (tmp_path / "20260708000001_add_price.up.sql").write_text(
        "ALTER TABLE widgets ADD COLUMN price NUMERIC(10,2) NOT NULL DEFAULT 0;\n"
    )
    (tmp_path / "20260708000001_add_price.down.sql").write_text(
        "ALTER TABLE widgets DROP COLUMN price;\n"
    )
    (tmp_path / "20260708000002_add_fn.up.sql").write_text(
        "CREATE FUNCTION public.widget_total() RETURNS numeric\n"
        "LANGUAGE sql AS $$ SELECT coalesce(sum(price), 0) FROM widgets $$;\n"
    )
    (tmp_path / "20260708000002_add_fn.down.sql").write_text(
        "DROP FUNCTION public.widget_total();\n"
    )

    with ExpectedSchemaDB(server_url, migrations_dir=tmp_path).from_base_plus_migrations(
        base_sql=_BASE_SQL
    ) as conn:
        # Column added by migration 1 is present.
        columns = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'widgets'"
            ).fetchall()
        }
        assert {"id", "name", "price"} <= columns

        # Function added by migration 2 is present and callable.
        total = conn.execute("SELECT public.widget_total()").fetchone()[0]
        assert total == 0

        # The replay recorded both migrations in the tracking table.
        applied = conn.execute("SELECT count(*) FROM tb_confiture").fetchone()[0]
        assert applied == 2


@pytest.mark.integration
def test_from_base_plus_migrations_without_base_starts_empty(
    server_url: str, _require_server: None, tmp_path
) -> None:
    """With base_sql=None the migrations build the whole schema from empty."""
    (tmp_path / "20260708000010_create_all.up.sql").write_text(
        "CREATE TABLE solo (id BIGSERIAL PRIMARY KEY, label TEXT);\n"
    )
    (tmp_path / "20260708000010_create_all.down.sql").write_text("DROP TABLE solo;\n")

    with ExpectedSchemaDB(server_url, migrations_dir=tmp_path).from_base_plus_migrations() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
        assert "solo" in tables
