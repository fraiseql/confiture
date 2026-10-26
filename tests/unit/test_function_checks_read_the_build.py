"""``--require-migration``'s function checks read the trees the build reads (#700).

The signature check (a parameter type changed, so the old overload needs a
``DROP FUNCTION``) and the body check (``--require-migration-bodies``) compared
each changed ``.sql`` file in the repository with itself at the two refs. A file
the environment does not build could fail the gate; a routine that moved between
files was never compared with itself; an unparseable file anywhere turned both
checks off. They now compare the routines of the two trees ``compare_refs``
reads — the build's selection at each ref, whole — from the fork point.
"""

import ast
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

import confiture
from confiture.cli.main import app
from confiture.core import git_schema
from confiture.core.function_signature_drift import routines_of
from confiture.core.git import GitRepository
from confiture.core.git_accompaniment import MigrationAccompanimentChecker
from confiture.core.schema_model import routine_ref
from confiture.core.schema_read import SchemaRead
from confiture.models.git import MigrationAccompanimentReport

PACKAGE = Path(confiture.__file__).resolve().parent
ROUTINE_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "routine_drift" / "git"

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
        """The gate's report — after holding it to the gate's two shortcuts.

        The checks run only when the diff holds a routine change: every report is
        compared with one the checks ran for unconditionally. And the routines they
        read (the model's) are the routines the diff compared (``declared``).
        """
        checker = MigrationAccompanimentChecker("local", self.root)
        report = checker.check_accompaniment(base, target, **kwargs)
        with patch("confiture.core.git_accompaniment._touches_routines", return_value=True):
            ungated = MigrationAccompanimentChecker("local", self.root).check_accompaniment(
                base, target, **kwargs
            )
        assert violations(ungated) == violations(report)
        if report.migration_error is None:
            for ref in (base, target):
                assert_one_routine_set(checker.differ.builder.read_at_ref(ref))
        return report


def violations(report: MigrationAccompanimentReport) -> list[dict]:
    return [v.to_dict() for v in (*report.signature_violations, *report.body_violations)]


def assert_one_routine_set(read: SchemaRead) -> None:
    """The routines the checks read are the ones ``compare_refs`` compared."""
    assert {routine_ref(routine) for routine in routines_of(read)} == {
        ref for ref in read.declared.objects if ref.kind in ("function", "procedure")
    }


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


# --- what the gate reads -------------------------------------------------------------


def test_the_routine_golden_fixture_reads_alike_gated_or_not(make_repo) -> None:
    repo = make_repo(
        files={"db/schema/10_routines.sql": (ROUTINE_FIXTURES / "base.sql").read_text()}
    )
    repo.commit(
        "head",
        {
            "db/schema/10_routines.sql": (ROUTINE_FIXTURES / "head.sql").read_text(),
            "db/migrations/002_carried.up.sql": (ROUTINE_FIXTURES / "migration.sql").read_text(),
        },
    )

    report = repo.check(check_bodies=True)

    assert [v.function_key for v in report.signature_violations] == [
        "public.fn_retype",
        "public.fn_when",
    ]
    assert bodies(report) == ["public.fn_body(integer)", "app.fn_array(bigint[])"]


def test_the_function_checks_read_nothing_again(make_repo) -> None:
    repo = make_repo(files={"db/schema/a.sql": fn("h", "integer")})
    repo.commit("move and edit", {"db/schema/a.sql": None, "db/schema/b.sql": fn("h", "bigint")})

    with (
        patch.object(git_schema, "read_segments", wraps=git_schema.read_segments) as reads,
        patch.object(
            GitRepository, "materialise", autospec=True, side_effect=GitRepository.materialise
        ) as copies,
    ):
        report = MigrationAccompanimentChecker("local", repo.root).check_accompaniment(
            "HEAD~1", "HEAD", check_bodies=True
        )

    assert report.signature_violations
    assert (reads.call_count, copies.call_count) == (2, 2)


def test_no_routine_change_builds_no_checker(make_repo) -> None:
    repo = make_repo(files={"db/schema/a.sql": fn("h", "integer")})
    repo.commit("a table", {"db/schema/u.sql": "CREATE TABLE u (id bigint);\n"})

    with (
        patch("confiture.core.git_accompaniment.FunctionSignatureChecker") as signature,
        patch("confiture.core.git_accompaniment.FunctionBodyChecker") as body,
    ):
        MigrationAccompanimentChecker("local", repo.root).check_accompaniment(
            "HEAD~1", "HEAD", check_bodies=True
        )

    assert (signature.call_count, body.call_count) == (0, 0)


@pytest.mark.parametrize("module", ["function_signature_checker.py", "function_body_checker.py"])
def test_the_checkers_hold_no_repository(module: str) -> None:
    """Routines in, verdict out: the git read is the glue's (``git_accompaniment``)."""
    tree = ast.parse((PACKAGE / "core" / module).read_text(encoding="utf-8"))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    named = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "confiture.core.git" not in imported
    assert "show_file_at_ref" not in named


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
