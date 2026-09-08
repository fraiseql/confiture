"""A directory an operator names is read relative to `--project-dir`.

`--baseline` has always been project-relative. `--migrations-dir` was not: it
reached `replica_001` as typed, so a lint run from outside the project read the
migrations of whatever happened to sit under the current directory — usually
nothing, which is a rule reporting "clean" about a tree it never opened. Three
rules read that flag now and `--overrides-dir` is a fourth directory of the same
shape, so there is one resolver.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_ENV = (
    "database_url: postgresql://localhost/test\n"
    "include_dirs:\n  - path: db/schema\n"
    "infrastructure:\n  replicas:\n    - read-1\n"
    "ownership:\n"
    "  expected_owner: app_owner\n"
    "  lint_enabled: true\n"
    "  apply_to:\n"
    "    - schema: public\n"
    "      relkinds: [r]\n"
)


@pytest.fixture
def project_next_door(tmp_path: Path) -> Iterator[Path]:
    """A project in `proj/`, with the cwd one directory above it."""
    project = tmp_path / "proj"
    (project / "db" / "schema").mkdir(parents=True)
    (project / "db" / "environments").mkdir(parents=True)
    (project / "db" / "environments" / "local.yaml").write_text(_ENV)
    (project / "db" / "schema" / "00001_create.sql").write_text(
        "CREATE TABLE tb_a (id INT PRIMARY KEY, c INT);\n"
    )
    (project / "db" / "migrations").mkdir(parents=True)
    (project / "db" / "migrations" / "20260908120000.up.sql").write_text(
        "ALTER TABLE public.tb_a DROP COLUMN c;\n"  # replica_001
        "CREATE TABLE public.tb_new (id int);\n"  # own_001: created, never owned
        "ALTER TABLE public.tb_old OWNER TO app_owner;\n"  # own_002: bare, uncreated
    )
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield project
    finally:
        os.chdir(old_cwd)


def _codes(project: Path, *select: str) -> set[str]:
    result = runner.invoke(
        app,
        [
            "lint",
            "--project-dir",
            str(project),
            "--select",
            *select,
            "--format",
            "json",
            "--fail-on",
            "never",
        ],
    )
    assert result.exit_code == 0, result.output
    return {i["rule_id"] for i in json.loads(result.stdout)["violations"]["items"]}


def test_replica_001_reads_the_project_s_migrations(project_next_door: Path) -> None:
    assert "replica_001" in _codes(project_next_door, "replica")


def test_the_ownership_rules_read_the_project_s_migrations(project_next_door: Path) -> None:
    assert _codes(project_next_door, "own") == {"own_001", "own_002"}


def test_an_absolute_migrations_dir_is_used_as_given(project_next_door: Path) -> None:
    result = runner.invoke(
        app,
        [
            "lint",
            "--project-dir",
            str(project_next_door),
            "--migrations-dir",
            str(project_next_door / "db" / "migrations"),
            "--select",
            "own_002",
            "--format",
            "json",
            "--fail-on",
            "never",
        ],
    )

    assert result.exit_code == 0, result.output
    codes = {i["rule_id"] for i in json.loads(result.stdout)["violations"]["items"]}
    assert codes == {"own_002"}
