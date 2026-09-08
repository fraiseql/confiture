"""The file-tree rules see the tree the build reads, and only that tree.

`GEN001` and `GEN003` walked the filesystem with `rglob` from a hardcoded
`db/schema`, so they reported files the environment keeps out of the build —
a directory in `exclude_dirs`, a file matched by a per-directory `exclude`
glob, a tree the project does not even build from (LINT-08). A finding about
the numbering of a file nothing reads is a finding with nothing behind it, and
`--schema-dir`'s help promised the resolution it did not do.

`confiture lint --select tree` and `confiture lint-unified --check tree` both
resolve the same way now, because both ask the same question of the same
builder.
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

_COLLIDING = {
    "00001_create.sql": "CREATE TABLE tb_a (id INT PRIMARY KEY);\n",
    "00001_update.sql": "CREATE TABLE tb_b (id INT PRIMARY KEY);\n",
}


def _project(root: Path, env_yaml: str, trees: dict[str, dict[str, str]]) -> None:
    (root / "db" / "environments").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments" / "local.yaml").write_text(env_yaml)
    for rel, files in trees.items():
        directory = root / rel
        directory.mkdir(parents=True, exist_ok=True)
        for name, sql in files.items():
            (directory / name).write_text(sql)


@pytest.fixture
def in_tmp(tmp_path: Path) -> Iterator[Path]:
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _tree_rules(*args: str) -> list[str]:
    """The rule ids `lint --select tree` reports on the project in the cwd."""
    result = runner.invoke(
        app, ["lint", "--select", "tree", "--format", "json", "--fail-on", "never", *args]
    )
    assert result.exit_code == 0, result.output
    return [i["rule_id"] for i in json.loads(result.stdout)["violations"]["items"]]


def _unified_tree_issues(*args: str) -> list[dict]:
    """The issues `lint-unified --check tree` reports on the project in the cwd.

    The exit code is the caller's business — a clean tree exits 0 and a tree with
    an error exits 1, and both are legitimate here. A run that crashed instead
    would not print a JSON payload, so the parse below is the check.
    """
    result = runner.invoke(app, ["lint-unified", "--check", "tree", "--format", "json", *args])
    return json.loads(result.stdout)["issues"]


def test_lint_is_silent_about_a_directory_the_build_excludes(in_tmp: Path) -> None:
    _project(
        in_tmp,
        "database_url: postgresql://localhost/test\n"
        "include_dirs:\n  - path: db/schema\n"
        "exclude_dirs:\n  - db/schema/legacy\n",
        {
            "db/schema/10_tables": {
                "00001_create.sql": "CREATE TABLE tb_a (id INT PRIMARY KEY);\n"
            },
            "db/schema/legacy": _COLLIDING,
        },
    )

    assert _tree_rules() == []


def test_lint_is_silent_about_a_file_an_exclude_glob_removes(in_tmp: Path) -> None:
    _project(
        in_tmp,
        "database_url: postgresql://localhost/test\n"
        "include_dirs:\n"
        "  - path: db/schema\n"
        "    exclude:\n"
        "      - 'legacy/*.sql'\n",
        {
            "db/schema/10_tables": {
                "00001_create.sql": "CREATE TABLE tb_a (id INT PRIMARY KEY);\n"
            },
            "db/schema/legacy": _COLLIDING,
        },
    )

    assert _tree_rules() == []


def test_lint_unified_is_silent_about_a_directory_the_build_excludes(in_tmp: Path) -> None:
    """The same tree, the same exclusion, the other command."""
    _project(
        in_tmp,
        "database_url: postgresql://localhost/test\n"
        "include_dirs:\n  - path: db/schema\n"
        "exclude_dirs:\n  - db/schema/legacy\n",
        {
            "db/schema/10_tables": {
                "00001_create.sql": "CREATE TABLE tb_a (id INT PRIMARY KEY);\n"
            },
            "db/schema/legacy": _COLLIDING,
        },
    )

    assert _unified_tree_issues() == []


def test_lint_unified_infers_the_tree_from_the_environment(in_tmp: Path) -> None:
    """`--schema-dir`'s help said "inferred from env config"; it read `db/schema`."""
    _project(
        in_tmp,
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/ddl\n",
        {"db/ddl": _COLLIDING},
    )

    issues = _unified_tree_issues()

    assert [i["rule"] for i in issues] == ["tree_001"]


def test_lint_unified_still_takes_an_explicit_schema_dir(in_tmp: Path) -> None:
    """An operator naming a tree gets that tree, whatever the environment builds."""
    _project(
        in_tmp,
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n",
        {
            "db/schema": {"00001_create.sql": "CREATE TABLE tb_a (id INT PRIMARY KEY);\n"},
            "elsewhere": _COLLIDING,
        },
    )

    issues = _unified_tree_issues("--schema-dir", "elsewhere")

    assert [i["rule"] for i in issues] == ["tree_001"]
