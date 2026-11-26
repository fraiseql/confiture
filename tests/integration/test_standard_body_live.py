"""A SQL-standard body against a real catalog: present by default, compared when materialised.

PostgreSQL keeps a ``RETURN expr`` / ``BEGIN ATOMIC`` body analysed in
``pg_proc.prosqlbody`` (``prosrc`` is empty) and prints it back through its own
deparser: ``public.unaccent('"public".unaccent'::regdictionary, $1)`` comes back
``unaccent('unaccent'::regdictionary, $1)``. So a tree and a database compare that
such a body exists (``analysed_expressions``), and a database built from its tree
is no change; with a scratch server the tree is read back through the same
deparser (``MATERIALISED``) and a body changed in the database is one change.

Requires a PostgreSQL server at ``CONFITURE_TEST_DB_URL`` with ``unaccent``.
"""

from dataclasses import replace
from pathlib import Path

import psycopg
import pytest

from confiture import platform
from confiture.core.differ import MATERIALISED, SchemaDiffer
from confiture.core.psql_applier import apply_sql_via_psql
from confiture.core.schema_read import read_text
from confiture.core.schema_sources import database_side, materialised_side

TREE = """
CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;
CREATE SCHEMA IF NOT EXISTS app;
CREATE FUNCTION app.fold(text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  RETURN public.unaccent('"public".unaccent'::regdictionary, $1);
CREATE FUNCTION app.label(t text) RETURNS text LANGUAGE sql IMMUTABLE RETURN lower(t);
CREATE FUNCTION app.next(a int) RETURNS int LANGUAGE sql BEGIN ATOMIC SELECT a + 1; END;
"""

PATCH = "CREATE OR REPLACE FUNCTION app.label(t text) RETURNS text LANGUAGE sql IMMUTABLE RETURN upper(t);"


@pytest.fixture
def built(fresh_database: str, tmp_path: Path) -> tuple[str, Path]:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'unaccent'"
        ).fetchone():
            pytest.skip("unaccent (contrib) is not installed on this server")
    apply_sql_via_psql(fresh_database, sql=TREE)
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(TREE, encoding="utf-8")
    return fresh_database, schema_file


def _routine_changes(changes: list) -> list[str]:
    return sorted(c.ref.display for c in changes if c.ref.kind in {"function", "procedure"})


def _materialised(url: str, schema_file: Path, scratch_url: str) -> list[str]:
    sql = schema_file.read_text(encoding="utf-8")
    read = read_text(sql)
    database = database_side(url, against=read.model)
    tree = materialised_side(sql, scratch_url, read=read)
    changes = SchemaDiffer().compare_sides(database, tree, replace(MATERIALISED, author="new"))
    return _routine_changes(changes.changes)


def test_a_database_built_from_its_tree_is_no_change(built: tuple[str, Path]) -> None:
    url, schema_file = built
    assert _routine_changes(platform.diff(url, schema_file).changes) == []


def test_without_a_scratch_server_a_standard_body_compares_as_present(
    built: tuple[str, Path],
) -> None:
    url, schema_file = built
    apply_sql_via_psql(url, sql=PATCH)
    assert _routine_changes(platform.diff(url, schema_file).changes) == []


def test_materialised_a_database_built_from_its_tree_is_no_change(
    built: tuple[str, Path], test_db_url: str
) -> None:
    assert _materialised(*built, test_db_url) == []


def test_materialised_a_body_changed_in_the_database_is_one_change(
    built: tuple[str, Path], test_db_url: str
) -> None:
    url, schema_file = built
    apply_sql_via_psql(url, sql=PATCH)
    changes = _materialised(url, schema_file, test_db_url)
    assert changes == ["app.label(text)"]


def test_the_database_reads_the_body_postgresql_deparses(built: tuple[str, Path]) -> None:
    url, _ = built
    with psycopg.connect(url) as conn:
        model = platform.introspect(conn, schemas=["app"])
    bodies = {r.name: (r.body, r.standard_body) for r in model.all_routines()}
    assert bodies["label"] == ("RETURN lower(t)", True)
    assert bodies["fold"][1] is True
    assert "unaccent" in (bodies["fold"][0] or "")
