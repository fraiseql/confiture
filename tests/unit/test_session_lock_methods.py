"""Tests for MigratorSession.is_locked() and get_lock_holder() (issue #91)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.config.environment import Environment
from confiture.core._migrator.session import MigratorSession
from confiture.exceptions import ConfigurationError


def _make_session() -> MigratorSession:
    """Create a MigratorSession without entering the context manager."""
    env = MagicMock(spec=Environment)
    env.database_url = "postgresql://localhost/test"
    env.migration = MagicMock()
    env.migration.tracking_table = "tb_confiture"
    return MigratorSession(config=env, migrations_dir=Path("db/migrations"))


def test_is_locked_outside_context_raises():
    """is_locked() raises ConfigurationError when called outside 'with'."""
    session = _make_session()
    with pytest.raises(ConfigurationError, match="context manager"):
        session.is_locked()


def test_get_lock_holder_outside_context_raises():
    """get_lock_holder() raises ConfigurationError when called outside 'with'."""
    session = _make_session()
    with pytest.raises(ConfigurationError, match="context manager"):
        session.get_lock_holder()


def test_is_locked_delegates_to_migration_lock():
    """is_locked() delegates to MigrationLock.is_locked()."""
    session = _make_session()
    session._conn = MagicMock()  # simulate entered context

    with patch("confiture.core._migrator.session.MigrationLock") as MockLock:
        mock_instance = MagicMock()
        mock_instance.is_locked.return_value = True
        MockLock.return_value = mock_instance

        result = session.is_locked()

        assert result is True
        mock_instance.is_locked.assert_called_once()


def test_get_lock_holder_delegates_to_migration_lock():
    """get_lock_holder() delegates to MigrationLock.get_lock_holder()."""
    session = _make_session()
    session._conn = MagicMock()  # simulate entered context

    holder_info = {
        "pid": 12345,
        "user": "postgres",
        "application": "confiture",
        "client_addr": None,
        "started_at": "2026-03-24T10:00:00",
    }

    with patch("confiture.core._migrator.session.MigrationLock") as MockLock:
        mock_instance = MagicMock()
        mock_instance.get_lock_holder.return_value = holder_info
        MockLock.return_value = mock_instance

        result = session.get_lock_holder()

        assert result == holder_info
        mock_instance.get_lock_holder.assert_called_once()


def test_is_locked_returns_false_when_no_lock():
    """is_locked() returns False when no lock is held."""
    session = _make_session()
    session._conn = MagicMock()

    with patch("confiture.core._migrator.session.MigrationLock") as MockLock:
        mock_instance = MagicMock()
        mock_instance.is_locked.return_value = False
        MockLock.return_value = mock_instance

        assert session.is_locked() is False


def test_get_lock_holder_returns_none_when_no_lock():
    """get_lock_holder() returns None when no lock is held."""
    session = _make_session()
    session._conn = MagicMock()

    with patch("confiture.core._migrator.session.MigrationLock") as MockLock:
        mock_instance = MagicMock()
        mock_instance.get_lock_holder.return_value = None
        MockLock.return_value = mock_instance

        assert session.get_lock_holder() is None
