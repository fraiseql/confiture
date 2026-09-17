"""A gate that could not run has not passed (issue #288, second observation).

`--require-migration` caught any exception from the schema comparison, printed a
yellow warning and returned a report whose `is_valid` was True — so a skipped
check and a passed check differed by a line of output and nothing else, and CI
went green on a schema nothing had read.

The reason recorded in the code was the sqlparse token limit, which has not been
reachable since pglast became the only parser (D13, 0.50.0). What reaches that
branch today is a schema **PostgreSQL itself rejects** — which `confiture build`
would also refuse, and which CLAUDE.md already calls a finding rather than a
clean result everywhere else it appears (`IDEM_UNPARSEABLE`,
`PFLIGHT_UNPARSEABLE` forcing `window_safe: false`, lint's `UNPARSEABLE`,
`DIFFER_400`).
"""

import subprocess
from pathlib import Path

import pytest

from confiture.core.git_accompaniment import MigrationAccompanimentChecker
from confiture.models.git import MigrationAccompanimentReport

CONFIG = (
    "database_url: postgresql://localhost/test\n"
    "include_dirs:\n"
    "  - path: db/schema\n"
    "    recursive: true\n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@test.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(CONFIG)
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "db" / "schema" / "10_tb_user.sql").write_text(
        "CREATE TABLE tb_user (pk BIGINT);\n"
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "the table")
    return tmp_path


class TestASkippedCheckIsNotAPass:
    def test_a_schema_postgres_rejects_fails_the_gate(self, repo: Path):
        (repo / "db" / "schema" / "20_broken.sql").write_text(
            "CREATE TABLE tb_broken (pk BIGINT,,);\n"
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "a schema that does not parse")

        report = MigrationAccompanimentChecker("local", repo).check_accompaniment("HEAD~1", "HEAD")
        assert report.migration_error is not None, "the parse failure is still named"
        assert report.is_valid is False

    def test_the_error_names_what_could_not_be_read(self, repo: Path):
        (repo / "db" / "schema" / "20_broken.sql").write_text("CREATE TABLE tb (pk BIGINT,,);\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "broken")

        report = MigrationAccompanimentChecker("local", repo).check_accompaniment("HEAD~1", "HEAD")
        assert "syntax error" in (report.migration_error or "").lower()

    def test_a_migration_does_not_excuse_a_schema_that_will_not_parse(self, repo: Path):
        """The check did not run; a migration being present says nothing about it."""
        (repo / "db" / "schema" / "20_broken.sql").write_text("CREATE TABLE tb (pk BIGINT,,);\n")
        (repo / "db" / "migrations" / "001_x.up.sql").write_text("SELECT 1;\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "broken, with a migration")

        report = MigrationAccompanimentChecker("local", repo).check_accompaniment("HEAD~1", "HEAD")
        assert report.has_new_migrations is True
        assert report.is_valid is False


class TestTheReportModel:
    """`is_valid` is the property every caller reads; it must carry the rule."""

    def test_a_report_carrying_a_parse_error_is_not_valid(self):
        assert (
            MigrationAccompanimentReport(
                has_ddl_changes=False,
                has_new_migrations=True,
                migration_error="Schema parse check skipped: syntax error",
            ).is_valid
            is False
        )

    def test_a_report_with_no_error_and_no_changes_is_still_valid(self):
        assert MigrationAccompanimentReport(
            has_ddl_changes=False, has_new_migrations=False
        ).is_valid

    def test_the_summary_says_the_check_did_not_run(self):
        report = MigrationAccompanimentReport(
            has_ddl_changes=False, has_new_migrations=False, migration_error="syntax error at x"
        )
        assert report.summary().startswith("Could not run:")
