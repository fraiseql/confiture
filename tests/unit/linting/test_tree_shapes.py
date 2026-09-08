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
from confiture.config.environment import DEFAULT_STATUS_WORDS

runner = CliRunner()

_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"

#: The issue's own tree, at the depth it names
#: (``db/0_schema/03_functions/034_dim/0248_configurator/…``).
_ISSUE_TREE = {
    "03_functions/034_dim/0248_configurator/00001_create.sql": "CREATE TABLE tb_cfg (id INT);\n",
    "03_functions/034_dim/0248_flag/00001_create.sql": "CREATE TABLE tb_flag (id INT);\n",
    "03_functions/034_dim/0341_geo/03452_odd/00001_create.sql": "CREATE TABLE tb_geo (id INT);\n",
    "03_functions/034_dim/unnumbered_thing.sql": "CREATE TABLE tb_thing (id INT);\n",
    f"03_functions/034_dim/00002_update_{DEFAULT_STATUS_WORDS[0]}.sql": (
        "CREATE TABLE tb_upd (id INT);\n"
    ),
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


def test_an_unnumbered_entry_beside_numbered_siblings(in_tmp: Path) -> None:
    """The third shape: a file with no prefix sorts by name against numbered siblings."""
    _project(in_tmp, _ISSUE_TREE)

    found = _codes(_findings(), "tree_007")

    assert [i["file"] for i in found] == ["db/schema/03_functions/034_dim/unnumbered_thing.sql"]
    assert found[0]["line"] == 1


def test_a_directory_of_unnumbered_files_is_not_a_finding(in_tmp: Path) -> None:
    """``00_common/extensions.sql`` is idiomatic: nothing in it is numbered."""
    _project(
        in_tmp,
        {
            "00_common/extensions.sql": "CREATE EXTENSION IF NOT EXISTS pgcrypto;\n",
            "00_common/roles.sql": "CREATE TABLE tb_r (id INT);\n",
            "10_tables/users.sql": "CREATE TABLE tb_u (id INT);\n",
        },
    )

    assert _codes(_findings(), "tree_007") == []


def test_a_status_word_in_a_name(in_tmp: Path) -> None:
    """The fourth shape: the file is in the build and its name says it is not finished."""
    _project(in_tmp, _ISSUE_TREE)

    found = _codes(_findings(), "tree_008")

    assert [i["file"] for i in found] == [
        f"db/schema/03_functions/034_dim/00002_update_{DEFAULT_STATUS_WORDS[0]}.sql"
    ]
    assert found[0]["severity"] == "info"
    assert DEFAULT_STATUS_WORDS[0] in found[0]["message"]


def test_the_status_words_are_configurable(in_tmp: Path) -> None:
    """A project names its own vocabulary; the default is documented, not hardcoded."""
    _project(
        in_tmp,
        {"00001_create_ADRAFT.sql": "CREATE TABLE tb_a (id INT);\n"},
        env_extra="lint:\n  status_words: [ADRAFT]\n",
    )

    found = _codes(_findings(), "tree_008")

    assert [i["file"] for i in found] == ["db/schema/00001_create_ADRAFT.sql"]


_EXCLUDED_ENV = (
    "database_url: postgresql://localhost/test\n"
    "include_dirs:\n"
    "  - path: db/schema\n"
    "    exclude:\n"
    "      - 'vendor/*.sql'\n"
    "exclude_dirs:\n"
    "  - db/schema/legacy\n"
)


def test_a_directory_the_build_never_reads_is_judged_by_nothing(in_tmp: Path) -> None:
    """LINT-08 holds for the four new rules: they read the build's file list.

    Both exclusion mechanisms are exercised — the legacy ``exclude_dirs`` and a
    per-directory ``exclude`` glob — because a rule that walked the tree itself
    would report the numbering of files nothing applies.
    """
    _project(
        in_tmp,
        {
            "0100_kept/00001_create.sql": "CREATE TABLE tb_a (id INT);\n",
            "legacy/0248_a/00001_create.sql": "CREATE TABLE tb_b (id INT);\n",
            "legacy/0248_b/00001_create.sql": "CREATE TABLE tb_c (id INT);\n",
            "vendor/00001_create.sql": "CREATE TABLE tb_d (id INT);\n",
            "vendor/unnumbered.sql": "CREATE TABLE tb_e (id INT);\n",
            f"vendor/00002_{DEFAULT_STATUS_WORDS[0]}.sql": "CREATE TABLE tb_f (id INT);\n",
        },
    )
    (in_tmp / "db" / "environments" / "local.yaml").write_text(_EXCLUDED_ENV)

    assert {i["rule_id"] for i in _findings()} == set()


def test_the_same_tree_without_the_exclusions_is_full_of_findings(in_tmp: Path) -> None:
    """The other half of the previous test: the tree really does trip the rules."""
    _project(
        in_tmp,
        {
            "0100_kept/00001_create.sql": "CREATE TABLE tb_a (id INT);\n",
            "legacy/0248_a/00001_create.sql": "CREATE TABLE tb_b (id INT);\n",
            "legacy/0248_b/00001_create.sql": "CREATE TABLE tb_c (id INT);\n",
            "vendor/00001_create.sql": "CREATE TABLE tb_d (id INT);\n",
            "vendor/unnumbered.sql": "CREATE TABLE tb_e (id INT);\n",
            f"vendor/00002_{DEFAULT_STATUS_WORDS[0]}.sql": "CREATE TABLE tb_f (id INT);\n",
        },
    )

    assert {i["rule_id"] for i in _findings()} >= {"tree_005", "tree_007", "tree_008"}


def test_a_baseline_absorbs_a_tree_that_has_never_been_checked(in_tmp: Path) -> None:
    """The adoption path for #249's reporter: 36 collisions, then a ratchet.

    A tree rule's object is a path, so the identity is stable across runs; a
    baseline written today must leave the run clean tomorrow and still fail on
    a collision added after it.
    """
    schema = {
        f"{n:04d}_a/00001_create.sql": f"CREATE TABLE tb_a{n} (id INT);\n" for n in range(100, 136)
    }
    schema.update(
        {
            f"{n:04d}_b/00001_create.sql": f"CREATE TABLE tb_b{n} (id INT);\n"
            for n in range(100, 136)
        }
    )
    _project(in_tmp, schema)
    baseline = in_tmp / ".confiture-lint-baseline.json"

    first = runner.invoke(
        app, ["lint", "--select", "tree_005", "--baseline", str(baseline), "--write-baseline"]
    )
    assert first.exit_code == 0, first.output
    assert len(json.loads(baseline.read_text())["rules"]["tree_005"]) == 36

    second = runner.invoke(app, ["lint", "--select", "tree_005", "--baseline", str(baseline)])
    assert second.exit_code == 0, second.output

    for suffix in ("c", "d"):
        directory = in_tmp / "db" / "schema" / f"0200_{suffix}"
        directory.mkdir()
        (directory / "00001_create.sql").write_text(f"CREATE TABLE tb_{suffix} (id INT);\n")
    third = runner.invoke(app, ["lint", "--select", "tree_005", "--baseline", str(baseline)])

    assert third.exit_code == 1, third.output
    assert "0200_d" in third.output
