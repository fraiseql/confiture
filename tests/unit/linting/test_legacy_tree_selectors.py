"""`GEN001`–`GEN004` still select the rules they used to name.

The file-tree rules emitted uppercase `GEN00x` codes from a second namespace
`confiture lint` could not reach. Folding them into the registry as
`tree_001`–`tree_004` is what gives them `--select`, `--ignore` and
`--baseline`, but it also renames an id a pipeline may have typed. The old
spelling stays an accepted *selector* for one minor — it costs one mapping —
while the emitted `rule_id` is the new code from day one, because a baseline
keyed on the old id would have to be rewritten either way.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.rule_registry import resolve_selection

runner = CliRunner()

_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"


@pytest.fixture
def colliding_tree(tmp_path: Path) -> Iterator[Path]:
    """A project whose schema directory has two files sharing one prefix."""
    schema = tmp_path / "db" / "schema"
    schema.mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    (schema / "00001_create.sql").write_text("CREATE TABLE tb_a (id INT PRIMARY KEY);\n")
    (schema / "00001_update.sql").write_text("CREATE TABLE tb_b (id INT PRIMARY KEY);\n")
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


@pytest.mark.parametrize(
    ("legacy", "code"),
    [
        ("GEN001", "tree_001"),
        ("GEN002", "tree_002"),
        ("GEN003", "tree_003"),
        ("GEN004", "tree_004"),
    ],
)
def test_the_old_code_selects_the_new_rule(legacy: str, code: str) -> None:
    assert resolve_selection([legacy], ()) == frozenset({code})


def test_the_old_code_is_accepted_by_ignore_too() -> None:
    """A pipeline that silenced a rule by its old id keeps silencing it."""
    family = resolve_selection(["tree"], ())

    assert resolve_selection(["tree"], ["GEN001"]) == family - {"tree_001"}


def test_a_legacy_selector_reports_under_the_new_code(colliding_tree: Path) -> None:
    """Selecting by the old id is accepted; the finding carries the new one."""
    result = runner.invoke(
        app,
        ["lint", "--select", "GEN001", "--format", "json", "--fail-on", "never"],
    )

    assert result.exit_code == 0, result.output
    emitted = {i["rule_id"] for i in json.loads(result.stdout)["violations"]["items"]}
    assert emitted == {"tree_001"}


def test_list_rules_says_the_old_codes_are_deprecated() -> None:
    """An operator reading the catalogue is told the alias exists and is going."""
    result = runner.invoke(app, ["lint", "--list-rules"])

    assert result.exit_code == 0, result.output
    plain = " ".join(result.stdout.split())
    assert "GEN001" in plain
    assert "deprecated" in plain.lower()
