"""Tests for dry_run_execute (SAVEPOINT-based) on MigratorSession.up() (issue #90)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.config.environment import Environment
from confiture.core._migrator.session import MigratorSession
from confiture.exceptions import ConfigurationError
from confiture.models.results import MigrateUpResult


def _make_entered_session(migrations_dir: Path) -> MigratorSession:
    """Create a MigratorSession that appears to be inside 'with'."""
    env = MagicMock(spec=Environment)
    env.database_url = "postgresql://localhost/test"
    env.migration = MagicMock()
    env.migration.tracking_table = "tb_confiture"

    session = MigratorSession(config=env, migrations_dir=migrations_dir)
    session._conn = MagicMock()
    session._migrator = MagicMock()
    return session


def _setup_pending(session, tmp_path, count=1):
    """Set up pending migration files on a session."""
    mdir = tmp_path / "migrations"
    mdir.mkdir(exist_ok=True)

    files = []
    for i in range(1, count + 1):
        f = mdir / f"00{i}_migration_{i}.up.sql"
        f.write_text(f"CREATE TABLE t{i} (id int);")
        files.append(f)

    session._migrations_dir = mdir
    session._migrator.find_migration_files.return_value = files
    session._migrator.find_pending.return_value = files
    session._migrator._version_from_filename.side_effect = lambda name: name.split("_")[0]
    return files


class TestDryRunExecute:
    """Tests for the dry_run_execute parameter."""

    def test_returns_success_on_valid_sql(self, tmp_path):
        """Successful SAVEPOINT execution returns success=True."""
        import confiture.core.migrator as _m

        session = _make_entered_session(tmp_path / "migrations")
        _setup_pending(session, tmp_path)

        with patch.object(_m, "LockConfig"):
            with patch.object(_m, "MigrationLock") as MockLock:
                mock_lock = MagicMock()
                mock_lock.acquire.return_value.__enter__ = MagicMock()
                mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)
                MockLock.return_value = mock_lock

                with patch.object(_m, "load_migration_class") as mock_load:
                    mock_cls = MagicMock()
                    mock_instance = MagicMock()
                    mock_instance.version = "001"
                    mock_instance.name = "migration_1"
                    mock_cls.return_value = mock_instance
                    mock_load.return_value = mock_cls

                    result = session.up(dry_run_execute=True)

        assert result.success is True
        assert result.dry_run is True
        assert result.dry_run_execute is True
        assert len(result.migrations_applied) == 1
        assert "rolled back" in result.warnings[0]

    def test_returns_error_on_sql_failure(self, tmp_path):
        """SQL error during SAVEPOINT execution returns error result."""
        import confiture.core.migrator as _m

        session = _make_entered_session(tmp_path / "migrations")
        _setup_pending(session, tmp_path)

        # Make apply() raise
        session._migrator.apply.side_effect = Exception("syntax error at or near 'CREAT'")

        with patch.object(_m, "LockConfig"):
            with patch.object(_m, "MigrationLock") as MockLock:
                mock_lock = MagicMock()
                mock_lock.acquire.return_value.__enter__ = MagicMock()
                mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)
                MockLock.return_value = mock_lock

                with patch.object(_m, "load_migration_class") as mock_load:
                    mock_cls = MagicMock()
                    mock_instance = MagicMock()
                    mock_instance.version = "001"
                    mock_instance.name = "migration_1"
                    mock_cls.return_value = mock_instance
                    mock_load.return_value = mock_cls

                    result = session.up(dry_run_execute=True)

        assert result.success is False
        assert result.dry_run_execute is True
        assert "syntax error" in result.errors[0]

    def test_rolls_back_savepoint(self, tmp_path):
        """SAVEPOINT and ROLLBACK SQL are executed on the connection."""
        import confiture.core.migrator as _m

        session = _make_entered_session(tmp_path / "migrations")
        _setup_pending(session, tmp_path)

        with patch.object(_m, "LockConfig"):
            with patch.object(_m, "MigrationLock") as MockLock:
                mock_lock = MagicMock()
                mock_lock.acquire.return_value.__enter__ = MagicMock()
                mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)
                MockLock.return_value = mock_lock

                with patch.object(_m, "load_migration_class") as mock_load:
                    mock_cls = MagicMock()
                    mock_instance = MagicMock()
                    mock_instance.version = "001"
                    mock_instance.name = "migration_1"
                    mock_cls.return_value = mock_instance
                    mock_load.return_value = mock_cls

                    session.up(dry_run_execute=True)

        # Check SAVEPOINT calls on connection
        execute_calls = [str(c) for c in session._conn.execute.call_args_list]
        assert any("SAVEPOINT dry_run_execute" in c for c in execute_calls)
        assert any("ROLLBACK TO SAVEPOINT dry_run_execute" in c for c in execute_calls)
        assert any("RELEASE SAVEPOINT dry_run_execute" in c for c in execute_calls)

    def test_rolls_back_even_on_failure(self, tmp_path):
        """ROLLBACK happens even when apply() raises."""
        import confiture.core.migrator as _m

        session = _make_entered_session(tmp_path / "migrations")
        _setup_pending(session, tmp_path)
        session._migrator.apply.side_effect = Exception("boom")

        with patch.object(_m, "LockConfig"):
            with patch.object(_m, "MigrationLock") as MockLock:
                mock_lock = MagicMock()
                mock_lock.acquire.return_value.__enter__ = MagicMock()
                mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)
                MockLock.return_value = mock_lock

                with patch.object(_m, "load_migration_class") as mock_load:
                    mock_cls = MagicMock()
                    mock_instance = MagicMock()
                    mock_instance.version = "001"
                    mock_instance.name = "migration_1"
                    mock_cls.return_value = mock_instance
                    mock_load.return_value = mock_cls

                    session.up(dry_run_execute=True)

        execute_calls = [str(c) for c in session._conn.execute.call_args_list]
        assert any("ROLLBACK TO SAVEPOINT" in c for c in execute_calls)

    def test_mutual_exclusion_with_dry_run(self, tmp_path):
        """Both dry_run and dry_run_execute → ConfigurationError."""
        mdir = tmp_path / "migrations"
        mdir.mkdir()

        session = _make_entered_session(mdir)

        with pytest.raises(ConfigurationError, match="Cannot use both"):
            session.up(dry_run=True, dry_run_execute=True)

    def test_no_pending_returns_empty_success(self, tmp_path):
        """No pending files → success with empty list."""
        mdir = tmp_path / "migrations"
        mdir.mkdir()

        session = _make_entered_session(mdir)
        session._migrator.find_migration_files.return_value = []
        session._migrator.find_pending.return_value = []

        result = session.up(dry_run_execute=True)
        assert result.success is True
        assert result.migrations_applied == []

    def test_respects_target(self, tmp_path):
        """Stops at target version."""
        import confiture.core.migrator as _m

        session = _make_entered_session(tmp_path / "migrations")
        _setup_pending(session, tmp_path, count=3)

        versions = ["001", "002", "003"]
        names = ["migration_1", "migration_2", "migration_3"]

        with patch.object(_m, "LockConfig"):
            with patch.object(_m, "MigrationLock") as MockLock:
                mock_lock = MagicMock()
                mock_lock.acquire.return_value.__enter__ = MagicMock()
                mock_lock.acquire.return_value.__exit__ = MagicMock(return_value=False)
                MockLock.return_value = mock_lock

                call_count = [0]

                def make_migration_class(f):
                    idx = call_count[0]
                    call_count[0] += 1
                    mock_cls = MagicMock()
                    mock_instance = MagicMock()
                    mock_instance.version = versions[idx]
                    mock_instance.name = names[idx]
                    mock_cls.return_value = mock_instance
                    return mock_cls

                with patch.object(_m, "load_migration_class", side_effect=make_migration_class):
                    result = session.up(dry_run_execute=True, target="002")

        assert result.success is True
        assert len(result.migrations_applied) == 2
        assert result.migrations_applied[0].version == "001"
        assert result.migrations_applied[1].version == "002"

    def test_result_has_dry_run_execute_field(self):
        """MigrateUpResult has dry_run_execute field."""
        result = MigrateUpResult(
            success=True,
            migrations_applied=[],
            total_execution_time_ms=0,
            dry_run_execute=True,
        )
        assert result.dry_run_execute is True

    def test_to_dict_includes_dry_run_execute(self):
        """to_dict() includes dry_run_execute field."""
        result = MigrateUpResult(
            success=True,
            migrations_applied=[],
            total_execution_time_ms=0,
            dry_run_execute=True,
        )
        d = result.to_dict()
        assert "dry_run_execute" in d
        assert d["dry_run_execute"] is True

    def test_combined_with_require_reversible(self, tmp_path):
        """Reversibility check runs first, blocks before SAVEPOINT if irreversible."""
        from confiture.models.results import MigrationPreflightInfo, PreflightResult

        session = _make_entered_session(tmp_path / "migrations")
        _setup_pending(session, tmp_path)

        preflight = PreflightResult(
            migrations=[
                MigrationPreflightInfo(version="001", name="migration_1", has_down=False),
            ]
        )

        with patch.object(session, "preflight", return_value=preflight):
            result = session.up(dry_run_execute=True, require_reversible=True)

        assert result.success is False
        assert "Irreversible" in result.errors[0]
        # SAVEPOINT should NOT have been called
        execute_calls = [str(c) for c in session._conn.execute.call_args_list]
        assert not any("SAVEPOINT" in c for c in execute_calls)
