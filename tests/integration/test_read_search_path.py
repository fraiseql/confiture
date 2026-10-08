"""The live reader reads under one ``search_path``, whatever the database sets (#639).

``pg_get_viewdef``, ``pg_get_functiondef``, ``format_type`` and the other deparsers
qualify a name only when the *reading session's* ``search_path`` would not find
it. A database (or a role in it) that sets its own path made the ``--from db``
side read ``inp`` and an unqualified view body, while the scratch side read
``s.inp``: the same stored object, two texts, a ``REPLACE`` of each. The reader
now reads under ``public`` — what a default session sees — and gives a caller's
connection back as it found it.
"""

import json
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.schema_sources import database_side

runner = CliRunner()

TREE = """
CREATE SCHEMA s;
CREATE TYPE s.inp AS (a int);
CREATE TABLE s.t (id int PRIMARY KEY, a int);
CREATE VIEW s.v AS SELECT t.id, t.a FROM s.t WHERE t.a > 0;
CREATE FUNCTION s.f(p s.inp) RETURNS int LANGUAGE sql AS $$ SELECT (p).a $$;
"""

#: How a database comes to read with ``s`` first.
SETTINGS = {
    "database": "ALTER DATABASE {db} SET search_path TO s, public",
    "role in database": "ALTER ROLE CURRENT_USER IN DATABASE {db} SET search_path TO s, public",
}


def _built(make_database: Callable[[str], str], setting: str) -> str:
    url = make_database("confiture_path")
    with psycopg.connect(url, autocommit=True) as conn:
        db = psycopg.sql.Identifier(conn.info.dbname).as_string(conn)
        conn.execute(setting.format(db=db))
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(TREE)
    return url


@pytest.mark.parametrize("where", sorted(SETTINGS))
def test_migrate_diff_from_db_reads_no_change(
    where: str,
    test_db_url: str,
    fresh_database_factory: Callable[[str], str],
    tmp_path: Path,
) -> None:
    url = _built(fresh_database_factory, SETTINGS[where])
    tree = tmp_path / "schema.sql"
    tree.write_text(TREE)
    config = tmp_path / "local.yaml"
    config.write_text(f"name: test\ndatabase_url: {url}\n")

    result = runner.invoke(
        app,
        ["migrate", "diff", "--from", "db", "--to", str(tree), "--config", str(config),
         "--format", "json", "--scratch-url", test_db_url],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["fidelity"] == "materialised"
    assert payload["changes"] == []


@pytest.mark.parametrize("autocommit", [True, False])
def test_a_caller_s_connection_keeps_its_path_and_its_transaction(
    autocommit: bool, fresh_database_factory: Callable[[str], str]
) -> None:
    url = _built(fresh_database_factory, SETTINGS["database"])
    with psycopg.connect(url, autocommit=autocommit) as conn:
        conn.execute("SET search_path TO s")
        status = conn.info.transaction_status

        side = database_side(conn)

        assert conn.execute("SHOW search_path").fetchone() == ("s",)
        assert conn.info.transaction_status == status
        assert side.model.views


def test_drift_with_a_default_schema_reads_both_sides_alike(
    test_db_url: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    """The scratch side is built with ``app`` first on its path; it is read under ``public``."""
    from confiture.core.drift import SchemaDriftDetector

    unqualified = (
        "CREATE TYPE inp AS (a int);\n"
        "CREATE TABLE t (id int PRIMARY KEY, a int CHECK (a > 0), r int REFERENCES t (id));\n"
        "CREATE VIEW v AS SELECT t.id FROM t WHERE t.a > 0;\n"
        "CREATE FUNCTION f(p inp) RETURNS int LANGUAGE sql AS $$ SELECT (p).a $$;\n"
    )
    url = _built(fresh_database_factory, "ALTER DATABASE {db} SET search_path TO app, public")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA app")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(unqualified)
    path = tmp_path / "schema.sql"
    path.write_text("CREATE SCHEMA app;\n" + unqualified)

    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn, scratch_url=test_db_url).compare_with_schema_file(
            str(path), default_schema="app"
        )

    assert report.drift_items == [], report.to_dict()
