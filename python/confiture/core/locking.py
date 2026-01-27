"""Distributed locking for migration coordination.

Uses PostgreSQL advisory locks to ensure only one migration
process runs at a time across all application instances.

This is critical for Kubernetes/multi-pod deployments where
multiple pods may start simultaneously and attempt to run migrations.

PostgreSQL advisory locks are:
- Session-scoped (auto-release on disconnect)
- Reentrant (same session can acquire multiple times)
- Database-scoped (different databases = different locks)
"""

import contextlib
import hashlib
import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg

logger = logging.getLogger(__name__)


class LockMode(Enum):
    """Lock acquisition modes."""

    BLOCKING = "blocking"  # Wait until lock available
    NON_BLOCKING = "non_blocking"  # Return immediately if locked


@dataclass
class LockConfig:
    """Configuration for migration locking.

    Attributes:
        enabled: Whether locking is enabled (default: True)
        timeout_ms: Lock acquisition timeout in milliseconds (default: 30000)
        lock_id: Custom lock ID (auto-generated from database name if None)
        mode: Lock acquisition mode (blocking or non-blocking)

    Example:
        >>> config = LockConfig(timeout_ms=60000)  # 1 minute timeout
        >>> config = LockConfig(enabled=False)  # Disable locking
        >>> config = LockConfig(mode=LockMode.NON_BLOCKING)  # Fail fast
    """

    enabled: bool = True
    timeout_ms: int = 30000  # 30 seconds default
    lock_id: int | None = None  # Custom lock ID (auto-generated if None)
    mode: LockMode = field(default=LockMode.BLOCKING)


class LockAcquisitionError(Exception):
    """Raised when lock cannot be acquired.

    Attributes:
        timeout: True if the error was due to timeout, False otherwise
    """

    def __init__(self, message: str, timeout: bool = False):
        super().__init__(message)
        self.timeout = timeout


class MigrationLock:
    """Manages distributed locks for migration execution.

    Uses PostgreSQL advisory locks which are:
    - Session-scoped (auto-release on disconnect)
    - Reentrant (same session can acquire multiple times)
    - Database-scoped (different databases = different locks)

    Advisory locks use two 32-bit integers: (classid, objid).
    We use a fixed namespace (classid) and a database-specific objid.

    Example:
        >>> import psycopg
        >>> conn = psycopg.connect('postgresql://localhost/mydb')
        >>> lock = MigrationLock(conn)
        >>> with lock.acquire():
        ...     # Run migrations here - guaranteed exclusive access
        ...     migrator.migrate_up()

        >>> # Non-blocking mode
        >>> lock = MigrationLock(conn, LockConfig(mode=LockMode.NON_BLOCKING))
        >>> try:
        ...     with lock.acquire():
        ...         migrator.migrate_up()
        ... except LockAcquisitionError:
        ...     print("Another migration is running, skipping")
    """

    # Default lock namespace (first 32 bits of SHA256("tb_confiture"))
    DEFAULT_LOCK_NAMESPACE = 1751936052

    def __init__(
        self,
        connection: "psycopg.Connection",
        config: LockConfig | None = None,
    ):
        """Initialize migration lock.

        Args:
            connection: psycopg3 database connection
            config: Lock configuration (uses defaults if None)
        """
        self.connection = connection
        self.config = config or LockConfig()
        self._lock_held = False
        self._lock_id: int | None = None

    def _get_lock_id(self) -> int:
        """Get or generate the lock ID.

        Returns:
            Lock ID integer (32-bit positive)
        """
        if self._lock_id is not None:
            return self._lock_id

        if self.config.lock_id is not None:
            self._lock_id = self.config.lock_id
        else:
            self._lock_id = self._generate_lock_id()

        return self._lock_id

    def _generate_lock_id(self) -> int:
        """Generate deterministic lock ID from database name.

        The lock ID is derived from the database name to ensure
        each database has its own lock scope.

        Returns:
            32-bit positive integer lock ID
        """
        # Get database name from connection
        with self.connection.cursor() as cur:
            cur.execute("SELECT current_database()")
            result = cur.fetchone()
            db_name = result[0] if result else "unknown"

        # Hash to 32-bit positive integer
        hash_bytes = hashlib.sha256(db_name.encode()).digest()
        return int.from_bytes(hash_bytes[:4], "big") & 0x7FFFFFFF

    @contextmanager
    def acquire(self) -> Generator[None, None, None]:
        """Context manager for lock acquisition.

        Acquires the lock on entry and releases it on exit (even if an
        exception occurs). The lock is also automatically released if
        the database connection drops.

        Yields:
            None - lock is held while in context

        Raises:
            LockAcquisitionError: If lock cannot be acquired

        Example:
            >>> with lock.acquire():
            ...     # Exclusive access guaranteed here
            ...     run_migrations()
            # Lock automatically released here
        """
        if not self.config.enabled:
            logger.debug("Locking disabled, skipping lock acquisition")
            yield
            return

        try:
            self._acquire_lock()
            yield
        finally:
            self._release_lock()

    def _acquire_lock(self) -> None:
        """Acquire the advisory lock.

        Raises:
            LockAcquisitionError: If lock cannot be acquired
        """
        lock_id = self._get_lock_id()

        if self.config.mode == LockMode.NON_BLOCKING:
            self._acquire_non_blocking(lock_id)
        else:
            self._acquire_blocking(lock_id)

        self._lock_held = True
        logger.info(
            f"Acquired migration lock (namespace={self.DEFAULT_LOCK_NAMESPACE}, id={lock_id})"
        )

    def _acquire_blocking(self, lock_id: int) -> None:
        """Acquire lock with timeout.

        Uses SET LOCAL statement_timeout to implement lock timeout.
        This setting only affects the current transaction.

        Args:
            lock_id: Lock object ID

        Raises:
            LockAcquisitionError: If timeout expires
        """
        import psycopg

        timeout_sec = self.config.timeout_ms / 1000

        with self.connection.cursor() as cur:
            # Set statement timeout for lock acquisition
            # Using string formatting for timeout is safe (integer value)
            cur.execute(f"SET LOCAL statement_timeout = '{self.config.timeout_ms}ms'")

            try:
                cur.execute(
                    "SELECT pg_advisory_lock(%s, %s)",
                    (self.DEFAULT_LOCK_NAMESPACE, lock_id),
                )
                # Reset statement timeout on success
                cur.execute("SET LOCAL statement_timeout = '0'")
            except psycopg.errors.QueryCanceled as e:
                # Rollback the failed transaction to clear the error state
                with contextlib.suppress(Exception):
                    self.connection.rollback()
                raise LockAcquisitionError(
                    f"Could not acquire migration lock within {timeout_sec}s. "
                    "Another migration may be running. "
                    "Use --no-lock to bypass (dangerous in multi-pod environments).",
                    timeout=True,
                ) from e

    def _acquire_non_blocking(self, lock_id: int) -> None:
        """Try to acquire lock without waiting.

        Uses pg_try_advisory_lock which returns immediately with
        true (acquired) or false (locked by another session).

        Args:
            lock_id: Lock object ID

        Raises:
            LockAcquisitionError: If lock is held by another process
        """
        with self.connection.cursor() as cur:
            cur.execute(
                "SELECT pg_try_advisory_lock(%s, %s)",
                (self.DEFAULT_LOCK_NAMESPACE, lock_id),
            )
            result = cur.fetchone()
            acquired = result[0] if result else False

            if not acquired:
                # Get information about who holds the lock
                holder = self.get_lock_holder()
                holder_info = ""
                if holder:
                    holder_info = (
                        f" Held by PID {holder['pid']}"
                        f" ({holder['application'] or 'unknown app'})"
                        f" since {holder['started_at']}"
                    )

                raise LockAcquisitionError(
                    f"Migration lock is held by another process.{holder_info} "
                    "Try again later or use blocking mode with --lock-timeout.",
                    timeout=False,
                )

    def _release_lock(self) -> None:
        """Release the advisory lock.

        Safe to call even if lock was not acquired (no-op in that case).
        Logs a warning if release fails but does not raise an exception
        since the lock will be released when the connection closes anyway.
        """
        if not self._lock_held:
            return

        lock_id = self._get_lock_id()

        try:
            with self.connection.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_unlock(%s, %s)",
                    (self.DEFAULT_LOCK_NAMESPACE, lock_id),
                )
                result = cur.fetchone()
                unlocked = result[0] if result else False

                if unlocked:
                    logger.info(f"Released migration lock (id={lock_id})")
                else:
                    logger.warning(
                        f"Lock release returned false (id={lock_id}) - lock may not have been held"
                    )

        except Exception as e:
            # Don't raise - lock will be released when connection closes
            logger.warning(f"Error releasing lock (id={lock_id}): {e}")
        finally:
            self._lock_held = False

    def is_locked(self) -> bool:
        """Check if migration lock is currently held (by any process).

        This can be used to check if another migration is running
        before attempting to acquire the lock.

        Returns:
            True if lock is held, False otherwise
        """
        lock_id = self._get_lock_id()

        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_locks
                    WHERE locktype = 'advisory'
                    AND classid = %s
                    AND objid = %s
                )
            """,
                (self.DEFAULT_LOCK_NAMESPACE, lock_id),
            )
            result = cur.fetchone()
            return result[0] if result else False

    def get_lock_holder(self) -> dict | None:
        """Get information about the current lock holder.

        Useful for diagnostics when a lock cannot be acquired.

        Returns:
            Dictionary with lock holder info, or None if lock not held:
            - pid: Process ID holding the lock
            - user: Database username
            - application: Application name (from connection)
            - client_addr: Client IP address
            - started_at: When the session started
        """
        lock_id = self._get_lock_id()

        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    l.pid,
                    a.usename,
                    a.application_name,
                    a.client_addr,
                    a.backend_start
                FROM pg_locks l
                JOIN pg_stat_activity a ON l.pid = a.pid
                WHERE l.locktype = 'advisory'
                AND l.classid = %s
                AND l.objid = %s
            """,
                (self.DEFAULT_LOCK_NAMESPACE, lock_id),
            )
            result = cur.fetchone()

            if result:
                return {
                    "pid": result[0],
                    "user": result[1],
                    "application": result[2],
                    "client_addr": str(result[3]) if result[3] else None,
                    "started_at": result[4],
                }
            return None

    @property
    def lock_held(self) -> bool:
        """Check if this instance currently holds the lock.

        Returns:
            True if this instance holds the lock, False otherwise
        """
        return self._lock_held
