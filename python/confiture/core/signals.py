"""Signal handling for graceful shutdown.

Provides utilities for graceful shutdown in containerized environments,
particularly for Kubernetes which sends SIGTERM before killing pods.
"""

import logging
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ShutdownState(Enum):
    """State of the shutdown handler."""

    RUNNING = "running"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


@dataclass
class ShutdownContext:
    """Context passed to cleanup handlers."""

    signal_received: str
    current_operation: str | None = None
    migration_in_progress: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class GracefulShutdown:
    """Handle graceful shutdown signals.

    Registers signal handlers for SIGTERM and SIGINT to enable
    graceful shutdown in containerized environments.

    Example:
        >>> shutdown = GracefulShutdown()
        >>> shutdown.register()
        >>> shutdown.add_cleanup(lambda ctx: print("Cleaning up..."))
        >>> while not shutdown.should_stop:
        ...     # Do work
        ...     pass

    Note:
        In Kubernetes, pods receive SIGTERM before being killed.
        This handler allows migrations to complete the current
        operation before exiting.
    """

    def __init__(self, timeout: float = 30.0):
        """Initialize graceful shutdown handler.

        Args:
            timeout: Maximum seconds to wait for cleanup handlers
        """
        self._should_stop = False
        self._state = ShutdownState.RUNNING
        self._cleanup_handlers: list[Callable[[ShutdownContext], None]] = []
        self._current_operation: str | None = None
        self._migration_in_progress: str | None = None
        self._timeout = timeout
        self._lock = threading.Lock()
        self._registered = False
        self._original_handlers: dict[int, Any] = {}

    @property
    def should_stop(self) -> bool:
        """Check if shutdown has been requested."""
        return self._should_stop

    @property
    def state(self) -> ShutdownState:
        """Get current shutdown state."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Check if still in running state."""
        return self._state == ShutdownState.RUNNING

    def register(self) -> "GracefulShutdown":
        """Register signal handlers.

        Returns:
            Self for chaining
        """
        if self._registered:
            logger.warning("Graceful shutdown handlers already registered")
            return self

        # Store original handlers
        self._original_handlers[signal.SIGTERM] = signal.signal(
            signal.SIGTERM, self._handle_signal
        )
        self._original_handlers[signal.SIGINT] = signal.signal(
            signal.SIGINT, self._handle_signal
        )

        self._registered = True
        logger.info("Graceful shutdown handlers registered")
        return self

    def unregister(self) -> None:
        """Restore original signal handlers."""
        if not self._registered:
            return

        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)

        self._original_handlers.clear()
        self._registered = False
        logger.info("Graceful shutdown handlers unregistered")

    def add_cleanup(
        self, handler: Callable[[ShutdownContext], None], priority: int = 0
    ) -> None:
        """Add cleanup handler to run on shutdown.

        Args:
            handler: Callable that receives ShutdownContext
            priority: Higher priority handlers run first (default: 0)

        Example:
            >>> def release_lock(ctx):
            ...     print(f"Releasing lock during {ctx.signal_received}")
            >>> shutdown.add_cleanup(release_lock, priority=10)
        """
        with self._lock:
            # Insert maintaining priority order (highest first)
            self._cleanup_handlers.append((priority, handler))
            self._cleanup_handlers.sort(key=lambda x: -x[0])

    def remove_cleanup(self, handler: Callable[[ShutdownContext], None]) -> bool:
        """Remove a cleanup handler.

        Args:
            handler: The handler to remove

        Returns:
            True if handler was found and removed
        """
        with self._lock:
            for i, (_, h) in enumerate(self._cleanup_handlers):
                if h == handler:
                    self._cleanup_handlers.pop(i)
                    return True
        return False

    def set_current_operation(self, operation: str | None) -> None:
        """Set the current operation being performed.

        Args:
            operation: Description of current operation, or None if idle
        """
        self._current_operation = operation

    def set_migration_in_progress(self, migration: str | None) -> None:
        """Set the current migration being executed.

        Args:
            migration: Migration name/version, or None if not migrating
        """
        self._migration_in_progress = migration

    def _handle_signal(self, signum: int, frame: Any) -> None:  # noqa: ARG002
        """Handle shutdown signal.

        Args:
            signum: Signal number
            frame: Current stack frame
        """
        sig_name = signal.Signals(signum).name
        logger.warning(f"Received {sig_name}, initiating graceful shutdown...")

        with self._lock:
            if self._state != ShutdownState.RUNNING:
                logger.warning(f"Already in {self._state.value} state, ignoring signal")
                return

            self._should_stop = True
            self._state = ShutdownState.SHUTTING_DOWN

        # Create context for cleanup handlers
        context = ShutdownContext(
            signal_received=sig_name,
            current_operation=self._current_operation,
            migration_in_progress=self._migration_in_progress,
        )

        # Run cleanup handlers
        self._run_cleanup_handlers(context)

        self._state = ShutdownState.STOPPED
        logger.info("Graceful shutdown complete")

    def _run_cleanup_handlers(self, context: ShutdownContext) -> None:
        """Run all registered cleanup handlers.

        Args:
            context: Shutdown context to pass to handlers
        """
        with self._lock:
            handlers = list(self._cleanup_handlers)

        for priority, handler in handlers:
            try:
                logger.debug(f"Running cleanup handler (priority={priority})")
                handler(context)
            except Exception as e:
                logger.error(f"Cleanup handler failed: {e}")

    def request_shutdown(self) -> None:
        """Programmatically request shutdown.

        Useful for testing or triggering shutdown from code.
        """
        self._handle_signal(signal.SIGTERM, None)

    def __enter__(self) -> "GracefulShutdown":
        """Context manager entry."""
        return self.register()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.unregister()


# Global instance for convenience
_shutdown: GracefulShutdown | None = None


def get_shutdown_handler() -> GracefulShutdown:
    """Get or create the global shutdown handler.

    Returns:
        Global GracefulShutdown instance
    """
    global _shutdown
    if _shutdown is None:
        _shutdown = GracefulShutdown()
    return _shutdown


def register_shutdown() -> GracefulShutdown:
    """Register and return global shutdown handler.

    Returns:
        Registered GracefulShutdown instance

    Example:
        >>> shutdown = register_shutdown()
        >>> shutdown.add_cleanup(my_cleanup_func)
    """
    return get_shutdown_handler().register()


def add_cleanup(
    handler: Callable[[ShutdownContext], None], priority: int = 0
) -> None:
    """Add cleanup handler to global shutdown handler.

    Args:
        handler: Cleanup function receiving ShutdownContext
        priority: Higher priority handlers run first
    """
    get_shutdown_handler().add_cleanup(handler, priority)


def should_stop() -> bool:
    """Check if shutdown has been requested.

    Returns:
        True if shutdown is in progress
    """
    return get_shutdown_handler().should_stop


def set_current_operation(operation: str | None) -> None:
    """Set current operation on global handler.

    Args:
        operation: Description of current operation
    """
    get_shutdown_handler().set_current_operation(operation)


def set_migration_in_progress(migration: str | None) -> None:
    """Set current migration on global handler.

    Args:
        migration: Migration name/version
    """
    get_shutdown_handler().set_migration_in_progress(migration)


class MigrationShutdownGuard:
    """Context manager for safe migration execution.

    Tracks migration state and ensures clean shutdown if
    interrupted mid-migration.

    Example:
        >>> with MigrationShutdownGuard("001_create_users", lock, connection):
        ...     migration.up()
    """

    def __init__(
        self,
        migration_name: str,
        lock: Any | None = None,
        connection: Any | None = None,
    ):
        """Initialize migration guard.

        Args:
            migration_name: Name of the migration being run
            lock: Optional lock to release on shutdown
            connection: Optional connection to rollback on shutdown
        """
        self.migration_name = migration_name
        self.lock = lock
        self.connection = connection
        self._shutdown = get_shutdown_handler()
        self._cleanup_registered = False

    def __enter__(self) -> "MigrationShutdownGuard":
        """Enter migration context."""
        self._shutdown.set_migration_in_progress(self.migration_name)

        # Register cleanup handler
        def cleanup(ctx: ShutdownContext) -> None:  # noqa: ARG001
            logger.warning(
                f"Shutdown during migration {self.migration_name}, cleaning up..."
            )

            # Release lock if held
            if self.lock is not None:
                try:
                    if hasattr(self.lock, "release"):
                        self.lock.release()
                    elif hasattr(self.lock, "_release_lock"):
                        self.lock._release_lock()
                    logger.info("Lock released during shutdown")
                except Exception as e:
                    logger.error(f"Failed to release lock: {e}")

            # Rollback connection if in transaction
            if self.connection is not None:
                try:
                    self.connection.rollback()
                    logger.info("Transaction rolled back during shutdown")
                except Exception as e:
                    logger.error(f"Failed to rollback transaction: {e}")

        self._shutdown.add_cleanup(cleanup, priority=100)
        self._cleanup_registered = True

        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit migration context."""
        self._shutdown.set_migration_in_progress(None)

        # Note: We don't remove the cleanup handler here because
        # if shutdown is in progress, it may still need to run.
        # Handlers are cleared when the process exits anyway.

    def check_shutdown(self) -> bool:
        """Check if shutdown was requested.

        Returns:
            True if should stop
        """
        return self._shutdown.should_stop
