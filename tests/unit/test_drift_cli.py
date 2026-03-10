"""Tests for drift CLI command and public API."""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


class TestDriftPublicApi:
    """Tests that drift classes are importable from the top-level public API."""

    def test_drift_importable_from_public_api(self):
        """SchemaDriftDetector and DriftReport should be importable from confiture."""
        from confiture import DriftItem, DriftReport, DriftSeverity, DriftType, SchemaDriftDetector

        assert SchemaDriftDetector is not None
        assert DriftReport is not None
        assert DriftItem is not None
        assert DriftType is not None
        assert DriftSeverity is not None


class TestDriftCommand:
    """Tests for the `confiture drift` CLI command."""

    def _make_no_drift_report(self):
        """Build a mock DriftReport with no drift."""
        from confiture.core.drift import DriftReport

        return DriftReport(
            database_name="test_db",
            expected_schema_source="file:schema.sql",
            drift_items=[],
            tables_checked=3,
            columns_checked=10,
            indexes_checked=2,
            detection_time_ms=5,
        )

    def _make_critical_drift_report(self):
        """Build a mock DriftReport with critical drift."""
        from confiture.core.drift import DriftItem, DriftReport, DriftSeverity, DriftType

        item = DriftItem(
            drift_type=DriftType.MISSING_TABLE,
            severity=DriftSeverity.CRITICAL,
            object_name="users",
            expected="users",
            actual=None,
            message="Table 'users' is missing from database",
        )
        return DriftReport(
            database_name="test_db",
            expected_schema_source="file:schema.sql",
            drift_items=[item],
            tables_checked=0,
            columns_checked=0,
            indexes_checked=0,
            detection_time_ms=3,
        )

    @patch("confiture.cli.commands.drift.create_connection")
    @patch("confiture.cli.commands.drift.load_config")
    @patch("confiture.cli.commands.drift.SchemaDriftDetector")
    def test_drift_command_no_drift(
        self, mock_detector_class, mock_load_config, mock_create_connection, tmp_path
    ):
        """Should exit 0 and print success message when no drift detected."""
        # Create a temporary config and schema file so path checks pass
        config_file = tmp_path / "confiture.yaml"
        config_file.write_text("database_url: postgresql://localhost/test\n")
        schema_file = tmp_path / "schema.sql"
        schema_file.write_text("CREATE TABLE users (id SERIAL PRIMARY KEY);")

        mock_load_config.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_create_connection.return_value = mock_conn

        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_detector.compare_with_schema_file.return_value = self._make_no_drift_report()

        result = runner.invoke(
            app,
            [
                "drift",
                "--config",
                str(config_file),
                "--schema",
                str(schema_file),
            ],
        )

        assert result.exit_code == 0
        assert "No schema drift detected" in result.stdout

    @patch("confiture.cli.commands.drift.create_connection")
    @patch("confiture.cli.commands.drift.load_config")
    @patch("confiture.cli.commands.drift.SchemaDriftDetector")
    def test_drift_command_critical_drift_exits_1(
        self, mock_detector_class, mock_load_config, mock_create_connection, tmp_path
    ):
        """Should exit 1 when critical drift is detected."""
        config_file = tmp_path / "confiture.yaml"
        config_file.write_text("database_url: postgresql://localhost/test\n")
        schema_file = tmp_path / "schema.sql"
        schema_file.write_text("CREATE TABLE users (id SERIAL PRIMARY KEY);")

        mock_load_config.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_create_connection.return_value = mock_conn

        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_detector.compare_with_schema_file.return_value = self._make_critical_drift_report()

        result = runner.invoke(
            app,
            [
                "drift",
                "--config",
                str(config_file),
                "--schema",
                str(schema_file),
            ],
        )

        assert result.exit_code == 1
        assert "Schema drift detected" in result.stdout

    @patch("confiture.cli.commands.drift.create_connection")
    @patch("confiture.cli.commands.drift.load_config")
    @patch("confiture.cli.commands.drift.SchemaDriftDetector")
    def test_drift_command_json_output(
        self, mock_detector_class, mock_load_config, mock_create_connection, tmp_path
    ):
        """Should output valid JSON with expected keys when --format json."""
        config_file = tmp_path / "confiture.yaml"
        config_file.write_text("database_url: postgresql://localhost/test\n")
        schema_file = tmp_path / "schema.sql"
        schema_file.write_text("CREATE TABLE users (id SERIAL PRIMARY KEY);")

        mock_load_config.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_create_connection.return_value = mock_conn

        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_detector.compare_with_schema_file.return_value = self._make_no_drift_report()

        result = runner.invoke(
            app,
            [
                "drift",
                "--config",
                str(config_file),
                "--schema",
                str(schema_file),
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "has_drift" in data
        assert "database_name" in data
        assert "drift_items" in data
        assert data["has_drift"] is False

    def test_drift_command_missing_schema_flag_exits_2(self, tmp_path):
        """Should exit 2 with error message when --schema is not provided."""
        config_file = tmp_path / "confiture.yaml"
        config_file.write_text("database_url: postgresql://localhost/test\n")

        result = runner.invoke(
            app,
            [
                "drift",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 2

    def test_drift_command_missing_config_exits_2(self, tmp_path):
        """Should exit 2 with error message when config file does not exist."""
        schema_file = tmp_path / "schema.sql"
        schema_file.write_text("CREATE TABLE users (id SERIAL PRIMARY KEY);")

        result = runner.invoke(
            app,
            [
                "drift",
                "--config",
                str(tmp_path / "nonexistent.yaml"),
                "--schema",
                str(schema_file),
            ],
        )

        assert result.exit_code == 2


class TestMigrateValidateCheckLiveDrift:
    """Tests for --check-live-drift flag on migrate validate."""

    @patch("confiture.cli.commands.migrate_analysis.SchemaDriftDetector")
    @patch("confiture.cli.commands.migrate_analysis.create_connection")
    @patch("confiture.cli.commands.migrate_analysis.load_config")
    def test_validate_check_live_drift_flag(
        self, mock_load_config, mock_create_connection, mock_detector_class, tmp_path
    ):
        """SchemaDriftDetector should be called when --check-live-drift is used."""
        config_file = tmp_path / "confiture.yaml"
        config_file.write_text("database_url: postgresql://localhost/test\n")
        schema_file = tmp_path / "schema.sql"
        schema_file.write_text("CREATE TABLE users (id SERIAL PRIMARY KEY);")

        mock_load_config.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_create_connection.return_value = mock_conn

        from confiture.core.drift import DriftReport

        no_drift_report = DriftReport(
            database_name="test_db",
            expected_schema_source=f"file:{schema_file}",
            drift_items=[],
            tables_checked=1,
            columns_checked=1,
            indexes_checked=0,
            detection_time_ms=2,
        )

        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        mock_detector.compare_with_schema_file.return_value = no_drift_report

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--check-live-drift",
                "--config",
                str(config_file),
                "--schema",
                str(schema_file),
            ],
        )

        assert result.exit_code == 0
        mock_detector_class.assert_called_once_with(mock_conn)
        mock_detector.compare_with_schema_file.assert_called_once_with(str(schema_file))
