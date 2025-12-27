"""Tests for dry-run CLI functionality in migrate up and migrate down commands."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


class TestMigrateUpDryRun:
    """Tests for migrate up --dry-run functionality."""

    def test_migrate_up_dry_run_analyzes_without_execution(self):
        """Test that --dry-run analyzes migrations without executing them."""
        with patch("confiture.core.connection.create_connection") as mock_conn_factory:
            with patch("confiture.core.connection.load_config"):
                with patch("confiture.core.migrator.Migrator") as mock_migrator_class:
                    # Setup mocks
                    mock_conn = MagicMock()
                    mock_conn_factory.return_value = mock_conn

                    mock_migrator = MagicMock()
                    mock_migrator_class.return_value = mock_migrator
                    mock_migrator.get_pending_migrations.return_value = [
                        Path("db/migrations/001_init.py"),
                        Path("db/migrations/002_add_users.py"),
                    ]
                    mock_migrator.find_migration_files.return_value = [
                        Path("db/migrations/001_init.py"),
                        Path("db/migrations/002_add_users.py"),
                    ]

                    # Mock migration module loading
                    with patch("confiture.core.connection.load_migration_module") as mock_load:
                        with patch("confiture.core.connection.get_migration_class") as mock_get_class:
                            # Setup migration mock
                            mock_migration = MagicMock()
                            mock_migration.version = "001"
                            mock_migration.name = "init"

                            mock_class = MagicMock(return_value=mock_migration)
                            mock_get_class.return_value = mock_class
                            mock_load.return_value = MagicMock()

                            # Execute
                            result = runner.invoke(
                                app,
                                ["migrate", "up", "--dry-run"],
                                catch_exceptions=False,
                            )

                            # Assert
                            assert result.exit_code == 0, f"Exit code: {result.exit_code}, Output: {result.stdout}"
                            assert "Migration Analysis Summary" in result.stdout
                            # apply() should NOT be called
                            mock_migrator.apply.assert_not_called()
                            # Connection should be closed
                            mock_conn.close.assert_called()

    def test_migrate_up_dry_run_json_format(self):
        """Test --dry-run with JSON output format."""
        with patch("confiture.core.connection.create_connection") as mock_conn_factory:
            with patch("confiture.core.connection.load_config"):
                with patch("confiture.core.migrator.Migrator") as mock_migrator_class:
                    mock_conn = MagicMock()
                    mock_conn_factory.return_value = mock_conn

                    mock_migrator = MagicMock()
                    mock_migrator_class.return_value = mock_migrator
                    mock_migrator.get_pending_migrations.return_value = [
                        Path("db/migrations/001_init.py"),
                    ]
                    mock_migrator.find_migration_files.return_value = [
                        Path("db/migrations/001_init.py"),
                    ]

                    with patch("confiture.core.connection.load_migration_module") as mock_load:
                        with patch("confiture.core.connection.get_migration_class") as mock_get_class:
                            mock_migration = MagicMock()
                            mock_migration.version = "001"
                            mock_migration.name = "init"

                            mock_class = MagicMock(return_value=mock_migration)
                            mock_get_class.return_value = mock_class
                            mock_load.return_value = MagicMock()

                            # Execute with JSON format
                            result = runner.invoke(
                                app,
                                ["migrate", "up", "--dry-run", "--format", "json"],
                                catch_exceptions=False,
                            )

                            # Assert
                            assert result.exit_code == 0
                            # Output contains JSON (may have other text before it)
                            # Extract JSON from output (it starts with {)
                            output_lines = result.stdout.strip().split("\n")
                            json_start = None
                            for i, line in enumerate(output_lines):
                                if line.startswith("{"):
                                    json_start = i
                                    break
                            assert json_start is not None, f"No JSON found in output: {result.stdout}"
                            json_str = "\n".join(output_lines[json_start:])
                            output_json = json.loads(json_str)
                            assert "migration_id" in output_json
                            assert "migrations" in output_json
                            assert "summary" in output_json
                            # Should have migration structure (may be empty due to mocking)
                            assert isinstance(output_json["migrations"], list)
                            assert isinstance(output_json["summary"], dict)
                            assert "unsafe_count" in output_json["summary"]

    def test_migrate_up_dry_run_saves_to_file(self):
        """Test --dry-run saves report to file with --output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "report.txt"

            with patch("confiture.core.connection.create_connection") as mock_conn_factory:
                with patch("confiture.core.connection.load_config"):
                    with patch("confiture.core.migrator.Migrator") as mock_migrator_class:
                        mock_conn = MagicMock()
                        mock_conn_factory.return_value = mock_conn

                        mock_migrator = MagicMock()
                        mock_migrator_class.return_value = mock_migrator
                        mock_migrator.get_pending_migrations.return_value = [
                            Path("db/migrations/001_init.py"),
                        ]
                        mock_migrator.find_migration_files.return_value = [
                            Path("db/migrations/001_init.py"),
                        ]

                        with patch("confiture.core.connection.load_migration_module") as mock_load:
                            with patch("confiture.core.connection.get_migration_class") as mock_get_class:
                                mock_migration = MagicMock()
                                mock_migration.version = "001"
                                mock_migration.name = "init"

                                mock_class = MagicMock(return_value=mock_migration)
                                mock_get_class.return_value = mock_class
                                mock_load.return_value = MagicMock()

                                # Execute with output file
                                result = runner.invoke(
                                    app,
                                    ["migrate", "up", "--dry-run", "--output", str(output_file)],
                                    catch_exceptions=False,
                                )

                                # Assert
                                assert result.exit_code == 0
                                assert output_file.exists(), f"File not created: {output_file}"
                                report_content = output_file.read_text()
                                assert "DRY-RUN MIGRATION ANALYSIS REPORT" in report_content

    def test_migrate_up_dry_run_execute_with_confirmation(self):
        """Test --dry-run-execute shows analysis then executes with confirmation."""
        with patch("confiture.core.connection.create_connection") as mock_conn_factory:
            with patch("confiture.core.connection.load_config"):
                with patch("confiture.core.migrator.Migrator") as mock_migrator_class:
                    mock_conn = MagicMock()
                    mock_conn_factory.return_value = mock_conn

                    mock_migrator = MagicMock()
                    mock_migrator_class.return_value = mock_migrator
                    mock_migrator.get_pending_migrations.return_value = [
                        Path("db/migrations/001_init.py"),
                    ]
                    mock_migrator.find_migration_files.return_value = [
                        Path("db/migrations/001_init.py"),
                    ]

                    with patch("confiture.core.connection.load_migration_module") as mock_load:
                        with patch("confiture.core.connection.get_migration_class") as mock_get_class:
                            mock_migration = MagicMock()
                            mock_migration.version = "001"
                            mock_migration.name = "init"

                            mock_class = MagicMock(return_value=mock_migration)
                            mock_get_class.return_value = mock_class
                            mock_load.return_value = MagicMock()

                            # Execute with user confirmation 'y'
                            result = runner.invoke(
                                app,
                                ["migrate", "up", "--dry-run-execute"],
                                input="y\n",
                                catch_exceptions=False,
                            )

                            # Assert
                            assert result.exit_code == 0
                            # Should show analysis first
                            assert "Migration Analysis Summary" in result.stdout
                            # Should ask for confirmation
                            assert "Proceed with real execution" in result.stdout


class TestMigrateDownDryRun:
    """Tests for migrate down --dry-run functionality."""

    def test_migrate_down_dry_run_analyzes_without_rollback(self):
        """Test that --dry-run analyzes rollback without executing it."""
        with patch("confiture.core.connection.create_connection") as mock_conn_factory:
            with patch("confiture.core.connection.load_config"):
                with patch("confiture.core.migrator.Migrator") as mock_migrator_class:
                    mock_conn = MagicMock()
                    mock_conn_factory.return_value = mock_conn

                    mock_migrator = MagicMock()
                    mock_migrator_class.return_value = mock_migrator
                    mock_migrator.get_applied_versions.return_value = ["001", "002"]
                    mock_migrator.find_migration_files.return_value = [
                        Path("db/migrations/001_init.py"),
                        Path("db/migrations/002_add_users.py"),
                    ]

                    with patch("confiture.core.connection.load_migration_module") as mock_load:
                        with patch("confiture.core.connection.get_migration_class") as mock_get_class:
                            mock_migration = MagicMock()
                            mock_migration.version = "002"
                            mock_migration.name = "add_users"

                            mock_class = MagicMock(return_value=mock_migration)
                            mock_get_class.return_value = mock_class
                            mock_load.return_value = MagicMock()

                            # Execute
                            result = runner.invoke(
                                app,
                                ["migrate", "down", "--dry-run", "--steps", "1"],
                                catch_exceptions=False,
                            )

                            # Assert
                            assert result.exit_code == 0
                            assert "Rollback Analysis Summary" in result.stdout
                            # rollback() should NOT be called
                            mock_migrator.rollback.assert_not_called()
                            # Connection should be closed
                            mock_conn.close.assert_called()

    def test_migrate_down_dry_run_json_format(self):
        """Test --dry-run with JSON format for migrate down."""
        with patch("confiture.core.connection.create_connection") as mock_conn_factory:
            with patch("confiture.core.connection.load_config"):
                with patch("confiture.core.migrator.Migrator") as mock_migrator_class:
                    mock_conn = MagicMock()
                    mock_conn_factory.return_value = mock_conn

                    mock_migrator = MagicMock()
                    mock_migrator_class.return_value = mock_migrator
                    mock_migrator.get_applied_versions.return_value = ["001"]
                    mock_migrator.find_migration_files.return_value = [
                        Path("db/migrations/001_init.py"),
                    ]

                    with patch("confiture.core.connection.load_migration_module") as mock_load:
                        with patch("confiture.core.connection.get_migration_class") as mock_get_class:
                            mock_migration = MagicMock()
                            mock_migration.version = "001"
                            mock_migration.name = "init"

                            mock_class = MagicMock(return_value=mock_migration)
                            mock_get_class.return_value = mock_class
                            mock_load.return_value = MagicMock()

                            # Execute with JSON format
                            result = runner.invoke(
                                app,
                                ["migrate", "down", "--dry-run", "--format", "json"],
                                catch_exceptions=False,
                            )

                            # Assert
                            assert result.exit_code == 0
                            # Extract JSON from output (it starts with {)
                            output_lines = result.stdout.strip().split("\n")
                            json_start = None
                            for i, line in enumerate(output_lines):
                                if line.startswith("{"):
                                    json_start = i
                                    break
                            assert json_start is not None, f"No JSON found in output: {result.stdout}"
                            json_str = "\n".join(output_lines[json_start:])
                            output_json = json.loads(json_str)
                            assert "migration_id" in output_json
                            assert "dry_run_rollback" in output_json["migration_id"]


class TestDryRunValidation:
    """Tests for dry-run flag validation."""

    def test_dry_run_and_dry_run_execute_mutually_exclusive(self):
        """Test that --dry-run and --dry-run-execute cannot be used together."""
        result = runner.invoke(
            app,
            ["migrate", "up", "--dry-run", "--dry-run-execute"],
            catch_exceptions=False,
        )

        # Should fail
        assert result.exit_code == 1
        assert "Cannot use both --dry-run and --dry-run-execute" in result.stdout

    def test_dry_run_with_force_not_allowed(self):
        """Test that --dry-run and --force cannot be used together."""
        result = runner.invoke(
            app,
            ["migrate", "up", "--dry-run", "--force"],
            catch_exceptions=False,
        )

        # Should fail
        assert result.exit_code == 1
        assert "Cannot use --dry-run with --force" in result.stdout

    def test_invalid_format_option(self):
        """Test that invalid format option is rejected."""
        result = runner.invoke(
            app,
            ["migrate", "up", "--dry-run", "--format", "csv"],
            catch_exceptions=False,
        )

        # Should fail
        assert result.exit_code == 1
        assert "Invalid format 'csv'" in result.stdout

    def test_migrate_down_invalid_format(self):
        """Test that invalid format is rejected in migrate down."""
        result = runner.invoke(
            app,
            ["migrate", "down", "--dry-run", "--format", "xml"],
            catch_exceptions=False,
        )

        # Should fail
        assert result.exit_code == 1
        assert "Invalid format 'xml'" in result.stdout


class TestDryRunExecution:
    """Tests for dry-run execution behavior."""

    def test_migrate_up_dry_run_execute_user_cancels(self):
        """Test that --dry-run-execute doesn't execute when user cancels."""
        with patch("confiture.core.connection.create_connection") as mock_conn_factory:
            with patch("confiture.core.connection.load_config"):
                with patch("confiture.core.migrator.Migrator") as mock_migrator_class:
                    mock_conn = MagicMock()
                    mock_conn_factory.return_value = mock_conn

                    mock_migrator = MagicMock()
                    mock_migrator_class.return_value = mock_migrator
                    mock_migrator.get_pending_migrations.return_value = [
                        Path("db/migrations/001_init.py"),
                    ]
                    mock_migrator.find_migration_files.return_value = [
                        Path("db/migrations/001_init.py"),
                    ]

                    with patch("confiture.core.connection.load_migration_module") as mock_load:
                        with patch("confiture.core.connection.get_migration_class") as mock_get_class:
                            mock_migration = MagicMock()
                            mock_migration.version = "001"
                            mock_migration.name = "init"

                            mock_class = MagicMock(return_value=mock_migration)
                            mock_get_class.return_value = mock_class
                            mock_load.return_value = MagicMock()

                            # Execute with user cancellation 'n'
                            result = runner.invoke(
                                app,
                                ["migrate", "up", "--dry-run-execute"],
                                input="n\n",
                                catch_exceptions=False,
                            )

                            # Assert
                            assert result.exit_code == 0
                            assert "Cancelled - no changes applied" in result.stdout
                            # apply() should NOT be called
                            mock_migrator.apply.assert_not_called()

    def test_migrate_up_no_pending_migrations_with_dry_run(self):
        """Test --dry-run when there are no pending migrations."""
        with patch("confiture.core.connection.create_connection") as mock_conn_factory:
            with patch("confiture.core.connection.load_config"):
                with patch("confiture.core.migrator.Migrator") as mock_migrator_class:
                    mock_conn = MagicMock()
                    mock_conn_factory.return_value = mock_conn

                    mock_migrator = MagicMock()
                    mock_migrator_class.return_value = mock_migrator
                    # No pending migrations
                    mock_migrator.get_pending_migrations.return_value = []

                    # Execute
                    result = runner.invoke(
                        app,
                        ["migrate", "up", "--dry-run"],
                        catch_exceptions=False,
                    )

                    # Assert
                    assert result.exit_code == 0
                    # Should show that 0 pending migrations found
                    assert "Found 0 pending migration(s)" in result.stdout
