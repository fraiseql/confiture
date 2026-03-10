"""Unit tests for grant accompaniment validation (Issue #66)."""

from pathlib import Path
from unittest.mock import MagicMock

from confiture.core.grant_accompaniment import GrantAccompanimentChecker
from confiture.models.git import GrantAccompanimentReport


class TestGrantAccompanimentReport:
    """Tests for GrantAccompanimentReport dataclass."""

    def test_no_grant_changes_is_valid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=False,
            has_migration_changes=False,
            grant_files_changed=[],
            migration_files_staged=[],
        )
        assert report.is_valid is True

    def test_grant_change_with_migration_is_valid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=True,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[Path("db/migrations/20260301120000_add_reporter.up.sql")],
        )
        assert report.is_valid is True

    def test_grant_change_without_migration_is_invalid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=False,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[],
        )
        assert report.is_valid is False

    def test_only_migration_no_grant_is_valid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=False,
            has_migration_changes=True,
            grant_files_changed=[],
            migration_files_staged=[Path("db/migrations/20260301120000_add_reporter.up.sql")],
        )
        assert report.is_valid is True

    def test_summary_no_changes(self):
        report = GrantAccompanimentReport(
            has_grant_changes=False,
            has_migration_changes=False,
            grant_files_changed=[],
            migration_files_staged=[],
        )
        assert "No grant" in report.summary()

    def test_summary_valid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=True,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[Path("db/migrations/20260301120000_add_reporter.up.sql")],
        )
        assert "accompanied" in report.summary()

    def test_summary_invalid(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=False,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[],
        )
        assert "without" in report.summary()

    def test_to_dict_structure(self):
        report = GrantAccompanimentReport(
            has_grant_changes=True,
            has_migration_changes=False,
            grant_files_changed=[Path("db/7_grant/741_grant_reporter.sql")],
            migration_files_staged=[],
        )
        d = report.to_dict()
        assert "is_valid" in d
        assert "has_grant_changes" in d
        assert "has_migration_changes" in d
        assert "grant_files_changed" in d
        assert "migration_files_staged" in d
        assert d["is_valid"] is False
        assert d["grant_files_changed"] == ["db/7_grant/741_grant_reporter.sql"]


class TestGrantAccompanimentChecker:
    """Tests for GrantAccompanimentChecker."""

    def _make_checker(self):
        checker = GrantAccompanimentChecker()
        checker.git_repo = MagicMock()
        return checker

    def test_no_grant_changes_is_valid(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = []
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.has_grant_changes is False

    def test_grant_change_with_migration_is_valid(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/741_grant_reporter.sql"),
            Path("db/migrations/20260301120000_add_reporter.up.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.has_grant_changes is True
        assert report.has_migration_changes is True

    def test_grant_change_without_migration_is_invalid(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/741_grant_reporter.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is False
        assert report.has_grant_changes is True
        assert report.has_migration_changes is False

    def test_only_migration_no_grant_is_valid(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/migrations/20260301120000_add_reporter.up.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.has_grant_changes is False

    def test_report_lists_grant_files(self):
        checker = self._make_checker()
        grant_file = Path("db/7_grant/741_grant_reporter.sql")
        checker.git_repo.get_staged_files.return_value = [grant_file]
        report = checker.check_accompaniment(staged_only=True)
        assert grant_file in report.grant_files_changed

    def test_report_lists_migration_files(self):
        checker = self._make_checker()
        migration_file = Path("db/migrations/20260301120000_add_reporter.up.sql")
        checker.git_repo.get_staged_files.return_value = [migration_file]
        report = checker.check_accompaniment(staged_only=True)
        assert migration_file in report.migration_files_staged

    def test_grant_in_wrong_dir_is_ignored(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/other/grant.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.has_grant_changes is False
        assert report.is_valid is True

    def test_non_up_sql_migration_not_counted(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/741_grant_reporter.sql"),
            Path("db/migrations/20260301120000_add_reporter.down.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.has_migration_changes is False
        assert report.is_valid is False

    def test_nested_grant_file_is_detected(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/subdir/grant.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.has_grant_changes is True

    def test_empty_repo_is_valid(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = []
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True

    def test_staged_only_uses_get_staged_files(self):
        checker = self._make_checker()
        checker.git_repo.get_staged_files.return_value = []
        checker.check_accompaniment(staged_only=True)
        checker.git_repo.get_staged_files.assert_called_once()
        checker.git_repo.get_changed_files.assert_not_called()

    def test_ref_mode_uses_get_changed_files(self):
        checker = self._make_checker()
        checker.git_repo.get_changed_files.return_value = []
        checker.check_accompaniment(base_ref="origin/main", target_ref="HEAD", staged_only=False)
        checker.git_repo.get_changed_files.assert_called_once_with("origin/main", "HEAD")
        checker.git_repo.get_staged_files.assert_not_called()

    def test_custom_grant_dir(self):
        checker = GrantAccompanimentChecker(grant_dir="db/grants")
        checker.git_repo = MagicMock()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/grants/reporter.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.has_grant_changes is True

    def test_custom_migrations_dir(self):
        checker = GrantAccompanimentChecker(migrations_dir="db/custom_migrations")
        checker.git_repo = MagicMock()
        checker.git_repo.get_staged_files.return_value = [
            Path("db/7_grant/grant.sql"),
            Path("db/custom_migrations/001_foo.up.sql"),
        ]
        report = checker.check_accompaniment(staged_only=True)
        assert report.has_migration_changes is True
