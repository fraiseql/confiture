"""Tests for MigratorSession.up()."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.config.environment import Environment
from confiture.core.migrator import MigratorSession
from confiture.models.results import MigrateUpResult


def _make_env() -> Environment:
    return Environment.model_validate(
        {
            "name": "test",
            "database_url": "postgresql://localhost/test",
            "include_dirs": ["db/schema"],
            "migration": {"tracking_table": "tb_confiture"},
        }
    )


def _make_session(env: Environment, migrations_dir: Path) -> tuple[MigratorSession, MagicMock]:
    mock_conn = MagicMock()
    with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
        session = MigratorSession(env, migrations_dir)
        session.__enter__()
    return session, mock_conn


class TestMigratorSessionUpNoMigrations:
    def test_no_pending_returns_success_with_empty_applied(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_add_users.py").write_text("# migration")

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)
        session._migrator.initialize = MagicMock()
        session._migrator.find_pending = MagicMock(return_value=[])
        session._migrator.find_migration_files = MagicMock(
            return_value=[migrations_dir / "001_add_users.py"]
        )

        result = session.up()

        assert isinstance(result, MigrateUpResult)
        assert result.success is True
        assert result.migrations_applied == []

    def test_missing_migrations_dir_raises(self, tmp_path):
        env = _make_env()
        session, _ = _make_session(env, tmp_path / "nonexistent")

        with pytest.raises(Exception):
            session.up()


class TestMigratorSessionUpAppliesMigrations:
    def test_applies_pending_migrations(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        migration_file = migrations_dir / "001_add_users.py"
        migration_file.write_text("# migration")

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)

        mock_migration = MagicMock()
        mock_migration.version = "001"
        mock_migration.name = "add_users"

        mock_class = MagicMock(return_value=mock_migration)

        session._migrator.initialize = MagicMock()
        session._migrator.find_pending = MagicMock(return_value=[migration_file])
        session._migrator.find_migration_files = MagicMock(return_value=[migration_file])
        session._migrator.apply = MagicMock()
        session._migrator._version_from_filename = MagicMock(return_value="001")

        with patch("confiture.core.migrator.load_migration_class", return_value=mock_class):
            with patch("confiture.core.migrator.MigrationLock") as mock_lock_cls:
                mock_lock = MagicMock()
                mock_lock_cls.return_value = mock_lock
                mock_lock.acquire.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)

                result = session.up()

        assert result.success is True
        assert len(result.migrations_applied) == 1
        assert result.migrations_applied[0].version == "001"

    def test_returns_skipped_versions(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        f1 = migrations_dir / "001_add_users.py"
        f2 = migrations_dir / "002_add_posts.py"
        f1.write_text("# migration")
        f2.write_text("# migration")

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)

        mock_migration = MagicMock()
        mock_migration.version = "002"
        mock_migration.name = "add_posts"
        mock_class = MagicMock(return_value=mock_migration)

        def _ver_from_filename(name: str) -> str:
            return name.split("_")[0]

        session._migrator.initialize = MagicMock()
        session._migrator.find_pending = MagicMock(return_value=[f2])
        session._migrator.find_migration_files = MagicMock(return_value=[f1, f2])
        session._migrator.apply = MagicMock()
        session._migrator._version_from_filename = MagicMock(side_effect=_ver_from_filename)

        with patch("confiture.core.migrator.load_migration_class", return_value=mock_class):
            with patch("confiture.core.migrator.MigrationLock") as mock_lock_cls:
                mock_lock = MagicMock()
                mock_lock_cls.return_value = mock_lock
                mock_lock.acquire.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)

                result = session.up()

        assert "001" in result.skipped

    def test_dry_run_returns_success_without_applying(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        migration_file = migrations_dir / "001_add_users.py"
        migration_file.write_text("# migration")

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)

        mock_migration = MagicMock()
        mock_migration.version = "001"
        mock_migration.name = "add_users"
        mock_class = MagicMock(return_value=mock_migration)

        session._migrator.initialize = MagicMock()
        session._migrator.find_pending = MagicMock(return_value=[migration_file])
        session._migrator.find_migration_files = MagicMock(return_value=[migration_file])
        session._migrator.apply = MagicMock()
        session._migrator._version_from_filename = MagicMock(return_value="001")

        with patch("confiture.core.migrator.load_migration_class", return_value=mock_class):
            result = session.up(dry_run=True)

        assert result.success is True
        assert result.dry_run is True
        # apply should NOT be called in dry-run
        session._migrator.apply.assert_not_called()

    def test_failed_migration_returns_failure_result(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        migration_file = migrations_dir / "001_add_users.py"
        migration_file.write_text("# migration")

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)

        mock_migration = MagicMock()
        mock_migration.version = "001"
        mock_migration.name = "add_users"
        mock_class = MagicMock(return_value=mock_migration)

        from confiture.exceptions import MigrationError

        session._migrator.initialize = MagicMock()
        session._migrator.find_pending = MagicMock(return_value=[migration_file])
        session._migrator.find_migration_files = MagicMock(return_value=[migration_file])
        session._migrator.apply = MagicMock(side_effect=MigrationError("SQL failed"))
        session._migrator._version_from_filename = MagicMock(return_value="001")

        with patch("confiture.core.migrator.load_migration_class", return_value=mock_class):
            with patch("confiture.core.migrator.MigrationLock") as mock_lock_cls:
                mock_lock = MagicMock()
                mock_lock_cls.return_value = mock_lock
                mock_lock.acquire.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)

                result = session.up()

        assert result.success is False
        assert len(result.errors) > 0

    def test_target_stops_at_version(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        f1 = migrations_dir / "001_add_users.py"
        f2 = migrations_dir / "002_add_posts.py"
        f3 = migrations_dir / "003_add_comments.py"
        for f in (f1, f2, f3):
            f.write_text("# migration")

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)

        def _make_migration(ver: str, name: str) -> MagicMock:
            m = MagicMock()
            m.version = ver
            m.name = name
            return m

        migrations = {
            "001_add_users.py": _make_migration("001", "add_users"),
            "002_add_posts.py": _make_migration("002", "add_posts"),
            "003_add_comments.py": _make_migration("003", "add_comments"),
        }

        def _load_class(path: Path) -> MagicMock:
            m = MagicMock()
            m.return_value = migrations[path.name]
            return m

        session._migrator.initialize = MagicMock()
        session._migrator.find_pending = MagicMock(return_value=[f1, f2, f3])
        session._migrator.find_migration_files = MagicMock(return_value=[f1, f2, f3])
        session._migrator.apply = MagicMock()
        session._migrator._version_from_filename = MagicMock(side_effect=lambda n: n.split("_")[0])

        with patch("confiture.core.migrator.load_migration_class", side_effect=_load_class):
            with patch("confiture.core.migrator.MigrationLock") as mock_lock_cls:
                mock_lock = MagicMock()
                mock_lock_cls.return_value = mock_lock
                mock_lock.acquire.return_value.__enter__ = MagicMock(return_value=None)
                mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)

                result = session.up(target="002")

        applied_versions = [m.version for m in result.migrations_applied]
        assert "001" in applied_versions
        assert "002" in applied_versions
        assert "003" not in applied_versions
