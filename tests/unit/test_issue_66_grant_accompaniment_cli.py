"""CLI tests for --require-grant-migration and --allow-grant-only flags (Issue #66)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app


class TestMigrateValidateGrantAccompaniment:
    """CLI tests for grant accompaniment validation."""

    runner = CliRunner()

    def _make_grant_result(self, is_valid: bool, has_grant_changes: bool = True):
        return {
            "is_valid": is_valid,
            "has_grant_changes": has_grant_changes,
            "has_migration_changes": is_valid,
            "grant_files_changed": ["db/7_grant/741_grant_reporter.sql"]
            if has_grant_changes
            else [],
            "migration_files_staged": ["db/migrations/001_foo.up.sql"] if is_valid else [],
        }

    def test_require_grant_migration_passes_when_valid(self):
        """Exit 0 when grant changes accompanied by migration."""
        with (
            patch("confiture.cli.git_validation.validate_git_flags_in_repo"),
            patch("confiture.cli.git_validation.GrantAccompanimentChecker") as mock_cls,
        ):
            mock_checker = MagicMock()
            mock_report = MagicMock()
            mock_report.is_valid = True
            mock_report.has_grant_changes = True
            mock_report.has_migration_changes = True
            mock_report.grant_files_changed = [Path("db/7_grant/741_grant_reporter.sql")]
            mock_report.migration_files_staged = [Path("db/migrations/001_foo.up.sql")]
            mock_report.to_dict.return_value = self._make_grant_result(True)
            mock_checker.check_accompaniment.return_value = mock_report
            mock_cls.return_value = mock_checker

            result = self.runner.invoke(
                app,
                ["migrate", "validate", "--require-grant-migration", "--staged"],
            )
            assert result.exit_code == 0

    def test_require_grant_migration_fails_when_invalid(self):
        """Exit 1 when grant changes without migration."""
        with (
            patch("confiture.cli.git_validation.validate_git_flags_in_repo"),
            patch("confiture.cli.git_validation.GrantAccompanimentChecker") as mock_cls,
        ):
            mock_checker = MagicMock()
            mock_report = MagicMock()
            mock_report.is_valid = False
            mock_report.has_grant_changes = True
            mock_report.has_migration_changes = False
            mock_report.grant_files_changed = [Path("db/7_grant/741_grant_reporter.sql")]
            mock_report.migration_files_staged = []
            mock_report.to_dict.return_value = self._make_grant_result(False)
            mock_checker.check_accompaniment.return_value = mock_report
            mock_cls.return_value = mock_checker

            result = self.runner.invoke(
                app,
                ["migrate", "validate", "--require-grant-migration", "--staged"],
            )
            assert result.exit_code == 1

    def test_allow_grant_only_suppresses_failure(self):
        """Exit 0 when --allow-grant-only is set even with grant changes."""
        # With --allow-grant-only, the grant check should be skipped entirely
        with patch("confiture.cli.git_validation.validate_git_flags_in_repo"):
            result = self.runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--require-grant-migration",
                    "--allow-grant-only",
                    "--staged",
                ],
            )
            # Should pass (grant check skipped), but no other checks run
            # so it should return 0 (all checks passed — grant check was allowed-only)
            assert result.exit_code == 0

    def test_require_grant_migration_json_output_on_failure(self):
        """JSON output on grant accompaniment failure."""
        with (
            patch("confiture.cli.git_validation.validate_git_flags_in_repo"),
            patch("confiture.cli.git_validation.GrantAccompanimentChecker") as mock_cls,
        ):
            mock_checker = MagicMock()
            mock_report = MagicMock()
            mock_report.is_valid = False
            mock_report.has_grant_changes = True
            mock_report.has_migration_changes = False
            mock_report.grant_files_changed = [Path("db/7_grant/741_grant_reporter.sql")]
            mock_report.migration_files_staged = []
            mock_report.to_dict.return_value = self._make_grant_result(False)
            mock_checker.check_accompaniment.return_value = mock_report
            mock_cls.return_value = mock_checker

            result = self.runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--require-grant-migration",
                    "--staged",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 1
            import json

            output = json.loads(result.output)
            assert output["status"] == "failed"
            assert output["check"] == "grant_accompaniment"
