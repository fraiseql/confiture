"""``migrate validate --staged`` scopes the git checks to the index (#184).

``--staged`` is the pre-commit mode: it exists to judge what is *about to be
committed*. Until 0.42.0 only ``--require-grant-migration`` honoured it, so
``--check-drift --staged`` and ``--require-migration --staged`` compared
``base_ref`` against ``HEAD`` — i.e. they ignored exactly the changes the
developer was committing, and passed a branch whose staged schema change had no
migration.

Every test here drives the real CLI against a real repository. Two details are
load-bearing:

- the file is staged and then edited further, so a check that reads the
  **worktree** instead of the **index** shows up as a wrong answer rather than
  as a coincidence;
- ``--base-ref HEAD`` is explicit, because the default (``origin/main``) does
  not resolve in a fresh throwaway repository.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_BASE_SCHEMA = "CREATE TABLE tb_machine (pk_machine BIGINT PRIMARY KEY);\n"
_STAGED_SCHEMA = _BASE_SCHEMA + "CREATE TABLE tb_staged_only (pk_staged BIGINT PRIMARY KEY);\n"
_WORKTREE_ONLY = "CREATE TABLE tb_worktree_only (pk_worktree BIGINT PRIMARY KEY);\n"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def staged_repo(tmp_path: Path) -> Iterator[Path]:
    """A repo whose schema change exists **only in the index**.

    ``db/schema/010_tables.sql`` is committed with one table, staged with a
    second, and then edited in the worktree with a third that is *not* staged.
    A check scoped to the index must see the second and never the third.
    """
    repo = tmp_path / "repo"
    (repo / "db" / "schema").mkdir(parents=True)
    (repo / "db" / "migrations").mkdir(parents=True)
    (repo / "db" / "environments").mkdir(parents=True)
    (repo / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    schema = repo / "db" / "schema" / "010_tables.sql"
    schema.write_text(_BASE_SCHEMA)

    _git(repo, "init", "-q", ".")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base schema")

    schema.write_text(_STAGED_SCHEMA)
    _git(repo, "add", "db/schema/010_tables.sql")
    schema.write_text(_STAGED_SCHEMA + _WORKTREE_ONLY)

    old_cwd = Path.cwd()
    os.chdir(repo)
    try:
        yield repo
    finally:
        os.chdir(old_cwd)


def _validate(*args: str) -> object:
    return runner.invoke(app, ["migrate", "validate", "--base-ref", "HEAD", *args])


class TestStagedDrift:
    def test_staged_schema_change_is_reported_as_drift(self, staged_repo: Path) -> None:
        result = _validate("--check-drift", "--staged")

        assert result.exit_code == 1, result.output
        assert "tb_staged_only" in result.output

    def test_unstaged_worktree_change_is_invisible(self, staged_repo: Path) -> None:
        """Content comes from the index blob, not from the file on disk."""
        result = _validate("--check-drift", "--staged")

        assert "tb_worktree_only" not in result.output

    def test_without_staged_the_index_is_ignored(self, staged_repo: Path) -> None:
        """The committed-ref comparison is unchanged: HEAD vs HEAD is no drift."""
        result = _validate("--check-drift")

        assert result.exit_code == 0, result.output
        assert "tb_staged_only" not in result.output


class TestStagedAccompaniment:
    def test_staged_ddl_without_a_staged_migration_fails(self, staged_repo: Path) -> None:
        result = _validate("--require-migration", "--staged")

        assert result.exit_code == 1, result.output

    def test_staged_ddl_with_a_staged_migration_passes(self, staged_repo: Path) -> None:
        migration = staged_repo / "db" / "migrations" / "20260806000000_add_staged.up.sql"
        migration.write_text("CREATE TABLE tb_staged_only (pk_staged BIGINT PRIMARY KEY);\n")
        _git(staged_repo, "add", str(migration.relative_to(staged_repo)))

        result = _validate("--require-migration", "--staged")

        assert result.exit_code == 0, result.output

    def test_an_unstaged_migration_does_not_count(self, staged_repo: Path) -> None:
        """Written but not `git add`ed: it is not part of the commit under test."""
        (staged_repo / "db" / "migrations" / "20260806000000_add_staged.up.sql").write_text(
            "CREATE TABLE tb_staged_only (pk_staged BIGINT PRIMARY KEY);\n"
        )

        result = _validate("--require-migration", "--staged")

        assert result.exit_code == 1, result.output


class TestStagedDegradesLikeTheCommittedPath:
    def test_unresolvable_base_ref_reports_git_003(self, staged_repo: Path) -> None:
        """A shallow checkout has no origin/main; say so with the remedy (#181's GIT_003).

        Staged mode resolves the base ref up front rather than letting the diff
        fail later, because the later failure would be git's own "bad revision"
        with nothing actionable in it.
        """
        result = runner.invoke(
            app,
            ["migrate", "validate", "--check-drift", "--base-ref", "origin/main", "--staged"],
        )

        assert result.exit_code == 7, result.output
        assert "fetch-depth" in result.output

    def test_empty_index_is_not_an_error(self, staged_repo: Path) -> None:
        """Nothing staged is a clean pass, not a crash: the empty tree is a tree."""
        _git(staged_repo, "reset", "-q", "HEAD")

        result = _validate("--check-drift", "--staged")

        assert result.exit_code == 0, result.output
