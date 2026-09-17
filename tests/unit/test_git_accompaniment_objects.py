"""The accompaniment gate on the objects it used to pass green (issue #288).

The reproduction the issue reports, reduced to a repository this test builds:
two commits, the first adding a table (the control the gate already catches),
the second adding a view and a new function and no migration. Before #288 the
second reported ``has_ddl_changes: False`` with ``migration_error: None`` — not
a skipped check, a check that looked and saw nothing — and the CLI printed
``✅ No DDL changes detected``.
"""

import subprocess
from pathlib import Path

import pytest

from confiture.core.git_accompaniment import MigrationAccompanimentChecker

CONFIG = (
    "database_url: postgresql://localhost/test\n"
    "include_dirs:\n"
    "  - path: db/schema\n"
    "    recursive: true\n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository holding one table, committed."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@test.com")
    _git(tmp_path, "config", "user.name", "Test User")

    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(CONFIG)
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "10_tb_user.sql").write_text(
        "CREATE TABLE tb_user (pk_user BIGINT PRIMARY KEY, name TEXT);\n"
    )
    _commit(tmp_path, "the table")
    return tmp_path


def _check(repo: Path):
    return MigrationAccompanimentChecker("local", repo).check_accompaniment("HEAD~1", "HEAD")


class TestObjectsWithoutAMigration:
    """Each of these is a change a migrate-only environment never receives."""

    def test_a_new_view_without_a_migration_fails_the_gate(self, repo: Path):
        (repo / "db" / "schema" / "20_v_user.sql").write_text(
            "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;\n"
        )
        _commit(repo, "a view, no migration")

        report = _check(repo)
        assert report.migration_error is None, "the schema parsed; this is not a skipped check"
        assert report.has_ddl_changes is True
        assert report.is_valid is False

    def test_a_redefined_view_without_a_migration_fails_the_gate(self, repo: Path):
        view = repo / "db" / "schema" / "20_v_user.sql"
        view.write_text("CREATE OR REPLACE VIEW v_user AS SELECT pk_user FROM tb_user;\n")
        _commit(repo, "a view, with no migration needed yet")
        view.write_text("CREATE OR REPLACE VIEW v_user AS SELECT pk_user, name FROM tb_user;\n")
        _commit(repo, "the view changes, no migration")

        report = _check(repo)
        assert report.migration_error is None
        assert report.has_ddl_changes is True
        assert report.is_valid is False

    def test_a_view_carried_by_a_migration_passes(self, repo: Path):
        """The gate is only worth having if it goes green when the work was done."""
        (repo / "db" / "schema" / "20_v_user.sql").write_text(
            "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;\n"
        )
        (repo / "db" / "migrations" / "001_v_user.up.sql").write_text(
            "CREATE VIEW v_user AS SELECT pk_user FROM tb_user;\n"
        )
        _commit(repo, "a view and its migration")

        report = _check(repo)
        assert report.has_ddl_changes is True
        assert report.has_new_migrations is True
        assert report.is_valid is True

    def test_a_comment_only_edit_still_passes(self, repo: Path):
        """Reformatting is not a schema change; the gate must not cry wolf."""
        (repo / "db" / "schema" / "10_tb_user.sql").write_text(
            "-- the users of the system\nCREATE TABLE tb_user (\n"
            "    pk_user BIGINT PRIMARY KEY,\n    name TEXT\n);\n"
        )
        _commit(repo, "reformat only")

        report = _check(repo)
        assert report.migration_error is None
        assert report.has_ddl_changes is False
        assert report.is_valid is True
