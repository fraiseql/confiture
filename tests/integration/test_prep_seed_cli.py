"""Integration tests for prep-seed validation CLI.

Tests the end-to-end CLI experience including flag combinations,
output formats, and error handling.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app


@pytest.fixture
def cli_runner() -> CliRunner:
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_seeds_with_violations(tmp_path: Path) -> Path:
    """Create temporary seed files with known violations."""
    seeds_dir = tmp_path / "db" / "seeds" / "prep"
    seeds_dir.mkdir(parents=True)

    # File with schema target violation (Level 1)
    (seeds_dir / "01_invalid_target.sql").write_text(
        "INSERT INTO catalog.tb_x (id, name) VALUES ('550e8400-e29b-41d4-a716-446655440000', 'test');"
    )

    # File with valid schema target
    (seeds_dir / "02_valid_target.sql").write_text(
        "INSERT INTO prep_seed.tb_y (id, name) VALUES ('550e8400-e29b-41d4-a716-446655440001', 'test');"
    )

    return seeds_dir


@pytest.fixture
def temp_schema_dir(tmp_path: Path) -> Path:
    """Create temporary schema directory."""
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True)

    # Create a simple table file
    (schema_dir / "tables.sql").write_text("CREATE TABLE tb_x (id UUID PRIMARY KEY);")

    # Create a simple resolver file
    (schema_dir / "fn_resolve_x.sql").write_text(
        "CREATE FUNCTION fn_resolve_x() AS $$ INSERT INTO prep_seed.tb_x VALUES (1); $$ LANGUAGE SQL;"
    )

    return schema_dir


class TestPrepSeedCLI:
    """Test prep-seed validation via CLI."""

    def test_help_shows_prep_seed_flags(self, cli_runner: CliRunner) -> None:
        """Test that help text includes prep-seed flags."""
        result = cli_runner.invoke(app, ["seed", "validate", "--help"])
        assert result.exit_code == 0
        assert "--prep-seed" in result.stdout
        assert "--level" in result.stdout or "-l" in result.stdout
        assert "--static-only" in result.stdout
        assert "--full-execution" in result.stdout

    def test_prep_seed_flag_enables_validation(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        temp_seeds_with_violations: Path,
        temp_schema_dir: Path,
    ) -> None:
        """Test that --prep-seed flag triggers new validation path."""
        # Change to temp directory
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            result = cli_runner.invoke(
                app,
                [
                    "seed",
                    "validate",
                    "--prep-seed",
                    "--level",
                    "1",
                    "--seeds-dir",
                    str(temp_seeds_with_violations),
                ],
            )

            # Should find violations
            assert result.exit_code != 0
            assert "Prep-Seed Validation Report" in result.stdout or "PREP_SEED" in result.stdout

        finally:
            os.chdir(original_cwd)

    def test_static_only_flag_limits_level(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        temp_seeds_with_violations: Path,
        temp_schema_dir: Path,
    ) -> None:
        """Test that --static-only runs only Levels 1-3."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            result = cli_runner.invoke(
                app,
                [
                    "seed",
                    "validate",
                    "--prep-seed",
                    "--static-only",
                    "--seeds-dir",
                    str(temp_seeds_with_violations),
                ],
            )

            # Should not require database URL
            assert "Database URL required" not in result.stdout

        finally:
            os.chdir(original_cwd)

    def test_full_execution_requires_database_url(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        temp_seeds_with_violations: Path,
        temp_schema_dir: Path,
    ) -> None:
        """Test that --full-execution requires --database-url."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            result = cli_runner.invoke(
                app,
                [
                    "seed",
                    "validate",
                    "--prep-seed",
                    "--full-execution",
                    "--seeds-dir",
                    str(temp_seeds_with_violations),
                ],
            )

            # Should error about missing database URL
            assert result.exit_code == 2
            assert "Database URL required" in result.stdout

        finally:
            os.chdir(original_cwd)

    def test_level_4_requires_database_url(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        temp_seeds_with_violations: Path,
    ) -> None:
        """Test that Level 4+ requires --database-url."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            result = cli_runner.invoke(
                app,
                [
                    "seed",
                    "validate",
                    "--prep-seed",
                    "--level",
                    "4",
                    "--seeds-dir",
                    str(temp_seeds_with_violations),
                ],
            )

            # Should error about missing database URL
            assert result.exit_code == 2
            assert "Database URL required" in result.stdout

        finally:
            os.chdir(original_cwd)

    def test_json_output_format(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        temp_seeds_with_violations: Path,
    ) -> None:
        """Test JSON output format."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            result = cli_runner.invoke(
                app,
                [
                    "seed",
                    "validate",
                    "--prep-seed",
                    "--level",
                    "1",
                    "--format",
                    "json",
                    "--seeds-dir",
                    str(temp_seeds_with_violations),
                ],
            )

            # Should output valid JSON
            try:
                json_output = json.loads(result.stdout)
                assert "violations" in json_output
                assert "violation_count" in json_output
                assert "files_scanned" in json_output
            except json.JSONDecodeError as e:
                pytest.fail(f"Invalid JSON output: {e}")

        finally:
            os.chdir(original_cwd)

    def test_json_output_to_file(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        temp_seeds_with_violations: Path,
    ) -> None:
        """Test JSON output to file."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            output_file = tmp_path / "report.json"

            cli_runner.invoke(
                app,
                [
                    "seed",
                    "validate",
                    "--prep-seed",
                    "--level",
                    "1",
                    "--format",
                    "json",
                    "--output",
                    str(output_file),
                    "--seeds-dir",
                    str(temp_seeds_with_violations),
                ],
            )

            # Should create file
            assert output_file.exists()
            json_content = json.loads(output_file.read_text())
            assert "violations" in json_content

        finally:
            os.chdir(original_cwd)

    def test_exit_code_0_no_violations(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Test exit code 0 when no violations found."""
        import os

        original_cwd = os.getcwd()
        try:
            # Create clean seeds directory
            seeds_dir = tmp_path / "db" / "seeds" / "prep"
            seeds_dir.mkdir(parents=True)
            (seeds_dir / "clean.sql").write_text(
                "INSERT INTO prep_seed.tb_x (id) VALUES ('550e8400-e29b-41d4-a716-446655440000');"
            )

            os.chdir(tmp_path)

            result = cli_runner.invoke(
                app,
                [
                    "seed",
                    "validate",
                    "--prep-seed",
                    "--level",
                    "1",
                    "--seeds-dir",
                    str(seeds_dir),
                ],
            )

            # Should exit successfully
            assert result.exit_code == 0
            assert "passed" in result.stdout.lower() or "no violations" in result.stdout.lower()

        finally:
            os.chdir(original_cwd)

    def test_exit_code_1_violations(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        temp_seeds_with_violations: Path,
    ) -> None:
        """Test exit code 1 when violations found."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            result = cli_runner.invoke(
                app,
                [
                    "seed",
                    "validate",
                    "--prep-seed",
                    "--level",
                    "1",
                    "--seeds-dir",
                    str(temp_seeds_with_violations),
                ],
            )

            # Should exit with violation code
            assert result.exit_code == 1

        finally:
            os.chdir(original_cwd)

    def test_exit_code_2_error(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Test exit code 2 on configuration error."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            result = cli_runner.invoke(
                app,
                [
                    "seed",
                    "validate",
                    "--prep-seed",
                    "--level",
                    "4",
                    "--seeds-dir",
                    str(tmp_path / "nonexistent"),
                ],
            )

            # Should exit with error code
            assert result.exit_code == 2

        finally:
            os.chdir(original_cwd)

    def test_csv_output_format(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        temp_seeds_with_violations: Path,
    ) -> None:
        """Test CSV output format."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            result = cli_runner.invoke(
                app,
                [
                    "seed",
                    "validate",
                    "--prep-seed",
                    "--level",
                    "1",
                    "--format",
                    "csv",
                    "--seeds-dir",
                    str(temp_seeds_with_violations),
                ],
            )

            # Should output CSV format
            assert "File" in result.stdout
            assert "Line" in result.stdout
            assert "Severity" in result.stdout

        finally:
            os.chdir(original_cwd)

    def test_multiple_seed_files_scanned(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Test that multiple seed files are scanned."""
        import os

        original_cwd = os.getcwd()
        try:
            seeds_dir = tmp_path / "db" / "seeds" / "prep"
            seeds_dir.mkdir(parents=True)

            # Create multiple files
            for i in range(3):
                (seeds_dir / f"seed_{i}.sql").write_text(
                    f"INSERT INTO prep_seed.tb_x (id) VALUES ('550e8400-e29b-41d4-a716-44665544000{i}');"
                )

            os.chdir(tmp_path)

            result = cli_runner.invoke(
                app,
                [
                    "seed",
                    "validate",
                    "--prep-seed",
                    "--level",
                    "1",
                    "--seeds-dir",
                    str(seeds_dir),
                ],
            )

            # Should report files scanned
            assert "Files scanned: 3" in result.stdout

        finally:
            os.chdir(original_cwd)
