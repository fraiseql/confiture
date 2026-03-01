"""Tests for Phase 5: CLI command (confiture migrate rebuild)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.models.results import MigrateRebuildResult, MigrationApplied

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestRebuildCLIHelp:
    """Cycle 5.1: Basic CLI wiring."""

    def test_help_shows_all_options(self):
        result = runner.invoke(app, ["migrate", "rebuild", "--help"])
        assert result.exit_code == 0
        clean = _strip_ansi(result.output)
        assert "--drop-schemas" in clean
        assert "--seed" in clean
        assert "--backup-tracking" in clean
        assert "--verify" in clean
        assert "--config" in clean
        assert "--migrations-dir" in clean
        assert "--dry-run" in clean
        assert "--yes" in clean
        assert "--format" in clean


class TestRebuildPreFlight:
    """Cycle 5.2: Pre-flight validation."""

    def test_missing_config_exits_1(self):
        result = runner.invoke(
            app, ["migrate", "rebuild", "--config", "/nonexistent/config.yaml", "--yes"]
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Config" in result.output

    def test_missing_migrations_dir_exits_1(self, tmp_path: Path):
        config = tmp_path / "config.yaml"
        config.write_text("database_url: postgresql://localhost/test\n")
        result = runner.invoke(
            app,
            [
                "migrate",
                "rebuild",
                "--config",
                str(config),
                "--migrations-dir",
                "/nonexistent/migrations",
                "--yes",
            ],
        )
        assert result.exit_code == 1


def _make_env(tmp_path: Path) -> tuple[Path, Path]:
    """Create config file and migrations dir for CLI tests."""
    config = tmp_path / "config.yaml"
    config.write_text("database_url: postgresql://localhost/test\n")
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    return config, migrations


class TestRebuildExecution:
    """Cycle 5.3: Confirmation UX and execution."""

    def _mock_result(self, **kwargs):
        defaults = {
            "success": True,
            "schemas_dropped": ["public"],
            "ddl_statements_executed": 5,
            "migrations_marked": [
                MigrationApplied(version="001", name="create_users", execution_time_ms=0),
            ],
            "total_execution_time_ms": 200,
            "dry_run": False,
            "warnings": [],
        }
        defaults.update(kwargs)
        return MigrateRebuildResult(**defaults)

    @patch("confiture.core.migrator.Migrator.from_config")
    def test_dry_run_shows_banner(self, mock_from_config, tmp_path: Path):
        config, migrations = _make_env(tmp_path)
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.rebuild.return_value = self._mock_result(dry_run=True)
        mock_from_config.return_value = mock_session

        result = runner.invoke(
            app,
            [
                "migrate",
                "rebuild",
                "--config",
                str(config),
                "--migrations-dir",
                str(migrations),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "dry run" in result.output.lower()

    @patch("confiture.core.migrator.Migrator.from_config")
    def test_yes_skips_prompt(self, mock_from_config, tmp_path: Path):
        config, migrations = _make_env(tmp_path)
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.rebuild.return_value = self._mock_result()
        mock_from_config.return_value = mock_session

        result = runner.invoke(
            app,
            [
                "migrate",
                "rebuild",
                "--config",
                str(config),
                "--migrations-dir",
                str(migrations),
                "--yes",
            ],
        )
        assert result.exit_code == 0


class TestRebuildFormatter:
    """Cycle 5.4: Structured output formatter."""

    @patch("confiture.core.migrator.Migrator.from_config")
    def test_json_output(self, mock_from_config, tmp_path: Path):
        config, migrations = _make_env(tmp_path)
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.rebuild.return_value = MigrateRebuildResult(
            success=True,
            schemas_dropped=["public"],
            ddl_statements_executed=5,
            migrations_marked=[
                MigrationApplied(version="001", name="init", execution_time_ms=0),
            ],
            total_execution_time_ms=100,
            dry_run=False,
        )
        mock_from_config.return_value = mock_session

        result = runner.invoke(
            app,
            [
                "migrate",
                "rebuild",
                "--config",
                str(config),
                "--migrations-dir",
                str(migrations),
                "--yes",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        assert '"success": true' in result.output or '"success":true' in result.output


class TestRebuildExitCodes:
    """Cycle 5.5: Semantic exit codes."""

    @patch("confiture.core.migrator.Migrator.from_config")
    def test_success_exit_0(self, mock_from_config, tmp_path: Path):
        config, migrations = _make_env(tmp_path)
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.rebuild.return_value = MigrateRebuildResult(
            success=True,
            schemas_dropped=[],
            ddl_statements_executed=5,
            migrations_marked=[],
            total_execution_time_ms=100,
            dry_run=False,
        )
        mock_from_config.return_value = mock_session

        result = runner.invoke(
            app,
            [
                "migrate",
                "rebuild",
                "--config",
                str(config),
                "--migrations-dir",
                str(migrations),
                "--yes",
            ],
        )
        assert result.exit_code == 0

    @patch("confiture.core.migrator.Migrator.from_config")
    def test_fatal_error_exit_3(self, mock_from_config, tmp_path: Path):
        config, migrations = _make_env(tmp_path)
        mock_from_config.side_effect = Exception("connection refused")

        result = runner.invoke(
            app,
            [
                "migrate",
                "rebuild",
                "--config",
                str(config),
                "--migrations-dir",
                str(migrations),
                "--yes",
            ],
        )
        assert result.exit_code == 3
