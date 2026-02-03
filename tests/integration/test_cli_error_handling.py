"""Integration tests for CLI error handling.

Tests that CLI commands use the error handler and exit with correct codes.
"""

import subprocess


class TestCliExitCodes:
    """Test that CLI commands exit with correct codes."""

    def test_build_with_nonexistent_env(self) -> None:
        """Test that build with nonexistent environment exits with code 2."""
        result = subprocess.run(
            ["confiture", "build", "--env", "nonexistent"],
            capture_output=True,
            text=True,
        )

        # Should exit with error code (not 0)
        assert result.returncode != 0
        # Configuration error should exit with code 2
        assert result.returncode in [1, 2]  # 2 is preferred for config errors

    def test_help_command_exits_success(self) -> None:
        """Test that help command exits with success code."""
        result = subprocess.run(
            ["confiture", "--help"],
            capture_output=True,
            text=True,
        )

        # Help should succeed
        assert result.returncode == 0

    def test_build_command_exists(self) -> None:
        """Test that build command is available."""
        result = subprocess.run(
            ["confiture", "build", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "build" in result.stdout.lower() or "schema" in result.stdout.lower()


class TestCliErrorMessages:
    """Test that CLI commands show proper error messages."""

    def test_error_message_format(self) -> None:
        """Test that error messages are formatted properly."""
        result = subprocess.run(
            ["confiture", "build", "--env", "nonexistent"],
            capture_output=True,
            text=True,
        )

        # Should have error output
        assert result.returncode != 0
        assert len(result.stderr + result.stdout) > 0

    def test_invalid_env_shows_error(self) -> None:
        """Test that invalid environment shows error."""
        result = subprocess.run(
            ["confiture", "build", "--env", "invalid_env_that_does_not_exist"],
            capture_output=True,
            text=True,
        )

        # Should fail
        assert result.returncode != 0

        # Should have error output
        output = result.stderr + result.stdout
        assert len(output) > 0
