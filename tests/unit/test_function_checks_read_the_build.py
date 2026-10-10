"""``--require-migration``'s function checks read the trees the build reads (#700).

The signature check (a parameter type changed, so the old overload needs a
``DROP FUNCTION``) and the body check (``--require-migration-bodies``) compared
each changed ``.sql`` file in the repository with itself at the two refs. A file
the environment does not build could fail the gate; a routine that moved between
files was never compared with itself; an unparseable file anywhere turned both
checks off. They now compare the routines of the two trees ``compare_refs``
reads — the build's selection at each ref, whole — from the fork point.
"""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.git import GitRepository
from confiture.core.git_accompaniment import MigrationAccompanimentChecker
from confiture.models.git import MigrationAccompanimentReport

runner = CliRunner()

DEFAULT_CONFIG = (
    "name: local\ndatabase_url: postgresql://localhost/x\ninclude_dirs:\n  - path: db/schema\n"
)
EXCLUDING_LEGACY = (
    "name: local\ndatabase_url: postgresql://localhost/x\n"
    'include_dirs:\n  - path: db/schema\n    exclude: ["legacy/**"]\n'
)
TABLE = "CREATE TABLE t (id bigint PRIMARY KEY);\n"


def fn(name: str, arg: str, body: str = "SELECT 1") -> str:
    return f"CREATE FUNCTION {name}(p {arg}) RETURNS integer LANGUAGE sql AS $$ {body} $$;\n"


def replace_fn(name: str, arg: str, body: str = "SELECT 1") -> str:
    return fn(name, arg, body).replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")


class Repo:
    """A git repository holding a confiture project at its root."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        ).stdout.strip()

    def write(self, files: dict[str, str | None]) -> None:
        for name, text in files.items():
            path = self.root / name
            if text is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)

    def commit(self, message: str, files: dict[str, str | None] | None = None) -> None:
        self.write(files or {})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def check(
        self, base: str = "HEAD~1", target: str = "HEAD", **kwargs: bool
    ) -> MigrationAccompanimentReport:
        return MigrationAccompanimentChecker("local", self.root).check_accompaniment(
            base, target, **kwargs
        )


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[..., Repo]:
    """A repository whose base commit holds *config*, a table and *files*."""

    def make(config: str = DEFAULT_CONFIG, files: dict[str, str | None] | None = None) -> Repo:
        repo = Repo(tmp_path / "repo")
        repo.root.mkdir()
        repo.git("init", "-q", "-b", "main")
        repo.git("config", "user.email", "test@test.com")
        repo.git("config", "user.name", "Test")
        repo.commit(
            "base",
            {
                "db/environments/local.yaml": config,
                "db/schema/t.sql": TABLE,
                "db/migrations/.keep": "",
                **(files or {}),
            },
        )
        return repo

    return make


def signatures(report: MigrationAccompanimentReport) -> list[tuple[str, str]]:
    return [(v.old_signature, v.new_signature) for v in report.signature_violations]


def bodies(report: MigrationAccompanimentReport) -> list[str]:
    return [v.signature_key for v in report.body_violations]


# --- files the build does not read -------------------------------------------


def test_a_retype_in_an_excluded_file_is_not_a_violation(make_repo) -> None:
    repo = make_repo(EXCLUDING_LEGACY, {"db/schema/legacy/old.sql": fn("g", "integer")})
    repo.commit("retype", {"db/schema/legacy/old.sql": fn("g", "bigint")})

    report = repo.check()

    assert signatures(report) == []
    assert report.has_ddl_changes is False
    assert report.is_valid


def test_a_retype_outside_the_include_dirs_is_not_a_violation(make_repo) -> None:
    repo = make_repo(
        files={"tests/fixtures/f.sql": fn("g", "integer"), "db/seeds/f.sql": fn("s", "integer")}
    )
    repo.commit(
        "retype", {"tests/fixtures/f.sql": fn("g", "bigint"), "db/seeds/f.sql": fn("s", "bigint")}
    )

    assert repo.check().is_valid


def test_a_retype_under_a_non_default_include_dir_is_a_violation(make_repo) -> None:
    config = DEFAULT_CONFIG + "  - path: sql/ddl\n"
    repo = make_repo(config, {"sql/ddl/f.sql": fn("g", "integer")})
    repo.commit("retype", {"sql/ddl/f.sql": fn("g", "bigint")})

    assert signatures(repo.check()) == [("public.g(integer)", "public.g(bigint)")]


def test_an_unparseable_file_outside_the_build_does_not_disable_the_check(make_repo) -> None:
    repo = make_repo(files={"db/schema/a.sql": fn("h", "integer")})
    repo.commit(
        "retype",
        {
            "db/schema/a.sql": fn("h", "bigint"),
            "db/migrations/001_h.up.sql": replace_fn("h", "bigint"),
            "tests/check.sql": "\\set ON_ERROR_STOP on\n-- CREATE FUNCTION is tested here\n",
        },
    )

    assert signatures(repo.check()) == [("public.h(integer)", "public.h(bigint)")]


# --- a routine that moves --------------------------------------------------------


def test_a_retype_across_a_git_mv_is_a_violation(make_repo) -> None:
    repo = make_repo(files={"db/schema/a.sql": fn("h", "integer")})
    repo.commit(
        "move and retype",
        {
            "db/schema/a.sql": None,
            "db/schema/b.sql": fn("h", "bigint"),
            "db/migrations/001_h.up.sql": replace_fn("h", "bigint"),
        },
    )

    report = repo.check()

    assert signatures(report) == [("public.h(integer)", "public.h(bigint)")]
    assert not report.is_valid


def test_a_retype_across_a_git_mv_with_the_drop_is_valid(make_repo) -> None:
    repo = make_repo(files={"db/schema/a.sql": fn("h", "integer")})
    repo.commit(
        "move and retype",
        {
            "db/schema/a.sql": None,
            "db/schema/b.sql": fn("h", "bigint"),
            "db/migrations/001_h.up.sql": "DROP FUNCTION h(integer);\n" + fn("h", "bigint"),
        },
    )

    assert repo.check().is_valid


def test_a_body_edit_across_a_git_mv_is_a_body_violation(make_repo) -> None:
    repo = make_repo(files={"db/schema/a.sql": fn("h", "integer")})
    repo.commit(
        "move and edit",
        {"db/schema/a.sql": None, "db/schema/b.sql": fn("h", "integer", "SELECT 2")},
    )

    assert bodies(repo.check(check_bodies=True)) == ["public.h(integer)"]


def test_a_body_edit_in_an_excluded_file_is_not_a_body_violation(make_repo) -> None:
    repo = make_repo(EXCLUDING_LEGACY, {"db/schema/legacy/old.sql": fn("g", "integer")})
    repo.commit("edit", {"db/schema/legacy/old.sql": fn("g", "integer", "SELECT 2")})

    report = repo.check(check_bodies=True)

    assert bodies(report) == []
    assert report.is_valid


# --- what the build makes of the tree ---------------------------------------------


def test_an_overload_added_beside_a_kept_one_is_not_a_retype(make_repo) -> None:
    repo = make_repo(files={"db/schema/a.sql": fn("f", "integer")})
    repo.commit(
        "overload",
        {
            "db/schema/a.sql": fn("f", "integer") + fn("f", "text"),
            "db/migrations/001_f.up.sql": fn("f", "text"),
        },
    )

    report = repo.check()

    assert signatures(report) == []
    assert report.is_valid


def test_a_routine_a_later_file_drops_is_compared_as_the_build_folds_it(make_repo) -> None:
    repo = make_repo(files={"db/schema/10_f.sql": fn("f", "integer")})
    repo.commit(
        "redefine in a later file",
        {
            "db/schema/20_f.sql": "DROP FUNCTION f(integer);\n" + fn("f", "bigint"),
            "db/migrations/001_f.up.sql": replace_fn("f", "bigint"),
        },
    )

    assert signatures(repo.check()) == [("public.f(integer)", "public.f(bigint)")]


def test_the_staged_tree_is_read_the_same_way(make_repo) -> None:
    repo = make_repo(EXCLUDING_LEGACY, {"db/schema/legacy/old.sql": fn("g", "integer")})
    repo.write({"db/schema/legacy/old.sql": fn("g", "bigint")})
    repo.git("add", "-A")
    git_repo = GitRepository(repo.root)

    report = repo.check("HEAD", git_repo.staged_tree_oid(), two_dot=True)

    assert signatures(report) == []
    assert report.is_valid


# --- from the fork point ------------------------------------------------------------


def test_a_routine_main_changed_after_the_fork_is_not_the_branchs(make_repo) -> None:
    repo = make_repo(files={"db/schema/a.sql": fn("h", "integer")})
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("unrelated", {"README.md": "a branch that touches no schema\n"})
    repo.git("checkout", "-q", "main")
    repo.commit(
        "retype on main",
        {
            "db/schema/a.sql": fn("h", "bigint", "SELECT 2"),
            "db/migrations/001_h.up.sql": "DROP FUNCTION h(integer);\n" + fn("h", "bigint"),
        },
    )
    repo.git("checkout", "-q", "feature")

    report = repo.check("main", "HEAD", check_bodies=True)

    assert signatures(report) == []
    assert bodies(report) == []
    assert report.has_ddl_changes is False
    assert report.is_valid


# --- where a migration is read from --------------------------------------------------


def test_a_migration_is_read_from_the_repository_not_the_cwd(
    make_repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(files={"db/schema/a.sql": fn("h", "integer")})
    repo.commit(
        "retype",
        {
            "db/schema/a.sql": fn("h", "bigint"),
            "db/migrations/001_h.up.sql": "DROP FUNCTION h(integer);\n" + fn("h", "bigint"),
        },
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert repo.check().is_valid


# --- the CLI ------------------------------------------------------------------------


def test_require_migration_json_ignores_an_excluded_file(
    make_repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(EXCLUDING_LEGACY, {"db/schema/legacy/old.sql": fn("g", "integer")})
    repo.commit("retype", {"db/schema/legacy/old.sql": fn("g", "bigint")})
    monkeypatch.chdir(repo.root)

    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--require-migration",
            "--base-ref",
            "HEAD~1",
            "--config",
            "db/environments/local.yaml",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "passed"
