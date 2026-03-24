"""Tests for require_reversible parameter on MigratorSession.up() (issue #89)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from confiture.config.environment import Environment
from confiture.core._migrator.session import MigratorSession
from confiture.models.results import MigrationPreflightInfo, PreflightResult


def _make_entered_session(migrations_dir: Path | None = None) -> MigratorSession:
    """Create a MigratorSession that appears to be inside 'with'."""
    env = MagicMock(spec=Environment)
    env.database_url = "postgresql://localhost/test"
    env.migration = MagicMock()
    env.migration.tracking_table = "tb_confiture"

    mdir = migrations_dir or Path("db/migrations")
    session = MigratorSession(config=env, migrations_dir=mdir)
    session._conn = MagicMock()
    session._migrator = MagicMock()
    return session


def _preflight_all_reversible() -> PreflightResult:
    return PreflightResult(
        migrations=[
            MigrationPreflightInfo(version="001", name="create_users", has_down=True),
            MigrationPreflightInfo(version="002", name="add_email", has_down=True),
        ]
    )


def _preflight_some_irreversible() -> PreflightResult:
    return PreflightResult(
        migrations=[
            MigrationPreflightInfo(version="001", name="create_users", has_down=True),
            MigrationPreflightInfo(version="002", name="add_email", has_down=False),
            MigrationPreflightInfo(version="003", name="drop_legacy", has_down=False),
        ]
    )


class TestRequireReversible:
    """Tests for the require_reversible parameter."""

    def test_up_require_reversible_all_have_down_succeeds(self, tmp_path):
        """All migrations have .down.sql → up() proceeds normally."""
        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_create_users.up.sql").write_text("CREATE TABLE users (id int);")
        (mdir / "001_create_users.down.sql").write_text("DROP TABLE users;")

        session = _make_entered_session(mdir)
        session._migrator.find_migration_files.return_value = [mdir / "001_create_users.up.sql"]
        session._migrator.find_pending.return_value = [mdir / "001_create_users.up.sql"]
        session._migrator._version_from_filename.return_value = "001"

        import confiture.core.migrator as _m

        with patch.object(session, "preflight", return_value=_preflight_all_reversible()):
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
                        mock_instance.name = "create_users"
                        mock_cls.return_value = mock_instance
                        mock_load.return_value = mock_cls

                        result = session.up(require_reversible=True)

        assert result.success is True

    def test_up_require_reversible_missing_down_returns_error(self, tmp_path):
        """One migration lacks .down.sql → up() returns error."""
        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_create_users.up.sql").write_text("CREATE TABLE users (id int);")

        session = _make_entered_session(mdir)
        session._migrator.find_migration_files.return_value = [mdir / "001_create_users.up.sql"]
        session._migrator.find_pending.return_value = [mdir / "001_create_users.up.sql"]
        session._migrator._version_from_filename.return_value = "001"

        with patch.object(session, "preflight", return_value=_preflight_some_irreversible()):
            result = session.up(require_reversible=True)

        assert result.success is False
        assert "Irreversible" in result.errors[0]
        assert "002" in result.errors[0]
        assert "003" in result.errors[0]

    def test_up_require_reversible_false_missing_down_succeeds(self, tmp_path):
        """Default (require_reversible=False) doesn't check reversibility."""
        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_create_users.up.sql").write_text("CREATE TABLE users (id int);")

        session = _make_entered_session(mdir)
        session._migrator.find_migration_files.return_value = [mdir / "001_create_users.up.sql"]
        session._migrator.find_pending.return_value = [mdir / "001_create_users.up.sql"]
        session._migrator._version_from_filename.return_value = "001"

        import confiture.core.migrator as _m

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
                    mock_instance.name = "create_users"
                    mock_cls.return_value = mock_instance
                    mock_load.return_value = mock_cls

                    result = session.up(require_reversible=False)

        assert result.success is True

    def test_up_require_reversible_no_pending_succeeds(self, tmp_path):
        """No pending migrations → success even with require_reversible."""
        mdir = tmp_path / "migrations"
        mdir.mkdir()

        session = _make_entered_session(mdir)
        session._migrator.find_migration_files.return_value = []
        session._migrator.find_pending.return_value = []

        result = session.up(require_reversible=True)
        assert result.success is True

    def test_up_require_reversible_dry_run_skips_check(self, tmp_path):
        """dry_run=True returns before the reversibility check."""
        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_create_users.up.sql").write_text("CREATE TABLE users (id int);")

        session = _make_entered_session(mdir)
        session._migrator.find_migration_files.return_value = [mdir / "001_create_users.up.sql"]
        session._migrator.find_pending.return_value = [mdir / "001_create_users.up.sql"]
        session._migrator._version_from_filename.return_value = "001"

        # Should not call preflight at all
        with patch.object(session, "preflight") as mock_preflight:
            result = session.up(dry_run=True, require_reversible=True)
            mock_preflight.assert_not_called()

        assert result.success is True
        assert result.dry_run is True

    def test_up_require_reversible_error_lists_all_irreversible(self, tmp_path):
        """Multiple irreversible migrations all listed in error message."""
        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_create_users.up.sql").write_text("CREATE TABLE users (id int);")
        (mdir / "002_add_email.up.sql").write_text("ALTER TABLE users ADD email text;")

        session = _make_entered_session(mdir)
        session._migrator.find_migration_files.return_value = [
            mdir / "001_create_users.up.sql",
            mdir / "002_add_email.up.sql",
        ]
        session._migrator.find_pending.return_value = [
            mdir / "001_create_users.up.sql",
            mdir / "002_add_email.up.sql",
        ]
        session._migrator._version_from_filename.side_effect = lambda name: name.split("_")[0]

        preflight = PreflightResult(
            migrations=[
                MigrationPreflightInfo(version="001", name="create_users", has_down=False),
                MigrationPreflightInfo(version="002", name="add_email", has_down=False),
            ]
        )

        with patch.object(session, "preflight", return_value=preflight):
            result = session.up(require_reversible=True)

        assert result.success is False
        assert "001" in result.errors[0]
        assert "002" in result.errors[0]
