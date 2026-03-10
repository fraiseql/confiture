"""CLI tests for confiture migrate verify command (Issue #65)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.migration_verifier import VerifyResult


class TestMigrateVerifyCLI:
    """CLI tests for migrate verify command."""

    runner = CliRunner()

    def _make_config(self, tmp_path) -> Path:
        """Create a minimal config file for testing."""
        config_file = tmp_path / "local.yaml"
        config_file.write_text("database:\n  url: postgresql://localhost/test\n")
        return config_file

    def test_requires_config(self):
        """Exit 1 when no config provided."""
        result = self.runner.invoke(app, ["migrate", "verify"])
        assert result.exit_code == 1

    def test_exits_0_when_all_verified(self, tmp_path):
        """Exit 0 when all migrations verified successfully."""
        config_file = self._make_config(tmp_path)

        verified_result = VerifyResult(
            version="001",
            name="foo",
            verify_file=Path("db/migrations/001_foo.verify.sql"),
            status="verified",
            actual_value=True,
        )

        with (
            patch("confiture.core.connection.load_config") as mock_load,
            patch("confiture.core.connection.create_connection") as mock_conn_fn,
            patch("confiture.core.migrator.Migrator") as mock_migrator_cls,
            patch("confiture.core.migration_verifier.MigrationVerifier") as mock_verifier_cls,
        ):
            mock_env = MagicMock()
            mock_env.database_url = "postgresql://localhost/test"
            mock_load.return_value = mock_env

            mock_conn = MagicMock()
            mock_conn_fn.return_value = mock_conn

            mock_migrator = MagicMock()
            mock_migrator.get_applied_versions.return_value = ["001"]
            mock_migrator_cls.return_value = mock_migrator

            mock_verifier = MagicMock()
            mock_verifier.verify_all.return_value = [verified_result]
            mock_verifier_cls.return_value = mock_verifier

            result = self.runner.invoke(
                app,
                ["migrate", "verify", "-c", str(config_file)],
            )
            assert result.exit_code == 0

    def test_exits_1_when_any_failed(self, tmp_path):
        """Exit 1 when any migration failed verification."""
        config_file = self._make_config(tmp_path)

        failed_result = VerifyResult(
            version="001",
            name="foo",
            verify_file=Path("db/migrations/001_foo.verify.sql"),
            status="failed",
            actual_value=False,
        )

        with (
            patch("confiture.core.connection.load_config") as mock_load,
            patch("confiture.core.connection.create_connection") as mock_conn_fn,
            patch("confiture.core.migrator.Migrator") as mock_migrator_cls,
            patch("confiture.core.migration_verifier.MigrationVerifier") as mock_verifier_cls,
        ):
            mock_env = MagicMock()
            mock_env.database_url = "postgresql://localhost/test"
            mock_load.return_value = mock_env

            mock_conn = MagicMock()
            mock_conn_fn.return_value = mock_conn

            mock_migrator = MagicMock()
            mock_migrator.get_applied_versions.return_value = ["001"]
            mock_migrator_cls.return_value = mock_migrator

            mock_verifier = MagicMock()
            mock_verifier.verify_all.return_value = [failed_result]
            mock_verifier_cls.return_value = mock_verifier

            result = self.runner.invoke(
                app,
                ["migrate", "verify", "-c", str(config_file)],
            )
            assert result.exit_code == 1

    def test_json_output_format(self, tmp_path):
        """JSON output contains expected keys."""
        config_file = self._make_config(tmp_path)

        verified_result = VerifyResult(
            version="001",
            name="foo",
            verify_file=Path("db/migrations/001_foo.verify.sql"),
            status="verified",
            actual_value=True,
        )

        with (
            patch("confiture.core.connection.load_config") as mock_load,
            patch("confiture.core.connection.create_connection") as mock_conn_fn,
            patch("confiture.core.migrator.Migrator") as mock_migrator_cls,
            patch("confiture.core.migration_verifier.MigrationVerifier") as mock_verifier_cls,
        ):
            mock_env = MagicMock()
            mock_env.database_url = "postgresql://localhost/test"
            mock_load.return_value = mock_env

            mock_conn = MagicMock()
            mock_conn_fn.return_value = mock_conn

            mock_migrator = MagicMock()
            mock_migrator.get_applied_versions.return_value = ["001"]
            mock_migrator_cls.return_value = mock_migrator

            mock_verifier = MagicMock()
            mock_verifier.verify_all.return_value = [verified_result]
            mock_verifier_cls.return_value = mock_verifier

            result = self.runner.invoke(
                app,
                ["migrate", "verify", "-c", str(config_file), "--format", "json"],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert "verified_count" in output
            assert "failed_count" in output
            assert "skipped_count" in output
            assert "total_applied" in output
            assert "results" in output

    def test_no_file_counted_as_skipped(self, tmp_path):
        """Migrations without verify files are counted as skipped."""
        config_file = self._make_config(tmp_path)

        no_file_result = VerifyResult(
            version="001",
            name="001",
            verify_file=None,
            status="no_file",
        )

        with (
            patch("confiture.core.connection.load_config") as mock_load,
            patch("confiture.core.connection.create_connection") as mock_conn_fn,
            patch("confiture.core.migrator.Migrator") as mock_migrator_cls,
            patch("confiture.core.migration_verifier.MigrationVerifier") as mock_verifier_cls,
        ):
            mock_env = MagicMock()
            mock_env.database_url = "postgresql://localhost/test"
            mock_load.return_value = mock_env

            mock_conn = MagicMock()
            mock_conn_fn.return_value = mock_conn

            mock_migrator = MagicMock()
            mock_migrator.get_applied_versions.return_value = ["001"]
            mock_migrator_cls.return_value = mock_migrator

            mock_verifier = MagicMock()
            mock_verifier.verify_all.return_value = [no_file_result]
            mock_verifier_cls.return_value = mock_verifier

            result = self.runner.invoke(
                app,
                ["migrate", "verify", "-c", str(config_file), "--format", "json"],
            )
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert output["skipped_count"] == 1
            assert output["failed_count"] == 0
