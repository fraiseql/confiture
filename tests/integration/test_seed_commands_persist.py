"""The commands that apply seed files leave the rows in the database.

``SeedApplier.apply_sequential`` runs every file inside its caller's transaction,
a savepoint each, and leaves the commit to whoever owns the connection. The
library tests (``test_seed_apply_workflow.py``, ``test_seed_profile_apply.py``)
each commit for themselves; the three commands that call it — ``seed apply
--sequential``, ``build --sequential`` and ``migrate rebuild --seed`` — never did,
so each reported its files applied and closed a connection that rolled them back.
These tests read the rows back on a connection of their own, which is the only
reading that distinguishes the two.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

pytestmark = pytest.mark.integration

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path, fresh_database: str) -> Iterator[Path]:
    """A project with ``widgets`` in its schema and in its database, and two seed files."""
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "10_widgets.sql").write_text(
        "CREATE TABLE widgets (id INT PRIMARY KEY);\n"
    )
    seeds = tmp_path / "db" / "seeds"
    seeds.mkdir()
    (seeds / "01_first.sql").write_text("INSERT INTO widgets VALUES (1);\n")
    (seeds / "02_second.sql").write_text("INSERT INTO widgets VALUES (2);\n")
    (tmp_path / "db" / "environments").mkdir()
    (tmp_path / "db" / "environments" / "test.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "test",
                "database_url": fresh_database,
                "include_dirs": ["db/schema", "db/seeds"],
            }
        )
    )
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE TABLE widgets (id INT PRIMARY KEY)")
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _rows(url: str) -> list[int]:
    with psycopg.connect(url) as conn:
        return [row[0] for row in conn.execute("SELECT id FROM widgets ORDER BY id")]


def test_seed_apply_leaves_its_rows(project: Path, fresh_database: str) -> None:
    result = runner.invoke(app, ["seed", "apply", "--sequential", "--env", "test"])

    assert result.exit_code == 0, result.output
    assert _rows(fresh_database) == [1, 2]


def test_seed_apply_json_is_the_whole_of_stdout(project: Path, fresh_database: str) -> None:
    result = runner.invoke(
        app, ["seed", "apply", "--sequential", "--env", "test", "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["succeeded"] == 2


def test_a_failing_seed_file_leaves_no_row(project: Path, fresh_database: str) -> None:
    (project / "db" / "seeds" / "02_second.sql").write_text("INSERT INTO widgets VALUES (1);\n")

    result = runner.invoke(app, ["seed", "apply", "--sequential", "--env", "test"])

    assert result.exit_code != 0, result.output
    assert _rows(fresh_database) == []


def test_continue_on_error_keeps_the_files_that_applied(project: Path, fresh_database: str) -> None:
    (project / "db" / "seeds" / "02_second.sql").write_text("INSERT INTO widgets VALUES (1);\n")
    (project / "db" / "seeds" / "03_third.sql").write_text("INSERT INTO widgets VALUES (3);\n")

    result = runner.invoke(
        app, ["seed", "apply", "--sequential", "--continue-on-error", "--env", "test"]
    )

    assert _rows(fresh_database) == [1, 3], result.output


def test_build_sequential_leaves_its_rows(project: Path, fresh_database: str) -> None:
    result = runner.invoke(app, ["build", "--env", "test", "--sequential", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["success"] is True
    assert _rows(fresh_database) == [1, 2]
