"""A lint finding names the file that wrote what it is about, and the line in that file.

The schema is read file by file, so a column an ``ALTER TABLE … ADD COLUMN`` in a
later file adds is found where it was written — not at its table's file, and not at
a line of the files joined together, which is a line of nothing the author edits.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

_TABLES = """CREATE SCHEMA app;

CREATE TABLE app.tb_widget (
    id uuid PRIMARY KEY,
    label text
);
"""

_LATER = """-- Added after the first release.
ALTER TABLE app.tb_widget ADD COLUMN "BadName" text;
"""

_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - db/schema\n"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "010_tables.sql").write_text(_TABLES)
    (tmp_path / "db" / "schema" / "020_later.sql").write_text(_LATER)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def test_a_column_added_in_a_later_file_is_found_where_it_is_written(project: Path) -> None:
    result = CliRunner().invoke(
        app, ["lint", "--env", "local", "--format", "json", "--fail-on", "never"]
    )
    items = json.loads(result.stdout)["violations"]["items"]
    (found,) = [i for i in items if i["rule_id"] == "naming_004"]

    assert (found["file"], found["line"]) == ("db/schema/020_later.sql", 2)
