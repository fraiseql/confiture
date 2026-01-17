"""Tests for graceful shutdown signal handling."""

import signal
import threading
from unittest.mock import Mock, patch

from confiture.core.signals import (
    GracefulShutdown,
    MigrationShutdownGuard,
    ShutdownContext,
    ShutdownState,
    add_cleanup,
    get_shutdown_handler,
    register_shutdown,
    set_current_operation,
    set_migration_in_progress,
    should_stop,
)


class TestShutdownContext:
    """Tests for ShutdownContext dataclass."""

    def test_context_creation(self):
        """Test creating shutdown context."""
        ctx = ShutdownContext(
            signal_received="SIGTERM",
            current_operation="applying migration",
            migration_in_progress="001_create_users",
        )
        assert ctx.signal_received == "SIGTERM"
        assert ctx.current_operation == "applying migration"
        assert ctx.migration_in_progress == "001_create_users"
        assert ctx.metadata == {}

    def test_context_with_metadata(self):
        """Test context with metadata."""
        ctx = ShutdownContext(
            signal_received="SIGINT",
            metadata={"key": "value"},
        )
        assert ctx.metadata["key"] == "value"


class TestGracefulShutdown:
    """Tests for GracefulShutdown class."""

    def test_initial_state(self):
        """Test initial shutdown state."""
        shutdown = GracefulShutdown()
        assert shutdown.should_stop is False
        assert shutdown.state == ShutdownState.RUNNING
        assert shutdown.is_running is True

    def test_register_handlers(self):
        """Test registering signal handlers."""
        shutdown = GracefulShutdown()

        with patch("signal.signal") as mock_signal:
            mock_signal.return_value = signal.SIG_DFL
            shutdown.register()

            # Should register SIGTERM and SIGINT
            calls = mock_signal.call_args_list
            signals_registered = [call[0][0] for call in calls]
            assert signal.SIGTERM in signals_registered
            assert signal.SIGINT in signals_registered

        shutdown.unregister()

    def test_register_twice_warns(self):
        """Test registering twice logs warning."""
        shutdown = GracefulShutdown()

        with patch("signal.signal"):
            shutdown.register()
            result = shutdown.register()  # Should warn but succeed

            assert result is shutdown

        shutdown.unregister()

    def test_unregister_restores_handlers(self):
        """Test unregistering restores original handlers."""
        shutdown = GracefulShutdown()
        original_handler = Mock()

        with patch("signal.signal", return_value=original_handler) as mock_signal:
            shutdown.register()
            shutdown.unregister()

            # Should restore original handlers
            restore_calls = [
                call for call in mock_signal.call_args_list if call[0][1] == original_handler
            ]
            assert len(restore_calls) >= 2

    def test_add_cleanup_handler(self):
        """Test adding cleanup handlers."""
        shutdown = GracefulShutdown()
        handler = Mock()

        shutdown.add_cleanup(handler)

        # Verify handler is stored
        assert len(shutdown._cleanup_handlers) == 1

    def test_add_cleanup_with_priority(self):
        """Test cleanup handlers respect priority."""
        shutdown = GracefulShutdown()
        results = []

        def handler1(ctx):
            results.append("handler1")

        def handler2(ctx):
            results.append("handler2")

        def handler3(ctx):
            results.append("handler3")

        shutdown.add_cleanup(handler1, priority=1)
        shutdown.add_cleanup(handler2, priority=10)  # Should run first
        shutdown.add_cleanup(handler3, priority=5)

        # Trigger cleanup
        ctx = ShutdownContext(signal_received="SIGTERM")
        shutdown._run_cleanup_handlers(ctx)

        assert results == ["handler2", "handler3", "handler1"]

    def test_remove_cleanup_handler(self):
        """Test removing cleanup handlers."""
        shutdown = GracefulShutdown()
        handler = Mock()

        shutdown.add_cleanup(handler)
        result = shutdown.remove_cleanup(handler)

        assert result is True
        assert len(shutdown._cleanup_handlers) == 0

    def test_remove_nonexistent_handler(self):
        """Test removing handler that doesn't exist."""
        shutdown = GracefulShutdown()
        handler = Mock()

        result = shutdown.remove_cleanup(handler)

        assert result is False

    def test_set_current_operation(self):
        """Test setting current operation."""
        shutdown = GracefulShutdown()
        shutdown.set_current_operation("running migration")

        assert shutdown._current_operation == "running migration"

    def test_set_migration_in_progress(self):
        """Test setting migration in progress."""
        shutdown = GracefulShutdown()
        shutdown.set_migration_in_progress("001_create_users")

        assert shutdown._migration_in_progress == "001_create_users"

    def test_request_shutdown(self):
        """Test programmatic shutdown request."""
        shutdown = GracefulShutdown()
        handler = Mock()
        shutdown.add_cleanup(handler)

        shutdown.request_shutdown()

        assert shutdown.should_stop is True
        assert shutdown.state == ShutdownState.STOPPED
        handler.assert_called_once()

    def test_request_shutdown_passes_context(self):
        """Test shutdown context is passed to handlers."""
        shutdown = GracefulShutdown()
        shutdown.set_current_operation("testing")
        shutdown.set_migration_in_progress("001_test")

        received_context = None

        def handler(ctx):
            nonlocal received_context
            received_context = ctx

        shutdown.add_cleanup(handler)
        shutdown.request_shutdown()

        assert received_context is not None
        assert received_context.signal_received == "SIGTERM"
        assert received_context.current_operation == "testing"
        assert received_context.migration_in_progress == "001_test"

    def test_cleanup_handler_exception_logged(self):
        """Test exceptions in cleanup handlers are logged."""
        shutdown = GracefulShutdown()

        def bad_handler(ctx):
            raise ValueError("Handler error")

        shutdown.add_cleanup(bad_handler)

        # Should not raise, just log
        shutdown.request_shutdown()

        assert shutdown.state == ShutdownState.STOPPED

    def test_context_manager(self):
        """Test context manager usage."""
        with patch("signal.signal"):
            with GracefulShutdown() as shutdown:
                assert shutdown._registered is True

            # Should be unregistered after exiting
            assert shutdown._registered is False

    def test_double_signal_ignored(self):
        """Test receiving signal twice is handled."""
        shutdown = GracefulShutdown()
        call_count = 0

        def handler(ctx):
            nonlocal call_count
            call_count += 1

        shutdown.add_cleanup(handler)

        # First signal
        shutdown._handle_signal(signal.SIGTERM, None)
        # Second signal (should be ignored)
        shutdown._handle_signal(signal.SIGTERM, None)

        assert call_count == 1


class TestGlobalShutdownFunctions:
    """Tests for global shutdown functions."""

    def test_get_shutdown_handler_singleton(self):
        """Test get_shutdown_handler returns same instance."""
        import confiture.core.signals as signals_module

        # Reset global
        signals_module._shutdown = None

        handler1 = get_shutdown_handler()
        handler2 = get_shutdown_handler()

        assert handler1 is handler2

    def test_register_shutdown(self):
        """Test register_shutdown function."""
        import confiture.core.signals as signals_module

        signals_module._shutdown = None

        with patch("signal.signal"):
            shutdown = register_shutdown()
            assert shutdown._registered is True
            shutdown.unregister()

    def test_add_cleanup_global(self):
        """Test add_cleanup adds to global handler."""
        import confiture.core.signals as signals_module

        signals_module._shutdown = None
        handler = Mock()

        add_cleanup(handler)

        shutdown = get_shutdown_handler()
        assert len(shutdown._cleanup_handlers) == 1

    def test_should_stop_global(self):
        """Test should_stop checks global handler."""
        import confiture.core.signals as signals_module

        signals_module._shutdown = None

        assert should_stop() is False

        shutdown = get_shutdown_handler()
        shutdown._should_stop = True

        assert should_stop() is True

    def test_set_current_operation_global(self):
        """Test set_current_operation on global handler."""
        import confiture.core.signals as signals_module

        signals_module._shutdown = None

        set_current_operation("testing")

        shutdown = get_shutdown_handler()
        assert shutdown._current_operation == "testing"

    def test_set_migration_in_progress_global(self):
        """Test set_migration_in_progress on global handler."""
        import confiture.core.signals as signals_module

        signals_module._shutdown = None

        set_migration_in_progress("001_test")

        shutdown = get_shutdown_handler()
        assert shutdown._migration_in_progress == "001_test"


class TestMigrationShutdownGuard:
    """Tests for MigrationShutdownGuard."""

    def test_guard_sets_migration_in_progress(self):
        """Test guard sets migration in progress."""
        import confiture.core.signals as signals_module

        signals_module._shutdown = None

        with MigrationShutdownGuard("001_create_users"):
            shutdown = get_shutdown_handler()
            assert shutdown._migration_in_progress == "001_create_users"

        assert shutdown._migration_in_progress is None

    def test_guard_releases_lock_on_shutdown(self):
        """Test guard releases lock on shutdown."""
        import confiture.core.signals as signals_module

        signals_module._shutdown = None

        mock_lock = Mock()
        mock_lock.release = Mock()

        guard = MigrationShutdownGuard("001_test", lock=mock_lock)
        guard.__enter__()

        # Simulate shutdown
        shutdown = get_shutdown_handler()
        shutdown.request_shutdown()

        mock_lock.release.assert_called_once()

    def test_guard_releases_lock_with_release_lock_method(self):
        """Test guard releases lock using _release_lock method."""
        import confiture.core.signals as signals_module

        signals_module._shutdown = None

        mock_lock = Mock(spec=["_release_lock"])
        mock_lock._release_lock = Mock()

        guard = MigrationShutdownGuard("001_test", lock=mock_lock)
        guard.__enter__()

        shutdown = get_shutdown_handler()
        shutdown.request_shutdown()

        mock_lock._release_lock.assert_called_once()

    def test_guard_rollbacks_connection_on_shutdown(self):
        """Test guard rolls back connection on shutdown."""
        import confiture.core.signals as signals_module

        signals_module._shutdown = None

        mock_conn = Mock()
        mock_conn.rollback = Mock()

        guard = MigrationShutdownGuard("001_test", connection=mock_conn)
        guard.__enter__()

        shutdown = get_shutdown_handler()
        shutdown.request_shutdown()

        mock_conn.rollback.assert_called_once()

    def test_guard_check_shutdown(self):
        """Test guard check_shutdown method."""
        import confiture.core.signals as signals_module

        signals_module._shutdown = None

        guard = MigrationShutdownGuard("001_test")

        with guard:
            assert guard.check_shutdown() is False

            shutdown = get_shutdown_handler()
            shutdown._should_stop = True

            assert guard.check_shutdown() is True

    def test_guard_handles_lock_release_error(self):
        """Test guard handles lock release errors gracefully."""
        import confiture.core.signals as signals_module

        signals_module._shutdown = None

        mock_lock = Mock()
        mock_lock.release = Mock(side_effect=RuntimeError("Lock error"))

        guard = MigrationShutdownGuard("001_test", lock=mock_lock)
        guard.__enter__()

        # Should not raise
        shutdown = get_shutdown_handler()
        shutdown.request_shutdown()

        mock_lock.release.assert_called_once()

    def test_guard_handles_connection_rollback_error(self):
        """Test guard handles connection rollback errors gracefully."""
        import confiture.core.signals as signals_module

        signals_module._shutdown = None

        mock_conn = Mock()
        mock_conn.rollback = Mock(side_effect=RuntimeError("Rollback error"))

        guard = MigrationShutdownGuard("001_test", connection=mock_conn)
        guard.__enter__()

        # Should not raise
        shutdown = get_shutdown_handler()
        shutdown.request_shutdown()

        mock_conn.rollback.assert_called_once()


class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_cleanup_additions(self):
        """Test adding cleanup handlers from multiple threads."""
        shutdown = GracefulShutdown()
        handlers_added = []

        def add_handlers():
            for _ in range(10):
                handler = Mock()
                shutdown.add_cleanup(handler)
                handlers_added.append(handler)

        threads = [threading.Thread(target=add_handlers) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(shutdown._cleanup_handlers) == 50

    def test_shutdown_while_adding_handlers(self):
        """Test shutdown during handler registration."""
        shutdown = GracefulShutdown()
        handlers_called = []

        def add_handlers():
            for _ in range(100):
                handler = Mock(side_effect=lambda ctx: handlers_called.append(1))
                shutdown.add_cleanup(handler)

        thread = threading.Thread(target=add_handlers)
        thread.start()

        # Request shutdown while adding
        shutdown.request_shutdown()
        thread.join()

        # Should complete without errors
        assert shutdown.state == ShutdownState.STOPPED
