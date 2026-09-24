"""``tree_001`` is on by default, at ``error`` (#384).

Two files in one directory sharing a numeric prefix leave their order to the
names after the prefix, so which of them loads first is an accident of spelling.
The rule was an ``error`` nobody saw unless they asked for it, which read as an
oversight: it now runs in a default ``confiture lint`` and fails it under the
default ``--fail-on error``. ``--ignore tree_001`` is the way back.
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

_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"


@pytest.fixture
def colliding_tree(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    schema = tmp_path / "db" / "schema"
    schema.mkdir(parents=True)
    (schema / "10_a.sql").write_text("CREATE TABLE tb_a (id INT PRIMARY KEY);\n")
    (schema / "10_b.sql").write_text("CREATE TABLE tb_b (id INT PRIMARY KEY);\n")
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _tree_001(result) -> list[dict]:
    items = json.loads(result.stdout)["violations"]["items"]
    return [i for i in items if i["rule_id"] == "tree_001"]


def test_a_default_lint_reports_a_shared_prefix_as_an_error(colliding_tree: Path) -> None:
    result = runner.invoke(app, ["lint", "--format", "json"])
    (finding,) = _tree_001(result)
    assert finding["severity"] == "error"
    assert result.exit_code != 0


def test_ignoring_it_restores_the_previous_default(colliding_tree: Path) -> None:
    result = runner.invoke(app, ["lint", "--format", "json", "--ignore", "tree_001"])
    assert _tree_001(result) == []
    assert result.exit_code == 0, result.output
