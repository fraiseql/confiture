"""The four tree shapes #249 found by hand, reported by `confiture lint` (#249).

The arrangement of the DDL tree decides which definition of an object wins and
which objects exist when a later file references them, and until 1.4.0 nothing
checked it: the reporter's audit of one large tree found 36 colliding prefixes,
9 entries whose prefix did not extend their parent's, 2 unnumbered entries and
7 filenames carrying a status word — every one of them by hand, because
`lint-unified --check tree` said "No issues found".

`tree_001` compares *files* within one directory, so a pair of colliding
*directories* was invisible to it; `tree_002` only looks at files that already
carry a prefix; `tree_003` needs two prefixed files in one directory.
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

#: The issue's own tree, at the depth it names
#: (``db/0_schema/03_functions/034_dim/0248_configurator/…``).
_ISSUE_TREE = {
    "03_functions/034_dim/0248_configurator/00001_create.sql": "CREATE TABLE tb_cfg (id INT);\n",
    "03_functions/034_dim/0248_flag/00001_create.sql": "CREATE TABLE tb_flag (id INT);\n",
    "03_functions/034_dim/0341_geo/03452_odd/00001_create.sql": "CREATE TABLE tb_geo (id INT);\n",
    "03_functions/034_dim/unnumbered_thing.sql": "CREATE TABLE tb_thing (id INT);\n",
    "03_functions/034_dim/00002_update_TODO.sql": "CREATE TABLE tb_upd (id INT);\n",
}


def _project(root: Path, schema: dict[str, str], env_extra: str = "") -> Path:
    (root / "db" / "environments").mkdir(parents=True, exist_ok=True)
    (root / "db" / "environments" / "local.yaml").write_text(_ENV + env_extra)
    for name, sql in schema.items():
        path = root / "db" / "schema" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sql)
    return root


@pytest.fixture
def in_tmp(tmp_path: Path) -> Iterator[Path]:
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _findings(*args: str) -> list[dict]:
    result = runner.invoke(
        app, ["lint", "--select", "tree", "--format", "json", "--fail-on", "never", *args]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["violations"]["items"]


def _codes(items: list[dict], code: str) -> list[dict]:
    return [i for i in items if i["rule_id"] == code]


def test_sibling_directories_sharing_a_prefix(in_tmp: Path) -> None:
    """0248_configurator/ beside 0248_flag/ — the issue's first shape, 36 times."""
    _project(in_tmp, _ISSUE_TREE)

    found = _codes(_findings(), "tree_005")

    assert len(found) == 1, [i["message"] for i in found]
    message = found[0]["message"]
    assert "0248_configurator" in message
    assert "0248_flag" in message
    # confiture is the only component that computes the build order, which is
    # the issue's argument for the rule living here rather than in each project.
    assert "0248_configurator" in message.split("reads")[-1]
    assert found[0]["file"] == "db/schema/03_functions/034_dim/0248_flag"


def test_an_entry_whose_prefix_does_not_extend_its_parent(in_tmp: Path) -> None:
    """0341_geo/03452_odd — a prefix of the wrong shape sorts its whole subtree elsewhere."""
    _project(in_tmp, _ISSUE_TREE)

    found = _codes(_findings(), "tree_006")

    odd = [i for i in found if i["file"].endswith("03452_odd")]
    assert len(odd) == 1, [i["file"] for i in found]
    assert "0341" in odd[0]["message"]


def test_the_convention_is_read_from_the_tree_not_assumed(in_tmp: Path) -> None:
    """A tree that numbers each directory independently is not a tree_006 finding.

    ``10_tables/01_users.sql`` is the layout `docs/organizing-sql-files.md`
    calls Pattern 2 and is entirely idiomatic. The rule fires only where the
    tree itself demonstrates the extending convention — where the parent's own
    prefix extends *its* parent's.
    """
    _project(
        in_tmp,
        {
            "10_tables/01_users.sql": "CREATE TABLE tb_users (id INT);\n",
            "10_tables/02_posts.sql": "CREATE TABLE tb_posts (id INT);\n",
            "20_views/01_user_stats.sql": "CREATE VIEW v_s AS SELECT 1 AS x;\n",
        },
    )

    assert _codes(_findings(), "tree_006") == []
