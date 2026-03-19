"""Tests for signature violation integration in MigrationAccompanimentChecker."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from confiture.core.function_signature_checker import FunctionSignatureViolation
from confiture.models.git import MigrationAccompanimentReport


def _build_report(
    has_ddl: bool = False,
    has_migrations: bool = True,
    signature_violations: list | None = None,
) -> MigrationAccompanimentReport:
    return MigrationAccompanimentReport(
        has_ddl_changes=has_ddl,
        has_new_migrations=has_migrations,
        signature_violations=signature_violations or [],
    )


class TestMigrationAccompanimentReportSignatureFields:
    def test_has_signature_violations_false_when_empty(self):
        report = _build_report()
        assert not report.has_signature_violations

    def test_has_signature_violations_true_when_present(self):
        v = FunctionSignatureViolation(
            function_key="public.f",
            old_signature="public.f(integer)",
            new_signature="public.f(bigint)",
            migration_file=None,
            message="missing DROP",
        )
        report = _build_report(signature_violations=[v])
        assert report.has_signature_violations

    def test_is_valid_false_when_signature_violation(self):
        v = FunctionSignatureViolation(
            function_key="public.f",
            old_signature="public.f(integer)",
            new_signature="public.f(bigint)",
            migration_file=None,
            message="missing DROP",
        )
        report = _build_report(has_ddl=True, has_migrations=True, signature_violations=[v])
        assert not report.is_valid

    def test_is_valid_true_no_violations_no_ddl(self):
        report = _build_report(has_ddl=False)
        assert report.is_valid

    def test_is_valid_true_ddl_with_migrations_no_violations(self):
        report = _build_report(has_ddl=True, has_migrations=True)
        assert report.is_valid

    def test_to_dict_includes_signature_violations(self):
        v = FunctionSignatureViolation(
            function_key="public.f",
            old_signature="public.f(integer)",
            new_signature="public.f(bigint)",
            migration_file=None,
            message="missing DROP",
        )
        report = _build_report(signature_violations=[v])
        d = report.to_dict()
        assert "signature_violations" in d
        assert len(d["signature_violations"]) == 1
        assert d["signature_violations"][0]["function_key"] == "public.f"

    def test_to_dict_violations_empty_list_when_none(self):
        report = _build_report()
        d = report.to_dict()
        assert d["signature_violations"] == []


class TestMigrationAccompanimentCheckerSignatureIntegration:
    """Integration tests for check_accompaniment signature checking, with mocked git/differ."""

    def _make_checker_mocked(self):
        """Build a MigrationAccompanimentChecker with mocked git and differ."""
        from confiture.core.git_accompaniment import MigrationAccompanimentChecker

        with patch("confiture.core.git_accompaniment.GitSchemaDiffer"), \
             patch("confiture.core.git_accompaniment.GitRepository"):
            checker = MigrationAccompanimentChecker.__new__(MigrationAccompanimentChecker)

        checker.env = "local"
        checker.repo_path = Path(".")
        checker.git_repo = MagicMock()
        checker.differ = MagicMock()
        return checker

    def test_accompaniment_invalid_when_signature_violation(self, tmp_path):
        """Signature violation (type change, no DROP) marks report invalid."""
        checker = self._make_checker_mocked()

        old_sql = "CREATE FUNCTION public.f(x INTEGER) RETURNS void AS $$ $$ LANGUAGE sql;"
        new_sql = "CREATE FUNCTION public.f(x BIGINT) RETURNS void AS $$ $$ LANGUAGE sql;"

        def show_at_ref(path, ref):
            if ref == "HEAD~1":
                return old_sql
            return new_sql

        checker.git_repo.show_file_at_ref.side_effect = show_at_ref
        checker.git_repo.get_changed_files.return_value = [Path("db/schema/functions.sql")]

        mock_diff = MagicMock()
        mock_diff.changes = []
        checker.differ.compare_refs.return_value = mock_diff
        checker.differ.has_ddl_changes.return_value = False

        report = checker.check_accompaniment("HEAD~1", "HEAD")
        assert report.has_signature_violations
        assert not report.is_valid
        assert len(report.signature_violations) == 1

    def test_accompaniment_valid_when_drop_in_migration(self, tmp_path):
        """Signature violation suppressed when migration has DROP FUNCTION."""
        checker = self._make_checker_mocked()

        mig = tmp_path / "001_change.up.sql"
        mig.write_text(
            "DROP FUNCTION public.f(integer);\n"
            "CREATE OR REPLACE FUNCTION public.f(x BIGINT) RETURNS void AS $$ $$ LANGUAGE sql;"
        )

        old_sql = "CREATE FUNCTION public.f(x INTEGER) RETURNS void AS $$ $$ LANGUAGE sql;"
        new_sql = "CREATE FUNCTION public.f(x BIGINT) RETURNS void AS $$ $$ LANGUAGE sql;"

        def show_at_ref(path, ref):
            if ref == "HEAD~1":
                return old_sql
            return new_sql

        checker.git_repo.show_file_at_ref.side_effect = show_at_ref
        checker.git_repo.get_changed_files.return_value = [
            Path("db/schema/functions.sql"),
            Path("db/migrations/001_change.up.sql"),
        ]

        mock_diff = MagicMock()
        mock_diff.changes = []
        checker.differ.compare_refs.return_value = mock_diff
        checker.differ.has_ddl_changes.return_value = False

        # Patch _get_new_migrations to return our actual tmp migration file
        with patch.object(checker, "_get_new_migrations", return_value=[mig]):
            report = checker.check_accompaniment("HEAD~1", "HEAD")

        assert not report.has_signature_violations
        assert report.is_valid
