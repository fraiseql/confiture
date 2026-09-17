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


class TestRoutinesWithoutAMigration:
    """Existence is unconditional; a body edit stays behind #178's flag."""

    FN = "CREATE OR REPLACE FUNCTION fn_c() RETURNS BIGINT LANGUAGE sql AS $$ SELECT 1 $$;\n"

    def test_a_new_function_without_a_migration_fails_the_gate(self, repo: Path):
        (repo / "db" / "schema" / "30_fn.sql").write_text(self.FN)
        _commit(repo, "a function, no migration")

        report = _check(repo)
        assert report.migration_error is None
        assert report.has_ddl_changes is True
        assert report.is_valid is False

    def test_a_deleted_function_without_a_migration_fails_the_gate(self, repo: Path):
        fn = repo / "db" / "schema" / "30_fn.sql"
        fn.write_text(self.FN)
        _commit(repo, "a function")
        fn.unlink()
        _commit(repo, "the function goes, no migration")

        report = _check(repo)
        assert report.has_ddl_changes is True
        assert report.is_valid is False

    def test_a_body_edit_alone_still_passes_by_default(self, repo: Path):
        """#178 made body edits opt-in. This must not turn that into always-on."""
        fn = repo / "db" / "schema" / "30_fn.sql"
        fn.write_text(self.FN)
        _commit(repo, "a function")
        fn.write_text(self.FN.replace("SELECT 1", "SELECT 2"))
        _commit(repo, "a body edit, no migration")

        report = _check(repo)
        assert report.has_ddl_changes is False
        assert report.is_valid is True

    def test_a_body_edit_fails_the_gate_with_require_migration_bodies(self, repo: Path):
        fn = repo / "db" / "schema" / "30_fn.sql"
        fn.write_text(self.FN)
        _commit(repo, "a function")
        fn.write_text(self.FN.replace("SELECT 1", "SELECT 2"))
        _commit(repo, "a body edit, no migration")

        report = MigrationAccompanimentChecker("local", repo).check_accompaniment(
            "HEAD~1", "HEAD", check_bodies=True
        )
        assert report.is_valid is False

    def test_a_new_function_fails_even_though_its_body_is_new_too(self, repo: Path):
        """The existence signal is not suppressed along with the body signal."""
        (repo / "db" / "schema" / "30_fn.sql").write_text(self.FN)
        _commit(repo, "a function, no migration")

        report = MigrationAccompanimentChecker("local", repo).check_accompaniment("HEAD~1", "HEAD")
        assert [c.type for c in report.ddl_changes] == ["ADD_FUNCTION"]

    def test_a_view_redefined_is_not_suppressed_by_the_body_default(self, repo: Path):
        """Only routines are behind the flag; nothing else reports a redefined view."""
        view = repo / "db" / "schema" / "20_v.sql"
        view.write_text("CREATE OR REPLACE VIEW v_user AS SELECT pk_user FROM tb_user;\n")
        _commit(repo, "a view")
        view.write_text("CREATE OR REPLACE VIEW v_user AS SELECT name FROM tb_user;\n")
        _commit(repo, "the view changes, no migration")

        assert _check(repo).is_valid is False
