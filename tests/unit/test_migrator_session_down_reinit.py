"""Tests for MigratorSession.down() and MigratorSession.reinit()."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.config.environment import Environment
from confiture.core.migrator import Migrator, MigratorSession
from confiture.models.results import MigrateDownResult, MigrateReinitResult, MigrationApplied


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


class TestMigratorSessionDown:
    def test_no_applied_returns_empty_result(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)
        session._migrator.initialize = MagicMock()
        session._migrator.get_applied_versions = MagicMock(return_value=[])

        result = session.down()

        assert isinstance(result, MigrateDownResult)
        assert result.success is True
        assert result.migrations_rolled_back == []

    def test_rolls_back_one_step_by_default(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        f1 = migrations_dir / "001_add_users.py"
        f1.write_text("# migration")

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)

        mock_migration = MagicMock()
        mock_migration.version = "001"
        mock_migration.name = "add_users"
        mock_class = MagicMock(return_value=mock_migration)

        session._migrator.initialize = MagicMock()
        session._migrator.get_applied_versions = MagicMock(return_value=["001"])
        session._migrator.find_migration_files = MagicMock(return_value=[f1])
        session._migrator.rollback = MagicMock()
        session._migrator._version_from_filename = MagicMock(return_value="001")

        with patch("confiture.core.migrator.load_migration_class", return_value=mock_class):
            result = session.down()

        assert result.success is True
        assert len(result.migrations_rolled_back) == 1
        assert result.migrations_rolled_back[0].version == "001"
        session._migrator.rollback.assert_called_once_with(mock_migration)

    def test_rolls_back_n_steps(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        f1 = migrations_dir / "001_add_users.py"
        f2 = migrations_dir / "002_add_posts.py"
        f1.write_text("# migration")
        f2.write_text("# migration")

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)

        def _make_mock(ver: str, name: str) -> MagicMock:
            m = MagicMock()
            m.version = ver
            m.name = name
            return m

        migs = {"001": _make_mock("001", "add_users"), "002": _make_mock("002", "add_posts")}

        def _load_class(path: Path) -> MagicMock:
            ver = path.name.split("_")[0]
            m = MagicMock()
            m.return_value = migs[ver]
            return m

        session._migrator.initialize = MagicMock()
        session._migrator.get_applied_versions = MagicMock(return_value=["001", "002"])
        session._migrator.find_migration_files = MagicMock(return_value=[f1, f2])
        session._migrator.rollback = MagicMock()
        session._migrator._version_from_filename = MagicMock(
            side_effect=lambda n: n.split("_")[0]
        )

        with patch("confiture.core.migrator.load_migration_class", side_effect=_load_class):
            result = session.down(steps=2)

        assert len(result.migrations_rolled_back) == 2
        versions = [m.version for m in result.migrations_rolled_back]
        assert "001" in versions
        assert "002" in versions

    def test_dry_run_does_not_rollback(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        f1 = migrations_dir / "001_add_users.py"
        f1.write_text("# migration")

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)

        mock_migration = MagicMock()
        mock_migration.version = "001"
        mock_migration.name = "add_users"
        mock_class = MagicMock(return_value=mock_migration)

        session._migrator.initialize = MagicMock()
        session._migrator.get_applied_versions = MagicMock(return_value=["001"])
        session._migrator.find_migration_files = MagicMock(return_value=[f1])
        session._migrator.rollback = MagicMock()
        session._migrator._version_from_filename = MagicMock(return_value="001")

        with patch("confiture.core.migrator.load_migration_class", return_value=mock_class):
            result = session.down(dry_run=True)

        session._migrator.rollback.assert_not_called()
        assert result.success is True


class TestMigratorSessionReinit:
    def test_reinit_delegates_to_migrator(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_add_users.py").write_text("# migration")

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)

        expected = MigrateReinitResult(
            success=True,
            deleted_count=3,
            migrations_marked=[
                MigrationApplied(version="001", name="add_users", execution_time_ms=0)
            ],
            total_execution_time_ms=0,
        )
        session._migrator.initialize = MagicMock()
        session._migrator.reinit = MagicMock(return_value=expected)

        result = session.reinit()

        assert isinstance(result, MigrateReinitResult)
        assert result.deleted_count == 3
        session._migrator.reinit.assert_called_once_with(
            through=None, dry_run=False, migrations_dir=migrations_dir
        )

    def test_reinit_passes_through_param(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)

        expected = MigrateReinitResult(
            success=True,
            deleted_count=1,
            migrations_marked=[],
            total_execution_time_ms=0,
        )
        session._migrator.initialize = MagicMock()
        session._migrator.reinit = MagicMock(return_value=expected)

        session.reinit(through="003")

        session._migrator.reinit.assert_called_once_with(
            through="003", dry_run=False, migrations_dir=migrations_dir
        )

    def test_reinit_dry_run(self, tmp_path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        env = _make_env()
        session, _ = _make_session(env, migrations_dir)

        expected = MigrateReinitResult(
            success=True,
            deleted_count=0,
            migrations_marked=[],
            total_execution_time_ms=0,
            dry_run=True,
        )
        session._migrator.initialize = MagicMock()
        session._migrator.reinit = MagicMock(return_value=expected)

        result = session.reinit(dry_run=True)

        assert result.dry_run is True
        session._migrator.reinit.assert_called_once_with(
            through=None, dry_run=True, migrations_dir=migrations_dir
        )
