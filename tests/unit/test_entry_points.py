"""Unit tests for entry points support in HookRegistry (Phase 4.2.1).

This test suite validates that the HookRegistry can discover and load hooks
from setuptools entry points, enabling third-party hook packages.
"""

from unittest.mock import Mock, patch, MagicMock
import pytest

from confiture.core.hooks import Hook, HookPhase, HookRegistry, HookResult, HookContext


class TestHookRegistryEntryPoints:
    """Test suite for entry points support in HookRegistry."""

    def test_hook_registry_has_load_entry_points_method(self):
        """HookRegistry should have _load_entry_points method."""
        registry = HookRegistry()
        assert hasattr(registry, "_load_entry_points")
        assert callable(registry._load_entry_points)

    def test_load_entry_points_called_on_init(self):
        """HookRegistry should call _load_entry_points during initialization."""
        with patch.object(HookRegistry, "_load_entry_points") as mock_load:
            registry = HookRegistry()
            mock_load.assert_called_once()

    def test_load_entry_points_discovers_entry_points(self):
        """HookRegistry._load_entry_points should discover hooks from entry_points."""
        # Create a mock hook class
        class CustomHook(Hook):
            phase = HookPhase.AFTER_DDL

            def execute(self, conn, context):
                return HookResult(
                    phase="AFTER_DDL",
                    hook_name="CustomHook",
                    rows_affected=0,
                )

        # Create mock entry point
        mock_ep = Mock()
        mock_ep.name = "custom_hook"
        mock_ep.load.return_value = CustomHook

        # Mock the entry_points function
        with patch("confiture.core.hooks.entry_points") as mock_entry_points:
            mock_entry_points.return_value = [mock_ep]

            registry = HookRegistry()
            # The hook should be registered
            assert registry.get("custom_hook") is CustomHook

    def test_load_entry_points_handles_missing_entry_points(self):
        """HookRegistry should handle case where no entry points are defined."""
        with patch("confiture.core.hooks.entry_points") as mock_entry_points:
            mock_entry_points.return_value = []

            registry = HookRegistry()
            # Should not raise, just create empty registry
            assert registry.list_hooks() == []

    def test_load_entry_points_handles_load_failure_gracefully(self):
        """HookRegistry should handle entry point load failures gracefully."""
        # Create mock entry point that fails to load
        mock_ep = Mock()
        mock_ep.name = "broken_hook"
        mock_ep.load.side_effect = ImportError("Module not found")

        with patch("confiture.core.hooks.entry_points") as mock_entry_points:
            mock_entry_points.return_value = [mock_ep]

            # Should not raise, should log warning
            registry = HookRegistry()
            # Broken hook should not be registered
            assert registry.get("broken_hook") is None

    def test_load_entry_points_handles_type_error_gracefully(self):
        """HookRegistry should handle invalid hook types from entry points."""
        # Create mock entry point that returns non-Hook object
        mock_ep = Mock()
        mock_ep.name = "invalid_hook"
        mock_ep.load.return_value = "not_a_hook_class"

        with patch("confiture.core.hooks.entry_points") as mock_entry_points:
            mock_entry_points.return_value = [mock_ep]

            # Should not raise
            registry = HookRegistry()
            # Invalid hook should not be registered
            assert registry.get("invalid_hook") is None

    def test_load_entry_points_supports_python_3_9_compatibility(self):
        """HookRegistry should support Python 3.9+ entry_points API."""
        # Python 3.10+ uses entry_points(group="...")
        # Python 3.9 and earlier use entry_points().get("...")

        class CustomHook(Hook):
            phase = HookPhase.AFTER_DDL

            def execute(self, conn, context):
                return HookResult(
                    phase="AFTER_DDL",
                    hook_name="CustomHook",
                    rows_affected=0,
                )

        mock_ep = Mock()
        mock_ep.name = "custom_hook"
        mock_ep.load.return_value = CustomHook

        # Mock Python 3.10+ style (with group parameter)
        with patch("confiture.core.hooks.entry_points") as mock_entry_points:
            mock_entry_points.return_value = [mock_ep]

            registry = HookRegistry()
            assert registry.get("custom_hook") is CustomHook

    def test_manual_registration_still_works_with_entry_points(self):
        """Existing manual hook registration should still work with entry points."""
        class ManualHook(Hook):
            phase = HookPhase.BEFORE_DDL

            def execute(self, conn, context):
                return HookResult(
                    phase="BEFORE_DDL",
                    hook_name="ManualHook",
                    rows_affected=0,
                )

        with patch("confiture.core.hooks.entry_points") as mock_entry_points:
            mock_entry_points.return_value = []

            registry = HookRegistry()
            # Manually register a hook
            registry.register("manual_hook", ManualHook)

            # Should be retrievable
            assert registry.get("manual_hook") is ManualHook

    def test_entry_points_and_manual_registration_coexist(self):
        """Entry points hooks and manually registered hooks should coexist."""
        class EntryPointHook(Hook):
            phase = HookPhase.AFTER_DDL

            def execute(self, conn, context):
                return HookResult(
                    phase="AFTER_DDL",
                    hook_name="EntryPointHook",
                    rows_affected=0,
                )

        class ManualHook(Hook):
            phase = HookPhase.BEFORE_DDL

            def execute(self, conn, context):
                return HookResult(
                    phase="BEFORE_DDL",
                    hook_name="ManualHook",
                    rows_affected=0,
                )

        # Create mock entry point
        mock_ep = Mock()
        mock_ep.name = "entry_point_hook"
        mock_ep.load.return_value = EntryPointHook

        with patch("confiture.core.hooks.entry_points") as mock_entry_points:
            mock_entry_points.return_value = [mock_ep]

            registry = HookRegistry()
            # Entry point hook is registered
            assert registry.get("entry_point_hook") is EntryPointHook

            # Manually register another hook
            registry.register("manual_hook", ManualHook)

            # Both should be available
            assert registry.get("entry_point_hook") is EntryPointHook
            assert registry.get("manual_hook") is ManualHook
            assert len(registry.list_hooks()) == 2

    def test_load_entry_points_logs_failures(self):
        """HookRegistry should log entry point load failures."""
        mock_ep = Mock()
        mock_ep.name = "broken_hook"
        mock_ep.load.side_effect = ImportError("Module not found")

        with patch("confiture.core.hooks.entry_points") as mock_entry_points:
            with patch("confiture.core.hooks.logger") as mock_logger:
                mock_entry_points.return_value = [mock_ep]

                registry = HookRegistry()
                # Warning should be logged
                mock_logger.warning.assert_called()

    def test_load_entry_points_with_multiple_hooks(self):
        """HookRegistry should load multiple hooks from entry points."""
        class Hook1(Hook):
            phase = HookPhase.BEFORE_DDL

            def execute(self, conn, context):
                return HookResult(phase="BEFORE_DDL", hook_name="Hook1")

        class Hook2(Hook):
            phase = HookPhase.AFTER_DDL

            def execute(self, conn, context):
                return HookResult(phase="AFTER_DDL", hook_name="Hook2")

        mock_ep1 = Mock()
        mock_ep1.name = "hook_1"
        mock_ep1.load.return_value = Hook1

        mock_ep2 = Mock()
        mock_ep2.name = "hook_2"
        mock_ep2.load.return_value = Hook2

        with patch("confiture.core.hooks.entry_points") as mock_entry_points:
            mock_entry_points.return_value = [mock_ep1, mock_ep2]

            registry = HookRegistry()
            assert registry.get("hook_1") is Hook1
            assert registry.get("hook_2") is Hook2
            assert len(registry.list_hooks()) == 2
