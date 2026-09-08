"""A tree finding can be baselined, and one severity name means one thing.

Two loose ends of the fold. `--baseline` is the adoption path #249's reporter
needs for a tree with 36 prefix collisions, and it works on a finding's
*identity* — which for a tree rule is a path, because the object a tree rule
reports is a file. `tree_001:file:00001_create.sql` alone would collapse every
directory in the tree onto one entry.

And confiture carried two enums called `LintSeverity` — three severity types
between them, two sharing a name (LINT-11) — so which one an import meant
depended on where the import was written.
"""

from __future__ import annotations

import ast
import collections
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.baseline import identity
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity

runner = CliRunner()

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "python" / "confiture"

_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"

_COLLIDING = {
    "00001_create.sql": "CREATE TABLE tb_a (id INT PRIMARY KEY);\n",
    "00001_update.sql": "CREATE TABLE tb_b (id INT PRIMARY KEY);\n",
}


@pytest.fixture
def colliding_tree(tmp_path: Path) -> Iterator[Path]:
    """`db/schema/10_tables` collides on one prefix; cwd is the project root."""
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    tables = tmp_path / "db" / "schema" / "10_tables"
    tables.mkdir(parents=True)
    for name, sql in _COLLIDING.items():
        (tables / name).write_text(sql)
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _lint(*args: str):
    return runner.invoke(app, ["lint", "--select", "tree", *args])


class TestTreeFindingsBaseline:
    def test_a_written_baseline_makes_the_next_run_clean(self, colliding_tree: Path) -> None:
        written = _lint("--baseline", "lint.json", "--write-baseline")
        assert written.exit_code == 0, written.output

        again = _lint("--baseline", "lint.json")

        assert again.exit_code == 0, again.output

    def test_a_new_collision_is_not_absorbed_by_the_baseline(self, colliding_tree: Path) -> None:
        _lint("--baseline", "lint.json", "--write-baseline")
        views = colliding_tree / "db" / "schema" / "20_views"
        views.mkdir()
        for name, sql in _COLLIDING.items():
            (views / name).write_text(sql.replace("tb_", "tb_v_"))

        after = _lint("--baseline", "lint.json", "--format", "json")

        assert after.exit_code == 1
        reported = json.loads(after.stdout)["violations"]["items"]
        assert [i["file"] for i in reported] == ["db/schema/20_views/00001_update.sql"]

    def test_the_baseline_file_records_the_tree_finding_by_path(self, colliding_tree: Path) -> None:
        _lint("--baseline", "lint.json", "--write-baseline")

        recorded = json.loads((colliding_tree / "lint.json").read_text())["rules"]

        assert recorded["tree_001"] == [
            "tree_001:file:00001_update.sql@db/schema/10_tables/00001_update.sql"
        ]


class TestTreeFindingIdentity:
    def test_the_same_filename_in_two_directories_is_two_identities(self) -> None:
        """Without `@file` a tree baseline would silence every directory at once."""

        def violation(directory: str) -> LintViolation:
            return LintViolation(
                rule_id="tree_001",
                rule_name="Prefix Uniqueness",
                severity=RuleSeverity.ERROR,
                object_type="file",
                object_name="00001_create.sql",
                message="…",
                file_path=f"db/schema/{directory}/00001_create.sql",
            )

        assert identity(violation("10_tables")) != identity(violation("20_views"))

    def test_two_migrations_missing_the_same_owner_are_two_identities(self) -> None:
        """own_001 reads a tree of migrations, so its object name repeats across them."""

        def violation(migration: str) -> LintViolation:
            return LintViolation(
                rule_id="own_001",
                rule_name="Ownership Coverage",
                severity=RuleSeverity.ERROR,
                object_type="table",
                object_name="public.tb_t",
                message="…",
                file_path=f"db/migrations/{migration}.up.sql",
            )

        assert identity(violation("20260101120000")) != identity(violation("20260202120000"))


def test_one_severity_enum_per_name() -> None:
    """`LintSeverity` named a three-value enum and a four-value one (LINT-11).

    Which one an import meant depended on where the import was written, and the
    compliance catalogues' `CRITICAL` has no counterpart anywhere a lint report
    can carry it.
    """
    by_name: dict[str, list[str]] = collections.defaultdict(list)
    for module in sorted(PACKAGE_ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Severity"):
                by_name[node.name].append(module.relative_to(PACKAGE_ROOT).as_posix())

    shared = {name: files for name, files in by_name.items() if len(files) > 1}

    assert shared == {}, f"one severity name, one enum: {shared}"
