"""What ``confiture.platform`` raises against a real database, and what a ``str`` means there.

A bare ``str`` where names are expected is one name, and a ``str`` where a path is
expected is that path. A seed file the run cannot read, or a transaction that
cannot commit, is a ``SeedError`` naming it, never the driver's or the codec's
exception.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from confiture import platform

DDL = """
CREATE SCHEMA app;
CREATE TABLE app.item (id INT PRIMARY KEY, label TEXT);
CREATE TABLE public.other (id INT);
"""


def _create(url: str, ddl: str = DDL) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(ddl)


def _labels(url: str) -> list[tuple]:
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT id, label FROM app.item ORDER BY id").fetchall()


def test_a_bare_schema_name_is_one_schema(fresh_database: str) -> None:
    _create(fresh_database)
    model = platform.introspect(fresh_database, schemas="app")
    assert [(ref.schema, ref.name) for ref in model.tables] == [("app", "item")]


def test_seeds_named_by_str_are_applied(fresh_database: str, tmp_path: Path) -> None:
    _create(fresh_database)
    (tmp_path / "01_a.sql").write_text("INSERT INTO app.item VALUES (1, 'one');\n")
    (tmp_path / "02_b.sql").write_text("INSERT INTO app.item VALUES (2, 'two');\n")
    assert platform.apply_seeds(fresh_database, str(tmp_path)).succeeded == 2
    result = platform.apply_seeds(
        fresh_database, [str(tmp_path / "02_b.sql")], continue_on_error=True
    )
    assert (result.total, result.failed) == (1, 1)
    assert _labels(fresh_database) == [(1, "one"), (2, "two")]


def test_a_seed_file_that_is_not_utf8_is_a_seed_error_naming_it(
    fresh_database: str, tmp_path: Path
) -> None:
    _create(fresh_database)
    (tmp_path / "01_ok.sql").write_text("INSERT INTO app.item VALUES (1, 'one');\n")
    (tmp_path / "02_latin1.sql").write_bytes(
        "INSERT INTO app.item VALUES (2, 'café');\n".encode("latin-1")
    )
    with pytest.raises(platform.SeedError, match=r"02_latin1\.sql") as caught:
        platform.apply_seeds(fresh_database, tmp_path)
    assert isinstance(caught.value.__cause__, UnicodeDecodeError)
    assert _labels(fresh_database) == []
    result = platform.apply_seeds(fresh_database, tmp_path, continue_on_error=True)
    assert (result.succeeded, result.failed_files) == (1, ["02_latin1.sql"])
    assert _labels(fresh_database) == [(1, "one")]


def test_a_run_whose_commit_fails_is_a_seed_error(fresh_database: str, tmp_path: Path) -> None:
    """A deferred foreign key is checked at commit, after every file ran clean."""
    _create(
        fresh_database,
        "CREATE TABLE parent (id INT PRIMARY KEY);\n"
        "CREATE TABLE child (id INT, parent_id INT REFERENCES parent "
        "DEFERRABLE INITIALLY DEFERRED);\n",
    )
    (tmp_path / "01_child.sql").write_text("INSERT INTO child VALUES (1, 42);\n")
    with pytest.raises(platform.SeedError, match="transaction") as caught:
        platform.apply_seeds(fresh_database, tmp_path)
    assert isinstance(caught.value.__cause__, psycopg.Error)
