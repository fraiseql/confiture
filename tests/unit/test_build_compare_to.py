"""``build --list-files --compare-to <ref>``: the build's own selection at a ref, against the working tree (#580)."""

import json
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core import build_order
from confiture.core.build_order import compare_to_ref, renames_since, selection_at_ref
from confiture.core.builder import SchemaBuilder
from confiture.core.schema_exporter import load_schema
from confiture.exceptions import GitError

SCHEMA = "backend/db/schema"
#: Each file distinct enough that git's rename detection pairs it with itself only.
FILES = {
    "01_extensions.sql": "CREATE EXTENSION IF NOT EXISTS pgcrypto;\n",
    "02_types.sql": "CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy');\n",
    "03_tables.sql": "CREATE TABLE users (\n    id bigint PRIMARY KEY,\n    email text NOT NULL\n);\n",
    "04_views.sql": "CREATE VIEW v_users AS\n    SELECT id, email\n    FROM users;\n",
    "05_functions.sql": "CREATE FUNCTION fn_one() RETURNS int\n    LANGUAGE sql AS $$ SELECT 1 $$;\n",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose project sits in ``backend/``, committed, then renumbered by hand.

    ``01_extensions`` becomes ``00_extensions`` (same place in the order);
    ``03_tables`` becomes ``06_tables`` (now after the views and functions).
    """
    root = tmp_path / "repo"
    (root / SCHEMA).mkdir(parents=True)
    for name, sql in FILES.items():
        (root / SCHEMA / name).write_text(sql)
    env_dir = root / "backend" / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "local.yaml").write_text(
        "name: local\n"
        'database_url: "postgresql://localhost/test"\n'
        "include_dirs:\n  - db/schema\n"
        "build:\n  validate_comments:\n    enabled: false\n"
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "mv", f"{SCHEMA}/01_extensions.sql", f"{SCHEMA}/00_extensions.sql")
    _git(root, "mv", f"{SCHEMA}/03_tables.sql", f"{SCHEMA}/06_tables.sql")
    return root


def _checkout_selection(root: Path, ref: str, tmp_path: Path) -> list[str]:
    """``selection_report()`` on a real checkout of *ref*, named relative to the checkout."""
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(root), str(clone)], check=True)
    _git(clone, "checkout", "-q", ref)
    report = SchemaBuilder("local", project_dir=clone / "backend").selection_report()
    return [f.path.resolve().relative_to(clone.resolve()).as_posix() for f in report.files]


def test_the_refs_selection_is_the_build_run_on_a_checkout_of_it(repo, tmp_path):
    head = _git(repo, "rev-parse", "HEAD")
    expected = _checkout_selection(repo, head, tmp_path)
    assert selection_at_ref(repo / "backend", "local", "HEAD") == expected
    assert expected[0] == f"{SCHEMA}/01_extensions.sql"


def test_the_working_tree_side_names_files_relative_to_the_repository(repo):
    assert build_order.selection_here(repo / "backend", "local") == [
        f"{SCHEMA}/00_extensions.sql",
        f"{SCHEMA}/02_types.sql",
        f"{SCHEMA}/04_views.sql",
        f"{SCHEMA}/05_functions.sql",
        f"{SCHEMA}/06_tables.sql",
    ]


def test_renames_come_from_git_rename_detection(repo):
    assert renames_since(repo / "backend", "HEAD") == {
        f"{SCHEMA}/01_extensions.sql": f"{SCHEMA}/00_extensions.sql",
        f"{SCHEMA}/03_tables.sql": f"{SCHEMA}/06_tables.sql",
    }


def test_the_comparison_reports_the_one_file_whose_order_moved(repo):
    result = compare_to_ref(repo / "backend", "local", "HEAD")
    assert result.files == 5
    assert len(result.renamed) == 2
    assert [m.path for m in result.moved] == [f"{SCHEMA}/06_tables.sql"]
    assert result.moved[0].was_after == f"{SCHEMA}/02_types.sql"
    assert result.moved[0].now_after == f"{SCHEMA}/05_functions.sql"


@pytest.mark.parametrize("ref", ["--output=x", "-p", "HEAD;rm"])
def test_an_option_shaped_ref_is_refused_before_git_runs(repo, monkeypatch, ref):
    def no_git(*args, **kwargs):
        raise AssertionError("git was spawned")

    monkeypatch.setattr(subprocess, "run", no_git)
    with pytest.raises(GitError):
        compare_to_ref(repo / "backend", "local", ref)


def test_an_environment_the_ref_has_not_is_named(repo):
    _git(repo, "rm", "-q", "--cached", "backend/db/environments/local.yaml")
    _git(repo, "commit", "-q", "-m", "untrack the environment")
    with pytest.raises(Exception, match=r"db/environments/local\.yaml.*HEAD"):
        selection_at_ref(repo / "backend", "local", "HEAD")


def _invoke(repo: Path, *extra: str):
    return CliRunner().invoke(
        app,
        ["build", "--env", "local", "--project-dir", str(repo / "backend"), *extra],
    )


def test_the_command_names_the_moved_file_and_exits_1(repo):
    result = _invoke(repo, "--list-files", "--compare-to", "HEAD")
    assert result.exit_code == 1, result.output
    text = " ".join(result.stdout.split())
    assert "5 files, 2 renamed, order preserved except:" in text
    assert f"{SCHEMA}/06_tables.sql" in text
    assert f"was after {SCHEMA}/02_types.sql, before {SCHEMA}/04_views.sql" in text
    assert f"now after {SCHEMA}/05_functions.sql" in text


def test_an_unchanged_order_exits_0(repo):
    _git(repo, "mv", f"{SCHEMA}/06_tables.sql", f"{SCHEMA}/03_tables.sql")
    result = _invoke(repo, "--list-files", "--compare-to", "HEAD")
    assert result.exit_code == 0, result.output
    assert "5 files, 1 renamed, order preserved" in " ".join(result.stdout.split())


def test_an_allowed_move_exits_0(repo):
    result = _invoke(
        repo, "--list-files", "--compare-to", "HEAD", "--allow", f"{SCHEMA}/06_tables.sql"
    )
    assert result.exit_code == 0, result.output
    assert "allowed" in result.stdout


def test_the_json_payload_validates_against_its_schema(repo):
    result = _invoke(repo, "--list-files", "--compare-to", "HEAD", "--format", "json")
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    schema = load_schema("build-list-files-compare.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
    assert payload["ref"] == "HEAD"
    assert payload["renamed"] == [
        {"from": f"{SCHEMA}/01_extensions.sql", "to": f"{SCHEMA}/00_extensions.sql"},
        {"from": f"{SCHEMA}/03_tables.sql", "to": f"{SCHEMA}/06_tables.sql"},
    ]
    assert [m["path"] for m in payload["moved"]] == [f"{SCHEMA}/06_tables.sql"]


@pytest.mark.parametrize(
    "argv",
    [["--compare-to", "HEAD"], ["--list-files", "--allow", "x.sql"]],
    ids=["compare-to-without-list-files", "allow-without-compare-to"],
)
def test_a_modifier_without_what_it_modifies_is_refused(repo, argv):
    result = _invoke(repo, *argv)
    assert result.exit_code == 5, result.output
    assert not (repo / "backend" / "db" / "generated").exists()
