"""Tests for distributed locking mechanism.

Tests the MigrationLock class and its PostgreSQL advisory lock integration.
"""

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from confiture.core.locking import (
    LockAcquisitionError,
    LockConfig,
    LockMode,
    MigrationLock,
)


class TestLockConfig:
    """Tests for LockConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = LockConfig()

        assert config.enabled is True
        assert config.timeout_ms == 30000
        assert config.lock_id is None
        assert config.mode == LockMode.BLOCKING

    def test_custom_timeout(self):
        """Test custom timeout configuration."""
        config = LockConfig(timeout_ms=60000)

        assert config.timeout_ms == 60000

    def test_custom_lock_id(self):
        """Test custom lock ID configuration."""
        config = LockConfig(lock_id=12345)

        assert config.lock_id == 12345

    def test_non_blocking_mode(self):
        """Test non-blocking mode configuration."""
        config = LockConfig(mode=LockMode.NON_BLOCKING)

        assert config.mode == LockMode.NON_BLOCKING

    def test_disabled_locking(self):
        """Test disabled locking configuration."""
        config = LockConfig(enabled=False)

        assert config.enabled is False


class TestLockAcquisitionError:
    """Tests for LockAcquisitionError exception."""

    def test_error_with_timeout(self):
        """Test error creation with timeout flag."""
        error = LockAcquisitionError("Lock timeout", timeout=True)

        assert str(error) == "Lock timeout"
        assert error.timeout is True

    def test_error_without_timeout(self):
        """Test error creation without timeout flag."""
        error = LockAcquisitionError("Lock busy", timeout=False)

        assert str(error) == "Lock busy"
        assert error.timeout is False

    def test_default_timeout_is_false(self):
        """Test default timeout value is False."""
        error = LockAcquisitionError("Lock error")

        assert error.timeout is False


class TestMigrationLock:
    """Tests for MigrationLock class."""

    def test_lock_id_generation_deterministic(self):
        """Test that lock ID generation is deterministic for same database."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("test_database",)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        lock1 = MigrationLock(mock_conn)
        lock2 = MigrationLock(mock_conn)

        # Both should generate the same lock ID for same database
        id1 = lock1._generate_lock_id()
        id2 = lock2._generate_lock_id()

        assert id1 == id2

    def test_lock_id_generation_different_databases(self):
        """Test that different databases get different lock IDs."""
        # First connection - database1
        mock_conn1 = MagicMock()
        mock_cursor1 = MagicMock()
        mock_cursor1.fetchone.return_value = ("database1",)
        mock_conn1.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor1)
        mock_conn1.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # Second connection - database2
        mock_conn2 = MagicMock()
        mock_cursor2 = MagicMock()
        mock_cursor2.fetchone.return_value = ("database2",)
        mock_conn2.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor2)
        mock_conn2.cursor.return_value.__exit__ = MagicMock(return_value=False)

        lock1 = MigrationLock(mock_conn1)
        lock2 = MigrationLock(mock_conn2)

        id1 = lock1._generate_lock_id()
        id2 = lock2._generate_lock_id()

        assert id1 != id2

    def test_lock_id_is_32bit_positive(self):
        """Test that generated lock ID is 32-bit positive integer."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("any_database",)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        lock = MigrationLock(mock_conn)
        lock_id = lock._generate_lock_id()

        assert 0 <= lock_id <= 0x7FFFFFFF

    def test_custom_lock_id_used(self):
        """Test that custom lock ID is used when provided."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        config = LockConfig(lock_id=99999)
        lock = MigrationLock(mock_conn, config)

        # Should not call database to generate lock ID
        assert lock._get_lock_id() == 99999

    def test_disabled_locking_skips_acquisition(self):
        """Test that disabled locking skips lock acquisition."""
        mock_conn = MagicMock()

        config = LockConfig(enabled=False)
        lock = MigrationLock(mock_conn, config)

        # Should not call any database operations
        with lock.acquire():
            pass

        # No cursor should have been created for locking
        mock_conn.cursor.assert_not_called()

    def test_acquire_blocking_calls_pg_advisory_lock(self):
        """Test that blocking acquire calls pg_advisory_lock."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("test_db",)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        lock = MigrationLock(mock_conn)

        with lock.acquire():
            pass

        # Check that pg_advisory_lock was called
        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        lock_call_found = any("pg_advisory_lock" in call for call in calls)
        unlock_call_found = any("pg_advisory_unlock" in call for call in calls)

        assert lock_call_found, "pg_advisory_lock should have been called"
        assert unlock_call_found, "pg_advisory_unlock should have been called"

    def test_acquire_non_blocking_calls_pg_try_advisory_lock(self):
        """Test that non-blocking acquire calls pg_try_advisory_lock."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("test_db",),  # current_database()
            (True,),  # pg_try_advisory_lock returns True (acquired)
            (True,),  # pg_advisory_unlock
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        config = LockConfig(mode=LockMode.NON_BLOCKING)
        lock = MigrationLock(mock_conn, config)

        with lock.acquire():
            pass

        # Check that pg_try_advisory_lock was called
        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        try_lock_call_found = any("pg_try_advisory_lock" in call for call in calls)

        assert try_lock_call_found, "pg_try_advisory_lock should have been called"

    def test_acquire_non_blocking_raises_when_locked(self):
        """Test that non-blocking fails when lock is held."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("test_db",),  # current_database()
            (False,),  # pg_try_advisory_lock returns False (not acquired)
            None,  # get_lock_holder query
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        config = LockConfig(mode=LockMode.NON_BLOCKING)
        lock = MigrationLock(mock_conn, config)

        with pytest.raises(LockAcquisitionError) as exc_info:
            with lock.acquire():
                pass

        assert exc_info.value.timeout is False
        assert "held by another process" in str(exc_info.value)

    def test_lock_released_on_normal_exit(self):
        """Test that lock is released on normal context exit."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("test_db",),  # current_database()
            (True,),  # pg_advisory_unlock
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        lock = MigrationLock(mock_conn)

        with lock.acquire():
            assert lock._lock_held is True

        # Lock should be released after context exit
        assert lock._lock_held is False

    def test_lock_released_on_exception(self):
        """Test that lock is released even when exception occurs."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("test_db",),  # current_database()
            (True,),  # pg_advisory_unlock
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        lock = MigrationLock(mock_conn)

        with pytest.raises(ValueError):
            with lock.acquire():
                assert lock._lock_held is True
                raise ValueError("Test exception")

        # Lock should still be released
        assert lock._lock_held is False

    def test_is_locked_returns_true_when_locked(self):
        """Test is_locked returns True when lock is held."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("test_db",),  # current_database()
            (True,),  # EXISTS query
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        lock = MigrationLock(mock_conn)

        assert lock.is_locked() is True

    def test_is_locked_returns_false_when_not_locked(self):
        """Test is_locked returns False when lock is not held."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("test_db",),  # current_database()
            (False,),  # EXISTS query
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        lock = MigrationLock(mock_conn)

        assert lock.is_locked() is False

    def test_get_lock_holder_returns_info_when_locked(self):
        """Test get_lock_holder returns holder info when lock is held."""
        from datetime import datetime

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        start_time = datetime.now()
        mock_cursor.fetchone.side_effect = [
            ("test_db",),  # current_database()
            (12345, "postgres", "confiture", "192.168.1.1", start_time),  # Lock holder query
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        lock = MigrationLock(mock_conn)
        holder = lock.get_lock_holder()

        assert holder is not None
        assert holder["pid"] == 12345
        assert holder["user"] == "postgres"
        assert holder["application"] == "confiture"
        assert holder["client_addr"] == "192.168.1.1"
        assert holder["started_at"] == start_time

    def test_get_lock_holder_returns_none_when_not_locked(self):
        """Test get_lock_holder returns None when lock is not held."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("test_db",),  # current_database()
            None,  # Lock holder query returns no result
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        lock = MigrationLock(mock_conn)
        holder = lock.get_lock_holder()

        assert holder is None

    def test_lock_held_property(self):
        """Test lock_held property reflects current state."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("test_db",),  # current_database()
            (True,),  # pg_advisory_unlock
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        lock = MigrationLock(mock_conn)

        assert lock.lock_held is False

        with lock.acquire():
            assert lock.lock_held is True

        assert lock.lock_held is False

    def test_default_lock_namespace(self):
        """Test that default lock namespace is consistent."""
        # Should be first 32 bits of SHA256("confiture_migrations")
        expected_namespace = 1751936052
        assert MigrationLock.DEFAULT_LOCK_NAMESPACE == expected_namespace

    def test_timeout_setting_applied(self):
        """Test that timeout setting is applied to statement_timeout."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            ("test_db",),  # current_database()
            (True,),  # pg_advisory_unlock
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        config = LockConfig(timeout_ms=5000)
        lock = MigrationLock(mock_conn, config)

        with lock.acquire():
            pass

        # Check that SET LOCAL statement_timeout was called with correct value
        calls = [str(call) for call in mock_cursor.execute.call_args_list]
        timeout_call_found = any("5000ms" in call for call in calls)

        assert timeout_call_found, "statement_timeout should be set to 5000ms"
