"""Tests for agent context tracking system.

Tests the AgentContext for tracking workflow state, request IDs, and
operation context throughout error handling.
"""

import pytest

from confiture.core.context import AgentContext, get_context, set_context


class TestAgentContextCreation:
    """Test AgentContext initialization."""

    def test_context_creation_minimal(self) -> None:
        """Test creating context with minimal fields."""
        ctx = AgentContext(request_id="req-123")
        assert ctx.request_id == "req-123"

    def test_context_creation_all_fields(self) -> None:
        """Test creating context with all fields."""
        ctx = AgentContext(
            request_id="req-123",
            workflow_stage="migration_up",
            operation_type="apply_migration",
            custom_data={"version": "001"},
        )
        assert ctx.request_id == "req-123"
        assert ctx.workflow_stage == "migration_up"
        assert ctx.operation_type == "apply_migration"
        assert ctx.custom_data == {"version": "001"}

    def test_context_default_values(self) -> None:
        """Test that optional fields have defaults."""
        ctx = AgentContext(request_id="req-123")
        assert ctx.workflow_stage is None
        assert ctx.operation_type is None
        assert ctx.custom_data == {}


class TestContextStorage:
    """Test global context storage."""

    def test_set_and_get_context(self) -> None:
        """Test setting and retrieving context."""
        ctx = AgentContext(request_id="req-123")
        set_context(ctx)

        retrieved = get_context()
        assert retrieved is ctx
        assert retrieved.request_id == "req-123"

    def test_context_is_thread_local(self) -> None:
        """Test that context is thread-local."""
        # In same thread, should work
        ctx = AgentContext(request_id="req-123")
        set_context(ctx)

        # Get should return same context
        assert get_context() is ctx

    def test_get_context_when_none_set(self) -> None:
        """Test getting context when none is set."""
        # Clear context first by setting None
        set_context(None)

        ctx = get_context()
        assert ctx is None


class TestContextManager:
    """Test context manager functionality."""

    def test_context_manager_sets_context(self) -> None:
        """Test that context manager sets context."""
        ctx = AgentContext(request_id="req-123")

        with ctx:
            # Inside context, should be set
            retrieved = get_context()
            assert retrieved is ctx

    def test_context_manager_clears_context(self) -> None:
        """Test that context manager clears context on exit."""
        ctx = AgentContext(request_id="req-123")

        with ctx:
            pass  # Enter and exit

        # After exit, context should be cleared
        retrieved = get_context()
        assert retrieved is None

    def test_nested_contexts(self) -> None:
        """Test nesting context managers."""
        ctx1 = AgentContext(request_id="req-1")
        ctx2 = AgentContext(request_id="req-2")

        with ctx1:
            assert get_context().request_id == "req-1"

            with ctx2:
                assert get_context().request_id == "req-2"

            # Back to ctx1
            assert get_context().request_id == "req-1"


class TestContextFields:
    """Test context field values."""

    def test_context_with_workflow_stage(self) -> None:
        """Test context tracks workflow stage."""
        stages = [
            "migration_planning",
            "schema_analysis",
            "migration_up",
            "migration_down",
            "verification",
        ]

        for stage in stages:
            ctx = AgentContext(request_id="req-1", workflow_stage=stage)
            assert ctx.workflow_stage == stage

    def test_context_with_operation_type(self) -> None:
        """Test context tracks operation type."""
        operations = [
            "apply_migration",
            "rollback_migration",
            "build_schema",
            "sync_data",
            "diff_schema",
        ]

        for op in operations:
            ctx = AgentContext(request_id="req-1", operation_type=op)
            assert ctx.operation_type == op

    def test_context_with_custom_data(self) -> None:
        """Test storing custom data in context."""
        custom = {"version": "001", "table_count": 5, "tags": ["test", "prod"]}
        ctx = AgentContext(request_id="req-1", custom_data=custom)

        assert ctx.custom_data == custom
        assert ctx.custom_data["version"] == "001"


class TestContextSerialization:
    """Test context serialization."""

    def test_context_to_dict(self) -> None:
        """Test converting context to dict."""
        ctx = AgentContext(
            request_id="req-123",
            workflow_stage="migration_up",
            operation_type="apply_migration",
            custom_data={"version": "001"},
        )

        data = ctx.to_dict()

        assert data["request_id"] == "req-123"
        assert data["workflow_stage"] == "migration_up"
        assert data["operation_type"] == "apply_migration"
        assert data["custom_data"] == {"version": "001"}

    def test_context_to_dict_with_none_values(self) -> None:
        """Test to_dict with None values."""
        ctx = AgentContext(request_id="req-123")

        data = ctx.to_dict()

        assert data["request_id"] == "req-123"
        # None values should be in dict
        assert "workflow_stage" in data
        assert data["workflow_stage"] is None


class TestContextCloning:
    """Test context cloning for parallel operations."""

    def test_clone_context(self) -> None:
        """Test cloning a context."""
        ctx1 = AgentContext(
            request_id="req-123",
            workflow_stage="migration_up",
            custom_data={"version": "001"},
        )

        ctx2 = ctx1.clone()

        assert ctx2.request_id == ctx1.request_id
        assert ctx2.workflow_stage == ctx1.workflow_stage
        assert ctx2.custom_data == ctx1.custom_data

    def test_clone_is_independent(self) -> None:
        """Test that cloned context is independent."""
        ctx1 = AgentContext(request_id="req-123", custom_data={"key": "value"})
        ctx2 = ctx1.clone()

        # Modify clone's custom_data
        ctx2.custom_data["key"] = "modified"

        # Original should be unchanged
        assert ctx1.custom_data["key"] == "value"
