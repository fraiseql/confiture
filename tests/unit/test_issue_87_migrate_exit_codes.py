"""Tests for Issue #87: Differentiate exit codes for retriable vs fatal errors.

Exit code contract for migrate up / migrate down:
    0  Success.
    1  Generic/unknown error.
    2  Validation or configuration error (bad flags, missing config).
    3  Migration execution error (SQL failure, duplicate versions).
    6  Lock/pool error (retriable — another process holds the lock).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(config_dir: Path) -> Path:
    config_file = config_dir / "test.yaml"
    config_file.write_text("name: test\ndatabase_url: postgresql://localhost/test_db\n")
    return config_file


def _write_migrations(migrations_dir: Path, count: int = 3) -> None:
    migrations_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        (migrations_dir / f"00{i}_migration_{i}.up.sql").write_text(f"-- migration {i}\nSELECT 1;")


def _make_env(tracking_table: str = "tb_confiture"):
    from confiture.config.environment import Environment

    return Environment.model_validate(
        {
            "name": "test",
            "database_url": "postgresql://localhost/test_db",
            "include_dirs": ["db/schema"],
            "migration": {"tracking_table": tracking_table},
        }
    )


def _make_migrator_mock(
    *,
    tracking_table_exists: bool = True,
    applied_versions: list[str] | None = None,
    pending_files: list[Path] | None = None,
) -> MagicMock:
    mock = MagicMock()
    mock.tracking_table_exists.return_value = tracking_table_exists
    mock.initialize.return_value = None
    mock.get_applied_versions.return_value = applied_versions or []
    mock.get_applied_migrations_with_timestamps.return_value = []
    mock.find_migration_files.return_value = []
    mock.find_pending.return_value = pending_files or []
    return mock


# ---------------------------------------------------------------------------
# migrate up — Validation errors → exit 2
# ---------------------------------------------------------------------------


class TestMigrateUpValidationExitCodes:
    """Validation / configuration errors should exit 2."""

    def test_conflicting_dry_run_flags_exits_2(self, tmp_path):
        """--dry-run + --dry-run-execute → exit 2."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir)

        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
                "--dry-run",
                "--dry-run-execute",
            ],
        )
        assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}"

    def test_dry_run_with_force_exits_2(self, tmp_path):
        """--dry-run + --force → exit 2."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir)

        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
                "--dry-run",
                "--force",
            ],
        )
        assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}"

    def test_invalid_format_exits_2(self, tmp_path):
        """Invalid --format value → exit 2."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir)

        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "xml",
            ],
        )
        assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}"

    def test_invalid_checksum_mismatch_exits_2(self, tmp_path):
        """Invalid --on-checksum-mismatch value → exit 2."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir)

        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
                "--on-checksum-mismatch",
                "crash",
            ],
        )
        assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}"


# ---------------------------------------------------------------------------
# migrate up — Duplicate versions → exit 3
# ---------------------------------------------------------------------------


class TestMigrateUpDuplicateVersionsExitCode:
    """Duplicate migration versions should already exit 3 (no change needed)."""

    def test_duplicate_versions_exits_3(self, tmp_path):
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        # Two files with the same version prefix
        (migrations_dir / "001_first.up.sql").write_text("SELECT 1;")
        (migrations_dir / "001_second.up.sql").write_text("SELECT 2;")

        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
            ],
        )
        assert result.exit_code == 3, f"Expected exit 3, got {result.exit_code}"


# ---------------------------------------------------------------------------
# migrate up — Lock acquisition error → exit 6
# ---------------------------------------------------------------------------


class TestMigrateUpLockExitCodes:
    """Lock errors should exit 6 (retriable)."""

    def test_lock_timeout_exits_6(self, tmp_path):
        """LockAcquisitionError with timeout → exit 6."""
        from confiture.core.locking import LockAcquisitionError

        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        mock_migrator = _make_migrator_mock(
            tracking_table_exists=True,
            applied_versions=["001"],
        )
        # Make find_pending return a file so we actually reach lock acquisition
        mock_migrator.find_pending.return_value = [migrations_dir / "002_migration_2.up.sql"]
        mock_migrator.find_migration_files.return_value = [
            migrations_dir / "001_migration_1.up.sql",
            migrations_dir / "002_migration_2.up.sql",
        ]

        mock_conn = MagicMock()

        lock_error = LockAcquisitionError("Could not acquire lock", timeout=5000)

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=mock_conn),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
            patch(
                "confiture.core.locking.MigrationLock.acquire",
                side_effect=lock_error,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "up",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 6, f"Expected exit 6, got {result.exit_code}"

    def test_lock_held_exits_6(self, tmp_path):
        """LockAcquisitionError without timeout → exit 6."""
        from confiture.core.locking import LockAcquisitionError

        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        mock_migrator = _make_migrator_mock(
            tracking_table_exists=True,
            applied_versions=["001"],
        )
        mock_migrator.find_pending.return_value = [migrations_dir / "002_migration_2.up.sql"]
        mock_migrator.find_migration_files.return_value = [
            migrations_dir / "001_migration_1.up.sql",
            migrations_dir / "002_migration_2.up.sql",
        ]

        mock_conn = MagicMock()

        lock_error = LockAcquisitionError("Lock already held")

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=mock_conn),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
            patch(
                "confiture.core.locking.MigrationLock.acquire",
                side_effect=lock_error,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "up",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 6, f"Expected exit 6, got {result.exit_code}"


# ---------------------------------------------------------------------------
# migrate up — Migration execution failure → exit 3
# ---------------------------------------------------------------------------


class TestMigrateUpMigrationFailure:
    """Failed migration SQL execution should exit 3."""

    def test_migration_execution_error_exits_3(self, tmp_path):
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        mock_migrator = _make_migrator_mock(
            tracking_table_exists=True,
            applied_versions=["001"],
        )
        pending_file = migrations_dir / "002_migration_2.up.sql"
        mock_migrator.find_pending.return_value = [pending_file]
        mock_migrator.find_migration_files.return_value = [
            migrations_dir / "001_migration_1.up.sql",
            pending_file,
        ]
        # apply() raises an exception for the migration
        mock_migrator.apply.side_effect = Exception("column 'foo' already exists")

        mock_conn = MagicMock()

        # Mock load_migration_class to return a class that produces a proper migration
        mock_migration = MagicMock()
        mock_migration.version = "002"
        mock_migration.name = "migration_2"
        mock_migration.strict_mode = False
        mock_migration_class = MagicMock(return_value=mock_migration)

        mock_lock = MagicMock()
        mock_lock.acquire.return_value.__enter__ = MagicMock()
        mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=mock_conn),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
            patch(
                "confiture.core.connection.load_migration_class", return_value=mock_migration_class
            ),
            patch("confiture.core.locking.MigrationLock", return_value=mock_lock),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "up",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 3, f"Expected exit 3, got {result.exit_code}"


# ---------------------------------------------------------------------------
# migrate up — Generic ConfiturError uses handle_cli_error
# ---------------------------------------------------------------------------


class TestMigrateUpGenericErrors:
    """Generic exceptions in outer catch should use handle_cli_error."""

    def test_confiture_error_uses_registry_exit_code(self, tmp_path):
        """ConfiturError with CONFIG error_code → exit 2."""
        from confiture.exceptions import ConfigurationError

        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir)

        with patch(
            "confiture.core.connection.load_config",
            side_effect=ConfigurationError("bad config", error_code="CONFIG_001"),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "up",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}"

    def test_unknown_exception_exits_1(self, tmp_path):
        """Non-ConfiturError → exit 1."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir)

        with patch(
            "confiture.core.connection.load_config",
            side_effect=RuntimeError("unexpected failure"),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "up",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}"


# ---------------------------------------------------------------------------
# migrate down — Validation errors → exit 2
# ---------------------------------------------------------------------------


class TestMigrateDownValidationExitCodes:
    """Validation errors in migrate down should exit 2."""

    def test_invalid_format_exits_2(self, tmp_path):
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir)

        result = runner.invoke(
            app,
            [
                "migrate",
                "down",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "xml",
            ],
        )
        assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}"


class TestMigrateDownGenericErrors:
    """Generic errors in migrate down outer catch should use handle_cli_error."""

    def test_confiture_error_uses_registry_exit_code(self, tmp_path):
        from confiture.exceptions import ConfigurationError

        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir)

        with patch(
            "confiture.core.connection.load_config",
            side_effect=ConfigurationError("bad config", error_code="CONFIG_001"),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "down",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}"


# ---------------------------------------------------------------------------
# migrate generate — Validation errors → exit 2
# ---------------------------------------------------------------------------


class TestMigrateGenerateValidationExitCodes:
    """Validation errors in migrate generate should exit 2."""

    def test_missing_from_to_with_generator_exits_2(self, tmp_path):
        """--generator without --from/--to → exit 2."""
        _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir)

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
                "--generator",
                "some_gen",
            ],
        )
        assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}"

    def test_generator_not_found_exits_2(self, tmp_path):
        """Generator not in config → exit 2."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir)

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
                "--config",
                str(config_file),
                "--generator",
                "nonexistent_gen",
                "--from",
                str(tmp_path / "old.sql"),
                "--to",
                str(tmp_path / "new.sql"),
            ],
        )
        assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}"
