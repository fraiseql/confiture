"""A database is a side of ``migrate diff``, read through ``live_catalog``, never ``pg_dump``.

The invariant: a database built from a tree, diffed against that tree, has **no
change**. Reading the database as text ``pg_dump`` wrote and comparing it as if an
author had (#562) broke it on every shape PostgreSQL rewrites — an unnamed
constraint it names, the index backing a primary key, an analysed CHECK or
default, a ``serial`` — and generated ``DROP``s for objects the tree declares.
"""

import json
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from test_diff_goldens import goldens
from typer.testing import CliRunner

from confiture import platform
from confiture.cli.main import app

runner = CliRunner()

#: Every tree a database can be built from.
BUILDABLE = [tree for tree in goldens.TREES if tree.drift]


def _built(make_database: Callable[[str], str], sql: str) -> str:
    url = make_database("confiture_diff_db")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql)
    return url


def _diff_from_db(url: str, tree: Path, tmp_path: Path) -> dict:
    config = tmp_path / "local.yaml"
    config.write_text(f"name: test\ndatabase_url: {url}\n")
    result = runner.invoke(
        app,
        ["migrate", "diff", "--from", "db", "--to", str(tree), "--config", str(config),
         "--format", "json"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


@pytest.mark.parametrize("tree", BUILDABLE, ids=[tree.name for tree in BUILDABLE])
def test_a_database_built_from_a_tree_is_no_change_from_it(
    tree, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    built = goldens.build(tree, tmp_path / f"{tree.name}.sql")
    url = _built(fresh_database_factory, built.read_text())
    payload = _diff_from_db(url, built, tmp_path)
    assert payload["changes"] == [], payload["changes"]
    assert payload["has_changes"] is False


REWRITTEN = """
CREATE TABLE parent (id SERIAL PRIMARY KEY, code TEXT UNIQUE);
CREATE TABLE child (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pid INT REFERENCES parent,
    status TEXT DEFAULT 'new' CHECK (status IN ('new', 'done')),
    size VARCHAR(50),
    at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON child (pid) WHERE status = 'new';
CREATE INDEX child_lower ON child (lower(status));
CREATE FUNCTION f(a int8) RETURNS int4 LANGUAGE sql AS 'SELECT 1';
CREATE VIEW v_child AS SELECT id, pid FROM child WHERE status IN ('new');
CREATE FUNCTION touch() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
CREATE TRIGGER trg_touch BEFORE UPDATE ON child FOR EACH ROW EXECUTE FUNCTION touch();
CREATE TABLE event (
    id BIGINT NOT NULL,
    at DATE NOT NULL,
    pid INT REFERENCES parent,
    kind TEXT CHECK (kind <> ''),
    PRIMARY KEY (id, at),
    UNIQUE (kind, at)
) PARTITION BY RANGE (at);
CREATE TABLE event_2026 PARTITION OF event FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE INDEX ON event (pid);
"""


def test_every_shape_postgresql_rewrites_is_no_change(
    fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    tree = tmp_path / "schema.sql"
    tree.write_text(REWRITTEN)
    url = _built(fresh_database_factory, REWRITTEN)
    assert _diff_from_db(url, tree, tmp_path)["changes"] == []
    assert platform.diff(url, REWRITTEN).changes == []
    assert platform.diff(REWRITTEN, url).changes == []


def test_a_change_to_the_tree_is_the_one_change(
    fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    url = _built(fresh_database_factory, REWRITTEN)
    wanted = REWRITTEN.replace("size VARCHAR(50),", "size VARCHAR(50),\n    note TEXT,").replace(
        "AS 'SELECT 1'", "AS 'SELECT 2'"
    )
    changes = platform.diff(url, wanted).changes
    assert sorted(type(change).__name__ for change in changes) == ["ColumnAdded", "ObjectReplaced"]


def test_what_only_the_database_holds_is_dropped_by_the_statement_that_undoes_it(
    fresh_database_factory: Callable[[str], str],
) -> None:
    url = _built(
        fresh_database_factory,
        REWRITTEN + "CREATE FUNCTION g(t text) RETURNS text LANGUAGE sql AS 'SELECT t';",
    )
    (change,) = platform.diff(url, REWRITTEN).changes
    assert type(change).__name__ == "ObjectDropped"
    assert change.ref.name == "g"
    assert "CREATE OR REPLACE FUNCTION" in change.obj.create_sql.upper()


def test_confiture_s_own_tables_are_not_the_project_s(
    fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    tree = tmp_path / "schema.sql"
    tree.write_text(REWRITTEN)
    url = _built(
        fresh_database_factory,
        REWRITTEN + "CREATE TABLE tb_confiture (id INT); CREATE TABLE tb_confiture_steps (id INT);",
    )
    assert _diff_from_db(url, tree, tmp_path)["changes"] == []


def test_a_database_object_with_no_statement_is_a_warning_not_a_silence(
    fresh_database_factory: Callable[[str], str],
) -> None:
    url = _built(
        fresh_database_factory,
        "CREATE TABLE t (id INT); CREATE DOMAIN positive AS INT CHECK (VALUE > 0);",
    )
    diff = platform.diff(url, "CREATE TABLE t (id INT);")
    assert diff.changes == []
    assert [w.code for w in diff.warnings] == ["DIFFER_404"]
