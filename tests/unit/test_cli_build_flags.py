"""Unit tests for CLI build command flags.

These tests verify that comment validation and separator style flags
are properly parsed and applied to override environment configuration.
"""

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


class TestCommentValidationFlags:
    """Test comment validation CLI flags."""

    def test_validate_comments_flag_enables_validation(self, tmp_path):
        """--validate-comments should enable comment validation."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
build:
  validate_comments:
    enabled: false
""")

        # Run with --validate-comments to override
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--validate-comments",
            ],
        )

        # Should show configuration override
        assert "Comment validation: True" in result.stdout
        assert result.exit_code == 0

    def test_no_validate_comments_flag_disables_validation(self, tmp_path):
        """--no-validate-comments should disable comment validation."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
build:
  validate_comments:
    enabled: true
""")

        # Run with --no-validate-comments to override
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--no-validate-comments",
            ],
        )

        # Should show configuration override
        assert "Comment validation: False" in result.stdout
        assert result.exit_code == 0

    def test_fail_on_unclosed_flag(self, tmp_path):
        """--fail-on-unclosed should override fail_on_unclosed_blocks."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
build:
  validate_comments:
    enabled: true
    fail_on_unclosed_blocks: false
""")

        # Run with --fail-on-unclosed to override
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--fail-on-unclosed",
            ],
        )

        # Should show configuration override
        assert "Fail on unclosed blocks: True" in result.stdout
        assert result.exit_code == 0

    def test_fail_on_spillover_flag(self, tmp_path):
        """--fail-on-spillover should override fail_on_spillover."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
build:
  validate_comments:
    enabled: true
    fail_on_spillover: false
""")

        # Run with --fail-on-spillover to override
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--fail-on-spillover",
            ],
        )

        # Should show configuration override
        assert "Fail on spillover: True" in result.stdout
        assert result.exit_code == 0

    def test_multiple_validation_flags_combined(self, tmp_path):
        """Multiple validation flags should all be applied."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
build:
  validate_comments:
    enabled: false
    fail_on_unclosed_blocks: false
    fail_on_spillover: false
""")

        # Run with multiple flags
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--validate-comments",
                "--fail-on-unclosed",
                "--fail-on-spillover",
            ],
        )

        # All overrides should appear
        assert "Comment validation: True" in result.stdout
        assert "Fail on unclosed blocks: True" in result.stdout
        assert "Fail on spillover: True" in result.stdout
        assert result.exit_code == 0


class TestSeparatorStyleFlags:
    """Test separator style CLI flags."""

    def test_separator_style_block_comment(self, tmp_path):
        """--separator-style block_comment should set style."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
build:
  separators:
    style: line_comment
""")

        # Run with --separator-style
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--separator-style",
                "block_comment",
            ],
        )

        # Should show configuration override
        assert "Separator style: block_comment" in result.stdout
        assert result.exit_code == 0

    def test_separator_style_line_comment(self, tmp_path):
        """--separator-style line_comment should set style."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
build:
  separators:
    style: block_comment
""")

        # Run with --separator-style
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--separator-style",
                "line_comment",
            ],
        )

        # Should show configuration override
        assert "Separator style: line_comment" in result.stdout
        assert result.exit_code == 0

    def test_separator_style_invalid(self, tmp_path):
        """Invalid separator style should error."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
""")

        # Run with invalid style
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--separator-style",
                "invalid_style",
            ],
        )

        # Should fail with error message
        assert "Invalid separator style: invalid_style" in result.stdout
        assert result.exit_code == 1

    def test_separator_style_custom_requires_template(self, tmp_path):
        """--separator-style custom without --separator-template should error."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
build:
  separators:
    style: block_comment
""")

        # Run with custom style but no template
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--separator-style",
                "custom",
            ],
        )

        # Should fail
        assert "Custom separator style requires --separator-template" in result.stdout
        assert result.exit_code == 1

    def test_separator_style_custom_with_template(self, tmp_path):
        """--separator-style custom with --separator-template should work."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
build:
  separators:
    style: block_comment
""")

        # Run with custom style and template
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--separator-style",
                "custom",
                "--separator-template",
                "\\n/* FILE: {file_path} */\\n",
            ],
        )

        # Should show overrides and succeed
        assert "Separator style: custom" in result.stdout
        assert result.exit_code == 0

    def test_separator_template_without_style(self, tmp_path):
        """--separator-template alone should use custom style."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
build:
  separators:
    style: custom
    custom_template: "\\n/* {{file_path}} */\\n"
""")

        # Run with just --separator-template
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--separator-template",
                "\\n/* NEW: {file_path} */\\n",
            ],
        )

        # Should succeed and show override
        assert "Custom template:" in result.stdout
        assert result.exit_code == 0


class TestNoFlagsUseConfig:
    """Test that omitting flags uses environment config."""

    def test_no_flags_uses_env_config(self, tmp_path):
        """Without flags, should use environment config."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
build:
  validate_comments:
    enabled: true
  separators:
    style: block_comment
""")

        # Run without any override flags
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
            ],
        )

        # Should not show any overrides
        assert "Configuration overrides applied" not in result.stdout
        assert result.exit_code == 0

    def test_no_override_message_when_no_flags(self, tmp_path):
        """No override message should appear if no flags provided."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "01_test.sql").write_text("SELECT 1;")

        env_dir = tmp_path / "db" / "environments"
        env_dir.mkdir(parents=True)
        (env_dir / "local.yaml").write_text(f"""
name: local
database_url: "postgresql://localhost/test"
include_dirs:
  - {schema_dir}
""")

        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
            ],
        )

        assert "Configuration overrides applied:" not in result.stdout
        assert result.exit_code == 0
