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
import os
import socket
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psycopg

logger = logging.getLogger(__name__)

# Diagnostic metadata table written under the advisory lock (issue #147).
# Correctness never depends on it — the advisory lock is the mutex; this row is
# best-effort identity for contenders to read.
LOCK_HOLDER_TABLE = "confiture_lock_holder"


@dataclass(frozen=True)
class LockIdentity:
    """Identity of a process acquiring the migration lock (issue #147).

    ``acquired_at`` is intentionally absent here — it is set by the database
    (server clock) when the metadata row is written, not by the client.
    """

    pid: int
    hostname: str
    command: str
    user: str | None = None


@dataclass(frozen=True)
class LockHolder:
    """Who holds the migration lock, merged from metadata + pg_stat_activity.

    ``held_for_seconds`` is computed at read time (``now() - acquired_at``).
    ``live`` reflects whether the holder pid is still in ``pg_stat_activity`` —
    a stale metadata row (holder crashed) reads ``live=False``.
    """

    pid: int | None
    hostname: str | None
    user: str | None
    command: str | None
    acquired_at: str | None
    held_for_seconds: int | None
    live: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Public holder contract (the #145 envelope's details.holder)."""
        return {
            "pid": self.pid,
            "hostname": self.hostname,
            "user": self.user,
            "command": self.command,
            "acquired_at": self.acquired_at,
            "held_for_seconds": self.held_for_seconds,
        }


def _holder_phrase(holder: "LockHolder | None") -> str:
    """A short ' Held by ...' clause for the human error message (#147).

    Empty when no identity is available (graceful degradation).
    """
    if holder is None or holder.pid is None:
        return " Holder identity unavailable (no metadata recorded)."
    parts = [f" Held by pid {holder.pid}"]
    if holder.hostname:
        parts.append(f" on {holder.hostname}")
    if holder.command:
        parts.append(f' running "{holder.command}"')
    if holder.held_for_seconds is not None:
        parts.append(f"; acquired {holder.held_for_seconds}s ago")
    if not holder.live:
        parts.append(" (holder process is gone — likely a stale lock)")
    return "".join(parts) + "."


def collect_lock_identity(command: str | None) -> LockIdentity:
    """Collect this process's identity for the lock metadata row.

    Args:
        command: The confiture command being run (e.g. "confiture migrate up").
            Passed explicitly by the CLI — never derived from argv, so a DSN
            never leaks into the lock metadata. Falls back to "confiture".

    Returns:
        A LockIdentity with pid, hostname, and command. ``user`` is left to the
        DB session (filled in at read time); ``acquired_at`` is DB-set.
    """
    return LockIdentity(
        pid=os.getpid(),
        hostname=socket.gethostname(),
        command=command or "confiture",
    )


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
    command: str | None = None  # confiture command for the lock-holder metadata (#147)


class LockAcquisitionError(Exception):
    """Raised when lock cannot be acquired.

    Attributes:
        timeout: True if the error was due to timeout, False otherwise
        holder: Identity of the current lock holder (issue #147), or None when
            unavailable (no metadata table / lock just released).
    """

    def __init__(
        self,
        message: str,
        timeout: bool = False,
        holder: "LockHolder | None" = None,
    ):
        super().__init__(message)
        self.timeout = timeout
        self.holder = holder


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
        # Best-effort diagnostic identity (#147) — never blocks the migration.
        self._write_holder_metadata(lock_id)

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
                holder = self._safe_read_lock_holder()
                raise LockAcquisitionError(
                    f"Could not acquire migration lock within {timeout_sec}s.{_holder_phrase(holder)} "
                    "Use --no-lock to bypass (dangerous in multi-pod environments).",
                    timeout=True,
                    holder=holder,
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
                # Identify who holds the lock (issue #147).
                holder = self._safe_read_lock_holder()
                raise LockAcquisitionError(
                    f"Migration lock is held by another process.{_holder_phrase(holder)} "
                    "Try again later or use blocking mode with --lock-timeout.",
                    timeout=False,
                    holder=holder,
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
            # Best-effort: clear the diagnostic identity row (#147).
            self._clear_holder_metadata(lock_id)

    # ------------------------------------------------------------------ #
    # Lock-holder identity metadata (issue #147) — diagnostic, best-effort #
    # ------------------------------------------------------------------ #

    def _write_holder_metadata(self, lock_id: int) -> None:
        """Record who holds the lock so contenders can read it.

        Best-effort: a metadata write failure (missing privileges, etc.) is
        logged and swallowed — identity is a diagnostic nicety, never a blocker.
        """
        identity = collect_lock_identity(self.config.command)
        try:
            with self.connection.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {LOCK_HOLDER_TABLE} (
                        lock_id BIGINT PRIMARY KEY,
                        pid INT,
                        hostname TEXT,
                        usename TEXT,
                        command TEXT,
                        acquired_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    f"""
                    INSERT INTO {LOCK_HOLDER_TABLE}
                        (lock_id, pid, hostname, usename, command, acquired_at)
                    VALUES (%s, %s, %s, current_user, %s, now())
                    ON CONFLICT (lock_id) DO UPDATE SET
                        pid = EXCLUDED.pid,
                        hostname = EXCLUDED.hostname,
                        usename = EXCLUDED.usename,
                        command = EXCLUDED.command,
                        acquired_at = now()
                    """,  # nosec B608 - LOCK_HOLDER_TABLE is a module constant; all values are parameter-bound
                    (lock_id, identity.pid, identity.hostname, identity.command),
                )
            # Commit so contenders on other connections can see the row. Safe:
            # the lock is acquired before any migration work, so nothing but the
            # (idempotent) initialize + lock + this row is pending here. The
            # session-scoped advisory lock survives the commit.
            self.connection.commit()
        except Exception as e:  # noqa: BLE001 — diagnostics must never block
            logger.warning(f"Could not write lock-holder metadata (id={lock_id}): {e}")
            with contextlib.suppress(Exception):
                self.connection.rollback()

    def _clear_holder_metadata(self, lock_id: int) -> None:
        """Remove this lock's identity row on release (best-effort)."""
        try:
            with self.connection.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {LOCK_HOLDER_TABLE} WHERE lock_id = %s",  # nosec B608 - LOCK_HOLDER_TABLE is a module constant; lock_id is parameter-bound
                    (lock_id,),
                )
            self.connection.commit()
        except Exception as e:  # noqa: BLE001 — diagnostics must never block
            logger.debug(f"Could not clear lock-holder metadata (id={lock_id}): {e}")
            with contextlib.suppress(Exception):
                self.connection.rollback()

    def _safe_read_lock_holder(self) -> "LockHolder | None":
        """read_lock_holder() that never raises (used on the error path)."""
        try:
            return self.read_lock_holder()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Could not read lock-holder metadata: {e}")
            with contextlib.suppress(Exception):
                self.connection.rollback()
            return None

    def read_lock_holder(self) -> "LockHolder | None":
        """Return the current lock holder, merging metadata + live activity.

        Reads the ``confiture_lock_holder`` row (exact command/acquired_at) and
        cross-checks ``pg_stat_activity`` for the pid's liveness. Returns None
        when no identity is recorded (older lock, or no metadata table) — the
        graceful-degradation path the issue requires.
        """
        lock_id = self._get_lock_id()
        with self.connection.cursor() as cur:
            # `live` is derived from pg_locks (is the advisory lock actually
            # held?), not from pid matching: h.pid is the *client* os.getpid(),
            # not a backend pid. A crashed holder auto-releases the advisory
            # lock, so a row whose lock is no longer held is a stale row.
            cur.execute(
                f"""
                SELECT
                    h.pid,
                    h.hostname,
                    h.usename,
                    h.command,
                    h.acquired_at,
                    EXTRACT(EPOCH FROM (now() - h.acquired_at))::bigint AS held_for_seconds,
                    EXISTS (
                        SELECT 1 FROM pg_locks
                        WHERE locktype = 'advisory' AND classid = %s AND objid = %s
                    ) AS live
                FROM {LOCK_HOLDER_TABLE} h
                WHERE h.lock_id = %s
                """,  # nosec B608 - LOCK_HOLDER_TABLE is a module constant; all values are parameter-bound
                (self.DEFAULT_LOCK_NAMESPACE, lock_id, lock_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return LockHolder(
            pid=row[0],
            hostname=row[1],
            user=row[2],
            command=row[3],
            acquired_at=row[4].isoformat() if row[4] else None,
            held_for_seconds=int(row[5]) if row[5] is not None else None,
            live=bool(row[6]),
        )

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
