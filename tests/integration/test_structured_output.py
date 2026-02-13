"""Integration tests for structured output feature.

Tests the build command with JSON/CSV output formats.
"""

import json

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app


@pytest.fixture
def runner():
    """Create a CLI test runner."""
    return CliRunner()


@pytest.fixture
def sample_project(tmp_path):
    """Create a minimal Confiture project structure for testing."""
    # Create schema directory
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True)

    # Create a simple schema file
    (schema_dir / "01_tables.sql").write_text(
        "CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(100));"
    )

    # Create environment config
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "local.yaml").write_text(
        "name: local\n"
        "database_url: postgresql://localhost/test\n"
        "include_dirs:\n"
        "  - db/schema\n"
    )

    # Create project config
    (tmp_path / "confiture.yaml").write_text(
        "project: test_project\n"
        "version: 1\n"
    )

    return tmp_path


class TestBuildJsonOutput:
    """Tests for build command with JSON output format."""

    def test_build_json_to_stdout(self, runner, sample_project):
        """Test build command outputs JSON to stdout."""
        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(sample_project),
            "--format", "json",
        ])

        # Should succeed
        assert result.exit_code == 0

        # Output should contain valid JSON (may have progress messages before it)
        # Extract JSON by finding the first '{' and last '}'
        stdout = result.stdout
        json_start = stdout.find('{')
        json_end = stdout.rfind('}') + 1

        try:
            json_str = stdout[json_start:json_end]
            data = json.loads(json_str)
            assert "success" in data
            assert data["success"] is True
            assert "files_processed" in data
            assert "schema_size_bytes" in data
        except json.JSONDecodeError:
            pytest.fail(f"Output does not contain valid JSON: {result.stdout}")

    def test_build_json_to_file(self, runner, sample_project):
        """Test build command saves JSON report to file."""
        output_file = sample_project / "build_report.json"

        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(sample_project),
            "--format", "json",
            "--report", str(output_file),
        ])

        # Should succeed
        assert result.exit_code == 0

        # Report file should exist
        assert output_file.exists()

        # Report should be valid JSON
        data = json.loads(output_file.read_text())
        assert data["success"] is True
        assert data["files_processed"] == 1
        assert "files_processed" in data

    def test_build_json_contains_metadata(self, runner, sample_project):
        """Test JSON output contains expected metadata."""
        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(sample_project),
            "--format", "json",
        ])

        assert result.exit_code == 0

        # Extract JSON from output
        stdout = result.stdout
        json_start = stdout.find('{')
        json_end = stdout.rfind('}') + 1
        json_str = stdout[json_start:json_end]
        data = json.loads(json_str)

        # Check expected fields
        assert "success" in data
        assert "files_processed" in data
        assert "schema_size_bytes" in data
        assert "output_path" in data
        assert "execution_time_ms" in data
        assert "seed_files_applied" in data


class TestBuildCsvOutput:
    """Tests for build command with CSV output format."""

    def test_build_csv_to_file(self, runner, sample_project):
        """Test build command saves CSV report to file."""
        output_file = sample_project / "build_metrics.csv"

        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(sample_project),
            "--format", "csv",
            "--report", str(output_file),
        ])

        # Should succeed
        assert result.exit_code == 0

        # Report file should exist
        assert output_file.exists()

        # Report should be valid CSV
        content = output_file.read_text()
        lines = content.strip().split("\n")

        # Should have header
        assert "metric,value" in lines[0]

        # Should have success row
        assert any("success,True" in line or "success,true" in line for line in lines)

    def test_build_csv_has_metrics(self, runner, sample_project):
        """Test CSV output contains key metrics."""
        output_file = sample_project / "metrics.csv"

        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(sample_project),
            "--format", "csv",
            "--report", str(output_file),
        ])

        assert result.exit_code == 0
        content = output_file.read_text()

        # Should contain metric rows
        assert "files_processed" in content
        assert "schema_size_bytes" in content
        assert "output_path" in content


class TestBuildTextOutput:
    """Tests for build command with default text output."""

    def test_build_text_default(self, runner, sample_project):
        """Test build command defaults to text format."""
        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(sample_project),
        ])

        # Should succeed
        assert result.exit_code == 0

        # Should contain Rich formatted output
        assert "✅" in result.stdout
        assert "Schema built successfully" in result.stdout

    def test_build_text_explicit(self, runner, sample_project):
        """Test build command with explicit text format."""
        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(sample_project),
            "--format", "text",
        ])

        assert result.exit_code == 0
        assert "✅" in result.stdout


class TestBuildFormatValidation:
    """Tests for format validation."""

    def test_build_invalid_format(self, runner, sample_project):
        """Test build command rejects invalid format."""
        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(sample_project),
            "--format", "invalid",
        ])

        # Should fail
        assert result.exit_code != 0
        assert "Invalid format" in result.stdout


class TestBuildWithShowHash:
    """Tests for build command with hash display and structured output."""

    def test_build_json_with_hash(self, runner, sample_project):
        """Test JSON output includes hash when --show-hash is used."""
        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(sample_project),
            "--format", "json",
            "--show-hash",
        ])

        assert result.exit_code == 0

        # Extract JSON from output
        stdout = result.stdout
        json_start = stdout.find('{')
        json_end = stdout.rfind('}') + 1
        json_str = stdout[json_start:json_end]
        data = json.loads(json_str)

        assert "hash" in data
        # Hash should be a non-empty string (or None is ok)
        assert data["hash"] is None or isinstance(data["hash"], str)


class TestBuildReportVsSchemaOutput:
    """Tests for distinguishing schema output from report output."""

    def test_build_creates_both_schema_and_json_report(self, runner, sample_project):
        """Test build creates schema file and separate JSON report."""
        schema_output = sample_project / "db" / "generated" / "schema_local.sql"
        report_output = sample_project / "build_report.json"

        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(sample_project),
            "--format", "json",
            "--report", str(report_output),
        ])

        assert result.exit_code == 0

        # Both files should exist
        assert schema_output.exists(), "Schema file should be created"
        assert report_output.exists(), "Report file should be created"

        # Schema file should contain SQL
        schema_content = schema_output.read_text()
        assert "CREATE TABLE" in schema_content

        # Report file should contain JSON
        report_content = json.loads(report_output.read_text())
        assert report_content["success"] is True
        assert "output_path" in report_content
