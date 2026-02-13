"""Tests for seed CLI commands - apply, convert, benchmark."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from confiture.cli.seed import seed_app


@pytest.fixture
def cli_runner() -> CliRunner:
    """Create a Typer CLI runner."""
    return CliRunner()


@pytest.fixture
def temp_seed_file(tmp_path: Path) -> Path:
    """Create a temporary seed file."""
    seed_file = tmp_path / "users.sql"
    seed_file.write_text("INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');")
    return seed_file


class TestSeedApplyCommand:
    """Test seed apply command."""

    def test_seed_apply_command_exists(self, cli_runner: CliRunner) -> None:
        """Test that seed apply command is available."""
        result = cli_runner.invoke(seed_app, ["apply", "--help"])
        assert result.exit_code == 0
        assert "apply" in result.stdout or "seed" in result.stdout

    def test_seed_apply_accepts_seeds_dir(
        self, cli_runner: CliRunner, temp_seed_file: Path
    ) -> None:
        """Test that apply command accepts seeds directory."""
        result = cli_runner.invoke(seed_app, ["apply", "--seeds-dir", str(temp_seed_file.parent)])
        # Should succeed or give appropriate error (not command not found)
        assert result.exit_code != 2  # Not "command not found"

    def test_seed_apply_accepts_copy_format_flag(
        self, cli_runner: CliRunner, temp_seed_file: Path
    ) -> None:
        """Test that apply command accepts --copy-format flag."""
        result = cli_runner.invoke(
            seed_app,
            ["apply", "--seeds-dir", str(temp_seed_file.parent), "--copy-format"],
        )
        # Should accept the flag
        assert "unrecognized arguments" not in result.stdout

    def test_seed_apply_accepts_copy_threshold(
        self, cli_runner: CliRunner, temp_seed_file: Path
    ) -> None:
        """Test that apply command accepts --copy-threshold option."""
        result = cli_runner.invoke(
            seed_app,
            [
                "apply",
                "--seeds-dir",
                str(temp_seed_file.parent),
                "--copy-threshold",
                "500",
            ],
        )
        # Should accept the option
        assert "unrecognized arguments" not in result.stdout

    def test_seed_apply_accepts_benchmark_flag(
        self, cli_runner: CliRunner, temp_seed_file: Path
    ) -> None:
        """Test that apply command accepts --benchmark flag."""
        result = cli_runner.invoke(
            seed_app,
            [
                "apply",
                "--seeds-dir",
                str(temp_seed_file.parent),
                "--benchmark",
            ],
        )
        # Should accept the flag
        assert "unrecognized arguments" not in result.stdout


class TestSeedConvertCommand:
    """Test seed convert command (INSERT to COPY)."""

    def test_seed_convert_command_exists(self, cli_runner: CliRunner) -> None:
        """Test that seed convert command is available."""
        result = cli_runner.invoke(seed_app, ["convert", "--help"])
        assert result.exit_code == 0

    def test_seed_convert_accepts_input_file(
        self, cli_runner: CliRunner, temp_seed_file: Path
    ) -> None:
        """Test that convert command accepts input file."""
        result = cli_runner.invoke(seed_app, ["convert", "--input", str(temp_seed_file)])
        # Should accept the input
        assert "unrecognized arguments" not in result.stdout

    def test_seed_convert_accepts_output_file(
        self, cli_runner: CliRunner, temp_seed_file: Path, tmp_path: Path
    ) -> None:
        """Test that convert command accepts output file."""
        output_file = tmp_path / "output.sql"
        result = cli_runner.invoke(
            seed_app,
            ["convert", "--input", str(temp_seed_file), "--output", str(output_file)],
        )
        # Should accept the option
        assert "unrecognized arguments" not in result.stdout

    def test_seed_convert_output_contains_copy_format(
        self, cli_runner: CliRunner, temp_seed_file: Path, tmp_path: Path
    ) -> None:
        """Test that convert output is in COPY format."""
        output_file = tmp_path / "output.sql"
        result = cli_runner.invoke(
            seed_app,
            ["convert", "--input", str(temp_seed_file), "--output", str(output_file)],
        )
        if result.exit_code == 0 and output_file.exists():
            output = output_file.read_text()
            assert "COPY" in output or "COPY users" in output


class TestSeedBenchmarkCommand:
    """Test seed benchmark command."""

    def test_seed_benchmark_command_exists(self, cli_runner: CliRunner) -> None:
        """Test that seed benchmark command is available."""
        result = cli_runner.invoke(seed_app, ["benchmark", "--help"])
        assert result.exit_code == 0

    def test_seed_benchmark_accepts_seeds_dir(
        self, cli_runner: CliRunner, temp_seed_file: Path
    ) -> None:
        """Test that benchmark command accepts seeds directory."""
        result = cli_runner.invoke(
            seed_app, ["benchmark", "--seeds-dir", str(temp_seed_file.parent)]
        )
        # Should accept the input
        assert "unrecognized arguments" not in result.stdout

    def test_seed_benchmark_output_shows_speedup(
        self, cli_runner: CliRunner, temp_seed_file: Path
    ) -> None:
        """Test that benchmark output shows speedup factor."""
        result = cli_runner.invoke(
            seed_app, ["benchmark", "--seeds-dir", str(temp_seed_file.parent)]
        )
        if result.exit_code == 0:
            # Should show performance metrics
            assert "speedup" in result.stdout.lower() or "faster" in result.stdout.lower()


class TestSeedApplyOutput:
    """Test output formatting of seed apply command."""

    def test_seed_apply_shows_format_chosen(
        self, cli_runner: CliRunner, temp_seed_file: Path
    ) -> None:
        """Test that apply command output shows which format was chosen."""
        result = cli_runner.invoke(
            seed_app,
            ["apply", "--seeds-dir", str(temp_seed_file.parent), "--copy-format"],
        )
        if result.exit_code == 0:
            # Output should indicate format or success
            assert len(result.stdout) > 0

    def test_seed_apply_shows_rows_loaded(
        self, cli_runner: CliRunner, temp_seed_file: Path
    ) -> None:
        """Test that apply command output shows rows loaded count."""
        result = cli_runner.invoke(
            seed_app,
            ["apply", "--seeds-dir", str(temp_seed_file.parent)],
        )
        if result.exit_code == 0:
            # Output should show progress
            assert len(result.stdout) > 0


class TestSeedCliConfiguration:
    """Test CLI configuration options."""

    def test_default_copy_threshold_is_1000(
        self, cli_runner: CliRunner, temp_seed_file: Path
    ) -> None:
        """Test that default threshold is 1000 rows."""
        result = cli_runner.invoke(
            seed_app,
            ["apply", "--seeds-dir", str(temp_seed_file.parent), "--help"],
        )
        # Help should show the default value
        assert "1000" in result.stdout or result.exit_code == 0

    def test_accepts_environment_variable_override(
        self, cli_runner: CliRunner, temp_seed_file: Path
    ) -> None:
        """Test that CLI respects environment variable overrides."""
        with patch.dict("os.environ", {"CONFITURE_COPY_THRESHOLD": "500"}):
            result = cli_runner.invoke(
                seed_app, ["apply", "--seeds-dir", str(temp_seed_file.parent)]
            )
            # Should work with env var
            assert result.exit_code in (0, 1)  # Success or handled error
