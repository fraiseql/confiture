"""Integration tests for concurrent migration scenarios.

These tests verify that the distributed locking mechanism works correctly
in real PostgreSQL environments with multiple concurrent connections.

Requires a running PostgreSQL instance with test database.
"""

import threading
import time
from typing import Callable

import psycopg
import pytest

from confiture.core.locking import (
    LockAcquisitionError,
    LockConfig,
    LockMode,
    MigrationLock,
)


def get_test_connection_string() -> str:
    """Get connection string for test database."""
    return "postgresql://postgres:postgres@localhost:5432/confiture_test"


@pytest.fixture
def test_db():
    """Create a test database connection."""
    try:
        conn = psycopg.connect(get_test_connection_string())
        yield conn
        conn.close()
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL test database not available")


@pytest.fixture
def second_connection():
    """Create a second database connection for concurrent testing."""
    try:
        conn = psycopg.connect(get_test_connection_string())
        yield conn
        conn.close()
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL test database not available")


@pytest.mark.integration
class TestConcurrentMigrations:
    """Test concurrent migration scenarios with real PostgreSQL."""

    def test_single_connection_acquires_lock(self, test_db):
        """Test that a single connection can acquire the lock."""
        lock = MigrationLock(test_db)

        with lock.acquire():
            assert lock.lock_held is True

        assert lock.lock_held is False

    def test_lock_blocks_second_process(self, test_db, second_connection):
        """Test that second connection waits for lock."""
        lock1 = MigrationLock(test_db)
        lock2 = MigrationLock(second_connection, LockConfig(timeout_ms=100))

        # First connection acquires lock
        with lock1.acquire():
            # Second connection should timeout trying to acquire
            with pytest.raises(LockAcquisitionError) as exc_info:
                with lock2.acquire():
                    pass

            assert exc_info.value.timeout is True

    def test_non_blocking_returns_immediately(self, test_db, second_connection):
        """Test non-blocking mode returns immediately when locked."""
        lock1 = MigrationLock(test_db)
        lock2 = MigrationLock(second_connection, LockConfig(mode=LockMode.NON_BLOCKING))

        with lock1.acquire():
            start = time.time()
            with pytest.raises(LockAcquisitionError) as exc_info:
                with lock2.acquire():
                    pass
            elapsed = time.time() - start

            # Should return almost immediately (< 1 second)
            assert elapsed < 1.0
            assert exc_info.value.timeout is False

    def test_lock_released_allows_second_acquisition(self, test_db, second_connection):
        """Test that released lock can be acquired by another connection."""
        lock1 = MigrationLock(test_db)
        lock2 = MigrationLock(second_connection)

        # First connection acquires and releases lock
        with lock1.acquire():
            assert lock1.lock_held is True

        # Second connection should now be able to acquire
        with lock2.acquire():
            assert lock2.lock_held is True

    def test_is_locked_reflects_actual_state(self, test_db, second_connection):
        """Test is_locked returns correct state across connections."""
        lock1 = MigrationLock(test_db)
        lock2 = MigrationLock(second_connection)

        # Before acquisition
        assert lock1.is_locked() is False

        with lock1.acquire():
            # Both connections should see the lock as held
            assert lock1.is_locked() is True
            assert lock2.is_locked() is True

        # After release
        assert lock1.is_locked() is False
        assert lock2.is_locked() is False

    def test_get_lock_holder_shows_holding_connection(self, test_db, second_connection):
        """Test get_lock_holder returns info about the holder."""
        lock1 = MigrationLock(test_db)
        lock2 = MigrationLock(second_connection)

        with lock1.acquire():
            holder = lock2.get_lock_holder()

            assert holder is not None
            assert "pid" in holder
            assert holder["pid"] > 0

    def test_concurrent_threads_serialize_correctly(self, test_db):
        """Test that concurrent threads serialize through the lock."""
        results: list[str] = []
        lock = threading.Lock()

        def worker(name: str, conn_str: str):
            try:
                conn = psycopg.connect(conn_str)
                migration_lock = MigrationLock(conn, LockConfig(timeout_ms=10000))

                with migration_lock.acquire():
                    with lock:
                        results.append(f"{name}_start")
                    time.sleep(0.1)  # Simulate work
                    with lock:
                        results.append(f"{name}_end")

                conn.close()
            except Exception as e:
                with lock:
                    results.append(f"{name}_error: {e}")

        conn_str = get_test_connection_string()
        threads = [
            threading.Thread(target=worker, args=("thread1", conn_str)),
            threading.Thread(target=worker, args=("thread2", conn_str)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each thread should complete (start and end)
        assert "thread1_start" in results or "thread2_start" in results
        assert "thread1_end" in results or "thread2_end" in results

        # Check that operations don't overlap (one ends before another starts)
        # Find the order of operations
        if results.index("thread1_start") < results.index("thread2_start"):
            # Thread1 started first, should end before thread2 starts
            assert results.index("thread1_end") < results.index("thread2_start")
        else:
            # Thread2 started first, should end before thread1 starts
            assert results.index("thread2_end") < results.index("thread1_start")

    def test_lock_released_on_connection_close(self, test_db, second_connection):
        """Test that lock is released when connection closes."""
        lock2 = MigrationLock(second_connection)

        # Create a new connection, acquire lock, then close it
        conn1 = psycopg.connect(get_test_connection_string())
        lock1 = MigrationLock(conn1)

        with lock1.acquire():
            # Lock is held
            assert lock2.is_locked() is True

        # Close the connection (releases the lock)
        conn1.close()

        # Small delay to let PostgreSQL clean up
        time.sleep(0.1)

        # Lock should now be released
        assert lock2.is_locked() is False

        # Should be able to acquire on second connection
        with lock2.acquire():
            assert lock2.lock_held is True

    def test_disabled_locking_allows_concurrent_access(self, test_db, second_connection):
        """Test that disabled locking allows concurrent access."""
        config = LockConfig(enabled=False)
        lock1 = MigrationLock(test_db, config)
        lock2 = MigrationLock(second_connection, config)

        entered_both = False

        def check_concurrent():
            nonlocal entered_both
            with lock2.acquire():
                entered_both = True

        with lock1.acquire():
            # Second lock should succeed immediately since locking is disabled
            t = threading.Thread(target=check_concurrent)
            t.start()
            t.join(timeout=1.0)

        assert entered_both is True

    def test_custom_lock_id_isolates_locks(self, test_db, second_connection):
        """Test that custom lock IDs create separate lock scopes."""
        lock1 = MigrationLock(test_db, LockConfig(lock_id=111))
        lock2 = MigrationLock(second_connection, LockConfig(lock_id=222))

        entered_both = False

        def acquire_lock2():
            nonlocal entered_both
            with lock2.acquire():
                entered_both = True

        # Both should be able to acquire simultaneously since different lock IDs
        with lock1.acquire():
            t = threading.Thread(target=acquire_lock2)
            t.start()
            t.join(timeout=1.0)

            assert entered_both is True

    def test_lock_timeout_configurable(self, test_db, second_connection):
        """Test that lock timeout is configurable and honored."""
        lock1 = MigrationLock(test_db)
        # Very short timeout
        lock2 = MigrationLock(second_connection, LockConfig(timeout_ms=50))

        with lock1.acquire():
            start = time.time()
            with pytest.raises(LockAcquisitionError):
                with lock2.acquire():
                    pass
            elapsed = time.time() - start

            # Should timeout around 50ms (allow some margin)
            assert 0.03 < elapsed < 0.5


@pytest.mark.integration
class TestLockRecovery:
    """Test lock recovery scenarios."""

    def test_lock_auto_releases_on_crash_simulation(self, test_db, second_connection):
        """Test that lock is released when connection is abruptly terminated."""
        lock2 = MigrationLock(second_connection)

        # Create a new connection and acquire lock
        conn1 = psycopg.connect(get_test_connection_string())
        lock1 = MigrationLock(conn1)

        with lock1.acquire():
            assert lock2.is_locked() is True

            # Simulate crash by canceling the backend
            with test_db.cursor() as cur:
                # Get the PID of conn1
                with conn1.cursor() as cur1:
                    cur1.execute("SELECT pg_backend_pid()")
                    result = cur1.fetchone()
                    pid = result[0] if result else None

                if pid:
                    # Terminate the backend
                    cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
                    test_db.commit()

        # Small delay for cleanup
        time.sleep(0.2)

        # Lock should now be released
        assert lock2.is_locked() is False

        # Should be able to acquire
        with lock2.acquire():
            assert lock2.lock_held is True

    def test_multiple_sequential_acquisitions(self, test_db):
        """Test that lock can be acquired and released multiple times."""
        lock = MigrationLock(test_db)

        for i in range(5):
            with lock.acquire():
                assert lock.lock_held is True
            assert lock.lock_held is False

    def test_exception_in_critical_section_releases_lock(self, test_db, second_connection):
        """Test that exception in critical section still releases lock."""
        lock1 = MigrationLock(test_db)
        lock2 = MigrationLock(second_connection, LockConfig(timeout_ms=1000))

        try:
            with lock1.acquire():
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # Lock should be released, second connection should acquire
        with lock2.acquire():
            assert lock2.lock_held is True
