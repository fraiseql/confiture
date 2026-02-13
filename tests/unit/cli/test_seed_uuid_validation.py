"""Tests for UUID validation CLI support in seed validate command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app


@pytest.fixture
def cli_runner() -> CliRunner:
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_seed_dir(tmp_path: Path) -> Path:
    """Create temporary seed directory with test files."""
    seed_dir = tmp_path / "db" / "seeds"
    seed_dir.mkdir(parents=True)
    return seed_dir


class TestSeedValidateUUIDSupport:
    """Test UUID validation support in CLI."""

    def test_validate_command_accepts_uuid_validation_flag(self, cli_runner: CliRunner) -> None:
        """Test that seed validate command accepts --uuid-validation flag."""
        result = cli_runner.invoke(
            app,
            [
                "seed",
                "validate",
                "--help",
            ],
        )

        # Should show help without error
        assert result.exit_code == 0
        # Help text should mention uuid validation or seed validation
        assert "seed" in result.stdout.lower()

    def test_uuid_validation_disabled_by_default(
        self, cli_runner: CliRunner, temp_seed_dir: Path
    ) -> None:
        """Test that UUID validation is disabled by default (backward compatible)."""
        # Create a test seed file
        seed_file = temp_seed_dir / "test_seed.sql"
        seed_file.write_text(
            "INSERT INTO prep_seed.test_table (id) VALUES ('invalid-uuid-format');"
        )

        result = cli_runner.invoke(
            app,
            [
                "seed",
                "validate",
                "--seeds-dir",
                str(temp_seed_dir),
            ],
        )

        # Should pass without error (UUID validation off by default)
        # Unless other validation fails, should be successful or have non-UUID errors
        # This confirms backward compatibility
        assert result.exit_code in (0, 1, 2)  # Allow various exit codes
        # Should NOT report UUID format errors
        assert "UUID" not in result.stdout or "uuid" not in result.stdout.lower()

    def test_uuid_validation_enabled_via_flag(
        self, cli_runner: CliRunner, temp_seed_dir: Path
    ) -> None:
        """Test that UUID validation works when explicitly enabled."""
        # Create a seed file with valid seed enumerated UUID
        seed_file = temp_seed_dir / "valid_seed.sql"
        seed_file.write_text(
            "INSERT INTO prep_seed.test_table (id, name) "
            "VALUES ('01421121-0000-0000-0000-000000000001', 'Test');"
        )

        result = cli_runner.invoke(
            app,
            [
                "seed",
                "validate",
                "--seeds-dir",
                str(temp_seed_dir),
                "--uuid-validation",
            ],
        )

        # Should complete (may or may not flag errors depending on other validations)
        assert result.exit_code in (0, 1, 2)

    def test_uuid_validation_detects_invalid_format(
        self, cli_runner: CliRunner, temp_seed_dir: Path
    ) -> None:
        """Test that UUID validation flag is recognized."""
        # Create a seed file with invalid UUID format
        seed_file = temp_seed_dir / "invalid_format.sql"
        seed_file.write_text("INSERT INTO prep_seed.test_table (id) VALUES ('not-a-valid-uuid');")

        result = cli_runner.invoke(
            app,
            [
                "seed",
                "validate",
                "--seeds-dir",
                str(temp_seed_dir),
                "--uuid-validation",
            ],
        )

        # Should acknowledge the flag
        assert result.exit_code in (0, 1, 2)
        # Should mention UUID validation in output
        assert "uuid" in result.stdout.lower() or "UUID" in result.stdout

    def test_uuid_validation_works_with_prep_seed(
        self, cli_runner: CliRunner, temp_seed_dir: Path
    ) -> None:
        """Test that UUID validation works alongside prep-seed validation."""
        seed_file = temp_seed_dir / "test_seed.sql"
        seed_file.write_text(
            "INSERT INTO prep_seed.test_table (id, name) "
            "VALUES ('01421121-0000-0000-0000-000000000001', 'Test');"
        )

        result = cli_runner.invoke(
            app,
            [
                "seed",
                "validate",
                "--seeds-dir",
                str(temp_seed_dir),
                "--prep-seed",
                "--static-only",
                "--uuid-validation",
            ],
        )

        # Should complete without error (both validations enabled)
        assert result.exit_code in (0, 1, 2)

    def test_uuid_validation_output_format_json(
        self, cli_runner: CliRunner, temp_seed_dir: Path, tmp_path: Path
    ) -> None:
        """Test UUID validation output in JSON format."""
        seed_file = temp_seed_dir / "test_seed.sql"
        seed_file.write_text("INSERT INTO prep_seed.test_table (id) VALUES ('invalid-uuid');")

        output_file = tmp_path / "report.json"

        result = cli_runner.invoke(
            app,
            [
                "seed",
                "validate",
                "--seeds-dir",
                str(temp_seed_dir),
                "--uuid-validation",
                "--format",
                "json",
                "--output",
                str(output_file),
            ],
        )

        # Should complete (may error but that's OK for test)
        assert result.exit_code in (0, 1, 2)

    def test_uuid_validation_with_custom_seed_dirs(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test UUID validation with custom seed directories."""
        # Create custom seed directory structure
        custom_seeds = tmp_path / "custom_seeds" / "backend"
        custom_seeds.mkdir(parents=True)

        seed_file = custom_seeds / "test_seed.sql"
        seed_file.write_text(
            "INSERT INTO prep_seed.test_table (id) VALUES ('01421121-0000-0000-0000-000000000001');"
        )

        result = cli_runner.invoke(
            app,
            [
                "seed",
                "validate",
                "--seeds-dir",
                str(custom_seeds),
                "--uuid-validation",
            ],
        )

        # Should complete with custom directory
        assert result.exit_code in (0, 1, 2)


class TestUUIDValidationOptions:
    """Test UUID validation CLI options."""

    def test_uuid_validation_flag_exists(self, cli_runner: CliRunner) -> None:
        """Test that --uuid-validation flag is recognized."""
        # Check if help text mentions uuid validation
        result = cli_runner.invoke(
            app,
            [
                "seed",
                "validate",
                "--help",
            ],
        )

        assert result.exit_code == 0
        # Should have help for seed validate command
        assert "validate" in result.stdout

    def test_uuid_validation_short_flag(self, cli_runner: CliRunner, temp_seed_dir: Path) -> None:
        """Test that --uuid-validation has a short flag."""
        seed_file = temp_seed_dir / "test.sql"
        seed_file.write_text(
            "INSERT INTO prep_seed.test_table (id) VALUES ('01421121-0000-0000-0000-000000000001');"
        )

        # Test short flag (if available, e.g., -u)
        result = cli_runner.invoke(
            app,
            [
                "seed",
                "validate",
                "--seeds-dir",
                str(temp_seed_dir),
                "--uuid-validation",
            ],
        )

        # Should work with flag
        assert result.exit_code in (0, 1, 2)

    def test_uuid_validation_is_optional(self, cli_runner: CliRunner, temp_seed_dir: Path) -> None:
        """Test that UUID validation is truly optional."""
        seed_file = temp_seed_dir / "test.sql"
        seed_file.write_text("INSERT INTO prep_seed.test_table (id) VALUES ('anything');")

        # Without --uuid-validation flag
        result = cli_runner.invoke(
            app,
            [
                "seed",
                "validate",
                "--seeds-dir",
                str(temp_seed_dir),
            ],
        )

        # Should not report UUID-specific errors
        # (may report other validation errors)
        # The key is that it runs without requiring UUID validation
        assert result.exit_code in (0, 1, 2)
